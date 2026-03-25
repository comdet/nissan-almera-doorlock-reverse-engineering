#!/usr/bin/env python3
"""
Nissan Almera Turbo (N18) / Versa — Interactive CAN/UDS Diagnostic Tool

Reverse-engineered from OBD door lock device capture.
Interactive menu for debugging and testing door lock/unlock, DRL, and raw CAN.

Usage:
  python nissan_diag.py
"""

import time
import sys
import os
import json

try:
    import can
except ImportError:
    print("ERROR: python-can not installed. Run: pip install python-can")
    sys.exit(1)

try:
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


# ============================================================================
# CAN / UDS Constants
# ============================================================================

BCM_REQUEST_ID  = 0x745
BCM_RESPONSE_ID = 0x765

SID_DIAG_SESSION_CTRL = 0x10
SID_TESTER_PRESENT    = 0x3E
SID_IO_CONTROL        = 0x2F
SID_READ_DATA_BY_ID   = 0x22
SID_NEGATIVE_RESPONSE = 0x7F

SESSION_DEFAULT  = 0x01
SESSION_EXTENDED = 0x03

IO_CTRL_SHORT_TERM_ADJ  = 0x03
IO_CTRL_RETURN_CONTROL  = 0x00

DID_DOOR_LOCK = 0x023F
DID_DRL       = 0x0202

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLength",
    0x14: "responseTooLong",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x25: "noResponseFromSubnetComponent",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceededNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}

KNOWN_INTERFACES = [
    ("slcan",     "slcan / CANable / USB-CAN (CH340, etc.)"),
    ("socketcan", "SocketCAN (Linux)"),
    ("pcan",      "PEAK PCAN-USB"),
    ("kvaser",    "Kvaser"),
    ("ixxat",     "IXXAT"),
    ("vector",    "Vector"),
    ("serial",    "Serial / raw UART (custom protocol)"),
]

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           ".nissan_diag_config.json")


# ============================================================================
# Helper
# ============================================================================

def hex_bytes(data):
    return " ".join(f"{b:02X}" for b in data)


def print_frame(direction, can_id, data, label=""):
    arrow = ">>" if direction == "TX" else "<<"
    extra = f"  ({label})" if label else ""
    print(f"  {arrow} 0x{can_id:03X} [{hex_bytes(data)}]{extra}")


def prompt(text, default=None):
    """Input with default value shown in brackets."""
    if default is not None:
        raw = input(f"{text} [{default}]: ").strip()
        return raw if raw else str(default)
    return input(f"{text}: ").strip()


def prompt_int(text, default=None):
    val = prompt(text, default)
    return int(val) if val else default


def prompt_choice(text, options, default=None):
    """Show numbered options, return selected value."""
    for i, (val, desc) in enumerate(options):
        marker = " *" if val == default else ""
        print(f"  {i + 1}. {desc}{marker}")
    raw = prompt(text, None)
    if not raw and default is not None:
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1][0]
    return default


# ============================================================================
# Config
# ============================================================================

class Config:
    """Persistent configuration."""

    DEFAULTS = {
        "interface": "slcan",
        "channel": "",
        "can_bitrate": 500000,
        "tty_baudrate": 115200,
        "timeout": 2.0,
        "sniff_duration": 10.0,
    }

    def __init__(self):
        self.data = dict(self.DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                self.data.update(saved)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def get(self, key):
        return self.data.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self.data[key] = value

    def summary(self):
        lines = []
        lines.append(f"  Interface     : {self.get('interface')}")
        lines.append(f"  Channel       : {self.get('channel') or '(not set)'}")
        lines.append(f"  CAN bitrate   : {self.get('can_bitrate')} bps")
        lines.append(f"  TTY baudrate  : {self.get('tty_baudrate')} bps")
        lines.append(f"  UDS timeout   : {self.get('timeout')}s")
        lines.append(f"  Sniff duration: {self.get('sniff_duration')}s")
        return "\n".join(lines)


# ============================================================================
# CAN Bus Connection
# ============================================================================

class CANConnection:
    """Manages CAN bus connection."""

    def __init__(self, config):
        self.bus = None
        self.config = config

    @property
    def connected(self):
        return self.bus is not None

    def connect(self):
        """Connect using current config."""
        if self.bus:
            self.disconnect()

        interface = self.config.get("interface")
        channel = self.config.get("channel")
        bitrate = self.config.get("can_bitrate")
        tty_baudrate = self.config.get("tty_baudrate")

        if not channel:
            raise ValueError("Channel not set — use [s] Settings to configure")

        kwargs = dict(interface=interface, channel=channel, bitrate=bitrate)
        if interface == "slcan" and tty_baudrate:
            kwargs["ttyBaudrate"] = tty_baudrate

        self.bus = can.Bus(**kwargs)
        return True

    def disconnect(self):
        if self.bus:
            try:
                self.bus.shutdown()
            except Exception:
                pass
            self.bus = None

    def status_str(self):
        if not self.connected:
            return "NOT CONNECTED"
        cfg = self.config
        extra = ""
        if cfg.get("interface") == "slcan":
            extra = f", tty={cfg.get('tty_baudrate')}"
        return (f"{cfg.get('interface')} @ {cfg.get('channel')} "
                f"(CAN {cfg.get('can_bitrate')}{extra})")


# ============================================================================
# UDS Client
# ============================================================================

class UDSClient:
    """UDS over CAN (ISO-TP Single Frame) for BCM communication."""

    def __init__(self, conn, timeout=2.0, verbose=True):
        self.conn = conn
        self.timeout = timeout
        self.verbose = verbose

    def send_raw(self, can_id, data):
        msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=False)
        self.conn.bus.send(msg)
        if self.verbose:
            print_frame("TX", can_id, data)

    def send_sf(self, can_id, payload):
        length = len(payload)
        data = [length] + list(payload) + [0xFF] * (7 - length)
        self.send_raw(can_id, data)

    def recv_any(self, timeout=None):
        if timeout is None:
            timeout = self.timeout
        return self.conn.bus.recv(timeout=timeout)

    def send_uds(self, payload, label=""):
        """Send UDS request to BCM and wait for response."""
        self.send_sf(BCM_REQUEST_ID, payload)

        deadline = time.time() + self.timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break

            msg = self.conn.bus.recv(timeout=min(remaining, 0.5))
            if msg is None:
                continue
            if msg.arbitration_id != BCM_RESPONSE_ID:
                continue

            data = list(msg.data)
            pci_type = (data[0] >> 4) & 0x0F
            if pci_type != 0:
                continue

            length = data[0] & 0x0F
            resp = data[1:1 + length]
            if not resp:
                continue

            if resp[0] == SID_NEGATIVE_RESPONSE and len(resp) >= 3:
                nrc = resp[2]
                if nrc == 0x78:
                    if self.verbose:
                        print(f"  << NRC 0x78 (responsePending), waiting...")
                    deadline = time.time() + 5.0
                    continue
                nrc_name = NRC_NAMES.get(nrc, "unknown")
                if self.verbose:
                    print_frame("RX", BCM_RESPONSE_ID, msg.data,
                                f"NEGATIVE: 0x{nrc:02X} {nrc_name}")
                return {"ok": False, "nrc": nrc, "nrc_name": nrc_name,
                        "service": resp[1], "raw": resp}

            if self.verbose:
                print_frame("RX", BCM_RESPONSE_ID, msg.data, label)
            return {"ok": True, "raw": resp}

        if self.verbose:
            print(f"  << TIMEOUT ({self.timeout}s) — no response from 0x{BCM_RESPONSE_ID:03X}")
        return None

    def enter_extended_session(self):
        return self.send_uds([SID_DIAG_SESSION_CTRL, SESSION_EXTENDED],
                             "ExtendedSession OK")

    def enter_default_session(self):
        return self.send_uds([SID_DIAG_SESSION_CTRL, SESSION_DEFAULT],
                             "DefaultSession OK")

    def tester_present(self):
        return self.send_uds([SID_TESTER_PRESENT, 0x00], "TesterPresent OK")

    def io_control(self, did, control_param, state):
        did_hi = (did >> 8) & 0xFF
        did_lo = did & 0xFF
        payload = [SID_IO_CONTROL, did_hi, did_lo, control_param] + list(state)
        return self.send_uds(payload, f"IOControl 0x{did:04X} OK")

    def read_data_by_id(self, did):
        did_hi = (did >> 8) & 0xFF
        did_lo = did & 0xFF
        return self.send_uds([SID_READ_DATA_BY_ID, did_hi, did_lo],
                             f"ReadDataById 0x{did:04X} OK")


# ============================================================================
# Menu Functions
# ============================================================================

def require_connection(conn):
    if not conn.connected:
        print("\n  Not connected! Use [c] to connect first.")
        return False
    return True


def menu_settings(config):
    """Settings / config menu."""
    while True:
        print("\n--- Settings ---\n")
        print(config.summary())
        print()
        print("  [1] Interface")
        print("  [2] Channel (serial port)")
        print("  [3] CAN bitrate")
        print("  [4] TTY baudrate (serial port speed)")
        print("  [5] UDS timeout")
        print("  [6] Sniff duration")
        print("  [7] List serial ports")
        print("  [8] Save & back")
        print("  [0] Back (no save)")

        choice = input("\n> ").strip()

        if choice == "1":
            print("\nSelect interface:")
            val = prompt_choice("Interface",
                                [(iface, f"{iface:12s} — {desc}")
                                 for iface, desc in KNOWN_INTERFACES],
                                config.get("interface"))
            if val:
                config.set("interface", val)
                print(f"  -> {val}")

        elif choice == "2":
            # List ports first
            if HAS_SERIAL:
                ports = list(serial.tools.list_ports.comports())
                if ports:
                    print("\n  Available serial ports:")
                    for i, p in enumerate(ports):
                        chip = f" [{p.manufacturer or ''}]" if p.manufacturer else ""
                        print(f"    {i + 1}. {p.device}{chip} — {p.description}")
                    sel = input("\n  Select # or type path: ").strip()
                    if sel.isdigit() and 1 <= int(sel) <= len(ports):
                        config.set("channel", ports[int(sel) - 1].device)
                        print(f"  -> {config.get('channel')}")
                        continue
                    elif sel:
                        config.set("channel", sel)
                        print(f"  -> {sel}")
                        continue
                else:
                    print("\n  No serial ports found!")
            val = prompt("Channel", config.get("channel"))
            if val:
                config.set("channel", val)

        elif choice == "3":
            print("\n  Common CAN bitrates: 125000, 250000, 500000, 1000000")
            val = prompt_int("CAN bitrate", config.get("can_bitrate"))
            if val:
                config.set("can_bitrate", val)

        elif choice == "4":
            print("\n  Common TTY baudrates: 9600, 115200, 230400, 460800,")
            print("  500000, 921600, 1000000, 1500000, 2000000")
            print("  CH340 typically: 115200 or 921600 or 1500000")
            val = prompt_int("TTY baudrate", config.get("tty_baudrate"))
            if val:
                config.set("tty_baudrate", val)

        elif choice == "5":
            val = prompt("UDS timeout (seconds)", config.get("timeout"))
            if val:
                config.set("timeout", float(val))

        elif choice == "6":
            val = prompt("Sniff duration (seconds)", config.get("sniff_duration"))
            if val:
                config.set("sniff_duration", float(val))

        elif choice == "7":
            list_serial_ports()

        elif choice == "8":
            config.save()
            print("  Config saved!")
            break
        elif choice == "0":
            break


def list_serial_ports():
    """List all serial ports with detail."""
    if not HAS_SERIAL:
        print("\n  pyserial not installed. Run: pip install pyserial")
        return
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("\n  No serial ports found.")
        return
    print(f"\n  Found {len(ports)} serial port(s):\n")
    for p in ports:
        print(f"    Device : {p.device}")
        print(f"    Desc   : {p.description}")
        if p.manufacturer:
            print(f"    Mfr    : {p.manufacturer}")
        if p.serial_number:
            print(f"    Serial : {p.serial_number}")
        if p.vid is not None:
            print(f"    VID:PID: {p.vid:04X}:{p.pid:04X}")
        print()


def menu_connect(conn):
    """Connect using saved config."""
    cfg = conn.config
    if not cfg.get("channel"):
        print("\n  Channel not set! Opening settings...")
        menu_settings(cfg)
        if not cfg.get("channel"):
            return

    print(f"\n  Connecting: {cfg.get('interface')} / {cfg.get('channel')} "
          f"@ CAN {cfg.get('can_bitrate')}")
    if cfg.get("interface") == "slcan":
        print(f"  TTY baudrate: {cfg.get('tty_baudrate')}")

    try:
        conn.connect()
        print("  Connected!")
    except Exception as e:
        print(f"  ERROR: {e}")
        print("\n  Troubleshooting:")
        print("  - Check cable / USB connection")
        print("  - Try different TTY baudrate in [s] Settings")
        print("  - Make sure no other program is using the port")


def menu_sniff(conn):
    """Sniff CAN bus traffic."""
    if not require_connection(conn):
        return

    duration = conn.config.get("sniff_duration")
    dur_str = prompt("Duration (seconds)", duration)
    duration = float(dur_str) if dur_str else duration

    filter_str = prompt("Filter CAN ID (hex, blank=all)", None)
    filter_id = int(filter_str, 16) if filter_str else None

    print(f"\nSniffing for {duration}s" +
          (f" (filter: 0x{filter_id:03X})" if filter_id else " (all IDs)") +
          " — Ctrl+C to stop\n")
    print(f"  {'Time':>8s}   {'CAN ID':>8s}  DLC  Data                     Decode")
    print("  " + "-" * 68)

    start = time.time()
    count = 0
    id_counts = {}

    try:
        while time.time() - start < duration:
            msg = conn.bus.recv(timeout=0.5)
            if msg is None:
                continue
            if filter_id is not None and msg.arbitration_id != filter_id:
                continue
            count += 1
            elapsed = time.time() - start
            cid = msg.arbitration_id
            id_counts[cid] = id_counts.get(cid, 0) + 1
            data_hex = hex_bytes(msg.data)
            decode = decode_frame_hint(cid, list(msg.data))
            print(f"  {elapsed:7.3f}s   0x{cid:03X}      {msg.dlc}  [{data_hex}]  {decode}")
    except KeyboardInterrupt:
        pass

    print("  " + "-" * 68)
    print(f"\n  Total: {count} frames in {time.time() - start:.1f}s")
    if id_counts:
        print("\n  Frames per CAN ID:")
        for cid in sorted(id_counts.keys()):
            name = ""
            if cid == BCM_REQUEST_ID:
                name = " (BCM request)"
            elif cid == BCM_RESPONSE_ID:
                name = " (BCM response)"
            elif cid == 0x7DF:
                name = " (OBD broadcast)"
            elif 0x7E0 <= cid <= 0x7EF:
                name = " (ECU diag)"
            print(f"    0x{cid:03X}: {id_counts[cid]}{name}")
    else:
        print("\n  *** NO FRAMES RECEIVED ***")
        print("  Possible issues:")
        print("    1. Vehicle ignition OFF (ECUs asleep)")
        print("    2. Wrong CAN bitrate (try 250000 or 500000)")
        print("    3. Wrong TTY baudrate (try 115200, 921600, 1500000)")
        print("    4. Adapter not connected / CAN-H CAN-L wiring issue")
        print("    5. Adapter doesn't speak slcan protocol")


def decode_frame_hint(can_id, data):
    """Quick decode hint for known frame patterns."""
    if not data or len(data) < 2:
        return ""
    pci_len = data[0] & 0x0F
    if (data[0] >> 4) != 0:
        return ""

    if can_id in (BCM_REQUEST_ID, BCM_RESPONSE_ID):
        if pci_len >= 1:
            sid = data[1]
            if sid == 0x10:
                session = data[2] if pci_len >= 2 else 0
                return f"DiagSession {'ext' if session == 3 else 'def' if session == 1 else hex(session)}"
            elif sid == 0x50:
                return "DiagSession+ OK"
            elif sid == 0x3E:
                return "TesterPresent"
            elif sid == 0x7E:
                return "TesterPresent+ OK"
            elif sid == 0x2F:
                if pci_len >= 4:
                    did = (data[2] << 8) | data[3]
                    return f"IOControl DID=0x{did:04X}"
                return "IOControl"
            elif sid == 0x6F:
                if pci_len >= 4:
                    did = (data[2] << 8) | data[3]
                    return f"IOControl+ 0x{did:04X} OK"
                return "IOControl+ OK"
            elif sid == 0x7F:
                if pci_len >= 3:
                    nrc = data[3]
                    return f"NRC 0x{nrc:02X} {NRC_NAMES.get(nrc, '')}"
                return "NegativeResponse"
            elif sid == 0x22:
                return "ReadDataById"
            elif sid == 0x62:
                return "ReadDataById+ OK"
    elif can_id == 0x7DF:
        if pci_len >= 2 and data[1] == 0x01:
            pid = data[2] if pci_len >= 3 else 0
            if pid == 0x0D:
                return "OBD: req speed"
            elif pid == 0x0C:
                return "OBD: req RPM"
    return ""


def menu_unlock(conn):
    if not require_connection(conn):
        return
    uds = UDSClient(conn, timeout=conn.config.get("timeout"))
    print("\n--- Door Unlock (DID=0x023F [00 01]) ---\n")

    print("[1/4] Enter extended session")
    r = uds.enter_extended_session()
    if r is None or not r["ok"]:
        print("  Retry...")
        time.sleep(0.3)
        r = uds.enter_extended_session()
        if r is None or not r["ok"]:
            print("  FAILED — cannot enter extended session")
            return

    print("[2/4] TesterPresent")
    uds.tester_present()

    print("[3/4] IOControl UNLOCK")
    r = uds.io_control(DID_DOOR_LOCK, IO_CTRL_SHORT_TERM_ADJ, [0x00, 0x01])
    if r is None:
        print("  TIMEOUT")
    elif not r["ok"]:
        print("  NRC received, re-entering session and retrying...")
        uds.enter_extended_session()
        r = uds.io_control(DID_DOOR_LOCK, IO_CTRL_SHORT_TERM_ADJ, [0x00, 0x01])
        if r and r["ok"]:
            print("  UNLOCK OK (retry)")
        else:
            print("  UNLOCK FAILED")
    else:
        print("  UNLOCK OK!")

    print("[4/4] Return control to ECU")
    uds.io_control(DID_DOOR_LOCK, IO_CTRL_RETURN_CONTROL, [0x00, 0x00])


def menu_lock(conn):
    if not require_connection(conn):
        return
    uds = UDSClient(conn, timeout=conn.config.get("timeout"))
    print("\n--- Door Lock (DID=0x023F [00 02]) ---\n")

    print("[1/3] Enter extended session")
    r = uds.enter_extended_session()
    if r is None or not r["ok"]:
        time.sleep(0.3)
        r = uds.enter_extended_session()
        if r is None or not r["ok"]:
            print("  FAILED")
            return

    print("[2/3] IOControl LOCK")
    r = uds.io_control(DID_DOOR_LOCK, IO_CTRL_SHORT_TERM_ADJ, [0x00, 0x02])
    if r is None:
        print("  TIMEOUT")
    elif not r["ok"]:
        uds.enter_extended_session()
        uds.io_control(DID_DOOR_LOCK, IO_CTRL_SHORT_TERM_ADJ, [0x00, 0x02])

    print("[3/3] Return control to ECU")
    uds.io_control(DID_DOOR_LOCK, IO_CTRL_RETURN_CONTROL, [0x00, 0x00])


def menu_drl(conn):
    if not require_connection(conn):
        return
    uds = UDSClient(conn, timeout=conn.config.get("timeout"))
    print("\n--- DRL Control (DID=0x0202) ---")
    print("  1. DRL ON  [00 02]")
    print("  2. DRL OFF [00 00]")

    choice = input("\n> ").strip()
    if choice == "1":
        state, label = [0x00, 0x02], "ON"
    elif choice == "2":
        state, label = [0x00, 0x00], "OFF"
    else:
        return

    print(f"\n[1/2] Enter extended session")
    r = uds.enter_extended_session()
    if r is None or not r["ok"]:
        time.sleep(0.3)
        uds.enter_extended_session()
    print(f"[2/2] IOControl DRL {label}")
    uds.io_control(DID_DRL, IO_CTRL_SHORT_TERM_ADJ, state)


def menu_raw_uds(conn):
    if not require_connection(conn):
        return
    uds = UDSClient(conn, timeout=conn.config.get("timeout"))
    print("\n--- Raw UDS to BCM (0x745 -> 0x765) ---")
    print("  Enter hex bytes, e.g. '10 03'")
    print("  Shortcuts:  ext = enter extended session")
    print("              tp  = TesterPresent")
    print("  Type 'q' to go back\n")

    shortcuts = {
        "ext": [0x10, 0x03],
        "def": [0x10, 0x01],
        "tp":  [0x3E, 0x00],
    }

    while True:
        raw = input("UDS> ").strip()
        if raw.lower() in ("q", "quit", "back", ""):
            break
        if raw.lower() in shortcuts:
            uds.send_uds(shortcuts[raw.lower()])
            continue
        try:
            payload = [int(b, 16) for b in raw.split()]
            if payload:
                uds.send_uds(payload)
        except ValueError:
            print("  Invalid hex. Example: 10 03")


def menu_raw_can(conn):
    if not require_connection(conn):
        return
    print("\n--- Raw CAN Frame ---")
    print("  Type 'q' to go back\n")

    while True:
        raw = input("CAN ID (hex)> ").strip()
        if raw.lower() in ("q", "quit", "back", ""):
            break
        try:
            can_id = int(raw, 16)
        except ValueError:
            print("  Invalid hex ID")
            continue

        data_str = input("Data (hex bytes)> ").strip()
        try:
            data = [int(b, 16) for b in data_str.split()] if data_str else []
        except ValueError:
            print("  Invalid hex data")
            continue

        while len(data) < 8:
            data.append(0xFF)

        msg = can.Message(arbitration_id=can_id, data=data[:8], is_extended_id=False)
        conn.bus.send(msg)
        print_frame("TX", can_id, data[:8])

        print("  Listening 2s for response...")
        deadline = time.time() + 2.0
        got = False
        while time.time() < deadline:
            resp = conn.bus.recv(timeout=0.5)
            if resp:
                print_frame("RX", resp.arbitration_id, resp.data)
                got = True
        if not got:
            print("  (no response)")


def menu_scan_dids(conn):
    if not require_connection(conn):
        return
    uds = UDSClient(conn, timeout=0.5, verbose=False)
    print("\n--- DID Scanner (ReadDataByIdentifier on BCM) ---")

    start_str = prompt("Start DID (hex)", "0100")
    end_str = prompt("End DID (hex)", "02FF")
    start_did = int(start_str, 16)
    end_did = int(end_str, 16)

    print(f"\nScanning 0x{start_did:04X} - 0x{end_did:04X}...")
    print("Entering extended session...")
    uds.verbose = True
    uds.enter_extended_session()
    uds.verbose = False

    found = []
    total = end_did - start_did + 1
    for i, did in enumerate(range(start_did, end_did + 1)):
        if (i + 1) % 16 == 0:
            uds.send_sf(BCM_REQUEST_ID, [SID_TESTER_PRESENT, 0x00])
            uds.recv_any(timeout=0.3)

        pct = (i + 1) * 100 // total
        sys.stdout.write(f"\r  Scanning 0x{did:04X}... ({pct}%)")
        sys.stdout.flush()

        r = uds.read_data_by_id(did)
        if r is not None and r["ok"]:
            data_hex = hex_bytes(r["raw"])
            found.append((did, r["raw"]))
            sys.stdout.write(f"\r  FOUND 0x{did:04X}: [{data_hex}]" + " " * 20 + "\n")

    print(f"\r  Done. {len(found)} readable DIDs." + " " * 20)
    if found:
        print("\n  Results:")
        for did, raw in found:
            print(f"    0x{did:04X}: [{hex_bytes(raw)}]")


def menu_full_sequence(conn):
    if not require_connection(conn):
        return
    uds = UDSClient(conn, timeout=conn.config.get("timeout"))
    print("\n--- Full Unlock Sequence (exact capture replay) ---\n")

    steps = [
        ("Enter extended session",
         [SID_DIAG_SESSION_CTRL, SESSION_EXTENDED]),
        ("TesterPresent",
         [SID_TESTER_PRESENT, 0x00]),
        ("IOControl DID=0x0202 [00 02] (DRL ON)",
         [SID_IO_CONTROL, 0x02, 0x02, IO_CTRL_SHORT_TERM_ADJ, 0x00, 0x02]),
        ("IOControl DID=0x023F [00 01] (UNLOCK)",
         [SID_IO_CONTROL, 0x02, 0x3F, IO_CTRL_SHORT_TERM_ADJ, 0x00, 0x01]),
        ("Return control DID=0x023F",
         [SID_IO_CONTROL, 0x02, 0x3F, IO_CTRL_RETURN_CONTROL, 0x00, 0x00]),
    ]

    for i, (desc, payload) in enumerate(steps):
        print(f"[{i + 1}/{len(steps)}] {desc}")
        r = uds.send_uds(payload)

        if r is None:
            print("  TIMEOUT — retrying with session re-entry")
            uds.enter_extended_session()
            time.sleep(0.1)
            r = uds.send_uds(payload)

        if r is not None and not r["ok"] and r["nrc"] == 0x7F:
            print("  Wrong session — re-entering extended")
            uds.enter_extended_session()
            time.sleep(0.1)
            r = uds.send_uds(payload)

        time.sleep(0.05)

    print("\nSequence complete.")


def menu_loopback_test(conn):
    """Test if adapter can send and receive (loopback or bus echo)."""
    if not require_connection(conn):
        return

    print("\n--- Loopback / Echo Test ---")
    print("  Sending a test frame and checking if anything comes back.\n")

    # Send a harmless OBD-II request (supported PIDs)
    test_data = [0x02, 0x01, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
    msg = can.Message(arbitration_id=0x7DF, data=test_data, is_extended_id=False)

    print(f"  TX 0x7DF [{hex_bytes(test_data)}]  (OBD: supported PIDs)")
    try:
        conn.bus.send(msg)
        print("  Send OK (no error from adapter)")
    except Exception as e:
        print(f"  Send FAILED: {e}")
        return

    print("  Listening 3s for any response...\n")
    deadline = time.time() + 3.0
    count = 0
    while time.time() < deadline:
        resp = conn.bus.recv(timeout=0.5)
        if resp:
            count += 1
            data_hex = hex_bytes(resp.data)
            decode = decode_frame_hint(resp.arbitration_id, list(resp.data))
            print(f"  RX 0x{resp.arbitration_id:03X} [{data_hex}]  {decode}")

    if count > 0:
        print(f"\n  Got {count} frame(s) — bus is alive!")
    else:
        print("\n  No frames received.")
        print("  Possible causes:")
        print("    - Adapter TX works but RX doesn't")
        print("    - No ECU responded (ignition off?)")
        print("    - CAN bitrate mismatch")
        print("    - TTY baudrate mismatch (adapter can't decode host commands)")


# ============================================================================
# Main Menu
# ============================================================================

def main():
    config = Config()
    conn = CANConnection(config)

    print()
    print("  Nissan Almera N18 — CAN/UDS Diagnostic Tool")
    print("  Hardware: CH340 + LM339 USB-to-OBD2 adapter")
    print("  CAN bus: 500 kbps")

    if not config.get("channel"):
        print("\n  First time? Let's configure your adapter.")
        menu_settings(config)

    while True:
        print()
        print("=" * 62)
        print(f"  {conn.status_str()}")
        print("=" * 62)
        print()
        print("  [c] Connect        [d] Disconnect      [s] Settings")
        print()
        print("  --- Diagnose ---")
        print("  [1] Sniff bus          [2] Loopback test")
        print("  [3] Raw UDS (BCM)      [4] Raw CAN frame")
        print("  [5] Scan DIDs")
        print()
        print("  --- Door Lock ---")
        print("  [6] Unlock door        [7] Lock door")
        print("  [8] Full capture replay")
        print()
        print("  --- DRL ---")
        print("  [9] DRL on/off")
        print()
        print("  [q] Quit")

        choice = input("\n> ").strip().lower()

        try:
            if choice == "c":
                menu_connect(conn)
            elif choice == "d":
                conn.disconnect()
                print("  Disconnected.")
            elif choice == "s":
                menu_settings(config)
            elif choice == "1":
                menu_sniff(conn)
            elif choice == "2":
                menu_loopback_test(conn)
            elif choice == "3":
                menu_raw_uds(conn)
            elif choice == "4":
                menu_raw_can(conn)
            elif choice == "5":
                menu_scan_dids(conn)
            elif choice == "6":
                menu_unlock(conn)
            elif choice == "7":
                menu_lock(conn)
            elif choice == "8":
                menu_full_sequence(conn)
            elif choice == "9":
                menu_drl(conn)
            elif choice in ("q", "quit", "exit"):
                conn.disconnect()
                print("  Bye!")
                break
            else:
                print("  Invalid choice.")
        except can.CanError as e:
            print(f"\n  CAN ERROR: {e}")
            print("  Connection may be lost. Try [c] to reconnect.")
        except KeyboardInterrupt:
            print("\n  Interrupted.")
        except Exception as e:
            print(f"\n  ERROR: {e}")

        input("\nPress Enter...")


if __name__ == "__main__":
    main()
