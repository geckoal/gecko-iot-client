"""
Unit tests for the MQTT keep-alive handed to the native client.

The awsiot builder silently drops keyword arguments it does not know, so
these tests run the real builder and check the options the awscrt client
is actually constructed with.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Add src to path for direct imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from awscrt import mqtt5  # noqa: E402

from gecko_iot_client.transporters.mqtt.client import MqttClient  # noqa: E402

BROKER_URL = (
    "wss://example.invalid/mqtt?x-amz-customauthorizer-name=authorizer"
    "&token=token&x-amz-customauthorizer-signature=signature"
)


class TestMqttKeepAlive(unittest.TestCase):
    """The connection must not run on the builder's 1200 s default."""

    def _connect_options(self):
        seen = {}

        def capture(client_options):
            seen["options"] = client_options
            return Mock()

        client = MqttClient()
        with patch.object(mqtt5, "Client", side_effect=capture), patch.object(
            MqttClient, "_wait_for_connection", return_value=True
        ):
            client.connect(BROKER_URL, "client-id")
        return seen["options"]

    def test_keep_alive_reaches_the_native_client(self):
        options = self._connect_options()
        self.assertEqual(options.connect_options.keep_alive_interval_sec, 60)

    def test_keep_alive_exceeds_the_ping_timeout(self):
        options = self._connect_options()
        self.assertEqual(options.ping_timeout_ms, 10_000)
        self.assertGreater(
            options.connect_options.keep_alive_interval_sec * 1000,
            options.ping_timeout_ms,
        )


if __name__ == "__main__":
    unittest.main()
