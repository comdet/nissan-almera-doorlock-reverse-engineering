# Car Companion — Android HUD Integration Protocol

Complete spec for implementing the Android side of the Almera N18 Car Companion.

## What the ESP32 does

The ESP32-C3 sits in the OBD-II port and:

- Reads every car state we know (RPM, speed, gear, doors, lock, lights, brake, etc.)
- Runs an 8-state driving machine that auto-fires lock / unlock / DRL based on real driving scenarios (see [STATE_MACHINE.md](STATE_MACHINE.md))
- Drops into low-power mode when parked (WiFi off, 30s RPM ping) to save the car battery
- Connects to **the Android phone's hotspot** as a WiFi station, then opens a TCP client to the phone and streams JSON

The Android side is a TCP server. It receives status frames, sends commands, and draws the HUD. Warnings / alerts / persistence are entirely Android's job — the ESP32 is a pure I/O bridge.

---

## Network

### Topology

```
ESP32-C3  ──────────────►  Android phone (Mobile Hotspot)
 (WiFi STA)                 (WiFi AP + TCP server)
  TCP client ─── port 35000 ───►  Android app
```

The Android phone is the access point. The ESP32 connects to it. This way the phone keeps its mobile data connection on the cellular side while the ESP32 talks to it on WiFi.

### Defaults (configurable via NVS)

| Field | Default | Where |
|---|---|---|
| WiFi SSID | `CarHUD` | NVS key `wifi_ssid` |
| WiFi password | `12345678` | NVS key `wifi_pass` |
| TCP port | `35000` | NVS key `tcp_port` |
| WiFi enabled | `false` | NVS key `wifi_en` |

`wifi_en` is **off by default** so a fresh ESP32 doesn't spam reconnect attempts before the HUD exists. Flip it on via the web config portal (long-press the BOOT button on the ESP32 for 3s, then connect to AP `AlmeraConfig` / `12345678` and open `http://192.168.4.1/`), or via a JSON `config` message once the HUD is paired.

### How the ESP32 finds the server

The ESP32 is a **TCP client**, not a server. When the Android phone runs its mobile hotspot, the phone is simultaneously:

1. The WiFi access point
2. The DHCP server that hands the ESP32 an IP
3. The default gateway for everything on the subnet

So after joining the hotspot, the ESP32 reads its DHCP-assigned gateway address (`WiFi.gatewayIP()`) — that *is* the Android phone's IP on the hotspot subnet — and opens a TCP socket to `<gateway_ip>:tcp_port`. No IP discovery, mDNS, or manual setup needed.

Common gateway IPs by Android version (informational only — the firmware doesn't care, it uses whatever DHCP says):

| Android | Hotspot subnet | Gateway = phone IP |
|---|---|---|
| Stock / most builds | `192.168.43.0/24` | `192.168.43.1` |
| Pixel (recent) | `192.168.49.0/24` | `192.168.49.1` |
| Samsung (some) | `192.168.42.0/24` | `192.168.42.1` |

#### Android server-side setup

Bind a `ServerSocket` to port 35000 on `0.0.0.0` and accept the inbound connection. The ESP32's IP becomes visible via `Socket.getInetAddress()` but you don't need it for anything — once accepted, just stream JSON in both directions on that socket.

```kotlin
val server = ServerSocket(35000)
while (true) {
    val sock = server.accept()                 // blocks until ESP32 connects
    val reader = sock.getInputStream().bufferedReader()
    val writer = sock.getOutputStream().bufferedWriter()
    // Read newline-delimited JSON from `reader`
    // Write commands to `writer` (don't forget the trailing '\n')
}
```

If TCP open fails (Android app not listening, or socket reset by Android killing the connection), the ESP32 retries with exponential backoff (1s → 2s → 4s … capped at 15s).

### Disconnect / reconnect

- ESP32 in **PARKED** for more than 30 seconds → low-power mode → WiFi off entirely. Server should expect the connection to drop and not retry aggressively while engine is off.
- When the engine restarts, ESP32 wakes within ~30s, restores WiFi, and reconnects automatically.

---

## Wire format

- **Transport:** TCP, plain bytes
- **Framing:** Newline-delimited (`\n`) JSON
- **Encoding:** UTF-8
- **Direction:** Full duplex — both sides can send any time
- One JSON object per line; no whitespace inside lines is mandated but the ESP32 currently sends compact JSON without spaces.

### Message types (ESP32 → Android)

| `type` | When | Rate |
|---|---|---|
| `hello` | Right after TCP accept | once per connection |
| `status` | Periodic full-state snapshot | every 1 second |
| `fast` | (Reserved) trimmed snapshot — RPM/speed/throttle only | not currently sent; spec retained for future use |
| `ack` | Reply to a command | per command |

### Message types (Android → ESP32)

| `cmd` | Action |
|---|---|
| `lock` | Lock all doors now |
| `unlock` | Unlock all doors now |
| `drl_on` | Turn DRL on (with TesterPresent keep-alive) |
| `drl_off` | Turn DRL off |
| `refresh` | Force a full re-poll of all DIDs/PIDs immediately |
| `config` | Update one or more NVS keys (see below) |

---

## Messages — ESP32 → Android

### `hello`

Sent once when the TCP connection comes up. Use it to learn firmware version and reset any "stale data" indicators on the HUD.

```json
{"type":"hello","fw":"0.2.0","car":"almera_n18","uptime":12}
```

| Field | Type | Meaning |
|---|---|---|
| `fw` | string | Firmware version |
| `car` | string | Always `almera_n18` for this build |
| `uptime` | int | Seconds since ESP32 boot |

### `status`

Sent every second. Single source of truth for the HUD.

Fields that haven't been read successfully yet are **omitted** rather than set to a sentinel value — treat absence as "unknown". The state machine fields (`state`, `gear`, `engine_running`, `locked`, `lowpower`) are always present.

```json
{
  "type": "status",
  "ts": 12345,
  "state": "LOCKED_CRUISING",
  "lowpower": false,

  "rpm": 2500,
  "speed": 80,
  "throttle": 45.0,
  "coolant": 88,
  "ambient": 31,
  "battery": 13.28,
  "mil": false,
  "dtc_count": 0,

  "gear": "D",
  "handbrake": false,
  "brake_pedal": false,
  "engine_running": true,

  "locked": true,
  "doors": {
    "driver":     false,
    "passenger":  false,
    "rear_left":  false,
    "rear_right": false,
    "trunk":      false
  },
  "lights": {
    "parking":       false,
    "high_beam":     false,
    "turn_left":     false,
    "turn_right":    false,
    "headlight_raw": 130
  },
  "wifi": {
    "rssi": -65,
    "ip":   "192.168.43.123"
  }
}
```

#### Field reference

##### Metadata

| Field | Type | Notes |
|---|---|---|
| `type` | string | Always `"status"` |
| `ts` | int | Milliseconds since ESP32 boot. Doubles as uptime. |
| `state` | string | One of the 8 driving-machine states (table below) |
| `lowpower` | bool | True when ESP32 has dropped WiFi and is in 30s-ping mode (only happens when `state == PARKED`). HUD likely won't see this — when it's true, WiFi is off and TCP is closed. |

##### OBD-II values

| Field | Type | Units | Notes |
|---|---|---|---|
| `rpm` | int | rpm | Omitted if unknown |
| `speed` | int | km/h | Omitted if unknown |
| `throttle` | float | %, one decimal | Throttle position from ECM (not driver pedal — that may match closely) |
| `coolant` | int | °C, range -40..215 | Engine coolant temperature |
| `ambient` | int | °C | Outside air temp |
| `battery` | float | volts, three decimals | ECU-reported battery voltage. Engine off ~12V, alternator running ~14V. |
| `mil` | bool | — | Check-engine light is on |
| `dtc_count` | int | — | Number of stored DTCs |

##### Transmission

| Field | Type | Values |
|---|---|---|
| `gear` | string | `"P"`, `"R"`, `"N"`, `"D"`, `"L"`, `"?"` (unknown) |
| `handbrake` | bool | Parking brake pulled |
| `engine_running` | bool | RPM > 0 (firmware uses RPM as the source of truth, not DID 0x1304) |

##### Body

| Field | Type | Notes |
|---|---|---|
| `brake_pedal` | bool | Driver pressing the brake |
| `locked` | bool | All doors locked |
| `doors.driver` | bool | Driver door open |
| `doors.passenger` | bool | Front passenger door open |
| `doors.rear_left` | bool | Rear left door open |
| `doors.rear_right` | bool | Rear right door open |
| `doors.trunk` | bool | Boot/trunk open |

##### Lights

| Field | Type | Notes |
|---|---|---|
| `lights.parking` | bool | Parking lights |
| `lights.high_beam` | bool | High beam |
| `lights.turn_left` | bool | Left turn signal flashing |
| `lights.turn_right` | bool | Right turn signal flashing |
| `lights.headlight_raw` | int | Raw byte 5 from DID 0x0109: `0x42` = off, `0x02` = parking only, `0x82` = headlight on |

##### Network

| Field | Type | Notes |
|---|---|---|
| `wifi.rssi` | int | Signal strength in dBm (-100…0; closer to 0 = stronger). `0` when WiFi is off. |
| `wifi.ip` | string | ESP32's IP on the hotspot subnet. Omitted when not connected. |

### `ack`

Sent after a command finishes executing on the bus.

```json
{"type":"ack","cmd":"lock","ok":true}
```

Currently `ok` reflects whether the command was queued, not whether the BCM actually responded with a positive UDS response. Treat it as "command accepted." For verification, watch the next `status` frame — `locked` should flip within a second or so.

### `fast` (reserved)

Was originally specced for sub-second HUD ticks. Not emitted in the current firmware — the 1s `status` cadence is enough for a fluid HUD. Kept reserved for future use.

```json
{"type":"fast","ts":123789,"rpm":820,"speed":0,"throttle":12.5}
```

---

## Messages — Android → ESP32

### Lock / Unlock / DRL / Refresh

```json
{"cmd":"lock"}
{"cmd":"unlock"}
{"cmd":"drl_on"}
{"cmd":"drl_off"}
{"cmd":"refresh"}
```

`refresh` forces the canPoll task to mark every polling group due immediately. Useful right after the HUD comes online so you don't have to wait for the next scheduled poll of each item.

### `config`

Update NVS settings. Any subset of fields is fine — only the keys present in the message get touched. Saved to flash automatically after the message is parsed.

```json
{
  "cmd": "config",
  "auto_lock":    true,
  "auto_unlock":  true,
  "auto_drl":     true,
  "lock_speed":   20,
  "unlock_delay": 1,

  "wifi_enabled": true,
  "wifi_ssid":    "CarHUD",
  "wifi_pass":    "12345678",
  "tcp_port":     35000,

  "json_on_serial": false
}
```

| Key | Type | Range | Effect |
|---|---|---|---|
| `auto_lock` | bool | — | Send LOCK at speed ≥ `lock_speed` |
| `auto_unlock` | bool | — | Send UNLOCK after `unlock_delay`s in ENGINE_OFF |
| `auto_drl` | bool | — | Turn DRL on at engine start, off at engine off |
| `lock_speed` | int | 1–100 km/h | Threshold for auto-lock |
| `unlock_delay` | int | 0–60 s | Engine-off countdown before unlock |
| `wifi_enabled` | bool | — | Master WiFi switch |
| `wifi_ssid` | string | ≤32 chars | The Android hotspot SSID |
| `wifi_pass` | string | ≤64 chars | The Android hotspot password |
| `tcp_port` | int | 1–65535 | Port Android listens on |
| `json_on_serial` | bool | — | Mirror status JSON to the USB serial console (for debug) |

The ESP32 doesn't reboot after a config save. Most fields take effect on the next poll cycle. WiFi changes only matter the next time wifi_task tries to reconnect.

---

## The 8 driving states

The HUD will see `state` change as the driver moves through the journey. Use this for UI affordances (e.g. show the "lock" button enabled only while parked, etc.). Full descriptions in [STATE_MACHINE.md](STATE_MACHINE.md).

| state | When | What the firmware does |
|---|---|---|
| `ACC_ON` | Key on, engine not started | Poll RPM only |
| `ENGINE_ON` | Engine running, not yet moving | DRL on, poll most things, wait for movement |
| `DRIVING` | Speed > 0, not yet at lock threshold | Full HUD-rate polling |
| `LOCKED_CRUISING` | Speed ≥ `lock_speed`, locked | Same as DRIVING |
| `LOCKED_STOPPED` | Stopped while locked | Watch RPM (engine off check) and doors (circular lock) |
| `REARM` | Door opened-and-closed during a stop | Wait for speed ≥ `lock_speed` then re-LOCK |
| `ENGINE_OFF` | RPM=0 + gear=P, counting down to UNLOCK | Poll RPM at 2 Hz to catch restart |
| `PARKED` | After UNLOCK fired | Slow polling, then low-power mode |

### Idle-stop (CVT auto stop/start) handling

`RPM=0 + gear=P` triggers `ENGINE_OFF`.
`RPM=0 + gear=D/N` (Nissan auto idle-stop) does **not** — the state machine stays in `LOCKED_STOPPED`. So your HUD logic doesn't need to second-guess idle-stop; the firmware handles it.

Helpful Android-side detection for the HUD itself:

```python
is_idle_stop_active = (
    state in ("LOCKED_STOPPED", "REARM")
    and engine_running == False
    and gear in ("D", "N")
)
```

---

## Suggested Android-side logic

These belong on the Android side because they involve user preference, persistence, or UI. None of them require firmware changes.

### Warnings to display

- `coolant > 100` → "Engine overheating"
- `battery < 11.8` → "Battery low" (only when engine off; engine-on threshold is lower)
- `mil == true` → "Check engine"
- `handbrake == true && speed > 0` → "Release handbrake"
- `gear != 'P' && state == 'PARKED'` → "Shift to P"
- Any `doors.* == true` while moving → "Door open"
- `rpm > 6000` → "Over-rev" (Almera 1.0 turbo redline ~6500)

### Trip logging

- Track odometer using `speed × Δt` (integrate over time)
- Log fuel economy if you wire in PID 0x5E later (currently not supported by this car)
- Start / end markers: `ENGINE_ON` → first transition into `DRIVING`, end at `PARKED`

### Quick UI affordances

- Show LOCK / UNLOCK buttons disabled while `state == ACC_ON` (no command will work without the engine ECU being warm)
- Grey out the LOCK button if `locked == true`
- Grey out UNLOCK if `locked == false`
- Show a "low signal" indicator when `wifi.rssi < -80`

---

## End-to-end example session

```
[t=0]     Android phone hotspot up, app TCP-listens on 35000
[t=3]     User turns key to ACC
[t=3.5]   ESP32 boots, NVS loaded, wifi_task starts
[t=5]     ESP32 connects to "CarHUD" hotspot
[t=6]     ESP32 opens TCP to gateway:35000
[t=6]     Android ← {"type":"hello","fw":"0.2.0","car":"almera_n18","uptime":3}
[t=7]     Android ← {"type":"status","state":"ACC_ON",...}
[t=7+1s]  Android ← {"type":"status","state":"ACC_ON",...}
[t=10]    User starts engine; RPM rises
[t=11]    Android ← {"type":"status","state":"ENGINE_ON","rpm":900,...}
[t=11]    ESP32 fires DRL_ON internally; next status shows `lights` updated
[t=12]    Android sees `engine_running:true`
[t=15]    User drives off
[t=16]    Android ← {"type":"status","state":"DRIVING","speed":12,"gear":"D",...}
[t=20]    Speed crosses 20 km/h
[t=21]    Android ← {"type":"status","state":"LOCKED_CRUISING","locked":true,...}
[t=21]    Android ← {"type":"ack","cmd":"lock","ok":true}   (note: SRC_AUTO)
[t=180]   User stops at a light, idle stop fires (RPM=0, gear=D)
[t=181]   Android ← {"type":"status","state":"LOCKED_STOPPED","engine_running":false,"gear":"D",...}
          ^^ HUD can show "Idle Stop Active"; do NOT show "Engine Off"
[t=183]   Light turns green, RPM returns
[t=184]   Android ← {"type":"status","state":"LOCKED_CRUISING","engine_running":true,...}
[t=2400]  User arrives, shifts to P, turns off engine
[t=2401]  Android ← {"type":"status","state":"LOCKED_STOPPED","engine_running":false,"gear":"P",...}
[t=2401]  ESP32 sees rpm=0 + gear=P → transitions to ENGINE_OFF
[t=2402]  Android ← {"type":"status","state":"ENGINE_OFF",...}
[t=2403]  After unlock_delay (1s), unlock + DRL off fire
[t=2403]  Android ← {"type":"status","state":"PARKED","locked":false,...}
[t=2403]  Android ← {"type":"ack","cmd":"unlock","ok":true}
[t=2403]  Android ← {"type":"ack","cmd":"drl_off","ok":true}
[t=2433]  30s in PARKED → low-power mode kicks in
[t=2433]  ESP32 disconnects TCP, drops WiFi
          Android sees TCP close. Display "ESP32 sleeping" or similar.
[t=...]   When user restarts, ESP32 wakes within 30s, reconnects.
```

---

## Manual control while developing

Until the Android app exists, you can drive the firmware from a terminal connected to the ESP32's USB serial port (115200 baud).

### Commands

```
help              — print available commands
status            — pretty-print the full snapshot
config            — print NVS config
config <k> <v>    — set one NVS key (e.g. config lock_speed 25)
save              — persist NVS changes
reset             — factory reset NVS
lock              — same as JSON cmd:lock
unlock            — same as JSON cmd:unlock
drl on            — turn DRL on
drl off           — turn DRL off
refresh           — force re-poll
dump              — print every known DID as raw hex (debug)
scan <ecu> <start_hex> <end_hex>
                  — probe a DID range, print responders
                    e.g. scan engine 1100 110F
wifi info         — show WiFi + TCP stats
wifi on | off     — toggle wifi_enabled at runtime
json on | off     — mirror JSON status to serial (for debug)
portal            — reboot into web config portal
reboot            — restart ESP32
```

### Send JSON instead

Anything starting with `{` is parsed as a JSON command, same as if it arrived over TCP:

```
{"cmd":"lock"}
{"cmd":"config","lock_speed":25}
```

### Web debug page

Long-press BOOT for 3s → ESP32 reboots into config-portal mode → AP `AlmeraConfig` / `12345678` → open `http://192.168.4.1/debug` for an auto-refreshing live status page. Useful for verifying field values before wiring them into the Android UI.

---

## Versioning

Currently `fw` is hard-coded in `firmware/src/json_protocol.cpp`. Bump it whenever the protocol shape changes incompatibly (rename a field, drop a state). Within a major, only add new optional fields. The Android side should:

- Treat unknown fields as ignorable
- Treat absent known fields as "unknown" (not zero)
- Display the `fw` string in an About / Diagnostics screen for support
