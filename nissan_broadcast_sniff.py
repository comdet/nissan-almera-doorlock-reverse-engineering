#!/usr/bin/env python3
"""
Nissan Almera N18 — CAN Broadcast Sniffer
==========================================
ฟัง broadcast traffic บน CAN bus เพื่อหา passive messages
ที่ไม่ต้อง poll (RPM, speed, doors, brake, turn signals ฯลฯ)

Hardware: ESP32-C3 + SN65HVD230 (ต้องใช้ SLCAN firmware เดิม!)

Usage:
  python3 nissan_broadcast_sniff.py                    # ฟังเฉยๆ แสดง summary
  python3 nissan_broadcast_sniff.py --duration 30      # ฟัง 30 วินาที
  python3 nissan_broadcast_sniff.py --diff              # interactive diff mode
  python3 nissan_broadcast_sniff.py --watch 0x354       # ดู CAN ID เฉพาะตัว
"""

import serial
import time
import sys
import glob
import argparse
from collections import defaultdict


# ============================================================================
# SLCAN — passive listen mode (ไม่ส่งอะไรเลย แค่ฟัง)
# ============================================================================

class SLCANListener:
    def __init__(self, port):
        self.ser = serial.Serial(port, 115200, timeout=0.1)
        time.sleep(1)
        self.ser.reset_input_buffer()
        self.ser.write(b'S6\r')  # 500kbps
        time.sleep(0.2)
        self.ser.write(b'O\r')   # Open channel
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    def read_frames(self):
        """Read all available frames. Returns list of (can_id, data_bytes)."""
        frames = []
        n = self.ser.in_waiting
        if not n:
            return frames
        raw = self.ser.read(n).decode('ascii', errors='replace')
        for part in raw.split('\r'):
            p = part.strip()
            if not p.startswith('t') or len(p) < 5:
                continue
            try:
                can_id = int(p[1:4], 16)
                dlc = int(p[4], 16)
                if len(p) >= 5 + dlc * 2:
                    data = bytes.fromhex(p[5:5 + dlc * 2])
                    frames.append((can_id, data))
            except (ValueError, IndexError):
                continue
        return frames

    def close(self):
        try:
            self.ser.write(b'C\r')
            time.sleep(0.1)
            self.ser.close()
        except Exception:
            pass


# ============================================================================
# Sniff Mode — summary of all broadcast CAN IDs
# ============================================================================

# Known diagnostic IDs to filter out
DIAG_IDS = {
    0x745, 0x765,  # BCM
    0x74C, 0x76C,  # Body ECU 2
    0x743, 0x763,  # Light ECU
    0x7E0, 0x7E8,  # ECM physical
    0x7E1, 0x7E9,  # Engine ECU
    0x7DF,          # OBD broadcast request
    0x7FF,          # max ID
}


def sniff_summary(listener, duration):
    """Passive listen: collect all CAN IDs and their data patterns."""
    print(f'Listening for {duration}s (passive only, no TX)...\n')

    stats = defaultdict(lambda: {
        'count': 0,
        'first_seen': None,
        'last_seen': None,
        'data_samples': set(),
        'dlc': 0,
    })

    start = time.time()
    total_frames = 0

    while time.time() - start < duration:
        frames = listener.read_frames()
        now = time.time() - start
        for can_id, data in frames:
            total_frames += 1
            s = stats[can_id]
            s['count'] += 1
            s['dlc'] = len(data)
            if s['first_seen'] is None:
                s['first_seen'] = now
            s['last_seen'] = now
            # Keep up to 20 unique payloads
            if len(s['data_samples']) < 20:
                s['data_samples'].add(data.hex(' '))

    print(f'Total frames received: {total_frames}')
    print(f'Unique CAN IDs: {len(stats)}')
    print()

    # Separate broadcast vs diagnostic
    broadcast_ids = {k: v for k, v in stats.items() if k not in DIAG_IDS}
    diag_ids = {k: v for k, v in stats.items() if k in DIAG_IDS}

    if broadcast_ids:
        print('=' * 80)
        print('BROADCAST MESSAGES (passive — ECU ส่งเอง)')
        print('=' * 80)
        print(f'{"CAN ID":>10} {"Count":>8} {"Rate":>8} {"DLC":>4} {"Unique":>7}  Sample Data')
        print('-' * 80)
        for cid in sorted(broadcast_ids.keys()):
            s = broadcast_ids[cid]
            elapsed = s['last_seen'] - s['first_seen'] if s['last_seen'] != s['first_seen'] else 1
            rate = s['count'] / elapsed
            sample = sorted(s['data_samples'])[0] if s['data_samples'] else ''
            print(f'  0x{cid:03X}    {s["count"]:>8}  {rate:>6.1f}/s  {s["dlc"]:>3}  {len(s["data_samples"]):>6}   {sample}')
        print()

    if diag_ids:
        print('--- Diagnostic IDs (filtered) ---')
        for cid in sorted(diag_ids.keys()):
            s = diag_ids[cid]
            print(f'  0x{cid:03X}  count={s["count"]}')
        print()

    return stats


# ============================================================================
# Diff Mode — compare before/after an action
# ============================================================================

def capture_snapshot(listener, seconds=3):
    """Capture current state of all CAN IDs for a few seconds."""
    snapshot = {}
    start = time.time()
    while time.time() - start < seconds:
        frames = listener.read_frames()
        for can_id, data in frames:
            if can_id not in DIAG_IDS:
                snapshot[can_id] = data  # keep last value
    return snapshot


def diff_snapshots(before, after):
    """Show which CAN IDs changed data between two snapshots."""
    all_ids = sorted(set(before.keys()) | set(after.keys()))
    changes = []
    for cid in all_ids:
        b = before.get(cid)
        a = after.get(cid)
        if b is None:
            changes.append((cid, 'NEW', None, a))
        elif a is None:
            changes.append((cid, 'GONE', b, None))
        elif b != a:
            changes.append((cid, 'CHANGED', b, a))
    return changes


def diff_mode(listener):
    """Interactive mode: capture baseline, wait for action, show diff."""
    print('=== Broadcast Diff Mode ===')
    print('ใช้เพื่อหาว่า CAN ID ไหนเปลี่ยนเมื่อทำอะไรสักอย่าง\n')

    while True:
        print('-' * 60)
        print('กด Enter เพื่อ capture baseline (3 วินาที)...')
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            break

        print('Capturing baseline...')
        before = capture_snapshot(listener, 3)
        print(f'  Got {len(before)} CAN IDs\n')

        print('ทำอะไรสักอย่าง (เปิดประตู / เหยียบเบรค / เปิดไฟเลี้ยว)')
        print('แล้วกด Enter...')
        try:
            action = input('  Action: ').strip() or '(unknown)'
        except (EOFError, KeyboardInterrupt):
            break

        print('Capturing after action...')
        after = capture_snapshot(listener, 3)
        print(f'  Got {len(after)} CAN IDs\n')

        changes = diff_snapshots(before, after)
        if not changes:
            print('  ไม่มี CAN ID ไหนเปลี่ยนเลย\n')
            continue

        print(f'  {len(changes)} CAN ID(s) changed for "{action}":')
        print(f'  {"CAN ID":>10}  {"Status":>8}  {"Before":>26}  {"After":>26}')
        print('  ' + '-' * 76)
        for cid, status, b, a in changes:
            b_str = b.hex(' ') if b else '-'
            a_str = a.hex(' ') if a else '-'
            # Highlight changed bytes
            if status == 'CHANGED' and b and a and len(b) == len(a):
                diff_bytes = []
                for i in range(len(b)):
                    if b[i] != a[i]:
                        diff_bytes.append(f'byte{i}:0x{b[i]:02X}→0x{a[i]:02X}')
                detail = '  ' + ', '.join(diff_bytes)
            else:
                detail = ''
            print(f'  0x{cid:03X}      {status:>8}  {b_str:>26}  {a_str:>26}{detail}')
        print()


# ============================================================================
# Watch Mode — monitor specific CAN ID in real-time
# ============================================================================

def watch_mode(listener, can_id_str):
    """Watch a specific CAN ID, showing every change."""
    target_id = int(can_id_str, 0)  # supports 0x354, 852, etc.
    print(f'Watching CAN ID 0x{target_id:03X} (Ctrl+C to stop)\n')
    print(f'{"Time":>10}  {"Data (hex)":>26}  Changed Bytes')
    print('-' * 70)

    last_data = None
    start = time.time()

    while True:
        try:
            frames = listener.read_frames()
            for can_id, data in frames:
                if can_id != target_id:
                    continue
                now = time.time() - start
                hex_str = data.hex(' ')

                if last_data is None:
                    print(f'  {now:>8.3f}s  {hex_str}  (first)')
                elif data != last_data:
                    diff_parts = []
                    for i in range(min(len(data), len(last_data))):
                        if data[i] != last_data[i]:
                            diff_parts.append(f'[{i}] 0x{last_data[i]:02X}→0x{data[i]:02X}')
                    print(f'  {now:>8.3f}s  {hex_str}  {", ".join(diff_parts)}')

                last_data = data
        except KeyboardInterrupt:
            break

    print(f'\nDone. Watched 0x{target_id:03X}')


# ============================================================================
# Main
# ============================================================================

def find_port():
    candidates = glob.glob('/dev/cu.usbmodem*') + glob.glob('/dev/ttyACM*')
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser(
        description='Nissan Almera N18 — CAN Broadcast Sniffer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
modes:
  (default)     Passive listen, show all CAN IDs + rates
  --diff        Interactive: capture before/after, show changes
  --watch ID    Monitor specific CAN ID in real-time

examples:
  python3 nissan_broadcast_sniff.py                  # survey all traffic
  python3 nissan_broadcast_sniff.py --duration 60    # listen 60 seconds
  python3 nissan_broadcast_sniff.py --diff           # find door/brake/signal IDs
  python3 nissan_broadcast_sniff.py --watch 0x354    # monitor one ID
""")
    parser.add_argument('--port', '-p', help='Serial port (auto-detect)')
    parser.add_argument('--duration', '-d', type=int, default=10, help='Sniff duration (seconds)')
    parser.add_argument('--diff', action='store_true', help='Interactive diff mode')
    parser.add_argument('--watch', '-w', help='Watch specific CAN ID (e.g. 0x354)')
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        print('ERROR: no serial port found. Use --port')
        print('NOTE: ต้องใช้ SLCAN firmware! (firmware/slcan_main.cpp.bak)')
        sys.exit(1)

    print(f'Connecting to {port} (SLCAN, 500kbps)...')
    listener = SLCANListener(port)
    print('Connected! Passive listen mode (ไม่ส่งอะไร แค่ฟัง)\n')

    try:
        if args.diff:
            diff_mode(listener)
        elif args.watch:
            watch_mode(listener, args.watch)
        else:
            sniff_summary(listener, args.duration)
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        listener.close()


if __name__ == '__main__':
    main()
