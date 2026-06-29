"""Operation mode (watercare) model for Gecko IoT devices."""

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OperationMode(Enum):
    """Enum for operation modes (watercare modes)."""

    AWAY = 0
    STANDARD = 1
    SAVINGS = 2
    SUPER_SAVINGS = 3
    WEEKENDER = 4
    OTHER = 5  # for unknown or unsupported modes

    @classmethod
    def from_value(cls, value: Any) -> "OperationMode":
        """
        Convert a value to OperationMode enum.

        Args:
            value: The value to convert (int, str, or OperationMode)

        Returns:
            OperationMode enum value, defaults to OTHER for unknown values
        """
        if isinstance(value, cls):
            return value

        try:
            # Try to convert to int if it's a string
            if isinstance(value, str):
                value = int(value)

            # Look up the enum by value
            for mode in cls:
                if mode.value == value:
                    return mode

        except (ValueError, TypeError):
            logger.warning(
                f"Invalid operation mode value: {value}, defaulting to OTHER"
            )

        return cls.OTHER
