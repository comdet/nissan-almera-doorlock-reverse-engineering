#!/usr/bin/env python3
"""
Nissan Almera Turbo (N18) / Versa — Door Unlock via UDS over CAN

Reverse-engineered from OBD door lock device capture.
Target: BCM (Body Control Module)
  Request CAN ID:  0x745
  Response CAN ID: 0x765

IMPORTANT: This script is for research/educational purposes.
           Test on your own vehicle only.

Hardware: Any python-can compatible CAN adapter
  - CANable / slcan
  - PEAK PCAN-USB
  - SocketCAN (Linux)
  - Kvaser
  - etc.

Usage:
  python nissan_door_unlock.py --interface slcan --channel COM3 --bitrate 500000
  python nissan_door_unlock.py --interface socketcan --channel can0
  python nissan_door_unlock.py --interface pcan --channel PCAN_USBBUS1
"""

import argparse
import time
import sys

try:
    import can
except ImportError:
    print("ERROR: python-can not installed. Run: pip install python-can")
    sys.exit(1)


# ============================================================================
# CAN / UDS Constants
# ============================================================================

BCM_REQUEST_ID  = 0x745
BCM_RESPONSE_ID = 0x765

# UDS Service IDs
SID_DIAG_SESSION_CTRL   = 0x10
SID_TESTER_PRESENT      = 0x3E
SID_IO_CONTROL          = 0x2F
SID_NEGATIVE_RESPONSE   = 0x7F

# Diagnostic Sessions
SESSION_DEFAULT  = 0x01
SESSION_EXTENDED = 0x03

# IOControl parameters
IO_CTRL_SHORT_TERM_ADJ = 0x03

# Door lock DIDs (observed from capture)
# Both DIDs were used by the OBD device during unlock.
# DID_DOOR_023F is the primary suspect for unlock command.
# DID_DOOR_0202 was also sent — purpose not 100% confirmed.
DID_DOOR_023F = 0x023F
DID_DOOR_0202 = 0x0202

# Control states observed:
#   DID=0x023F: [00 01] = unlock?,  [00 00] = return control to ECU
#   DID=0x0202: [00 02] = unlock?   (only seen once, positive response)

# NRC codes we care about
NRC_SERVICE_NOT_SUPPORTED_IN_SESSION = 0x7F
NRC_CONDITIONS_NOT_CORRECT           = 0x22
NRC_RESPONSE_PENDING                 = 0x78
NRC_REQUEST_OUT_OF_RANGE             = 0x31


# ============================================================================
# UDS over CAN (ISO-TP Single Frame only — all our messages fit in 1 frame)
# ============================================================================

class UDSError(Exception):
    """Raised when ECU sends a negative response."""
    def __init__(self, service, nrc):
        self.service = service
        self.nrc = nrc
        nrc_names = {
            0x10: "generalReject", 0x11: "serviceNotSupported",
            0x12: "subFunctionNotSupported", 0x13: "incorrectMessageLength",
            0x22: "conditionsNotCorrect", 0x31: "requestOutOfRange",
            0x33: "securityAccessDenied", 0x35: "invalidKey",
            0x78: "requestCorrectlyReceivedResponsePending",
            0x7E: "subFunctionNotSupportedInActiveSession",
            0x7F: "serviceNotSupportedInActiveSession",
        }
        name = nrc_names.get(nrc, f"unknown(0x{nrc:02X})")
        super().__init__(f"NRC=0x{nrc:02X} ({name}) for service 0x{service:02X}")


class NissanBCM:
    """Communicate with Nissan BCM via UDS Single Frames."""

    def __init__(self, bus, timeout=2.0):
        self.bus = bus
        self.timeout = timeout

    def _send_single_frame(self, payload):
        """Send an ISO-TP Single Frame (PCI type 0) to BCM."""
        length = len(payload)
        if length > 7:
            raise ValueError(f"Single frame payload too long: {length} bytes (max 7)")

        data = [length] + list(payload) + [0xFF] * (7 - length)
        msg = can.Message(
            arbitration_id=BCM_REQUEST_ID,
            data=data,
            is_extended_id=False,
        )
        self.bus.send(msg)
        return msg

    def _recv_response(self, expected_sid=None, timeout=None):
        """
        Wait for a response from BCM (CAN ID 0x765).
        Handles:
          - Positive response (SID + 0x40)
          - Negative response (0x7F) with NRC
          - Response pending (NRC 0x78) — waits and retries
        Returns the payload bytes (after PCI byte).
        """
        if timeout is None:
            timeout = self.timeout
        deadline = time.time() + timeout

        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break

            msg = self.bus.recv(timeout=min(remaining, 0.5))
            if msg is None:
                continue
            if msg.arbitration_id != BCM_RESPONSE_ID:
                continue

            data = list(msg.data)
            pci_type = (data[0] >> 4) & 0x0F

            if pci_type != 0:
                # Not a single frame response — skip (we don't expect multiframe here)
                continue

            length = data[0] & 0x0F
            payload = data[1:1+length]

            if not payload:
                continue

            sid = payload[0]

            # Negative response
            if sid == SID_NEGATIVE_RESPONSE and len(payload) >= 3:
                rejected_sid = payload[1]
                nrc = payload[2]

                # Response pending — ECU needs more time
                if nrc == NRC_RESPONSE_PENDING:
                    print(f"  BCM: response pending (NRC=0x78), waiting...")
                    deadline = time.time() + 5.0  # extend timeout
                    continue

                raise UDSError(rejected_sid, nrc)

            # Positive response
            if expected_sid is not None and sid != (expected_sid + 0x40):
                # Not the response we expected — keep waiting
                continue

            return payload

        raise TimeoutError(f"No response from BCM (0x{BCM_RESPONSE_ID:03X}) within {timeout}s")

    # ------------------------------------------------------------------
    # UDS Services
    # ------------------------------------------------------------------

    def diagnostic_session_control(self, session):
        """Switch diagnostic session. Returns True on success."""
        session_names = {0x01: "default", 0x03: "extended"}
        name = session_names.get(session, f"0x{session:02X}")
        print(f"  >> DiagSessionControl -> {name}")

        self._send_single_frame([SID_DIAG_SESSION_CTRL, session])
        resp = self._recv_response(expected_sid=SID_DIAG_SESSION_CTRL)
        # resp[0] = 0x50, resp[1] = session echo
        print(f"  << OK: session={name}")
        return True

    def tester_present(self):
        """Send TesterPresent to keep session alive."""
        print(f"  >> TesterPresent")
        self._send_single_frame([SID_TESTER_PRESENT, 0x00])
        resp = self._recv_response(expected_sid=SID_TESTER_PRESENT)
        print(f"  << OK")
        return True

    def io_control(self, did, control_param, control_state):
        """
        Send IOControlByIdentifier.
        did: 16-bit DID
        control_param: control option (0x03 = shortTermAdjustment)
        control_state: list of bytes
        """
        did_hi = (did >> 8) & 0xFF
        did_lo = did & 0xFF
        payload = [SID_IO_CONTROL, did_hi, did_lo, control_param] + list(control_state)

        state_hex = " ".join(f"0x{b:02X}" for b in control_state)
        print(f"  >> IOControl DID=0x{did:04X} param=0x{control_param:02X} state=[{state_hex}]")

        self._send_single_frame(payload)
        resp = self._recv_response(expected_sid=SID_IO_CONTROL)
        # resp[0] = 0x6F, resp[1:3] = DID echo, rest = status
        status = resp[3:] if len(resp) > 3 else []
        status_hex = " ".join(f"0x{b:02X}" for b in status)
        print(f"  << OK: status=[{status_hex}]")
        return resp

    def enter_extended_session(self):
        """Enter extended diagnostic session with retry."""
        return self.diagnostic_session_control(SESSION_EXTENDED)

    def return_to_default_session(self):
        """Return to default session."""
        return self.diagnostic_session_control(SESSION_DEFAULT)


# ============================================================================
# Door Unlock Procedures
# ============================================================================

def unlock_door(bcm, method="both"):
    """
    Perform door unlock sequence.

    method:
      "023F"  - Use DID=0x023F with state [00 01] only
      "0202"  - Use DID=0x0202 with state [00 02] only
      "both"  - Use both DIDs (as observed in capture)
    """
    print("=" * 60)
    print("DOOR UNLOCK SEQUENCE")
    print("=" * 60)

    # Step 1: Enter extended diagnostic session
    print("\n[Step 1] Enter extended diagnostic session")
    try:
        bcm.enter_extended_session()
    except (UDSError, TimeoutError) as e:
        print(f"  FAIL: {e}")
        print("  Retrying...")
        time.sleep(0.5)
        try:
            bcm.enter_extended_session()
        except Exception as e2:
            print(f"  FATAL: Cannot enter extended session: {e2}")
            return False

    # Step 2: TesterPresent
    print("\n[Step 2] TesterPresent (keep-alive)")
    try:
        bcm.tester_present()
    except (UDSError, TimeoutError) as e:
        print(f"  WARNING: TesterPresent failed: {e} (continuing anyway)")

    # Step 3: Send IOControl command(s)
    success = False

    if method in ("0202", "both"):
        print(f"\n[Step 3a] IOControl DID=0x0202 [00 02]")
        try:
            bcm.io_control(DID_DOOR_0202, IO_CTRL_SHORT_TERM_ADJ, [0x00, 0x02])
            print("  -> DID=0x0202 command accepted!")
            success = True
        except UDSError as e:
            if e.nrc == NRC_SERVICE_NOT_SUPPORTED_IN_SESSION:
                print(f"  FAIL: Wrong session! Re-entering extended...")
                try:
                    bcm.enter_extended_session()
                    bcm.io_control(DID_DOOR_0202, IO_CTRL_SHORT_TERM_ADJ, [0x00, 0x02])
                    success = True
                except Exception as e2:
                    print(f"  FAIL on retry: {e2}")
            else:
                print(f"  FAIL: {e}")
        except TimeoutError as e:
            print(f"  FAIL: No response ({e})")

    if method in ("023F", "both"):
        print(f"\n[Step 3b] IOControl DID=0x023F [00 01]")
        # Make sure we're in extended session
        try:
            bcm.enter_extended_session()
        except Exception:
            pass

        try:
            bcm.io_control(DID_DOOR_023F, IO_CTRL_SHORT_TERM_ADJ, [0x00, 0x01])
            print("  -> DID=0x023F command accepted!")
            success = True
        except UDSError as e:
            if e.nrc == NRC_SERVICE_NOT_SUPPORTED_IN_SESSION:
                print(f"  FAIL: Wrong session! Re-entering extended...")
                try:
                    bcm.enter_extended_session()
                    bcm.io_control(DID_DOOR_023F, IO_CTRL_SHORT_TERM_ADJ, [0x00, 0x01])
                    success = True
                except Exception as e2:
                    print(f"  FAIL on retry: {e2}")
            else:
                print(f"  FAIL: {e}")
        except TimeoutError as e:
            print(f"  FAIL: No response ({e})")

    # Step 4: Return control to ECU
    print(f"\n[Step 4] Return control to ECU (DID=0x023F [00 00])")
    try:
        # Ensure extended session
        bcm.enter_extended_session()
        bcm.io_control(DID_DOOR_023F, IO_CTRL_SHORT_TERM_ADJ, [0x00, 0x00])
        print("  -> Control returned to ECU")
    except Exception as e:
        print(f"  WARNING: Return control failed: {e}")

    # Step 5: Return to default session
    print(f"\n[Step 5] Return to default session")
    try:
        bcm.return_to_default_session()
    except Exception as e:
        print(f"  WARNING: Session switch failed: {e}")

    print("\n" + "=" * 60)
    if success:
        print("UNLOCK SEQUENCE COMPLETE (at least one command succeeded)")
    else:
        print("UNLOCK SEQUENCE FAILED (no IOControl command was accepted)")
    print("=" * 60)

    return success


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Nissan Almera Turbo (N18) Door Unlock via CAN/UDS"
    )
    parser.add_argument(
        "--interface", "-i", required=True,
        help="python-can interface (slcan, socketcan, pcan, kvaser, etc.)"
    )
    parser.add_argument(
        "--channel", "-c", required=True,
        help="CAN channel (COM3, can0, PCAN_USBBUS1, etc.)"
    )
    parser.add_argument(
        "--bitrate", "-b", type=int, default=500000,
        help="CAN bitrate (default: 500000)"
    )
    parser.add_argument(
        "--method", "-m", choices=["023F", "0202", "both"], default="both",
        help="Which DID(s) to use for unlock (default: both)"
    )
    parser.add_argument(
        "--timeout", "-t", type=float, default=2.0,
        help="Response timeout in seconds (default: 2.0)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be sent without actually sending"
    )
    parser.add_argument(
        "--sniff", type=float, nargs="?", const=5.0, default=None,
        metavar="SECONDS",
        help="Sniff all CAN traffic for N seconds (default: 5) to verify bus connection"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Show all received CAN frames during unlock sequence"
    )
    parser.add_argument(
        "--tty-baudrate", type=int, default=None,
        help="Serial port baud rate for slcan adapter (default: auto)"
    )

    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN — showing CAN frames that would be sent:\n")
        print("  1. DiagSessionControl -> extended")
        print(f"     TX 0x{BCM_REQUEST_ID:03X}: [02 10 03 FF FF FF FF FF]")
        print()
        print("  2. TesterPresent")
        print(f"     TX 0x{BCM_REQUEST_ID:03X}: [02 3E 00 FF FF FF FF FF]")
        print()
        if args.method in ("0202", "both"):
            print("  3a. IOControl DID=0x0202 [00 02]")
            print(f"     TX 0x{BCM_REQUEST_ID:03X}: [06 2F 02 02 03 00 02 FF]")
            print()
        if args.method in ("023F", "both"):
            print("  3b. IOControl DID=0x023F [00 01]")
            print(f"     TX 0x{BCM_REQUEST_ID:03X}: [06 2F 02 3F 03 00 01 FF]")
            print()
        print("  4. Return control: IOControl DID=0x023F [00 00]")
        print(f"     TX 0x{BCM_REQUEST_ID:03X}: [06 2F 02 3F 03 00 00 FF]")
        print()
        print("  5. DiagSessionControl -> default")
        print(f"     TX 0x{BCM_REQUEST_ID:03X}: [02 10 01 FF FF FF FF FF]")
        return

    # --- Connect to CAN bus ---
    print(f"Connecting to CAN bus: {args.interface} / {args.channel} @ {args.bitrate}")
    bus_kwargs = dict(
        interface=args.interface,
        channel=args.channel,
        bitrate=args.bitrate,
    )
    if args.tty_baudrate and args.interface == "slcan":
        bus_kwargs["ttyBaudrate"] = args.tty_baudrate
    try:
        bus = can.Bus(**bus_kwargs)
    except Exception as e:
        print(f"ERROR: Cannot open CAN bus: {e}")
        sys.exit(1)

    print("Connected!\n")

    # --- Sniff mode: just listen and print all frames ---
    if args.sniff is not None:
        duration = args.sniff
        print(f"SNIFF MODE — listening for {duration}s on CAN bus...\n")
        print(f"{'Time':>10s}  {'CAN ID':>8s}  {'DLC':>3s}  Data")
        print("-" * 60)
        start = time.time()
        count = 0
        id_counts = {}
        try:
            while time.time() - start < duration:
                msg = bus.recv(timeout=0.5)
                if msg is not None:
                    count += 1
                    data_hex = " ".join(f"{b:02X}" for b in msg.data)
                    elapsed = time.time() - start
                    cid = f"0x{msg.arbitration_id:03X}"
                    print(f"  {elapsed:8.3f}s  {cid:>8s}  {msg.dlc:>3d}  [{data_hex}]")
                    id_counts[msg.arbitration_id] = id_counts.get(msg.arbitration_id, 0) + 1
        except KeyboardInterrupt:
            pass
        print("-" * 60)
        print(f"\nTotal frames received: {count}")
        if id_counts:
            print("\nFrames per CAN ID:")
            for cid in sorted(id_counts.keys()):
                print(f"  0x{cid:03X}: {id_counts[cid]}")
        else:
            print("\n*** NO FRAMES RECEIVED ***")
            print("Possible issues:")
            print("  1. CAN adapter not connected to vehicle")
            print("  2. Vehicle ignition is OFF (many ECUs sleep when off)")
            print("  3. Wrong bitrate (try 250000 or 500000)")
            print("  4. slcan adapter needs --tty-baudrate (try 115200 or 921600)")
            print("  5. CAN-H/CAN-L wires swapped or not connected")
        bus.shutdown()
        return

    bcm = NissanBCM(bus, timeout=args.timeout)

    # Patch _recv_response for debug mode
    if args.debug:
        _original_recv = bcm.bus.recv
        def _debug_recv(timeout=None):
            msg = _original_recv(timeout=timeout)
            if msg is not None:
                data_hex = " ".join(f"{b:02X}" for b in msg.data)
                print(f"  [DEBUG RX] 0x{msg.arbitration_id:03X} [{data_hex}]")
            return msg
        bcm.bus.recv = _debug_recv

    try:
        result = unlock_door(bcm, method=args.method)
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\nAborted by user")
        sys.exit(130)
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
