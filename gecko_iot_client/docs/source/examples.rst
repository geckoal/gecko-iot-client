Examples
========

This page contains practical examples for common use cases with the Gecko IoT Client.

Basic Spa Control
-----------------

A simple spa control application that manages pumps, heaters, and lights:

.. code-block:: python

   import time
   from gecko_iot_client import GeckoIotClient, ZoneType
   from gecko_iot_client.transporters.mqtt import MqttTransporter


   class SpaController:
       def __init__(self, device_id, broker_url):
           self.transporter = MqttTransporter(broker_url)
           self.client = GeckoIotClient(device_id, self.transporter)

       def start_spa_session(self):
           """Start a typical spa session"""
           with self.client as client:
               # Wait for initial configuration
               time.sleep(3)

               print("🛁 Starting spa session...")

               # Turn on circulation pump
               flow_zones = client.get_zones_by_type(ZoneType.FLOW_ZONE)
               if flow_zones:
                   circulation_pump = flow_zones[0]  # Main circulation
                   circulation_pump.set_speed_desired(100.0, active=True)
                   print(f"✓ {circulation_pump.name} activated at 100%")

               # Set comfortable temperature
               temp_zones = client.get_zones_by_type(ZoneType.TEMPERATURE_CONTROL_ZONE)
               if temp_zones:
                   heater = temp_zones[0]
                   heater.set_target_temperature_desired(38.0)  # 38°C
                   print(f"✓ {heater.name} set to 38°C")

               # Turn on mood lighting
               light_zones = client.get_zones_by_type(ZoneType.LIGHTING_ZONE)
               if light_zones:
                   mood_light = light_zones[0]
                   # Set to relaxing blue
                   mood_light.set_color_desired(50, 100, 255, active=True)
                   print(f"✓ {mood_light.name} set to relaxing blue")

               print("🌟 Spa session started! Enjoy your relaxation.")

               # Monitor session
               self._monitor_session(client, duration_minutes=30)

       def _monitor_session(self, client, duration_minutes):
           """Monitor the spa session"""
           print(f"📊 Monitoring session for {duration_minutes} minutes...")

           for minute in range(duration_minutes):
               time.sleep(60)  # Wait 1 minute

               # Check temperature progress
               temp_zones = client.get_zones_by_type(ZoneType.TEMPERATURE_CONTROL_ZONE)
               if temp_zones:
                   heater = temp_zones[0]
                   current = heater.temperature_
                   target = heater.set_point
                   if current and target:
                       print(f"🌡️  Minute {minute+1}: {current:.1f}°C (target: {target:.1f}°C)")


   # Usage
   if __name__ == "__main__":
       # WebSocket URL with embedded authentication (recommended)
       broker_url = 'wss://xyz123.iot.us-east-1.amazonaws.com/mqtt?x-amz-customauthorizer-name=YourCustomAuthorizer&token=your_auth_token&x-amz-customauthorizer-signature=your_encoded_signature'

       spa = SpaController(
           device_id="my-spa-001",
           broker_url=broker_url
       )
       spa.start_spa_session()

       # Alternative: Certificate-based authentication
       # spa_transporter = MqttTransporter()
       # spa_transporter.connect(
       #     broker_url="xyz123.iot.us-east-1.amazonaws.com",
       #     cert_filepath="certificates/device-cert.pem.crt",
       #     pri_key_filepath="certificates/device-private.pem.key",
       #     ca_filepath="certificates/AmazonRootCA1.pem"
       # )
       # spa = SpaController("my-spa-001", spa_transporter)
       # spa.start_spa_session()

Zone State Monitoring
---------------------

Monitor all zone states and log changes to a file:

.. code-block:: python

   import json
   import time
   from datetime import datetime
   from gecko_iot_client import GeckoIotClient, ZoneType
   from gecko_iot_client.transporters.mqtt import MqttTransporter


   class ZoneMonitor:
       def __init__(self, device_id, transporter, log_file="zone_changes.log"):
           self.client = GeckoIotClient(device_id, transporter)
           self.log_file = log_file

       def start_monitoring(self):
           """Start comprehensive zone monitoring"""
           with self.client as client:
               # Setup change callbacks
               self._setup_callbacks(client)

               # Wait for initial state
               time.sleep(3)

               # Log initial state
               self._log_current_state(client)

               print("🔍 Zone monitoring started. Press Ctrl+C to stop.")
               try:
                   while True:
                       time.sleep(10)  # Check every 10 seconds
                       self._periodic_check(client)
               except KeyboardInterrupt:
                   print("\n📄 Monitoring stopped. Check log file for details.")

       def _setup_callbacks(self, client):
           """Setup callbacks for zone changes"""
           def zone_change_logger(zone_name):
               def callback(attribute, old_value, new_value):
                   timestamp = datetime.now().isoformat()
                   log_entry = {
                       "timestamp": timestamp,
                       "zone": zone_name,
                       "attribute": attribute,
                       "old_value": old_value,
                       "new_value": new_value
                   }
                   self._write_log(log_entry)
                   print(f"📝 [{zone_name}] {attribute}: {old_value} → {new_value}")
               return callback

           client.register_zone_callbacks(zone_change_logger)

       def _log_current_state(self, client):
           """Log current state of all zones"""
           timestamp = datetime.now().isoformat()
           zones_state = {}

           for zone_type in ZoneType:
               zones = client.get_zones_by_type(zone_type)
               zones_state[zone_type.value] = []

               for zone in zones:
                   zone_data = {
                       "id": zone.id,
                       "name": zone.name,
                       "state": zone.model_dump()
                   }
                   zones_state[zone_type.value].append(zone_data)

           state_log = {
               "timestamp": timestamp,
               "event": "current_state",
               "zones": zones_state
           }
           self._write_log(state_log)

       def _periodic_check(self, client):
           """Perform periodic health checks"""
           flow_zones = client.get_zones_by_type(ZoneType.FLOW_ZONE)
           temp_zones = client.get_zones_by_type(ZoneType.TEMPERATURE_CONTROL_ZONE)

           # Check for any inactive pumps that should be running
           for pump in flow_zones:
               if pump.speed and pump.speed > 0 and not pump.active:
                   print(f"⚠️  Warning: {pump.name} has speed {pump.speed}% but is inactive")

           # Check temperature differential
           for heater in temp_zones:
               if heater.temperature_ and heater.set_point:
                   diff = abs(heater.temperature_ - heater.set_point)
                   if diff > 5.0:  # More than 5°C difference
                       print(f"🌡️  Note: {heater.name} is {diff:.1f}°C from target")

       def _write_log(self, log_entry):
           """Write log entry to file"""
           with open(self.log_file, "a") as f:
               f.write(json.dumps(log_entry) + "\n")

Automated Zone Control
---------------------

Implement intelligent zone control based on schedules and conditions:

.. code-block:: python

   import time
   from datetime import datetime, time as dt_time
   from gecko_iot_client import GeckoIotClient, ZoneType
   from gecko_iot_client.transporters.mqtt import MqttTransporter


   class SmartSpaController:
       def __init__(self, device_id, transporter):
           self.client = GeckoIotClient(device_id, transporter)
           self.schedules = {
               "morning": {
                   "time": dt_time(7, 0),  # 7:00 AM
                   "temperature": 36.0,
                   "lighting": {"r": 255, "g": 200, "b": 100},  # Warm light
                   "pumps": {"circulation": 80.0}
               },
               "evening": {
                   "time": dt_time(19, 0),  # 7:00 PM
                   "temperature": 38.0,
                   "lighting": {"r": 100, "g": 50, "b": 255},  # Cool blue
                   "pumps": {"circulation": 100.0}
               },
               "night": {
                   "time": dt_time(22, 0),  # 10:00 PM
                   "temperature": 34.0,
                   "lighting": {"r": 50, "g": 255, "b": 50},  # Dim green
                   "pumps": {"circulation": 60.0}
               }
           }

       def run_smart_control(self):
           """Run intelligent spa control"""
           with self.client as client:
               print("🤖 Smart spa controller started")
               time.sleep(3)  # Wait for initial state

               while True:
                   current_time = datetime.now().time()
                   schedule = self._get_current_schedule(current_time)

                   if schedule:
                       print(f"📅 Applying {schedule} schedule...")
                       self._apply_schedule(client, self.schedules[schedule])

                   # Check environmental conditions
                   self._check_conditions(client)

                   time.sleep(300)  # Check every 5 minutes

       def _get_current_schedule(self, current_time):
           """Determine which schedule should be active"""
           schedules_sorted = sorted(
               self.schedules.items(),
               key=lambda x: x[1]["time"]
           )

           for schedule_name, schedule_data in schedules_sorted:
               if current_time >= schedule_data["time"]:
                   active_schedule = schedule_name
               else:
                   break

           return active_schedule

       def _apply_schedule(self, client, schedule_config):
           """Apply a schedule configuration"""
           # Set temperature
           temp_zones = client.get_zones_by_type(ZoneType.TEMPERATURE_CONTROL_ZONE)
           if temp_zones and "temperature" in schedule_config:
               for heater in temp_zones:
                   heater.set_target_temperature_desired(schedule_config["temperature"])

           # Set lighting
           light_zones = client.get_zones_by_type(ZoneType.LIGHTING_ZONE)
           if light_zones and "lighting" in schedule_config:
               lighting = schedule_config["lighting"]
               for light in light_zones:
                   light.set_color_desired(
                       lighting["r"], lighting["g"], lighting["b"], active=True
                   )

           # Set pumps
           flow_zones = client.get_zones_by_type(ZoneType.FLOW_ZONE)
           if flow_zones and "pumps" in schedule_config:
               pumps_config = schedule_config["pumps"]
               for pump in flow_zones:
                   if "circulation" in pumps_config:
                       pump.set_speed_desired(pumps_config["circulation"], active=True)

       def _check_conditions(self, client):
           """Check for unusual conditions and respond"""
           temp_zones = client.get_zones_by_type(ZoneType.TEMPERATURE_CONTROL_ZONE)

           for heater in temp_zones:
               if heater.temperature_ and heater.set_point:
                   diff = heater.temperature_ - heater.set_point

                   # If temperature is too high, reduce pump speed
                   if diff > 2.0:
                       flow_zones = client.get_zones_by_type(ZoneType.FLOW_ZONE)
                       for pump in flow_zones:
                           if pump.speed and pump.speed > 70:
                               new_speed = max(50.0, pump.speed - 20)
                               pump.set_speed_desired(new_speed)
                               print(f"🔥 Reducing {pump.name} speed due to high temperature")

Custom Zone Callbacks
--------------------

Create sophisticated monitoring with custom callback functions:

.. code-block:: python

   from gecko_iot_client import GeckoIotClient
   from gecko_iot_client.transporters.mqtt import MqttTransporter


   def create_alert_callback(zone_name, alert_conditions):
       """Create a callback that triggers alerts based on conditions"""
       def callback(attribute, old_value, new_value):
           # Check each alert condition
           for condition in alert_conditions:
               if (attribute == condition["attribute"] and
                   condition["check"](new_value)):
                   print(f"🚨 ALERT [{zone_name}]: {condition['message']}")

                   # Could send email, SMS, etc. here
                   if "action" in condition:
                       condition["action"](new_value)

       return callback


   def temperature_too_high_action(temperature):
       """Action to take when temperature is too high"""
       print(f"🌡️  Taking action: Temperature is {temperature}°C - activating cooling measures")
       # Could trigger emergency cooling, send notifications, etc.


   # Setup alerts
   def setup_spa_alerts(client):
       # Temperature alerts
       temp_alerts = [
           {
               "attribute": "temperature_",
               "check": lambda t: t and t > 40.0,
               "message": "Temperature exceeds safe limit!",
               "action": temperature_too_high_action
           },
           {
               "attribute": "set_point",
               "check": lambda sp: sp and sp > 42.0,
               "message": "Setpoint too high - safety concern!"
           }
       ]

       # Flow alerts
       flow_alerts = [
           {
               "attribute": "speed",
               "check": lambda s: s and s < 30.0,
               "message": "Flow speed critically low!"
           },
           {
               "attribute": "active",
               "check": lambda a: a is False,
               "message": "Pump has stopped unexpectedly!"
           }
       ]

       # Register callbacks with zones
       temp_zones = client.get_zones_by_type(ZoneType.TEMPERATURE_CONTROL_ZONE)
       for zone in temp_zones:
           callback = create_alert_callback(zone.name, temp_alerts)
           zone.register_callback(callback)

       flow_zones = client.get_zones_by_type(ZoneType.FLOW_ZONE)
       for zone in flow_zones:
           callback = create_alert_callback(zone.name, flow_alerts)
           zone.register_callback(callback)

Testing and Debugging
---------------------

Utilities for testing your spa integration:

.. code-block:: python

   def test_zone_connectivity(client):
       """Test that all zones are responding"""
       print("🔧 Testing zone connectivity...")

       all_zones = []
       for zone_type in ZoneType:
           zones = client.get_zones_by_type(zone_type)
           all_zones.extend(zones)

       if not all_zones:
           print("❌ No zones found - check configuration")
           return False

       print(f"✓ Found {len(all_zones)} zones total")

       for zone in all_zones:
           # Test basic zone properties
           print(f"  📍 {zone.name} ({zone.zone_type.value})")
           print(f"    ID: {zone.id}")
           print(f"    Has state manager: {zone._state_manager is not None}")

       return True


   def debug_zone_state(zone):
       """Print detailed zone state information"""
       print(f"\n🔍 Debug info for {zone.name}:")
       print(f"  Type: {zone.zone_type.value}")
       print(f"  ID: {zone.id}")

       # Print all model fields and values
       for field_name, field_value in zone.model_dump().items():
           if not field_name.startswith('_'):
               print(f"  {field_name}: {field_value}")

       # Check if zone can publish updates
       if zone._publish_callback is not None:
           print("  ✓ Can publish desired state updates")
       else:
           print("  ❌ Cannot publish desired state updates")

These examples demonstrate the flexibility and power of the Gecko IoT Client for building sophisticated spa control applications.
