#!/usr/bin/env python3
"""
Nissan Almera N18 — DID Diff Tool
===================================
อ่าน manufacturer DIDs 2 รอบ แล้วแสดง byte ที่เปลี่ยน
ใช้สำหรับ decode ว่า byte ไหนคืออะไร

Usage:
  python3 nissan_diff.py              # interactive diff
  python3 nissan_diff.py --loop       # วนหลายรอบ
"""

import serial
import time
import sys
import glob
import argparse


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

    def read_frames(self, timeout=0.5):
        frames = []
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(0.03)
            n = self.ser.in_waiting
            if n:
                raw = self.ser.read(n).decode('ascii', errors='replace')
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


def read_did(bus, req_id, did):
    """Read a DID with multiframe + NRC 0x78 handling. Returns bytes or None."""
    dh = (did >> 8) & 0xFF
    dl = did & 0xFF

    bus.ser.reset_input_buffer()
    bus.raw_send(req_id, [0x02, 0x10, 0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    time.sleep(0.3)
    bus.ser.reset_input_buffer()

    bus.raw_send(req_id, [0x03, 0x22, dh, dl, 0xFF, 0xFF, 0xFF, 0xFF])

    all_data = bytearray()
    total_len = 0
    ff_found = False
    end = time.time() + 6  # long timeout for NRC 0x78

    while time.time() < end:
        time.sleep(0.05)
        n = bus.ser.in_waiting
        if not n:
            continue
        raw = bus.ser.read(n).decode('ascii', errors='replace')
        for part in raw.split('\r'):
            p = part.strip()
            if not p.startswith('t') or len(p) < 5:
                continue
            rd = int(p[4], 16)
            rdata = bytes.fromhex(p[5:5 + rd * 2]) if len(p) >= 5 + rd * 2 else b''
            if not rdata:
                continue

            pci = (rdata[0] >> 4) & 0x0F

            # Negative response
            if len(rdata) >= 4 and rdata[1] == 0x7F:
                if rdata[3] == 0x78:
                    continue  # pending, keep waiting
                return None

            # Single frame
            if pci == 0 and not ff_found:
                pci_len = rdata[0] & 0x0F
                bus.raw_send(req_id, [0x02, 0x10, 0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
                return bytes(rdata[1:1 + pci_len])

            # First frame
            if pci == 1 and not ff_found:
                total_len = ((rdata[0] & 0x0F) << 8) | rdata[1]
                all_data = bytearray(rdata[2:])
                ff_found = True
                bus.raw_send(req_id, [0x30, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])

            # Consecutive frame
            if pci == 2 and ff_found:
                all_data.extend(rdata[1:])

        if ff_found and len(all_data) >= total_len:
            break

    bus.raw_send(req_id, [0x02, 0x10, 0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    time.sleep(0.2)

    if all_data:
        return bytes(all_data[:total_len])
    return None


# DID definitions
DIDS = [
    (0x745, 0x0109, 'Door/Body (BCM)'),
    (0x74C, 0x0108, 'Body Data (45B)'),
    (0x743, 0x0E07, 'Light/Body'),
    (0x7E1, 0x1301, 'Engine Status'),
    (0x7E1, 0x1304, 'Engine Status 2'),
]


def read_all_dids(bus):
    """Read all manufacturer DIDs. Returns dict of {did: bytes}."""
    results = {}
    for req_id, did, name in DIDS:
        data = read_did(bus, req_id, did)
        results[did] = data
    return results


def show_diff(before, after, label=''):
    """Show byte-by-byte diff between two readings."""
    if label:
        print(f'\n  === {label} ===')

    any_change = False

    for req_id, did, name in DIDS:
        b = before.get(did)
        a = after.get(did)

        if b is None or a is None:
            if b != a:
                print(f'\n  DID 0x{did:04X} {name}: {"N/A -> data" if b is None else "data -> N/A"}')
            continue

        if b == a:
            continue

        any_change = True
        print(f'\n  DID 0x{did:04X} {name}:')

        for i in range(max(len(b), len(a))):
            bv = b[i] if i < len(b) else None
            av = a[i] if i < len(a) else None
            if bv != av:
                bstr = f'0x{bv:02X}' if bv is not None else '  --'
                astr = f'0x{av:02X}' if av is not None else '  --'

                # Show binary diff for bitmask analysis
                if bv is not None and av is not None:
                    bdiff = bv ^ av
                    bits_changed = f'  XOR=0x{bdiff:02X} ({bdiff:08b})'
                else:
                    bits_changed = ''

                print(f'    byte {i:2d}: {bstr} -> {astr}{bits_changed}')

    if not any_change:
        print('\n  (no changes detected)')


def main():
    parser = argparse.ArgumentParser(description='Nissan DID Diff Tool')
    parser.add_argument('--port', '-p', help='Serial port')
    parser.add_argument('--loop', '-l', action='store_true', help='Loop mode')
    args = parser.parse_args()

    port = args.port or (glob.glob('/dev/cu.usbmodem*') + glob.glob('/dev/ttyACM*') or [None])[0]
    if not port:
        print('ERROR: no port')
        sys.exit(1)

    print(f'Connecting to {port}...')
    bus = SLCAN(port)
    print('Connected!\n')

    try:
        round_num = 0
        baseline = None

        while True:
            round_num += 1

            if baseline is None:
                input('  Press ENTER to read BASELINE (current state)...')
                print('  Reading...')
                baseline = read_all_dids(bus)
                print('  Baseline saved:')
                for req_id, did, name in DIDS:
                    d = baseline.get(did)
                    if d:
                        print(f'    DID 0x{did:04X} {name}: {len(d)} bytes')
                    else:
                        print(f'    DID 0x{did:04X} {name}: N/A')
                print()
                print('  Now change something (open door, shift gear, etc.)')
            else:
                label = input(f'  [{round_num}] What did you change? (or "reset" / "quit"): ').strip()
                if label.lower() in ('q', 'quit', 'exit'):
                    break
                if label.lower() in ('r', 'reset'):
                    baseline = None
                    print('  Baseline cleared.\n')
                    continue

                print('  Reading...')
                after = read_all_dids(bus)
                show_diff(baseline, after, label or f'Round {round_num}')
                print()

                if not args.loop:
                    cont = input('  Continue? (y/n/reset): ').strip().lower()
                    if cont in ('n', 'q', 'quit'):
                        break
                    if cont in ('r', 'reset'):
                        baseline = None
                        print('  Baseline cleared.\n')
                        continue

    except (KeyboardInterrupt, EOFError):
        print('\nDone.')
    finally:
        bus.close()


if __name__ == '__main__':
    main()
