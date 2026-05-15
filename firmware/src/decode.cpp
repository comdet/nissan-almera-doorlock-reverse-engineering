#include "decode.h"
#include <string.h>

namespace decode {

// ---------------- Manufacturer DIDs ----------------

void did0109(const uint8_t* data, size_t len, CarState& s) {
    // Need at least [62 01 09 b3 b4 b5 b6 b7 b8 ...]
    if (len < 9) return;
    if (data[0] != 0x62 || data[1] != 0x01 || data[2] != 0x09) return;

    // Lights / signals (byte 4)
    uint8_t b4 = data[4];
    s.turn_right       = (b4 & 0x08) != 0;
    s.turn_left        = (b4 & 0x04) != 0;
    s.light_parking    = (b4 & 0x02) != 0;
    s.light_high_beam  = (b4 & 0x01) != 0;

    // Headlight state (byte 5): 0x42 off, 0x02 parking, 0x82 headlight
    s.headlight_state = data[5];

    // Door open bitmask (byte 6)
    uint8_t b6 = data[6];
    s.door_driver_open     = (b6 & 0x80) != 0;
    s.door_passenger_open  = (b6 & 0x40) != 0;
    s.door_rear_left_open  = (b6 & 0x20) != 0;
    s.door_rear_right_open = (b6 & 0x10) != 0;
    s.door_trunk_open      = (b6 & 0x08) != 0;

    // Lock state (byte 8): 0x00 locked, 0x10 unlocked
    uint8_t b8 = data[8];
    s.locked   = (b8 == 0x00);
    s.unlocked = (b8 == 0x10);

    // NOTE: byte 17 was previously decoded as brake-pedal but it turned out
    // to be stale — it stays at 0x0C through key off and doesn't reflect the
    // pedal in real time. The reliable brake source is DID 0x0E07 byte 19
    // bit 3 (see did0E07). Byte 17 is left undecoded for now.
}

void did1301(const uint8_t* data, size_t len, CarState& s) {
    // [62 13 01 byte3] — 4 bytes single frame from Engine ECU 0x7E1
    // Verified 2026-04-17 on car: all 5 positions + engine off (ACC on).
    // 0x10 P, 0x20 R, 0x40 N, 0x80 D, 0x08 L
    if (len < 4) return;
    if (data[0] != 0x62 || data[1] != 0x13 || data[2] != 0x01) return;

    uint8_t b3 = data[3];
    switch (b3) {
        case 0x10: strcpy(s.gear, "P"); break;
        case 0x20: strcpy(s.gear, "R"); break;
        case 0x40: strcpy(s.gear, "N"); break;
        case 0x80: strcpy(s.gear, "D"); break;
        case 0x08: strcpy(s.gear, "L"); break;
        default:   strcpy(s.gear, "?"); break;
    }
}

void did0E07(const uint8_t* data, size_t len, CarState& s) {
    // Need [62 0E 07 ... up to byte 19]
    if (len < 20) return;
    if (data[0] != 0x62 || data[1] != 0x0E || data[2] != 0x07) return;

    // Byte 19 is a bitmask — verified on the car 2026-05-15:
    //   bit 4 (0x10) = handbrake / parking-brake engaged (held across engine
    //                   off when the ECU is alive; may drop when ECU sleeps)
    //   bit 3 (0x08) = brake pedal pressed (real-time, reliable)
    // Observed values: 0x00, 0x08, 0x10, 0x18 — all combos of the two bits.
    //
    // The earlier "byte 19 == 0x10" check captured handbrake correctly when
    // the brake pedal was released (only path with bit 4 set), but reported
    // handbrake=false when the driver was both pulling the parking brake AND
    // pressing the pedal (which is the normal park sequence). Use bit
    // arithmetic so both signals are independent.
    uint8_t b19 = data[19];
    s.handbrake     = (b19 & 0x10) != 0;
    s.brake_pedal   = (b19 & 0x08) != 0;   // overrides the stale BCM byte 17 source
    s.e07_byte19_raw = b19;
}

void did1304(const uint8_t* data, size_t len, CarState& s) {
    // [62 13 04 byte3] — 4 bytes total
    if (len < 4) return;
    if (data[0] != 0x62 || data[1] != 0x13 || data[2] != 0x04) return;

    uint8_t b3 = data[3];
    s.engine_status_1304 = b3;
    s.engine_running = (b3 == 0x06);
}

// ---------------- OBD-II PIDs ----------------

void obdRpm(const uint8_t* data, size_t len, CarState& s) {
    if (len < 2) return;
    uint16_t raw = ((uint16_t)data[0] << 8) | data[1];
    s.rpm = (int16_t)(raw / 4);
}

void obdSpeed(const uint8_t* data, size_t len, CarState& s) {
    if (len < 1) return;
    s.speed = (int16_t)data[0];
}

void obdCoolant(const uint8_t* data, size_t len, CarState& s) {
    if (len < 1) return;
    s.coolant = (int16_t)data[0] - 40;
}

void obdThrottle(const uint8_t* data, size_t len, CarState& s) {
    if (len < 1) return;
    // % * 10 to keep one decimal in integer
    s.throttle_x10 = (int16_t)((uint32_t)data[0] * 1000 / 255);
}

void obdBattery(const uint8_t* data, size_t len, CarState& s) {
    if (len < 2) return;
    uint16_t raw = ((uint16_t)data[0] << 8) | data[1];
    s.battery_mv = (int16_t)raw;  // already mV
}

void obdAmbient(const uint8_t* data, size_t len, CarState& s) {
    if (len < 1) return;
    s.ambient = (int16_t)data[0] - 40;
}

void obdMil(const uint8_t* data, size_t len, CarState& s) {
    if (len < 1) return;
    s.mil       = (data[0] & 0x80) != 0;
    s.dtc_count = data[0] & 0x7F;
}

}  // namespace decode
