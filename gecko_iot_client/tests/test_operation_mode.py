"""
Unit tests for OperationMode functionality.
"""

import unittest

from src.gecko_iot_client.models.events import EventChannel, EventEmitter
from src.gecko_iot_client.models.operation_mode import OperationMode
from src.gecko_iot_client.models.operation_mode_controller import (
    OperationModeController,
)


class TestOperationMode(unittest.TestCase):
    """Test OperationMode enum functionality."""

    def test_operation_mode_enum_values(self):
        """Test that all operation mode enum values are correct."""
        self.assertEqual(OperationMode.AWAY.value, 0)
        self.assertEqual(OperationMode.STANDARD.value, 1)
        self.assertEqual(OperationMode.SAVINGS.value, 2)
        self.assertEqual(OperationMode.SUPER_SAVINGS.value, 3)
        self.assertEqual(OperationMode.WEEKENDER.value, 4)
        self.assertEqual(OperationMode.OTHER.value, 5)

    def test_operation_mode_from_value_valid_int(self):
        """Test converting valid integer values to OperationMode."""
        self.assertEqual(OperationMode.from_value(0), OperationMode.AWAY)
        self.assertEqual(OperationMode.from_value(1), OperationMode.STANDARD)
        self.assertEqual(OperationMode.from_value(2), OperationMode.SAVINGS)
        self.assertEqual(OperationMode.from_value(3), OperationMode.SUPER_SAVINGS)
        self.assertEqual(OperationMode.from_value(4), OperationMode.WEEKENDER)
        self.assertEqual(OperationMode.from_value(5), OperationMode.OTHER)

    def test_operation_mode_from_value_valid_string(self):
        """Test converting valid string values to OperationMode."""
        self.assertEqual(OperationMode.from_value("0"), OperationMode.AWAY)
        self.assertEqual(OperationMode.from_value("1"), OperationMode.STANDARD)
        self.assertEqual(OperationMode.from_value("2"), OperationMode.SAVINGS)

    def test_operation_mode_from_value_existing_enum(self):
        """Test that passing an existing OperationMode returns the same value."""
        self.assertEqual(
            OperationMode.from_value(OperationMode.STANDARD), OperationMode.STANDARD
        )

    def test_operation_mode_from_value_invalid(self):
        """Test that invalid values default to OTHER."""
        self.assertEqual(OperationMode.from_value(999), OperationMode.OTHER)
        self.assertEqual(OperationMode.from_value("invalid"), OperationMode.OTHER)
        self.assertEqual(OperationMode.from_value(None), OperationMode.OTHER)
        self.assertEqual(OperationMode.from_value([]), OperationMode.OTHER)


class TestOperationModeController(unittest.TestCase):
    """Test OperationModeController functionality."""

    def test_default_initialization(self):
        """Test default initialization of OperationModeController."""
        controller = OperationModeController()
        self.assertEqual(controller.operation_mode, OperationMode.OTHER)

    def test_mode_name_property(self):
        """Test mode_name property returns correct names."""
        test_cases = [
            (OperationMode.AWAY, "Away"),
            (OperationMode.STANDARD, "Standard"),
            (OperationMode.SAVINGS, "Savings"),
            (OperationMode.SUPER_SAVINGS, "Super Savings"),
            (OperationMode.WEEKENDER, "Weekender"),
            (OperationMode.OTHER, "Other"),
        ]

        for mode, expected_name in test_cases:
            with self.subTest(mode=mode):
                controller = OperationModeController()
                controller.operation_mode = mode
                self.assertEqual(controller.mode_name, expected_name)

    def test_is_energy_saving_property(self):
        """Test is_energy_saving property logic."""
        # Energy saving modes
        energy_saving_modes = [
            OperationMode.AWAY,
            OperationMode.SAVINGS,
            OperationMode.SUPER_SAVINGS,
        ]
        for mode in energy_saving_modes:
            with self.subTest(mode=mode):
                controller = OperationModeController()
                controller.operation_mode = mode
                self.assertTrue(controller.is_energy_saving)

        # Non-energy saving modes
        non_energy_saving_modes = [
            OperationMode.STANDARD,
            OperationMode.WEEKENDER,
            OperationMode.OTHER,
        ]
        for mode in non_energy_saving_modes:
            with self.subTest(mode=mode):
                controller = OperationModeController()
                controller.operation_mode = mode
                self.assertFalse(controller.is_energy_saving)

    def test_from_state_data_valid(self):
        """Test creating OperationModeController from valid state data."""
        state_data = {"state": {"reported": {"features": {"operationMode": 1}}}}

        controller = OperationModeController.from_state_data(state_data)
        self.assertEqual(controller.operation_mode, OperationMode.STANDARD)

    def test_from_state_data_missing_features(self):
        """Test creating OperationModeController from state data missing features."""
        state_data = {"state": {"reported": {}}}

        controller = OperationModeController.from_state_data(state_data)
        self.assertEqual(controller.operation_mode, OperationMode.OTHER)

    def test_from_state_data_missing_operation_mode(self):
        """Test creating OperationModeController from state data missing operationMode."""
        state_data = {"state": {"reported": {"features": {}}}}

        controller = OperationModeController.from_state_data(state_data)
        self.assertEqual(controller.operation_mode, OperationMode.OTHER)

    def test_update_from_state_data_changed(self):
        """Test updating from state data when operation mode changes."""
        controller = OperationModeController()

        state_data = {
            "state": {"reported": {"features": {"operationMode": 2}}}  # SAVINGS
        }

        changed = controller.update_from_state_data(state_data)
        self.assertTrue(changed)
        self.assertEqual(controller.operation_mode, OperationMode.SAVINGS)

    def test_update_from_state_data_unchanged(self):
        """Test updating from state data when operation mode doesn't change."""
        controller = OperationModeController()
        controller.operation_mode = OperationMode.SAVINGS

        state_data = {
            "state": {
                "reported": {
                    "features": {"operationMode": 2}  # SAVINGS - same as current
                }
            }
        }

        changed = controller.update_from_state_data(state_data)
        self.assertFalse(changed)
        self.assertEqual(controller.operation_mode, OperationMode.SAVINGS)

    def test_update_from_state_data_error_handling(self):
        """Test error handling in update_from_state_data."""
        controller = OperationModeController()

        # Test with empty dict - should not change anything (defaults to OTHER)
        changed = controller.update_from_state_data({})
        self.assertFalse(changed)
        self.assertEqual(controller.operation_mode, OperationMode.OTHER)

    def test_to_dict(self):
        """Test dictionary conversion."""
        controller = OperationModeController()
        controller.operation_mode = OperationMode.SAVINGS
        result = controller.to_dict()

        expected = {
            "operation_mode": "SAVINGS",
            "operation_mode_value": 2,
            "mode_name": "Savings",
            "is_energy_saving": True,
        }

        self.assertEqual(result, expected)

    def test_repr(self):
        """Test string representation."""
        controller = OperationModeController()
        controller.operation_mode = OperationMode.AWAY
        repr_str = repr(controller)
        self.assertIn("AWAY", repr_str)
        self.assertIn("0", repr_str)


class TestOperationModeEvents(unittest.TestCase):
    """Test OperationMode integration with event system."""

    def test_operation_mode_update_event_channel_exists(self):
        """Test that OPERATION_MODE_UPDATE event channel exists."""
        channel = EventChannel.OPERATION_MODE_UPDATE
        self.assertEqual(channel.value, "operation_mode_update")

    def test_event_emitter_with_operation_mode_updates(self):
        """Test EventEmitter with operation mode update events."""
        emitter = EventEmitter()
        callback_data = []

        def operation_mode_callback(data):
            callback_data.append(data)

        emitter.on(EventChannel.OPERATION_MODE_UPDATE, operation_mode_callback)

        # Emit event with controller
        controller = OperationModeController()
        controller.operation_mode = OperationMode.AWAY
        emitter.emit(EventChannel.OPERATION_MODE_UPDATE, controller)

        self.assertEqual(len(callback_data), 1)
        self.assertEqual(callback_data[0], controller)
        self.assertEqual(callback_data[0].operation_mode, OperationMode.AWAY)

    def test_multiple_callbacks_for_operation_mode_updates(self):
        """Test multiple callbacks for operation mode updates."""
        emitter = EventEmitter()
        callback1_data = []
        callback2_data = []

        def callback1(data):
            callback1_data.append(data)

        def callback2(data):
            callback2_data.append(data)

        emitter.on(EventChannel.OPERATION_MODE_UPDATE, callback1)
        emitter.on(EventChannel.OPERATION_MODE_UPDATE, callback2)

        controller = OperationModeController()
        controller.operation_mode = OperationMode.SUPER_SAVINGS
        emitter.emit(EventChannel.OPERATION_MODE_UPDATE, controller)

        self.assertEqual(len(callback1_data), 1)
        self.assertEqual(len(callback2_data), 1)
        self.assertEqual(callback1_data[0].operation_mode, OperationMode.SUPER_SAVINGS)
        self.assertEqual(callback2_data[0].operation_mode, OperationMode.SUPER_SAVINGS)


if __name__ == "__main__":
    unittest.main()
