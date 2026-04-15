# Nissan Almera N18 — OBD-II PID Scan Results

## วันที่ทดสอบ: 2026-04-15
## สภาพรถ: เครื่อง idle, จอดนิ่ง, น้ำ ~77°C

## Supported PIDs Summary

```
PID 0x00 => BE 1F A8 13   (PIDs 0x01-0x20: 16 supported)
PID 0x20 => 90 05 A0 11   (PIDs 0x21-0x40: 7 supported)
PID 0x40 => FE D8 80 01   (PIDs 0x41-0x60: 15 supported)
Total: 38 PIDs supported
```

---

## PIDs 0x01-0x1F (Confirmed — ECM 0x7E8)

| PID | ชื่อ | ค่าที่อ่านได้ | Raw | สูตร |
|---|---|---|---|---|
| 0x01 | MIL / DTC Count | MIL=OFF, DTCs=0 | 00 07 E1 00 | bit7=MIL, bit0-6=count |
| 0x03 | Fuel System Status | Closed loop | 02 | lookup |
| 0x04 | Engine Load | 38.4% | 62 | A*100/255 % |
| 0x05 | Coolant Temp | 77°C | 75 | A-40 °C |
| 0x06 | Short Term Fuel Trim B1 | -2.3% | 7D | (A-128)*100/128 % |
| 0x07 | Long Term Fuel Trim B1 | 1.6% | 82 | (A-128)*100/128 % |
| 0x0C | Engine RPM | 800 rpm | 0C 80 | (256A+B)/4 rpm |
| 0x0D | Vehicle Speed | 0 km/h | 00 | A km/h |
| 0x0E | Timing Advance | -1.5° | 7D | A/2-64 deg |
| 0x0F | Intake Air Temp | 46°C | 56 | A-40 °C |
| 0x10 | MAF Air Flow | 4.2 g/s | 01 A7 | (256A+B)/100 g/s |
| 0x11 | Throttle Position | 12.5% | 20 | A*100/255 % |
| 0x13 | O2 Sensors Present | 2 sensors | 03 | bitmask |
| 0x15 | O2 Sensor B1S2 Voltage | 0.7V | 8C FF | A/200 V |
| 0x1C | OBD Standard | EOBD (type 6) | 06 | lookup |
| 0x1F | Runtime Since Start | 3m 11s | 00 BF | 256A+B sec |

## PIDs 0x20-0x3F (Extended)

| PID | ชื่อ | ค่าที่อ่านได้ | Raw | สูตร |
|---|---|---|---|---|
| 0x21 | Distance with MIL on | 0 km | 00 00 | 256A+B km |
| 0x24 | O2 Sensor 1 (wide-range) | — | 84 94 48 3E | equiv ratio + voltage |
| 0x2E | Commanded Evap Purge | 0% | 00 | A*100/255 % |
| 0x30 | Warm-ups since DTC clear | 255 | FF | A count |
| 0x31 | Distance since DTC clear | 39,518 km | 9A 5E | 256A+B km |
| 0x33 | Barometric Pressure | 98 kPa | 62 | A kPa |
| 0x3C | Catalyst Temp B1S1 | 76.0°C | 02 F8 | (256A+B)/10-40 °C |

## PIDs 0x40-0x60 (Extended 2)

| PID | ชื่อ | ค่าที่อ่านได้ | Raw | สูตร | หมายเหตุ |
|---|---|---|---|---|---|
| 0x41 | Monitor status (drive cycle) | — | 00 07 E1 A1 | bitmask | |
| **0x42** | **ECU/Battery Voltage** | **13.2V** | 33 90 | (256A+B)/1000 V | ★ สำคัญ |
| 0x43 | Absolute Load | 38.4% | 00 62 | (256A+B)*100/255 % | |
| 0x44 | Commanded Equiv Ratio | 1.004 | 81 07 | (256A+B)/32768 | |
| 0x45 | Relative Throttle Pos | 3.1% | 08 | A*100/255 % | |
| **0x46** | **Ambient Air Temp** | **31°C** | 47 | A-40 °C | ★ สำคัญ |
| 0x47 | Absolute Throttle Pos B | 10.2% | 1A | A*100/255 % | |
| 0x49 | Accelerator Pedal Pos D | 0% | 00 | A*100/255 % | |
| 0x4A | Accelerator Pedal Pos E | 0% | 00 | A*100/255 % | |
| 0x4C | Commanded Throttle | 9.8% | 19 | A*100/255 % | |
| 0x4D | Time with MIL on | 0 min | 00 00 | 256A+B min | |
| 0x51 | Fuel Type | Gasoline (1) | 01 | lookup | |
| 0x60 | PIDs supported 0x61-0x80 | 01 00 80 | 01 00 80 00 | bitmask | มี PIDs เพิ่มอีก! |

---

## สรุปข้อมูลสำคัญสำหรับ Car Companion

| ข้อมูล | PID | สถานะ |
|---|---|---|
| Engine RPM | 0x0C | ✅ 800 rpm (idle) |
| Vehicle Speed | 0x0D | ✅ 0 km/h |
| Coolant Temp | 0x05 | ✅ 77°C |
| Throttle | 0x11 | ✅ 12.5% |
| **Battery Voltage** | **0x42** | ✅ **13.2V** |
| **Ambient Temp** | **0x46** | ✅ **31°C** |
| Barometric Pressure | 0x33 | ✅ 98 kPa |
| Fuel Type | 0x51 | ✅ Gasoline |
| Distance since clear | 0x31 | ✅ 39,518 km (≈ odometer) |
| Check Engine | 0x01 | ✅ OFF, 0 DTCs |
| Fuel Level | 0x2F | ❌ ไม่รองรับ |
| Engine Oil Temp | 0x5C | ❌ ไม่รองรับ |
| Fuel Consumption Rate | 0x5E | ❌ ไม่รองรับ |
| Gear Position | — | ❌ ไม่มี standard PID |

## PIDs ที่ยังไม่ได้ scan (0x61-0x80)

PID 0x60 = `01 00 80 00` → มี PIDs เพิ่มเติมในช่วง 0x61-0x80:
- 0x61: supported
- 0x71: supported
- ต้อง scan เพิ่ม

---

## ข้อสังเกต

1. **Fuel Level (0x2F) ไม่รองรับ** — ต้องหาจาก manufacturer DID (อาจอยู่ใน DID 0x0108 45 bytes)
2. **Distance since DTC clear = 39,518 km** — น่าจะใกล้เคียงเลขไมล์จริง
3. **Battery Voltage = 13.2V** — ค่าปกติเครื่องติด (alternator ชาร์จ)
4. **Ambient Temp = 31°C** — อุณหภูมิภายนอก
5. **Barometric = 98 kPa** — ความดันบรรยากาศ (ปกติ ~101 kPa ที่ระดับน้ำทะเล)
6. **PID 0x60 บอกว่ายังมี PIDs อีก** ในช่วง 0x61-0x80
