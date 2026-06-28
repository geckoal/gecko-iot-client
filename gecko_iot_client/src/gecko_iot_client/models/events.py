"""Event system for Gecko IoT Client notifications."""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, List

if TYPE_CHECKING:
    from ..async_adapter import AsyncCallbackAdapter

logger = logging.getLogger(__name__)


class EventChannel(Enum):
    """Event channels for different types of notifications."""

    CONNECTIVITY_UPDATE = "connectivity_update"
    OPERATION_MODE_UPDATE = "operation_mode_update"
    ZONE_UPDATE = "zone_update"
    SENSOR_UPDATE = "sensor_update"
    STATE_UPDATE = "state_update"
    CONFIGURATION_UPDATE = "configuration_update"


class EventEmitter:
    """
    Event emitter for managing callbacks across different channels.

    Supports both synchronous and asynchronous callbacks. Sync callbacks
    are invoked directly on the emitting thread (existing behavior). Async
    callbacks are dispatched via an AsyncCallbackAdapter to the consumer's
    event loop.

    Args:
        async_adapter: Optional adapter for dispatching async callbacks.
            When not provided, only sync callbacks are supported.
    """

    def __init__(self, async_adapter: AsyncCallbackAdapter | None = None):
        self._callbacks: Dict[EventChannel, List[Callable]] = {
            channel: [] for channel in EventChannel
        }
        self._async_callbacks: Dict[EventChannel, List[Callable]] = {
            channel: [] for channel in EventChannel
        }
        self._async_adapter = async_adapter
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def async_adapter(self) -> AsyncCallbackAdapter | None:
        """Return the current async adapter."""
        return self._async_adapter

    @async_adapter.setter
    def async_adapter(self, adapter: AsyncCallbackAdapter | None) -> None:
        """Set the async adapter."""
        self._async_adapter = adapter

    def on(self, channel: EventChannel, callback: Callable) -> None:
        """
        Register a synchronous callback for a specific event channel.

        The callback will be invoked on the emitting thread (background thread).

        Args:
            channel: The event channel to listen to
            callback: Function to call when the event occurs
        """
        if callback not in self._callbacks[channel]:
            self._callbacks[channel].append(callback)
            self._logger.debug(f"Registered callback for {channel.value}")

    def off(self, channel: EventChannel, callback: Callable) -> None:
        """
        Unregister a synchronous callback from a specific event channel.

        Args:
            channel: The event channel to stop listening to
            callback: The callback function to remove
        """
        if callback in self._callbacks[channel]:
            self._callbacks[channel].remove(callback)
            self._logger.debug(f"Unregistered callback for {channel.value}")

    def on_async(self, channel: EventChannel, callback: Callable) -> None:
        """
        Register an async callback (coroutine function) for an event channel.

        The callback will be scheduled on the consumer's event loop via the
        AsyncCallbackAdapter. Requires an async_adapter to be configured.

        Args:
            channel: Event channel to listen to.
            callback: Async callable (coroutine function).

        Raises:
            RuntimeError: If no AsyncCallbackAdapter is configured.
        """
        if self._async_adapter is None:
            raise RuntimeError(
                "Cannot register async callbacks without an AsyncCallbackAdapter. "
                "Pass async_adapter to GeckoIotClient constructor."
            )
        if callback not in self._async_callbacks[channel]:
            self._async_callbacks[channel].append(callback)
            self._logger.debug(f"Registered async callback for {channel.value}")

    def off_async(self, channel: EventChannel, callback: Callable) -> None:
        """
        Unregister an async callback from an event channel.

        Args:
            channel: Event channel to stop listening to.
            callback: The async callback to remove.
        """
        if callback in self._async_callbacks[channel]:
            self._async_callbacks[channel].remove(callback)
            self._logger.debug(f"Unregistered async callback for {channel.value}")

    def emit(self, channel: EventChannel, data: Any = None) -> None:
        """
        Emit an event to all registered callbacks for a channel.

        Sync callbacks are invoked directly on the current thread.
        Async callbacks are scheduled via the AsyncCallbackAdapter.

        Args:
            channel: The event channel to emit to
            data: Optional data to pass to the callbacks
        """
        self._logger.debug(f"Emitting {channel.value} event with data: {data}")

        # Invoke sync callbacks (existing behavior)
        for callback in self._callbacks[channel]:
            try:
                if data is not None:
                    callback(data)
                else:
                    callback()
            except Exception as e:
                self._logger.error(f"Error in {channel.value} callback: {e}")

        # Schedule async callbacks via adapter
        if self._async_adapter and self._async_adapter.is_running():
            for callback in self._async_callbacks[channel]:
                try:
                    coro = callback(data) if data is not None else callback()
                    self._async_adapter.schedule(coro)
                except Exception as e:
                    self._logger.error(
                        f"Error scheduling {channel.value} async callback: {e}"
                    )

    def clear(self, channel: EventChannel | None = None) -> None:
        """
        Clear callbacks for a specific channel or all channels.

        Clears both sync and async callbacks.

        Args:
            channel: Optional specific channel to clear. If None, clears all.
        """
        if channel:
            self._callbacks[channel].clear()
            self._async_callbacks[channel].clear()
            self._logger.debug(f"Cleared all callbacks for {channel.value}")
        else:
            for ch in EventChannel:
                self._callbacks[ch].clear()
                self._async_callbacks[ch].clear()
            self._logger.debug("Cleared all callbacks for all channels")
