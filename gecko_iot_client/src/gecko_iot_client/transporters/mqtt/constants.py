"""Constants for MQTT transporter."""

# Error messages
NOT_CONNECTED_ERROR = "Not connected"

# Token refresh
DEFAULT_TOKEN_REFRESH_BUFFER = 600  # 10 minutes before expiry (safer margin)

# Reconnection
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY = 1.0
RECONNECT_MAX_DELAY = 60.0

# Keep-alive: must exceed the ping timeout; AWS IoT accepts 30 to 1200 s
KEEP_ALIVE_INTERVAL = 60
PING_TIMEOUT_MS = 10_000

# Timeouts
SUBSCRIPTION_TIMEOUT = 5.0
CONNECTION_TIMEOUT = 10
PUBLISH_TIMEOUT = 5.0
