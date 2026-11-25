"""Protocol parser for Junteks KG-F Coulomb Meter (Binary BCD & ASCII RS485)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .const import CURRENT_DIRECTIONS, OUTPUT_STATES

_LOGGER = logging.getLogger(__name__)


def bcd_byte_to_dec(byte_val: int) -> int:
    """Convert a single BCD byte (e.g. 0x25) to decimal (25)."""
    return ((byte_val >> 4) & 0x0F) * 10 + (byte_val & 0x0F)


def dec_to_bcd_byte(dec_val: int) -> int:
    """Convert a 0-99 decimal value to a BCD byte (e.g. 16 -> 0x16)."""
    return ((dec_val // 10) << 4) | (dec_val % 10)


def int_to_bcd_bytes(val: int) -> bytes:
    """Convert a non-negative integer to big-endian BCD bytes (2 digits per byte)."""
    if val <= 0:
        return b"\x00"
    parts: list[int] = []
    while val > 0:
        parts.append(dec_to_bcd_byte(val % 100))
        val //= 100
    parts.reverse()
    return bytes(parts)


def build_binary_command(value: int, tag: int) -> bytes:
    """Build a binary BCD write command frame: [0xBB, BCD(value), tag, chk, 0xEE]."""
    body = bytes([0xBB]) + int_to_bcd_bytes(value) + bytes([tag])
    chk = dec_to_bcd_byte(sum(body) % 100)
    return body + bytes([chk, 0xEE])


@dataclass
class JunteksData:
    """Parsed data state from the Junteks KG-F meter."""

    protocol_mode: str = "unknown"  # "binary" or "ascii"
    model: str | None = None
    firmware_version: float | None = None
    serial_number: int | None = None
    device_address: int | None = None

    voltage_v: float | None = None
    current_a: float | None = None
    current_abs_a: float | None = None
    power_w: float | None = None
    power_abs_w: float | None = None

    remaining_capacity_ah: float | None = None
    preset_capacity_ah: float | None = None
    soc_percent: float | None = None
    cumulative_capacity_ah: float | None = None
    energy_kwh: float | None = None

    temperature_c: float | None = None
    runtime_s: int | None = None
    remaining_time_min: int | None = None
    internal_resistance_mohm: float | None = None

    output_state_code: int | None = None
    output_state: str | None = None
    direction_code: int | None = None
    direction: str | None = None

    # Protection & extended settings
    ovp_v: float | None = None
    lvp_v: float | None = None
    ocp_a: float | None = None
    ncp_a: float | None = None
    opp_w: float | None = None
    otp_c: int | None = None
    ltp_c: int | None = None
    protect_revert_time_s: int | None = None
    delay_time_s: int | None = None
    relay_mode: str | None = None
    full_voltage_v: float | None = None
    low_voltage_v: float | None = None
    full_current_pct: float | None = None
    detect_time_min: float | None = None

    last_raw_hex: str | None = None
    extra_tags: dict[int, int] = field(default_factory=dict)

    def update_derived(self) -> None:
        """Update derived fields such as SOC, signed current/power, and direction."""
        # Charging (direction_code == 1) is positive; discharging (direction_code == 0) is negative.
        if self.current_abs_a is not None:
            if self.current_abs_a == 0:
                self.current_a = 0.0
                self.direction = "idle"
            elif self.direction_code == 1:
                self.current_a = self.current_abs_a
                self.direction = "charging"
            elif self.direction_code == 0:
                self.current_a = -self.current_abs_a
                self.direction = "discharging"
            else:
                self.current_a = self.current_abs_a

        if self.power_abs_w is not None:
            if self.current_abs_a == 0 or self.power_abs_w == 0:
                self.power_w = 0.0
            elif self.direction_code == 1:
                self.power_w = self.power_abs_w
            elif self.direction_code == 0:
                self.power_w = -self.power_abs_w
            else:
                self.power_w = self.power_abs_w

        if (
            self.remaining_capacity_ah is not None
            and self.preset_capacity_ah is not None
            and self.preset_capacity_ah > 0
        ):
            soc = (self.remaining_capacity_ah / self.preset_capacity_ah) * 100.0
            self.soc_percent = round(max(0.0, min(100.0, soc)), 1)


class JunteksProtocolParser:
    """Stateful stream parser handling both Binary BCD (0xEE) and ASCII (:rXX=) frames."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.data = JunteksData()

    def feed(self, chunk: bytes) -> list[str]:
        """Feed incoming BLE notification bytes and return list of parsed frame types."""
        _LOGGER.debug("BLE RX (%d bytes): %s", len(chunk), chunk.hex(" ").upper())
        self._buf.extend(chunk)
        parsed_events: list[str] = []

        # Guard against unbounded buffer growth on noise
        if len(self._buf) > 4096:
            _LOGGER.warning("Buffer overflow (%d bytes), clearing", len(self._buf))
            self._buf.clear()
            return parsed_events

        while True:
            # Check for Binary BCD frame terminator (0xEE)
            ee_idx = self._buf.find(b"\xee")
            # Check for ASCII frame terminator (\r\n)
            crlf_idx = self._buf.find(b"\r\n")

            # Decide which frame comes first if any
            if ee_idx != -1 and (crlf_idx == -1 or ee_idx < crlf_idx):
                # Ensure it's not an ASCII frame accidentally containing 0xEE (unlikely in UTF-8/ASCII)
                if self._buf.lstrip()[:1] == b":" and crlf_idx != -1:
                    frame_bytes = bytes(self._buf[: crlf_idx + 2])
                    del self._buf[: crlf_idx + 2]
                    if ev := self._parse_ascii_frame(frame_bytes):
                        parsed_events.append(ev)
                    continue

                frame_bytes = bytes(self._buf[: ee_idx + 1])
                del self._buf[: ee_idx + 1]
                if ev := self._parse_binary_frame(frame_bytes):
                    parsed_events.append(ev)
                continue

            if crlf_idx != -1:
                frame_bytes = bytes(self._buf[: crlf_idx + 2])
                del self._buf[: crlf_idx + 2]
                if ev := self._parse_ascii_frame(frame_bytes):
                    parsed_events.append(ev)
                continue

            break

        return parsed_events

    def _parse_binary_frame(self, frame: bytes) -> str | None:
        """Parse a binary BCD frame ending with 0xEE."""
        if len(frame) < 3:
            _LOGGER.debug("Ignoring short binary frame: %s", frame.hex(" ").upper())
            return None

        checksum_calc = dec_to_bcd_byte(sum(frame[:-2]) % 100)
        checksum_recv = frame[-2]

        # MainActivity.java accepts matching BCD checksum or 12 (0x0C)
        if checksum_recv != checksum_calc and checksum_recv != 0x0C:
            _LOGGER.debug(
                "Binary checksum mismatch: calc=0x%02X recv=0x%02X frame=%s",
                checksum_calc,
                checksum_recv,
                frame.hex(" ").upper(),
            )
            return None

        self.data.protocol_mode = "binary"
        self.data.last_raw_hex = frame.hex(" ").upper()

        # 0xAA (170) indicates offline curve history data
        if frame[0] == 0xAA:
            _LOGGER.debug("Received history curve binary frame (%d bytes)", len(frame))
            return "binary_curve"

        # Normal telemetry/settings frame: strip frame[0] and trailing [checksum, 0xEE]
        payload = frame[1:-2]
        val = 0
        tags_parsed: list[tuple[int, int]] = []

        for b in payload:
            if b >= 0xA0:  # >= 160 is a Tag
                self._apply_binary_tag(b, val)
                tags_parsed.append((b, val))
                val = 0
            else:
                val = val * 100 + bcd_byte_to_dec(b)

        self.data.update_derived()
        _LOGGER.debug("Parsed binary tags: %s", [(hex(t), v) for t, v in tags_parsed])
        return "binary_telemetry"

    def _apply_binary_tag(self, tag: int, val: int) -> None:
        """Apply a single parsed (tag, val) pair from binary BCD protocol."""
        d = self.data
        if tag == 176:  # 0xB0: Preset battery capacity
            d.preset_capacity_ah = val / 10.0
        elif tag == 177:  # 0xB1: Over-temperature protection
            otp = val - 100
            d.otp_c = None if otp < -20 else otp
        elif tag == 183:  # 0xB7: Relay mode (0=NO, 1=NC)
            d.relay_mode = "normally_closed" if val == 1 else "normally_open"
        elif tag == 192:  # 0xC0: Voltage
            d.voltage_v = val / 100.0
        elif tag == 193:  # 0xC1: Current
            d.current_abs_a = val / 100.0
        elif tag == 194:  # 0xC2: Delay time (s)
            d.delay_time_s = val
        elif tag == 195:  # 0xC3: Protection revert time (s)
            d.protect_revert_time_s = val
        elif tag == 196:  # 0xC4: Address
            d.device_address = val
        elif tag == 197:  # 0xC5: OVP
            d.ovp_v = val / 100.0
        elif tag == 198:  # 0xC6: LVP
            d.lvp_v = val / 100.0
        elif tag == 199:  # 0xC7: OCP
            d.ocp_a = val / 100.0
        elif tag == 200:  # 0xC8: NCP
            d.ncp_a = val / 100.0
        elif tag == 201:  # 0xC9: OPP
            d.opp_w = val / 100.0
        elif tag == 208:  # 0xD0: Output / protection state
            d.output_state_code = val
            d.output_state = OUTPUT_STATES.get(val, f"UNKNOWN({val})")
        elif tag == 209:  # 0xD1: Current direction
            d.direction_code = val
            d.direction = CURRENT_DIRECTIONS.get(val, f"unknown({val})")
        elif tag == 210:  # 0xD2: Remaining capacity
            d.remaining_capacity_ah = val / 1000.0
        elif tag == 211:  # 0xD3: Cumulative capacity
            d.cumulative_capacity_ah = val / 1000.0
        elif tag == 212:  # 0xD4: Cumulative energy (kWh)
            d.energy_kwh = val / 100000.0
        elif tag == 213:  # 0xD5: Runtime (s)
            d.runtime_s = val
        elif tag == 214:  # 0xD6: Remaining time (min)
            d.remaining_time_min = val
        elif tag == 215:  # 0xD7: Battery internal resistance (mOhm)
            d.internal_resistance_mohm = val / 100.0
        elif tag == 216:  # 0xD8: Power
            d.power_abs_w = val / 100.0
        elif tag == 217:  # 0xD9: External temperature
            temp = val - 100
            d.temperature_c = None if temp < -20 else float(temp)
        elif tag == 224:  # 0xE0: Model
            series = "H" if (val // 1000) == 1 else "F"
            d.model = f"KG{val % 1000}{series}"
        elif tag == 225:  # 0xE1: Serial number (8629 = IAP)
            if val != 8629:
                d.serial_number = val
        elif tag == 226:  # 0xE2: Firmware version
            d.firmware_version = val / 100.0
        elif tag == 227:  # 0xE3: Low-temperature protection
            ltp = val - 100
            d.ltp_c = None if ltp < -20 else ltp
        elif tag == 230:  # 0xE6: Full voltage (V)
            d.full_voltage_v = val / 100.0
        elif tag == 231:  # 0xE7: Low voltage (V)
            d.low_voltage_v = val / 100.0
        elif tag == 232:  # 0xE8: Full current (%)
            d.full_current_pct = val / 10.0
        elif tag == 233:  # 0xE9: Detect time (min)
            d.detect_time_min = val / 10.0
        else:
            d.extra_tags[tag] = val

    def _parse_ascii_frame(self, frame: bytes) -> str | None:
        """Parse an ASCII RS485-style frame (e.g. :r50=...,\\r\\n)."""
        try:
            text = frame.decode("utf-8", errors="replace").strip()
        except Exception:
            return None

        if not text.startswith(":"):
            _LOGGER.debug("Ignoring non-colon ASCII line: %r", text)
            return None

        _LOGGER.debug("ASCII RX: %s", text)
        self.data.protocol_mode = "ascii"
        self.data.last_raw_hex = text

        if "=" not in text:
            return None

        cmd_part, body = text.split("=", 1)
        parts = [p for p in body.split(",") if p != ""]
        if len(parts) < 2:
            return None

        try:
            addr = int(parts[0])
            recv_chk = int(parts[1])
            vals = [int(p) for p in parts[2:]]
        except ValueError:
            _LOGGER.debug("Failed to parse numeric ASCII fields: %s", text)
            return None

        calc_chk = (sum(vals) % 255) + 1
        if recv_chk != 0 and recv_chk != calc_chk:
            _LOGGER.debug(
                "ASCII checksum mismatch: calc=%d recv=%d line=%s",
                calc_chk,
                recv_chk,
                text,
            )
            return None

        d = self.data
        d.device_address = addr
        cmd = cmd_part.lower()

        if cmd == ":r00" and len(vals) >= 3:
            model_code = vals[0]
            series = "H" if (model_code // 1000) == 1 else "F"
            d.model = f"KG{model_code % 1000}{series}"
            d.firmware_version = vals[1] / 100.0
            d.serial_number = vals[2]
            return "ascii_r00"

        if cmd == ":r50" and len(vals) >= 12:
            d.voltage_v = vals[0] / 100.0
            d.current_abs_a = vals[1] / 100.0
            d.remaining_capacity_ah = vals[2] / 1000.0
            d.cumulative_capacity_ah = vals[3] / 1000.0
            d.energy_kwh = vals[4] / 100000.0
            d.runtime_s = vals[5]
            temp = vals[6] - 100
            d.temperature_c = None if temp < -20 else float(temp)
            # vals[7] is reserved
            d.output_state_code = vals[8]
            d.output_state = OUTPUT_STATES.get(vals[8], f"UNKNOWN({vals[8]})")
            d.direction_code = vals[9]
            d.direction = CURRENT_DIRECTIONS.get(vals[9], f"unknown({vals[9]})")
            d.remaining_time_min = vals[10]
            d.internal_resistance_mohm = vals[11] / 100.0
            d.power_abs_w = round(d.voltage_v * d.current_abs_a, 2)
            d.update_derived()
            return "ascii_r50"

        if cmd == ":r51" and len(vals) >= 10:
            d.ovp_v = vals[0] / 100.0
            d.lvp_v = vals[1] / 100.0
            d.ocp_a = vals[2] / 100.0
            d.ncp_a = vals[3] / 100.0
            d.opp_w = vals[4] / 100.0
            otp = vals[5] - 100
            d.otp_c = None if otp < -20 else otp
            d.protect_revert_time_s = vals[6]
            d.delay_time_s = vals[7]
            d.preset_capacity_ah = vals[8] / 10.0
            if len(vals) >= 14:
                d.relay_mode = "normally_closed" if vals[13] == 1 else "normally_open"
            d.update_derived()
            return "ascii_r51"

        return f"ascii_{cmd[1:]}"
