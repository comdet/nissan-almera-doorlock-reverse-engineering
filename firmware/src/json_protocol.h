/*
 * Phase 4 — JSON serialize/deserialize.
 * Format matches FIRMWARE_PLAN.md (newline-delimited, TCP and Serial).
 */

#pragma once

#include <stdint.h>
#include <stddef.h>
#include "cmd_queue.h"

namespace json_proto {

// Build "hello" frame. Writes to buf with trailing \n. Returns bytes written.
size_t buildHello(char* buf, size_t buf_size);

// Build full "status" snapshot from current CarState. Takes the car_state mutex internally.
size_t buildStatus(char* buf, size_t buf_size);

// Build "fast" frame (rpm/speed/throttle only).
size_t buildFast(char* buf, size_t buf_size);

// Build "ack" for a completed command.
size_t buildAck(char* buf, size_t buf_size, const char* cmd, bool ok);

// Parse one incoming JSON line. If it's a known command, push to cmdQueue
// (with the given source) and return the command type. Returns CMD_NONE on
// failure or unknown command.
//
// Recognised forms:
//   {"cmd":"lock"} / "unlock" / "drl_on" / "drl_off" / "refresh"
//   {"cmd":"config","auto_lock":true,"lock_speed":20, ...}  -> updates NVS, no enqueue
CmdType parseAndDispatch(const char* line, size_t len, CmdSource source);

}  // namespace json_proto
