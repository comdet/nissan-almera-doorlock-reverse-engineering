#!/usr/bin/env python3
"""Send 'portal' to firmware and capture ~12s of Serial output."""
import serial
import sys
import time
import threading


def reader(ser, stop_evt):
    while not stop_evt.is_set():
        try:
            data = ser.read(4096)
            if data:
                sys.stdout.write(data.decode('utf-8', errors='replace'))
                sys.stdout.flush()
        except Exception as e:
            print(f"\n[reader] {e}")
            break


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM30"
    ser = serial.Serial(port, 115200, timeout=0.2)
    time.sleep(0.5)
    ser.reset_input_buffer()

    stop_evt = threading.Event()
    t = threading.Thread(target=reader, args=(ser, stop_evt), daemon=True)
    t.start()

    print("\n>>> portal\n")
    ser.write(b"portal\n")
    ser.flush()
    # USB CDC drops on reboot — re-open after a moment
    time.sleep(2)
    try:
        ser.close()
    except Exception:
        pass

    # Reconnect to capture boot output
    for _ in range(20):
        try:
            ser = serial.Serial(port, 115200, timeout=0.2)
            break
        except Exception:
            time.sleep(0.3)

    stop_evt.clear()
    t2 = threading.Thread(target=reader, args=(ser, stop_evt), daemon=True)
    t2.start()

    time.sleep(10)
    stop_evt.set()
    ser.close()


if __name__ == "__main__":
    main()
