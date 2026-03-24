# Nissan Almera Turbo (N18) / Versa — Door Lock Reverse Engineering

## สารบัญ

1. [ภาพรวมโปรเจค](#1-ภาพรวมโปรเจค)
2. [พื้นฐานความรู้ที่จำเป็น](#2-พื้นฐานความรู้ที่จำเป็น)
3. [วิธีการ Capture ข้อมูล](#3-วิธีการ-capture-ข้อมูล)
4. [โครงสร้างไฟล์ในโปรเจค](#4-โครงสร้างไฟล์ในโปรเจค)
5. [ผลการวิเคราะห์ข้อมูลดิบ](#5-ผลการวิเคราะห์ข้อมูลดิบ)
6. [ECU ที่เกี่ยวข้อง](#6-ecu-ที่เกี่ยวข้อง)
7. [Polling Loop — สิ่งที่ MCU ทำเป็นประจำ](#7-polling-loop--สิ่งที่-mcu-ทำเป็นประจำ)
8. [ลำดับการ Unlock ประตู](#8-ลำดับการ-unlock-ประตู)
9. [รายละเอียด CAN Frame ทุก byte](#9-รายละเอียด-can-frame-ทุก-byte)
10. [ข้อจำกัดและสิ่งที่ยังไม่แน่ใจ](#10-ข้อจำกัดและสิ่งที่ยังไม่แน่ใจ)
11. [วิธีใช้งาน Script](#11-วิธีใช้งาน-script)

---

## 1. ภาพรวมโปรเจค

โปรเจคนี้คือการ reverse engineer (วิศวกรรมย้อนกลับ) protocol การสั่งล็อค/ปลดล็อคประตูรถ
Nissan Almera Turbo (N18) ซึ่งในต่างประเทศมีชื่อรุ่นคล้ายกันคือ Nissan Versa

เป้าหมายคือถอดรหัสว่า OBD Door Lock Device (อุปกรณ์เสริมที่เสียบช่อง OBD-II
เพื่อสั่งล็อค/ปลดล็อคประตูอัตโนมัติ) ส่งคำสั่งอะไรไปบน CAN Bus เพื่อสั่งประตู

---

## 2. พื้นฐานความรู้ที่จำเป็น

### 2.1 CAN Bus (Controller Area Network Bus)

CAN Bus คือระบบสื่อสารภายในรถยนต์ ทำหน้าที่เป็น "สายสื่อสาร" ที่เชื่อมอุปกรณ์อิเล็กทรอนิกส์
ทุกตัวในรถเข้าด้วยกัน เปรียบเสมือน "กลุ่มไลน์" ที่ทุกคนอ่านข้อความได้ แต่แต่ละข้อความจะมี
หมายเลขกำกับ (CAN ID) เพื่อให้รู้ว่าใครเป็นคนส่ง/ใครควรรับ

**คุณสมบัติสำคัญ:**
- ใช้สาย 2 เส้น: CAN-H (High) และ CAN-L (Low)
- ความเร็วในรถทั่วไป: 500 kbps (500,000 bits ต่อวินาที)
- ทุกอุปกรณ์บน bus เห็นทุก message (broadcast)
- แต่ละ message เรียกว่า "CAN Frame"

### 2.2 CAN Frame (เฟรมข้อมูล CAN)

CAN Frame คือหน่วยข้อมูล 1 ชุดที่ส่งบน CAN Bus ประกอบด้วย:

```
┌───────────┬────────────┬─────┬──────────────┬──────┬─────┬─────────────┐
│ SOF       │ CAN ID     │ RTR │ DLC          │ DATA │ CRC │ EOF         │
│ Start of  │ ตัวระบุ     │     │ Data Length  │ ข้อมูล│     │ End of      │
│ Frame     │ ผู้ส่ง/ชนิด │     │ Code         │ 0-8  │     │ Frame       │
│ (1 bit)   │ (11 bit)   │     │ (จำนวน byte) │ byte │     │ (7 bit)     │
└───────────┴────────────┴─────┴──────────────┴──────┴─────┴─────────────┘
```

- **SOF (Start of Frame):** bit เริ่มต้น บอกว่า frame เริ่มแล้ว
- **CAN ID (CAN Identifier):** เลข 11 bit (0x000-0x7FF) ระบุว่าข้อความนี้เป็นของใคร/เกี่ยวกับอะไร
- **RTR (Remote Transmission Request):** บอกว่าเป็น data frame หรือ request frame
- **DLC (Data Length Code):** ตัวเลข 0-8 บอกว่า data มีกี่ byte
- **DATA:** ข้อมูลจริง 0-8 byte
- **CRC (Cyclic Redundancy Check):** รหัสตรวจสอบความถูกต้อง 15 bit
- **EOF (End of Frame):** bit สิ้นสุด บอกว่า frame จบแล้ว

### 2.3 ECU (Electronic Control Unit)

ECU คือ "คอมพิวเตอร์ขนาดเล็ก" ที่ควบคุมระบบต่าง ๆ ในรถ รถ 1 คันมี ECU หลายสิบตัว เช่น:

- **BCM (Body Control Module):** ควบคุมระบบตัวถังรถ เช่น ล็อคประตู, ไฟ, กระจก, แตร
- **ECM (Engine Control Module):** ควบคุมเครื่องยนต์
- **TCM (Transmission Control Module):** ควบคุมเกียร์

แต่ละ ECU มี CAN ID ประจำตัวสำหรับรับส่งข้อมูล

### 2.4 OBD-II (On-Board Diagnostics version II)

OBD-II คือมาตรฐานการวินิจฉัยรถยนต์ ช่อง OBD-II เป็นพอร์ต 16 pin อยู่ใต้คอนโซลหน้ารถ
(ฝั่งคนขับ) ที่ช่างใช้เสียบเครื่องมือวินิจฉัยเพื่ออ่านค่าต่าง ๆ จากรถ

ช่อง OBD-II ต่อตรงเข้ากับ CAN Bus ของรถ ดังนั้นอุปกรณ์ที่เสียบเข้าไปสามารถ:
- อ่านค่าเซ็นเซอร์ (ความเร็ว, รอบเครื่อง, อุณหภูมิ)
- อ่านรหัสข้อผิดพลาด (DTC = Diagnostic Trouble Code)
- **สั่งงาน actuator (อุปกรณ์ทำงาน) เช่น สั่งล็อค/ปลดล็อคประตู**

### 2.5 UDS (Unified Diagnostic Services) — มาตรฐาน ISO 14229

UDS คือ protocol มาตรฐานสำหรับสื่อสารกับ ECU ในเชิง "วินิจฉัย" (diagnostic)
เปรียบเสมือน "ภาษา" ที่เครื่องมือวินิจฉัย (Tester) ใช้คุยกับ ECU

**UDS ทำงานแบบ Request-Response:**
- Tester ส่ง "คำขอ" (Request) ไปที่ ECU
- ECU ส่ง "คำตอบ" (Response) กลับมา — อาจเป็น Positive (สำเร็จ) หรือ Negative (ล้มเหลว)

**Service ID (SID):** ตัวเลข 1 byte ที่บอกว่า "ขอทำอะไร"

| SID (hex) | ชื่อ Service | ความหมาย |
|-----------|-------------|----------|
| 0x10 | DiagnosticSessionControl | เปลี่ยนโหมดการวินิจฉัย (เช่น เข้าโหมดขั้นสูง) |
| 0x22 | ReadDataByIdentifier | อ่านค่าข้อมูลจาก ECU ตาม DID ที่ระบุ |
| 0x2F | InputOutputControlByIdentifier | **สั่งงาน actuator** (เช่น สั่งล็อค/ปลดล็อคประตู) |
| 0x3E | TesterPresent | ส่งสัญญาณ "ยังอยู่" เพื่อไม่ให้ session หมดเวลา |
| 0x7F | NegativeResponse | ECU ตอบปฏิเสธ พร้อมรหัสเหตุผล |

**Positive Response:** ECU ตอบด้วย SID + 0x40 เช่น ถ้าส่ง 0x10 จะตอบ 0x50
**Negative Response:** ECU ตอบ 0x7F ตามด้วยรหัสปฏิเสธ (NRC = Negative Response Code)

### 2.6 Diagnostic Session (โหมดการวินิจฉัย)

ECU มีหลายโหมดการทำงาน แต่ละโหมดอนุญาตให้ทำ service ต่างกัน:

| Session | ค่า (hex) | ความหมาย |
|---------|-----------|----------|
| Default Session | 0x01 | โหมดปกติ — ทำได้แค่อ่านค่าพื้นฐาน |
| Extended Diagnostic Session | 0x03 | โหมดขั้นสูง — ทำได้มากขึ้น รวมถึงสั่งงาน actuator |

**สำคัญมาก:** การสั่ง IOControl (สั่งล็อค/ปลดล็อคประตู) ต้องอยู่ใน Extended Session เท่านั้น
ถ้าส่งตอนอยู่ Default Session จะถูกปฏิเสธด้วย NRC = 0x7F
(serviceNotSupportedInActiveSession = service นี้ไม่รองรับใน session ปัจจุบัน)

### 2.7 ISO-TP (ISO 15765-2 — Transport Protocol)

ISO-TP คือ protocol ชั้นกลาง ที่ "ห่อ" ข้อมูล UDS ใส่ CAN Frame

ปัญหา: CAN Frame ส่งข้อมูลได้สูงสุดแค่ 8 byte แต่ข้อความ UDS บางอันยาวกว่า 8 byte
ISO-TP จึงแบ่งข้อมูลยาวออกเป็นหลาย frame:

| ประเภท Frame | PCI (byte แรก) | ใช้เมื่อ |
|-------------|----------------|---------|
| **SF (Single Frame)** | 0x0N (N=ความยาว) | ข้อมูลสั้น พอใส่ frame เดียว (1-7 byte) |
| **FF (First Frame)** | 0x1N (N=ความยาว MSB) | ชิ้นแรกของข้อมูลยาว |
| **CF (Consecutive Frame)** | 0x2N (N=ลำดับ) | ชิ้นถัด ๆ ไปของข้อมูลยาว |
| **FC (Flow Control)** | 0x30 | ฝั่งรับบอกฝั่งส่งว่า "ส่งต่อได้" |

PCI ย่อมาจาก Protocol Control Information คือ byte แรกของ data ที่บอกว่า frame นี้เป็นประเภทไหน

ตัวอย่าง: `02 10 03 FF FF FF FF FF`
- `02` = Single Frame, ความยาว 2 byte
- `10 03` = UDS payload (DiagnosticSessionControl, session=Extended)
- `FF FF FF FF FF` = padding (ข้อมูลเสริมให้ครบ 8 byte ไม่มีความหมาย)

### 2.8 DID (Data Identifier)

DID คือ "หมายเลขข้อมูล" 2 byte ที่ใช้ระบุว่าต้องการอ่าน/เขียน/สั่งงานอะไร
เปรียบเสมือน "เลขที่เอกสาร" ที่บอก ECU ว่า "ขอข้อมูลชุดนี้" หรือ "สั่งงานอุปกรณ์ตัวนี้"

DID ที่พบในการ capture นี้:

| DID (hex) | ใช้กับ Service | ความหมาย (สันนิษฐาน) |
|-----------|---------------|---------------------|
| 0x0109 | ReadDataByIdentifier (0x22) | อ่านสถานะประตู (18 byte) |
| 0x0108 | ReadDataByIdentifier (0x22) | อ่านข้อมูลจาก ECU 0x74C (45 byte) |
| 0x0E07 | ReadDataByIdentifier (0x22) | อ่านข้อมูลจาก ECU 0x743 (22 byte) |
| 0x1301 | ReadDataByIdentifier (0x22) | อ่านข้อมูลจาก ECU 0x7E1 |
| 0x1304 | ReadDataByIdentifier (0x22) | อ่านข้อมูลจาก ECU 0x7E1 |
| **0x023F** | **IOControlByIdentifier (0x2F)** | **สั่งงาน door lock actuator** |
| **0x0202** | **IOControlByIdentifier (0x2F)** | **สั่งงาน (ยังไม่ยืนยันหน้าที่แน่ชัด)** |

### 2.9 IOControlByIdentifier (SID = 0x2F) — คำสั่งสั่งงาน Actuator

นี่คือ service ที่สำคัญที่สุดในโปรเจคนี้ ใช้สำหรับสั่งงาน "actuator" (อุปกรณ์ที่ทำงานทางกายภาพ)
เช่น มอเตอร์ล็อคประตู, รีเลย์ไฟ, มอเตอร์กระจก ฯลฯ

โครงสร้างคำสั่ง:

```
[PCI] [SID] [DID_high] [DID_low] [controlParam] [controlState...]

ตัวอย่าง: 06 2F 02 3F 03 00 01 FF
           │  │  └──┘  │  └──┘  │
           │  │  DID    │  state  padding
           │  SID       controlParam
           PCI(SF,len=6)
```

**controlParam (พารามิเตอร์ควบคุม):**

| ค่า (hex) | ชื่อ | ความหมาย |
|-----------|------|----------|
| 0x00 | returnControlToECU | คืนการควบคุมให้ ECU (หยุดสั่งงาน) |
| 0x01 | resetToDefault | รีเซ็ตกลับค่าเริ่มต้น |
| 0x02 | freezeCurrentState | ค้างสถานะปัจจุบัน |
| 0x03 | shortTermAdjustment | ปรับค่าชั่วคราว (ใช้ค่าใน controlState) |

### 2.10 NRC (Negative Response Code) — รหัสปฏิเสธ

เมื่อ ECU ปฏิเสธคำสั่ง จะตอบ SID=0x7F พร้อม NRC บอกเหตุผล:

| NRC (hex) | ชื่อ | ความหมาย |
|-----------|------|----------|
| 0x78 | requestCorrectlyReceivedResponsePending | "ได้รับคำสั่งแล้ว รอแป๊บ" (ไม่ใช่ error) |
| 0x7F | serviceNotSupportedInActiveSession | "คำสั่งนี้ใช้ไม่ได้ใน session ปัจจุบัน" |
| 0x22 | conditionsNotCorrect | "เงื่อนไขไม่ตรง" (เช่น รถวิ่งอยู่) |
| 0x31 | requestOutOfRange | "ค่าที่ส่งมาอยู่นอกช่วงที่รับได้" |
| 0x33 | securityAccessDenied | "ไม่ผ่านการยืนยันตัวตน" |

---

## 3. วิธีการ Capture ข้อมูล

### 3.1 อุปกรณ์

- **OBD Door Lock Device:** อุปกรณ์เสริมที่เสียบช่อง OBD-II เพื่อสั่งล็อค/ปลดล็อคประตูอัตโนมัติ
  ภายในมี MCU (Microcontroller Unit = ไมโครคอนโทรลเลอร์) ต่อกับ CAN Transceiver IC
  (ชิปแปลงสัญญาณระหว่าง logic level กับ CAN Bus)
- **Logic Analyzer:** เครื่องมือจับสัญญาณดิจิทัล (Saleae Logic)
- **ซอฟต์แวร์:** Saleae Logic 2 พร้อม CAN decoder

### 3.2 การต่อสาย

```
CAN Bus (รถ)
    │
    │  CAN-H / CAN-L
    │
┌───┴───────────────┐
│ CAN Transceiver IC │
│ (แปลงสัญญาณ)      │
└───┬──────┬────────┘
    │ RX   │ TX
    │      │
    │      └──── Logic Analyzer CH2 (doorunlock3_d2.txt)
    │             = สิ่งที่ MCU ส่งออกไป
    │
    └─────────── Logic Analyzer CH1 (doorunlock3.txt)
                  = สิ่งที่ MCU ได้รับจาก CAN Bus
    │
┌───┴────────┐
│    MCU     │
│ (สมองของ   │
│  อุปกรณ์)  │
└────────────┘
```

- **RX (Receive) = doorunlock3.txt:** ทุกอย่างที่ MCU เห็นบน CAN Bus
  รวมถึง message ของตัวเอง (echo) และ message จาก ECU อื่น ๆ ทุกตัว
- **TX (Transmit) = doorunlock3_d2.txt:** เฉพาะสิ่งที่ MCU ตัวนี้ส่งออกไปเท่านั้น
  ช่วยให้แยกได้ชัดเจนว่า "อุปกรณ์สั่งอะไร" vs "รถตอบอะไร"

### 3.3 สถานการณ์ขณะ Capture

1. ประตูรถ **อาจ unlock อยู่แล้ว** ก่อนเริ่ม capture (ข้อจำกัดที่สำคัญ)
2. เสียบ OBD Door Lock Device เข้าช่อง OBD-II
3. ได้ยินเสียง unlock ประตู
4. หยุด capture

**ข้อจำกัด:** เนื่องจากประตูอาจ unlock อยู่แล้ว เราไม่สามารถยืนยัน 100% ว่าคำสั่งไหน
"ทำให้" ประตู unlock — อุปกรณ์อาจส่งคำสั่ง unlock ซ้ำทุกครั้งที่เสียบไม่ว่าสถานะจะเป็นอะไร

---

## 4. โครงสร้างไฟล์ในโปรเจค

### 4.1 ไฟล์ข้อมูลดิบ (จาก Saleae Logic Analyzer)

| ไฟล์ | ขนาด | คำอธิบาย |
|------|-------|---------|
| `doorunlock3.txt` | 63 MB | ข้อมูลดิบช่อง RX (MCU รับ) — decoded CAN frames จาก Saleae |
| `doorunlock3_d2.txt` | 63 MB | ข้อมูลดิบช่อง TX (MCU ส่ง) — decoded CAN frames จาก Saleae |
| `unlock3.sr`, `unlock3.pvs` | เล็ก | Saleae Logic session file สำหรับเปิดดูใน Logic 2 |
| `lock.sr`, `lock2.sr`, `unlock.sr`, `unlock2.sr` | เล็ก | capture อื่น ๆ (ยังไม่ได้วิเคราะห์) |

### 4.2 ไฟล์ผลลัพธ์จากการวิเคราะห์

| ไฟล์ | คำอธิบาย |
|------|---------|
| `doorunlock3_frames.txt` | frame ทั้งหมดจาก RX เรียงตามเวลา พร้อม UDS decode |
| `doorunlock3_tx_only.txt` | เฉพาะ frame ที่ MCU ส่ง (TX) พร้อม UDS decode |
| `doorunlock3_combined.txt` | RX + TX รวมกันเรียงตามเวลา มีเครื่องหมาย `***` กำกับ TX |
| `doorunlock3_unlock_analysis.txt` | วิเคราะห์เฉพาะ BCM (0x745/0x765) แสดง timeline unlock |

### 4.3 Script

| ไฟล์ | คำอธิบาย |
|------|---------|
| `parse_can_frames.py` | แกะ frame จากไฟล์ดิบ นับจำนวน แสดงสถิติ |
| `extract_uds_conversation.py` | แกะ frame จาก RX พร้อม decode UDS เต็มรูปแบบ |
| `extract_both_channels.py` | แกะทั้ง RX + TX รวม timeline |
| `analyze_unlock_sequence.py` | วิเคราะห์เฉพาะ sequence การ unlock ที่ BCM |
| `nissan_door_unlock.py` | **script สำหรับส่งคำสั่ง unlock จริง** (ต้องใช้กับ CAN adapter) |

---

## 5. ผลการวิเคราะห์ข้อมูลดิบ

### 5.1 สถิติไฟล์ RX (doorunlock3.txt)

```
บรรทัดทั้งหมด:         1,714,847 บรรทัด
  - CAN Fields lines:    323,459   (ข้อมูล decoded frame)
  - CAN Bits lines:    1,304,449   (ข้อมูล bit-level ดิบ — ไม่ได้ใช้)
  - อื่น ๆ:               86,939

CAN Frame ทั้งหมด:        29,224 frame
  - Idle/Empty (ID=0):    28,982   (99.2% — frame ว่างเปล่าตอน bus ไม่มีข้อมูล)
  - Valid (ID ไม่เป็น 0):     242   (0.8% — frame ที่มีข้อมูลจริง)
```

### 5.2 สถิติไฟล์ TX (doorunlock3_d2.txt)

```
Valid TX frames: 234 frame
  - 0x7FF (idle padding):  78 frame  (MCU ส่ง 0xFF ทั้งหมด — ไม่มีความหมาย)
  - 0x745 (BCM request):   65 frame  ← สำคัญ
  - 0x743 (ECU request):   37 frame
  - 0x74C (ECU request):   19 frame
  - 0x7E1 (ECU request):   19 frame
  - 0x7DF (OBD broadcast): 13 frame
  - 0x515, 0x7C1, 0x7E8:    3 frame  (initialization / อื่น ๆ)
```

### 5.3 ทำไม 0x745 ถึงมีเยอะ?

0x745 คือ CAN ID สำหรับส่งคำสั่งไป BCM (**ทุกคำสั่ง** ไปที่ BCM ใช้ ID นี้) ดังนั้น:

```
0x745 จำนวน 65 frames ประกอบด้วย:
  ├── TesterPresent (0x3E)          ~20 ครั้ง  ← keep-alive ส่งทุก ~2-3 วินาที
  ├── ReadDataByIdentifier (0x22)   ~10 ครั้ง  ← polling อ่านสถานะ
  ├── FlowControl (0x30)            ~10 ครั้ง  ← ตอบรับ multiframe
  ├── DiagnosticSessionControl (0x10) ~10 ครั้ง ← เปลี่ยน session
  ├── IOControlByIdentifier (0x2F)     6 ครั้ง  ← ★ ตัวสั่งประตูจริง ๆ!
  └── อื่น ๆ                         ~9 ครั้ง
```

**สรุป: จาก 65 frame มีแค่ 6 frame (9%) ที่เป็นคำสั่ง lock/unlock จริง ที่เหลือเป็น overhead**

---

## 6. ECU ที่เกี่ยวข้อง

MCU ในอุปกรณ์ OBD Door Lock สื่อสารกับ ECU หลายตัวพร้อมกัน:

| CAN ID Request | CAN ID Response | ECU (สันนิษฐาน) | หน้าที่ |
|----------------|-----------------|-----------------|--------|
| **0x745** | **0x765** | **BCM (Body Control Module)** | **ล็อค/ปลดล็อคประตู** ← ตัวหลัก |
| 0x74C | 0x76C | BCM หรือ ECU อื่น | อ่านข้อมูล DID=0x0108 |
| 0x743 | 0x763 | ECU อื่น | อ่านข้อมูล DID=0x0E07 |
| 0x7E1 | ไม่เห็น response | Engine ECU หรืออื่น | อ่านข้อมูล DID=0x1301, 0x1304 |
| 0x7DF | (broadcast) | ทุก ECU ที่รับ OBD-II | อ่าน Vehicle Speed (PID=0x0D) |

**ทำไมถึงคุยกับหลาย ECU?**
อุปกรณ์ต้องรู้สถานะรถก่อนสั่งงาน เช่น:
- ความเร็วรถ (0x7DF → PID 0x0D) — อาจไม่สั่ง unlock ถ้ารถวิ่งอยู่
- สถานะประตู (0x745 → DID 0x0109) — ตรวจว่าประตูล็อค/ปลดล็อคอยู่

---

## 7. Polling Loop — สิ่งที่ MCU ทำเป็นประจำ

MCU วน loop ทุก ~6 วินาที ส่งคำสั่งเหล่านี้ซ้ำ ๆ:

```
ทุกรอบ loop (~6 วินาที):

  1. TesterPresent (0x3E) บน 0x745
     → keep-alive เพื่อไม่ให้ session หมดเวลา

  2. ReadDataByIdentifier DID=0x0109 บน 0x745
     → อ่านสถานะประตู (response = 18 byte multiframe)

  3. ReadDataByIdentifier DID=0x0108 บน 0x74C
     → อ่านข้อมูลจาก ECU อีกตัว (response = 45 byte multiframe)

  4. OBD-II Service 0x01 PID=0x0D บน 0x7DF
     → อ่าน Vehicle Speed (ความเร็วรถ)

  5. ReadDataByIdentifier DID=0x1301 บน 0x7E1
     → อ่านข้อมูลจาก ECU เครื่องยนต์

  6. ReadDataByIdentifier DID=0x0E07 บน 0x743
     → อ่านข้อมูลจาก ECU อีกตัว (response = 22 byte multiframe)

  7. ReadDataByIdentifier DID=0x1304 บน 0x7E1
     → อ่านข้อมูลเพิ่มเติมจาก ECU เครื่องยนต์
```

นอกจาก polling แล้ว ทุกรอบ MCU ยัง re-enter Extended Session ให้ ECU ทุกตัว:

```
  DiagSessionControl → Extended (0x03) บน 0x745 (BCM)
  DiagSessionControl → Extended (0x03) บน 0x74C
  DiagSessionControl → 0xC0 (manufacturer specific) บน 0x7E1
  DiagSessionControl → Extended (0x03) บน 0x743
```

---

## 8. ลำดับการ Unlock ประตู

### 8.1 Timeline เต็ม (จาก capture)

capture ทั้งหมดกินเวลา ~3.7 วินาที
IOControlByIdentifier (SID=0x2F) ถูกส่ง 6 ครั้ง:

```
เวลา      คำสั่ง                                      ผลลัพธ์
────────  ──────────────────────────────────────────  ──────────────
0.349s    IOControl DID=0x023F [00 01] (UNLOCK?)      ไม่เห็น response ชัด
0.849s    IOControl DID=0x023F [00 01] (UNLOCK?)      ไม่เห็น response ชัด
1.831s    IOControl DID=0x0202 [00 02] (ไม่แน่ใจ)     ✅ OK (status=[03 01])
1.958s    IOControl DID=0x023F [00 01] (UNLOCK?)      ❌ REJECTED — อยู่ Default Session
2.574s    IOControl DID=0x023F [00 00] (คืน control)   ✅ OK (status=[03 01])
2.824s    IOControl DID=0x023F [00 00] (คืน control)   ไม่เห็น response ชัด
```

### 8.2 วิเคราะห์ลำดับเหตุการณ์

**ช่วงที่ 1 (0.0s - 1.2s): ส่ง unlock + polling**

```
0.000s  เริ่ม polling (ReadDataByID, TesterPresent)
0.349s  ★ IOControl DID=0x023F [00 01]        ← unlock ครั้งที่ 1
        (ไม่เห็น positive response ในข้อมูล RX — อาจสำเร็จหรือไม่ก็ได้)
0.354s  DiagSessionControl → Extended          ← re-enter session
...     polling ต่อ...
0.849s  ★ IOControl DID=0x023F [00 01]        ← unlock ครั้งที่ 2 (retry?)
0.854s  DiagSessionControl → Extended
...     polling ต่อ...
1.213s  DiagSessionControl → Default           ← กลับ default session
```

**ช่วงที่ 2 (1.7s - 2.0s): ส่งคำสั่งเพิ่มเติม + error**

```
1.721s  DiagSessionControl → Extended
1.776s  TesterPresent → OK
1.831s  ★ IOControl DID=0x0202 [00 02]        ← คำสั่งอีก DID → ✅ สำเร็จ!
1.887s  TesterPresent → OK
1.942s  DiagSessionControl → Default           ← กลับ default session

1.953s  TesterPresent → OK
1.958s  ★ IOControl DID=0x023F [00 01]        ← unlock ครั้งที่ 3
1.961s  ❌ REJECTED: NRC=0x7F (serviceNotSupportedInActiveSession)
        → ส่งตอนอยู่ Default Session จึงถูกปฏิเสธ!
1.963s  DiagSessionControl → Extended          ← แก้ไข: เข้า Extended ใหม่
```

**ช่วงที่ 3 (2.5s - 2.8s): คืนควบคุมให้ ECU**

```
2.564s  DiagSessionControl → Extended
2.574s  ★ IOControl DID=0x023F [00 00]        ← คืน control ให้ ECU → ✅ สำเร็จ
2.584s  DiagSessionControl → Default

2.818s  ★ IOControl DID=0x023F [00 00]        ← คืน control อีกครั้ง
2.829s  DiagSessionControl → Extended
...     กลับเข้า polling loop ปกติ
```

### 8.3 สรุปขั้นตอน Unlock (Minimal Sequence)

จากการวิเคราะห์ ขั้นตอนขั้นต่ำที่ต้องทำเพื่อ unlock คือ:

```
ขั้นตอนที่ 1: เข้า Extended Diagnostic Session
  ส่ง: [02 10 03 FF FF FF FF FF] ไปที่ CAN ID 0x745
  รอ:  [06 50 03 00 32 01 F4 00] จาก CAN ID 0x765 (OK)

ขั้นตอนที่ 2: TesterPresent (keep-alive)
  ส่ง: [02 3E 00 FF FF FF FF FF] ไปที่ CAN ID 0x745
  รอ:  [02 7E 00 ...] จาก CAN ID 0x765 (OK)

ขั้นตอนที่ 3: IOControl — สั่ง Unlock
  ส่ง: [06 2F 02 3F 03 00 01 FF] ไปที่ CAN ID 0x745
  รอ:  [05 6F 02 3F 03 01 ...] จาก CAN ID 0x765 (OK)

ขั้นตอนที่ 4: IOControl — คืนควบคุมให้ ECU
  ส่ง: [06 2F 02 3F 03 00 00 FF] ไปที่ CAN ID 0x745
  รอ:  [05 6F 02 3F 03 01 ...] จาก CAN ID 0x765 (OK)

ขั้นตอนที่ 5: กลับ Default Session
  ส่ง: [02 10 01 FF FF FF FF FF] ไปที่ CAN ID 0x745
  รอ:  [06 50 01 00 32 01 F4 00] จาก CAN ID 0x765 (OK)
```

---

## 9. รายละเอียด CAN Frame ทุก byte

### 9.1 DiagnosticSessionControl → Extended Session

```
ส่ง (Request) — CAN ID: 0x745
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│ 0x02 │ 0x10 │ 0x03 │ 0xFF │ 0xFF │ 0xFF │ 0xFF │ 0xFF │
├──────┼──────┼──────┼──────┴──────┴──────┴──────┴──────┤
│ PCI  │ SID  │ Sub  │ Padding (ไม่มีความหมาย)           │
│ SF   │ Diag │ Ext  │                                   │
│ len=2│ Sess │ Sess │                                   │
└──────┴──────┴──────┴───────────────────────────────────┘

PCI = 0x02: Single Frame, ความยาว UDS payload = 2 byte
SID = 0x10: DiagnosticSessionControl
Sub = 0x03: subFunction = Extended Diagnostic Session

รับ (Positive Response) — CAN ID: 0x765
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│ 0x06 │ 0x50 │ 0x03 │ 0x00 │ 0x32 │ 0x01 │ 0xF4 │ 0x00 │
├──────┼──────┼──────┼──────┴──────┼──────┴──────┼──────┤
│ PCI  │ SID  │ Sub  │ P2 timeout  │ P2* timeout │ pad  │
│ SF   │ +Diag│ Ext  │ = 0x0032    │ = 0x01F4    │      │
│ len=6│ Sess │ Sess │ = 50 ms     │ = 500 ×10   │      │
│      │      │      │             │ = 5000 ms   │      │
└──────┴──────┴──────┴─────────────┴─────────────┴──────┘

SID = 0x50: Positive Response ของ 0x10 (0x10 + 0x40 = 0x50)
P2 timeout = 50ms: เวลาที่ ECU ใช้ตอบปกติ
P2* timeout = 5000ms: เวลาสูงสุดที่ ECU อาจใช้ (กรณี response pending)
```

### 9.2 DiagnosticSessionControl → Default Session

```
ส่ง — CAN ID: 0x745
[02 10 01 FF FF FF FF FF]
          └── 0x01 = Default Session

รับ — CAN ID: 0x765
[06 50 01 00 32 01 F4 00]
       └── 0x01 = Default Session confirmed
```

### 9.3 TesterPresent

```
ส่ง — CAN ID: 0x745
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│ 0x02 │ 0x3E │ 0x00 │ 0xFF │ 0xFF │ 0xFF │ 0xFF │ 0xFF │
├──────┼──────┼──────┼──────┴──────┴──────┴──────┴──────┤
│ PCI  │ SID  │ Sub  │ Padding                          │
│ SF   │Test  │ 0x00 │                                   │
│ len=2│ Pres │      │                                   │
└──────┴──────┴──────┴───────────────────────────────────┘

SID = 0x3E: TesterPresent — "ฉันยังอยู่ อย่าปิด session"
Sub = 0x00: subFunction ปกติ

รับ — CAN ID: 0x765
[02 7E 00 00 00 00 00 00]
    └── 0x7E = Positive Response ของ 0x3E (0x3E + 0x40 = 0x7E)
```

### 9.4 IOControlByIdentifier — Unlock (DID=0x023F)

```
ส่ง — CAN ID: 0x745
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│ 0x06 │ 0x2F │ 0x02 │ 0x3F │ 0x03 │ 0x00 │ 0x01 │ 0xFF │
├──────┼──────┼──────┴──────┼──────┼──────┴──────┼──────┤
│ PCI  │ SID  │ DID         │ ctrl │ controlState│ pad  │
│ SF   │ IO   │ = 0x023F    │ Param│ = [00 01]   │      │
│ len=6│ Ctrl │             │ short│             │      │
│      │      │             │ Term │             │      │
│      │      │             │ Adj  │             │      │
└──────┴──────┴─────────────┴──────┴─────────────┴──────┘

PCI = 0x06: Single Frame, ความยาว UDS payload = 6 byte
SID = 0x2F: IOControlByIdentifier
DID = 0x023F: door lock actuator (ตัว actuator ที่ควบคุมล็อคประตู)
controlParam = 0x03: shortTermAdjustment (ปรับค่าชั่วคราว)
controlState = [0x00, 0x01]: ค่าที่ส่งให้ actuator
  → 0x00 0x01 = สันนิษฐานว่า UNLOCK

รับ (Positive Response) — CAN ID: 0x765
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│ 0x05 │ 0x6F │ 0x02 │ 0x3F │ 0x03 │ 0x01 │ 0x00 │ 0x00 │
├──────┼──────┼──────┴──────┼──────┴──────┴──────┴──────┤
│ PCI  │ SID  │ DID echo    │ status                    │
│ SF   │ +IO  │ = 0x023F    │ = [03 01 00 00]           │
│ len=5│ Ctrl │             │                            │
└──────┴──────┴─────────────┴────────────────────────────┘

SID = 0x6F: Positive Response ของ 0x2F (0x2F + 0x40 = 0x6F)
DID echo: ECU ส่ง DID กลับมายืนยัน
status: สถานะหลังทำงาน [03 01] = controlParam echo + result
```

### 9.5 IOControlByIdentifier — คืนควบคุมให้ ECU (DID=0x023F)

```
ส่ง — CAN ID: 0x745
[06 2F 02 3F 03 00 00 FF]
                  └──┘
              controlState = [00 00]
              → คืนการควบคุมให้ ECU / หยุดสั่งงาน
```

### 9.6 IOControlByIdentifier — DID=0x0202 (ยังไม่ยืนยันหน้าที่)

```
ส่ง — CAN ID: 0x745
[06 2F 02 02 03 00 02 FF]
       └──┘     └──┘
       DID      controlState
       0x0202   [00 02]

รับ — CAN ID: 0x765
[05 6F 02 02 03 01 00 00]
       └──┘  └────────┘
       DID   status=[03 01 00 00]
       echo
```

### 9.7 Negative Response — ตัวอย่างที่เกิดขึ้นจริง

```
รับ — CAN ID: 0x765
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│ 0x03 │ 0x7F │ 0x2F │ 0x7F │ 0x00 │ 0x00 │ 0x00 │ 0x00 │
├──────┼──────┼──────┼──────┼──────┴──────┴──────┴──────┤
│ PCI  │ SID  │ rej  │ NRC  │ padding                   │
│ SF   │ Neg  │ SID  │      │                            │
│ len=3│ Resp │      │      │                            │
└──────┴──────┴──────┴──────┴────────────────────────────┘

SID = 0x7F: NegativeResponse
Rejected SID = 0x2F: คำสั่ง IOControlByIdentifier ถูกปฏิเสธ
NRC = 0x7F: serviceNotSupportedInActiveSession
→ ถูกปฏิเสธเพราะส่งคำสั่ง IOControl ตอนอยู่ใน Default Session
   ต้องเข้า Extended Session (0x03) ก่อนจึงจะส่งคำสั่งนี้ได้
```

---

## 10. ข้อจำกัดและสิ่งที่ยังไม่แน่ใจ

### 10.1 ไม่แน่ใจว่า DID ไหนคือตัว Unlock จริง ๆ

เนื่องจากประตูอาจ unlock อยู่แล้วก่อน capture:
- **DID=0x023F [00 01]** น่าจะเป็น unlock (ส่ง 3 ครั้ง, retry pattern บ่งบอกว่าสำคัญ)
- **DID=0x0202 [00 02]** ยังไม่แน่ใจ (ส่ง 1 ครั้ง, ได้ positive response)
- อาจต้องทั้ง 2 คำสั่งทำงานร่วมกัน หรืออาจต้องแค่อันเดียว

### 10.2 ไม่มี capture ของการ Lock

capture นี้มีเฉพาะ unlock จึงยังไม่รู้ว่า:
- คำสั่ง lock ใช้ DID เดียวกันแต่เปลี่ยน controlState?
  (เช่น DID=0x023F [00 02] = lock?)
- หรือใช้ DID อื่นทั้งหมด?

### 10.3 controlState ค่าอื่นยังไม่รู้ความหมาย

| DID | controlState | สถานะ | ความหมาย |
|-----|-------------|-------|----------|
| 0x023F | [00 01] | สันนิษฐาน | UNLOCK |
| 0x023F | [00 00] | ค่อนข้างแน่ใจ | คืน control ให้ ECU |
| 0x023F | [00 02] | ไม่รู้ | อาจเป็น LOCK? (ยังไม่มีข้อมูล) |
| 0x0202 | [00 02] | ไม่แน่ใจ | อาจเป็น unlock เสริม หรือ hazard light |

### 10.4 ECU 0x7E1 ไม่เคยตอบ

ใน capture ไม่เห็น response จาก ECU ที่รับ request จาก CAN ID 0x7E1
อาจเป็นเพราะ:
- ECU ตอบช้าเกินไป
- ECU ไม่รองรับคำสั่งที่ส่ง
- response ถูกรบกวนหรือหลุดไปใน noise

### 10.5 0x7FF และ Frame ผิดปกติ

- **0x7FF (DLC=15):** MCU ส่ง frame ที่มี DLC เกิน 8 (ผิดมาตรฐาน CAN 2.0)
  เป็น 0xFF ทั้งหมด — อาจเป็น bus initialization/synchronization
- **0x515, 0x7C1:** ส่งตอนเริ่มต้น อาจเป็น wake-up หรือ initialization protocol

---

## 11. วิธีใช้งาน Script

### 11.1 Script วิเคราะห์ข้อมูล

ไม่ต้องติดตั้ง library เพิ่ม ใช้ Python 3 มาตรฐาน:

```bash
# วิเคราะห์ไฟล์ RX — แสดงสถิติ frame ทั้งหมด
python parse_can_frames.py

# แกะ RX เป็น conversation พร้อม UDS decode
python extract_uds_conversation.py

# แกะ RX + TX รวม timeline
python extract_both_channels.py

# วิเคราะห์เฉพาะ unlock sequence
python analyze_unlock_sequence.py
```

### 11.2 Script สั่ง Unlock จริง (nissan_door_unlock.py)

**ต้องการ:**
- Python 3
- python-can library: `pip install python-can`
- CAN adapter ที่รองรับ python-can (เช่น CANable, PEAK PCAN-USB, SocketCAN)

```bash
# ดู frame ที่จะส่ง โดยไม่ส่งจริง (dry-run)
python nissan_door_unlock.py --dry-run -i slcan -c COM3

# สั่ง unlock ด้วย DID=0x023F เท่านั้น
python nissan_door_unlock.py -i slcan -c COM3 --method 023F

# สั่ง unlock ด้วย DID=0x0202 เท่านั้น
python nissan_door_unlock.py -i slcan -c COM3 --method 0202

# สั่ง unlock ด้วยทั้ง 2 DID (เหมือนที่อุปกรณ์เดิมทำ)
python nissan_door_unlock.py -i slcan -c COM3 --method both
```

**ตัวเลือก interface ที่รองรับ:**

| interface | ตัวอย่าง channel | อุปกรณ์ |
|-----------|-----------------|--------|
| slcan | COM3 (Windows), /dev/ttyACM0 (Linux) | CANable, USBtin |
| socketcan | can0 | Linux SocketCAN |
| pcan | PCAN_USBBUS1 | PEAK PCAN-USB |
| kvaser | 0 | Kvaser Leaf Light |
| ixxat | 0 | IXXAT USB-to-CAN |

### 11.3 Failsafe ในตัว Script

1. **Auto-retry เมื่อ session ผิด:** ถ้า ECU ตอบ NRC=0x7F จะเข้า Extended Session ใหม่แล้วส่งซ้ำ
2. **Response Pending:** ถ้า ECU ตอบ NRC=0x78 (กำลังประมวลผล) จะรอเพิ่มอีก 5 วินาที
3. **Timeout handling:** ทุกคำสั่งมี timeout (default 2 วินาที) ป้องกันค้าง
4. **คืน control ให้ ECU เสมอ:** ส่ง IOControl [00 00] หลังสั่งเสร็จ เพื่อให้ ECU กลับทำงานปกติ
5. **กลับ Default Session เสมอ:** ไม่ว่าสำเร็จหรือล้มเหลว จะกลับ Default Session ก่อนจบ
