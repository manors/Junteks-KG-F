# Junteks KG-F Coulomb Meter (Home Assistant Integration)

Home Assistant custom integration for **Junteks KG-F series** (KG110F / KG140F / KG160F, etc.) Bluetooth battery coulomb meters, designed to work seamlessly with **ESP32 Bluetooth Proxy** (ESPHome) or local Bluetooth adapters.

## Features

- **Auto Discovery**: Automatically discovers nearby `BTG*` / `FFF0` Junteks BLE devices via Home Assistant Bluetooth / ESP32 Bluetooth Proxy.
- **Dual Protocol Support**:
  - **Binary BCD Protocol** (default, active push from newer firmware)
  - **ASCII RS485 Passthrough Protocol** (automatic fallback for older firmware)
- **Sensors**:
  - Voltage (V), Current (A, `+` charging / `-` discharging), Power (W, `+` charging / `-` discharging)
  - Battery Level / SOC (%), Remaining Capacity (Ah), Preset Capacity (Ah)
  - Cumulative Capacity (Ah), Energy (kWh)
  - External Temperature (°C)
  - Runtime (s), Remaining Time (min), Internal Resistance (mΩ)
  - Output / Protection State (`ON`, `OFF`, `OVP`, `OCP`, `LVP`, `NCP`, `OPP`, `OTP`)
  - Current Direction (`charging`, `discharging`, `idle`)
  - Protection & Extended Diagnostics (`OVP`, `LVP`, `OCP`, `NCP`, `OPP`, `OTP`, `LTP`, revert/delay time, relay mode, full/low voltage, full current ratio, detect time, device address, protocol mode)
- **Controls**:
  - Output & Data Recording Switch
  - Zero Current Button
  - Clear Accumulated Data Button

## Installation

### Via HACS (Custom Repository)

1. Open **HACS** -> **Integrations** -> three-dots menu -> **Custom repositories**.
2. Add this repository URL with category **Integration**.
3. Search for **Junteks KG-F Coulomb Meter** and download it.
4. Restart Home Assistant.

### Manual Installation

1. Copy `custom_components/junteks_kg_f` into your Home Assistant `<config>/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings -> Devices & Services -> Add Integration** and search for **Junteks KG-F Coulomb Meter**.
