/*
 * Phase 2 — canPollTask: sole owner of the CAN bus.
 *
 * Responsibilities:
 *   - Poll OBD PIDs and manufacturer DIDs on schedule (fast/medium/slow tiers)
 *   - Drain cmdQueue and execute lock/unlock/DRL via UDS
 *   - DRL keep-alive (TesterPresent every ~1.2s while drl_active = true)
 *   - Update car_state::state under mutex
 */

#pragma once

#include <stdint.h>

namespace poll_task {

void start(uint32_t stack = 6144, uint8_t priority = 3);

// Read-only stats (safe to call from any task — uses internal atomics-ish vars).
uint32_t getPollOk();
uint32_t getPollFail();
bool     isDrlActive();

}  // namespace poll_task
