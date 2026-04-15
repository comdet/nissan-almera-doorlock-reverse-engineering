#!/usr/bin/env python3
"""
Nissan Almera N18 — Door Lock Status Reader (SLCAN)
====================================================
อ่านสถานะ lock/unlock ของประตูจาก BCM ผ่าน ESP32-C3 + SN65HVD230

Usage:
  python3 nissan_status.py                          # อ่านครั้งเดียว
  python3 nissan_status.py --watch                  # อ่านวนซ้ำทุก 1 วินาที
  python3 nissan_status.py --watch --interval 0.5   # อ่านทุก 0.5 วินาที
  python3 nissan_status.py --port /dev/cu.usbmodem1101
"""

import serial
import time
import sys
import argparse


# ============================================================================
# SLCAN CAN Bus Communication
# ============================================================================

class SLCAN:
    """ESP32-C3 SLCAN adapter communication."""

    def __init__(self, port, bitrate=500000):
        self.ser = serial.Serial(port, 115200, timeout=2)
        time.sleep(1)
        self.ser.reset_input_buffer()
        # Init SLCAN
        self._raw('S6')   # 500kbps
        self._raw('O')    # Open channel
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    def _raw(self, cmd):
        self.ser.write((cmd + '\r').encode())
        time.sleep(0.2)
        self.ser.read(self.ser.in_waiting or 256)

    def send(self, can_id, data, wait=0.4):
        """Send CAN frame, return list of (id, bytes) responses."""
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

    def send_one(self, can_id, data, wait=0.4):
        """Send CAN frame, return first response data bytes or b''."""
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
# BCM Communication
# ============================================================================

BCM_REQ = 0x745
BCM_RSP = 0x765

# Padding
FF8 = [0xFF] * 5  # pad to 8 bytes


def bcm_extended_session(bus):
    """Enter Extended Diagnostic Session."""
    r = bus.send_one(BCM_REQ, [0x02, 0x10, 0x03] + FF8[:5])
    ok = r and len(r) >= 2 and r[1] == 0x50
    return ok


def bcm_default_session(bus):
    """Return to Default Session."""
    bus.send_one(BCM_REQ, [0x02, 0x10, 0x01] + FF8[:5])


def bcm_tester_present(bus):
    """TesterPresent keep-alive."""
    bus.send_one(BCM_REQ, [0x02, 0x3E, 0x00] + FF8[:5])


def bcm_read_did_0109(bus):
    """Read DID 0x0109 (door status) — 18-byte multiframe response.

    Returns full UDS payload bytes or None on failure.
    """
    # Request: ReadDataByIdentifier DID=0x0109
    resp = bus.send(BCM_REQ, [0x03, 0x22, 0x01, 0x09, 0xFF, 0xFF, 0xFF, 0xFF], wait=0.5)

    if not resp:
        return None

    _, first = resp[0]
    if not first:
        return None

    # Single Frame?
    pci_type = (first[0] >> 4) & 0x0F
    if pci_type == 0:
        pci_len = first[0] & 0x0F
        return first[1:1 + pci_len]

    # First Frame (multiframe)
    if pci_type == 1:
        total_len = ((first[0] & 0x0F) << 8) | first[1]
        all_data = bytearray(first[2:])  # first 6 bytes

        # Send FlowControl CTS
        fc_frames = bus.send(BCM_REQ,
                             [0x30, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF],
                             wait=0.8)

        for _, cf in fc_frames:
            if cf and (cf[0] >> 4) == 2:  # Consecutive Frame
                all_data.extend(cf[1:])

        return bytes(all_data[:total_len])

    # Negative response
    if len(first) >= 4 and first[1] == 0x7F:
        return None

    return None


# ============================================================================
# Door Status Parsing
# ============================================================================

def parse_door_status(uds_payload):
    """Parse DID 0x0109 response.

    Returns dict with parsed fields.
    UDS payload format: [62 01 09 ...data...]
    """
    if not uds_payload or len(uds_payload) < 9:
        return None

    # Verify SID + DID
    if uds_payload[0] != 0x62 or uds_payload[1] != 0x01 or uds_payload[2] != 0x09:
        return None

    data = uds_payload[3:]  # strip SID + DID

    result = {
        'raw': uds_payload.hex(' '),
        'data_hex': data.hex(' '),
    }

    # Byte 5 (index 5 in data = byte 8 in full response) = lock status
    if len(data) > 5:
        lock_byte = data[5]  # byte index 5 in data = byte 8 overall
        result['lock_byte'] = lock_byte
        result['locked'] = lock_byte == 0x00
        result['unlocked'] = lock_byte == 0x10
        if lock_byte == 0x00:
            result['status'] = 'LOCKED'
        elif lock_byte == 0x10:
            result['status'] = 'UNLOCKED'
        else:
            result['status'] = f'UNKNOWN (0x{lock_byte:02X})'
    else:
        result['status'] = 'PARSE ERROR'

    return result


def read_status(bus, verbose=False):
    """Read and return door status. Returns parsed dict or None."""
    if not bcm_extended_session(bus):
        if verbose:
            print('  !! Cannot enter extended session')
        return None

    payload = bcm_read_did_0109(bus)
    bcm_default_session(bus)

    if not payload:
        if verbose:
            print('  !! No response from BCM')
        return None

    return parse_door_status(payload)


# ============================================================================
# Main
# ============================================================================

def find_port():
    """Auto-detect ESP32-C3 SLCAN port."""
    import glob
    candidates = glob.glob('/dev/cu.usbmodem*') + glob.glob('/dev/ttyACM*')
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser(
        description='Nissan Almera N18 — Door Lock Status Reader')
    parser.add_argument('--port', '-p',
                        help='Serial port (auto-detect if omitted)')
    parser.add_argument('--watch', '-w', action='store_true',
                        help='Watch mode — read repeatedly')
    parser.add_argument('--interval', '-i', type=float, default=1.0,
                        help='Watch interval in seconds (default: 1.0)')
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        print('ERROR: no serial port found. Use --port')
        sys.exit(1)

    print(f'Connecting to {port}...')
    bus = SLCAN(port)
    print('Connected!\n')

    try:
        if args.watch:
            print('Watching door status (Ctrl+C to stop)...\n')
            last_status = None
            while True:
                result = read_status(bus)
                if result:
                    status = result['status']
                    lock_byte = result.get('lock_byte', None)
                    ts = time.strftime('%H:%M:%S')

                    if status != last_status:
                        byte_str = f'0x{lock_byte:02X}' if lock_byte is not None else '??'
                        print(f'  [{ts}] {status}  (byte8={byte_str})')
                        last_status = status
                else:
                    print(f'  [{time.strftime("%H:%M:%S")}] READ FAILED')

                time.sleep(args.interval)
        else:
            result = read_status(bus, verbose=True)
            if result:
                print(f'  Status : {result["status"]}')
                print(f'  Byte 8 : 0x{result.get("lock_byte", 0):02X}')
                print(f'  Raw    : {result["raw"]}')
            else:
                print('  !! Failed to read status')
                sys.exit(1)

    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        bus.close()


if __name__ == '__main__':
    main()
