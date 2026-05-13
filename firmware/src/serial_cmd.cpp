#include "serial_cmd.h"
#include "cmd_queue.h"
#include "car_state.h"
#include "nvs_config.h"
#include "json_protocol.h"
#include "wifi_task.h"
#include "poll_task.h"
#include "config.h"
#include "can_manager.h"
#include <Arduino.h>
#include <string.h>
#include <stdlib.h>

namespace serial_cmd {

static char   buf[256];
static size_t len = 0;

static const char* boolStr(bool v) { return v ? "YES" : "no "; }

void printSnapshotText() {
    car_state::Guard g;
    if (!g.ok()) { Serial.println("[snapshot] lock timeout"); return; }
    const CarState& s = car_state::state;

    Serial.println();
    Serial.println("================ Almera N18 — Snapshot ================");
    Serial.printf("state: %s  uptime: %lus  pollOK/fail: %lu/%lu  drl=%s  rxMiss=%lu txFail=%lu\n",
                  poll_task::getStateName(), millis() / 1000,
                  poll_task::getPollOk(), poll_task::getPollFail(),
                  poll_task::isDrlActive() ? "ON" : "off",
                  can_mgr::getRxMissed(), can_mgr::getTxFailed());
    Serial.println("-- Engine --");
    Serial.printf("  RPM         : %d\n", s.rpm);
    Serial.printf("  Speed       : %d km/h\n", s.speed);
    Serial.printf("  Coolant     : %d C\n", s.coolant);
    Serial.printf("  Throttle    : %d.%d %%\n",
                  s.throttle_x10 / 10, s.throttle_x10 >= 0 ? (s.throttle_x10 % 10) : 0);
    Serial.printf("  Battery     : %d.%03d V\n",
                  s.battery_mv / 1000, s.battery_mv >= 0 ? (s.battery_mv % 1000) : 0);
    Serial.printf("  Ambient     : %d C\n", s.ambient);
    Serial.printf("  Running     : %s  (0x1304 b3=0x%02X)\n",
                  boolStr(s.engine_running), s.engine_status_1304);
    Serial.printf("  MIL         : %s  dtc=%u\n", boolStr(s.mil), s.dtc_count);
    Serial.println("-- Transmission --");
    Serial.printf("  Gear        : %s\n", s.gear);
    Serial.printf("  Handbrake   : %s\n", boolStr(s.handbrake));
    Serial.println("-- Body --");
    Serial.printf("  Locked      : %s\n", boolStr(s.locked));
    Serial.printf("  Doors       : drv=%s pass=%s RL=%s RR=%s trunk=%s\n",
                  boolStr(s.door_driver_open),
                  boolStr(s.door_passenger_open),
                  boolStr(s.door_rear_left_open),
                  boolStr(s.door_rear_right_open),
                  boolStr(s.door_trunk_open));
    Serial.printf("  Brake pedal : %s\n", boolStr(s.brake_pedal));
    Serial.println("-- Lights --");
    Serial.printf("  Headlight   : 0x%02X\n", s.headlight_state);
    Serial.printf("  Parking     : %s   High beam: %s\n",
                  boolStr(s.light_parking), boolStr(s.light_high_beam));
    Serial.printf("  Turn        : L=%s R=%s\n",
                  boolStr(s.turn_left), boolStr(s.turn_right));
}

void printHelp() {
    Serial.println();
    Serial.println("-- commands --");
    Serial.println("  lock | unlock | drl on | drl off | refresh");
    Serial.println("  status              show car snapshot");
    Serial.println("  config              show config");
    Serial.println("  config <key> <val>  set: auto_lock/auto_unlock/auto_drl (true|false),");
    Serial.println("                           lock_speed/unlock_delay (int),");
    Serial.println("                           json_on_serial/wifi_enabled (true|false),");
    Serial.println("                           wifi_ssid/wifi_pass (string), tcp_port (int)");
    Serial.println("  save                persist config to NVS");
    Serial.println("  reset               reset config to defaults");
    Serial.println("  wifi info           show WiFi/TCP status");
    Serial.println("  json on | json off  toggle Serial JSON output");
    Serial.println("  help                this menu");
    Serial.println("  reboot              restart ESP32");
    Serial.println("  portal              reboot into web config portal (or hold BOOT 3s)");
    Serial.println();
}

static void printWifiInfo() {
    wifi_task::Info i = wifi_task::snapshot();
    Serial.println("-- WiFi --");
    Serial.printf("  enabled    : %s\n", i.wifi_enabled ? "true" : "false");
    Serial.printf("  wifi_conn  : %s\n", i.wifi_connected ? "yes" : "no");
    Serial.printf("  tcp_conn   : %s\n", i.tcp_connected ? "yes" : "no");
    if (i.wifi_connected) {
        Serial.printf("  rssi       : %d dBm\n", i.rssi);
        Serial.printf("  ip         : %u.%u.%u.%u\n",
                      i.ip_v4 & 0xFF, (i.ip_v4 >> 8) & 0xFF,
                      (i.ip_v4 >> 16) & 0xFF, (i.ip_v4 >> 24) & 0xFF);
        Serial.printf("  gateway    : %u.%u.%u.%u  port=%u\n",
                      i.gateway_v4 & 0xFF, (i.gateway_v4 >> 8) & 0xFF,
                      (i.gateway_v4 >> 16) & 0xFF, (i.gateway_v4 >> 24) & 0xFF,
                      nvs_cfg::cfg.tcp_port);
    }
    Serial.printf("  tcp_recon  : %lu  bytes tx=%lu rx=%lu\n",
                  i.tcp_reconnects, i.bytes_tx, i.bytes_rx);
}

static bool parseBool(const char* s, bool* out) {
    if (!s) return false;
    if (!strcmp(s, "true")  || !strcmp(s, "on")  || !strcmp(s, "1")) { *out = true;  return true; }
    if (!strcmp(s, "false") || !strcmp(s, "off") || !strcmp(s, "0")) { *out = false; return true; }
    return false;
}

// Modifies arg in-place: returns key in *key and value in *val (rest of line).
static void splitKV(char* arg, char** key, char** val) {
    *key = arg;
    while (*arg && *arg != ' ' && *arg != '\t') arg++;
    if (*arg) {
        *arg++ = '\0';
        while (*arg == ' ' || *arg == '\t') arg++;
    }
    *val = arg;
}

static bool setConfigKey(const char* key, const char* val) {
    if (!val || !*val) return false;
    bool b;
    if (!strcmp(key, "auto_lock"))    { if (parseBool(val, &b)) { nvs_cfg::cfg.auto_lock = b; return true; } }
    else if (!strcmp(key, "auto_unlock")) { if (parseBool(val, &b)) { nvs_cfg::cfg.auto_unlock = b; return true; } }
    else if (!strcmp(key, "auto_drl"))    { if (parseBool(val, &b)) { nvs_cfg::cfg.auto_drl = b; return true; } }
    else if (!strcmp(key, "json_on_serial")) { if (parseBool(val, &b)) { nvs_cfg::cfg.json_on_serial = b; return true; } }
    else if (!strcmp(key, "wifi_enabled"))   { if (parseBool(val, &b)) { nvs_cfg::cfg.wifi_enabled = b; return true; } }
    else if (!strcmp(key, "lock_speed"))   { nvs_cfg::cfg.lock_speed   = (uint8_t)atoi(val); return true; }
    else if (!strcmp(key, "unlock_delay")) { nvs_cfg::cfg.unlock_delay = (uint8_t)atoi(val); return true; }
    else if (!strcmp(key, "tcp_port"))     { nvs_cfg::cfg.tcp_port     = (uint16_t)atoi(val); return true; }
    else if (!strcmp(key, "wifi_ssid"))    {
        strncpy(nvs_cfg::cfg.wifi_ssid, val, sizeof(nvs_cfg::cfg.wifi_ssid) - 1);
        nvs_cfg::cfg.wifi_ssid[sizeof(nvs_cfg::cfg.wifi_ssid) - 1] = '\0';
        return true;
    }
    else if (!strcmp(key, "wifi_pass"))    {
        strncpy(nvs_cfg::cfg.wifi_pass, val, sizeof(nvs_cfg::cfg.wifi_pass) - 1);
        nvs_cfg::cfg.wifi_pass[sizeof(nvs_cfg::cfg.wifi_pass) - 1] = '\0';
        return true;
    }
    return false;
}

static void dispatch(char* line) {
    // Trim leading whitespace
    while (*line == ' ' || *line == '\t') line++;
    if (!*line) return;

    // JSON?
    if (*line == '{') {
        CmdType t = json_proto::parseAndDispatch(line, strlen(line), SRC_SERIAL);
        Serial.printf("[json] -> %s\n", cmd_queue::typeLabel(t));
        return;
    }

    // Strip trailing whitespace
    size_t l = strlen(line);
    while (l && (line[l-1] == ' ' || line[l-1] == '\t')) line[--l] = '\0';

    // Text commands — split first token vs rest
    char* cmd = line;
    char* arg = line;
    while (*arg && *arg != ' ' && *arg != '\t') arg++;
    if (*arg) { *arg++ = '\0'; while (*arg == ' ' || *arg == '\t') arg++; }

    if (!strcmp(cmd, "lock"))      { cmd_queue::push(CMD_LOCK,    SRC_SERIAL); Serial.println("[cmd] lock queued"); }
    else if (!strcmp(cmd, "unlock"))  { cmd_queue::push(CMD_UNLOCK,  SRC_SERIAL); Serial.println("[cmd] unlock queued"); }
    else if (!strcmp(cmd, "refresh")) { cmd_queue::push(CMD_REFRESH, SRC_SERIAL); Serial.println("[cmd] refresh queued"); }
    else if (!strcmp(cmd, "drl")) {
        if (!strcmp(arg, "on"))       { cmd_queue::push(CMD_DRL_ON,  SRC_SERIAL); Serial.println("[cmd] drl on queued"); }
        else if (!strcmp(arg, "off")) { cmd_queue::push(CMD_DRL_OFF, SRC_SERIAL); Serial.println("[cmd] drl off queued"); }
        else Serial.println("? drl on | drl off");
    }
    else if (!strcmp(cmd, "json")) {
        if (!strcmp(arg, "on"))       { nvs_cfg::cfg.json_on_serial = true;  Serial.println("[cfg] json_on_serial = true"); }
        else if (!strcmp(arg, "off")) { nvs_cfg::cfg.json_on_serial = false; Serial.println("[cfg] json_on_serial = false"); }
        else Serial.println("? json on | json off");
    }
    else if (!strcmp(cmd, "wifi")) {
        if (!strcmp(arg, "info") || !*arg) { printWifiInfo(); }
        else if (!strcmp(arg, "on"))   { nvs_cfg::cfg.wifi_enabled = true;  Serial.println("[cfg] wifi_enabled = true"); }
        else if (!strcmp(arg, "off"))  { nvs_cfg::cfg.wifi_enabled = false; Serial.println("[cfg] wifi_enabled = false"); }
        else Serial.println("? wifi info | wifi on | wifi off");
    }
    else if (!strcmp(cmd, "status"))  { printSnapshotText(); }
    else if (!strcmp(cmd, "config"))  {
        if (!*arg) { nvs_cfg::print(); return; }
        char* k; char* v;
        splitKV(arg, &k, &v);
        if (setConfigKey(k, v)) Serial.printf("[cfg] %s = %s\n", k, v);
        else Serial.printf("? unknown key or bad value: %s\n", k);
    }
    else if (!strcmp(cmd, "save"))    { Serial.printf("[cfg] save %s\n", nvs_cfg::save() ? "ok" : "FAIL"); }
    else if (!strcmp(cmd, "reset"))   { nvs_cfg::resetDefaults(); Serial.println("[cfg] reset to defaults"); }
    else if (!strcmp(cmd, "help") || !strcmp(cmd, "?")) { printHelp(); }
    else if (!strcmp(cmd, "reboot"))  { Serial.println("rebooting..."); delay(200); ESP.restart(); }
    else if (!strcmp(cmd, "portal"))  {
        nvs_cfg::cfg.config_mode_next_boot = true;
        nvs_cfg::save();
        Serial.println("rebooting into config portal...");
        delay(200); ESP.restart();
    }
    else Serial.printf("? unknown: %s  (try: help)\n", cmd);
}

void poll() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\r' || c == '\n') {
            if (len > 0) {
                buf[len] = '\0';
                dispatch(buf);
                len = 0;
            }
        } else if (len < sizeof(buf) - 1) {
            buf[len++] = c;
        } else {
            // overflow — reset
            len = 0;
        }
    }
}

}  // namespace serial_cmd
