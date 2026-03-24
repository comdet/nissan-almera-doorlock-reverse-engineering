#!/usr/bin/env python3
"""
Parse CAN frames from decoded Saleae Logic export (doorunlock3.txt).
Streams the file line-by-line to handle large files (63 MB+).

Output:
  - Total frames found (including empty/idle)
  - Valid frames (non-zero ID)
  - Empty/idle frames (ID=0, DLC=0)
  - Skipped bit-level lines
  - Per-ID breakdown with data payloads
"""

import re
import sys
from collections import defaultdict

INPUT_FILE = "doorunlock3.txt"

# Regex for a Fields line
# e.g. "192392400-192392447 CAN: Fields: Start of frame"
# e.g. "192393362-192393362 CAN: Fields: Data length code: 8"
FIELDS_RE = re.compile(
    r"^(\d+)-(\d+)\s+CAN:\s+Fields:\s+(.+)$"
)
BITS_RE = re.compile(r"CAN:\s+Bits:")


def parse_field(field_str):
    """Parse a field string like 'Identifier: 1868 (0x74c)' or 'Start of frame'."""
    if ":" in field_str:
        key, _, value = field_str.partition(":")
        return key.strip(), value.strip()
    return field_str.strip(), None


def extract_frame_info(frame_lines):
    """Extract structured info from a list of (start, end, field_key, field_value) tuples."""
    info = {
        "timestamp_start": frame_lines[0][0],
        "timestamp_end": frame_lines[-1][1],
        "identifier_raw": None,
        "identifier_hex": None,
        "dlc": 0,
        "data_bytes": [],
        "crc": None,
        "rtr": None,
        "ide": None,
    }

    for start, end, key, value in frame_lines:
        if key == "Identifier":
            # e.g. "1868 (0x74c)"
            m = re.search(r"\(0x([0-9a-fA-F]+)\)", value)
            if m:
                info["identifier_hex"] = m.group(1)
                info["identifier_raw"] = int(m.group(1), 16)
            else:
                # fallback: try parsing as int
                try:
                    info["identifier_raw"] = int(value.split()[0])
                    info["identifier_hex"] = hex(info["identifier_raw"])[2:]
                except ValueError:
                    pass
        elif key == "Data length code":
            try:
                info["dlc"] = int(value)
            except ValueError:
                pass
        elif key.startswith("Data byte"):
            info["data_bytes"].append(value)
        elif key == "CRC-15 sequence":
            info["crc"] = value
        elif key == "Remote transmission request":
            info["rtr"] = value
        elif key == "Identifier extension bit":
            info["ide"] = value

    return info


def main():
    total_lines = 0
    bit_lines = 0
    field_lines = 0
    other_lines = 0

    total_frames = 0
    empty_frames = 0  # ID=0, DLC=0
    valid_frames = 0

    # Per-ID stats: id_hex -> list of data payloads
    id_stats = defaultdict(list)

    current_frame = []  # list of (start_ts, end_ts, field_key, field_value)
    in_frame = False

    with open(INPUT_FILE, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            total_lines += 1
            line = line.rstrip("\n\r")

            if BITS_RE.search(line):
                bit_lines += 1
                continue

            m = FIELDS_RE.match(line)
            if not m:
                other_lines += 1
                continue

            field_lines += 1
            ts_start = int(m.group(1))
            ts_end = int(m.group(2))
            field_str = m.group(3)
            key, value = parse_field(field_str)

            if key == "Start of frame":
                # Start collecting a new frame
                current_frame = [(ts_start, ts_end, key, value)]
                in_frame = True
            elif in_frame:
                current_frame.append((ts_start, ts_end, key, value))
                if key == "End of frame":
                    # Frame complete
                    total_frames += 1
                    info = extract_frame_info(current_frame)

                    if info["identifier_raw"] == 0 and info["dlc"] == 0:
                        empty_frames += 1
                    else:
                        valid_frames += 1
                        id_hex = info["identifier_hex"] or "unknown"
                        data_str = " ".join(info["data_bytes"]) if info["data_bytes"] else "(no data)"
                        id_stats[id_hex].append({
                            "data": data_str,
                            "dlc": info["dlc"],
                            "ts_start": info["timestamp_start"],
                            "ts_end": info["timestamp_end"],
                            "crc": info["crc"],
                            "rtr": info["rtr"],
                            "ide": info["ide"],
                        })

                    in_frame = False
                    current_frame = []

    # ---- Report ----
    print("=" * 70)
    print("CAN FRAME ANALYSIS REPORT")
    print("=" * 70)
    print(f"Total lines processed:    {total_lines:>12,}")
    print(f"  Field lines:            {field_lines:>12,}")
    print(f"  Bit-level lines (skip): {bit_lines:>12,}")
    print(f"  Other/unrecognized:     {other_lines:>12,}")
    print()
    print(f"Total frames found:       {total_frames:>12,}")
    print(f"  Valid frames (ID!=0):   {valid_frames:>12,}")
    print(f"  Empty/idle (ID=0):      {empty_frames:>12,}")
    print()

    if id_stats:
        print("-" * 70)
        print(f"{'CAN ID':>10}  {'Count':>8}  {'DLC':>4}  {'Sample Data'}")
        print("-" * 70)
        for id_hex in sorted(id_stats.keys(), key=lambda x: int(x, 16)):
            frames = id_stats[id_hex]
            count = len(frames)
            dlc = frames[0]["dlc"]
            sample = frames[0]["data"]
            print(f"  0x{id_hex:>7s}  {count:>8,}  {dlc:>4}  {sample}")
        print("-" * 70)
        print(f"{'TOTAL':>10}  {valid_frames:>8,}")
        print()

        # Unique data payloads per ID
        print("=" * 70)
        print("UNIQUE DATA PAYLOADS PER CAN ID")
        print("=" * 70)
        for id_hex in sorted(id_stats.keys(), key=lambda x: int(x, 16)):
            frames = id_stats[id_hex]
            unique_data = set(f["data"] for f in frames)
            print(f"\n  CAN ID 0x{id_hex} — {len(frames)} frames, {len(unique_data)} unique payload(s):")
            for i, data in enumerate(sorted(unique_data)):
                if i >= 20:
                    print(f"    ... and {len(unique_data) - 20} more")
                    break
                print(f"    [{i+1:>3}] {data}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
