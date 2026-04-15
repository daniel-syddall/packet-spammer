# Packet Spammer

A self-contained 802.11 WiFi frame injection tool with a browser-based control panel. Runs on a Raspberry Pi (or any Linux SBC) inside Docker. Designed to be pointed at a target channel and left running unattended — or controlled live from any device on the same network.

## Contents

- [How It Works](#how-it-works)
- [Hardware Requirements](#hardware-requirements)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
  - [config/config.toml](#configconfigtoml)
  - [Packet Types](#packet-types)
- [Web UI](#web-ui)
- [REST API Reference](#rest-api-reference)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Adding a New Packet Type](#adding-a-new-packet-type)
- [Dependencies](#dependencies)

---

## How It Works

On startup the system:

1. Scans `/sys/class/net` for a **USB wireless adapter** (built-in Pi WiFi is intentionally skipped).
2. Puts the adapter into **monitor mode** and sets the configured 802.11 channel using `iw`.
3. Builds a Scapy frame from the configured packet type and parameters.
4. Launches a background thread that injects that frame at the configured rate (packets per second) using raw `AF_PACKET` sockets — no association, no IP stack.
5. Starts a **FastAPI web server** on port `8080` so you can monitor and control everything from a browser.

All configuration is persisted to `config/config.toml`. Changes made through the web UI are written back to disk immediately.

---

## Hardware Requirements

| Component | Notes |
|-----------|-------|
| Raspberry Pi (any model with USB) | Tested target. Any Linux SBC works. |
| **USB WiFi adapter** that supports monitor mode and packet injection | e.g. Alfa AWUS036ACH, AWUS036ACS, cards based on RT8812AU, AR9271, MT7612U. The Pi's built-in BCM chip is **not used** — it does not support injection reliably. |
| MicroSD + power | Standard Pi setup. |

> **Important:** Plug in the USB WiFi adapter **before** starting the container. The adapter is detected once at startup (with a 10-second retry watchdog if it's missed). If you plug it in after the container is already running, the watchdog will find it within 10 seconds automatically.

---

## Quick Start

```bash
# Clone / copy the project onto the Pi, then:
./host.sh          # builds the Docker image and starts in the foreground
./host.sh -d       # start detached (background)
```

Then open a browser on any device on the same network:

```
http://<pi-ip>:8080
```

`host.sh` installs Docker automatically if it isn't present.

### Autostart on Pi reboot

The container is configured with `restart: unless-stopped` in `docker-compose.yml`, so it comes back automatically after a reboot. The **Autostart** toggle in the web UI controls whether transmission begins immediately when the container starts, or waits for a manual Start press.

---

## Configuration

### config/config.toml

The single config file. Edited by the web UI at runtime; you can also edit it manually before starting.

```toml
[api]
enabled = true
host    = "0.0.0.0"
port    = 8080

[sender]
autostart          = false   # Begin transmitting on container start?
packets_per_second = 10      # Injection rate (1–1000)
channel            = 6       # 802.11 channel (1–13 for 2.4 GHz, 36–165 for 5 GHz)

[packet]
type       = "deauth"        # One of: deauth | beacon | probe_req | disassoc | auth
source_mac = "aa:bb:cc:dd:ee:ff"
dest_mac   = "ff:ff:ff:ff:ff:ff"
bssid      = "aa:bb:cc:dd:ee:ff"
reason     = 7
```

### Packet Types

Each type has its own set of fields. The web UI renders the correct form automatically when you select a type.

---

#### `deauth` — Deauthentication

Sends an 802.11 Deauthentication management frame.

| Field | Type | Description |
|-------|------|-------------|
| `source_mac` | MAC | Spoofed source address (typically the AP's MAC) |
| `dest_mac` | MAC | Target client, or `ff:ff:ff:ff:ff:ff` to broadcast |
| `bssid` | MAC | BSS identifier (the AP's MAC) |
| `reason` | int | Reason code (see table below) |

Common reason codes:

| Code | Meaning |
|------|---------|
| 1 | Unspecified |
| 3 | STA leaving IBSS/ESS |
| 4 | Inactivity timeout |
| 7 | Class 3 frame from non-associated STA *(most common)* |

---

#### `beacon` — Beacon

Broadcasts 802.11 Beacon frames — makes a fake access point visible to nearby devices.

| Field | Type | Description |
|-------|------|-------------|
| `ssid` | str | Network name to advertise |
| `source_mac` | MAC | Spoofed AP source address |
| `bssid` | MAC | BSS identifier |

The beacon includes a DS Parameter Set element set to the currently configured channel, and a standard supported-rates IE.

---

#### `probe_req` — Probe Request

Sends 802.11 Probe Request frames. An empty SSID is a wildcard — any AP in range will respond.

| Field | Type | Description |
|-------|------|-------------|
| `source_mac` | MAC | Spoofed source address |
| `ssid` | str | Target SSID, or empty string for wildcard |

---

#### `disassoc` — Disassociation

Sends 802.11 Disassociation frames.

| Field | Type | Description |
|-------|------|-------------|
| `source_mac` | MAC | Spoofed source address |
| `dest_mac` | MAC | Target client, or broadcast |
| `bssid` | MAC | BSS identifier |
| `reason` | int | Reason code (1=unspecified, 3=leaving BSS, 5=AP overloaded) |

---

#### `auth` — Authentication

Sends 802.11 Authentication frames. Useful for auth flood testing.

| Field | Type | Description |
|-------|------|-------------|
| `source_mac` | MAC | Spoofed source address |
| `dest_mac` | MAC | Target (AP) |
| `bssid` | MAC | BSS identifier |
| `algo` | int | 0 = Open System, 1 = Shared Key |
| `seq` | int | Sequence number (1–4) |

---

## Web UI

Accessible at `http://<pi-ip>:8080` from any device on the network.

### Interface Banner

At the top of the page, shows the current status of the USB WiFi adapter:

- **Green** — adapter found, in monitor mode, channel set. Shows interface name (e.g. `wlan1`) and frequency.
- **Yellow** — adapter found but something went wrong (e.g. channel set failed).
- **Red** — no USB adapter detected. Plug one in; the watchdog will detect it within 10 seconds.

### Stat Cards

| Card | Description |
|------|-------------|
| **Status** | `RUNNING` (animated green) or `STOPPED` |
| **Rate** | Current configured packets per second |
| **Channel** | 802.11 channel and derived frequency in MHz |
| **Packets Sent** | Total frames injected this session |
| **Session Time** | Time since transmission started |

### Transmission Panel (left)

- **START / STOP** button — disabled if no adapter is ready.
- **Packets per second** — rate input. Click *Apply Settings* to push the change. Takes effect immediately without restarting.
- **Channel** — channel number input. Shows derived frequency as you type. Applied immediately via `iw`.
- **Autostart on boot** — toggle. Fires immediately; no Apply needed.

### Packet Panel (right)

- **Frame Type** dropdown — switching type re-renders the fields below it.
- **MAC address fields** each have a **Random** button that generates a locally-administered unicast MAC.
- **Apply Packet** — validates all fields, rebuilds the Scapy frame, and hot-swaps it into the running send loop. The very next injected frame uses the new config.

---

## REST API Reference

The web UI uses this API. You can also call it directly.

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Liveness probe — returns `{"status": "ok"}` |
| `GET` | `/api/status` | System uptime and sender state summary |

### Sender Control

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/sender/status` | Full status snapshot (running, packets sent, interface, config) |
| `POST` | `/api/sender/start` | Begin injection. 503 if no interface is ready |
| `POST` | `/api/sender/stop` | Stop injection |

### Configuration

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `GET` | `/api/config` | — | Full current config |
| `PUT` | `/api/config/sender` | `{"packets_per_second": N, "channel": N, "autostart": bool}` | Update sender settings (all fields optional) |
| `GET` | `/api/config/packet` | — | Current packet config |
| `PUT` | `/api/config/packet` | `{"type": "...", ...fields}` | Replace packet config and hot-swap the frame |

#### Example — change rate to 50 pps and channel to 11:

```bash
curl -X PUT http://pi-ip:8080/api/config/sender \
  -H 'Content-Type: application/json' \
  -d '{"packets_per_second": 50, "channel": 11}'
```

#### Example — switch to beacon spam:

```bash
curl -X PUT http://pi-ip:8080/api/config/packet \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "beacon",
    "ssid": "FreeWifi",
    "source_mac": "de:ad:be:ef:00:01",
    "bssid": "de:ad:be:ef:00:01"
  }'
```

---

## Project Structure

```
packet-spammer/
├── run.py                          # Entry point
├── pyproject.toml                  # Python dependencies
├── Dockerfile                      # python:3.13-slim + iw + iproute2
├── docker-compose.yml              # Single service, privileged, host network
├── host.sh                         # Build + start script
│
├── config/
│   └── config.toml                 # Runtime configuration (written by web UI)
│
├── app/
│   ├── models/
│   │   └── config.py               # Pydantic config models (all packet types)
│   ├── sender/
│   │   ├── interface.py            # USB WiFi detection + monitor mode manager
│   │   ├── engine.py               # Background thread send loop
│   │   └── packets/
│   │       ├── factory.py          # Dispatches config → Scapy frame
│   │       ├── deauth.py           # 802.11 Deauth builder
│   │       ├── beacon.py           # 802.11 Beacon builder
│   │       ├── probe_req.py        # 802.11 Probe Request builder
│   │       ├── disassoc.py         # 802.11 Disassociation builder
│   │       └── auth.py             # 802.11 Authentication builder
│   ├── host/
│   │   └── runtime.py              # Top-level coordinator (API + sender + watchdog)
│   └── api/
│       └── routes.py               # FastAPI route handlers
│
└── base/                           # Reusable infrastructure (unchanged from baseplate)
    ├── api/
    │   ├── server.py               # FastAPI + Uvicorn lifecycle wrapper
    │   ├── routes.py               # /api/health and /api/status
    │   └── static/
    │       └── index.html          # Web UI
    └── config/
        ├── models.py               # APIConfig, SpammerConfig, BaseHostConfig
        └── loader.py               # TOML load/save via Pydantic
```

---

## Architecture

```
┌─────────────────────────────────────────────┐
│  Docker container  (privileged, host network)│
│                                             │
│  HostRuntime                                │
│  ├─ InterfaceManager                        │
│  │    scan /sys/class/net for USB WiFi      │
│  │    iw dev <iface> set type monitor       │
│  │    iw dev <iface> set channel N          │
│  │    watchdog: retry every 10s if missing  │
│  │                                          │
│  ├─ SenderEngine (background thread)        │
│  │    PacketFactory.build(config)           │
│  │    → Scapy frame (RadioTap/Dot11/...)    │
│  │    → sendp(frame, iface, verbose=0)      │
│  │    rate-controlled via monotonic clock   │
│  │    hot-swap: frame + rate changeable     │
│  │    while running                         │
│  │                                          │
│  └─ APIServer (FastAPI + Uvicorn :8080)     │
│       /api/sender/start|stop|status         │
│       /api/config/sender  (PUT)             │
│       /api/config/packet  (PUT)             │
│       /  → index.html (web UI)              │
└─────────────────────────────────────────────┘
         │ host network namespace
         ▼
    USB WiFi dongle (wlan1, wlan2, ...)
    in monitor mode
         │
         ▼
    802.11 frames injected over the air
```

### Send loop timing

The engine uses a **monotonic accumulator** rather than a plain `time.sleep(interval)`. This means:

- Accumulated drift from slow sends is bounded at ±1 second (reset guard).
- Rate changes take effect on the next iteration without restarting the thread.
- The `threading.Event.wait()` is used for sleeping so `stop()` returns immediately rather than waiting out a full sleep interval.

---

## Adding a New Packet Type

1. **Add a config model** in [app/models/config.py](app/models/config.py):

```python
class MyPacketConfig(BaseModel):
    type: Literal["my_type"] = "my_type"
    some_field: str = "value"
```

2. **Add it to the union** in the same file:

```python
PacketConfig = Annotated[
    Union[..., MyPacketConfig],
    Field(discriminator="type"),
]
```

3. **Create a builder** at `app/sender/packets/my_type.py`:

```python
from scapy.layers.dot11 import RadioTap, Dot11, ...
from app.models.config import MyPacketConfig

def build(cfg: MyPacketConfig):
    return RadioTap() / Dot11(...) / ...
```

4. **Register it in the factory** ([app/sender/packets/factory.py](app/sender/packets/factory.py)):

```python
from app.sender.packets import my_type

# Inside PacketFactory.build():
case MyPacketConfig():
    frame = my_type.build(cfg)
```

5. **Add it to the web UI** in [base/api/static/index.html](base/api/static/index.html):

```javascript
// In the <select> element:
<option value="my_type">My Packet Type</option>

// In the SCHEMAS object:
my_type: [
    { id: "some_field", label: "Some Field", type: "text" },
]
```

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
