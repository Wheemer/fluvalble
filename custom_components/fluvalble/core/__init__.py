"""Constants for the Fluval Aquarium LED integration."""

DOMAIN = "fluvalble"

# Options flow keys / defaults
CONF_PING_INTERVAL = "ping_interval"
CONF_ACTIVE_TIME = "active_time"
CONF_LAMP_PROFILE = "lamp_profile"
CONF_WIRE_DIALECT = "wire_dialect"
CONF_CHANNEL_ENDIAN = "channel_endian"
DEFAULT_PING_INTERVAL = 10  # seconds between keep-alive reads
DEFAULT_ACTIVE_TIME = 0  # 0 = keep GATT connected permanently; else seconds after last command
DEFAULT_LAMP_PROFILE = "auto"
DEFAULT_WIRE_DIALECT = "random"

# Classic-BLE framing choices. ``random`` is FluvalConnect's OLD-light
# EncodeUtil.encodeMessage path; the others remain available for older forks.
WIRE_DIALECT_RANDOM = "random"
WIRE_DIALECT_XOR_0E = "xor_0e"
WIRE_DIALECT_RAND0 = "rand0"
WIRE_DIALECTS = (
    WIRE_DIALECT_RANDOM,
    WIRE_DIALECT_XOR_0E,
    WIRE_DIALECT_RAND0,
)

# Lamp profile options (options flow + channel layout)
LAMP_PROFILE_AUTO = "auto"
LAMP_PROFILE_PLANT = "plant"
LAMP_PROFILE_AQUASKY = "aquasky"
LAMP_PROFILE_AQUASKY3 = "aquasky3"
LAMP_PROFILES = (
    LAMP_PROFILE_AUTO,
    LAMP_PROFILE_PLANT,
    LAMP_PROFILE_AQUASKY,
    LAMP_PROFILE_AQUASKY3,
)

# ---------------------------------------------------------------------------
# BLE command protocol
# ---------------------------------------------------------------------------
# Every outbound command starts with CMD_HEADER followed by a command byte.
# Reverse-engineered from the Fluval Plant 3.0 ("Planted Tank") protocol.
CMD_HEADER = 0x68
CMD_MODE = 0x02  # followed by mode byte: 0=manual, 1=automatic, 2=professional
CMD_SWITCH = 0x03  # followed by 0x01 (on) / 0x00 (off)
CMD_BRIGHTNESS = 0x04  # followed by per-channel BE uint16 (progress*10); see OldLightKxtKt
CMD_STATUS = 0x05  # request current state (no payload)
CMD_CLOCK = 0x0E  # sync RTC: Y M D W h m s
