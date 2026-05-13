/*
 * Phase 1 — Decode DID/PID raw bytes into CarState.
 * Mapping rules verified in DECODED_DIDS.md.
 */

#pragma once

#include <stdint.h>
#include <stddef.h>
#include "car_state.h"

namespace decode {

// UDS payload starts with [62 DID_H DID_L ...] for ReadDataByIdentifier responses.
// Pass the full payload (including the 62 header).
void did0109(const uint8_t* data, size_t len, CarState& s);  // BCM doors/lock/lights
void did0108(const uint8_t* data, size_t len, CarState& s);  // gear
void did0E07(const uint8_t* data, size_t len, CarState& s);  // handbrake
void did1304(const uint8_t* data, size_t len, CarState& s);  // engine running

// OBD: data is the bytes after [41 PID], i.e. the value bytes only.
void obdRpm(const uint8_t* data, size_t len, CarState& s);
void obdSpeed(const uint8_t* data, size_t len, CarState& s);
void obdCoolant(const uint8_t* data, size_t len, CarState& s);
void obdThrottle(const uint8_t* data, size_t len, CarState& s);
void obdBattery(const uint8_t* data, size_t len, CarState& s);
void obdAmbient(const uint8_t* data, size_t len, CarState& s);
void obdMil(const uint8_t* data, size_t len, CarState& s);

}  // namespace decode
