#!/usr/bin/env python3
"""
Extract valid CAN frames from doorunlock3.txt and decode UDS conversation.
Output: chronological conversation with UDS service decoding.
"""

import re
from collections import defaultdict

INPUT_FILE = "doorunlock3.txt"
OUTPUT_FILE = "doorunlock3_frames.txt"

FIELDS_RE = re.compile(r"^(\d+)-(\d+)\s+CAN:\s+Fields:\s+(.+)$")

# UDS Service IDs
UDS_SERVICES = {
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x14: "ClearDiagnosticInformation",
    0x19: "ReadDTCInformation",
    0x22: "ReadDataByIdentifier",
    0x23: "ReadMemoryByAddress",
    0x27: "SecurityAccess",
    0x28: "CommunicationControl",
    0x2E: "WriteDataByIdentifier",
    0x2F: "InputOutputControlByIdentifier",
    0x31: "RoutineControl",
    0x34: "RequestDownload",
    0x35: "RequestUpload",
    0x36: "TransferData",
    0x37: "RequestTransferExit",
    0x3E: "TesterPresent",
    0x50: "+DiagnosticSessionControl",
    0x51: "+ECUReset",
    0x54: "+ClearDiagnosticInformation",
    0x59: "+ReadDTCInformation",
    0x62: "+ReadDataByIdentifier",
    0x63: "+ReadMemoryByAddress",
    0x67: "+SecurityAccess",
    0x68: "+CommunicationControl",
    0x6E: "+WriteDataByIdentifier",
    0x6F: "+InputOutputControlByIdentifier",
    0x71: "+RoutineControl",
    0x74: "+RequestDownload",
    0x75: "+RequestUpload",
    0x76: "+TransferData",
    0x77: "+RequestTransferExit",
    0x7E: "+TesterPresent",
    0x7F: "NegativeResponse",
}

DIAG_SESSIONS = {
    0x01: "defaultSession",
    0x02: "programmingSession",
    0x03: "extendedDiagnosticSession",
    0xC0: "vehicleManufacturerSpecific (0xC0)",
}

NRC_CODES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x25: "noResponseFromSubnetComponent",
    0x26: "failurePreventsExecutionOfRequestedAction",
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

IO_CONTROL_PARAMS = {
    0x00: "returnControlToECU",
    0x01: "resetToDefault",
    0x02: "freezeCurrentState",
    0x03: "shortTermAdjustment",
}

# Known request/response CAN ID pairs
# Request -> Response
PAIR_MAP = {
    0x743: 0x763,
    0x745: 0x765,
    0x74C: 0x76C,
    0x7DF: 0x7E8,  # OBD-II broadcast
    0x7E1: None,    # unknown response ID
}

RESPONSE_IDS = {0x763, 0x765, 0x76C, 0x7E8}


def parse_field(field_str):
    if ":" in field_str:
        key, _, value = field_str.partition(":")
        return key.strip(), value.strip()
    return field_str.strip(), None


def decode_uds(data_bytes, can_id):
    """Decode UDS/ISO-TP layer from data bytes. Returns human-readable string."""
    if not data_bytes:
        return ""

    vals = []
    for b in data_bytes:
        if b.startswith("0x"):
            vals.append(int(b, 16))
        else:
            vals.append(int(b))

    if len(vals) < 2:
        return ""

    lines = []
    pci_type = (vals[0] >> 4) & 0x0F  # ISO-TP PCI type

    if pci_type == 0:
        # Single Frame
        length = vals[0] & 0x0F
        if length == 0 or length + 1 > len(vals):
            return f"  [ISO-TP] Single Frame, len={length}"
        sid = vals[1]
        lines.append(f"  [ISO-TP] Single Frame, len={length}")
        lines.append(f"  [UDS]    {_decode_sid(sid, vals[1:1+length], can_id)}")

    elif pci_type == 1:
        # First Frame
        length = ((vals[0] & 0x0F) << 8) | vals[1]
        lines.append(f"  [ISO-TP] First Frame, total_len={length}")
        if len(vals) > 2:
            sid = vals[2]
            lines.append(f"  [UDS]    {_decode_sid(sid, vals[2:], can_id)}")

    elif pci_type == 2:
        # Consecutive Frame
        seq = vals[0] & 0x0F
        data_hex = " ".join(f"{v:02X}" for v in vals[1:])
        lines.append(f"  [ISO-TP] Consecutive Frame, seq={seq}, data=[{data_hex}]")

    elif pci_type == 3:
        # Flow Control
        fs = vals[0] & 0x0F
        bs = vals[1]
        stmin = vals[2]
        fs_str = {0: "ContinueToSend", 1: "Wait", 2: "Overflow"}.get(fs, f"unknown({fs})")
        lines.append(f"  [ISO-TP] Flow Control: {fs_str}, blockSize={bs}, STmin={stmin}ms")

    else:
        data_hex = " ".join(f"{v:02X}" for v in vals)
        lines.append(f"  [RAW]    {data_hex}")

    return "\n".join(lines)


def _decode_sid(sid, payload, can_id):
    """Decode a UDS service call."""
    svc_name = UDS_SERVICES.get(sid, f"Unknown(0x{sid:02X})")
    parts = [f"Service: 0x{sid:02X} ({svc_name})"]

    if sid == 0x10 and len(payload) >= 2:
        # DiagnosticSessionControl
        sub = payload[1]
        sess = DIAG_SESSIONS.get(sub, f"0x{sub:02X}")
        parts.append(f"subFunction={sess}")

    elif sid == 0x22 and len(payload) >= 3:
        # ReadDataByIdentifier
        did = (payload[1] << 8) | payload[2]
        parts.append(f"DID=0x{did:04X}")

    elif sid == 0x62 and len(payload) >= 3:
        # Positive response to ReadDataByIdentifier
        did = (payload[1] << 8) | payload[2]
        resp_data = " ".join(f"{v:02X}" for v in payload[3:])
        parts.append(f"DID=0x{did:04X}")
        if resp_data:
            parts.append(f"data=[{resp_data}]")

    elif sid == 0x2F and len(payload) >= 4:
        # InputOutputControlByIdentifier
        did = (payload[1] << 8) | payload[2]
        iocp = payload[3]
        iocp_name = IO_CONTROL_PARAMS.get(iocp, f"0x{iocp:02X}")
        parts.append(f"DID=0x{did:04X}, controlParam={iocp_name}")
        if len(payload) > 4:
            state_data = " ".join(f"{v:02X}" for v in payload[4:])
            parts.append(f"controlState=[{state_data}]")

    elif sid == 0x6F and len(payload) >= 3:
        # Positive response to IOControl
        did = (payload[1] << 8) | payload[2]
        parts.append(f"DID=0x{did:04X}")
        if len(payload) > 3:
            status = " ".join(f"{v:02X}" for v in payload[3:])
            parts.append(f"status=[{status}]")

    elif sid == 0x50 and len(payload) >= 2:
        # Positive response to DiagSessionControl
        sub = payload[1]
        sess = DIAG_SESSIONS.get(sub, f"0x{sub:02X}")
        parts.append(f"session={sess}")
        if len(payload) >= 6:
            p2 = (payload[2] << 8) | payload[3]
            p2star = (payload[4] << 8) | payload[5]
            parts.append(f"P2={p2}ms, P2*={p2star * 10}ms")

    elif sid == 0x3E:
        # TesterPresent
        if len(payload) >= 2:
            parts.append(f"subFunction=0x{payload[1]:02X}")

    elif sid == 0x7E:
        # Positive TesterPresent
        if len(payload) >= 2:
            parts.append(f"subFunction=0x{payload[1]:02X}")

    elif sid == 0x7F and len(payload) >= 3:
        # NegativeResponse
        rej_sid = payload[1]
        nrc = payload[2]
        rej_name = UDS_SERVICES.get(rej_sid, f"0x{rej_sid:02X}")
        nrc_name = NRC_CODES.get(nrc, f"0x{nrc:02X}")
        parts = [f"Service: 0x{sid:02X} (NegativeResponse)"]
        parts.append(f"rejectedService={rej_name}(0x{rej_sid:02X})")
        parts.append(f"NRC={nrc_name}(0x{nrc:02X})")

    elif sid == 0x01 and len(payload) >= 2:
        # OBD-II service 01
        pid = payload[1]
        pid_names = {0x0D: "VehicleSpeed", 0x0C: "EngineRPM", 0x05: "CoolantTemp"}
        pname = pid_names.get(pid, f"0x{pid:02X}")
        parts = [f"Service: 0x01 (OBD-II RequestCurrentPowertrainData)"]
        parts.append(f"PID=0x{pid:02X} ({pname})")

    return ", ".join(parts)


def main():
    # Pass 1: collect all valid frames
    frames = []
    current_frame_fields = []
    in_frame = False

    with open(INPUT_FILE, "r", encoding="utf-8", errors="replace") as f:
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
                current_frame_fields = [(ts_start, ts_end, key, value)]
                in_frame = True
            elif in_frame:
                current_frame_fields.append((ts_start, ts_end, key, value))
                if key == "End of frame":
                    # Build frame
                    info = {"ts": current_frame_fields[0][0], "ts_end": current_frame_fields[-1][1]}
                    data_bytes = []
                    for _, _, k, v in current_frame_fields:
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

                    # Skip empty/idle frames
                    can_id = info.get("id", 0)
                    dlc = info.get("dlc", 0)
                    if can_id == 0 and dlc == 0:
                        pass  # skip idle
                    else:
                        frames.append(info)

                    in_frame = False
                    current_frame_fields = []

    # Sort by timestamp
    frames.sort(key=lambda f: f["ts"])

    # Reassemble multiframe UDS messages
    # Track ISO-TP reassembly per CAN ID
    multiframe_buf = {}  # can_id -> {"total_len": N, "data": [...], "first_frame": frame}

    # Write output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        out.write("=" * 80 + "\n")
        out.write("CAN / UDS CONVERSATION — doorunlock3.txt\n")
        out.write(f"Total valid frames: {len(frames)}\n")
        out.write("=" * 80 + "\n\n")

        # Group into logical exchanges
        prev_ts = None
        frame_num = 0

        for fr in frames:
            frame_num += 1
            can_id = fr.get("id", 0)
            id_hex = fr.get("id_hex", "???")
            dlc = fr.get("dlc", 0)
            data = fr["data"]
            ts = fr["ts"]

            # Time gap detection — insert separator for gaps > 50ms worth of ticks
            if prev_ts is not None:
                gap = ts - prev_ts
                if gap > 5000000:  # large gap
                    out.write(f"\n{'- ' * 40}\n")
                    out.write(f"  [GAP: ~{gap:,} ticks]\n")
                    out.write(f"{'- ' * 40}\n\n")

            # Direction
            if can_id in RESPONSE_IDS:
                direction = "<< ECU RESP"
            else:
                direction = ">> TESTER  "

            data_hex = " ".join(data) if data else "(empty)"
            out.write(f"#{frame_num:<4} [{ts:>12,}]  0x{id_hex:>4s}  DLC={dlc}  {direction}  {data_hex}\n")

            # UDS decode
            uds_info = decode_uds(data, can_id)
            if uds_info:
                out.write(uds_info + "\n")

            # ISO-TP reassembly tracking
            vals = []
            for b in data:
                vals.append(int(b, 16) if b.startswith("0x") else int(b))

            if vals:
                pci = (vals[0] >> 4) & 0x0F
                if pci == 1:
                    # First Frame — start buffer
                    total_len = ((vals[0] & 0x0F) << 8) | vals[1]
                    multiframe_buf[can_id] = {
                        "total_len": total_len,
                        "data": list(vals[2:]),
                        "frame_num": frame_num,
                    }
                elif pci == 2 and can_id in multiframe_buf:
                    # Consecutive Frame
                    multiframe_buf[can_id]["data"].extend(vals[1:])
                    buf = multiframe_buf[can_id]
                    if len(buf["data"]) >= buf["total_len"]:
                        # Complete!
                        full_data = buf["data"][:buf["total_len"]]
                        full_hex = " ".join(f"{v:02X}" for v in full_data)
                        out.write(f"  [REASSEMBLED] len={buf['total_len']}: [{full_hex}]\n")

                        # Decode the reassembled UDS
                        if full_data:
                            sid = full_data[0]
                            uds_str = _decode_sid(sid, full_data, can_id)
                            out.write(f"  [UDS FULL]    {uds_str}\n")

                        del multiframe_buf[can_id]

            out.write("\n")

        # Summary section
        out.write("\n" + "=" * 80 + "\n")
        out.write("SUMMARY\n")
        out.write("=" * 80 + "\n\n")

        # Count per ID
        id_counts = defaultdict(int)
        for fr in frames:
            id_counts[fr.get("id", 0)] += 1

        out.write("Frames per CAN ID:\n")
        for cid in sorted(id_counts.keys()):
            role = "ECU Response" if cid in RESPONSE_IDS else "Tester Request"
            out.write(f"  0x{cid:03X}: {id_counts[cid]:>4} frames  ({role})\n")

        out.write(f"\nTotal: {len(frames)} frames\n")

    print(f"Written {len(frames)} frames to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
