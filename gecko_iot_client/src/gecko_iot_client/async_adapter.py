"""Async callback adapter for bridging thread-based events to asyncio event loops.

This module provides the AsyncCallbackAdapter abstraction that allows gecko-iot-client
to dispatch callbacks directly onto a consumer's event loop without requiring the
consumer to manually bridge threads.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class AsyncCallbackAdapter(ABC):
    """
    Adapter that bridges gecko-iot-client's internal thread-based
    event dispatch to an external asyncio event loop.

    Consumers provide an implementation that schedules coroutines onto
    their own event loop. The library calls ``schedule()`` from any thread,
    and the adapter ensures the coroutine runs on the correct loop.
    """

    @abstractmethod
    def schedule(self, coro: Coroutine[Any, Any, Any]) -> None:
        """
        Schedule a coroutine to run on the consumer's event loop.

        This method is called from background threads. Implementations
        must be thread-safe.

        Args:
            coro: A coroutine object to be scheduled on the event loop.
        """
        ...

    @abstractmethod
    def schedule_with_result(
        self, coro: Coroutine[Any, Any, Any], timeout: float = 30.0
    ) -> Any:
        """
        Schedule a coroutine and block until its result is available.

        Used for callbacks that need a return value (e.g., token refresh).
        This method blocks the calling thread until the coroutine completes.

        Args:
            coro: A coroutine object to schedule.
            timeout: Maximum seconds to wait for the result.

        Returns:
            The result of the coroutine.

        Raises:
            asyncio.TimeoutError: If the coroutine doesn't complete within timeout.
            Exception: Any exception raised by the coroutine.
        """
        ...

    @property
    @abstractmethod
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the event loop this adapter dispatches to."""
        ...

    @abstractmethod
    def is_running(self) -> bool:
        """Return True if the target event loop is still running."""
        ...


class EventLoopAdapter(AsyncCallbackAdapter):
    """
    Default adapter that dispatches coroutines to a specific asyncio event loop.

    This is the standard implementation suitable for most asyncio consumers,
    including Home Assistant.

    Args:
        loop: The asyncio event loop to dispatch callbacks to.

    Example:
        >>> adapter = EventLoopAdapter(asyncio.get_event_loop())
        >>> client = GeckoIotClient("device-1", transporter, async_adapter=adapter)
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def schedule(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Schedule coroutine on the event loop (fire-and-forget)."""
        if not self.is_running():
            logger.warning("Event loop not running, dropping scheduled coroutine")
            # Close the coroutine to avoid ResourceWarning
            coro.close()
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def schedule_with_result(
        self, coro: Coroutine[Any, Any, Any], timeout: float = 30.0
    ) -> Any:
        """Schedule coroutine and block the calling thread for its result."""
        if not self.is_running():
            coro.close()
            raise RuntimeError("Event loop is not running")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the target event loop."""
        return self._loop

    def is_running(self) -> bool:
        """Return True if the event loop is running and not closed."""
        return self._loop.is_running() and not self._loop.is_closed()
