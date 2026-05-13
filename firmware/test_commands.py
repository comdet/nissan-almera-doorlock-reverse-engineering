#!/usr/bin/env python3
"""Send a fixed test sequence to the firmware on COM30 and print everything received.

Each line is sent with a 1s gap. Total run ~30s. Useful for verifying
serial_cmd / json_protocol / nvs_config without the car attached.
"""
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


COMMANDS = [
    ("help", 1.0),
    ("status", 1.5),
    ("config", 1.0),
    ("config auto_lock false", 0.5),
    ("config lock_speed 25", 0.5),
    ("config", 0.5),
    ("json on", 0.5),
    ("status", 2.5),
    ("json off", 0.5),
    ("lock", 1.0),
    ("unlock", 1.0),
    ("drl on", 1.0),
    ("drl off", 1.0),
    ('{"cmd":"refresh"}', 1.0),
    ('{"cmd":"config","auto_lock":true,"lock_speed":20}', 0.5),
    ("config", 0.5),
    ("save", 0.5),
    ("wifi info", 1.0),
]


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM30"
    print(f"opening {port}...")
    ser = serial.Serial(port, 115200, timeout=0.2)
    time.sleep(0.5)
    ser.reset_input_buffer()

    stop_evt = threading.Event()
    t = threading.Thread(target=reader, args=(ser, stop_evt), daemon=True)
    t.start()

    print("\n--- sending command sequence ---\n")
    for cmd, delay in COMMANDS:
        print(f"\n>>> {cmd}\n")
        ser.write((cmd + "\n").encode())
        ser.flush()
        time.sleep(delay)

    # tail a bit more so async snapshots show
    time.sleep(3)
    stop_evt.set()
    ser.close()


if __name__ == "__main__":
    main()
