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

// True when the car has been PARKED long enough that we're in low-power mode
// (WiFi off, polling slowed to a single RPM ping every ~30s). Comms tasks
// (wifi_task) should suspend themselves while this is true.
bool isLowPower();

// Set the parameters for the next CMD_SCAN. Call this from a comms task,
// then push CMD_SCAN to the queue — canPoll will pick it up and run.
void setScanRange(uint32_t req_id, uint32_t resp_id, uint16_t did_start, uint16_t did_end);

}  // namespace poll_task
