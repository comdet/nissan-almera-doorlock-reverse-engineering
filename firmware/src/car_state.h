/*
 * CarState — latest decoded values from the car.
 * Phase 2: protected by a FreeRTOS mutex. Always use car_state::lock/unlock
 * (or the RAII Guard) when reading or writing fields.
 */

#pragma once

#include <stdint.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

struct CarState {
    // OBD-II values
    int16_t  rpm        = -1;   // rpm, -1 = unknown
    int16_t  speed      = -1;   // km/h
    int16_t  coolant    = -127; // °C (-40 .. 215), -127 = unknown
    int16_t  ambient    = -127; // °C
    int16_t  throttle_x10 = -1; // % * 10, -1 = unknown
    int16_t  battery_mv = -1;   // mV, -1 = unknown
    bool     mil        = false;
    uint8_t  dtc_count  = 0;

    // BCM DID 0x0109
    bool door_driver_open    = false;
    bool door_passenger_open = false;
    bool door_rear_left_open = false;
    bool door_rear_right_open = false;
    bool door_trunk_open     = false;
    bool locked              = false;  // false = unknown/unlocked, set from byte 8
    bool unlocked            = false;
    bool brake_pedal         = false;
    bool light_high_beam     = false;
    bool light_parking       = false;
    bool turn_left           = false;
    bool turn_right          = false;
    uint8_t headlight_state  = 0;      // raw byte 5

    // Engine ECU DID 0x1301 byte 3 — gear position (works engine off too)
    char gear[3] = "?";   // "P","R","N","D","L","?"

    // Light ECU DID 0x0E07
    bool    handbrake       = false;  // byte 19 bit 4 (0x10)
    uint8_t e07_byte19_raw  = 0;      // for debug — full bitmask

    // Engine ECU DID 0x1304 byte 3
    bool engine_running = false;
    uint8_t engine_status_1304 = 0;

    // Timestamps (millis) — when value was last updated
    uint32_t ts_obd_fast    = 0;
    uint32_t ts_obd_med     = 0;
    uint32_t ts_obd_slow    = 0;
    uint32_t ts_did_0109    = 0;
    uint32_t ts_did_1301    = 0;
    uint32_t ts_did_0e07    = 0;
    uint32_t ts_did_1304    = 0;
};

namespace car_state {

extern CarState state;

void init();                              // create mutex
bool lock(uint32_t timeout_ms = 100);     // returns true if acquired
void unlock();

// RAII helper — auto-unlock at scope exit.
class Guard {
public:
    explicit Guard(uint32_t timeout_ms = 100) : ok_(lock(timeout_ms)) {}
    ~Guard() { if (ok_) unlock(); }
    bool ok() const { return ok_; }
private:
    bool ok_;
};

}  // namespace car_state

