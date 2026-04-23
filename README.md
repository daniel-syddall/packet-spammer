# Packet Spammer

A self-contained 802.11 WiFi frame injection tool with a browser-based control panel. Runs on a Raspberry Pi (or any Linux SBC) inside Docker. Supports multiple named injection tasks running simultaneously across a pool of USB WiFi adapters.

## Contents

- [How It Works](#how-it-works)
- [Hardware Requirements](#hardware-requirements)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
  - [config/config.toml](#configconfigtoml)
  - [Task Types](#task-types)
  - [Packet Types](#packet-types)
- [Web UI](#web-ui)
- [REST API Reference](#rest-api-reference)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Adding a New Packet Type](#adding-a-new-packet-type)
- [Adding a New Task Type](#adding-a-new-task-type)
- [Dependencies](#dependencies)

---

## How It Works

On startup the system:

1. Scans `/sys/class/net` for **all USB wireless adapters** (built-in Pi WiFi is intentionally skipped).
2. Puts every detected adapter into **monitor mode** and adds it to the **interface pool**.
3. Loads tasks from `config/config.toml` and starts any tasks with `enabled = true`.
4. Splits the pool evenly across enabled tasks — each task gets `floor(N/T)` adapters.
5. Starts a **FastAPI web server** on port `8080` for live monitoring and control.

All configuration is persisted to `config/config.toml`. Changes made through the web UI are written back to disk immediately.

---

## Hardware Requirements

| Component | Notes |
|-----------|-------|
| Raspberry Pi (any model with USB) | Tested target. Any Linux SBC works. |
| **USB WiFi adapter(s)** that support monitor mode and packet injection | e.g. Alfa AWUS036ACH, AWUS036ACS, cards based on RT8812AU, AR9271, MT7612U. The Pi's built-in BCM chip is **not used** — it does not support injection reliably. |
| MicroSD + power | Standard Pi setup. |

> **Important:** Plug in USB WiFi adapters **before** starting the container. Adapters are detected once at startup with a 10-second retry watchdog. If a dongle is plugged in after startup the watchdog will find it automatically.

---

## Quick Start

```bash
# Clone / copy the project onto the Pi, then:
./host.sh          # build the Docker image and start (foreground)
./host.sh -d       # start detached (background)
```

Then open a browser on any device on the same network:

```
http://<pi-ip>:8080
```

`host.sh` installs Docker automatically if it isn't present.

### Autostart on Pi reboot

The container is configured with `restart: unless-stopped` in `docker-compose.yml`, so it comes back automatically after a reboot. Tasks with `enabled = true` in config begin transmitting immediately on container start.

---

## Configuration

### config/config.toml

```toml
[api]
enabled = true
host    = "0.0.0.0"
port    = 8080

[[tasks]]
type               = "standard"
id                 = "demo0001"
name               = "Deauth Flood"
enabled            = false
channel            = 6
packets_per_second = 10
packet             = {type = "deauth", source_mac = "aa:bb:cc:dd:ee:ff", dest_mac = "ff:ff:ff:ff:ff:ff", bssid = "aa:bb:cc:dd:ee:ff", reason = 7}
```

Multiple `[[tasks]]` blocks are supported. The web UI reads and writes this file at runtime.

### Task Types

#### `standard` — Fixed Channel

Injects a single 802.11 frame type at a fixed rate on a fixed channel. One worker thread per allocated interface.

| Field | Type | Description |
|-------|------|-------------|
| `channel` | int | 802.11 channel (1–165) |
| `packets_per_second` | int | Injection rate (1–1000) |
| `packet` | PacketConfig | Frame type and parameters (see below) |

---

#### `span` — Multi-Channel Cycling

Each allocated interface cycles through a list of channels with a configurable dwell time. Interfaces are **staggered** — interface i starts at `channels[i % len(channels)]` — giving simultaneous multi-channel coverage.

| Field | Type | Description |
|-------|------|-------------|
| `channels` | list[int] | Channel list to cycle through, e.g. `[1, 6, 11]` |
| `dwell_ms` | int | Milliseconds to stay on each channel before hopping |
| `packets_per_second` | int | Injection rate per interface per channel |
| `packet` | PacketConfig | Frame type and parameters |

---

#### `beacon_sequence` — Beacon SSID Flood

Broadcasts a rotating sequence of beacon frames with SSIDs following the pattern `{task_name}-{seq_num}-{pos}`. The sequencer advances through positions 1 → `sequence_length`, then increments `seq_num` and repeats. Each SSID is broadcast for one second.

| Field | Type | Description |
|-------|------|-------------|
| `task_name` | str | SSID prefix (e.g. `"ap"` → `"ap-1-1"`, `"ap-1-2"`, …) |
| `sequence_length` | int | Number of positions before seq_num increments |
| `channel` | int | 802.11 channel to transmit on |
| `packets_per_second` | int | Injection rate per interface |
| `source_mac` | MAC | Spoofed AP source address |
| `bssid` | MAC | BSS identifier |

---

### Packet Types

Used by the `standard` and `span` task types.

#### `deauth` — Deauthentication

| Field | Type | Description |
|-------|------|-------------|
| `source_mac` | MAC | Spoofed source address (typically the AP's MAC) |
| `dest_mac` | MAC | Target client, or `ff:ff:ff:ff:ff:ff` to broadcast |
| `bssid` | MAC | BSS identifier |
| `reason` | int | Reason code (7 = most common) |

#### `beacon` — Beacon

| Field | Type | Description |
|-------|------|-------------|
| `ssid` | str | Network name to advertise |
| `source_mac` | MAC | Spoofed AP source address |
| `bssid` | MAC | BSS identifier |

#### `probe_req` — Probe Request

| Field | Type | Description |
|-------|------|-------------|
| `source_mac` | MAC | Spoofed source address |
| `ssid` | str | Target SSID, or empty string for wildcard |

#### `disassoc` — Disassociation

| Field | Type | Description |
|-------|------|-------------|
| `source_mac` | MAC | Spoofed source address |
| `dest_mac` | MAC | Target client, or broadcast |
| `bssid` | MAC | BSS identifier |
| `reason` | int | Reason code |

#### `auth` — Authentication

| Field | Type | Description |
|-------|------|-------------|
| `source_mac` | MAC | Spoofed source address |
| `dest_mac` | MAC | Target AP |
| `bssid` | MAC | BSS identifier |
| `algo` | int | 0 = Open System, 1 = Shared Key |
| `seq` | int | Sequence number (1–4) |

---

## Web UI

Accessible at `http://<pi-ip>:8080`.

### Interface Pool Strip

At the top of every page, shows each detected USB adapter:

- **Green dot** — adapter in monitor mode, ready for injection. Shows interface name and current channel.
- **Red error** — no adapters found. Plug one in; the watchdog retries every 10 seconds.

### Task Cards

Each configured task appears as a card showing:

| Field | Description |
|-------|-------------|
| **Name** | Task name with type badge (Standard / Span / Beacon Seq) |
| **Status** | `RUNNING` (animated green) or `STOPPED` |
| **Packets Sent** | Total frames injected this session |
| **Session Time** | Time since this task started |
| **Channel / Rate** | Task-specific summary |

**Buttons** per card: **Start**, **Stop**, **Edit**, **Delete**.

### Add / Edit Modal

Click **+ Add Task** or **Edit** on a card to open the configuration modal:

- **Task Name** and **Task Type** selector at the top.
- Type-specific fields render dynamically below.
- For `standard` and `span`, a **Packet Config** section appears with a **Frame Type** selector and per-type fields.
- MAC address fields have a **Random** button generating a locally-administered unicast MAC.

---

## REST API Reference

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Liveness probe — returns `{"status": "ok"}` |
| `GET` | `/api/status` | System uptime |

### Interface Pool

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/pool` | Pool status — adapter list, count, readiness |

### Task Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/tasks` | List all tasks with runtime status |
| `POST` | `/api/tasks` | Create a new task |
| `GET` | `/api/tasks/{id}` | Get one task's status |
| `PUT` | `/api/tasks/{id}` | Replace a task's configuration |
| `DELETE` | `/api/tasks/{id}` | Remove a task |
| `POST` | `/api/tasks/{id}/start` | Enable and start a task |
| `POST` | `/api/tasks/{id}/stop` | Disable and stop a task |

#### Example — create a span task:

```bash
curl -X POST http://pi-ip:8080/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "span",
    "name": "Channel Sweep",
    "channels": [1, 6, 11],
    "dwell_ms": 500,
    "packets_per_second": 20,
    "packet": {"type": "deauth", "source_mac": "de:ad:be:ef:00:01",
                "dest_mac": "ff:ff:ff:ff:ff:ff", "bssid": "de:ad:be:ef:00:01", "reason": 7}
  }'
```

#### Example — start a task:

```bash
curl -X POST http://pi-ip:8080/api/tasks/abc12345/start
```

---

## Project Structure

```
packet-spammer/
├── run.py                          # Entry point
├── pyproject.toml                  # Python dependencies
├── Dockerfile
├── docker-compose.yml              # Single service, privileged, host network
├── host.sh                         # Build + start script
│
├── config/
│   └── config.toml                 # Runtime configuration (written by web UI)
│
├── app/
│   ├── models/
│   │   └── config.py               # Pydantic config models (all task + packet types)
│   ├── sender/
│   │   ├── utils.py                # Shared subprocess helpers (iw, ip link)
│   │   ├── pool.py                 # InterfacePool — manages all USB adapters
│   │   └── tasks/
│   │       ├── base.py             # BaseTaskEngine abstract class
│   │       ├── standard.py         # StandardTaskEngine — fixed channel
│   │       ├── span.py             # SpanTaskEngine — staggered multi-channel
│   │       ├── beacon_seq.py       # BeaconSequenceEngine — SSID rotation
│   │       └── manager.py          # TaskManager — allocates pool across tasks
│   ├── host/
│   │   └── runtime.py              # Top-level coordinator
│   └── api/
│       └── routes.py               # FastAPI route handlers
│
└── base/                           # Reusable infrastructure
    ├── api/
    │   ├── server.py               # FastAPI + Uvicorn lifecycle wrapper
    │   ├── routes.py               # /api/health and /api/status
    │   └── static/
    │       └── index.html          # Web UI
    └── config/
        ├── models.py               # APIConfig, BaseHostConfig
        └── loader.py               # TOML load/save via Pydantic
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Docker container  (privileged, host network)    │
│                                                 │
│  HostRuntime                                    │
│  ├─ InterfacePool                               │
│  │    scan /sys/class/net for ALL USB WiFi      │
│  │    iw dev <iface> set type monitor           │
│  │    watchdog: retry every 10s if pool empty   │
│  │                                             │
│  ├─ TaskManager                                 │
│  │    allocate(N_adapters / N_active_tasks)     │
│  │    rebalance on add / remove / toggle        │
│  │                                             │
│  │    StandardTaskEngine                        │
│  │    ├─ _WorkerThread(iface0)                  │
│  │    └─ _WorkerThread(iface1)                  │
│  │         fixed channel, fixed frame, N pps    │
│  │                                             │
│  │    SpanTaskEngine                            │
│  │    ├─ _SpanWorker(iface0, offset=0)          │
│  │    └─ _SpanWorker(iface1, offset=1)          │
│  │         staggered ch cycling, dwell_ms       │
│  │                                             │
│  │    BeaconSequenceEngine                      │
│  │    ├─ _Sequencer  → updates shared frame     │
│  │    ├─ _Worker(iface0)                        │
│  │    └─ _Worker(iface1)                        │
│  │         all interfaces, rotating SSID        │
│  │                                             │
│  └─ APIServer (FastAPI + Uvicorn :8080)         │
│       /api/pool                                 │
│       /api/tasks  (CRUD + start/stop)           │
│       /  → index.html (web UI)                  │
└─────────────────────────────────────────────────┘
         │ host network namespace
         ▼
    USB WiFi dongle pool (wlan1, wlan2, …)
    in monitor mode
         │
         ▼
    802.11 frames injected over the air
```

### Interface allocation

When a task is started or stopped the pool is reallocated:

- `floor(N / T)` interfaces per task (T = active task count)
- First `N % T` tasks each get one extra interface
- If a task gets zero interfaces it logs a warning and does not start

### Span stagger

Worker `i` in a SpanTask starts at channel index `i % len(channels)`. With 3 interfaces and channels `[1, 6, 11]` the interface layout is:

```
iface0 → starts at ch1  → hops to ch6  → ch11 → ch1  …
iface1 → starts at ch6  → hops to ch11 → ch1  → ch6  …
iface2 → starts at ch11 → hops to ch1  → ch6  → ch11 …
```

All three channels are covered simultaneously.

---

## Adding a New Packet Type

1. **Add a config model** in [app/models/config.py](app/models/config.py):

```python
class MyPacketConfig(BaseModel):
    type: Literal["my_type"] = "my_type"
    some_field: str = "value"
```

2. **Add it to `PacketConfig`** in the same file.

3. **Create a builder** at `app/sender/packets/my_type.py`.

4. **Register it in the factory** ([app/sender/packets/factory.py](app/sender/packets/factory.py)).

5. **Add it to the web UI** in [base/api/static/index.html](base/api/static/index.html) — add to `PACKET_SCHEMAS`.

---

## Adding a New Task Type

1. **Add a config model** in [app/models/config.py](app/models/config.py) and add it to `TaskConfig`.

2. **Create a task engine** in `app/sender/tasks/my_task.py` extending `BaseTaskEngine`.

3. **Register it in `_make_engine()`** in [app/sender/tasks/manager.py](app/sender/tasks/manager.py).

4. **Add it to the web UI** in [base/api/static/index.html](base/api/static/index.html) — add to `TASK_SCHEMAS` and the `<select>` element.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `scapy` | 802.11 frame construction and raw socket injection |
| `fastapi` | REST API framework |
| `uvicorn[standard]` | ASGI server for FastAPI |
| `pydantic` | Config validation and serialisation |
| `tomli-w` | TOML serialisation (writing config back to disk) |

System packages installed in the Docker image: `iw`, `iproute2`, `net-tools`.

Python 3.13+ required.
