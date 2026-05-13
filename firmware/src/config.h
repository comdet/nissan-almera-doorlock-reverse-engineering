/*
 * Phase 1 — CAN pins, IDs, DIDs, polling intervals
 * Verified from Python scripts working on the actual car (2026-04-15/16)
 */

#pragma once

#include <stdint.h>

// ---------------- Hardware ----------------
// ESP32-C3 Super Mini + SN65HVD230
// GPIO4 = CAN TX, GPIO3 = CAN RX (matches existing SLCAN firmware)
#define CAN_TX_PIN  4
#define CAN_RX_PIN  3
#define CAN_BITRATE 500000UL

#define SERIAL_BAUD 115200UL

// Built-in BOOT button on ESP32-C3-DevKitM-1 and Super Mini boards.
// Active LOW (pressed = LOW), has on-board pull-up.
#define BUTTON_PIN          9
#define BUTTON_HOLD_MS      3000   // hold this long to enter config mode

// Config portal (AP mode)
#define CFG_AP_SSID         "AlmeraConfig"
#define CFG_AP_PASS         "12345678"
#define CFG_AP_PORT         80

// ---------------- CAN IDs (verified) ----------------
// BCM: door lock/unlock, DRL, body status
static const uint32_t BCM_REQ  = 0x745;
static const uint32_t BCM_RESP = 0x765;

// Light ECU: handbrake (DID 0x0E07, 22 bytes)
static const uint32_t LIGHT_REQ  = 0x743;
static const uint32_t LIGHT_RESP = 0x763;

// Engine ECU (TCM/ECM): gear (DID 0x1301) + engine status (DID 0x1304)
// Gear via 0x1301 — single frame, fast, all 5 positions (P/R/N/D/L), works engine off
static const uint32_t ENG_REQ  = 0x7E1;
static const uint32_t ENG_RESP = 0x7E9;

// OBD-II broadcast
static const uint32_t OBD_BROADCAST = 0x7DF;
static const uint32_t OBD_RESP_ECM  = 0x7E8;

// ---------------- DIDs (verified) ----------------
static const uint16_t DID_DOOR_BODY   = 0x0109;  // BCM   — 18 bytes
static const uint16_t DID_GEAR        = 0x1301;  // 0x7E1 — 4 bytes single frame (P/R/N/D/L)
static const uint16_t DID_HANDBRAKE   = 0x0E07;  // 0x743 — 22 bytes
static const uint16_t DID_ENGINE_RUN  = 0x1304;  // 0x7E1 — 4 bytes

// ---------------- OBD-II PIDs (verified supported) ----------------
static const uint8_t PID_ENGINE_LOAD  = 0x04;
static const uint8_t PID_COOLANT      = 0x05;
static const uint8_t PID_RPM          = 0x0C;
static const uint8_t PID_SPEED        = 0x0D;
static const uint8_t PID_THROTTLE     = 0x11;
static const uint8_t PID_BATTERY      = 0x42;
static const uint8_t PID_AMBIENT      = 0x46;
static const uint8_t PID_MIL_DTC      = 0x01;

// ---------------- UDS service IDs ----------------
static const uint8_t SID_SESSION_CTRL = 0x10;
static const uint8_t SID_READ_DID     = 0x22;
static const uint8_t SID_TESTER_PRES  = 0x3E;
static const uint8_t SID_IO_CONTROL   = 0x2F;
static const uint8_t SID_NEG_RESP     = 0x7F;

static const uint8_t SESSION_DEFAULT  = 0x01;
static const uint8_t SESSION_EXTENDED = 0x03;

static const uint8_t NRC_RESPONSE_PENDING = 0x78;

// ---------------- Polling intervals (ms) — per state ----------------
// State-driven polling: rate depends on what the driver is doing right now.
// OBD PIDs (0x7DF) are safe to poll freely. Manufacturer DIDs require
// ExtendedSession — poll those less when not needed. BCM 0x0109 is "free"
// while DRL is active (BCM already in ExtSession via TesterPresent keep-alive).

// ACC_ON: key turned, waiting for engine
static const uint32_t POLL_ACC_RPM_MS   = 2000;
static const uint32_t POLL_ACC_BATT_MS  = 10000;

// ENGINE_ON: running, not yet moving
static const uint32_t POLL_ENGON_FAST_MS = 1000;
static const uint32_t POLL_ENGON_MED_MS  = 5000;
static const uint32_t POLL_ENGON_BCM_MS  = 3000;
static const uint32_t POLL_ENGON_GEAR_MS = 5000;
static const uint32_t POLL_ENGON_HBRK_MS = 5000;
static const uint32_t POLL_ENGON_ENG_MS  = 10000;

// DRIVING / LOCKED_CRUISING: full HUD data
static const uint32_t POLL_DRV_FAST_MS  = 1000;
static const uint32_t POLL_DRV_MED_MS   = 3000;
static const uint32_t POLL_DRV_SLOW_MS  = 15000;
static const uint32_t POLL_DRV_BCM_MS   = 2000;
static const uint32_t POLL_DRV_GEAR_MS  = 10000;  // keep fresh — avoid stale "?" if a stall pushes us to ENGINE_OFF check

// LOCKED_STOPPED / REARM: watching doors + idle stop
static const uint32_t POLL_STOP_FAST_MS = 1000;
static const uint32_t POLL_STOP_BCM_MS  = 2000;
static const uint32_t POLL_STOP_GEAR_MS = 3000;

// ENGINE_OFF: countdown — keep this short so restart-cancel is responsive
static const uint32_t POLL_OFF_RPM_MS   = 500;

// PARKED: safety check (only during first LOWPOWER_DELAY_MS), then low-power
static const uint32_t POLL_PARK_BCM_MS    = 5000;
static const uint32_t POLL_PARK_GEAR_MS   = 10000;
static const uint32_t POLL_PARK_HBRK_MS   = 10000;

// Low-power mode — car has been parked long enough that we don't need to
// keep WiFi up or poll status. Only ping RPM occasionally to detect restart.
static const uint32_t LOWPOWER_ENTER_MS   = 30000;   // 30s in PARKED before going low-power
static const uint32_t POLL_PARK_LP_RPM_MS = 30000;   // ping RPM every 30s while low-power
static const uint32_t LOWPOWER_TASK_DELAY_MS = 500;  // longer vTaskDelay between iterations

// If no CAN response for this long in any non-driving state, assume the bus
// is dead (ACC off / car parked) and enter low-power mode regardless of which
// state we're nominally in. Handles boot-with-no-car and stuck states.
static const uint32_t NO_RESP_LOWPOWER_MS = 60000;   // 60s of failed polls

// DRL keep-alive (BCM TesterPresent while drl_active)
static const uint32_t DRL_TP_INTERVAL_MS = 1200;

// Dashboard print
static const uint32_t PRINT_MS = 2000;

// ---------------- UDS timing ----------------
static const uint32_t TIMEOUT_FRAME_MS    = 800;
// Used to be 5000 to accommodate DID 0x0108's NRC 0x78 ~3s delay. We dropped
// that DID (gear is now read via single-frame 0x1301) so every DID we touch
// answers under 500ms when alive. Lower timeout means the canPoll task
// recovers in 1.5s instead of 5s when the engine ECU goes silent at shutdown
// — that 3.5s saving is the difference between auto-unlock feeling instant
// vs feeling laggy.
static const uint32_t TIMEOUT_PENDING_MS  = 1500;
static const uint32_t INTER_FRAME_MS      = 30;
