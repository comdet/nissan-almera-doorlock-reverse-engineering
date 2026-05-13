/*
 * Phase 2 — Serial command interface (debug + manual control).
 *
 * Accepts both:
 *   - Text commands: "lock", "unlock", "drl on", "drl off", "status",
 *                    "config", "config <key> <val>", "save", "wifi on/off",
 *                    "wifi info", "json on/off", "help", "reboot"
 *   - JSON lines: any string starting with '{' is forwarded to json_proto.
 *
 * Drive by calling poll() from the comms task on each iteration; it reads
 * available Serial bytes non-blocking, splits on CR/LF, and dispatches.
 */

#pragma once

#include <stdint.h>

namespace serial_cmd {

void poll();
void printHelp();
void printSnapshotText();   // pretty snapshot (used by 'status' or comms task)

}  // namespace serial_cmd
