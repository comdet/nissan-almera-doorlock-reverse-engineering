#!/usr/bin/env python3
"""
Nissan Almera N18 — Car Status Reader (SLCAN)
===============================================
อ่านสถานะรถครบ: ประตู, เกียร์, ล็อค, OBD PIDs

Hardware: ESP32-C3 Super Mini + SN65HVD230 (SLCAN firmware)

Usage:
  python3 nissan_car_status.py              # อ่านครั้งเดียว
  python3 nissan_car_status.py --watch      # live dashboard
  python3 nissan_car_status.py --json       # output JSON
"""

import serial
import time
import sys
import glob
import json
import argparse


# ============================================================================
# SLCAN
# ============================================================================

class SLCAN:
    def __init__(self, port):
        self.ser = serial.Serial(port, 115200, timeout=2)
        time.sleep(1)
        self.ser.reset_input_buffer()
        self.ser.write(b'S6\r')
        time.sleep(0.2)
        self.ser.write(b'O\r')
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    def raw_send(self, can_id, data):
        dlc = len(data)
        hex_data = ''.join(f'{b:02X}' for b in data)
        self.ser.write(f't{can_id:03X}{dlc}{hex_data}\r'.encode())

    def read_did(self, req_id, did):
        """Read DID with multiframe + NRC 0x78 handling."""
        dh = (did >> 8) & 0xFF
        dl = did & 0xFF
        self.ser.reset_input_buffer()
        self.raw_send(req_id, [0x02, 0x10, 0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
        time.sleep(0.3)
        self.ser.reset_input_buffer()
        self.raw_send(req_id, [0x03, 0x22, dh, dl, 0xFF, 0xFF, 0xFF, 0xFF])

        all_data = bytearray()
        total_len = 0
        ff_found = False
        end = time.time() + 6

        while time.time() < end:
            time.sleep(0.05)
            n = self.ser.in_waiting
            if not n:
                continue
            raw = self.ser.read(n).decode('ascii', errors='replace')
            for part in raw.split('\r'):
                p = part.strip()
                if not p.startswith('t') or len(p) < 5:
                    continue
                rd = int(p[4], 16)
                rdata = bytes.fromhex(p[5:5 + rd * 2]) if len(p) >= 5 + rd * 2 else b''
                if not rdata:
                    continue
                pci = (rdata[0] >> 4) & 0x0F
                if len(rdata) >= 4 and rdata[1] == 0x7F:
                    if rdata[3] == 0x78:
                        continue
                    return None
                if pci == 0 and not ff_found:
                    pci_len = rdata[0] & 0x0F
                    self.raw_send(req_id, [0x02, 0x10, 0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
                    return bytes(rdata[1:1 + pci_len])
                if pci == 1 and not ff_found:
                    total_len = ((rdata[0] & 0x0F) << 8) | rdata[1]
                    all_data = bytearray(rdata[2:])
                    ff_found = True
                    self.raw_send(req_id, [0x30, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
                if pci == 2 and ff_found:
                    all_data.extend(rdata[1:])
            if ff_found and len(all_data) >= total_len:
                break

        self.raw_send(req_id, [0x02, 0x10, 0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
        time.sleep(0.2)
        return bytes(all_data[:total_len]) if all_data else None

    def obd_query(self, pid):
        """OBD-II Mode 01 query via 0x7DF."""
        self.ser.reset_input_buffer()
        self.raw_send(0x7DF, [0x02, 0x01, pid, 0x00, 0x00, 0x00, 0x00, 0x00])
        time.sleep(0.4)
        raw = self.ser.read(self.ser.in_waiting or 1024).decode('ascii', errors='replace')
        for part in raw.split('\r'):
            p = part.strip()
            if p.startswith('t7E8') and len(p) >= 5:
                rd = int(p[4], 16)
                rdata = bytes.fromhex(p[5:5 + rd * 2]) if len(p) >= 5 + rd * 2 else b''
                if len(rdata) >= 3 and rdata[1] == 0x41 and rdata[2] == pid:
                    return rdata[3:]
        return None

    def close(self):
        try:
            self.ser.write(b'C\r')
            time.sleep(0.1)
            self.ser.close()
        except Exception:
            pass


# ============================================================================
# Decode Functions
# ============================================================================

# DID 0x0109 byte 6 — door open/close bitmask
DOOR_BITS = {
    7: 'driver',        # 0x80
    6: 'passenger',     # 0x40
    5: 'rear_left',     # 0x20
    4: 'rear_right',    # 0x10
    3: 'trunk',         # 0x08
}

# DID 0x0108 byte 27 — gear position
GEAR_MAP = {
    0x80: 'P',
    0x00: 'R',
    0x40: 'N',
    0xC0: 'D',  # D and L share same value
}


def decode_doors(did_0109):
    """Decode DID 0x0109 → dict of door states."""
    if not did_0109 or len(did_0109) < 9:
        return None

    result = {}

    # Byte 6: door open/close
    b6 = did_0109[6]
    doors_open = []
    for bit, name in DOOR_BITS.items():
        is_open = bool(b6 & (1 << bit))
        result[f'{name}_open'] = is_open
        if is_open:
            doors_open.append(name)
    result['any_open'] = len(doors_open) > 0
    result['doors_open_list'] = doors_open

    # Byte 8: lock status
    b8 = did_0109[8]
    result['locked'] = b8 == 0x00
    result['unlocked'] = b8 == 0x10
    result['lock_status'] = 'LOCKED' if b8 == 0x00 else 'UNLOCKED' if b8 == 0x10 else f'?(0x{b8:02X})'

    # Byte 17: brake pedal
    if len(did_0109) > 17:
        b17 = did_0109[17]
        result['brake_pedal'] = b17 != 0x00
        result['brake_pedal_raw'] = b17

    return result


def decode_gear(did_0108):
    """Decode DID 0x0108 byte 27 → gear string.

    Note: byte 27 is reliable for gear only when engine is running.
    When engine is off, handbrake/engine state contaminates the value.
    """
    if not did_0108 or len(did_0108) < 28:
        return None
    b27 = did_0108[27]
    return GEAR_MAP.get(b27, f'?(0x{b27:02X})')


def decode_handbrake(did_0e07):
    """Decode DID 0x0E07 byte 19 → handbrake status."""
    if not did_0e07 or len(did_0e07) < 20:
        return None
    b19 = did_0e07[19]
    return b19 == 0x10  # True = ON


def decode_engine(did_1301, did_1304):
    """Decode engine status from DIDs 0x1301/0x1304."""
    result = {}
    if did_1301 and len(did_1301) >= 4:
        result['status_1301'] = did_1301[3]
        result['running'] = did_1301[3] == 0x10
    if did_1304 and len(did_1304) >= 4:
        result['status_1304'] = did_1304[3]
    return result


# ============================================================================
# Read All Status
# ============================================================================

def read_car_status(bus):
    """Read all car status. Returns dict."""
    status = {}

    # Doors + Lock (DID 0x0109)
    d = bus.read_did(0x745, 0x0109)
    doors = decode_doors(d)
    if doors:
        status.update(doors)

    # Gear (DID 0x0108)
    d = bus.read_did(0x74C, 0x0108)
    gear = decode_gear(d)
    if gear:
        status['gear'] = gear

    # Handbrake (DID 0x0E07)
    d = bus.read_did(0x743, 0x0E07)
    hb = decode_handbrake(d)
    if hb is not None:
        status['handbrake'] = hb
        status['handbrake_status'] = 'ON' if hb else 'OFF'

    # Engine DIDs
    d1 = bus.read_did(0x7E1, 0x1301)
    d2 = bus.read_did(0x7E1, 0x1304)
    eng = decode_engine(d1, d2)
    if eng:
        status.update(eng)

    # OBD PIDs
    d = bus.obd_query(0x0C)
    if d and len(d) >= 2:
        status['rpm'] = (d[0] * 256 + d[1]) / 4

    d = bus.obd_query(0x0D)
    if d and len(d) >= 1:
        status['speed'] = d[0]

    d = bus.obd_query(0x05)
    if d and len(d) >= 1:
        status['coolant_temp'] = d[0] - 40

    d = bus.obd_query(0x42)
    if d and len(d) >= 2:
        status['battery_v'] = (d[0] * 256 + d[1]) / 1000

    d = bus.obd_query(0x46)
    if d and len(d) >= 1:
        status['ambient_temp'] = d[0] - 40

    d = bus.obd_query(0x11)
    if d and len(d) >= 1:
        status['throttle'] = d[0] * 100 / 255

    return status


def print_status(s):
    """Pretty print car status."""
    print('  --- Engine ---')
    print(f'  RPM            : {s.get("rpm", "?"):.0f}' if 'rpm' in s else '  RPM            : N/A')
    print(f'  Speed          : {s.get("speed", "?")} km/h')
    print(f'  Coolant        : {s.get("coolant_temp", "?")}°C')
    print(f'  Battery        : {s.get("battery_v", "?"):.1f}V' if 'battery_v' in s else '  Battery        : N/A')
    print(f'  Ambient        : {s.get("ambient_temp", "?")}°C')
    print(f'  Throttle       : {s.get("throttle", "?"):.1f}%' if 'throttle' in s else '  Throttle       : N/A')

    print('  --- Transmission ---')
    print(f'  Gear           : {s.get("gear", "?")}')
    print(f'  Handbrake      : {s.get("handbrake_status", "?")}')

    print('  --- Doors ---')
    print(f'  Lock           : {s.get("lock_status", "?")}')
    for name in ['driver', 'passenger', 'rear_left', 'rear_right', 'trunk']:
        key = f'{name}_open'
        if key in s:
            state = 'OPEN' if s[key] else 'closed'
            label = name.replace('_', ' ').title()
            print(f'  {label:15s}: {state}')
    print(f'  Brake Pedal    : {"PRESSED" if s.get("brake_pedal") else "released"}')


# ============================================================================
# Main
# ============================================================================

def find_port():
    candidates = glob.glob('/dev/cu.usbmodem*') + glob.glob('/dev/ttyACM*')
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser(description='Nissan Almera N18 — Car Status')
    parser.add_argument('--port', '-p', help='Serial port')
    parser.add_argument('--watch', '-w', action='store_true', help='Live mode')
    parser.add_argument('--interval', '-i', type=float, default=2.0, help='Watch interval')
    parser.add_argument('--json', '-j', action='store_true', help='JSON output')
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        print('ERROR: no port')
        sys.exit(1)

    if not args.json:
        print(f'Connecting to {port}...')
    bus = SLCAN(port)
    if not args.json:
        print('Connected!\n')

    try:
        if args.watch:
            while True:
                s = read_car_status(bus)
                if args.json:
                    print(json.dumps(s))
                else:
                    print('\033[2J\033[H', end='')
                    print('=' * 40)
                    print('  Nissan Almera N18 — Car Status')
                    print('=' * 40)
                    print()
                    print_status(s)
                    print(f'\n  [{time.strftime("%H:%M:%S")}]')
                time.sleep(args.interval)
        else:
            s = read_car_status(bus)
            if args.json:
                print(json.dumps(s, indent=2))
            else:
                print_status(s)

    except KeyboardInterrupt:
        if not args.json:
            print('\nStopped.')
    finally:
        bus.close()


if __name__ == '__main__':
    main()
