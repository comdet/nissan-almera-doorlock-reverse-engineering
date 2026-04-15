# ESP32-C3 SLCAN CAN Bus Adapter

Firmware สำหรับ ESP32-C3 + SN65HVD230 CAN transceiver
ทำหน้าที่เป็น SLCAN (Serial-Line CAN) adapter ให้ python-can สื่อสารกับ CAN Bus ของรถได้

## Hardware ที่ต้องใช้

- ESP32-C3 development board (เช่น ESP32-C3-DevKitM-1)
- SN65HVD230 CAN transceiver module (3.3V)
- สาย jumper

## การต่อสาย

```
ESP32-C3           SN65HVD230          CAN Bus (OBD-II)
─────────          ──────────          ────────────────
3.3V ──────────── VCC
GND  ──────────── GND ─────────────── GND (pin 4,5)
GPIO4 (TX) ────── D (Driver Input)
GPIO5 (RX) ────── R (Receiver Output)
                   CANH ──────────────── CAN-H (pin 6)
                   CANL ──────────────── CAN-L (pin 14)
                   Rs ────── GND         (high speed mode)
```

### OBD-II Pinout ที่เกี่ยวข้อง

```
OBD-II Connector (มองจากด้านหน้า)
┌─────────────────────────────────┐
│  1   2   3   4   5   6   7   8 │
│  9  10  11  12  13  14  15  16  │
└─────────────────────────────────┘

Pin 4  = Chassis Ground
Pin 5  = Signal Ground
Pin 6  = CAN-H (High)
Pin 14 = CAN-L (Low)
Pin 16 = Battery Power (+12V) — ไม่ต้องต่อกับ ESP32 โดยตรง!
```

### ข้อควรระวัง

- SN65HVD230 VCC ต้องต่อ **3.3V เท่านั้น** (ห้ามต่อ 5V!)
- SN65HVD230 Rs pin ต่อ GND = high speed mode (เหมาะกับ 500kbps)
- หลีก GPIO2, GPIO8, GPIO9 ของ ESP32-C3 (strapping pins อาจทำให้ boot ไม่ได้)

## การ Flash Firmware

### ด้วย PlatformIO (แนะนำ)

```bash
cd firmware
pio run -t upload
```

### ด้วย Arduino IDE

1. ติดตั้ง Arduino ESP32 core (Board Manager → esp32 by Espressif)
2. เลือก Board: "ESP32C3 Dev Module"
3. เปิดไฟล์ `src/main.cpp`
4. Upload

## การใช้งานกับ python-can

### ติดตั้ง

```bash
pip install python-can
```

### ทดสอบเบื้องต้น

```python
import can

# เปลี่ยน channel ตาม OS:
#   macOS:  /dev/cu.usbmodem*  หรือ /dev/tty.usbmodem*
#   Linux:  /dev/ttyACM0
#   Windows: COM3 (ดูจาก Device Manager)

bus = can.interface.Bus(
    interface='slcan',
    channel='/dev/tty.usbmodem1101',  # เปลี่ยนตาม port จริง
    bitrate=500000
)

# ดักฟัง CAN frame
print("Listening for CAN frames... (Ctrl+C to stop)")
try:
    while True:
        msg = bus.recv(timeout=1.0)
        if msg:
            print(msg)
except KeyboardInterrupt:
    pass
finally:
    bus.shutdown()
```

### สั่ง Unlock ประตู

```bash
# Dry run (ดู frame ที่จะส่ง ไม่ส่งจริง)
python nissan_door_unlock.py --dry-run -i slcan -c /dev/tty.usbmodem1101

# สั่ง unlock จริง
python nissan_door_unlock.py -i slcan -c /dev/tty.usbmodem1101 --method 023F
```

## หา Serial Port

### macOS
```bash
ls /dev/cu.usbmodem*
```

### Linux
```bash
ls /dev/ttyACM*
```

### Windows
ดูจาก Device Manager → Ports (COM & LPT)

## SLCAN Protocol

Firmware นี้ implement SLCAN (LAWICEL) protocol ครบ:

| Command | Description |
|---------|-------------|
| `Sn`    | Set speed (S6 = 500kbps) |
| `O`     | Open CAN channel |
| `C`     | Close CAN channel |
| `tIIILDD..` | Send standard frame |
| `TIIIIIIIILDD..` | Send extended frame |
| `F`     | Read status flags |
| `V`     | Hardware version |
| `N`     | Serial number |

python-can จัดการ protocol นี้ให้อัตโนมัติ ไม่ต้องส่ง command เอง
