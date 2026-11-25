"""The Junteks KG-F Coulomb Meter integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ASCII_CMD_READ_INFO,
    ASCII_CMD_READ_MEASUREMENT,
    ASCII_CMD_READ_SETTINGS,
    CHAR_NOTIFY_UUID,
    CHAR_WRITE_UUID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HANDSHAKE_CMD_BINARY,
)
from .protocol import JunteksData, JunteksProtocolParser

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Junteks KG-F from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    scan_interval: int = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
    )
    coordinator = JunteksCoordinator(hass, address, scan_interval)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await coordinator.async_shutdown()
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Update coordinator interval when options change without reconnecting."""
    coordinator: JunteksCoordinator = hass.data[DOMAIN][entry.entry_id]
    scan_interval: int = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
    )
    coordinator.set_scan_interval(scan_interval)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: JunteksCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


class JunteksCoordinator(DataUpdateCoordinator[JunteksData]):
    """Manage BLE connection and data parsing for Junteks KG-F."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{address}",
            update_interval=timedelta(seconds=max(10, scan_interval)),
        )
        self.address = address
        self.parser = JunteksProtocolParser()
        self._client: BleakClient | None = None
        self._connect_lock = asyncio.Lock()
        self._rx_event = asyncio.Event()
        self._min_push_interval = scan_interval
        self._last_push_time = 0.0

    def set_scan_interval(self, scan_interval: int) -> None:
        """Update the minimum state push / poll interval in seconds."""
        self._min_push_interval = scan_interval
        self.update_interval = timedelta(seconds=max(10, scan_interval))
        _LOGGER.debug("Updated scan_interval to %ss", scan_interval)

    @callback
    def _on_disconnected(self, client: BleakClient) -> None:
        """Handle BLE disconnection."""
        _LOGGER.warning("Disconnected from Junteks KG-F (%s)", self.address)
        self._client = None

    @callback
    def _on_notify(self, _sender: int, data: bytearray) -> None:
        """Handle incoming BLE notifications from FFF1."""
        events = self.parser.feed(bytes(data))
        if events:
            self._rx_event.set()
            now = time.monotonic()
            if now - self._last_push_time >= self._min_push_interval:
                self._last_push_time = now
                self.async_set_updated_data(self.parser.data)

    async def _ensure_connected(self) -> BleakClient:
        """Ensure BLE connection is active and notifications are subscribed."""
        if self._client and self._client.is_connected:
            return self._client

        async with self._connect_lock:
            if self._client and self._client.is_connected:
                return self._client

            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if not ble_device:
                raise UpdateFailed(
                    f"Device {self.address} not found via Bluetooth/ESP32 Proxy"
                )

            _LOGGER.debug("Connecting to Junteks KG-F at %s", self.address)
            client = await establish_connection(
                BleakClient,
                ble_device,
                self.address,
                disconnected_callback=self._on_disconnected,
            )

            try:
                await client.start_notify(CHAR_NOTIFY_UUID, self._on_notify)
                _LOGGER.debug("Subscribed to notify characteristic %s", CHAR_NOTIFY_UUID)
                await asyncio.sleep(0.5)

                self._rx_event.clear()
                _LOGGER.debug(
                    "Sending binary handshake: %s",
                    HANDSHAKE_CMD_BINARY.hex(" ").upper(),
                )
                await client.write_gatt_char(
                    CHAR_WRITE_UUID, HANDSHAKE_CMD_BINARY, response=False
                )

                # Wait briefly to see if device responds in binary mode
                try:
                    await asyncio.wait_for(self._rx_event.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    _LOGGER.info(
                        "No binary response within 3s from %s; probing ASCII RS485 protocol",
                        self.address,
                    )
                    for cmd in (
                        ASCII_CMD_READ_INFO,
                        ASCII_CMD_READ_SETTINGS,
                        ASCII_CMD_READ_MEASUREMENT,
                    ):
                        await client.write_gatt_char(
                            CHAR_WRITE_UUID, cmd, response=False
                        )
                        await asyncio.sleep(0.25)

                    try:
                        await asyncio.wait_for(self._rx_event.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        _LOGGER.warning(
                            "Connected to %s but received no valid frames yet",
                            self.address,
                        )
            except Exception:
                await client.disconnect()
                raise

            self._client = client
            return client

    async def _async_update_data(self) -> JunteksData:
        """Keep connection alive and poll if in ASCII mode."""
        try:
            client = await self._ensure_connected()
            if self.parser.data.protocol_mode == "ascii":
                await client.write_gatt_char(
                    CHAR_WRITE_UUID, ASCII_CMD_READ_MEASUREMENT, response=False
                )
                await asyncio.sleep(0.3)
        except (BleakError, TimeoutError, OSError) as err:
            self._client = None
            raise UpdateFailed(f"BLE communication error: {err}") from err

        return self.parser.data

    async def async_send_command(self, binary_cmd: bytes, ascii_cmd: bytes) -> None:
        """Send a control command to the device using the active protocol."""
        client = await self._ensure_connected()
        cmd = (
            ascii_cmd
            if self.parser.data.protocol_mode == "ascii"
            else binary_cmd
        )
        _LOGGER.debug("BLE TX (%d bytes): %s", len(cmd), cmd.hex(" ").upper())
        self._last_push_time = 0.0
        await client.write_gatt_char(CHAR_WRITE_UUID, cmd, response=False)
        await asyncio.sleep(0.2)
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Disconnect cleanly on unload."""
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(CHAR_NOTIFY_UUID)
            except BleakError:
                pass
            await self._client.disconnect()
        self._client = None
