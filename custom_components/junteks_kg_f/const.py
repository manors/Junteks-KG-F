"""Constants for the Junteks KG-F Coulomb Meter integration."""

DOMAIN = "junteks_kg_f"

# BLE GATT UUIDs from MainActivity.java
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
CHAR_WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

# Handshake bytes sent onDescriptorWrite in MainActivity.java:
# new byte[]{-69, -102, -87, 16, -18} -> BB 9A A9 10 EE
HANDSHAKE_CMD_BINARY = bytes([0xBB, 0x9A, 0xA9, 0x10, 0xEE])

# Fallback ASCII commands if device uses RS485 passthrough text protocol
ASCII_CMD_READ_INFO = b":R00=1,2,1,\r\n"
ASCII_CMD_READ_SETTINGS = b":R51=1,2,1,\r\n"
ASCII_CMD_READ_MEASUREMENT = b":R50=1,2,1,\r\n"

CONF_ADDRESS = "address"
CONF_DEVICE_ADDR = "device_address"
DEFAULT_DEVICE_ADDR = 1

# Output / protection state mapping (Tag 0xD0 / :r50[10])
OUTPUT_STATES = {
    0: "ON",
    1: "OVP",
    2: "OCP",
    3: "LVP",
    4: "NCP",
    5: "OPP",
    6: "OTP",
    99: "OFF",
}

# Current direction mapping (Tag 0xD1 / :r50[11])
CURRENT_DIRECTIONS = {
    0: "forward",
    1: "reverse",
}
