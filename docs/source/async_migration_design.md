# Async Migration Design Document

## Status: Phase 1 & 2 Implemented

**Author**: Gecko IoT Team
**Date**: 2025 (Implemented June 2026)
**Validates**: NFR-3, NFR-9

---

## 1. Problem Statement

The `gecko-iot-client` library currently dispatches all callbacks from background threads
managed by the MQTT transporter. Consumers running on an `asyncio` event loop (such as
Home Assistant) must bridge these synchronous, thread-dispatched callbacks back onto the
event loop using patterns like `asyncio.run_coroutine_threadsafe` or
`loop.call_soon_threadsafe`.

### Current Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  MQTT Transporter (background thread)                       │
│                                                             │
│  on_state_change() ──► EventEmitter.emit() ──► callbacks   │
│  on_connectivity()                              (sync)      │
│  TokenManager._refresh_monitor_loop()                       │
└─────────────────────────────────────────────────────────────┘
                          │
                          │  Callbacks fire on background thread
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Consumer (Home Assistant integration)                      │
│                                                             │
│  run_coroutine_threadsafe(handle_zone_update, hass.loop)    │
│  loop.call_soon_threadsafe(coordinator.async_set_updated)   │
│  future = run_coroutine_threadsafe(api_call, loop)          │
│  result = future.result(timeout=30)  # blocks thread       │
└─────────────────────────────────────────────────────────────┘
```

### Problems with Current Approach

1. **Thread safety complexity**: Every consumer must manually bridge callbacks to their
   event loop, which is error-prone.
2. **Blocking on async results**: The sync `refresh_token_callback` must block the
   background thread while waiting for an async API call, risking deadlocks.
3. **HA Core compliance**: Home Assistant strongly prefers native async throughout.
   The `run_coroutine_threadsafe` pattern is fragile and discouraged.
4. **Exception propagation**: Exceptions in async code don't naturally propagate back
   to the background thread caller.
5. **Testing difficulty**: Thread-based callbacks are harder to test deterministically.

---

## 2. AsyncCallbackAdapter Interface

The `AsyncCallbackAdapter` is the core abstraction that allows `gecko-iot-client` to
dispatch callbacks directly onto a consumer's event loop without requiring the consumer
to manually bridge threads.

### Interface Definition

```python
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any


class AsyncCallbackAdapter(ABC):
    """
    Adapter that bridges gecko-iot-client's internal thread-based
    event dispatch to an external asyncio event loop.

    Consumers provide an implementation that schedules coroutines onto
    their own event loop. The library calls `schedule()` from any thread,
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
```

### Default Implementation (for HA and generic asyncio consumers)

```python
class EventLoopAdapter(AsyncCallbackAdapter):
    """
    Default adapter that dispatches to a specific asyncio event loop.

    Usage:
        adapter = EventLoopAdapter(asyncio.get_event_loop())
        client = GeckoIotClient(id, transporter, async_adapter=adapter)
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def schedule(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Schedule coroutine on the event loop (fire-and-forget)."""
        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    def schedule_with_result(
        self, coro: Coroutine[Any, Any, Any], timeout: float = 30.0
    ) -> Any:
        """Schedule coroutine and wait for its result."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def is_running(self) -> bool:
        return self._loop.is_running() and not self._loop.is_closed()
```

### Home Assistant Specific Adapter

```python
class HomeAssistantAdapter(EventLoopAdapter):
    """
    HA-specific adapter that uses hass.loop for dispatching.

    Usage in ha-gecko-integration:
        adapter = HomeAssistantAdapter(hass.loop)
        # Pass to gecko-iot-client at connection time
    """

    def __init__(self, hass_loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(hass_loop)
```

---

## 3. Async Registration API

### New `on_async(event, callback)` Method

Alongside the existing `on(event, callback)` for sync callbacks, a new
`on_async(event, callback)` method accepts coroutine functions. When an event fires,
async callbacks are dispatched via the `AsyncCallbackAdapter`, while sync callbacks
continue to be invoked directly on the emitting thread.

### API Design

```python
class GeckoIotClient:
    """Extended client with async callback support."""

    def __init__(
        self,
        idd: str,
        transporter: AbstractTransporter,
        config_timeout: float = 5.0,
        async_adapter: AsyncCallbackAdapter | None = None,
    ):
        # ... existing init ...
        self._async_adapter = async_adapter

    def on(self, channel: EventChannel, callback: Callable) -> None:
        """
        Register a synchronous callback for an event channel.

        The callback will be invoked on the emitting thread (background thread).
        This is the existing behavior — unchanged for backward compatibility.

        Args:
            channel: Event channel to listen to.
            callback: Synchronous callable.
        """
        self._event_emitter.on(channel, callback)

    def on_async(
        self,
        channel: EventChannel,
        callback: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """
        Register an async callback (coroutine function) for an event channel.

        The callback will be scheduled on the consumer's event loop via the
        AsyncCallbackAdapter. Requires an async_adapter to be set at init.

        Args:
            channel: Event channel to listen to.
            callback: Async callable (coroutine function).

        Raises:
            RuntimeError: If no AsyncCallbackAdapter was provided at init.
        """
        if self._async_adapter is None:
            raise RuntimeError(
                "Cannot register async callbacks without an AsyncCallbackAdapter. "
                "Pass async_adapter to GeckoIotClient constructor."
            )
        self._event_emitter.on_async(channel, callback)

    def on_zone_update_async(
        self,
        callback: Callable[[dict[ZoneType, list[AbstractZone]]], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Register an async callback for zone updates.

        Convenience method wrapping on_async(EventChannel.ZONE_UPDATE, callback).

        Args:
            callback: Async function receiving the zones dict.
        """
        self.on_async(EventChannel.ZONE_UPDATE, callback)

    def off_async(
        self,
        channel: EventChannel,
        callback: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """
        Unregister an async callback from an event channel.

        Args:
            channel: Event channel to stop listening to.
            callback: The async callback to remove.
        """
        self._event_emitter.off_async(channel, callback)
```

### Updated EventEmitter

```python
class EventEmitter:
    """Extended event emitter with async callback support."""

    def __init__(self, async_adapter: AsyncCallbackAdapter | None = None):
        self._callbacks: dict[EventChannel, list[Callable]] = {
            channel: [] for channel in EventChannel
        }
        self._async_callbacks: dict[EventChannel, list[Callable]] = {
            channel: [] for channel in EventChannel
        }
        self._async_adapter = async_adapter

    def on(self, channel: EventChannel, callback: Callable) -> None:
        """Register a sync callback."""
        if callback not in self._callbacks[channel]:
            self._callbacks[channel].append(callback)

    def on_async(self, channel: EventChannel, callback: Callable) -> None:
        """Register an async callback (coroutine function)."""
        if callback not in self._async_callbacks[channel]:
            self._async_callbacks[channel].append(callback)

    def off_async(self, channel: EventChannel, callback: Callable) -> None:
        """Unregister an async callback."""
        if callback in self._async_callbacks[channel]:
            self._async_callbacks[channel].remove(callback)

    def emit(self, channel: EventChannel, data: Any = None) -> None:
        """
        Emit an event to all registered callbacks.

        - Sync callbacks: invoked directly on the current thread.
        - Async callbacks: scheduled via the AsyncCallbackAdapter.
        """
        # Invoke sync callbacks (existing behavior)
        for callback in self._callbacks[channel]:
            try:
                if data is not None:
                    callback(data)
                else:
                    callback()
            except Exception as e:
                logger.error(f"Error in {channel.value} sync callback: {e}")

        # Schedule async callbacks via adapter
        if self._async_adapter and self._async_adapter.is_running():
            for callback in self._async_callbacks[channel]:
                try:
                    coro = callback(data) if data is not None else callback()
                    self._async_adapter.schedule(coro)
                except Exception as e:
                    logger.error(f"Error scheduling {channel.value} async callback: {e}")
```

---

## 4. Current Sync-From-Thread Callbacks

The following callbacks are currently invoked from background threads in
`gecko-iot-client`. Each requires migration to support async dispatch.

### 4.1 Zone Update Callbacks

| Callback | Source Thread | Current Signature | Invoked By |
|----------|--------------|-------------------|------------|
| Zone update | MQTT message handler thread | `Callable[[dict[ZoneType, list[AbstractZone]]], None]` | `EventEmitter.emit(ZONE_UPDATE, zones)` |

**Trigger path**: MQTT message arrives → `MqttTransporter` dispatches on internal
thread → `GeckoIotClient._on_state_change()` → `_process_state_updates()` →
`_notify_zone_updates()` → `EventEmitter.emit(ZONE_UPDATE, zones)`

**Consumer impact**: HA integration uses `asyncio.run_coroutine_threadsafe` or
`loop.call_soon_threadsafe` to push zones into the coordinator.

### 4.2 Connectivity Update Callbacks

| Callback | Source Thread | Current Signature | Invoked By |
|----------|--------------|-------------------|------------|
| Connectivity update | MQTT thread / transporter thread | `Callable[[ConnectivityStatus], None]` | `EventEmitter.emit(CONNECTIVITY_UPDATE, status)` |

**Trigger path**: Transport connection state changes → `_on_transporter_connectivity_change()`
→ `EventEmitter.emit(CONNECTIVITY_UPDATE, status)`. Also from shadow state updates
via `_process_state_updates()`.

**Consumer impact**: HA integration bridges to coordinator via `call_soon_threadsafe`.

### 4.3 Token Refresh Callback

| Callback | Source Thread | Current Signature | Invoked By |
|----------|--------------|-------------------|------------|
| Token refresh | `TokenManager._refresh_monitor_loop` (daemon thread) | `Callable[[], dict]` or `Callable[[str \| None], str \| None]` | `TokenManager.refresh_token()` |

**Trigger path**: `TokenManager` background thread detects token near expiry →
calls `_token_refresh_callback()` → expects synchronous return of new token/URL.

**Consumer impact**: This is the most problematic callback. The HA integration's
refresh callback must call an async API (`async_get_monitor_livestream`) from a
sync context, requiring `run_coroutine_threadsafe(...).result(timeout=30)` which
blocks the background thread and risks deadlocks if the event loop is busy.

### 4.4 Operation Mode Update Callbacks

| Callback | Source Thread | Current Signature | Invoked By |
|----------|--------------|-------------------|------------|
| Operation mode update | MQTT message handler thread | `Callable[[OperationModeController], None]` | `EventEmitter.emit(OPERATION_MODE_UPDATE, controller)` |

**Trigger path**: State update from device shadow → `_process_state_updates()` →
detects operation mode change → `EventEmitter.emit(OPERATION_MODE_UPDATE, controller)`.

**Consumer impact**: HA integration bridges to coordinator via `call_soon_threadsafe`.

### 4.5 Configuration Loaded Callback

| Callback | Source Thread | Current Signature | Invoked By |
|----------|--------------|-------------------|------------|
| Configuration loaded | MQTT shadow thread | `Callable[[dict], None]` | `transporter.on_configuration_loaded(callback)` |

**Trigger path**: AWS IoT shadow `get` response arrives on MQTT thread →
transporter invokes `on_configuration_loaded` handler.

**Consumer impact**: Internal to `GeckoIotClient` (not exposed to HA), but still
runs on background thread.

### Summary Table

| # | Callback | Thread | Needs Return Value | Priority |
|---|----------|--------|-------------------|----------|
| 1 | Zone update | MQTT handler | No | High |
| 2 | Connectivity update | MQTT/transport | No | High |
| 3 | Token refresh | TokenManager daemon | Yes (`str \| None`) | Critical |
| 4 | Operation mode update | MQTT handler | No | Medium |
| 5 | Configuration loaded | MQTT shadow | No | Low (internal) |

---

## 5. Backward Compatibility Approach (Dual Interface)

### Design Principle

The async interface is **opt-in**. Existing consumers using sync callbacks continue to
work without any code changes. The `async_adapter` parameter is optional — when absent,
the library behaves exactly as it does today.

### Compatibility Matrix

| Consumer Type | `async_adapter` | `on()` (sync) | `on_async()` | Behavior |
|---------------|-----------------|---------------|--------------|----------|
| CLI / scripts | Not provided | ✅ Works | ❌ Raises RuntimeError | Sync-only (current behavior) |
| Home Assistant | Provided | ✅ Works (deprecated) | ✅ Works | Async dispatched to hass.loop |
| Mixed | Provided | ✅ Works | ✅ Works | Both fire: sync on thread, async on loop |

### Rules

1. **No breaking changes**: The existing `GeckoIotClient(id, transporter)` constructor
   signature remains valid. `async_adapter` is keyword-only and optional.

2. **Both callback types fire**: When an event emits, sync callbacks fire on the current
   thread first, then async callbacks are scheduled on the event loop. This ensures
   consumers that register both types receive both notifications.

3. **Deprecation path**: In a future major version (2.0), sync callbacks may be
   deprecated for event channels that have async equivalents. The `on()` method will
   emit a deprecation warning when `async_adapter` is provided and the consumer
   registers sync callbacks for channels that support async.

4. **Token refresh special case**: The `token_refresh_callback` parameter on
   `MqttTransporter` continues to accept sync callables. A new
   `async_token_refresh_callback` parameter is added alongside it. If both are
   provided, the async version takes precedence.

### Migration Example for Existing Consumers

```python
# BEFORE (existing code — continues to work unchanged)
client = GeckoIotClient("device-1", transporter)
client.on(EventChannel.ZONE_UPDATE, my_sync_handler)
client.connect()

# AFTER (opt-in async — existing sync callbacks still work)
adapter = EventLoopAdapter(asyncio.get_event_loop())
client = GeckoIotClient("device-1", transporter, async_adapter=adapter)

# Async callbacks (new)
client.on_async(EventChannel.ZONE_UPDATE, my_async_handler)

# Sync callbacks (still supported, still work)
client.on(EventChannel.ZONE_UPDATE, my_sync_handler)

client.connect()
```

### Version Strategy

- **v1.1.x**: Current release (sync-only, public diagnostics API).
- **v1.2.0**: Add `AsyncCallbackAdapter`, `on_async()`, `EventLoopAdapter`. No
  breaking changes. Sync callbacks remain the default.
- **v2.0.0** (future): Deprecate sync callbacks when adapter is present. Consider
  making `async_adapter` required for new consumers.

---

## 6. Async Token Refresh Interface

The token refresh callback is the most complex migration because it requires a
**return value** from an async operation. The background thread must wait for the
event loop to complete the async API call and return the result.

### Current Interface (Sync)

```python
# Current: sync callback invoked from TokenManager background thread
# Consumer blocks on run_coroutine_threadsafe to get async result
def refresh_token_callback(monitor_id: str | None = None) -> str | None:
    """Called from background thread. Must return new URL or None."""
    future = asyncio.run_coroutine_threadsafe(
        api_client.async_get_monitor_livestream(monitor_id),
        hass.loop,
    )
    result = future.result(timeout=30.0)  # Blocks background thread
    return result.get("brokerUrl")
```

### New Async Interface

```python
# New: async callback scheduled on the event loop
# TokenManager uses adapter.schedule_with_result() to get the return value
async def async_refresh_token(monitor_id: str) -> str | None:
    """
    Async token refresh callback.

    Called when the MQTT transport's JWT token is about to expire.
    The implementation fetches a fresh websocket URL with new credentials
    from the backend API.

    Args:
        monitor_id: The monitor ID that needs a fresh token.

    Returns:
        New websocket URL (including fresh JWT) or None on failure.
        Returning None signals the transport to back off and retry later.
    """
    try:
        livestream_data = await api_client.async_get_monitor_livestream(monitor_id)
        return livestream_data.get("brokerUrl")
    except Exception:
        return None
```

### TokenManager Changes

```python
class TokenManager:
    """Updated token manager with async refresh support."""

    def __init__(
        self,
        token_refresh_callback: Callable[[], dict] | None = None,
        async_token_refresh_callback: Callable[[str], Coroutine[Any, Any, str | None]] | None = None,
        async_adapter: AsyncCallbackAdapter | None = None,
        refresh_threshold_minutes: int = 15,
    ):
        self._token_refresh_callback = token_refresh_callback
        self._async_token_refresh_callback = async_token_refresh_callback
        self._async_adapter = async_adapter
        # ... rest of init ...

    def refresh_token(self) -> dict:
        """
        Refresh the token using sync or async callback.

        If async callback + adapter are available, uses schedule_with_result()
        to invoke the async refresh on the event loop and block for the result.
        Otherwise falls back to the sync callback.
        """
        if (
            self._async_token_refresh_callback
            and self._async_adapter
            and self._async_adapter.is_running()
        ):
            # Use async path: schedule coroutine and wait for result
            coro = self._async_token_refresh_callback(self._monitor_id)
            new_url = self._async_adapter.schedule_with_result(coro, timeout=30.0)
            if not new_url:
                raise TokenRefreshError("Async token refresh returned None")
            return {"broker_url": new_url}

        elif self._token_refresh_callback:
            # Legacy sync path (unchanged)
            new_token = self._token_refresh_callback()
            if not new_token:
                raise TokenRefreshError("Token refresh callback returned None")
            return new_token

        else:
            raise TokenRefreshError("No token refresh callback configured")
```

### MqttTransporter Changes

```python
class MqttTransporter:
    """Updated transporter constructor."""

    def __init__(
        self,
        broker_url: str,
        monitor_id: str,
        token_refresh_callback: Callable[[str | None], str | None] | None = None,
        async_token_refresh_callback: Callable[[str], Coroutine[Any, Any, str | None]] | None = None,
        async_adapter: AsyncCallbackAdapter | None = None,
    ):
        # Pass async callback + adapter through to TokenManager
        self._token_manager = TokenManager(
            token_refresh_callback=token_refresh_callback,
            async_token_refresh_callback=async_token_refresh_callback,
            async_adapter=async_adapter,
        )
```

### HA Integration Usage (After Migration)

```python
# In coordinator.py or connection_manager.py
async def _create_async_token_refresh(self, monitor_id: str) -> str | None:
    """Async token refresh — no thread bridging needed."""
    entry = self.hass.config_entries.async_get_entry(self.entry_id)
    if not entry:
        return None

    api_client = entry.runtime_data.api_client
    livestream_data = await api_client.async_get_monitor_livestream(monitor_id)
    return livestream_data.get("brokerUrl")

# At connection setup time:
adapter = EventLoopAdapter(hass.loop)
transporter = MqttTransporter(
    broker_url=websocket_url,
    monitor_id=monitor_id,
    async_token_refresh_callback=self._create_async_token_refresh,
    async_adapter=adapter,
)
```

---

## 7. Async Zone Update Interface

Zone updates are the most frequent callback type. The async interface allows
consumers to handle zone data directly on their event loop without bridging.

### Current Interface (Sync)

```python
# Called from MQTT handler background thread
def on_zone_update(zones: dict[ZoneType, list[AbstractZone]]) -> None:
    """Sync callback — must bridge to event loop manually."""
    new_data = {**coordinator.data, "zones": zones, "status": "active"}
    asyncio.run_coroutine_threadsafe(
        coordinator._async_handle_zone_update(new_data),
        hass.loop,
    )
```

### New Async Interface

```python
async def on_zone_update(zones: dict[ZoneType, list[AbstractZone]]) -> None:
    """
    Async zone update callback.

    Invoked directly on the consumer's event loop when zone data changes.
    No thread bridging required — the AsyncCallbackAdapter handles dispatch.

    Args:
        zones: Dictionary mapping ZoneType to list of AbstractZone instances.
               Contains the complete current zone state (not a delta).
    """
    new_data = {
        **coordinator.data,
        "zones": zones,
        "status": "active",
    }
    coordinator.async_set_updated_data(new_data)
```

### Registration

```python
# Using the new on_async API
client.on_async(EventChannel.ZONE_UPDATE, on_zone_update)

# Or using the convenience method
client.on_zone_update_async(on_zone_update)
```

### HA Integration Usage (After Migration)

```python
class GeckoConnectionManager:
    """Updated connection manager using async zone callbacks."""

    def _setup_client_handlers(self, gecko_client, connection, monitor_id):
        coordinator = self._coordinators.get(monitor_id)

        # Register async zone handler — runs directly on hass.loop
        async def async_on_zone_update(
            updated_zones: dict[ZoneType, list[AbstractZone]],
        ) -> None:
            if coordinator:
                new_data = {
                    **coordinator.data,
                    "zones": updated_zones,
                    "status": "active",
                }
                coordinator.async_set_updated_data(new_data)

        # Register async connectivity handler
        async def async_on_connectivity_update(
            connectivity_status: ConnectivityStatus,
        ) -> None:
            connection.connectivity_status = connectivity_status
            connection.is_connected = bool(connectivity_status.transport_connected)

            if coordinator:
                new_data = {
                    **coordinator.data,
                    "connectivity": connectivity_status,
                    "status": (
                        "active"
                        if connectivity_status.is_fully_connected
                        else "disconnected"
                    ),
                }
                coordinator.async_set_updated_data(new_data)

        # Use async registration — no call_soon_threadsafe needed
        gecko_client.on_async(EventChannel.ZONE_UPDATE, async_on_zone_update)
        gecko_client.on_async(
            EventChannel.CONNECTIVITY_UPDATE, async_on_connectivity_update
        )
```

### Benefits Over Current Approach

1. **No `call_soon_threadsafe`**: The adapter handles thread-to-loop dispatch.
2. **Exception visibility**: Exceptions in async handlers are logged by the adapter,
   not silently swallowed on a background thread.
3. **Natural async**: The handler is a normal coroutine — can `await` other async
   operations if needed.
4. **Testability**: In tests, the adapter can be mocked to invoke callbacks
   synchronously for deterministic test execution.

---

## 8. Implementation Timeline and Phasing

### Phase 1: Adapter Foundation (v1.2.0)

**Duration**: 1-2 weeks
**Breaking changes**: None

| Task | Description | Effort |
|------|-------------|--------|
| 1.1 | Implement `AsyncCallbackAdapter` ABC | S |
| 1.2 | Implement `EventLoopAdapter` default | S |
| 1.3 | Add `async_adapter` parameter to `GeckoIotClient.__init__` | S |
| 1.4 | Extend `EventEmitter` with `on_async`, `off_async`, async dispatch | M |
| 1.5 | Add `on_async()` and `off_async()` to `GeckoIotClient` | S |
| 1.6 | Add `on_zone_update_async()` convenience method | S |
| 1.7 | Unit tests for adapter and async event dispatch | M |
| 1.8 | Integration tests simulating HA usage pattern | M |
| 1.9 | Update Sphinx API docs | S |

**Deliverable**: `gecko-iot-client v1.2.0` on PyPI. Consumers can start using
`on_async()` while sync callbacks continue to work.

**Verification**: HA integration can optionally switch to `on_async()` for zone and
connectivity updates. If successful, removes `call_soon_threadsafe` for those paths.

---

### Phase 2: Migrate Callbacks (v1.3.0)

**Duration**: 2-3 weeks
**Breaking changes**: None (async paths are additive)

| Task | Description | Effort |
|------|-------------|--------|
| 2.1 | Add `async_token_refresh_callback` to `MqttTransporter` | M |
| 2.2 | Update `TokenManager` to support async refresh via adapter | M |
| 2.3 | Add `schedule_with_result()` implementation + tests | M |
| 2.4 | Migrate HA token refresh to async interface | M |
| 2.5 | Add async operation mode callback support | S |
| 2.6 | Add async configuration loaded callback (internal) | S |
| 2.7 | Update HA `connection_manager.py` to use all async callbacks | L |
| 2.8 | Remove `run_coroutine_threadsafe` from HA coordinator | M |
| 2.9 | Remove `call_soon_threadsafe` from HA connection_manager | M |
| 2.10 | End-to-end testing with HA integration | L |

**Deliverable**: `gecko-iot-client v1.3.0`. HA integration fully migrated to async
callbacks. Zero `run_coroutine_threadsafe` or `call_soon_threadsafe` in HA code.

**Verification**: All HA integration tests pass. Manual testing confirms real-time
updates work correctly via MQTT → async callback → coordinator → entities.

---

### Phase 3: Remove Sync Bridge (v2.0.0 — Future)

**Duration**: 1-2 weeks (after stabilization period)
**Breaking changes**: Yes (major version bump)

| Task | Description | Effort |
|------|-------------|--------|
| 3.1 | Add deprecation warnings to `on()` when adapter is present | S |
| 3.2 | Announce deprecation timeline in CHANGELOG | S |
| 3.3 | Remove sync `token_refresh_callback` parameter | M |
| 3.4 | Make `async_adapter` required in `GeckoIotClient.__init__` | S |
| 3.5 | Remove legacy `on_zone_update()` sync method | S |
| 3.6 | Simplify `EventEmitter` (async-only paths) | M |
| 3.7 | Update all examples and documentation | M |
| 3.8 | Release as v2.0.0 with migration guide | S |

**Deliverable**: `gecko-iot-client v2.0.0`. Clean async-only interface. Consumers
that haven't migrated must pin to v1.x.

**Note**: Phase 3 is optional and should only be executed after Phase 2 has been
stable in production for at least 2-3 months. The dual interface (Phase 2 state) is
acceptable for HA core submission.

---

### Dependency Graph

```
Phase 1 (Adapter)         Phase 2 (Migrate)         Phase 3 (Remove)
─────────────────         ─────────────────         ────────────────
AsyncCallbackAdapter  ──► async token refresh  ──► remove sync token refresh
EventLoopAdapter      ──► HA migration         ──► make adapter required
on_async() API        ──► remove thread bridge ──► remove on() sync path
EventEmitter async    ──► end-to-end tests     ──► v2.0.0 release
```

### Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Event loop not running when callback fires | `is_running()` check in adapter; fallback to sync if loop is gone |
| Deadlock in `schedule_with_result()` | Configurable timeout (default 30s); log + raise on timeout |
| Ordering of sync vs async callbacks | Document: sync fires first, then async is scheduled (not guaranteed same tick) |
| Backward compat for CLI consumers | Sync path is default when no adapter; never removed in v1.x |
| Thread safety of `async_set_updated_data` | HA's DataUpdateCoordinator is thread-safe via `call_soon_threadsafe` internally |

---

## Appendix A: File Inventory (Changes Required)

### gecko-iot-client

| File | Changes |
|------|---------|
| `src/gecko_iot_client/__init__.py` | Add `async_adapter` param, `on_async()`, `off_async()`, `on_zone_update_async()` |
| `src/gecko_iot_client/models/events.py` | Add `on_async()`, `off_async()`, async dispatch in `emit()` |
| `src/gecko_iot_client/transporters/token_manager.py` | Add `async_token_refresh_callback`, use adapter for async refresh |
| `src/gecko_iot_client/transporters/mqtt/__init__.py` | Add `async_token_refresh_callback` + `async_adapter` params |
| `src/gecko_iot_client/adapters/__init__.py` | New module: `AsyncCallbackAdapter`, `EventLoopAdapter` |
| `tests/test_async_adapter.py` | New: unit tests for adapter |
| `tests/test_async_events.py` | New: tests for on_async dispatch |
| `docs/source/async_migration_design.md` | This document |
| `docs/source/api.rst` | Update API reference for new methods |

### ha-gecko-integration (consumer changes, Phase 2)

| File | Changes |
|------|---------|
| `custom_components/gecko/connection_manager.py` | Replace `call_soon_threadsafe` with `on_async()` registration |
| `custom_components/gecko/coordinator.py` | Remove `run_coroutine_threadsafe` bridge, use async callbacks |
| `custom_components/gecko/__init__.py` | Create `EventLoopAdapter(hass.loop)` at setup, pass to client |

---

## Appendix B: Decision Log

| Decision | Rationale |
|----------|-----------|
| Adapter pattern over direct loop injection | Decouples library from asyncio internals; testable; allows non-asyncio consumers |
| `on_async` vs replacing `on` | Backward compatible; no breaking changes in v1.x |
| `schedule_with_result` blocks calling thread | Necessary for token refresh where MQTT thread needs the new URL before proceeding |
| Sync callbacks fire before async are scheduled | Ensures existing sync consumers see data first; async consumers get eventual delivery |
| Phase 3 is optional for HA core submission | Dual interface (Phase 2) meets NFR-9 acceptance criteria |
