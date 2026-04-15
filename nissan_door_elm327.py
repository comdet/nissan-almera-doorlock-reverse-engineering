#!/usr/bin/env python3
"""
Nissan Almera Turbo (N18) — Door Lock/Unlock via ELM327
=========================================================
สั่ง lock/unlock ประตูและ DRL ผ่าน ELM327 WiFi adapter
ต่อตรง TCP หรือผ่าน ESP32-C3 USB bridge

การเชื่อมต่อ:
  TCP ตรง:   python nissan_door_elm327.py --tcp 192.168.0.10:35000
  Serial:    python nissan_door_elm327.py --serial COM4

คำสั่ง:
  python nissan_door_elm327.py --tcp ... --cmd unlock
  python nissan_door_elm327.py --serial COM4 --cmd lock
  python nissan_door_elm327.py --tcp ... --cmd status
  python nissan_door_elm327.py --tcp ...              (interactive)
"""

import socket
import time
import sys
import os
import argparse
import re

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import serial as pyserial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


# ============================================================================
# ELM327 Communication Layer
# ============================================================================

class ELM327:
    """ELM327 adapter — TCP (direct WiFi) or Serial (ESP32-C3 bridge)."""

    def __init__(self, conn, verbose=True):
        self.conn = conn
        self.verbose = verbose
        self.is_tcp = isinstance(conn, socket.socket)

    @classmethod
    def connect_tcp(cls, host, port, verbose=True):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))
        elm = cls(sock, verbose)
        time.sleep(0.5)
        elm._drain()
        return elm

    @classmethod
    def connect_serial(cls, port, baudrate=115200, verbose=True):
        if not HAS_SERIAL:
            print("ERROR: pyserial not installed. Run: pip install pyserial")
            sys.exit(1)
        ser = pyserial.Serial(port, baudrate, timeout=1)
        elm = cls(ser, verbose)
        # Longer wait for WiFi bridge adapters (ESP32-C3 → ELM327 WiFi)
        if verbose:
            print("  Waiting for adapter...")
        time.sleep(3.0)
        elm._drain()
        return elm

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def _drain(self):
        """Drain pending data from buffer."""
        if self.is_tcp:
            self.conn.settimeout(0.3)
            try:
                while self.conn.recv(4096):
                    pass
            except (socket.timeout, OSError):
                pass
            self.conn.settimeout(5)
        else:
            self.conn.reset_input_buffer()
            # Keep reading until silence (ELM327 may still be sending)
            time.sleep(0.05)
            for _ in range(10):
                n = self.conn.in_waiting
                if n:
                    self.conn.read(n)
                    time.sleep(0.05)
                else:
                    break

    def _read_until_prompt(self, timeout=3.0):
        """Read data until '>' prompt or timeout."""
        buf = b""
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break

                if self.is_tcp:
                    self.conn.settimeout(min(0.5, remaining))
                    chunk = self.conn.recv(4096)
                else:
                    chunk = self.conn.read(self.conn.in_waiting or 1)

                if chunk:
                    buf += chunk
                    if b">" in buf:
                        break
            except (socket.timeout, OSError):
                continue

        return buf

    def cmd(self, command, timeout=3.0):
        """Send AT/OBD command, wait for '>' prompt.
        Returns list of response lines (cleaned)."""
        if self.verbose:
            print(f"  TX> {command}")

        self._drain()

        raw = (command + "\r").encode("ascii")
        if self.is_tcp:
            self.conn.sendall(raw)
        else:
            self.conn.write(raw)

        buf = self._read_until_prompt(timeout)

        # Decode and parse lines
        text = buf.decode("ascii", errors="replace")
        lines = []
        for part in text.split("\r"):
            line = part.strip().replace(">", "").strip()
            # skip empty, skip echo of our command
            if not line:
                continue
            if line.upper() == command.upper():
                continue
            lines.append(line)

        if self.verbose:
            for l in lines:
                print(f"  RX< {l}")

        return lines


# ============================================================================
# Nissan BCM via ELM327
# ============================================================================

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLength",
    0x22: "conditionsNotCorrect",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x78: "responsePending",
    0x7E: "subFuncNotSupportedInSession",
    0x7F: "serviceNotSupportedInActiveSession",
}

# ELM327 error keywords
ELM_ERRORS = {
    "?", "NO DATA", "CAN ERROR", "UNABLE TO CONNECT",
    "BUS INIT: ...ERROR", "BUFFER FULL", "DATA ERROR",
    "BUS BUSY", "FB ERROR", "ACT ALERT",
}


class NissanBCM:
    """Nissan BCM UDS communication through ELM327.

    With ATCAF1 + ATH1, response format:
        765 50 03 00 32 01 F4
        ^^^                      CAN ID (3 hex chars)
            ^^ ^^ ^^ ^^ ^^ ^^   UDS payload (PCI stripped by ELM327)
    """

    def __init__(self, elm):
        self.elm = elm
        self._method = None   # best known method: 'standard', 'atcaf0', 'stpx'

    def setup(self):
        """Configure ELM327 for Nissan BCM (CAN 500kbps, header 0x745)."""
        print("\n--- ELM327 Setup ---")

        # Reset — wait extra for clone to finish boot
        self.elm.cmd("ATZ", timeout=4)
        time.sleep(1.0)
        self.elm._drain()

        # Echo off FIRST — critical for clean response parsing
        self.elm.cmd("ATE0")
        time.sleep(0.1)
        self.elm._drain()

        resp = self.elm.cmd("ATI")
        ver = resp[0] if resp else "?"
        print(f"  ELM327: {ver}")

        cmds = [
            ("ATL0",      "linefeeds off"),
            ("ATSP6",     "CAN 500kbps (ISO 15765-4)"),
            ("ATSH 745",  "header -> BCM (0x745)"),
            ("ATCAF1",    "CAN auto formatting ON"),
            ("ATH1",      "show response headers"),
            ("ATST FF",   "timeout max (~1s)"),
        ]
        for cmd, desc in cmds:
            self.elm.cmd(cmd)
            if self.elm.verbose:
                print(f"         {cmd:10s}  {desc}")

        # Skip ATCRA — v1.5 clones don't filter properly and
        # cause spurious '?' on every response.  Accept all CAN IDs.
        self._atcra_set = False

        print("--- Ready ---\n")

    def _parse_response(self, lines):
        """Parse ELM327 CAN response (ATH1 mode).

        ATCAF1 may or may not strip PCI depending on clone.
        Handles both formats:
          Stripped: '765 50 03 00 32 01 F4'     (first data byte is SID+0x40)
          Raw:      '765 06 50 03 00 32 01 F4'  (first data byte is PCI)

        Clone quirk: some clones return '?' alongside valid data when
        ATCRA filter doesn't match the response CAN ID.  We skip error
        lines and look for real data first.

        Returns (can_id:int|None, uds_payload:list[int], error:str|None)"""
        first_error = None

        for line in lines:
            upper = line.strip().upper()

            # Skip ESP32-C3 bridge debug messages
            if upper.startswith("[WIFI]") or upper.startswith("[TCP]"):
                continue

            # ELM327 error keyword — remember but don't bail yet
            if upper in ELM_ERRORS or upper.startswith("BUS INIT"):
                if first_error is None:
                    first_error = upper
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            try:
                can_id = int(parts[0], 16)
                data = [int(b, 16) for b in parts[1:]]
                if not data:
                    continue

                # Detect if first byte is PCI (SF: high nibble=0, low=length)
                first = data[0]
                pci_type = (first >> 4) & 0x0F
                pci_len = first & 0x0F

                if pci_type == 0 and 1 <= pci_len <= 7 and len(data) >= pci_len + 1:
                    # Looks like PCI byte — strip it
                    payload = data[1:1 + pci_len]
                else:
                    # Already stripped or unknown format — use as-is
                    payload = data

                return can_id, payload, None
            except ValueError:
                continue

        # No valid data found — return the first error we saw
        return None, [], first_error or "UNPARSEABLE"

    def send_uds(self, uds_hex, label=""):
        """Send UDS command (ATCAF1 adds ISO-TP framing automatically).
        Returns (ok:bool, can_id:int|None, payload:list|str)."""
        if label and self.elm.verbose:
            print(f"\n  [{label}]")

        lines = self.elm.cmd(uds_hex, timeout=3)

        if not lines:
            if self.elm.verbose:
                print("  !! No response")
            return False, None, "NO RESPONSE"

        can_id, payload, error = self._parse_response(lines)

        if error:
            if self.elm.verbose:
                print(f"  !! Error: {error}")
            return False, can_id, error

        if payload and payload[0] == 0x7F and len(payload) >= 3:
            nrc = payload[2]
            nrc_name = NRC_NAMES.get(nrc, f"0x{nrc:02X}")
            if self.elm.verbose:
                print(f"  !! REJECTED: NRC=0x{nrc:02X} ({nrc_name})")
            return False, can_id, payload

        # Validate response SID matches request SID.
        # Catches stale responses from earlier commands (e.g., late
        # TesterPresent 0x7E arriving during IOControl window).
        if payload:
            try:
                req = bytes.fromhex(uds_hex.replace(" ", ""))
                # SID could be at [0] (ATCAF1) or [1] (ATCAF0 with PCI)
                expected = set()
                if len(req) >= 1:
                    expected.add((req[0] + 0x40) & 0xFF)
                if len(req) >= 2:
                    expected.add((req[1] + 0x40) & 0xFF)
                if payload[0] not in expected:
                    if self.elm.verbose:
                        print(f"  !! SID mismatch: got 0x{payload[0]:02X},"
                              f" expected one of"
                              f" {{{', '.join(f'0x{s:02X}' for s in sorted(expected))}}}"
                              f" -- stale response from another command")
                    return False, can_id, "SID_MISMATCH"
            except (ValueError, IndexError):
                pass

        return True, can_id, payload

    # ---- UDS Helpers ----

    def enter_extended_session(self):
        """DiagnosticSessionControl → Extended (0x03)."""
        ok, _, _ = self.send_uds("10 03", "Extended Session")
        return ok

    def return_default_session(self):
        """DiagnosticSessionControl → Default (0x01)."""
        ok, _, _ = self.send_uds("10 01", "Default Session")
        return ok

    def tester_present(self):
        """TesterPresent keep-alive."""
        ok, _, _ = self.send_uds("3E 00", "TesterPresent")
        return ok

    def io_control(self, did, state, label=""):
        """IOControlByIdentifier — shortTermAdjustment (0x03)."""
        did_hex = f"{(did >> 8) & 0xFF:02X} {did & 0xFF:02X}"
        state_hex = " ".join(f"{b:02X}" for b in state)
        cmd = f"2F {did_hex} 03 {state_hex}"
        desc = label or f"IOControl DID=0x{did:04X} [{state_hex}]"
        ok, _, resp = self.send_uds(cmd, desc)
        if not ok and isinstance(resp, list) and len(resp) >= 3 and resp[2] == 0x7F:
            # Wrong session — auto retry
            if self.elm.verbose:
                print("  -> Wrong session, re-entering extended...")
            self.enter_extended_session()
            ok, _, resp = self.send_uds(cmd, f"{desc} (retry)")
        return ok

    def _obd_query(self, pid_cmd):
        """Send OBD-II query via broadcast, temporarily switching header+filter.
        Returns raw response lines."""
        self.elm.cmd("ATSH 7DF")
        self.elm.cmd("ATCRA 7E8")
        lines = self.elm.cmd(pid_cmd, timeout=3)
        self.elm.cmd("ATSH 745")
        self.elm.cmd("ATCRA 765")
        return lines

    def read_speed(self):
        """OBD-II PID 0x0D (vehicle speed). Returns km/h or None."""
        lines = self._obd_query("01 0D")
        for line in lines:
            parts = line.split()
            # Raw: '7E8 03 41 0D XX ...'  -> find 41 0D after PCI
            for i in range(len(parts) - 2):
                if parts[i].upper() == "41" and parts[i + 1].upper() == "0D":
                    try:
                        return int(parts[i + 2], 16)
                    except ValueError:
                        pass
        return None

    def read_rpm(self):
        """OBD-II PID 0x0C (engine RPM). Returns RPM or None."""
        lines = self._obd_query("01 0C")
        for line in lines:
            parts = line.split()
            for i in range(len(parts) - 3):
                if parts[i].upper() == "41" and parts[i + 1].upper() == "0C":
                    try:
                        a = int(parts[i + 2], 16)
                        b = int(parts[i + 3], 16)
                        return ((a * 256) + b) // 4
                    except (ValueError, IndexError):
                        pass
        return None

    def read_voltage(self):
        """Battery voltage via ATRV."""
        lines = self.elm.cmd("ATRV")
        for line in lines:
            m = re.search(r"(\d+\.?\d*)\s*V", line, re.IGNORECASE)
            if m:
                return float(m.group(1))
        return None

    # ---- Adapter Probe & Alternative Methods ----

    def probe(self):
        """Detect adapter type and capabilities. Returns info dict."""
        print("\n" + "=" * 50)
        print("  ADAPTER PROBE")
        print("=" * 50)
        info = {}

        # ATI — standard ELM327 version
        resp = self.elm.cmd("ATI")
        info['version'] = resp[0] if resp else "?"
        print(f"  ELM327 version : {info['version']}")

        # STI — STN1110 detection
        resp = self.elm.cmd("STI")
        is_stn = bool(resp) and all("?" not in l for l in resp)
        info['is_stn'] = is_stn
        if is_stn:
            info['stn_version'] = resp[0] if resp else "?"
            print(f"  STN1110        : YES  {info['stn_version']}")
            stdi = self.elm.cmd("STDI")
            if stdi:
                info['stn_device'] = stdi
                for l in stdi:
                    print(f"                   {l}")
        else:
            print("  STN1110        : NO")

        # ATCAF1 payload limit test
        print("\n  Testing ATCAF1 payload limit...")
        max_pl = self._test_payload_limit()
        info['max_payload'] = max_pl
        print(f"  Max payload (ATCAF1): {max_pl} bytes")
        if max_pl < 6:
            print(f"  !! IOControl needs 6 bytes -- ATCAF1 BLOCKED")

        # ATCAF0 raw mode test
        print("\n  Testing ATCAF0 raw CAN mode...")
        caf0_result = self._test_atcaf0()
        info['atcaf0'] = caf0_result
        if caf0_result == 'ok':
            print("  ATCAF0 raw send: OK (got BCM response)")
        elif caf0_result == 'sent_no_resp':
            print("  ATCAF0 raw send: SENT but NO DATA (may still work)")
        else:
            print(f"  ATCAF0 raw send: FAILED ({caf0_result})")

        # Determine best method
        print("\n  --- Recommendation ---")
        if max_pl >= 6:
            self._method = 'standard'
            print("  -> Standard ATCAF1 mode (payload fits)")
        elif caf0_result in ('ok', 'sent_no_resp'):
            self._method = 'atcaf0'
            print("  -> ATCAF0 raw CAN mode (bypass payload limit)")
        elif is_stn:
            self._method = 'stpx'
            print("  -> STN1110 STPX mode")
        else:
            self._method = 'atcaf0'  # try anyway as best guess
            print("  -> Will try ATCAF0 (best available option)")
            print("     If that fails, need ELM327 v2.x or direct CAN adapter")
        print("=" * 50 + "\n")

        return info

    def _test_payload_limit(self):
        """Test max bytes the clone accepts in ATCAF1 mode."""
        max_ok = 0
        for n in range(2, 8):
            # DiagSessionControl Default (10 01) + padding bytes
            payload = "10 01" + " 00" * (n - 2) if n > 2 else "10 01"
            lines = self.elm.cmd(payload, timeout=2)
            has_q = any(l.strip() == "?" for l in lines)
            has_data = any(self._line_has_can_data(l) for l in lines)
            if has_q and not has_data:
                # '?' with no data = clone genuinely rejected the payload
                break
            if has_data or not has_q:
                max_ok = n
        # Re-enter extended session (test sent Default Session)
        self.enter_extended_session()
        return max_ok

    @staticmethod
    def _line_has_can_data(line):
        """Check if a response line contains hex CAN data (e.g. '7E8 06 50 ...')."""
        parts = line.strip().split()
        if len(parts) < 2:
            return False
        try:
            int(parts[0], 16)
            int(parts[1], 16)
            return True
        except ValueError:
            return False

    def _test_atcaf0(self):
        """Test if ATCAF0 can actually send CAN data.
        Returns: 'ok', 'sent_no_resp', 'rejected', or 'error'."""
        self.elm.cmd("ATCAF0")
        time.sleep(0.1)

        # Send DiagSession Extended as raw CAN:
        # PCI(02) SID(10) Sub(03) Pad(FF x5) = 8 bytes
        lines = self.elm.cmd("02 10 03 FF FF FF FF FF", timeout=3)
        self.elm.cmd("ATCAF1")

        for line in lines:
            upper = line.strip().upper()
            if upper == "?":
                return 'rejected'
            if "NO DATA" in upper:
                return 'sent_no_resp'
            if "CAN ERROR" in upper:
                return 'error'
            # Any response with hex data = success
            parts = line.split()
            if len(parts) >= 3:
                try:
                    int(parts[0], 16)
                    return 'ok'
                except ValueError:
                    continue
        return 'sent_no_resp'  # no clear error = probably sent

    def _build_raw_iocontrol(self, did, ctrl_param, state):
        """Build 8-byte raw CAN data for IOControlByIdentifier.
        Returns hex string like '06 2F 02 3F 03 00 01 FF'."""
        did_h = (did >> 8) & 0xFF
        did_l = did & 0xFF
        # UDS payload: SID(2F) DID_H DID_L CtrlParam State[0] State[1]
        uds = [0x2F, did_h, did_l, ctrl_param] + list(state)
        pci = len(uds)  # SF PCI = length
        raw = [pci] + uds
        # Pad to 8 bytes
        while len(raw) < 8:
            raw.append(0xFF)
        return " ".join(f"{b:02X}" for b in raw[:8])

    def io_control_raw(self, did, state, label=""):
        """IOControlByIdentifier via ATCAF0 raw CAN mode.
        Enters ATCAF0, sends raw frame, restores ATCAF1."""
        raw_hex = self._build_raw_iocontrol(did, 0x03, state)
        desc = label or f"IOControl DID=0x{did:04X} (raw)"

        self.elm.cmd("ATCAF0")
        time.sleep(0.05)
        ok, can_id, resp = self.send_uds(raw_hex, desc)

        # If NO DATA, try without any receive filter
        if not ok and isinstance(resp, str) and "NO DATA" in resp.upper():
            if self.elm.verbose:
                print("  -> NO DATA, retrying with ATAR (no filter)...")
            self.elm.cmd("ATAR")
            ok, can_id, resp = self.send_uds(raw_hex, f"{desc} (ATAR)")
            # Restore ATCRA if it was set
            if self._atcra_set:
                self.elm.cmd("ATCRA 765")

        self.elm.cmd("ATCAF1")
        return ok, resp

    def io_control_stpx(self, did, state, label=""):
        """IOControlByIdentifier via STN1110 STPX command."""
        did_h = (did >> 8) & 0xFF
        did_l = did & 0xFF
        uds = [0x2F, did_h, did_l, 0x03] + list(state)
        pci = len(uds)
        raw = [pci] + uds
        while len(raw) < 8:
            raw.append(0xFF)
        data_hex = "".join(f"{b:02X}" for b in raw[:8])

        desc = label or f"IOControl DID=0x{did:04X} (STPX)"
        if self.elm.verbose:
            print(f"\n  [{desc}]")

        lines = self.elm.cmd(f"STPX H:745, D:{data_hex}, R:1", timeout=5)

        for line in lines:
            upper = line.strip().upper()
            if upper == "?":
                if self.elm.verbose:
                    print("  !! STPX not supported")
                return False, "STPX_NOT_SUPPORTED"
            if "NO DATA" in upper:
                return False, "NO DATA"

        can_id, payload, error = self._parse_response(lines)
        if error:
            return False, error
        if payload and payload[0] == 0x7F:
            nrc = payload[2] if len(payload) >= 3 else 0
            return False, payload
        return True, payload

    def unlock_raw(self):
        """Unlock door using ATCAF0 raw CAN mode.

        Strategy: ExtendedSession via ATCAF1 (2 bytes, works on clone),
        then ATCAF0 for raw 8-byte IOControl frame."""
        print("\n--- Unlock via ATCAF0 Raw CAN ---")

        if not self.enter_extended_session():
            time.sleep(0.5)
            if not self.enter_extended_session():
                print("  !! Cannot enter extended session")
                return False
        self.tester_present()

        ok, resp = self.io_control_raw(0x023F, [0x00, 0x01],
                                       "UNLOCK (DID=0x023F [00 01] raw)")

        # Return control to ECU (raw)
        self.io_control_raw(0x023F, [0x00, 0x00], "Return Control (raw)")

        # Restore and cleanup
        self.return_default_session()

        if ok:
            print("  UNLOCK raw: OK")
        else:
            print(f"  UNLOCK raw: response={resp}")
            print("  (listen for door click -- frame may have been sent)")
        print("---")
        return ok

    def lock_raw(self):
        """Lock door using ATCAF0 raw CAN mode."""
        print("\n--- Lock via ATCAF0 Raw CAN ---")

        if not self.enter_extended_session():
            time.sleep(0.5)
            if not self.enter_extended_session():
                print("  !! Cannot enter extended session")
                return False
        self.tester_present()

        ok, resp = self.io_control_raw(0x023F, [0x00, 0x02],
                                       "LOCK (DID=0x023F [00 02] raw)")

        self.io_control_raw(0x023F, [0x00, 0x00], "Return Control (raw)")
        self.return_default_session()

        if ok:
            print("  LOCK raw: OK")
        else:
            print(f"  LOCK raw: response={resp}")
            print("  (listen for door click -- frame may have been sent)")
        print("---")
        return ok

    def unlock_stpx(self):
        """Unlock door using STN1110 STPX command."""
        print("\n--- Unlock via STPX (STN1110) ---")

        if not self.enter_extended_session():
            print("  !! Cannot enter extended session")
            return False
        self.tester_present()

        ok, resp = self.io_control_stpx(0x023F, [0x00, 0x01],
                                        "UNLOCK (STPX)")
        self.io_control_stpx(0x023F, [0x00, 0x00], "Return Control (STPX)")
        self.return_default_session()

        print(f"  STPX unlock: {'OK' if ok else resp}")
        print("---")
        return ok

    def lock_stpx(self):
        """Lock door using STN1110 STPX command."""
        print("\n--- Lock via STPX (STN1110) ---")

        if not self.enter_extended_session():
            print("  !! Cannot enter extended session")
            return False
        self.tester_present()

        ok, resp = self.io_control_stpx(0x023F, [0x00, 0x02],
                                        "LOCK (STPX)")
        self.io_control_stpx(0x023F, [0x00, 0x00], "Return Control (STPX)")
        self.return_default_session()

        print(f"  STPX lock: {'OK' if ok else resp}")
        print("---")
        return ok


# ============================================================================
# Door Lock / DRL Constants
# ============================================================================

DID_DOOR = 0x023F
DID_DRL  = 0x0202

UNLOCK      = [0x00, 0x01]
LOCK        = [0x00, 0x02]   # inferred — needs live test
RETURN_ECU  = [0x00, 0x00]
DRL_ON      = [0x00, 0x02]
DRL_OFF     = [0x00, 0x00]   # inferred — needs live test


# ============================================================================
# Commands
# ============================================================================

def _do_standard_io(bcm, did, state, label):
    """Standard ATCAF1 IOControl — returns True/False/'payload_blocked'."""
    if not bcm.enter_extended_session():
        time.sleep(0.5)
        if not bcm.enter_extended_session():
            print("  !! Cannot enter extended session")
            return False
    bcm.tester_present()

    ok = bcm.io_control(did, state, label)

    # Detect if clone blocked the payload (io_control returns False,
    # and the ELM returned '?' for the 6-byte command)
    if not ok and bcm._method is None:
        # The command might have been blocked by payload limit.
        # We can't tell for sure here, but if we haven't probed yet,
        # we'll try fallback methods.
        bcm.io_control(did, RETURN_ECU, "Return control to ECU")
        bcm.return_default_session()
        return 'maybe_blocked'

    bcm.io_control(did, RETURN_ECU, "Return control to ECU")
    bcm.return_default_session()
    return ok


def do_unlock(bcm):
    print("=" * 50)
    print("  DOOR UNLOCK")
    print("=" * 50)

    method = bcm._method

    ok = False

    # Method 1: Standard ATCAF1 (if known to work or first try)
    if method in (None, 'standard'):
        print("  Trying standard ATCAF1...")
        result = _do_standard_io(bcm, DID_DOOR, UNLOCK,
                                 "Unlock (DID=0x023F [00 01])")
        if result is True:
            ok = True
            bcm._method = 'standard'
        elif result == 'maybe_blocked' and method is None:
            print("  Standard method failed, trying alternatives...")

    # Method 2: ATCAF0 raw CAN
    if not ok and method in (None, 'atcaf0', 'maybe_blocked'):
        print("  Trying ATCAF0 raw CAN mode...")
        ok = bcm.unlock_raw()
        if ok:
            bcm._method = 'atcaf0'

    # Method 3: STN1110 STPX
    if not ok and method in (None, 'stpx'):
        print("  Trying STPX (STN1110)...")
        ok = bcm.unlock_stpx()
        if ok:
            bcm._method = 'stpx'

    print("=" * 50)
    print(f"  UNLOCK: {'OK' if ok else 'FAILED'}")
    if not ok:
        print("  TIP: Run [8] Probe to diagnose adapter capabilities")
        print("       Listen for door click even if response says FAILED")
    print("=" * 50)
    return ok


def do_lock(bcm):
    print("=" * 50)
    print("  DOOR LOCK")
    print("=" * 50)

    method = bcm._method
    ok = False

    if method in (None, 'standard'):
        print("  Trying standard ATCAF1...")
        result = _do_standard_io(bcm, DID_DOOR, LOCK,
                                 "Lock (DID=0x023F [00 02])")
        if result is True:
            ok = True
            bcm._method = 'standard'

    if not ok and method in (None, 'atcaf0', 'maybe_blocked'):
        print("  Trying ATCAF0 raw CAN mode...")
        ok = bcm.lock_raw()
        if ok:
            bcm._method = 'atcaf0'

    if not ok and method in (None, 'stpx'):
        print("  Trying STPX (STN1110)...")
        ok = bcm.lock_stpx()
        if ok:
            bcm._method = 'stpx'

    print("=" * 50)
    print(f"  LOCK: {'OK' if ok else 'FAILED'}")
    if not ok:
        print("  TIP: Run [8] Probe to diagnose adapter capabilities")
    print("=" * 50)
    return ok


def do_drl_on(bcm):
    print("=== DRL ON ===")
    bcm.enter_extended_session()
    ok = bcm.io_control(DID_DRL, DRL_ON, "DRL ON (DID=0x0202 [00 02])")
    bcm.return_default_session()
    print(f"  {'OK' if ok else 'FAILED'}")
    return ok


def do_drl_off(bcm):
    print("=== DRL OFF (inferred) ===")
    bcm.enter_extended_session()
    ok = bcm.io_control(DID_DRL, DRL_OFF, "DRL OFF (DID=0x0202 [00 00])")
    bcm.io_control(DID_DRL, RETURN_ECU, "Return DRL control")
    bcm.return_default_session()
    print(f"  {'OK' if ok else 'FAILED'}")
    return ok


def do_status(bcm):
    print("=== VEHICLE STATUS ===")

    v = bcm.read_voltage()
    print(f"  Battery : {v:.1f}V" if v else "  Battery : N/A")

    rpm = bcm.read_rpm()
    print(f"  RPM     : {rpm}" if rpm is not None else "  RPM     : N/A")

    speed = bcm.read_speed()
    print(f"  Speed   : {speed} km/h" if speed is not None else "  Speed   : N/A")

    engine = "ON" if (rpm is not None and rpm > 0) else ("OFF" if rpm == 0 else "?")
    print(f"  Engine  : {engine}")

    print("=== DONE ===")


def do_probe(bcm):
    """Probe adapter capabilities and recommend best method."""
    info = bcm.probe()
    return info.get('max_payload', 0) >= 6 or info.get('atcaf0') in ('ok', 'sent_no_resp')


# ============================================================================
# Interactive Mode
# ============================================================================

def interactive(bcm):
    print()
    print("=" * 50)
    print("  Nissan Almera — ELM327 Door Lock")
    print("  Ctrl+C to quit")
    print("=" * 50)

    while True:
        method_str = f" [{bcm._method or 'auto'}]" if bcm._method else ""
        print()
        print(f"  --- Door Lock{method_str} ---")
        print("  [1] Unlock door        [5] Read status")
        print("  [2] Lock door          [6] Raw AT command")
        print("  [3] DRL on             [7] Raw UDS hex")
        print("  [4] DRL off            [8] Probe adapter")
        print("                         [q] Quit")
        print()

        try:
            choice = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            do_unlock(bcm)
        elif choice == "2":
            do_lock(bcm)
        elif choice == "3":
            do_drl_on(bcm)
        elif choice == "4":
            do_drl_off(bcm)
        elif choice == "5":
            do_status(bcm)
        elif choice == "6":
            try:
                cmd = input("  AT> ").strip()
                if cmd:
                    bcm.elm.cmd(cmd)
            except (EOFError, KeyboardInterrupt):
                pass
        elif choice == "7":
            try:
                cmd = input("  UDS> ").strip()
                if cmd:
                    bcm.send_uds(cmd, "Raw UDS")
            except (EOFError, KeyboardInterrupt):
                pass
        elif choice == "8":
            do_probe(bcm)
        elif choice in ("q", "quit", "exit"):
            break

    print("\nBye!")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Nissan Almera Turbo (N18) — Door Lock via ELM327",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
connection (pick one):
  --tcp HOST:PORT     ELM327 WiFi direct (e.g. 192.168.0.10:35000)
  --serial PORT       ESP32-C3 USB bridge (e.g. COM4)

commands (--cmd):
  unlock    Unlock doors (auto-detects best method)
  lock      Lock doors (auto-detects best method)
  drl-on    DRL on
  drl-off   DRL off (inferred)
  status    Battery voltage + RPM + speed
  probe     Detect adapter capabilities and payload limits

auto-fallback for ELM327 v1.5 clone (4-byte payload limit):
  1. Standard ATCAF1  (works if payload <= 4 bytes)
  2. ATCAF0 raw CAN   (bypass limit with raw 8-byte frames)
  3. STN1110 STPX     (if clone is STN1110-based)

examples:
  python nissan_door_elm327.py --tcp 192.168.0.10:35000
  python nissan_door_elm327.py --serial COM4
  python nissan_door_elm327.py --serial COM4 --cmd unlock
  python nissan_door_elm327.py --serial COM4 --cmd probe
  python nissan_door_elm327.py --tcp 192.168.0.10:35000 --cmd status
""")
    parser.add_argument("--tcp", metavar="HOST:PORT",
                        help="TCP connection to ELM327 WiFi")
    parser.add_argument("--serial", metavar="PORT",
                        help="Serial port (ESP32-C3 bridge)")
    parser.add_argument("--baud", type=int, default=115200,
                        help="Serial baud rate (default: 115200)")
    parser.add_argument("--cmd",
                        choices=["unlock", "lock", "drl-on", "drl-off",
                                 "status", "probe"],
                        help="Single-shot command (omit for interactive)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress verbose output")

    args = parser.parse_args()

    if not args.tcp and not args.serial:
        parser.error("specify --tcp or --serial")

    verbose = not args.quiet

    # ---- Connect ----
    if args.tcp:
        parts = args.tcp.rsplit(":", 1)
        host = parts[0] if parts[0] else "192.168.0.10"
        port = int(parts[1]) if len(parts) > 1 else 35000
        print(f"Connecting TCP {host}:{port} ...")
        try:
            elm = ELM327.connect_tcp(host, port, verbose=verbose)
        except Exception as e:
            print(f"ERROR: {e}")
            sys.exit(1)
    else:
        print(f"Connecting Serial {args.serial} @ {args.baud} ...")
        try:
            elm = ELM327.connect_serial(args.serial, args.baud, verbose=verbose)
        except Exception as e:
            print(f"ERROR: {e}")
            sys.exit(1)

    print("Connected!")

    bcm = NissanBCM(elm)

    try:
        bcm.setup()

        if args.cmd:
            cmds = {
                "unlock":  do_unlock,
                "lock":    do_lock,
                "drl-on":  do_drl_on,
                "drl-off": do_drl_off,
                "status":  do_status,
                "probe":   do_probe,
            }
            ok = cmds[args.cmd](bcm)
            sys.exit(0 if ok else 1)
        else:
            interactive(bcm)

    except KeyboardInterrupt:
        print("\nAborted")
    finally:
        # Best-effort cleanup
        try:
            bcm.return_default_session()
        except Exception:
            pass
        elm.close()


if __name__ == "__main__":
    main()
