#!/usr/bin/env python3
"""
Focused analysis of the UNLOCK sequence.
Context: Nissan Almera Turbo (N18) / Versa
Capture: OBD door lock device plugged in → door unlocks → capture stopped.
Only 0x745 (request) / 0x765 (response) BCM conversation.
"""

import re
from collections import defaultdict

FIELDS_RE = re.compile(r"^(\d+)-(\d+)\s+CAN:\s+Fields:\s+(.+)$")


def parse_field(field_str):
    if ":" in field_str:
        key, _, value = field_str.partition(":")
        return key.strip(), value.strip()
    return field_str.strip(), None


def extract_frames(filename):
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
                    info["data"] = data_bytes
                    can_id = info.get("id", 0)
                    dlc = info.get("dlc", 0)
                    if not (can_id == 0 and dlc == 0):
                        frames.append(info)
                    in_frame = False
                    current = []
    frames.sort(key=lambda f: f["ts"])
    return frames


def get_vals(data_bytes):
    return [int(b, 16) if b.startswith("0x") else int(b) for b in data_bytes]


def main():
    print("Loading RX and TX...")
    rx_frames = extract_frames("doorunlock3.txt")
    tx_frames = extract_frames("doorunlock3_d2.txt")

    for fr in rx_frames:
        fr["ch"] = "RX"
    for fr in tx_frames:
        fr["ch"] = "TX"

    all_frames = rx_frames + tx_frames
    all_frames.sort(key=lambda f: f["ts"])

    # Filter only 0x745/0x765 + all IOControl related
    bcm_ids = {0x745, 0x765}

    out_lines = []
    out_lines.append("=" * 90)
    out_lines.append("NISSAN ALMERA TURBO (N18) — OBD DOOR UNLOCK SEQUENCE ANALYSIS")
    out_lines.append("=" * 90)
    out_lines.append("")
    out_lines.append("Setup: Logic analyzer between MCU TX/RX and CAN transceiver")
    out_lines.append("Event: Device plugged in → door UNLOCK heard → capture stopped")
    out_lines.append("Focus: BCM communication (0x745 request / 0x765 response)")
    out_lines.append("")
    out_lines.append("-" * 90)
    out_lines.append("")

    # Track session state
    session_state = "unknown"
    first_ts = None
    phase_num = 0
    prev_ts = None

    # Collect all BCM events
    bcm_events = []
    for fr in all_frames:
        can_id = fr.get("id", 0)
        if can_id not in bcm_ids:
            continue
        # Skip duplicate RX echo of TX
        if fr["ch"] == "RX" and can_id == 0x745:
            # This is the MCU's own TX echoed back on bus - skip if we have TX
            continue
        bcm_events.append(fr)

    # Also include TX 0x745 frames
    for fr in all_frames:
        can_id = fr.get("id", 0)
        if can_id == 0x745 and fr["ch"] == "TX":
            bcm_events.append(fr)

    bcm_events.sort(key=lambda f: f["ts"])

    # Deduplicate (TX and RX with same timestamp within 10 ticks)
    deduped = []
    seen_ts = set()
    for fr in bcm_events:
        key = (fr.get("id"), fr["ts"] // 100)
        if key not in seen_ts:
            seen_ts.add(key)
            deduped.append(fr)

    # Process
    event_num = 0
    io_events = []

    for fr in deduped:
        can_id = fr.get("id", 0)
        vals = get_vals(fr["data"]) if fr["data"] else []
        if not vals:
            continue

        pci = (vals[0] >> 4) & 0x0F

        if first_ts is None:
            first_ts = fr["ts"]

        elapsed_ms = (fr["ts"] - first_ts) / 48000  # approximate: assume 48MHz sample rate
        elapsed_s = elapsed_ms / 1000

        direction = "TX>>" if (fr["ch"] == "TX" or can_id == 0x745) else "<<RX"
        if can_id == 0x765:
            direction = "<<RX"

        # Decode
        desc = ""
        is_important = False

        if pci == 0:  # Single Frame
            length = vals[0] & 0x0F
            if length >= 1:
                sid = vals[1]

                if sid == 0x10:  # DiagSessionCtrl
                    sub = vals[2] if length >= 2 else 0
                    sess_map = {0x01: "DEFAULT", 0x02: "PROGRAMMING", 0x03: "EXTENDED"}
                    sess = sess_map.get(sub, f"0x{sub:02X}")
                    desc = f"DiagSessionCtrl → {sess}"
                    is_important = True

                elif sid == 0x50:  # +DiagSessionCtrl
                    sub = vals[2] if length >= 2 else 0
                    sess_map = {0x01: "DEFAULT", 0x02: "PROGRAMMING", 0x03: "EXTENDED"}
                    sess = sess_map.get(sub, f"0x{sub:02X}")
                    session_state = sess
                    p2 = (vals[3] << 8 | vals[4]) if length >= 5 else 0
                    desc = f"+DiagSessionCtrl OK → session={sess} (P2={p2}ms)"
                    is_important = True

                elif sid == 0x2F:  # IOControlByID
                    did = (vals[2] << 8 | vals[3]) if length >= 3 else 0
                    ctrl = vals[4] if length >= 4 else 0
                    ctrl_map = {0x00: "returnToECU", 0x01: "resetDefault",
                                0x02: "freeze", 0x03: "shortTermAdj"}
                    ctrl_name = ctrl_map.get(ctrl, f"0x{ctrl:02X}")
                    state_bytes = vals[5:1+length] if length > 4 else []
                    state_hex = " ".join(f"0x{v:02X}" for v in state_bytes)
                    desc = f"★ IOControlByID DID=0x{did:04X} {ctrl_name} [{state_hex}]"
                    is_important = True
                    io_events.append({
                        "ts": fr["ts"], "elapsed_s": elapsed_s,
                        "did": did, "ctrl": ctrl_name,
                        "state": state_bytes, "direction": direction,
                        "session": session_state,
                    })

                elif sid == 0x6F:  # +IOControlByID
                    did = (vals[2] << 8 | vals[3]) if length >= 3 else 0
                    status = vals[4:1+length]
                    status_hex = " ".join(f"0x{v:02X}" for v in status)
                    desc = f"★ +IOControlByID OK DID=0x{did:04X} status=[{status_hex}]"
                    is_important = True
                    io_events.append({
                        "ts": fr["ts"], "elapsed_s": elapsed_s,
                        "did": did, "ctrl": "RESPONSE_OK",
                        "state": status, "direction": direction,
                        "session": session_state,
                    })

                elif sid == 0x3E:
                    desc = "TesterPresent"

                elif sid == 0x7E:
                    desc = "+TesterPresent OK"

                elif sid == 0x7F:  # NegativeResponse
                    rej_sid = vals[2] if length >= 2 else 0
                    nrc = vals[3] if length >= 3 else 0
                    nrc_map = {0x78: "responsePending", 0x7F: "svcNotSupportedInSession",
                               0x22: "conditionsNotCorrect", 0x31: "requestOutOfRange"}
                    nrc_name = nrc_map.get(nrc, f"0x{nrc:02X}")
                    svc_map = {0x2F: "IOControl", 0x22: "ReadDataByID", 0x10: "DiagSession"}
                    svc_name = svc_map.get(rej_sid, f"0x{rej_sid:02X}")
                    desc = f"✗ NEGATIVE RESPONSE: {svc_name} rejected, NRC={nrc_name}"
                    is_important = True
                    if rej_sid == 0x2F:
                        io_events.append({
                            "ts": fr["ts"], "elapsed_s": elapsed_s,
                            "did": 0, "ctrl": f"REJECTED({nrc_name})",
                            "state": [], "direction": direction,
                            "session": session_state,
                        })

                elif sid == 0x22:  # ReadDataByID
                    did = (vals[2] << 8 | vals[3]) if length >= 3 else 0
                    desc = f"ReadDataByID DID=0x{did:04X}"

                else:
                    desc = f"SID=0x{sid:02X}"

        elif pci == 3:  # Flow Control
            desc = f"FlowControl CTS"

        elif pci == 1:  # First Frame
            total = ((vals[0] & 0x0F) << 8) | vals[1]
            sid = vals[2] if len(vals) > 2 else 0
            if sid == 0x62:
                did = (vals[3] << 8 | vals[4]) if len(vals) > 4 else 0
                desc = f"+ReadDataByID DID=0x{did:04X} (multiframe, {total}B)"
            else:
                desc = f"FirstFrame total={total} SID=0x{sid:02X}"

        elif pci == 2:  # Consecutive Frame
            seq = vals[0] & 0x0F
            desc = f"ConsecutiveFrame seq={seq}"

        if not desc:
            desc = " ".join(f"{v:02X}" for v in vals)

        # Gap detection
        if prev_ts is not None and (fr["ts"] - prev_ts) > 3000000:
            gap_s = (fr["ts"] - prev_ts) / 48000 / 1000
            phase_num += 1
            out_lines.append(f"")
            out_lines.append(f"  {'─' * 70}")
            out_lines.append(f"  GAP: ~{gap_s:.1f}s")
            out_lines.append(f"  {'─' * 70}")
            out_lines.append(f"")

        event_num += 1
        marker = "  ★★★" if "IOControl" in desc or "NEGATIVE" in desc else "     "
        prefix = f"{marker} [{elapsed_s:8.3f}s] {direction} 0x{fr.get('id_hex', '???'):>3s}"
        out_lines.append(f"{prefix}  {desc}")

        prev_ts = fr["ts"]

    # Summary
    out_lines.append("")
    out_lines.append("=" * 90)
    out_lines.append("IOControl EVENT SUMMARY")
    out_lines.append("=" * 90)
    out_lines.append("")
    for i, ev in enumerate(io_events):
        did_hex = f"0x{ev['did']:04X}" if ev['did'] else "n/a"
        state_hex = " ".join(f"0x{v:02X}" for v in ev['state'])
        out_lines.append(
            f"  #{i+1}  [{ev['elapsed_s']:8.3f}s]  {ev['direction']:4s}  "
            f"DID={did_hex}  {ev['ctrl']:<30s}  [{state_hex}]  "
            f"(session={ev['session']})"
        )

    out_lines.append("")
    out_lines.append("=" * 90)
    out_lines.append("PROTOCOL DECODE — UNLOCK PROCEDURE")
    out_lines.append("=" * 90)
    out_lines.append("""
Based on capture analysis (Nissan Almera Turbo N18 / Versa):

TARGET ECU: Body Control Module (BCM)
  Request CAN ID:  0x745
  Response CAN ID: 0x765

UNLOCK PROCEDURE (what the OBD device does):

  Phase 1: INITIALIZE
    - Enter extendedDiagnosticSession on all ECUs
    - Start polling loop (ReadDataByID, TesterPresent, OBD-II speed)

  Phase 2: UNLOCK ATTEMPT(s)
    a) Enter extendedDiagnosticSession (REQUIRED)
       TX: 02 10 03 FF FF FF FF FF
       RX: 06 50 03 00 32 01 F4 00  (OK)

    b) TesterPresent (keep-alive)
       TX: 02 3E 00 FF FF FF FF FF
       RX: 02 7E 00 ...             (OK)

    c) IOControlByIdentifier — UNLOCK COMMAND
       TX: 06 2F 02 3F 03 00 01 FF
            │  │  └──┘ │  └──┘
            │  │  DID   │  controlState
            │  │ 0x023F │  [00 01]
            │  SID=0x2F  controlParam=shortTermAdj(0x03)
            len=6

       RX: 05 6F 02 3F 03 01 00 00  (positive response)

    d) Return to defaultSession
       TX: 02 10 01 FF FF FF FF FF
       RX: 06 50 01 00 32 01 F4 00  (OK)

  Phase 3: CLEANUP / RE-INIT
    - Re-enter extendedSession on all ECUs
    - Resume polling loop

  ADDITIONAL COMMAND OBSERVED:
    TX: 06 2F 02 02 03 00 02 FF     (IOControl DID=0x0202 [00 02])
    RX: 05 6F 02 02 03 01 00 00     (OK)
    → Possibly related to door lock indicator or secondary function

  DID=0x023F controlState values:
    [00 01] = UNLOCK (sent 3x during capture, including 1 rejected in wrong session)
    [00 00] = RETURN CONTROL TO ECU / RESET (sent 2x as cleanup after unlock)

KEY FINDINGS:
  1. MUST be in extendedDiagnosticSession (0x03) before IOControl
  2. Primary unlock: DID=0x023F, shortTermAdj, state=[00 01]
  3. Device retries unlock command multiple times (robust error handling)
  4. After unlock, sends [00 00] to return actuator control to ECU
  5. Secondary command DID=0x0202 [00 02] purpose unclear - possibly:
     - Interior light trigger
     - Door lock motor direction indicator
     - Separate lock/unlock mechanism for different door groups
""")

    output = "\n".join(out_lines)
    with open("doorunlock3_unlock_analysis.txt", "w", encoding="utf-8") as f:
        f.write(output)
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(output)
    print(f"\nSaved to doorunlock3_unlock_analysis.txt")


if __name__ == "__main__":
    main()
