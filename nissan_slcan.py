#!/usr/bin/env python3
"""
Nissan Almera N18 — Door Lock/Unlock via ESP32-C3 SLCAN
========================================================
สั่ง lock/unlock ประตูและ DRL ผ่าน ESP32-C3 + SN65HVD230 CAN transceiver

Hardware:
  ESP32-C3 Super Mini + SN65HVD230 (SLCAN firmware)
  GPIO4 = CAN TX → SN65HVD230 CTX/D
  GPIO3 = CAN RX → SN65HVD230 CRX/R

Usage:
  python3 nissan_slcan.py unlock
  python3 nissan_slcan.py lock
  python3 nissan_slcan.py status
  python3 nissan_slcan.py drl-on
  python3 nissan_slcan.py drl-off
  python3 nissan_slcan.py                  (interactive)
  python3 nissan_slcan.py --port /dev/cu.usbmodem1101 unlock
"""

import serial
import time
import sys
import glob
import argparse


# ============================================================================
# SLCAN CAN Bus Communication
# ============================================================================

class SLCAN:
    """ESP32-C3 SLCAN adapter."""

    def __init__(self, port, verbose=True):
        self.ser = serial.Serial(port, 115200, timeout=2)
        self.verbose = verbose
        time.sleep(1)
        self.ser.reset_input_buffer()
        self._raw('S6')   # 500kbps
        self._raw('O')    # Open channel
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    def _raw(self, cmd):
        self.ser.write((cmd + '\r').encode())
        time.sleep(0.2)
        self.ser.read(self.ser.in_waiting or 256)

    def send(self, can_id, data, wait=0.3):
        """Send CAN frame. Returns list of (id, bytes) responses."""
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

    def send_one(self, can_id, data, wait=0.3):
        """Send CAN frame, return first response bytes."""
        frames = self.send(can_id, data, wait)
        return frames[0][1] if frames else b''

    def close(self):
        try:
            self.ser.write(b'C\r')
            time.sleep(0.1)
            self.ser.close()
        except Exception:
            pass


# ============================================================================
# BCM UDS Commands
# ============================================================================

BCM = 0x745
PAD = [0xFF, 0xFF, 0xFF, 0xFF, 0xFF]


def is_positive(resp):
    """Check if response is UDS positive (not NRC 0x7F)."""
    if not resp or len(resp) < 2:
        return False
    # Check for negative response
    if resp[1] == 0x7F:
        return False
    return True


def extended_session(bus):
    r = bus.send_one(BCM, [0x02, 0x10, 0x03] + PAD)
    return is_positive(r)


def default_session(bus):
    bus.send_one(BCM, [0x02, 0x10, 0x01] + PAD)


def tester_present(bus):
    bus.send_one(BCM, [0x02, 0x3E, 0x00] + PAD)


def io_control(bus, did, state, wait=0.3):
    """IOControlByIdentifier shortTermAdjustment."""
    dh = (did >> 8) & 0xFF
    dl = did & 0xFF
    r = bus.send_one(BCM, [0x06, 0x2F, dh, dl, 0x03, state[0], state[1], 0xFF], wait)
    return is_positive(r)


def read_door_status(bus):
    """Read DID 0x0109, return (status_str, byte8_value) or (None, None)."""
    if not extended_session(bus):
        return None, None

    resp = bus.send(BCM, [0x03, 0x22, 0x01, 0x09, 0xFF, 0xFF, 0xFF, 0xFF], wait=0.5)
    if not resp:
        default_session(bus)
        return None, None

    _, first = resp[0]
    all_data = bytearray()

    if first and (first[0] >> 4) == 1:
        # Multiframe
        total_len = ((first[0] & 0x0F) << 8) | first[1]
        all_data = bytearray(first[2:])
        fc_resp = bus.send(BCM, [0x30, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], wait=0.8)
        for _, cf in fc_resp:
            if cf and (cf[0] >> 4) == 2:
                all_data.extend(cf[1:])
        all_data = all_data[:total_len]

    default_session(bus)

    # UDS payload: [62 01 09 ...data...]
    # Byte 8 overall = data[5] = lock status
    if len(all_data) >= 9 and all_data[0] == 0x62:
        byte8 = all_data[8]  # index 8 in full payload
        if byte8 == 0x00:
            return 'LOCKED', byte8
        elif byte8 == 0x10:
            return 'UNLOCKED', byte8
        else:
            return f'UNKNOWN(0x{byte8:02X})', byte8

    return None, None


# ============================================================================
# Door Lock / Unlock / DRL Commands
# ============================================================================

DID_LOCK = 0x0202     # door lock/unlock control
DID_DOOR_AUX = 0x023F  # door auxiliary actuator (causes DRL side effect)

# DID=0x0202 controlState values
STATE_UNLOCK = [0x00, 0x02]   # unlock door
STATE_LOCK = [0x00, 0x01]     # lock door

# DID=0x023F controlState values (auxiliary — not needed for lock/unlock)
AUX_ACTIVATE = [0x00, 0x01]   # activate (causes DRL on as side effect)
AUX_NEUTRAL = [0x00, 0x00]    # return control


def do_unlock(bus, verbose=True):
    """Unlock door.

    Minimal sequence (confirmed 2026-04-15):
      ExtSession → TesterPresent → DID=0x0202 [00 02] → DefaultSession
    No DRL side effect. DID=0x023F not needed.
    """
    if verbose:
        print('  UNLOCK...')

    if not extended_session(bus):
        if verbose:
            print('  !! ExtSession failed')
        return False

    tester_present(bus)
    io_control(bus, DID_LOCK, STATE_UNLOCK, wait=0.5)
    default_session(bus)

    # Verify
    status, _ = read_door_status(bus)
    ok = status == 'UNLOCKED'
    if verbose:
        print(f'  => {status}  {"OK" if ok else "FAILED"}')
    return ok


def do_lock(bus, verbose=True):
    """Lock door.

    Minimal sequence (confirmed 2026-04-15):
      ExtSession → TesterPresent → DID=0x0202 [00 01] → DefaultSession
    """
    if verbose:
        print('  LOCK...')

    if not extended_session(bus):
        if verbose:
            print('  !! ExtSession failed')
        return False

    tester_present(bus)
    io_control(bus, DID_LOCK, STATE_LOCK, wait=0.5)
    default_session(bus)

    # Verify
    status, _ = read_door_status(bus)
    locked = status == 'LOCKED'
    if verbose:
        print(f'  => {status}  {"OK" if locked else "FAILED"}')
    return locked


def do_drl_on(bus, verbose=True):
    """Turn DRL on via DID=0x023F [00 01].

    DRL requires TesterPresent keep-alive to stay on.
    Runs until Ctrl+C, then sends DRL OFF automatically.
    """
    if verbose:
        print('  DRL ON (Ctrl+C to stop)...')

    if not extended_session(bus):
        if verbose:
            print('  !! ExtSession failed')
        return False

    tester_present(bus)
    ok = io_control(bus, DID_DOOR_AUX, AUX_ACTIVATE, wait=0.5)

    if not ok:
        if verbose:
            print('  !! DRL ON failed')
        default_session(bus)
        return False

    if verbose:
        print('  DRL ON — keeping alive...')

    try:
        while True:
            time.sleep(1)
            tester_present(bus)
    except KeyboardInterrupt:
        pass

    if verbose:
        print('\n  DRL OFF...')
    io_control(bus, DID_DOOR_AUX, AUX_NEUTRAL, wait=0.5)
    default_session(bus)
    if verbose:
        print('  Done')
    return True


def do_drl_off(bus, verbose=True):
    """Turn DRL off — return control on DID=0x023F + default session."""
    if verbose:
        print('  DRL OFF...')
    extended_session(bus)
    tester_present(bus)
    io_control(bus, DID_DOOR_AUX, AUX_NEUTRAL, wait=0.5)
    default_session(bus)
    if verbose:
        print('  Done')
    return True


def do_status(bus, verbose=True):
    """Read and display door status."""
    status, byte8 = read_door_status(bus)
    if status:
        if verbose:
            print(f'  Door: {status}  (byte8=0x{byte8:02X})')
        return status
    else:
        if verbose:
            print('  !! Read failed')
        return None


# ============================================================================
# Interactive Mode
# ============================================================================

def interactive(bus):
    print()
    print('=' * 45)
    print('  Nissan Almera N18 — SLCAN Door Lock')
    print('  Ctrl+C to quit')
    print('=' * 45)

    while True:
        print()
        print('  [1] Unlock        [4] DRL on')
        print('  [2] Lock          [5] DRL off')
        print('  [3] Status        [q] Quit')
        print()

        try:
            c = input('  > ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if c == '1':
            do_unlock(bus)
        elif c == '2':
            do_lock(bus)
        elif c == '3':
            do_status(bus)
        elif c == '4':
            do_drl_on(bus)
        elif c == '5':
            do_drl_off(bus)
        elif c in ('q', 'quit', 'exit'):
            break

    print('\nBye!')


# ============================================================================
# Main
# ============================================================================

def find_port():
    candidates = glob.glob('/dev/cu.usbmodem*') + glob.glob('/dev/ttyACM*')
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser(
        description='Nissan Almera N18 — Door Lock/Unlock via SLCAN',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  unlock    Unlock doors
  lock      Lock doors
  status    Read lock status
  drl-on    DRL on
  drl-off   DRL off
  (omit)    Interactive mode

examples:
  python3 nissan_slcan.py unlock
  python3 nissan_slcan.py lock
  python3 nissan_slcan.py status
  python3 nissan_slcan.py --port /dev/cu.usbmodem1101 unlock
""")
    parser.add_argument('cmd', nargs='?',
                        choices=['unlock', 'lock', 'status', 'drl-on', 'drl-off'],
                        help='Command (omit for interactive)')
    parser.add_argument('--port', '-p', help='Serial port (auto-detect)')
    parser.add_argument('-q', '--quiet', action='store_true')
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        print('ERROR: no serial port. Use --port')
        sys.exit(1)

    verbose = not args.quiet
    if verbose:
        print(f'Connecting to {port}...')

    bus = SLCAN(port, verbose)

    if verbose:
        print('Connected!\n')

    try:
        if args.cmd:
            cmds = {
                'unlock': do_unlock,
                'lock': do_lock,
                'status': do_status,
                'drl-on': do_drl_on,
                'drl-off': do_drl_off,
            }
            result = cmds[args.cmd](bus, verbose)
            sys.exit(0 if result else 1)
        else:
            interactive(bus)
    except KeyboardInterrupt:
        print('\nAborted')
    finally:
        bus.close()


if __name__ == '__main__':
    main()
