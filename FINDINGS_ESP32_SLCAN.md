# Nissan Almera N18 — Door Lock/Unlock Findings (ESP32-C3 + SN65HVD230 SLCAN)

## วันที่ทดสอบ: 2026-04-15

## Hardware ที่ใช้สำเร็จ

```
Mac (USB) → ESP32-C3 Super Mini (SLCAN firmware) → SN65HVD230 → OBD-II CAN Bus → BCM
```

- **ESP32-C3 Super Mini** + SLCAN firmware (firmware/src/main.cpp)
  - GPIO4 = CAN TX → SN65HVD230 CTX/D
  - GPIO3 = CAN RX → SN65HVD230 CRX/R
  - TWAI_MODE_NORMAL (ส่ง+รับ)
- **SN65HVD230** CAN transceiver (3.3V, Rs→GND = high speed)
  - CANH → OBD-II Pin 6
  - CANL → OBD-II Pin 14
- CAN Bus: **500kbps**, 11-bit standard IDs
- python-can interface: **slcan**

## ELM327 v1.5 Clone — ทำไมใช้ไม่ได้

ทดสอบ 2 clone:

| | Clone 1 | Clone 2 |
|---|---------|---------|
| ATSH 745 (BCM address) | ส่งได้ แต่ response จาก ECM 7E8 ไม่ใช่ BCM 765 | **ส่งไม่ได้เลย** (NO DATA) |
| Payload limit (ATCAF1) | **4 bytes** (IOControl ต้องการ 6) | 7 bytes (พอ) |
| ATCAF0 raw mode | ส่งไม่ออก (NO DATA) | N/A |
| ATCRA 765 filter | ไม่ทำงาน เกิด spurious `?` | ไม่ทำงาน |
| สรุป | payload limit block | ส่ง non-standard CAN ID ไม่ได้ |

**ELM327 v1.5 clone ไม่สามารถสื่อสารกับ BCM (0x745/0x765) ได้** เพราะเป็น non-standard OBD-II address

---

## CAN IDs ที่เกี่ยวข้อง

| CAN ID Request | CAN ID Response | ECU | หน้าที่ |
|---|---|---|---|
| **0x745** | **0x765** | **BCM (Body Control Module)** | Door lock, DRL, body functions |
| 0x7DF | 0x7E8, 0x7E9 | ECM + TCM (broadcast) | OBD-II standard queries |

---

## DIDs ที่ทดสอบแล้ว

### DID=0x023F — Door Lock Actuator (IOControl)

| controlParam | controlState | ผลลัพธ์ | ความหมาย |
|---|---|---|---|
| 0x03 (shortTermAdj) | **[00 01]** | **OK** (6F response) | **ใช้ใน UNLOCK sequence** |
| 0x03 (shortTermAdj) | **[00 00]** | **OK** (6F response) | **ใช้ใน LOCK sequence / return control** |
| 0x03 (shortTermAdj) | [00 02] | NRC 0x31 | requestOutOfRange |
| 0x03 (shortTermAdj) | [00 03]-[00 0F] | NRC 0x31 | requestOutOfRange |
| 0x03 (shortTermAdj) | [01 xx] | NRC 0x13 | incorrectMessageLength |
| 0x03 (shortTermAdj) | [02 00] | NRC 0x31 | requestOutOfRange |
| 0x00 (returnCtrl) | N/A | OK (status 0x11) | ไม่มีผลกับ actuator |
| 0x01 (resetDefault) | N/A | NRC 0x31 | ไม่รองรับ |
| 0x02 (freezeState) | N/A | NRC 0x31 | ไม่รองรับ |

**สรุป DID=0x023F:** auxiliary actuator — ทำให้ไฟ DRL ติด/ดับ
- [00 01] = activate (DRL ON เป็น side effect)
- [00 00] = return control (DRL OFF)
- **ไม่จำเป็นสำหรับ lock/unlock** — DID=0x0202 ตัวเดียวพอ

### DID=0x0202 — Door Lock/Unlock Control (IOControl) ★ ตัวหลัก

| controlState | ผลลัพธ์ | ความหมาย |
|---|---|---|
| **[00 02]** | **OK** | **UNLOCK ประตู** |
| **[00 01]** | **OK** | **LOCK ประตู** |
| [00 00] | NRC 0x31 | requestOutOfRange |

**สรุป DID=0x0202:** นี่คือคำสั่ง lock/unlock จริง ทำงานแบบ minimal (4 commands)
- **[00 02] = UNLOCK** (ไม่มี DRL side effect เมื่อส่งเดี่ยว)
- **[00 01] = LOCK**

### DID=0x0109 — Door Status (ReadDataByIdentifier)

18-byte multiframe response ต้อง FlowControl

| Byte | UNLOCKED | LOCKED | ความหมาย |
|---|---|---|---|
| 0-2 | 62 01 09 | 62 01 09 | SID + DID echo |
| 3 | 09 | 09 | ? |
| 4 | 00 | 00 | ? |
| 5 | 42 | 42 | ? |
| 6-7 | 00 00 | 00 00 | ? |
| **8** | **0x10** | **0x00** | **Lock status: 0x10=UNLOCKED, 0x00=LOCKED** |
| 9-17 | 00...01 98 00 00 | 00...01 98 00 00 | ไม่เปลี่ยน |

---

## Minimal UNLOCK Sequence (ยืนยันแล้ว — 4 commands)

```
TX 0x745: [02 10 03 FF FF FF FF FF]    DiagSessionControl → Extended
RX 0x765: [06 50 03 00 32 01 F4 00]    Positive response

TX 0x745: [02 3E 00 FF FF FF FF FF]    TesterPresent
RX 0x765: [02 7E 00 ...]               Positive response

TX 0x745: [06 2F 02 02 03 00 02 FF]    ★ IOControl DID=0x0202 [00 02] = UNLOCK
RX 0x765: [05 6F 02 02 03 01 00 00]    Positive response

TX 0x745: [02 10 01 FF FF FF FF FF]    DiagSessionControl → Default
RX 0x765: [06 50 01 00 32 01 F4 00]    Positive response
```

**ผลลัพธ์:** ประตูปลดล็อค ไม่มี DRL side effect

---

## Minimal LOCK Sequence (ยืนยันแล้ว — 4 commands)

```
TX 0x745: [02 10 03 FF FF FF FF FF]    DiagSessionControl → Extended
RX 0x765: [06 50 03 00 32 01 F4 00]    Positive response

TX 0x745: [02 3E 00 FF FF FF FF FF]    TesterPresent
RX 0x765: [02 7E 00 ...]               Positive response

TX 0x745: [06 2F 02 02 03 00 01 FF]    ★ IOControl DID=0x0202 [00 01] = LOCK
RX 0x765: [05 6F 02 02 03 01 00 00]    Positive response

TX 0x745: [02 10 01 FF FF FF FF FF]    DiagSessionControl → Default
RX 0x765: [06 50 01 00 32 01 F4 00]    Positive response
```

**ผลลัพธ์:** ประตูล็อค (ส่งซ้ำตอน lock อยู่ → ล็อคซ้ำมีเสียง)

---

## DRL ON/OFF (ยืนยันแล้ว)

DRL ใช้ DID=0x023F (ไม่เกี่ยวกับ DID=0x0202)

**DRL ON:**
```
TX 0x745: [02 10 03 FF FF FF FF FF]    DiagSessionControl → Extended
TX 0x745: [02 3E 00 FF FF FF FF FF]    TesterPresent
TX 0x745: [06 2F 02 3F 03 00 01 FF]    IOControl DID=0x023F [00 01] = DRL ON
... keep-alive: ส่ง TesterPresent ทุก 1-2 วินาที ...
```

**DRL OFF:**
```
TX 0x745: [06 2F 02 3F 03 00 00 FF]    IOControl DID=0x023F [00 00] = DRL OFF
TX 0x745: [02 10 01 FF FF FF FF FF]    DiagSessionControl → Default
```

**สำคัญ:** DRL ต้อง maintain Extended Session ด้วย TesterPresent keep-alive
ถ้าหยุดส่ง TP → session timeout (~5 วินาที) → BCM กลับ Default → ไฟดับเอง

---

## ข้อค้นพบสำคัญ

### 1. DID=0x0202 คือคำสั่ง lock/unlock ตัวจริง

README เดิมสันนิษฐานว่า DID=0x0202 เป็น DRL (Daytime Running Lights)
**ความจริง:** DID=0x0202 คือ **door lock/unlock command**:
- **[00 02] = UNLOCK** (ไม่มี DRL side effect เมื่อส่งเดี่ยว)
- **[00 01] = LOCK**
- **ทำงานแบบ minimal** — แค่ 4 commands (ExtSession → TP → IOControl → Default)

### 2. DID=0x023F คือ DRL control

DID=0x023F ควบคุมไฟ DRL (Daytime Running Lights):
- **[00 01] = DRL ON** (ต้อง keep-alive ด้วย TesterPresent)
- **[00 00] = DRL OFF** (หรือหยุด keep-alive → ดับเอง)
- **ไม่จำเป็นสำหรับ lock/unlock** — DID=0x0202 ตัวเดียวพอ

### 3. ไม่ต้องการ SecurityAccess (SID 0x27)

ไม่มี security layer — ส่ง IOControl ได้ทันทีใน Extended Session

### 4. Response status [03 01] คงที่

BCM ตอบ `6F 02 3F 03 01 00 00` ทุกครั้งไม่ว่าจะ lock หรือ unlock
- 03 = echo controlParam (shortTermAdjustment)
- 01 = status (คงที่ ไม่ใช่ lock state)

### 5. ตรวจสอบสถานะด้วย DID=0x0109 Byte 8

- **0x10** = UNLOCKED
- **0x00** = LOCKED

---

## Scripts

| Script | หน้าที่ |
|--------|--------|
| `nissan_slcan.py` | **ตัวหลัก** — lock/unlock/status/DRL ผ่าน SLCAN |
| `nissan_status.py` | อ่านสถานะ lock/unlock (DID 0x0109 byte 8) |
| `nissan_door_elm327.py` | ผ่าน ELM327 (ใช้ไม่ได้กับ v1.5 clone) |

## สิ่งที่ยังต้องทดสอบ

1. **Minimal UNLOCK** — ลอง DID=0x0202 [00 02] อย่างเดียว (เหมือน minimal lock)
2. **DRL behavior** — [00 02] เปิด DRL จริงหรือแค่ side effect ของ unlock trigger?
3. **Timing sensitivity** — delay ระหว่าง phase สำคัญแค่ไหน?
4. **DID=0x0202 [00 00]** — NRC 0x31 ตอน return control; อาจต้องใช้ค่าอื่น
5. **Integration กับ script** — อัพเดท nissan_door_unlock.py / nissan_diag.py ให้ใช้ SLCAN
