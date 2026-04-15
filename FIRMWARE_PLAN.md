# ESP32-C3 Car Companion Firmware — WiFi + CAN

## Context

ปัจจุบัน ESP32-C3 รัน SLCAN firmware (USB serial bridge) ต้องต่อ laptop ถึงจะใช้ได้
ต้องเปลี่ยนเป็น **standalone WiFi firmware** ที่:
- เชื่อมต่อ Android HUD ผ่าน WiFi (HUD เปิด AP ไว้)
- อ่านข้อมูลรถจาก CAN bus อัตโนมัติ
- ส่งข้อมูลไปยัง Android HUD ผ่าน TCP/JSON
- รับคำสั่ง lock/unlock/DRL จาก Android HUD
- ทำงาน standalone (auto-lock/unlock/DRL) แม้ไม่มี Android

## Hardware

```
ESP32-C3 Super Mini + SN65HVD230 → OBD-II CAN Bus (500kbps)
GPIO4 = CAN TX, GPIO3 = CAN RX
WiFi: Station mode → connect to Android HUD AP
```

---

## Architecture

### FreeRTOS Tasks (single-core ESP32-C3)

```
┌─────────────────────────────────────────────────┐
│  canPollTask (Priority 3 — highest)             │
│  - อ่าน OBD PIDs + manufacturer DIDs            │
│  - ประมวลผลคำสั่ง lock/unlock/DRL               │
│  - จัดการ UDS session ทุก ECU                    │
│  - อัพเดท CarState struct                       │
│  - เป็น task เดียวที่แตะ CAN bus                 │
├─────────────────────────────────────────────────┤
│  autoFeatureTask (Priority 2 — middle)          │
│  - State machine: auto-lock/unlock/DRL          │
│  - อ่าน CarState → ส่งคำสั่งผ่าน cmdQueue       │
├─────────────────────────────────────────────────┤
│  wifiTask (Priority 1 — lowest)                 │
│  - WiFi STA connect to HUD AP                   │
│  - TCP client เชื่อม HUD server (gateway IP)     │
│  - ส่ง JSON status / รับ JSON commands            │
└─────────────────────────────────────────────────┘
```

### Inter-Task Communication

```
cmdQueue (FreeRTOS Queue, 8 items)
  wifiTask ──────→ canPollTask
  autoFeatureTask ─→ canPollTask

CarState (mutex-protected struct)
  canPollTask ────→ wifiTask (อ่านเพื่อส่ง JSON)
  canPollTask ────→ autoFeatureTask (อ่านเพื่อตัดสินใจ)
```

### WiFi Connection

- ESP32 = **WiFi Station** เชื่อมต่อ AP ของ Android HUD
- ESP32 = **TCP Client** เชื่อมไป HUD server ที่ gateway IP:35000
- Default SSID: `CarHUD` / Pass: `12345678` (เปลี่ยนได้ผ่าน NVS)
- ยังไม่มี HUD จริง — ใช้ Serial debug ก่อน, WiFi เพิ่มทีหลัง
- Auto-reconnect ทั้ง WiFi และ TCP
- CAN ทำงานได้แม้ WiFi ยังไม่ connect

---

## CAN Bus Protocol Reference

### ECUs ที่ใช้

| ECU | Request ID | Response ID | ข้อมูล |
|-----|-----------|-------------|--------|
| BCM | 0x745 | 0x765 | Door lock/unlock, DRL, door/body status |
| Body ECU 2 | 0x74C | 0x76C | Gear position (45-byte, NRC 0x78) |
| Light ECU | 0x743 | 0x763 | Handbrake |
| Engine ECU | 0x7E1 | 0x7E9 | Engine running status |
| OBD Broadcast | 0x7DF | 0x7E8 | Standard PIDs |

### Control Commands

**Lock:** ExtSession → TP → `06 2F 02 02 03 00 01 FF` → Default
**Unlock:** ExtSession → TP → `06 2F 02 02 03 00 02 FF` → Default
**DRL ON:** ExtSession → TP → `06 2F 02 3F 03 00 01 FF` → keep TP every 1-2s
**DRL OFF:** `06 2F 02 3F 03 00 00 FF` → Default

### Status DIDs

**DID 0x0109 (BCM 0x745) — 18 bytes multiframe:**
- Byte 4: lights bitmask (bit3=turn R, bit2=turn L, bit1=parking, bit0=high beam)
- Byte 5: headlight state (0x42=off, 0x02=parking, 0x82=headlight)
- Byte 6: door open bitmask (bit7=FL, bit6=FR, bit5=RL, bit4=RR, bit3=trunk)
- Byte 8: lock (0x00=locked, 0x10=unlocked)
- Byte 17: brake pedal (0x00=off, 0x0C=pressed)

**DID 0x0108 (0x74C) — 45 bytes multiframe + NRC 0x78 (~3s wait):**
- Byte 27: gear (0x80=P, 0x00=R, 0x40=N, 0xC0=D/L) — engine ON only

**DID 0x0E07 (0x743) — 22 bytes multiframe:**
- Byte 19: handbrake (0x10=ON, 0x00=OFF)

**DID 0x1304 (0x7E1) — 4 bytes single frame:**
- Byte 3: engine (0x02=OFF, 0x06=RUNNING)

### OBD PIDs (via 0x7DF, no session needed)

| PID | ข้อมูล | สูตร |
|-----|--------|------|
| 0x0C | RPM | (A*256+B)/4 rpm |
| 0x0D | Speed | A km/h |
| 0x05 | Coolant Temp | A-40 °C |
| 0x11 | Throttle | A*100/255 % |
| 0x42 | Battery Voltage | (A*256+B)/1000 V |
| 0x46 | Ambient Temp | A-40 °C |
| 0x01 | MIL + DTC Count | bit7=MIL, bit0-6=count |
| 0x1F | Runtime | A*256+B seconds |

---

## Polling Schedule

~250ms per slot, 4 slots/second

**Fast (ทุก 500ms):** RPM, Speed, Throttle
**Medium (ทุก 2s):** DID 0x0109 (doors/lock/lights), DID 0x0E07 (handbrake), Coolant, Battery
**Slow (ทุก 10s):** DID 0x0108 (gear, non-blocking NRC 0x78), Ambient, Engine status, MIL
**DRL keep-alive:** TesterPresent to BCM ทุก 1.2s เมื่อ DRL active

---

## JSON Protocol (TCP, newline-delimited)

### ESP32 → Android

```json
{"type":"hello","fw":"1.0.0","car":"almera_n18","uptime":12345}

{"type":"status","ts":123456,"rpm":800,"speed":0,"gear":"P","locked":true,
 "doors":{"driver":false,"passenger":false,"rear_left":false,"rear_right":false,"trunk":false},
 "handbrake":true,"brake_pedal":false,
 "lights":{"parking":false,"headlight":false,"high_beam":false,"turn_left":false,"turn_right":false},
 "coolant":77,"battery":13.2,"ambient":31,"engine_running":true,
 "mil":false,"dtc_count":0,"drl_active":false}

{"type":"fast","ts":123789,"rpm":820,"speed":0,"throttle":12.5}

{"type":"ack","cmd":"lock","ok":true}
```

### Android → ESP32

```json
{"cmd":"lock"}
{"cmd":"unlock"}
{"cmd":"drl_on"}
{"cmd":"drl_off"}
{"cmd":"refresh"}
{"cmd":"config","auto_lock":true,"lock_speed":20,"unlock_delay":3}
```

---

## Auto-Feature State Machine

```
IDLE → ENGINE_RUNNING       (RPM>0: DRL ON ถ้า enabled)
ENGINE_RUNNING → SPEED_LOCKED  (speed≥20: LOCK)
SPEED_LOCKED → ENGINE_RUNNING  (speed<20: rearm circular lock)
ENGINE_RUNNING → ENGINE_OFF_WAIT  (RPM=0: start unlock timer)
ENGINE_OFF_WAIT → IDLE         (3s elapsed: UNLOCK + DRL OFF)
ENGINE_OFF_WAIT → ENGINE_RUNNING  (RPM>0: engine restarted, cancel)
```

---

## NVS Configuration

| Key | Type | Default | คำอธิบาย |
|-----|------|---------|----------|
| wifi_ssid | string | "CarHUD" | HUD AP SSID |
| wifi_pass | string | "12345678" | HUD AP password |
| tcp_port | uint16 | 35000 | HUD server port |
| auto_lock | bool | true | Auto-lock at speed |
| auto_unlock | bool | true | Auto-unlock engine off |
| auto_drl | bool | true | Auto-DRL engine on |
| lock_speed | uint8 | 20 | Lock threshold km/h |
| unlock_delay | uint8 | 3 | Unlock delay seconds |

---

## File Structure

```
firmware/src/
  main.cpp              — setup(), task creation
  config.h              — pins, constants, defaults
  car_state.h/cpp       — CarState struct + mutex
  can_manager.h/cpp     — TWAI TX/RX, ISO-TP, multiframe
  session_manager.h/cpp — UDS session per ECU
  poll_task.h/cpp       — polling loop + command processing
  wifi_task.h/cpp       — WiFi STA + TCP client + JSON
  auto_features.h/cpp   — 4-feature state machine
  decode.h/cpp          — DID/PID decode (ported from Python)
  nvs_config.h/cpp      — Preferences load/save
  json_protocol.h/cpp   — ArduinoJson serialize/deserialize
```

## platformio.ini

```ini
[env:esp32c3]
platform = espressif32
framework = arduino
board = esp32-c3-devkitm-1
monitor_speed = 115200
build_flags =
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
lib_deps =
    bblanchon/ArduinoJson@^7.0.0
```

---

## Implementation Phases

### Phase 1: CAN Core + Decode ← เริ่มที่นี่
- `main.cpp`, `config.h`, `can_manager`, `decode`, `car_state`
- อ่าน PIDs + DIDs print ผ่าน Serial Monitor
- **เป้าหมาย: flash แล้วเสียบ USB ดูข้อมูลรถผ่าน Serial**

### Phase 2: Session Manager + Poll Task
- `session_manager`, `poll_task`
- Polling schedule + command queue
- ทดสอบ lock/unlock/DRL ผ่าน Serial command

### Phase 3: NVS Config
- `nvs_config`
- WiFi credentials + feature flags

### Phase 4: WiFi + TCP + JSON
- `wifi_task`, `json_protocol`
- เชื่อม Android HUD จริง

### Phase 5: Auto-Features
- `auto_features` state machine
- ทดสอบบนรถจริง

### Phase 6: Integration + Hardening
- End-to-end test, error recovery, memory profiling

---

## Verification

1. **Phase 1:** Serial output ต้องแสดง RPM, Speed, Gear, Doors ตรงกับ `python3 nissan_car_status.py`
2. **Phase 2:** สั่ง `lock`/`unlock` ผ่าน Serial → ประตูต้องทำงาน
3. **Phase 4:** Android เชื่อม TCP → เห็น JSON status + สั่ง lock ได้
4. **Phase 5:** ขับรถ >20 km/h → auto-lock, ดับเครื่อง → auto-unlock
