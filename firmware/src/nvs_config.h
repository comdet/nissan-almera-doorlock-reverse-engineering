/*
 * Phase 3 — Non-volatile config via ESP32 Preferences (NVS).
 *
 * Loaded once at boot into the global Config struct. Mutate fields directly
 * for in-RAM changes; call save() to persist. Keys match FIRMWARE_PLAN.md.
 */

#pragma once

#include <stdint.h>
#include <Arduino.h>

struct Config {
    // WiFi (STA mode — connect to HUD's AP)
    char     wifi_ssid[33];      // up to 32 chars + null
    char     wifi_pass[65];      // up to 64 chars + null
    uint16_t tcp_port;           // HUD server port
    bool     wifi_enabled;       // master switch — set false to keep ESP32 standalone

    // Auto-feature toggles
    bool     auto_lock;          // lock at speed
    bool     auto_unlock;        // unlock after engine off
    bool     auto_drl;           // DRL on when engine running

    // Thresholds
    uint8_t  lock_speed;         // km/h threshold (auto-lock fires above this)
    uint8_t  unlock_delay;       // seconds after engine off before unlock

    // Output toggles
    bool     json_on_serial;     // true = emit JSON on Serial; false = pretty text

    // Transient — set true to enter the web config portal on next boot.
    // Cleared automatically when the portal starts.
    bool     config_mode_next_boot;
};

namespace nvs_cfg {

extern Config cfg;

// Load values from NVS into cfg. Writes defaults for missing keys.
// Returns true on success.
bool load();

// Persist current cfg into NVS.
bool save();

// Reset everything to defaults and persist.
bool resetDefaults();

// Print the current config to Serial.
void print();

}  // namespace nvs_cfg
