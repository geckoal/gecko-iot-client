# gecko-iot-client — Architecture & Evaluation

## Overview

`gecko-iot-client` is a standalone Python library published to PyPI that provides communication with Gecko IoT devices (spas, hot tubs, pool equipment) via AWS IoT Core over MQTT/WebSocket. It offers an event-driven, zone-based API for real-time device control and state synchronization.

```mermaid
graph TB
    subgraph "Consumer Application"
        APP[Application / Home Assistant]
        AA[AsyncCallbackAdapter<br/>Thread → Event Loop Bridge]
    end

    subgraph "gecko-iot-client"
        GC[GeckoIotClient<br/>Main Entry Point]
        EE[EventEmitter<br/>Pub/Sub Event System]
        ZP[ZoneConfigurationParser]
        ZC[Zone Control<br/>Publish Desired State]

        subgraph "Domain Models"
            AZ[AbstractZone]
            TCZ[TemperatureControlZone]
            LZ[LightingZone]
            FZ[FlowZone]
            OMC[OperationModeController]
            CS[ConnectivityStatus]
        end

        subgraph "Transport Layer"
            AT[AbstractTransporter<br/>Interface]
            MT[MqttTransporter<br/>Gecko Business Logic]
            MC[MqttClient<br/>AWS IoT MQTT5 Protocol]
            TM[TokenManager<br/>JWT Expiry Tracking]
            RH[ReconnectionHandler<br/>Exponential Backoff]
            CR[CallbackRegistry<br/>Thread-safe]
        end
    end

    subgraph "AWS IoT Core"
        BROKER[MQTT Broker<br/>Custom Authorizer]
        SHADOW[Device Shadow<br/>Config + State]
    end

    subgraph "Hardware"
        GW[Gecko Gateway]
        SPA[Spa / Hot Tub]
    end

    APP --> GC
    APP --> AA
    AA --> EE

    GC --> EE
    GC --> ZP
    GC --> ZC
    ZP --> AZ
    AZ --> TCZ
    AZ --> LZ
    AZ --> FZ
    GC --> OMC
    GC --> CS

    GC --> AT
    AT --> MT
    MT --> MC
    MT --> TM
    MT --> RH
    MT --> CR

    MC -.->|MQTT5 over WSS| BROKER
    BROKER --> SHADOW
    SHADOW -.-> GW
    GW -.-> SPA
```

---

## Key Concepts

### 1. GeckoIotClient — The Facade

`GeckoIotClient` is the single entry point for consumers. It orchestrates:

- Connection lifecycle (connect/disconnect via transporter)
- Configuration loading and zone parsing
- State change processing and distribution
- Event registration (sync and async callbacks)
- Zone control setup (binding publish callbacks to zones)
- Diagnostics API

```python
# Minimal usage
with GeckoIotClient("monitor-id", transporter) as client:
    client.on(EventChannel.ZONE_UPDATE, my_handler)
    zones = client.get_zones()
```

### 2. Zone-Based Domain Model

All controllable features are modeled as **zones** — a polymorphic hierarchy with a decorator-based registry.

```mermaid
classDiagram
    class AbstractZone {
        +id: str
        +name: str
        +zone_type: ZoneType
        +config: dict
        -_publish_callback: Callable
        +set_publish_callback(callback)
        +update_from_state(state)
        +update_from_config(config)
        +_publish_desired_state(updates)
        +_get_runtime_state_fields() set
        +_get_field_mappings() dict
        +to_config() dict
        +to_state_dict() dict
        +from_config(zone_id, config, zone_type)$
        +register_zone_type(zone_type)$
    }

    class TemperatureControlZone {
        +temperature_: float
        +set_point: float
        +status_: TemperatureControlZoneStatus
        +mode_: TemperatureControlMode
        +min_temperature_set_point_c: float
        +max_temperature_set_point_c: float
        +set_target_temperature(temp)
        +get_temperature_state() dict
    }

    class LightingZone {
        +active: bool
        +rgbi: RGB
        +effect: str
        +activate()
        +deactivate()
        +set_color(r, g, b, i)
        +set_effect(effect_name)
        +get_lighting_state() dict
    }

    class FlowZone {
        +active: bool
        +speed: float
        +initiators_: list[FlowZoneInitiator]
        +capabilities: list[FlowZoneCapabilities]
        +presets: list[FlowZonePreset]
        +type: FlowZoneType
        +activate()
        +deactivate()
        +set_speed(speed, active)
        +get_flow_state() dict
    }

    class OperationModeController {
        +operation_mode: OperationMode
        +mode_name: str
        +is_energy_saving: bool
        +set_mode(mode)
        +set_mode_by_name(name)
        +set_mode_by_value(value)
        +update_from_state_data(state) bool
    }

    AbstractZone <|-- TemperatureControlZone
    AbstractZone <|-- LightingZone
    AbstractZone <|-- FlowZone
```

**Zone Types:**

| Zone Type | Enum Value | Capabilities |
|-----------|-----------|--------------|
| TemperatureControlZone | `temperatureControl` | Current temp, target temp, heating status, eco mode, min/max limits |
| LightingZone | `lighting` | On/off, RGB+intensity color, named effects |
| FlowZone | `flow` | On/off, variable speed, presets, initiator tracking, sub-types (pump/waterfall/blower) |

**Registry Pattern:**

```python
@AbstractZone.register_zone_type(ZoneType.FLOW_ZONE)
class FlowZone(AbstractZone): ...
```

This allows `ZoneConfigurationParser` to instantiate the correct class based on the `zone_type` key in device configuration without explicit if/else chains.

### 3. Event System

```mermaid
graph LR
    subgraph "EventEmitter"
        CH_ZONE[ZONE_UPDATE]
        CH_CONN[CONNECTIVITY_UPDATE]
        CH_OP[OPERATION_MODE_UPDATE]
        CH_SENSOR[SENSOR_UPDATE]
        CH_STATE[STATE_UPDATE]
        CH_CONFIG[CONFIGURATION_UPDATE]
    end

    subgraph "Sync Callbacks (background thread)"
        SC1[callback_1]
        SC2[callback_2]
    end

    subgraph "Async Callbacks (event loop)"
        AC1[async_handler_1]
        AC2[async_handler_2]
    end

    subgraph "AsyncCallbackAdapter"
        ELA[EventLoopAdapter]
    end

    CH_ZONE --> SC1
    CH_ZONE --> SC2
    CH_ZONE --> ELA
    ELA -->|run_coroutine_threadsafe| AC1
    ELA -->|run_coroutine_threadsafe| AC2
```

**EventChannel enum:**
- `CONNECTIVITY_UPDATE` — transport/gateway/vessel status changes
- `OPERATION_MODE_UPDATE` — watercare mode changes
- `ZONE_UPDATE` — zone configuration or runtime state changes
- `SENSOR_UPDATE`, `STATE_UPDATE`, `CONFIGURATION_UPDATE` — reserved for future use

**Dual callback support:**
- `client.on(channel, sync_callback)` — called directly on the emitting thread
- `client.on_async(channel, async_callback)` — dispatched to consumer's event loop via adapter

### 4. Transport Layer Architecture

```mermaid
graph TB
    subgraph "AbstractTransporter Interface"
        CONNECT[connect/disconnect]
        PUB[publish_desired_state]
        LOAD[load_configuration / load_state]
        CB[on_state_change / on_connectivity_change / on_configuration_loaded / on_state_loaded]
    end

    subgraph "MqttTransporter (Gecko Business Logic)"
        TOPICS[Topic Builder: $aws/things/{monitor_id}/...]
        CONFIG_FLOW[Config Request/Response]
        STATE_FLOW[Shadow Get/Update/Documents]
        TOKEN[Token Refresh + Reconnection]
    end

    subgraph "MqttClient (Protocol Layer)"
        MQTT5[AWS CRT MQTT5 Client]
        PARSE[WebSocket URL Parser]
        ROUTE[Message Router → Topic Handlers]
        LIFECYCLE[Connection Lifecycle Callbacks]
    end

    CONNECT --> TOPICS
    PUB --> STATE_FLOW
    LOAD --> CONFIG_FLOW
    CB --> TOKEN

    TOPICS --> MQTT5
    CONFIG_FLOW --> MQTT5
    STATE_FLOW --> MQTT5
    TOKEN --> MQTT5
    MQTT5 --> PARSE
    MQTT5 --> ROUTE
    MQTT5 --> LIFECYCLE
```

The transport is split into two layers:

| Layer | Class | Responsibility |
|-------|-------|---------------|
| Business Logic | `MqttTransporter` | Gecko topic structure, shadow operations, token management, retry orchestration |
| Protocol | `MqttClient` | MQTT5 connect/publish/subscribe, URL parsing, message routing, lifecycle events |

### 5. AWS IoT Shadow Integration

The library communicates with Gecko devices via AWS IoT Device Shadows:

```mermaid
sequenceDiagram
    participant Client as GeckoIotClient
    participant MT as MqttTransporter
    participant IOT as AWS IoT Core
    participant Device as Gecko Gateway

    Note over Client,Device: Initialization Flow
    Client->>MT: connect()
    MT->>IOT: MQTT5 WSS (custom authorizer)
    IOT-->>MT: CONNACK
    MT->>IOT: Subscribe to config/get/accepted, shadow topics
    Client->>MT: load_configuration(timeout)
    MT->>IOT: Publish to $aws/things/{id}/config/get
    IOT-->>MT: config/get/accepted (zone config)
    MT->>Client: on_configuration_loaded(config)
    Client->>Client: parse zones → setup zone control

    Note over Client,Device: State Synchronization
    Client->>MT: load_state()
    MT->>IOT: Publish to shadow/name/state/get
    IOT-->>MT: shadow/name/state/get/accepted
    MT->>Client: on_state_loaded(shadow_data)
    Client->>Client: apply_state_to_zones + emit events

    Note over Client,Device: Real-time Updates (Push)
    Device->>IOT: Shadow update (state change)
    IOT-->>MT: shadow/name/state/update/documents
    MT->>Client: on_state_change(new_state)
    Client->>Client: process_state_updates → emit ZONE_UPDATE

    Note over Client,Device: Control Commands
    Client->>Client: zone.set_target_temperature(25)
    Client->>MT: publish_desired_state({zones: {...}})
    MT->>IOT: Publish to shadow/name/state/update
    IOT->>Device: Desired state delta
    Device->>IOT: Shadow reported update
    IOT-->>MT: update/documents (confirmation)
```

**Topic Structure:**

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `$aws/things/{id}/config/get` | Publish | Request device configuration |
| `$aws/things/{id}/config/get/accepted` | Subscribe | Configuration response |
| `$aws/things/{id}/shadow/name/state/get` | Publish | Request current state |
| `$aws/things/{id}/shadow/name/state/get/accepted` | Subscribe | State response |
| `$aws/things/{id}/shadow/name/state/update` | Publish | Set desired state |
| `$aws/things/{id}/shadow/name/state/update/documents` | Subscribe | Real-time state changes |

### 6. Token Management & Reconnection

```mermaid
stateDiagram-v2
    [*] --> Connected
    Connected --> TokenRefresh: token within buffer (proactive)
    Connected --> Disconnected: unexpected disconnect (valid token)
    Connected --> TokenRefreshThenReconnect: unexpected disconnect (expired token)

    TokenRefresh --> Connected: refresh + reconnect success
    TokenRefresh --> RefreshRetry: callback returned None / exception
    RefreshRetry --> TokenRefresh: backoff elapsed (30s→300s)
    RefreshRetry --> GaveUp: 10 consecutive failures

    Disconnected --> Reconnecting: schedule_reconnect
    Reconnecting --> Connected: connect success
    Reconnecting --> Reconnecting: backoff retry (1s→60s)
    Reconnecting --> CooldownRefresh: 5 attempts exhausted
    CooldownRefresh --> TokenRefresh: 5 min cooldown elapsed

    TokenRefreshThenReconnect --> Connected: refresh + reconnect success
    TokenRefreshThenReconnect --> RefreshRetry: refresh failed

    GaveUp --> Connected: next successful connection resets
```

**Token Lifecycle:**
1. `TokenManager` parses JWT from broker URL at construction
2. Background thread checks expiry every 10 seconds
3. When `time_to_expiry <= refresh_buffer_seconds`: triggers refresh
4. Refresh path: invoke callback → get new URL → disconnect → reconnect with fresh URL
5. On failure: progressive backoff (30s × 2^(n-1), max 300s)
6. After 10 consecutive failures: stops retrying until next manual reconnect

**Reconnection Strategy:**
- `ReconnectionHandler`: exponential backoff (1s → 2s → 4s → ... → 60s max)
- Max 5 attempts before entering cooldown
- Cooldown: waits 5 minutes then forces a token refresh
- Connectivity callbacks are **suppressed** during refresh/reconnect to prevent UI flicker

### 7. AsyncCallbackAdapter (Thread Bridge)

```mermaid
sequenceDiagram
    participant BG as Background Thread<br/>(MQTT callbacks)
    participant EE as EventEmitter
    participant ACA as AsyncCallbackAdapter
    participant LOOP as Consumer Event Loop
    participant HANDLER as Async Handler

    BG->>EE: emit(ZONE_UPDATE, data)
    Note over EE: Sync callbacks called directly on BG thread
    EE->>ACA: schedule(async_handler(data))
    ACA->>LOOP: run_coroutine_threadsafe(coro)
    LOOP->>HANDLER: await async_handler(data)

    Note over BG,HANDLER: For token refresh (needs return value)
    BG->>ACA: schedule_with_result(coro, timeout=30)
    ACA->>LOOP: run_coroutine_threadsafe(coro)
    LOOP->>HANDLER: result = await coro
    HANDLER-->>ACA: return result
    ACA-->>BG: future.result() → unblocks thread
```

Two implementations:
- `AsyncCallbackAdapter` (ABC) — defines the interface
- `EventLoopAdapter` — concrete implementation using `asyncio.run_coroutine_threadsafe`

This abstraction allows the library to work with any event loop framework, not just asyncio.

### 8. Zone Configuration Parsing

```mermaid
flowchart TD
    RAW[Raw Config from Device] --> ZP[ZoneConfigurationParser]
    ZP --> EXTRACT[Extract value from metadata<br/>value > currentValue > default > minimum]
    EXTRACT --> CREATE[Create zone instances<br/>via registered classes]
    CREATE --> ZONES[Dict~ZoneType → List~AbstractZone~~]

    STATE[Shadow State Data] --> APPLY[apply_state_to_zones]
    APPLY --> MATCH[Match zone by ID]
    MATCH --> UPDATE[zone.update_from_state]
    UPDATE --> FIELDS[Apply field mappings<br/>isActive→active, flowSpeed→speed, etc.]
```

Two distinct update paths:
1. **Configuration** (structure/limits) → `parse_zones_configuration()` → creates zone instances
2. **Runtime State** (current values) → `apply_state_to_zones()` → updates existing instances

Each zone defines `_get_field_mappings()` to translate device-side names to Python attributes:
```python
# FlowZone mappings
{"isActive": "active", "flowSpeed": "speed", "pumpSpeed": "speed", "running": "active"}
```

### 9. Zone Control (Desired State Publishing)

When a consumer calls a control method (e.g., `zone.set_target_temperature(25)`):

```mermaid
sequenceDiagram
    participant Consumer
    participant Zone as TemperatureControlZone
    participant GC as GeckoIotClient
    participant MT as MqttTransporter
    participant IOT as AWS IoT

    Consumer->>Zone: set_target_temperature(25.0)
    Zone->>Zone: validate(min ≤ 25 ≤ max)
    Zone->>Zone: self.set_point = 25.0
    Zone->>GC: _publish_desired_state({"setPoint": 25})
    Note over Zone,GC: via zone_callback(zone_type, zone_id, updates)
    GC->>GC: build desired = {zones: {temperatureControl: {id: {setPoint: 25}}}}
    GC->>MT: publish_desired_state(desired)
    MT->>IOT: Publish to shadow/name/state/update
    Note over MT: future.result(timeout=5) → wait for PUBACK
    IOT-->>MT: PUBACK confirmation
    GC->>GC: log "✅ Published desired state"
```

The publish path validates connectivity before sending and blocks for delivery confirmation (PUBACK).

---

## Features Summary

| Feature | Implementation |
|---------|---------------|
| AWS IoT MQTT5 | `awscrt` + `awsiot` via custom authorizer (WebSocket + JWT) |
| Multi-zone control | Polymorphic zone hierarchy with registry pattern |
| Real-time state sync | Device Shadow subscriptions → push updates via events |
| Async/sync callbacks | `EventEmitter` with `AsyncCallbackAdapter` bridge |
| Async zone control | `async_*` methods on all zone classes + `OperationModeController` |
| Token management | Proactive refresh with progressive backoff |
| Reconnection | Exponential backoff (5 attempts → cooldown → forced refresh) |
| Connectivity tracking | `ConnectivityStatus` (transport + gateway + vessel) |
| Operation modes | `OperationModeController` (Away, Standard, Savings, etc.) |
| Diagnostics API | `get_diagnostics()` method for observability |
| Context manager | `with GeckoIotClient(...) as client:` lifecycle |
| Type safety | Full type hints, `py.typed` marker |
| Extensibility | `AbstractTransporter` ABC for alternative protocols |
| Dependency injection | `MqttTransporter` accepts optional injected components |
| Structured logging | Key log calls include `extra={}` fields for observability |

---

## Package Structure

```
gecko_iot_client/
├── src/gecko_iot_client/
│   ├── __init__.py              # GeckoIotClient facade + public API exports
│   ├── api.py                   # GeckoApiClient ABC (HTTP REST client)
│   ├── async_adapter.py         # AsyncCallbackAdapter + EventLoopAdapter
│   ├── const.py                 # Library constants
│   ├── models/
│   │   ├── __init__.py          # Model re-exports
│   │   ├── abstract_zone.py    # AbstractZone base + ZoneType enum + registry
│   │   ├── connectivity.py     # ConnectivityStatus (transport/gateway/vessel)
│   │   ├── events.py           # EventChannel + EventEmitter
│   │   ├── flow_zone.py        # FlowZone + presets + capabilities + initiators
│   │   ├── lighting_zone.py    # LightingZone + RGB
│   │   ├── operation_mode.py           # OperationMode enum
│   │   ├── operation_mode_controller.py # Read/write controller for watercare
│   │   ├── temperature_control_zone.py # TemperatureControlZone + status enum
│   │   ├── zone_parser.py      # ZoneConfigurationParser
│   │   └── zone_types.py       # Convenience re-export of all zone types
│   └── transporters/
│       ├── __init__.py          # AbstractTransporter ABC
│       ├── exceptions.py        # Exception hierarchy
│       ├── logging_config.py    # Logging configuration
│       ├── token_manager.py     # JWT parsing + expiry tracking
│       └── mqtt/
│           ├── __init__.py      # MqttTransporter + MqttClient exports
│           ├── callback_registry.py  # Thread-safe callback storage
│           ├── client.py        # MqttClient (low-level MQTT5)
│           ├── constants.py     # Timeouts, backoff constants
│           ├── reconnection_handler.py # Exponential backoff logic
│           ├── token_manager.py # JWT parsing + expiry tracking (MQTT-specific)
│           ├── transporter.py   # MqttTransporter (Gecko business logic, DI-ready)
│           └── utils.py         # JSON parsing, future helpers, callback dispatch
├── tests/                       # 17 test modules
├── examples/demo.py             # Interactive demo script
├── docs/                        # Sphinx documentation source
├── pyproject.toml               # Build config (setuptools + setuptools-scm)
└── pytest.ini                   # Test configuration (markers: unit, integration, slow)
```

---

## Senior Architect Evaluation

### Strengths

1. **Clean layered architecture** — The separation between `MqttClient` (protocol) and `MqttTransporter` (business logic) is excellent. Each has a focused responsibility and can be tested independently.

2. **Framework-agnostic design** — The `AsyncCallbackAdapter` abstraction means the library doesn't depend on any specific event loop framework. It works equally well with Home Assistant, a standalone asyncio script, or a different runtime.

3. **Thoughtful zone model** — The registry pattern with decorators provides clean extensibility. Adding a new zone type requires only a new class with `@register_zone_type`. The separation of config parsing vs. runtime state updates via `_get_field_mappings()` handles the impedance mismatch between device naming and Python conventions.

4. **Robust token lifecycle** — The proactive refresh (before expiry), progressive backoff on failure, and the escalation path (refresh → reconnect → cooldown → forced refresh) show production hardening.

5. **Good event semantics** — `EventChannel` provides clear categorization, and the emit/on/off API is simple. Supporting both sync and async callbacks with suppression during internal operations (refresh/reconnect) prevents state thrashing.

6. **Publish confirmation** — Waiting for PUBACK (`future.result(timeout=5)`) before logging success ensures the message actually reached the broker, not just the local send buffer.

7. **Diagnostics API** — The `get_diagnostics()` method provides a structured snapshot without exposing internals, making it safe for external consumers (like the HA integration's diagnostics dump).

8. **Good test coverage** — 17 test modules covering reconnection flows, token management, zone parsing, event system, and edge cases. Tests use proper mocking to isolate the MQTT layer.

### Areas for Improvement — Status

#### 1. Threading Model Should Be Async-Native (High Priority) — PLANNED

**Status:** Deferred for a future major version.

The transport layer uses 4–5 daemon threads for expiry monitoring, reconnection, token refresh retries, and post-connection setup. While this works reliably, it creates complexity with locks, events, and potential race conditions.

**Migration plan:** Since `awscrt`'s MQTT5 client already manages its own I/O thread internally, the additional threading is unnecessary in principle. A full migration to asyncio-native scheduling (`asyncio.create_task` + `asyncio.sleep`) would eliminate locks and simplify testing. However, this is a significant refactor affecting the entire transport layer and will be addressed in a dedicated effort.

#### 2. `AbstractTransporter` Should Use ABC — ✅ RESOLVED

`AbstractTransporter` now inherits from `ABC` and all methods are decorated with `@abstractmethod`. mypy catches missing implementations at analysis time.

#### 3. `_publish_callback` Is a Class Variable — ✅ RESOLVED

`_publish_callback` is now an instance variable initialized in `AbstractZone.__init__()`. No class-level mutable state.

#### 4. Async API for Zone Control Methods — ✅ RESOLVED

All zone classes and `OperationModeController` now provide `async_*` variants of their control methods:
- `TemperatureControlZone.async_set_target_temperature()`
- `LightingZone.async_set_color()`, `async_set_effect()`, `async_activate()`, `async_deactivate()`
- `FlowZone.async_set_speed()`, `async_activate()`, `async_deactivate()`
- `OperationModeController.async_set_mode()`

These use `_async_publish_desired_state()` on `AbstractZone` which dispatches via an async publish callback or falls back to `run_in_executor()` with the sync callback.

#### 5. `ConnectionStateManager` Is Unused — ✅ RESOLVED

`ConnectionStateManager` and `connection_state.py` have been removed from the source package. The actual state management in `MqttTransporter` uses `_is_reconnecting` / `_is_refreshing_token` flags with `ReconnectionHandler`.

#### 6. Duplicate `OperationModeStatus` — ✅ RESOLVED

`OperationModeStatus` has been removed. `OperationModeController` is the single source of truth for operation mode state and control.

#### 7. Dependency Injection for MqttClient — ✅ RESOLVED

`MqttTransporter.__init__` now accepts optional keyword-only parameters:
- `mqtt_client: MqttClient | None`
- `token_manager: TokenManager | None`
- `reconnection_handler: ReconnectionHandler | None`

When not provided, defaults are created as before. This enables proper unit testing without class-level patching.

#### 8. Zone `config` Stores Raw Config Indefinitely — ✅ RESOLVED (FlowZone)

`FlowZone` now extracts `_speed_config` and `_flow_zone_type` at `__init__` time rather than re-deriving from `self.config` on every property access. The `speed_config` and `type` properties return pre-computed values.

Note: `self.config` is still stored on `AbstractZone` for backward compatibility and `update_from_config()` support. A future iteration could freeze or remove it entirely.

#### 9. GeckoApiClient Lives in the IoT Client Library — ✅ RESOLVED (documented)

`aiohttp` is declared as a required dependency in `pyproject.toml`. The module docstring on `api.py` now documents the design rationale: consumers typically need both MQTT real-time communication and REST API access, so bundling them in a single library reduces integration friction.

#### 10. Structured Logging — ✅ RESOLVED (incremental)

Key log calls in `MqttTransporter` now pass structured fields via `extra={}`:
- Token refresh timing (`monitor_id`, `time_to_expiry`)
- Callback duration (`monitor_id`, `duration_s`)
- Refresh retry scheduling (`monitor_id`, `retry_delay_s`, `failure_count`)
- Connection status changes (`monitor_id`, `connected`)
- Reconnection scheduling (`monitor_id`, `attempt`, `delay_s`)

This enables queryable logs in centralized logging systems without requiring a `structlog` dependency.

---

## Remaining Roadmap

| Item | Priority | Status | Notes |
|------|----------|--------|-------|
| Async-native transport layer | High | Planned | Major refactor — replace threading with asyncio tasks |
| Remove `self.config` from AbstractZone | Low | Planned | Breaking change — needs migration path |
| Full structured logging coverage | Low | In progress | Key paths done; remaining debug logs can be converted incrementally |

---

## Testing Architecture

```
tests/
├── test_api.py                    # GeckoApiClient HTTP methods
├── test_async_adapter.py          # EventLoopAdapter thread bridging
├── test_callback_registry.py      # Thread-safe callback storage
├── test_connectivity.py           # ConnectivityStatus state transitions
├── test_diagnostics_api.py        # get_diagnostics() output structure
├── test_events.py                 # EventEmitter pub/sub behavior
├── test_exceptions.py             # Exception hierarchy
├── test_mqtt_utils.py             # JSON parsing, future helpers
├── test_operation_mode.py         # OperationMode enum conversion
├── test_operation_mode_controller.py  # Mode controller state + commands
├── test_publish_confirmation.py   # PUBACK waiting behavior
├── test_reconnection_flows.py     # Full reconnection orchestration
├── test_reconnection_handler.py   # Exponential backoff math
├── test_token_manager.py          # JWT parsing + expiry tracking
├── test_zone_parser.py            # Config → zone instances
└── test_zone_states.py            # Runtime state application
```

**Test patterns used:**
- `unittest.mock.patch` for isolating MQTT client from network
- Helper functions to generate valid broker URLs with configurable expiry
- Thread timing assertions with `time.sleep` for concurrency tests
- Direct method invocation to test internal flows without threading

---

## Summary

`gecko-iot-client` is a well-architected IoT client library with clean separation of concerns, a thoughtful domain model, and production-grade resilience features. The layered transport design and framework-agnostic async adapter make it suitable for diverse consumers.

The following improvements have been implemented:
- **ABC enforcement** on `AbstractTransporter` — mypy catches missing implementations
- **Instance-level `_publish_callback`** — eliminates class-variable sharing bug
- **Async zone control methods** — consumers can `await zone.async_set_target_temperature()` directly
- **Dead code removal** (`ConnectionStateManager`, `OperationModeStatus`) — single source of truth
- **Dependency injection** on `MqttTransporter` — testable without monkey-patching
- **Config extraction at init** in `FlowZone` — avoids re-deriving from raw config
- **Structured logging** with `extra={}` fields — queryable in centralized systems
- **Documented `GeckoApiClient` placement** — rationale for bundling REST + MQTT

The remaining high-impact improvement is:
1. **Migrate threading to asyncio** — eliminates the largest source of complexity and potential bugs

This change would evolve the transport layer from "works well with careful usage" to a fully async-native design that's simpler to reason about, test, and maintain.
