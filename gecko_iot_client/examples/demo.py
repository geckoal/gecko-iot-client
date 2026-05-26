#!/usr/bin/env python3
"""
Demo script for GeckoIotClient
"""

import logging
import os
import sys
import time

# Add the src directory to the Python path so we can import our package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gecko_iot_client import GeckoIotClient  # noqa: E402
from gecko_iot_client.models.abstract_zone import ZoneType  # noqa: E402
from gecko_iot_client.models.lighting_zone import LightingZone  # noqa: E402
from gecko_iot_client.transporters.mqtt import MqttTransporter  # noqa: E402

# Setup logging to see what's happening
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def create_zone_change_logger(zone_name: str):
    """Create a logging callback for zone changes"""

    def log_change(attribute: str, old_value, new_value):
        print(f"🔄 [{zone_name}] {attribute} changed: {old_value} -> {new_value}")

    return log_change


def on_zones_updated(zones_dict):
    """Callback when zones are updated from state data"""
    print("\n🎉 ZONES UPDATED FROM STATE DATA!")
    print("=" * 50)
    for zone_type, zone_list in zones_dict.items():
        print(f"\n📍 Zone Type: {zone_type.value.upper()}")
        for zone in zone_list:
            print(f"   • {zone.name} (ID: {zone.id})")

            # Show specific state for each zone type
            if zone_type == ZoneType.FLOW_ZONE:
                state = zone.get_flow_state()
                print(
                    f"     Flow State: Active={state['active']}, Speed={state['speed']}%"
                )
            elif zone_type == ZoneType.LIGHTING_ZONE:
                state = zone.get_lighting_state()
                color = state.get("color")
                if color:
                    print(
                        f"     Light State: Active={state['active']}, Color=RGB({color['r']},{color['g']},{color['b']})"
                    )
                else:
                    print(f"     Light State: Active={state['active']}, No Color Set")
            elif zone_type == ZoneType.TEMPERATURE_CONTROL_ZONE:
                print(
                    f"     Temp State: Current={zone.temperature}°C, "
                    f"Target={zone.target_temperature}°C, Status={zone.status}"
                )
    print("=" * 50)


def main():
    """Main demo function"""
    print("Creating MQTT transporter...")
    websocket_url = (
        "wss://a28a28s8rcruem-ats.iot.us-east-1.amazonaws.com/mqtt"
        "?x-amz-customauthorizer-name=ThirdPartyMqttCustomAuthorizer"
        "&token=111111119&x-amz-customauthorizer-signature=2222222"
    )
    transporter = MqttTransporter(websocket_url, "24002a002")

    print("Creating GeckoIotClient...")
    client = GeckoIotClient(idd="24002a002", transporter=transporter)

    # Register callback for zone updates
    client.on_zone_update(on_zones_updated)

    print(f"Client created with ID: {client.id}")

    with client:
        print("Client is connected and running.")
        # Register zone callbacks after zones are loaded
        print("\n📝 Registering zone change callbacks...")
        client.register_zone_callbacks(create_zone_change_logger)

        toggle_counter = 0

        while True:
            try:
                # Toggle light zone every 2 seconds
                lighting_zones = client.get_zones_by_type(ZoneType.LIGHTING_ZONE)
                if lighting_zones:
                    light_zone = lighting_zones[0]
                    toggle_counter += 1

                    if isinstance(light_zone, LightingZone):
                        current_active = light_zone.active or False
                        new_active = not current_active

                        status = "ON" if new_active else "OFF"
                        print(
                            f"\n💡 [{toggle_counter}] Turning light {status}: {light_zone.name}"
                        )
                        if new_active:
                            light_zone.activate()
                        else:
                            light_zone.deactivate()
                    else:
                        print(
                            f"\n⚠️  [{toggle_counter}] Zone is not a LightingZone instance"
                        )
                else:
                    print(f"\n⚠️  [{toggle_counter}] No lighting zones found to toggle")

                time.sleep(2)

            except KeyboardInterrupt:
                print("\n👋 Demo interrupted by user.")
                break

        print("Demo completed. Check logs above for any config responses.")


if __name__ == "__main__":
    main()
