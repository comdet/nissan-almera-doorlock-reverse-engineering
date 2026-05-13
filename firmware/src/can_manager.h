/*
 * Phase 1 — CAN/UDS layer.
 * Owns the TWAI driver. Blocking ISO-TP read + blocking OBD query.
 */

#pragma once

#include <stdint.h>
#include <stddef.h>
#include "driver/twai.h"

namespace can_mgr {

bool init();
void deinit();
bool sendFrame(uint32_t id, const uint8_t* data, uint8_t len);

// Drain TWAI RX queue, optionally returning the first frame whose ID matches expected_id.
// timeout_ms: how long to wait for the matching frame.
// Returns true if a matching frame was captured into out.
bool waitFrame(uint32_t expected_id, twai_message_t* out, uint32_t timeout_ms);

// UDS Diagnostic Session Control. Returns true on positive response.
bool udsSetSession(uint32_t req_id, uint32_t resp_id, uint8_t session);

// UDS ReadDataByIdentifier (0x22) with ISO-TP multiframe + NRC 0x78 handling.
// Performs ExtSession -> Read -> DefaultSession.
// Writes the UDS payload (starting with 0x62 ...) into out buffer.
// Returns number of bytes written, or 0 on failure.
size_t udsReadDid(uint32_t req_id, uint32_t resp_id, uint16_t did,
                  uint8_t* out, size_t max_len);

// OBD-II Mode 01 query via 0x7DF. Writes response bytes (after [41 PID]) into out.
// Returns number of bytes written, or 0 on failure.
size_t obdQuery(uint8_t pid, uint8_t* out, size_t max_len);

// Status helpers
uint32_t getRxMissed();
uint32_t getTxFailed();

// ---------------- UDS commands (IOControl + session helpers) ----------------

// UDS TesterPresent (0x3E 00) to a given ECU.
bool udsTesterPresent(uint32_t req_id, uint32_t resp_id);

// IOControlByIdentifier with shortTermAdjustment (controlParam = 0x03).
// state_a/state_b are the two payload bytes (e.g. [0x00, 0x01]).
// Performs: ExtSession -> TesterPresent -> IOControl. Caller chooses whether
// to return to default session (close=true) or keep extended (close=false).
bool udsIoControlShortAdj(uint32_t req_id, uint32_t resp_id, uint16_t did,
                          uint8_t state_a, uint8_t state_b, bool close = true);

}  // namespace can_mgr
