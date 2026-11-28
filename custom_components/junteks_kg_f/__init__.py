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
    CONF_KEEP_CONNECTED,
    CONF_SCAN_INTERVAL,
    DEFAULT_KEEP_CONNECTED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HANDSHAKE_CMD_BINARY,
    MIN_SHORT_CONN_INTERVAL,
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
    keep_connected: bool = entry.options.get(
        CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED
    )
    coordinator = JunteksCoordinator(hass, address, scan_interval, keep_connected)

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
    """Update coordinator options when changed."""
    coordinator: JunteksCoordinator = hass.data[DOMAIN][entry.entry_id]
    scan_interval: int = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
    )
    keep_connected: bool = entry.options.get(
        CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED
    )
    await coordinator.async_set_options(scan_interval, keep_connected)


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
        keep_connected: bool = DEFAULT_KEEP_CONNECTED,
    ) -> None:
        effective_interval = (
            scan_interval
            if keep_connected
            else max(MIN_SHORT_CONN_INTERVAL, scan_interval)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{address}",
            update_interval=timedelta(seconds=effective_interval),
        )
        self.address = address
        self.parser = JunteksProtocolParser()
        self._client: BleakClient | None = None
        self._connect_lock = asyncio.Lock()
        self._rx_event = asyncio.Event()
        self._keep_connected = keep_connected
        self._min_push_interval = scan_interval
        self._last_push_time = 0.0
        self._consecutive_failures = 0

    async def async_set_options(
        self, scan_interval: int, keep_connected: bool
    ) -> None:
        """Update scan interval and connection mode."""
        self._min_push_interval = scan_interval
        self._keep_connected = keep_connected
        effective_interval = (
            scan_interval
            if keep_connected
            else max(MIN_SHORT_CONN_INTERVAL, scan_interval)
        )
        self.update_interval = timedelta(seconds=effective_interval)
        _LOGGER.debug(
            "Updated options: scan_interval=%ss, keep_connected=%s",
            effective_interval,
            keep_connected,
        )
        if not keep_connected:
            await self.async_shutdown()
        else:
            await self.async_request_refresh()

    @callback
    def _on_disconnected(self, client: BleakClient) -> None:
        """Handle BLE disconnection."""
        if self._keep_connected:
            _LOGGER.warning("Disconnected from Junteks KG-F (%s)", self.address)
        else:
            _LOGGER.debug("Disconnected from Junteks KG-F (%s)", self.address)
        self._client = None

    @callback
    def _on_notify(self, _sender: int, data: bytearray) -> None:
        """Handle incoming BLE notifications from FFF1."""
        events = self.parser.feed(bytes(data))
        if events:
            self._rx_event.set()
            if self._keep_connected:
                now = time.monotonic()
                if now - self._last_push_time >= self._min_push_interval:
                    self._last_push_time = now
                    self.async_set_updated_data(self.parser.data)

    async def _connect_and_handshake(self) -> BleakClient:
        """Connect to device, subscribe to notifications, and send handshake."""
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
            await asyncio.sleep(0.3)

            self._rx_event.clear()
            if self.parser.data.protocol_mode == "ascii":
                for cmd in (ASCII_CMD_READ_SETTINGS, ASCII_CMD_READ_MEASUREMENT):
                    await client.write_gatt_char(
                        CHAR_WRITE_UUID, cmd, response=False
                    )
                    await asyncio.sleep(0.2)
            else:
                _LOGGER.debug(
                    "Sending binary handshake: %s",
                    HANDSHAKE_CMD_BINARY.hex(" ").upper(),
                )
                await client.write_gatt_char(
                    CHAR_WRITE_UUID, HANDSHAKE_CMD_BINARY, response=False
                )

            try:
                await asyncio.wait_for(self._rx_event.wait(), timeout=2.5)
                # Give device a brief window to finish multi-packet telemetry/settings
                await asyncio.sleep(0.35)
            except asyncio.TimeoutError:
                if self.parser.data.protocol_mode == "unknown":
                    _LOGGER.info(
                        "No binary response within 2.5s from %s; probing ASCII RS485 protocol",
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
                        await asyncio.wait_for(self._rx_event.wait(), timeout=2.5)
                        await asyncio.sleep(0.35)
                    except asyncio.TimeoutError:
                        _LOGGER.warning(
                            "Connected to %s but received no valid frames",
                            self.address,
                        )
        except BaseException:
            await self._safe_disconnect(client)
            raise

        return client

    async def _safe_disconnect(self, client: BleakClient | None) -> None:
        """Disconnect safely and ensure BLE slot is released."""
        if not client:
            return
        try:
            _LOGGER.debug(
                "Releasing BLE connection to %s (is_connected=%s)",
                self.address,
                client.is_connected,
            )
            await asyncio.wait_for(client.disconnect(), timeout=5.0)
            _LOGGER.debug(
                "BLE connection released for %s (is_connected=%s)",
                self.address,
                client.is_connected,
            )
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.debug("Error during disconnect from %s: %s", self.address, err)

    async def _async_update_data(self) -> JunteksData:
        """Fetch data using on-demand short connection or keep-alive connection."""
        async with self._connect_lock:
            if self._keep_connected:
                try:
                    if not (self._client and self._client.is_connected):
                        self._client = await self._connect_and_handshake()
                    elif self.parser.data.protocol_mode == "ascii":
                        await self._client.write_gatt_char(
                            CHAR_WRITE_UUID,
                            ASCII_CMD_READ_MEASUREMENT,
                            response=False,
                        )
                        await asyncio.sleep(0.3)
                    self._consecutive_failures = 0
                except (BleakError, TimeoutError, OSError, UpdateFailed) as err:
                    self._client = None
                    raise UpdateFailed(f"BLE communication error: {err}") from err
                return self.parser.data

            # Short-connection (on-demand) mode: connect -> fetch -> disconnect immediately
            client: BleakClient | None = None
            try:
                client = await self._connect_and_handshake()
                self._consecutive_failures = 0
            except (BleakError, TimeoutError, OSError, UpdateFailed) as err:
                self._consecutive_failures += 1
                # Allow temporary failures (e.g. phone app is currently connected)
                # without turning entities unavailable immediately.
                if (
                    self.parser.data.protocol_mode != "unknown"
                    and self._consecutive_failures < 3
                ):
                    _LOGGER.warning(
                        "Unable to connect to %s (attempt %d/3, possibly in use by another device): %s",
                        self.address,
                        self._consecutive_failures,
                        err,
                    )
                    return self.parser.data
                raise UpdateFailed(f"BLE communication error: {err}") from err
            finally:
                await self._safe_disconnect(client)
                self._client = None

        return self.parser.data

    async def async_send_command(self, binary_cmd: bytes, ascii_cmd: bytes) -> None:
        """Send a control command to the device and release connection if short-conn mode."""
        cmd = (
            ascii_cmd
            if self.parser.data.protocol_mode == "ascii"
            else binary_cmd
        )
        _LOGGER.debug("BLE TX (%d bytes): %s", len(cmd), cmd.hex(" ").upper())

        async with self._connect_lock:
            if self._keep_connected:
                if not (self._client and self._client.is_connected):
                    self._client = await self._connect_and_handshake()
                self._last_push_time = 0.0
                await self._client.write_gatt_char(
                    CHAR_WRITE_UUID, cmd, response=False
                )
                await asyncio.sleep(0.4)
                self.async_set_updated_data(self.parser.data)
                return

            client: BleakClient | None = None
            try:
                client = await self._connect_and_handshake()
                self._rx_event.clear()
                await client.write_gatt_char(CHAR_WRITE_UUID, cmd, response=False)
                await asyncio.sleep(0.5)
                self.async_set_updated_data(self.parser.data)
            finally:
                await self._safe_disconnect(client)
                self._client = None

    async def async_shutdown(self) -> None:
        """Disconnect cleanly on unload."""
        await self._safe_disconnect(self._client)
        self._client = None
