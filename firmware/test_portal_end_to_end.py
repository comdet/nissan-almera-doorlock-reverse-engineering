#!/usr/bin/env python3
"""End-to-end test of the config portal:
  1. send 'portal' over serial
  2. verify ESP32 reboots into config mode (AP up, URL shown)
  3. connect a separate WiFi-capable host? — out of scope here.
     Instead we just observe the serial output and check that pressing reset
     (which is what a real user would do after saving) brings us back to
     normal mode.
"""
import serial
import sys
import time
import threading

lines = []
lock = threading.Lock()


def reader(ser, stop_evt):
    buf = b""
    while not stop_evt.is_set():
        try:
            data = ser.read(256)
            if data:
                sys.stdout.write(data.decode('utf-8', errors='replace'))
                sys.stdout.flush()
                buf += data
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    with lock:
                        lines.append(line.decode('utf-8', errors='replace').rstrip())
        except Exception:
            break


def open_with_retry(port, retries=20):
    for _ in range(retries):
        try:
            return serial.Serial(port, 115200, timeout=0.2)
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("port not available")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM30"
    ser = open_with_retry(port)
    time.sleep(0.5)
    ser.reset_input_buffer()

    stop_evt = threading.Event()
    t = threading.Thread(target=reader, args=(ser, stop_evt), daemon=True)
    t.start()

    print("\n>>> portal\n")
    ser.write(b"portal\n")
    ser.flush()
    time.sleep(2)
    stop_evt.set()
    ser.close()

    # Reconnect for boot output (portal mode)
    ser = open_with_retry(port)
    stop_evt = threading.Event()
    t = threading.Thread(target=reader, args=(ser, stop_evt), daemon=True)
    t.start()
    time.sleep(5)
    stop_evt.set()
    ser.close()

    portal_up = any("CONFIG PORTAL MODE" in l for l in lines)
    ap_ok     = any("AP start : ok" in l for l in lines)
    url_shown = any("URL" in l and "192.168.4.1" in l for l in lines)
    print("\n--- check ---")
    print(f"portal_up = {portal_up}")
    print(f"ap_ok     = {ap_ok}")
    print(f"url_shown = {url_shown}")

    # Reboot to clear portal mode (flag already cleared by run() at entry)
    print("\n--- reboot to confirm normal mode resumes ---")
    ser = open_with_retry(port)
    # The firmware doesn't respond to serial input in portal mode, so we use
    # the DTR pulse trick to reset over USB CDC.
    try:
        ser.setDTR(False); time.sleep(0.1); ser.setDTR(True)
    except Exception:
        pass
    stop_evt = threading.Event()
    lines.clear()
    t = threading.Thread(target=reader, args=(ser, stop_evt), daemon=True)
    t.start()
    time.sleep(6)
    stop_evt.set()
    ser.close()

    saw_twai = any("TWAI ready" in l for l in lines)
    saw_help = any("commands" in l for l in lines)
    in_portal_again = any("CONFIG PORTAL" in l for l in lines)
    print("\n--- check ---")
    print(f"twai_ready_after_reset = {saw_twai}")
    print(f"help_after_reset       = {saw_help}")
    print(f"still_in_portal        = {in_portal_again}  (expect False)")


if __name__ == "__main__":
    main()
