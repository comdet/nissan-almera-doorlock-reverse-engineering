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

// Body ECU 2: gear (DID 0x0108, 45 bytes, NRC 0x78)
static const uint32_t BODY2_REQ  = 0x74C;
static const uint32_t BODY2_RESP = 0x76C;

// Light ECU: handbrake (DID 0x0E07, 22 bytes)
static const uint32_t LIGHT_REQ  = 0x743;
static const uint32_t LIGHT_RESP = 0x763;

// Engine ECU (TCM/ECM): engine status (DID 0x1304)
static const uint32_t ENG_REQ  = 0x7E1;
static const uint32_t ENG_RESP = 0x7E9;

// OBD-II broadcast
static const uint32_t OBD_BROADCAST = 0x7DF;
static const uint32_t OBD_RESP_ECM  = 0x7E8;

// ---------------- DIDs (verified) ----------------
static const uint16_t DID_DOOR_BODY   = 0x0109;  // BCM   — 18 bytes
static const uint16_t DID_GEAR        = 0x0108;  // 0x74C — 45 bytes, NRC 0x78
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

// ---------------- Polling intervals (ms) ----------------
// Phase 1: simple sequential polling — values are nominal
static const uint32_t POLL_FAST_MS   = 500;    // RPM, Speed, Throttle
static const uint32_t POLL_MED_MS    = 2000;   // DID 0x0109, DID 0x0E07, Coolant, Battery
static const uint32_t POLL_SLOW_MS   = 10000;  // DID 0x0108 (gear), DID 0x1304, Ambient, MIL
static const uint32_t PRINT_MS       = 2000;   // print snapshot

// ---------------- UDS timing ----------------
static const uint32_t TIMEOUT_FRAME_MS    = 800;
static const uint32_t TIMEOUT_PENDING_MS  = 5000;
static const uint32_t INTER_FRAME_MS      = 30;
