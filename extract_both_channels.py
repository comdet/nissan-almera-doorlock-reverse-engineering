#!/usr/bin/env python3
"""
Process both RX and TX CAN captures from logic analyzer tapped between MCU and CAN transceiver.

RX (doorunlock3.txt)    = everything MCU receives from CAN bus
TX (doorunlock3_d2.txt) = everything MCU transmits onto CAN bus

Output: Combined chronological view showing what the MCU sent vs received,
        plus a separate TX-only analysis to understand the MCU's protocol.
"""

import re
from collections import defaultdict

FIELDS_RE = re.compile(r"^(\d+)-(\d+)\s+CAN:\s+Fields:\s+(.+)$")

# UDS decode tables
UDS_SERVICES = {
    0x10: "DiagSessionCtrl", 0x11: "ECUReset", 0x22: "ReadDataByID",
    0x27: "SecurityAccess", 0x2E: "WriteDataByID", 0x2F: "IOControlByID",
    0x31: "RoutineControl", 0x3E: "TesterPresent",
    0x50: "+DiagSessionCtrl", 0x62: "+ReadDataByID", 0x67: "+SecurityAccess",
    0x6E: "+WriteDataByID", 0x6F: "+IOControlByID", 0x71: "+RoutineControl",
    0x7E: "+TesterPresent", 0x7F: "NegativeResponse",
    0x01: "OBD-II_ReqCurrent", 0x41: "OBD-II_RespCurrent",
}

DIAG_SESSIONS = {0x01: "default", 0x02: "programming", 0x03: "extended", 0xC0: "mfr_0xC0"}

NRC_CODES = {
    0x10: "generalReject", 0x11: "svcNotSupported", 0x12: "subFuncNotSupported",
    0x13: "incorrectMsgLen", 0x22: "conditionsNotCorrect", 0x31: "requestOutOfRange",
    0x33: "securityAccessDenied", 0x35: "invalidKey", 0x78: "responsePending",
    0x7E: "subFuncNotSupportedInSession", 0x7F: "svcNotSupportedInSession",
}

IO_CTRL = {0x00: "returnToECU", 0x01: "resetDefault", 0x02: "freeze", 0x03: "shortTermAdj"}


def parse_field(field_str):
    if ":" in field_str:
        key, _, value = field_str.partition(":")
        return key.strip(), value.strip()
    return field_str.strip(), None


def extract_frames(filename):
    """Extract all valid CAN frames from a file. Returns list of frame dicts."""
    frames = []
    current = []
    in_frame = False

    with open(filename, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n\r")
            m = FIELDS_RE.match(line)
            if not m:
                continue
            ts_start = int(m.group(1))
            ts_end = int(m.group(2))
            field_str = m.group(3)
            key, value = parse_field(field_str)

            if key == "Start of frame":
                current = [(ts_start, ts_end, key, value)]
                in_frame = True
            elif in_frame:
                current.append((ts_start, ts_end, key, value))
                if key == "End of frame":
                    info = {"ts": current[0][0], "ts_end": current[-1][1]}
                    data_bytes = []
                    for _, _, k, v in current:
                        if k == "Identifier":
                            rm = re.search(r"\(0x([0-9a-fA-F]+)\)", v)
                            if rm:
                                info["id"] = int(rm.group(1), 16)
                                info["id_hex"] = rm.group(1)
                        elif k == "Data length code":
                            info["dlc"] = int(v)
                        elif k.startswith("Data byte"):
                            data_bytes.append(v)
                        elif k == "CRC-15 sequence":
                            info["crc"] = v
                    info["data"] = data_bytes
                    can_id = info.get("id", 0)
                    dlc = info.get("dlc", 0)
                    if not (can_id == 0 and dlc == 0):
                        frames.append(info)
                    in_frame = False
                    current = []
    frames.sort(key=lambda f: f["ts"])
    return frames


def decode_uds_short(data_bytes):
    """Short one-line UDS decode."""
    vals = []
    for b in data_bytes:
        vals.append(int(b, 16) if b.startswith("0x") else int(b))
    if len(vals) < 1:
        return ""

    pci = (vals[0] >> 4) & 0x0F

    if pci == 0:  # Single Frame
        length = vals[0] & 0x0F
        if length < 1 or length + 1 > len(vals):
            return f"SF len={length}"
        sid = vals[1]
        return f"SF [{_decode_sid_short(sid, vals[1:1+length])}]"
    elif pci == 1:  # First Frame
        total = ((vals[0] & 0x0F) << 8) | vals[1]
        sid = vals[2] if len(vals) > 2 else 0
        return f"FF total={total} [{_decode_sid_short(sid, vals[2:])}]"
    elif pci == 2:  # Consecutive Frame
        seq = vals[0] & 0x0F
        return f"CF seq={seq} [{' '.join(f'{v:02X}' for v in vals[1:])}]"
    elif pci == 3:  # Flow Control
        fs = {0: "CTS", 1: "Wait", 2: "Overflow"}.get(vals[0] & 0x0F, "?")
        return f"FC {fs} BS={vals[1]} STmin={vals[2]}"
    return f"raw [{' '.join(f'{v:02X}' for v in vals)}]"


def _decode_sid_short(sid, payload):
    svc = UDS_SERVICES.get(sid, f"0x{sid:02X}")

    if sid == 0x10 and len(payload) >= 2:
        sess = DIAG_SESSIONS.get(payload[1], f"0x{payload[1]:02X}")
        return f"{svc} session={sess}"

    elif sid == 0x50 and len(payload) >= 2:
        sess = DIAG_SESSIONS.get(payload[1], f"0x{payload[1]:02X}")
        extra = ""
        if len(payload) >= 6:
            p2 = (payload[2] << 8) | payload[3]
            p2s = (payload[4] << 8) | payload[5]
            extra = f" P2={p2}/{p2s*10}ms"
        return f"{svc} session={sess}{extra}"

    elif sid == 0x22 and len(payload) >= 3:
        did = (payload[1] << 8) | payload[2]
        return f"{svc} DID=0x{did:04X}"

    elif sid == 0x62 and len(payload) >= 3:
        did = (payload[1] << 8) | payload[2]
        data = " ".join(f"{v:02X}" for v in payload[3:])
        return f"{svc} DID=0x{did:04X} [{data}]"

    elif sid == 0x2F and len(payload) >= 4:
        did = (payload[1] << 8) | payload[2]
        ctrl = IO_CTRL.get(payload[3], f"0x{payload[3]:02X}")
        state = " ".join(f"{v:02X}" for v in payload[4:])
        return f"{svc} DID=0x{did:04X} {ctrl} [{state}]"

    elif sid == 0x6F and len(payload) >= 3:
        did = (payload[1] << 8) | payload[2]
        status = " ".join(f"{v:02X}" for v in payload[3:])
        return f"{svc} DID=0x{did:04X} [{status}]"

    elif sid == 0x3E and len(payload) >= 2:
        return f"{svc} sub=0x{payload[1]:02X}"

    elif sid == 0x7E and len(payload) >= 2:
        return f"{svc} sub=0x{payload[1]:02X}"

    elif sid == 0x7F and len(payload) >= 3:
        rej = UDS_SERVICES.get(payload[1], f"0x{payload[1]:02X}")
        nrc = NRC_CODES.get(payload[2], f"0x{payload[2]:02X}")
        return f"NegResp svc={rej} NRC={nrc}"

    elif sid == 0x01 and len(payload) >= 2:
        return f"OBD-II PID=0x{payload[1]:02X}"

    elif sid == 0x41 and len(payload) >= 2:
        data = " ".join(f"{v:02X}" for v in payload[2:])
        return f"OBD-II_Resp PID=0x{payload[1]:02X} [{data}]"

    return svc


def reassemble_multiframe(frames):
    """Track ISO-TP multiframe reassembly across frames. Returns dict: frame_index -> reassembled UDS."""
    bufs = {}  # can_id -> {"total": N, "data": [...]}
    results = {}

    for i, fr in enumerate(frames):
        vals = [int(b, 16) if b.startswith("0x") else int(b) for b in fr["data"]]
        if not vals:
            continue
        can_id = fr.get("id", 0)
        pci = (vals[0] >> 4) & 0x0F

        if pci == 1:
            total = ((vals[0] & 0x0F) << 8) | vals[1]
            bufs[can_id] = {"total": total, "data": list(vals[2:])}
        elif pci == 2 and can_id in bufs:
            bufs[can_id]["data"].extend(vals[1:])
            buf = bufs[can_id]
            if len(buf["data"]) >= buf["total"]:
                full = buf["data"][:buf["total"]]
                if full:
                    sid = full[0]
                    results[i] = {
                        "hex": " ".join(f"{v:02X}" for v in full),
                        "uds": _decode_sid_short(sid, full),
                        "total": buf["total"],
                    }
                del bufs[can_id]

    return results


def main():
    print("Processing RX (doorunlock3.txt)...")
    rx_frames = extract_frames("doorunlock3.txt")
    print(f"  -> {len(rx_frames)} valid frames")

    print("Processing TX (doorunlock3_d2.txt)...")
    tx_frames = extract_frames("doorunlock3_d2.txt")
    print(f"  -> {len(tx_frames)} valid frames")

    # ========== TX-only analysis ==========
    with open("doorunlock3_tx_only.txt", "w", encoding="utf-8") as out:
        out.write("=" * 90 + "\n")
        out.write("TX CHANNEL — What the MCU sends onto CAN bus\n")
        out.write(f"Total TX frames: {len(tx_frames)}\n")
        out.write("=" * 90 + "\n\n")

        # Stats
        id_counts = defaultdict(int)
        for fr in tx_frames:
            id_counts[fr.get("id", 0)] += 1

        out.write("CAN IDs transmitted by MCU:\n")
        for cid in sorted(id_counts.keys()):
            out.write(f"  0x{cid:03X}: {id_counts[cid]:>4} frames\n")
        out.write(f"\n  Total: {len(tx_frames)} frames\n\n")
        out.write("-" * 90 + "\n\n")

        # Reassemble multiframes
        tx_reassembled = reassemble_multiframe(tx_frames)

        for i, fr in enumerate(tx_frames):
            can_id = fr.get("id", 0)
            id_hex = fr.get("id_hex", "???")
            dlc = fr.get("dlc", 0)
            data_hex = " ".join(fr["data"]) if fr["data"] else "(empty)"
            uds = decode_uds_short(fr["data"]) if fr["data"] else ""

            out.write(f"#{i+1:<4} [{fr['ts']:>12,}]  0x{id_hex:>4s}  DLC={dlc}  {data_hex}\n")
            if uds:
                out.write(f"      {uds}\n")
            if i in tx_reassembled:
                r = tx_reassembled[i]
                out.write(f"      *** REASSEMBLED ({r['total']} bytes): [{r['hex']}]\n")
                out.write(f"      *** UDS: {r['uds']}\n")
            out.write("\n")

    print(f"Written TX analysis to doorunlock3_tx_only.txt")

    # ========== Combined RX+TX timeline ==========
    # Tag each frame with channel
    for fr in rx_frames:
        fr["ch"] = "RX"
    for fr in tx_frames:
        fr["ch"] = "TX"

    all_frames = rx_frames + tx_frames
    all_frames.sort(key=lambda f: f["ts"])

    # Reassemble for combined
    combined_reassembled = reassemble_multiframe(all_frames)

    with open("doorunlock3_combined.txt", "w", encoding="utf-8") as out:
        out.write("=" * 100 + "\n")
        out.write("COMBINED RX + TX TIMELINE\n")
        out.write("RX = MCU receives from CAN bus | TX = MCU transmits onto CAN bus\n")
        out.write(f"Total: {len(all_frames)} frames (RX={len(rx_frames)}, TX={len(tx_frames)})\n")
        out.write("=" * 100 + "\n\n")

        prev_ts = None
        for i, fr in enumerate(all_frames):
            can_id = fr.get("id", 0)
            id_hex = fr.get("id_hex", "???")
            dlc = fr.get("dlc", 0)
            ch = fr["ch"]
            data_hex = " ".join(fr["data"]) if fr["data"] else "(empty)"
            uds = decode_uds_short(fr["data"]) if fr["data"] else ""

            # Gap marker
            if prev_ts is not None and (fr["ts"] - prev_ts) > 5000000:
                out.write(f"  {'~' * 80}\n")
                out.write(f"  GAP: ~{fr['ts'] - prev_ts:,} ticks\n")
                out.write(f"  {'~' * 80}\n\n")

            arrow = "MCU<<" if ch == "RX" else ">>MCU"
            marker = "    " if ch == "RX" else "*** "

            out.write(f"{marker}#{i+1:<4} [{fr['ts']:>12,}] {ch} {arrow}  0x{id_hex:>4s} DLC={dlc}  {data_hex}\n")
            if uds:
                out.write(f"{marker}      {uds}\n")
            if i in combined_reassembled:
                r = combined_reassembled[i]
                out.write(f"{marker}      REASSEMBLED ({r['total']}B): [{r['hex']}]\n")
                out.write(f"{marker}      UDS: {r['uds']}\n")
            out.write("\n")
            prev_ts = fr["ts"]

    print(f"Written combined timeline to doorunlock3_combined.txt")


if __name__ == "__main__":
    main()
