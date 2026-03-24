#!/usr/bin/env python3
"""
Nissan Almera Turbo (N18) / Versa — OBD Door Lock Device Clone

Replicates all 4 features of the original OBD door lock device:
  1. Drive Lock    — auto lock doors when speed > threshold
  2. Power Off Unlock — auto unlock doors when engine off
  3. Circular Locking  — re-lock after door opened during driving
  4. DRL (Daytime Running Lights) — auto DRL when engine running

Target ECU: BCM (Body Control Module)
  Request CAN ID:  0x745
  Response CAN ID: 0x765

Usage:
  python nissan_door_lock.py -i slcan -c COM3
  python nissan_door_lock.py -i socketcan -c can0
  python nissan_door_lock.py -i slcan -c COM3 --speed-threshold 25
  python nissan_door_lock.py -i slcan -c COM3 --no-drl
  python nissan_door_lock.py --dry-run -i slcan -c COM3
"""

import argparse
import threading
import time
import sys

try:
    import can
except ImportError:
    print("ERROR: python-can not installed. Run: pip install python-can")
    sys.exit(1)


# ==========================================================================
# Constants
# ==========================================================================

BCM_REQ  = 0x745
BCM_RESP = 0x765
OBD_BROADCAST = 0x7DF

SID_DIAG_SESSION  = 0x10
SID_READ_DATA     = 0x22
SID_IO_CONTROL    = 0x2F
SID_TESTER_PRESENT = 0x3E
SID_NEG_RESPONSE  = 0x7F

SESSION_DEFAULT  = 0x01
SESSION_EXTENDED = 0x03

IO_SHORT_TERM_ADJ = 0x03

DID_DOOR_LOCK = 0x023F   # door lock actuator
DID_DRL       = 0x0202   # daytime running lights

DOOR_UNLOCK  = [0x00, 0x01]
DOOR_LOCK    = [0x00, 0x02]  # inferred — needs testing
RETURN_TO_ECU = [0x00, 0x00]
DRL_ON       = [0x00, 0x02]
DRL_OFF      = [0x00, 0x00]  # inferred — needs testing

NRC_RESPONSE_PENDING = 0x78
NRC_WRONG_SESSION    = 0x7F

SPEED_PID = 0x0D
DID_DOOR_STATUS = 0x0109
DID_ENGINE_1    = 0x1301
DID_ENGINE_2    = 0x1304


# ==========================================================================
# UDS Communication Layer
# ==========================================================================

class UDSError(Exception):
    def __init__(self, service, nrc):
        self.service = service
        self.nrc = nrc
        names = {
            0x10: "generalReject", 0x11: "serviceNotSupported",
            0x12: "subFunctionNotSupported", 0x13: "incorrectMessageLength",
            0x22: "conditionsNotCorrect", 0x31: "requestOutOfRange",
            0x33: "securityAccessDenied", 0x78: "responsePending",
            0x7E: "subFuncNotSupportedInSession",
            0x7F: "serviceNotSupportedInActiveSession",
        }
        super().__init__(f"NRC=0x{nrc:02X} ({names.get(nrc, '?')}) for SID 0x{service:02X}")


class BCMClient:
    """UDS Single Frame communication with BCM."""

    def __init__(self, bus, req_id=BCM_REQ, resp_id=BCM_RESP, timeout=2.0, verbose=True):
        self.bus = bus
        self.req_id = req_id
        self.resp_id = resp_id
        self.timeout = timeout
        self.verbose = verbose
        self._lock = threading.Lock()

    def log(self, msg):
        if self.verbose:
            print(f"  [BCM] {msg}")

    def send_sf(self, payload, arb_id=None):
        """Send ISO-TP Single Frame."""
        if arb_id is None:
            arb_id = self.req_id
        n = len(payload)
        data = [n] + list(payload) + [0xFF] * (7 - n)
        self.bus.send(can.Message(arbitration_id=arb_id, data=data, is_extended_id=False))

    def recv_sf(self, expected_sid=None, resp_id=None, timeout=None):
        """Receive single frame response, handling NRC 0x78 (pending)."""
        if resp_id is None:
            resp_id = self.resp_id
        if timeout is None:
            timeout = self.timeout
        deadline = time.time() + timeout

        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            msg = self.bus.recv(timeout=min(remaining, 0.5))
            if msg is None or msg.arbitration_id != resp_id:
                continue
            data = list(msg.data)
            if (data[0] >> 4) != 0:
                continue
            length = data[0] & 0x0F
            payload = data[1:1+length]
            if not payload:
                continue
            sid = payload[0]
            if sid == SID_NEG_RESPONSE and len(payload) >= 3:
                if payload[2] == NRC_RESPONSE_PENDING:
                    deadline = time.time() + 5.0
                    continue
                raise UDSError(payload[1], payload[2])
            if expected_sid is not None and sid != (expected_sid + 0x40):
                continue
            return payload

        raise TimeoutError(f"No response from 0x{resp_id:03X}")

    def enter_extended_session(self):
        with self._lock:
            self.log("DiagSession -> extended")
            self.send_sf([SID_DIAG_SESSION, SESSION_EXTENDED])
            self.recv_sf(expected_sid=SID_DIAG_SESSION)

    def return_default_session(self):
        with self._lock:
            self.log("DiagSession -> default")
            self.send_sf([SID_DIAG_SESSION, SESSION_DEFAULT])
            self.recv_sf(expected_sid=SID_DIAG_SESSION)

    def tester_present(self):
        with self._lock:
            self.send_sf([SID_TESTER_PRESENT, 0x00])
            self.recv_sf(expected_sid=SID_TESTER_PRESENT)

    def io_control(self, did, state):
        """Send IOControlByIdentifier with shortTermAdjustment + auto session retry."""
        with self._lock:
            did_hi = (did >> 8) & 0xFF
            did_lo = did & 0xFF
            payload = [SID_IO_CONTROL, did_hi, did_lo, IO_SHORT_TERM_ADJ] + list(state)
            self.send_sf(payload)
            try:
                return self.recv_sf(expected_sid=SID_IO_CONTROL)
            except UDSError as e:
                if e.nrc == NRC_WRONG_SESSION:
                    self.log("Wrong session — re-entering extended")
                    self.send_sf([SID_DIAG_SESSION, SESSION_EXTENDED])
                    self.recv_sf(expected_sid=SID_DIAG_SESSION)
                    self.send_sf(payload)
                    return self.recv_sf(expected_sid=SID_IO_CONTROL)
                raise

    def read_obd_speed(self):
        """Send OBD-II PID 0x0D (vehicle speed) via broadcast 0x7DF.
        Returns speed in km/h or None on failure."""
        with self._lock:
            self.send_sf([0x02, 0x01, SPEED_PID, 0x00, 0x00, 0x00, 0x00], arb_id=OBD_BROADCAST)
            # Response could come from any ECU, typically 0x7E8
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                msg = self.bus.recv(timeout=0.5)
                if msg is None:
                    continue
                data = list(msg.data)
                if (data[0] & 0x0F) >= 2 and len(data) >= 4:
                    if data[1] == 0x41 and data[2] == SPEED_PID:
                        return data[3]
            return None

    def read_data(self, did, resp_id=None):
        """ReadDataByIdentifier. Returns first frame payload or None."""
        with self._lock:
            did_hi = (did >> 8) & 0xFF
            did_lo = did & 0xFF
            self.send_sf([SID_READ_DATA, did_hi, did_lo])
            try:
                return self.recv_sf(expected_sid=SID_READ_DATA, resp_id=resp_id)
            except (UDSError, TimeoutError):
                return None


# ==========================================================================
# Feature Implementation
# ==========================================================================

class NissanDoorLockDevice:
    """
    Replicates the 4-feature OBD door lock device.

    State machine:
      - Monitors speed, engine status, door status in a loop
      - Triggers lock/unlock/DRL based on conditions
    """

    def __init__(self, bcm, speed_threshold=25, unlock_delay=3.0,
                 enable_drl=True, verbose=True):
        self.bcm = bcm
        self.speed_threshold = speed_threshold
        self.unlock_delay = unlock_delay
        self.enable_drl = enable_drl
        self.verbose = verbose

        # State
        self.speed = 0
        self.engine_running = False
        self.doors_locked = False
        self.drl_active = False
        self.door_was_opened = False
        self.engine_was_running = False
        self.drive_lock_armed = True  # can trigger drive lock

        self._running = False

    def log(self, msg):
        if self.verbose:
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] {msg}")

    # -- Actuator commands --

    def _do_lock(self):
        """Lock all doors."""
        self.log(">>> LOCKING DOORS")
        try:
            self.bcm.enter_extended_session()
            self.bcm.tester_present()
            self.bcm.io_control(DID_DOOR_LOCK, DOOR_LOCK)
            self.bcm.io_control(DID_DOOR_LOCK, RETURN_TO_ECU)
            self.bcm.return_default_session()
            self.doors_locked = True
            self.log(">>> DOORS LOCKED OK")
            return True
        except Exception as e:
            self.log(f"!!! LOCK FAILED: {e}")
            self._safe_return_default()
            return False

    def _do_unlock(self):
        """Unlock all doors."""
        self.log(">>> UNLOCKING DOORS")
        try:
            self.bcm.enter_extended_session()
            self.bcm.tester_present()
            self.bcm.io_control(DID_DOOR_LOCK, DOOR_UNLOCK)
            self.bcm.io_control(DID_DOOR_LOCK, RETURN_TO_ECU)
            self.bcm.return_default_session()
            self.doors_locked = False
            self.log(">>> DOORS UNLOCKED OK")
            return True
        except Exception as e:
            self.log(f"!!! UNLOCK FAILED: {e}")
            self._safe_return_default()
            return False

    def _do_drl_on(self):
        """Turn on DRL."""
        self.log(">>> DRL ON")
        try:
            self.bcm.enter_extended_session()
            self.bcm.io_control(DID_DRL, DRL_ON)
            self.bcm.return_default_session()
            self.drl_active = True
            return True
        except Exception as e:
            self.log(f"!!! DRL ON FAILED: {e}")
            self._safe_return_default()
            return False

    def _do_drl_off(self):
        """Turn off DRL."""
        self.log(">>> DRL OFF")
        try:
            self.bcm.enter_extended_session()
            self.bcm.io_control(DID_DRL, DRL_OFF)
            self.bcm.io_control(DID_DRL, RETURN_TO_ECU)
            self.bcm.return_default_session()
            self.drl_active = False
            return True
        except Exception as e:
            self.log(f"!!! DRL OFF FAILED: {e}")
            self._safe_return_default()
            return False

    def _safe_return_default(self):
        """Best-effort return to default session."""
        try:
            self.bcm.return_default_session()
        except Exception:
            pass

    # -- Sensor reads --

    def _poll_speed(self):
        speed = self.bcm.read_obd_speed()
        if speed is not None:
            self.speed = speed

    def _poll_engine(self):
        """Try to determine engine status from ECU responses.
        Heuristic: if 0x7E1 responds to ReadDataByID, engine ECU is alive = engine on."""
        # The original device polls DID 0x1301 on 0x7E1.
        # If we get a response, engine is likely running.
        # We send on 0x7E1 and expect response on 0x7E9 (standard offset +8)
        resp = self.bcm.read_data(DID_ENGINE_1, resp_id=None)
        # Fallback: use speed > 0 as engine running indicator
        if resp is not None:
            self.engine_running = True
        elif self.speed > 0:
            self.engine_running = True
        else:
            # No response + speed 0 = likely engine off
            self.engine_running = False

    def _poll_door_status(self):
        """Read door status. The 18-byte response contains door open/close bits.
        Since we don't know the exact bit layout, we track if the response changes
        between polls to detect a door event."""
        resp = self.bcm.read_data(DID_DOOR_STATUS)
        # TODO: decode specific bits when mapping is known
        # For now, we can't reliably detect door open from this data
        return resp

    # -- Main loop --

    def run(self):
        """Main event loop. Press Ctrl+C to stop."""
        self._running = True
        self.log("=" * 50)
        self.log("NISSAN DOOR LOCK DEVICE — STARTED")
        self.log(f"  Speed threshold: {self.speed_threshold} km/h")
        self.log(f"  Unlock delay:    {self.unlock_delay}s after engine off")
        self.log(f"  DRL:             {'enabled' if self.enable_drl else 'disabled'}")
        self.log("=" * 50)

        engine_off_time = None

        try:
            # Initial session setup
            try:
                self.bcm.enter_extended_session()
                self.bcm.return_default_session()
                self.log("BCM communication OK")
            except Exception as e:
                self.log(f"WARNING: Initial BCM handshake failed: {e}")

            while self._running:
                loop_start = time.time()

                # -- Poll sensors --
                try:
                    self._poll_speed()
                except Exception:
                    pass

                try:
                    self._poll_engine()
                except Exception:
                    pass

                try:
                    self._poll_door_status()
                except Exception:
                    pass

                # Keep session alive
                try:
                    self.bcm.tester_present()
                except Exception:
                    pass

                self.log(f"  speed={self.speed}km/h engine={'ON' if self.engine_running else 'OFF'} "
                         f"locked={self.doors_locked} drl={self.drl_active}")

                # ======================================================
                # Feature 1: Drive Lock — lock when speed > threshold
                # ======================================================
                if (self.engine_running
                        and self.speed >= self.speed_threshold
                        and not self.doors_locked
                        and self.drive_lock_armed):
                    self.log("[Feature 1] Drive Lock — speed >= threshold")
                    if self._do_lock():
                        self.drive_lock_armed = False  # don't re-lock until re-armed

                # ======================================================
                # Feature 2: Power Off Unlock — unlock after engine off
                # ======================================================
                if self.engine_was_running and not self.engine_running:
                    # Engine just turned off
                    engine_off_time = time.time()
                    self.log("[Feature 2] Engine OFF detected — will unlock in "
                             f"{self.unlock_delay}s")

                if (engine_off_time is not None
                        and not self.engine_running
                        and time.time() - engine_off_time >= self.unlock_delay):
                    self.log("[Feature 2] Power Off Unlock — unlocking doors")
                    self._do_unlock()
                    engine_off_time = None

                    # Also turn off DRL when engine off
                    if self.drl_active:
                        self.log("[Feature 4] Engine OFF — turning off DRL")
                        self._do_drl_off()

                # If engine turns back on, cancel pending unlock
                if engine_off_time is not None and self.engine_running:
                    self.log("[Feature 2] Engine back ON — cancelling unlock")
                    engine_off_time = None

                # ======================================================
                # Feature 3: Circular Locking — re-lock after door event
                # ======================================================
                # Re-arm drive lock when speed drops below threshold
                # (simulates: stopped -> door opened -> door closed -> driving again)
                if self.speed < self.speed_threshold and self.doors_locked:
                    # At low speed with doors locked = someone might open a door
                    self.drive_lock_armed = True

                # If doors become unlocked while engine is running and we were locked
                # that means someone opened a door (or used key fob).
                # Re-arm so next time we hit speed threshold, we lock again.
                if self.engine_running and not self.doors_locked:
                    self.drive_lock_armed = True

                # ======================================================
                # Feature 4: DRL — turn on when engine is running
                # ======================================================
                if self.enable_drl:
                    if self.engine_running and not self.drl_active:
                        self.log("[Feature 4] Engine ON — turning on DRL")
                        self._do_drl_on()

                # Track previous engine state
                self.engine_was_running = self.engine_running

                # Poll interval — match original device (~0.5s between commands)
                elapsed = time.time() - loop_start
                sleep_time = max(0, 0.5 - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            self.log("\nStopping...")
        finally:
            self._running = False
            self.log("Cleaning up...")
            # Return control to ECU for both actuators
            try:
                self.bcm.enter_extended_session()
                self.bcm.io_control(DID_DOOR_LOCK, RETURN_TO_ECU)
                self.bcm.io_control(DID_DRL, RETURN_TO_ECU)
                self.bcm.return_default_session()
            except Exception:
                pass
            self.log("STOPPED")

    def stop(self):
        self._running = False


# ==========================================================================
# Single-shot commands (for testing)
# ==========================================================================

def cmd_unlock(bcm):
    print("=== DOOR UNLOCK ===")
    bcm.enter_extended_session()
    bcm.tester_present()
    bcm.io_control(DID_DOOR_LOCK, DOOR_UNLOCK)
    bcm.io_control(DID_DOOR_LOCK, RETURN_TO_ECU)
    bcm.return_default_session()
    print("=== DONE ===")


def cmd_lock(bcm):
    print("=== DOOR LOCK ===")
    bcm.enter_extended_session()
    bcm.tester_present()
    bcm.io_control(DID_DOOR_LOCK, DOOR_LOCK)
    bcm.io_control(DID_DOOR_LOCK, RETURN_TO_ECU)
    bcm.return_default_session()
    print("=== DONE ===")


def cmd_drl_on(bcm):
    print("=== DRL ON ===")
    bcm.enter_extended_session()
    bcm.io_control(DID_DRL, DRL_ON)
    bcm.return_default_session()
    print("=== DONE ===")


def cmd_drl_off(bcm):
    print("=== DRL OFF ===")
    bcm.enter_extended_session()
    bcm.io_control(DID_DRL, DRL_OFF)
    bcm.io_control(DID_DRL, RETURN_TO_ECU)
    bcm.return_default_session()
    print("=== DONE ===")


def cmd_status(bcm):
    print("=== READ STATUS ===")
    speed = bcm.read_obd_speed()
    print(f"  Vehicle speed: {speed} km/h" if speed is not None else "  Vehicle speed: N/A")
    door = bcm.read_data(DID_DOOR_STATUS)
    if door:
        door_hex = " ".join(f"{b:02X}" for b in door)
        print(f"  Door status (raw): [{door_hex}]")
    else:
        print("  Door status: N/A")
    print("=== DONE ===")


# ==========================================================================
# Main
# ==========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Nissan Almera Turbo (N18) — OBD Door Lock Device Clone",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands (--cmd):
  run      Run full device emulation with all 4 features (default)
  unlock   Single-shot: unlock doors
  lock     Single-shot: lock doors
  drl-on   Single-shot: turn on DRL
  drl-off  Single-shot: turn off DRL
  status   Read current vehicle speed and door status

examples:
  python nissan_door_lock.py -i slcan -c COM3
  python nissan_door_lock.py -i slcan -c COM3 --cmd unlock
  python nissan_door_lock.py -i slcan -c COM3 --cmd lock
  python nissan_door_lock.py -i slcan -c COM3 --no-drl --speed-threshold 30
  python nissan_door_lock.py --dry-run -i slcan -c COM3
""")
    parser.add_argument("-i", "--interface", required=True,
                        help="python-can interface (slcan, socketcan, pcan, etc.)")
    parser.add_argument("-c", "--channel", required=True,
                        help="CAN channel (COM3, can0, PCAN_USBBUS1, etc.)")
    parser.add_argument("-b", "--bitrate", type=int, default=500000)
    parser.add_argument("--cmd", default="run",
                        choices=["run", "unlock", "lock", "drl-on", "drl-off", "status"])
    parser.add_argument("--speed-threshold", type=int, default=25,
                        help="Speed (km/h) to trigger auto-lock (default: 25)")
    parser.add_argument("--unlock-delay", type=float, default=3.0,
                        help="Seconds after engine off before auto-unlock (default: 3.0)")
    parser.add_argument("--no-drl", action="store_true",
                        help="Disable DRL feature")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show CAN frames without sending")

    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN — CAN frames used by this device:\n")
        print("  Lock doors:")
        print("    0x745: [02 10 03 FF FF FF FF FF]  DiagSession -> extended")
        print("    0x745: [02 3E 00 FF FF FF FF FF]  TesterPresent")
        print("    0x745: [06 2F 02 3F 03 00 02 FF]  IOControl DID=0x023F [00 02] = LOCK")
        print("    0x745: [06 2F 02 3F 03 00 00 FF]  IOControl DID=0x023F [00 00] = return")
        print("    0x745: [02 10 01 FF FF FF FF FF]  DiagSession -> default")
        print()
        print("  Unlock doors:")
        print("    0x745: [02 10 03 FF FF FF FF FF]  DiagSession -> extended")
        print("    0x745: [02 3E 00 FF FF FF FF FF]  TesterPresent")
        print("    0x745: [06 2F 02 3F 03 00 01 FF]  IOControl DID=0x023F [00 01] = UNLOCK")
        print("    0x745: [06 2F 02 3F 03 00 00 FF]  IOControl DID=0x023F [00 00] = return")
        print("    0x745: [02 10 01 FF FF FF FF FF]  DiagSession -> default")
        print()
        print("  DRL on:")
        print("    0x745: [02 10 03 FF FF FF FF FF]  DiagSession -> extended")
        print("    0x745: [06 2F 02 02 03 00 02 FF]  IOControl DID=0x0202 [00 02] = DRL ON")
        print("    0x745: [02 10 01 FF FF FF FF FF]  DiagSession -> default")
        print()
        print("  Polling (every 0.5s):")
        print("    0x7DF: [02 01 0D 00 00 00 00 00]  OBD-II read vehicle speed")
        print("    0x745: [03 22 01 09 FF FF FF FF]  ReadDataByID door status")
        print("    0x745: [02 3E 00 FF FF FF FF FF]  TesterPresent")
        print()
        print(f"  NOTE: DOOR_LOCK [00 02] is inferred and not yet confirmed by capture.")
        print(f"        DRL_OFF  [00 00] is inferred and not yet confirmed by capture.")
        return

    verbose = not args.quiet
    print(f"Connecting: {args.interface} / {args.channel} @ {args.bitrate}")
    try:
        bus = can.Bus(interface=args.interface, channel=args.channel, bitrate=args.bitrate)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    bcm = BCMClient(bus, timeout=args.timeout, verbose=verbose)

    try:
        if args.cmd == "run":
            device = NissanDoorLockDevice(
                bcm,
                speed_threshold=args.speed_threshold,
                unlock_delay=args.unlock_delay,
                enable_drl=not args.no_drl,
                verbose=verbose,
            )
            device.run()
        elif args.cmd == "unlock":
            cmd_unlock(bcm)
        elif args.cmd == "lock":
            cmd_lock(bcm)
        elif args.cmd == "drl-on":
            cmd_drl_on(bcm)
        elif args.cmd == "drl-off":
            cmd_drl_off(bcm)
        elif args.cmd == "status":
            cmd_status(bcm)
    except KeyboardInterrupt:
        print("\nAborted")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
