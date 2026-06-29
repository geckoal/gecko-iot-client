"""Tests for the AsyncCallbackAdapter and async event dispatch."""

import asyncio
import threading
import time

import pytest

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src"))

from gecko_iot_client import AsyncCallbackAdapter, EventLoopAdapter, GeckoIotClient
from gecko_iot_client.models.events import EventChannel, EventEmitter


# ---------------------------------------------------------------------------
# EventLoopAdapter tests
# ---------------------------------------------------------------------------


class TestEventLoopAdapter:
    """Tests for EventLoopAdapter."""

    def test_schedule_fires_coroutine_on_loop(self):
        """Verify schedule() dispatches a coroutine to the event loop."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)
        results = []

        async def coro():
            results.append("executed")

        # Run loop in background thread
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        try:
            adapter.schedule(coro())
            time.sleep(0.1)  # Give loop time to process
            assert results == ["executed"]
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()

    def test_schedule_with_result_returns_value(self):
        """Verify schedule_with_result() blocks and returns the coroutine result."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)

        async def coro():
            await asyncio.sleep(0.01)
            return "token_url"

        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        try:
            result = adapter.schedule_with_result(coro(), timeout=5.0)
            assert result == "token_url"
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()

    def test_schedule_with_result_propagates_exception(self):
        """Verify exceptions from the coroutine propagate to the caller."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)

        async def failing_coro():
            raise ValueError("refresh failed")

        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        try:
            with pytest.raises(ValueError, match="refresh failed"):
                adapter.schedule_with_result(failing_coro(), timeout=5.0)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()

    def test_schedule_with_result_timeout(self):
        """Verify TimeoutError raised when coroutine takes too long."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)

        async def slow_coro():
            await asyncio.sleep(10)
            return "never"

        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        try:
            with pytest.raises(TimeoutError):
                adapter.schedule_with_result(slow_coro(), timeout=0.1)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()

    def test_is_running_true_when_loop_active(self):
        """Verify is_running() returns True when the loop is running."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)

        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        time.sleep(0.05)

        try:
            assert adapter.is_running() is True
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()

    def test_is_running_false_when_loop_closed(self):
        """Verify is_running() returns False when loop is closed."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)
        loop.close()

        assert adapter.is_running() is False

    def test_schedule_drops_coro_when_loop_not_running(self):
        """Verify schedule() drops the coroutine gracefully when loop is closed."""
        loop = asyncio.new_event_loop()
        loop.close()
        adapter = EventLoopAdapter(loop)

        async def coro():
            pass  # pragma: no cover

        # Should not raise
        adapter.schedule(coro())


# ---------------------------------------------------------------------------
# EventEmitter async dispatch tests
# ---------------------------------------------------------------------------


class TestEventEmitterAsync:
    """Tests for EventEmitter async callback support."""

    def test_on_async_raises_without_adapter(self):
        """Verify on_async() raises RuntimeError when no adapter configured."""
        emitter = EventEmitter()

        async def handler(data):
            pass  # pragma: no cover

        with pytest.raises(RuntimeError, match="AsyncCallbackAdapter"):
            emitter.on_async(EventChannel.ZONE_UPDATE, handler)

    def test_on_async_registers_callback(self):
        """Verify on_async() registers the callback."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)
        emitter = EventEmitter(async_adapter=adapter)

        async def handler(data):
            pass  # pragma: no cover

        emitter.on_async(EventChannel.ZONE_UPDATE, handler)
        assert handler in emitter._async_callbacks[EventChannel.ZONE_UPDATE]
        loop.close()

    def test_off_async_removes_callback(self):
        """Verify off_async() removes the callback."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)
        emitter = EventEmitter(async_adapter=adapter)

        async def handler(data):
            pass  # pragma: no cover

        emitter.on_async(EventChannel.ZONE_UPDATE, handler)
        emitter.off_async(EventChannel.ZONE_UPDATE, handler)
        assert handler not in emitter._async_callbacks[EventChannel.ZONE_UPDATE]
        loop.close()

    def test_emit_dispatches_async_callback(self):
        """Verify emit() dispatches async callbacks via the adapter."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)
        emitter = EventEmitter(async_adapter=adapter)
        results = []

        async def handler(data):
            results.append(data)

        emitter.on_async(EventChannel.ZONE_UPDATE, handler)

        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        try:
            # Emit from a background thread (simulating MQTT thread)
            emit_thread = threading.Thread(
                target=emitter.emit,
                args=(EventChannel.ZONE_UPDATE, {"zones": "data"}),
            )
            emit_thread.start()
            emit_thread.join(timeout=2)

            time.sleep(0.1)
            assert results == [{"zones": "data"}]
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()

    def test_emit_fires_both_sync_and_async(self):
        """Verify emit() fires both sync and async callbacks."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)
        emitter = EventEmitter(async_adapter=adapter)
        sync_results = []
        async_results = []

        def sync_handler(data):
            sync_results.append(data)

        async def async_handler(data):
            async_results.append(data)

        emitter.on(EventChannel.CONNECTIVITY_UPDATE, sync_handler)
        emitter.on_async(EventChannel.CONNECTIVITY_UPDATE, async_handler)

        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        try:
            emitter.emit(EventChannel.CONNECTIVITY_UPDATE, "connected")
            time.sleep(0.1)
            assert sync_results == ["connected"]
            assert async_results == ["connected"]
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()

    def test_clear_removes_async_callbacks(self):
        """Verify clear() removes async callbacks too."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)
        emitter = EventEmitter(async_adapter=adapter)

        async def handler(data):
            pass  # pragma: no cover

        emitter.on_async(EventChannel.ZONE_UPDATE, handler)
        emitter.clear(EventChannel.ZONE_UPDATE)
        assert emitter._async_callbacks[EventChannel.ZONE_UPDATE] == []
        loop.close()


# ---------------------------------------------------------------------------
# GeckoIotClient async interface tests
# ---------------------------------------------------------------------------


class TestGeckoIotClientAsync:
    """Tests for GeckoIotClient on_async/off_async methods."""

    def _make_mock_transporter(self):
        """Create a minimal mock transporter."""
        from unittest.mock import MagicMock

        transporter = MagicMock()
        transporter.on_connectivity_change = MagicMock()
        return transporter

    def test_on_async_raises_without_adapter(self):
        """Verify on_async raises RuntimeError when no adapter provided."""
        transporter = self._make_mock_transporter()
        client = GeckoIotClient("test-1", transporter)

        async def handler(data):
            pass  # pragma: no cover

        with pytest.raises(RuntimeError):
            client.on_async(EventChannel.ZONE_UPDATE, handler)

    def test_on_async_registers_with_adapter(self):
        """Verify on_async works when adapter is provided."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)
        transporter = self._make_mock_transporter()
        client = GeckoIotClient("test-1", transporter, async_adapter=adapter)

        async def handler(data):
            pass  # pragma: no cover

        client.on_async(EventChannel.ZONE_UPDATE, handler)
        # Verify via internal emitter
        assert handler in client._event_emitter._async_callbacks[EventChannel.ZONE_UPDATE]
        loop.close()

    def test_off_async_unregisters(self):
        """Verify off_async removes the callback."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)
        transporter = self._make_mock_transporter()
        client = GeckoIotClient("test-1", transporter, async_adapter=adapter)

        async def handler(data):
            pass  # pragma: no cover

        client.on_async(EventChannel.ZONE_UPDATE, handler)
        client.off_async(EventChannel.ZONE_UPDATE, handler)
        assert handler not in client._event_emitter._async_callbacks[EventChannel.ZONE_UPDATE]
        loop.close()

    def test_on_zone_update_async_convenience(self):
        """Verify on_zone_update_async is a convenience for on_async(ZONE_UPDATE)."""
        loop = asyncio.new_event_loop()
        adapter = EventLoopAdapter(loop)
        transporter = self._make_mock_transporter()
        client = GeckoIotClient("test-1", transporter, async_adapter=adapter)

        async def handler(zones):
            pass  # pragma: no cover

        client.on_zone_update_async(handler)
        assert handler in client._event_emitter._async_callbacks[EventChannel.ZONE_UPDATE]
        loop.close()

    def test_backward_compatible_without_adapter(self):
        """Verify GeckoIotClient works normally without async_adapter."""
        transporter = self._make_mock_transporter()
        client = GeckoIotClient("test-1", transporter)

        results = []

        def sync_handler(data):
            results.append(data)

        client.on(EventChannel.ZONE_UPDATE, sync_handler)
        client._event_emitter.emit(EventChannel.ZONE_UPDATE, {"test": True})
        assert results == [{"test": True}]
