from enum import Enum
import logging
from typing import Any, Dict, Optional

from .abstract_zone import AbstractZone, ZoneType

logger = logging.getLogger(__name__)


class TemperatureControlZoneStatus(Enum):
    """Enum for temperature control zone status"""

    IDLE = 0
    HEATING = 1
    COOLING = 2
    INVALID = 3
    HEAT_PUMP_HEATING = 4
    HEAT_PUMP_AND_HEATER_HEATING = 5
    HEAT_PUMP_COOLING = 6
    HEAT_PUMP_DEFROSTING = 7
    HEAT_PUMP_ERROR = 8

    @property
    def is_heating(self) -> bool:
        return self in {
            TemperatureControlZoneStatus.HEATING,
            TemperatureControlZoneStatus.HEAT_PUMP_HEATING,
            TemperatureControlZoneStatus.HEAT_PUMP_AND_HEATER_HEATING,
        }


class TemperatureControlMode:
    """Temperature control mode configuration"""

    def __init__(self, eco: bool = False):
        """Initialize temperature control mode."""
        self.eco = eco


@AbstractZone.register_zone_type(ZoneType.TEMPERATURE_CONTROL_ZONE)
class TemperatureControlZone(AbstractZone):
    """State representation for temperature control zone v1 with validation"""

    def __init__(self, zone_id: str, config: Dict[str, Any]):
        """Initialize TemperatureControlZone with zone_id and config."""
        # Set default name if not provided
        if "name" not in config or config["name"] is None:
            config["name"] = f"Water Temperature {zone_id}"

        # Extract temperature control specific fields before parent init
        self.min_temperature_set_point_c = config.pop(
            "minTemperatureSetPointC", config.pop("min_temperature_set_point_c", None)
        )
        self.max_temperature_set_point_c = config.pop(
            "maxTemperatureSetPointC", config.pop("max_temperature_set_point_c", None)
        )

        # Initialize parent
        super().__init__(
            id=zone_id,
            zone_type=ZoneType.TEMPERATURE_CONTROL_ZONE,
            name=config.get("name"),
            config=config,
        )

        # Initialize temperature control specific attributes from config
        self.status_: Optional[TemperatureControlZoneStatus] = (
            self._convert_status_to_enum(config.get("status_"))
        )
        self.temperature_: Optional[float] = config.get("temperature_")
        self.mode_: Optional[TemperatureControlMode] = config.get("mode_")
        self.set_point: Optional[float] = config.get("set_point")

        # Validate temperature ranges if values are present
        self._validate_temperature_range()

    def _validate_temperature_range(self) -> None:
        """Validate temperature values are within acceptable range (-50 to 100 Celsius)."""
        if self.temperature_ is not None and not (-50.0 <= self.temperature_ <= 100.0):
            raise ValueError(
                f"Temperature {self.temperature_}°C is outside valid range (-50°C to 100°C)"
            )

        if self.set_point is not None and not (-50.0 <= self.set_point <= 100.0):
            raise ValueError(
                f"Set point {self.set_point}°C is outside valid range (-50°C to 100°C)"
            )

        if self.min_temperature_set_point_c is not None and not (
            -50.0 <= self.min_temperature_set_point_c <= 100.0
        ):
            raise ValueError(
                f"Min temperature {self.min_temperature_set_point_c}°C is outside valid range (-50°C to 100°C)"
            )

        if self.max_temperature_set_point_c is not None and not (
            -50.0 <= self.max_temperature_set_point_c <= 100.0
        ):
            raise ValueError(
                f"Max temperature {self.max_temperature_set_point_c}°C is outside valid range (-50°C to 100°C)"
            )

    @property
    def status(self) -> Optional[TemperatureControlZoneStatus]:
        return self.status_

    @property
    def temperature(self) -> Optional[float]:
        return self.temperature_

    @property
    def mode(self) -> Optional[TemperatureControlMode]:
        return self.mode_

    @property
    def target_temperature(self) -> Optional[float]:
        return self.set_point

    @property
    def min_temperature_set_point_c_value(self) -> Optional[float]:
        return self.min_temperature_set_point_c

    @property
    def max_temperature_set_point_c_value(self) -> Optional[float]:
        return self.max_temperature_set_point_c

    def __str__(self) -> str:
        """String representation of the TemperatureControlZone."""
        temp_str = f"{self.temperature_}°C" if self.temperature_ is not None else "N/A"
        target_str = f"{self.set_point}°C" if self.set_point is not None else "N/A"
        status_str = self.status_.name if self.status_ else "N/A"
        eco_mode = self.mode_.eco if self.mode_ else False

        return (
            f"TemperatureControlZone(name='{self.name}', id={self.id}, "
            f"temp={temp_str}, target={target_str}, status={status_str}, "
            f"eco_mode={eco_mode})"
        )

    def set_target_temperature(self, temperature: float) -> None:
        """Set target temperature with validation against configured limits."""
        if (
            self.min_temperature_set_point_c is None
            or self.max_temperature_set_point_c is None
        ):
            raise ValueError(
                "Temperature limits not configured - cannot validate set point"
            )

        if not (
            self.min_temperature_set_point_c
            <= temperature
            <= self.max_temperature_set_point_c
        ):
            raise ValueError(
                f"Set point {temperature}°C is outside configured range "
                f"({self.min_temperature_set_point_c}°C to {self.max_temperature_set_point_c}°C)"
            )

        self.set_point = temperature
        self._publish_desired_state({"setPoint": temperature})

    def get_temperature_state(self) -> Dict[str, Any]:
        """Get the current temperature state as a simple dictionary."""
        return {
            "current_temperature": self.temperature_,
            "target_temperature": self.set_point,
            "status": self.status_.name if self.status_ else None,
            "eco_mode": self.mode_.eco if self.mode_ else None,
        }

    def _get_runtime_state_fields(self) -> set:
        return {"temperature_", "set_point", "mode_", "status_"}

    def _convert_status_to_enum(
        self, status_value: Any
    ) -> Optional[TemperatureControlZoneStatus]:
        """Convert status value to TemperatureControlZoneStatus enum."""
        if status_value is None:
            return None

        try:
            # If it's already the correct enum type, return it
            if isinstance(status_value, TemperatureControlZoneStatus):
                return status_value

            # If it's an integer, try to convert by value
            if isinstance(status_value, int):
                return TemperatureControlZoneStatus(status_value)

            # If it's a string, try to convert by name
            if isinstance(status_value, str):
                # Try by name first (e.g., "HEATING")
                try:
                    return TemperatureControlZoneStatus[status_value.upper()]
                except KeyError:
                    # Try to convert string to int then to enum (e.g., "1" -> 1 -> HEATING)
                    try:
                        int_value = int(status_value)
                        return TemperatureControlZoneStatus(int_value)
                    except (ValueError, TypeError):
                        pass

        except (ValueError, KeyError) as e:
            logger.warning(
                f"Could not convert status value {status_value} (type: {type(status_value).__name__}) "
                f"to TemperatureControlZoneStatus: {e}"
            )

        return None

    def update_from_state(self, state: Dict[str, Any]) -> None:
        """Update temperature control zone from runtime state."""
        
        if "temperature_" in state:
            self.temperature_ = state["temperature_"]
        
        if "setPoint" in state:
            self.set_point = state["setPoint"]

        # Handle status conversion
        status_value = state.get("status_")
        if status_value is not None:
            converted_status = self._convert_status_to_enum(status_value)
            if converted_status is not None:
                self.status_ = converted_status

        # Handle mode
        if "mode_" in state:
            mode_data = state["mode_"]
            if isinstance(mode_data, dict):
                self.mode_ = TemperatureControlMode(eco=mode_data.get("eco", False))
            elif isinstance(mode_data, TemperatureControlMode):
                self.mode_ = mode_data
