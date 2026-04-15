#!/usr/bin/env python3
"""
Nissan Almera N18 — OBD-II PID Reader (SLCAN)
===============================================
อ่านข้อมูลเครื่องยนต์และรถผ่าน standard OBD-II PIDs

Hardware: ESP32-C3 Super Mini + SN65HVD230 (SLCAN firmware)

Usage:
  python3 nissan_obd.py                    # อ่านครั้งเดียว
  python3 nissan_obd.py --watch            # อ่านวนซ้ำ (Ctrl+C หยุด)
  python3 nissan_obd.py --watch -i 0.5     # อ่านทุก 0.5 วินาที
  python3 nissan_obd.py --raw              # แสดง raw bytes ด้วย
  python3 nissan_obd.py --pid 0C 0D 05     # เลือก PIDs
  python3 nissan_obd.py --scan             # scan PIDs 00-60 ทั้งหมด
"""

import serial
import time
import sys
import glob
import argparse


# ============================================================================
# SLCAN
# ============================================================================

class SLCAN:
    def __init__(self, port):
        self.ser = serial.Serial(port, 115200, timeout=2)
        time.sleep(1)
        self.ser.reset_input_buffer()
        self._raw('S6')
        self._raw('O')
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    def _raw(self, cmd):
        self.ser.write((cmd + '\r').encode())
        time.sleep(0.2)
        self.ser.read(self.ser.in_waiting or 256)

    def send(self, can_id, data, wait=0.4):
        dlc = len(data)
        hex_data = ''.join(f'{b:02X}' for b in data)
        self.ser.reset_input_buffer()
        self.ser.write(f't{can_id:03X}{dlc}{hex_data}\r'.encode())
        time.sleep(wait)
        frames = []
        raw = self.ser.read(self.ser.in_waiting or 2048).decode('ascii', errors='replace')
        for part in raw.split('\r'):
            p = part.strip()
            if p.startswith('t') and len(p) >= 5:
                rid = int(p[1:4], 16)
                rd = int(p[4], 16)
                rdata = bytes.fromhex(p[5:5 + rd * 2]) if len(p) >= 5 + rd * 2 else b''
                frames.append((rid, rdata))
        return frames

    def close(self):
        try:
            self.ser.write(b'C\r')
            time.sleep(0.1)
            self.ser.close()
        except Exception:
            pass


# ============================================================================
# OBD-II Query
# ============================================================================

def obd_query(bus, pid, wait=0.4):
    """Send Mode 01 PID query via 0x7DF broadcast.
    Returns data bytes (after 41 PID) or None."""
    frames = bus.send(0x7DF,
                      [0x02, 0x01, pid, 0x00, 0x00, 0x00, 0x00, 0x00],
                      wait=wait)
    for rid, rdata in frames:
        if rid in (0x7E8, 0x7E9) and len(rdata) >= 3:
            if rdata[1] == 0x41 and rdata[2] == pid:
                return rdata[3:]
    return None


def obd_query_raw(bus, pid, wait=0.4):
    """Like obd_query but returns (data_bytes, raw_response_bytes, ecuid)."""
    frames = bus.send(0x7DF,
                      [0x02, 0x01, pid, 0x00, 0x00, 0x00, 0x00, 0x00],
                      wait=wait)
    for rid, rdata in frames:
        if rid in (0x7E8, 0x7E9) and len(rdata) >= 3:
            if rdata[1] == 0x41 and rdata[2] == pid:
                return rdata[3:], rdata, rid
    return None, None, None


# ============================================================================
# PID Definitions — decode formulas
# ============================================================================

PIDS = {
    # PID: (name, data_bytes_needed, decode_func, unit)
    0x01: ('MIL / DTC Count', 1, None, ''),
    0x03: ('Fuel System Status', 1, None, ''),
    0x04: ('Engine Load', 1, lambda d: d[0] * 100 / 255, '%'),
    0x05: ('Coolant Temp', 1, lambda d: d[0] - 40, 'C'),
    0x06: ('Short Term Fuel Trim B1', 1, lambda d: (d[0] - 128) * 100 / 128, '%'),
    0x07: ('Long Term Fuel Trim B1', 1, lambda d: (d[0] - 128) * 100 / 128, '%'),
    0x0C: ('Engine RPM', 2, lambda d: (d[0] * 256 + d[1]) / 4, 'rpm'),
    0x0D: ('Vehicle Speed', 1, lambda d: d[0], 'km/h'),
    0x0E: ('Timing Advance', 1, lambda d: d[0] / 2 - 64, 'deg'),
    0x0F: ('Intake Air Temp', 1, lambda d: d[0] - 40, 'C'),
    0x10: ('MAF Air Flow', 2, lambda d: (d[0] * 256 + d[1]) / 100, 'g/s'),
    0x11: ('Throttle Position', 1, lambda d: d[0] * 100 / 255, '%'),
    0x13: ('O2 Sensors Present', 1, None, ''),
    0x15: ('O2 Sensor B1S2 Voltage', 1, lambda d: d[0] / 200, 'V'),
    0x1C: ('OBD Standard', 1, None, ''),
    0x1F: ('Runtime Since Start', 2, lambda d: d[0] * 256 + d[1], 'sec'),
    # Extended PIDs (0x21-0x40) — query PID 0x20 first to confirm
    0x21: ('Distance with MIL', 2, lambda d: d[0] * 256 + d[1], 'km'),
    0x2F: ('Fuel Level', 1, lambda d: d[0] * 100 / 255, '%'),
    0x30: ('Warm-ups since DTC clear', 1, lambda d: d[0], 'count'),
    0x31: ('Distance since DTC clear', 2, lambda d: d[0] * 256 + d[1], 'km'),
    0x33: ('Barometric Pressure', 1, lambda d: d[0], 'kPa'),
    # Extended PIDs (0x41-0x60)
    0x42: ('ECU/Battery Voltage', 2, lambda d: (d[0] * 256 + d[1]) / 1000, 'V'),
    0x46: ('Ambient Air Temp', 1, lambda d: d[0] - 40, 'C'),
    0x5C: ('Engine Oil Temp', 1, lambda d: d[0] - 40, 'C'),
    0x5E: ('Fuel Consumption Rate', 2, lambda d: (d[0] * 256 + d[1]) / 20, 'L/h'),
}

FUEL_SYSTEM = {
    0: 'Off', 1: 'Open loop (cold)', 2: 'Closed loop',
    4: 'Open loop (load)', 8: 'Open loop (fault)', 16: 'Closed loop (fault)',
}

OBD_STANDARD = {
    1: 'OBD-II (CARB)', 2: 'OBD (EPA)', 3: 'OBD+OBD-II',
    6: 'EOBD', 7: 'EOBD+OBD-II', 9: 'EOBD+OBD', 13: 'JOBD',
    14: 'Euro 5 (EOBD)', 17: 'Euro 6',
}


def decode_pid(pid, data):
    """Decode PID data to (value_str, raw_hex)."""
    raw_hex = ' '.join(f'{b:02X}' for b in data)

    if pid not in PIDS:
        return raw_hex, raw_hex

    name, need, func, unit = PIDS[pid]

    if len(data) < need:
        return 'INCOMPLETE', raw_hex

    # Special PIDs
    if pid == 0x01:
        mil = 'ON' if (data[0] & 0x80) else 'OFF'
        dtc = data[0] & 0x7F
        return f'MIL={mil}, DTCs={dtc}', raw_hex

    if pid == 0x03:
        return FUEL_SYSTEM.get(data[0], f'0x{data[0]:02X}'), raw_hex

    if pid == 0x1C:
        return OBD_STANDARD.get(data[0], f'type {data[0]}'), raw_hex

    if pid == 0x13:
        count = bin(data[0]).count('1')
        return f'{count} sensors (0x{data[0]:02X})', raw_hex

    if func:
        val = func(data)
        if isinstance(val, float):
            return f'{val:.1f} {unit}', raw_hex
        return f'{val} {unit}', raw_hex

    return raw_hex, raw_hex


def format_runtime(seconds):
    """Format seconds to human-readable."""
    if seconds >= 3600:
        return f'{seconds // 3600}h {(seconds % 3600) // 60}m {seconds % 60}s'
    return f'{seconds // 60}m {seconds % 60}s'


# ============================================================================
# Scan & Read
# ============================================================================

# PIDs confirmed supported by ECM (from PID 0x00 = BE 1F A8 13)
CONFIRMED_PIDS = [
    0x01, 0x03, 0x04, 0x05, 0x06, 0x07,
    0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11,
    0x13, 0x15, 0x1C, 0x1F,
]


def read_all(bus, pids=None, show_raw=False):
    """Read and display PIDs."""
    if pids is None:
        pids = CONFIRMED_PIDS

    for pid in pids:
        data = obd_query(bus, pid)
        name = PIDS.get(pid, (f'PID 0x{pid:02X}', 0, None, ''))[0]

        if data is None:
            print(f'  {name:25s}: N/A')
            continue

        val_str, raw_hex = decode_pid(pid, data)

        # Pretty format for runtime
        if pid == 0x1F and data and len(data) >= 2:
            secs = data[0] * 256 + data[1]
            val_str = format_runtime(secs)

        if show_raw:
            print(f'  {name:25s}: {val_str:20s} [{raw_hex}]')
        else:
            print(f'  {name:25s}: {val_str}')


def scan_supported_pids(bus):
    """Query PID 0x00, 0x20, 0x40 to discover all supported PIDs."""
    all_supported = []

    for base_pid in [0x00, 0x20, 0x40]:
        data = obd_query(bus, base_pid)
        if data is None or len(data) < 4:
            break

        bits = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
        for i in range(32):
            if bits & (1 << (31 - i)):
                supported_pid = base_pid + i + 1
                all_supported.append(supported_pid)

        raw_hex = ' '.join(f'{b:02X}' for b in data)
        print(f'  PID 0x{base_pid:02X} => {raw_hex}')

        # Check if next range is supported
        if not (bits & 1):  # last bit = next range supported
            break

    return all_supported


def scan_and_read(bus, show_raw=False):
    """Scan all supported PIDs and read their values."""
    print('--- Scanning supported PIDs ---')
    supported = scan_supported_pids(bus)
    print(f'  Total: {len(supported)} PIDs supported')
    print()

    print('--- Reading all supported PIDs ---')
    for pid in supported:
        data = obd_query(bus, pid, wait=0.3)
        name = PIDS.get(pid, (f'PID 0x{pid:02X}', 0, None, ''))[0]

        if data is None:
            print(f'  0x{pid:02X} {name:25s}: N/A')
            continue

        val_str, raw_hex = decode_pid(pid, data)

        if pid == 0x1F and data and len(data) >= 2:
            secs = data[0] * 256 + data[1]
            val_str = format_runtime(secs)

        if show_raw:
            print(f'  0x{pid:02X} {name:25s}: {val_str:20s} [{raw_hex}]')
        else:
            print(f'  0x{pid:02X} {name:25s}: {val_str}')


# ============================================================================
# Main
# ============================================================================

def find_port():
    candidates = glob.glob('/dev/cu.usbmodem*') + glob.glob('/dev/ttyACM*')
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser(
        description='Nissan Almera N18 — OBD-II PID Reader',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python3 nissan_obd.py                  # read confirmed PIDs once
  python3 nissan_obd.py --watch          # live dashboard
  python3 nissan_obd.py --scan           # discover + read all PIDs
  python3 nissan_obd.py --pid 0C 0D 05   # read specific PIDs
  python3 nissan_obd.py --raw            # show raw bytes
""")
    parser.add_argument('--port', '-p', help='Serial port (auto-detect)')
    parser.add_argument('--watch', '-w', action='store_true',
                        help='Live update mode (Ctrl+C to stop)')
    parser.add_argument('--interval', '-i', type=float, default=1.0,
                        help='Watch interval seconds (default: 1.0)')
    parser.add_argument('--raw', '-r', action='store_true',
                        help='Show raw hex bytes')
    parser.add_argument('--scan', '-s', action='store_true',
                        help='Scan all supported PIDs (0x00-0x60)')
    parser.add_argument('--pid', nargs='+', metavar='XX',
                        help='Specific PIDs to read (hex, e.g. 0C 0D 05)')
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        print('ERROR: no serial port. Use --port')
        sys.exit(1)

    print(f'Connecting to {port}...')
    bus = SLCAN(port)
    print('Connected!\n')

    try:
        if args.scan:
            scan_and_read(bus, show_raw=args.raw)

        elif args.watch:
            pids = None
            if args.pid:
                pids = [int(p, 16) for p in args.pid]
            else:
                # Dashboard: just key PIDs for speed
                pids = [0x0C, 0x0D, 0x05, 0x04, 0x11, 0x1F]

            print('Live dashboard (Ctrl+C to stop)\n')
            while True:
                print(f'\033[2J\033[H', end='')  # clear screen
                print('=' * 45)
                print('  Nissan Almera N18 — Live Dashboard')
                print('=' * 45)
                print()
                read_all(bus, pids, show_raw=args.raw)
                print(f'\n  [{time.strftime("%H:%M:%S")}] interval={args.interval}s')
                time.sleep(args.interval)

        else:
            pids = None
            if args.pid:
                pids = [int(p, 16) for p in args.pid]
            read_all(bus, pids, show_raw=args.raw)

    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        bus.close()


if __name__ == '__main__':
    main()
