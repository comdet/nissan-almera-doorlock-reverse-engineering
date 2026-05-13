/*
 * Phase 2 — canPollTask: sole owner of the CAN bus.
 *
 * Responsibilities:
 *   - Poll OBD PIDs and manufacturer DIDs based on driving state
 *   - Drive 8-state state machine (ACC_ON, ENGINE_ON, DRIVING, LOCKED_CRUISING,
 *     LOCKED_STOPPED, REARM, ENGINE_OFF, PARKED) — see STATE_MACHINE.md
 *   - Trigger auto-feature commands (lock at speed, unlock after engine off,
 *     DRL on with engine, circular re-lock after door event)
 *   - Drain cmdQueue and execute commands via UDS
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

// Current state-machine state for status display / debugging.
const char* getStateName();

}  // namespace poll_task
