/*
 * Config portal — alternative boot mode.
 *
 * Entered when nvs_cfg::cfg.config_mode_next_boot is true at boot. The portal:
 *   - Disables WiFi STA and any CAN polling.
 *   - Brings up a WiFi AP (CFG_AP_SSID / CFG_AP_PASS).
 *   - Serves an HTML form at http://192.168.4.1/ to edit all NVS fields.
 *   - On /save POST: writes NVS, clears config_mode_next_boot, then reboots.
 *
 * run() never returns — it blocks the main thread (no other tasks should be
 * running in this mode).
 */

#pragma once

namespace config_portal {

void run();

}  // namespace config_portal
