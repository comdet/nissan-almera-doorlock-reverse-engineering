#!/usr/bin/env python3
"""
Live monitor for verifying brake + gear decoding on the actual car.

Polls the firmware's `dump` command every couple of seconds, parses the raw
hex output for the four DIDs we care about, and prints a one-line snapshot
with the most relevant bytes highlighted. Bytes that changed since the last
poll are flagged so it's obvious what's actually moving when you press
the brake / shift gear / turn the key.

Run while connected to the ESP32-C3 over USB (Car Companion firmware must
already be flashed, no modifications). Walk through the test scenarios from
the verification plan, watch which bytes move.

Usage:
    python3 verify_brake_gear.py
    python3 verify_brake_gear.py --port /dev/cu.usbmodem1101 --interval 2.0

Press Ctrl+C to stop.
"""

import argparse
import glob
import re
import sys
import time
from datetime import datetime

try:
    import serial
except ImportError:
    print("pip install pyserial", file=sys.stderr)
    sys.exit(1)


# ANSI colors — fine on most terminals (Terminal.app, iTerm, modern Linux)
C_RESET   = "\033[0m"
C_DIM     = "\033[2m"
C_BOLD    = "\033[1m"
C_RED     = "\033[31m"
C_GREEN   = "\033[32m"
C_YELLOW  = "\033[33m"
C_CYAN    = "\033[36m"
C_MAGENTA = "\033[35m"

# Parse a "len=NN: HH HH HH ..." style row out of the dump output.
LINE_RE = re.compile(r"^(.+?)\s+len=\s*(\d+):\s*([0-9A-Fa-f\s]+)$")


def find_port():
    candidates = glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/ttyACM*")
    return candidates[0] if candidates else None


def parse_dump(text):
    """Pull out {did_name: [bytes]} from a single `dump` block."""
    out = {}
    for line in text.split("\n"):
        line = line.rstrip()
        m = LINE_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        hex_parts = m.group(3).split()
        try:
            bytes_arr = [int(h, 16) for h in hex_parts]
        except ValueError:
            continue
        out[name] = bytes_arr
    return out


def get_byte(parsed, did_name, idx):
    arr = parsed.get(did_name)
    if arr is None or idx >= len(arr):
        return None
    return arr[idx]


def fmt_byte(cur, prev, width=2):
    """Format a byte with highlight if changed."""
    if cur is None:
        return C_DIM + "--" + C_RESET
    s = f"{cur:02X}"
    if prev is not None and cur != prev:
        s = C_YELLOW + C_BOLD + s + C_RESET + C_RED + "!" + C_RESET
    else:
        s = s + " "
    return s


def fmt_gear(b):
    if b is None:
        return C_DIM + "--" + C_RESET
    label = {0x10: "P", 0x20: "R", 0x40: "N", 0x80: "D", 0x08: "L"}.get(b)
    if label is None:
        return f"{b:02X}?"
    return f"{b:02X}/{label}"


def fmt_engine_status(b):
    if b is None:
        return C_DIM + "--" + C_RESET
    label = {0x02: "OFF", 0x06: "RUN"}.get(b, "??")
    return f"{b:02X}/{label}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default=None, help="Serial port (auto-detect if omitted)")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="Minimum seconds between polls (default 2.0)")
    ap.add_argument("--show-full-bcm", action="store_true",
                    help="Also print the full BCM 0x0109 hex on every line")
    args = ap.parse_args()

    port = args.port or find_port()
    if not port:
        print("No serial port found. Use --port", file=sys.stderr)
        sys.exit(1)

    print(f"Opening {port} ...")
    ser = serial.Serial(port, 115200, timeout=2)
    time.sleep(0.5)
    ser.reset_input_buffer()

    print()
    print(C_BOLD + "Brake / Gear Verification Monitor" + C_RESET)
    print()
    print(C_BOLD + "Columns:" + C_RESET)
    print(f"  {C_CYAN}G{C_RESET}    gear from DID 0x1301 byte 3   (0x10=P 0x20=R 0x40=N 0x80=D 0x08=L 0x01=idle)")
    print(f"  {C_CYAN}E{C_RESET}    engine status DID 0x1304 b3   (0x02=off, 0x06=running)")
    print(f"  {C_CYAN}Br{C_RESET}   brake-pedal raw DID 0x0109 b17   ★ KEY FIELD ★")
    print(f"  {C_CYAN}b6{C_RESET}   doors bitmask DID 0x0109 b6   (for context — should follow door state)")
    print(f"  {C_CYAN}b8{C_RESET}   lock DID 0x0109 b8   (0x00=locked, 0x10=unlocked)")
    print(f"  {C_CYAN}HB{C_RESET}   handbrake DID 0x0E07 b19   (0x10=ON, 0x00=OFF)")
    print(f"  {C_YELLOW}YY!{C_RESET}  yellow value with ! = changed vs previous poll")
    print()
    print("Action plan — perform each, watch which bytes flip:")
    print("  1. ACC on, engine off, in P, no brake")
    print("  2. Press brake firmly (still parked, engine off)")
    print("  3. Start engine, idle in P, brake released")
    print("  4. Brake + shift to D + release brake (still parked)")
    print("  5. Drive at ~20 km/h, no brake")
    print("  6. Drive at ~20 km/h, *light braking* to slow")
    print("  7. Come to a full stop, brake still pressed")
    print("  8. Brake released (engine still on, in D)")
    print("  9. Brake + shift to P, brake still pressed")
    print(" 10. Brake released, engine still on, P")
    print(" 11. Turn key OFF — watch how G and E behave over 30+ seconds")
    print()
    print("Ctrl+C to stop.")
    print()

    prev_parsed = {}
    start = time.time()

    try:
        while True:
            t_poll_start = time.time()
            ser.reset_input_buffer()
            ser.write(b"dump\r\n")

            # Wait for END DUMP marker, or 10s timeout (worst case all DIDs fail)
            buf = ""
            deadline = time.time() + 10
            while time.time() < deadline:
                n = ser.in_waiting
                if n:
                    chunk = ser.read(n).decode("utf-8", errors="replace")
                    buf += chunk
                    if "END DUMP" in buf:
                        break
                time.sleep(0.05)

            # Slice out the DUMP block
            start_idx = buf.find("DID DUMP")
            end_idx   = buf.find("END DUMP")
            block = buf[start_idx:end_idx] if (start_idx >= 0 and end_idx > start_idx) else buf

            parsed = parse_dump(block)

            # Pull the bytes we care about
            ts = datetime.now().strftime("%H:%M:%S")
            elapsed = int(time.time() - start)

            g    = get_byte(parsed, "Engine 0x1301", 3)
            e    = get_byte(parsed, "Engine 0x1304", 3)
            br   = get_byte(parsed, "BCM 0x0109",    17)
            b6   = get_byte(parsed, "BCM 0x0109",    6)
            b8   = get_byte(parsed, "BCM 0x0109",    8)
            hb   = get_byte(parsed, "Light 0x0E07",  19)

            pg   = get_byte(prev_parsed, "Engine 0x1301", 3)
            pe   = get_byte(prev_parsed, "Engine 0x1304", 3)
            pbr  = get_byte(prev_parsed, "BCM 0x0109",    17)
            pb6  = get_byte(prev_parsed, "BCM 0x0109",    6)
            pb8  = get_byte(prev_parsed, "BCM 0x0109",    8)
            phb  = get_byte(prev_parsed, "Light 0x0E07",  19)

            # Highlight gear+engine labels separately (they have helpful tags)
            g_changed = (pg is not None and g != pg)
            e_changed = (pe is not None and e != pe)

            g_str = fmt_gear(g) + (C_RED + "!" + C_RESET if g_changed else "")
            e_str = fmt_engine_status(e) + (C_RED + "!" + C_RESET if e_changed else "")

            print(
                f"[{ts}|+{elapsed:4d}s] "
                f"G={g_str:18}  "
                f"E={e_str:18}  "
                f"Br={fmt_byte(br, pbr)}  "
                f"b6={fmt_byte(b6, pb6)}  "
                f"b8={fmt_byte(b8, pb8)}  "
                f"HB={fmt_byte(hb, phb)}"
            )

            if args.show_full_bcm:
                bcm = parsed.get("BCM 0x0109", [])
                if bcm:
                    hex_str = " ".join(f"{b:02X}" for b in bcm)
                    print(f"           BCM full: {C_DIM}{hex_str}{C_RESET}")

            prev_parsed = parsed

            # Honour the interval (minus the time the dump itself already took)
            slept = time.time() - t_poll_start
            if slept < args.interval:
                time.sleep(args.interval - slept)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
