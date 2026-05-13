#include "json_protocol.h"
#include "car_state.h"
#include "nvs_config.h"
#include "config.h"
#include <ArduinoJson.h>
#include <Arduino.h>

namespace json_proto {

static const char* FW_VERSION = "0.2.0";
static const char* CAR_MODEL  = "almera_n18";

size_t buildHello(char* buf, size_t buf_size) {
    JsonDocument doc;
    doc["type"]   = "hello";
    doc["fw"]     = FW_VERSION;
    doc["car"]    = CAR_MODEL;
    doc["uptime"] = millis() / 1000;
    size_t n = serializeJson(doc, buf, buf_size);
    if (n + 1 < buf_size) { buf[n++] = '\n'; buf[n] = '\0'; }
    return n;
}

size_t buildStatus(char* buf, size_t buf_size) {
    JsonDocument doc;
    doc["type"] = "status";
    doc["ts"]   = millis();

    {
        car_state::Guard g;
        if (!g.ok()) return 0;
        const CarState& s = car_state::state;

        if (s.rpm >= 0)             doc["rpm"]      = s.rpm;
        if (s.speed >= 0)           doc["speed"]    = s.speed;
        if (s.throttle_x10 >= 0)    doc["throttle"] = s.throttle_x10 / 10.0;
        if (s.coolant > -127)       doc["coolant"]  = s.coolant;
        if (s.ambient > -127)       doc["ambient"]  = s.ambient;
        if (s.battery_mv >= 0)      doc["battery"]  = s.battery_mv / 1000.0;
        doc["mil"]       = s.mil;
        doc["dtc_count"] = s.dtc_count;

        doc["gear"]           = s.gear;
        doc["handbrake"]      = s.handbrake;
        doc["brake_pedal"]    = s.brake_pedal;
        doc["engine_running"] = s.engine_running;

        doc["locked"] = s.locked;
        JsonObject doors = doc["doors"].to<JsonObject>();
        doors["driver"]     = s.door_driver_open;
        doors["passenger"]  = s.door_passenger_open;
        doors["rear_left"]  = s.door_rear_left_open;
        doors["rear_right"] = s.door_rear_right_open;
        doors["trunk"]      = s.door_trunk_open;

        JsonObject lights = doc["lights"].to<JsonObject>();
        lights["parking"]    = s.light_parking;
        lights["high_beam"]  = s.light_high_beam;
        lights["turn_left"]  = s.turn_left;
        lights["turn_right"] = s.turn_right;
        lights["headlight_raw"] = s.headlight_state;
    }

    size_t n = serializeJson(doc, buf, buf_size);
    if (n + 1 < buf_size) { buf[n++] = '\n'; buf[n] = '\0'; }
    return n;
}

size_t buildFast(char* buf, size_t buf_size) {
    JsonDocument doc;
    doc["type"] = "fast";
    doc["ts"]   = millis();

    {
        car_state::Guard g;
        if (!g.ok()) return 0;
        const CarState& s = car_state::state;
        if (s.rpm >= 0)          doc["rpm"]      = s.rpm;
        if (s.speed >= 0)        doc["speed"]    = s.speed;
        if (s.throttle_x10 >= 0) doc["throttle"] = s.throttle_x10 / 10.0;
    }

    size_t n = serializeJson(doc, buf, buf_size);
    if (n + 1 < buf_size) { buf[n++] = '\n'; buf[n] = '\0'; }
    return n;
}

size_t buildAck(char* buf, size_t buf_size, const char* cmd, bool ok) {
    JsonDocument doc;
    doc["type"] = "ack";
    doc["cmd"]  = cmd;
    doc["ok"]   = ok;
    size_t n = serializeJson(doc, buf, buf_size);
    if (n + 1 < buf_size) { buf[n++] = '\n'; buf[n] = '\0'; }
    return n;
}

// ---------------- Parsing ----------------

static CmdType cmdFromString(const char* s) {
    if (!s) return CMD_NONE;
    if (strcmp(s, "lock")    == 0) return CMD_LOCK;
    if (strcmp(s, "unlock")  == 0) return CMD_UNLOCK;
    if (strcmp(s, "drl_on")  == 0) return CMD_DRL_ON;
    if (strcmp(s, "drl_off") == 0) return CMD_DRL_OFF;
    if (strcmp(s, "refresh") == 0) return CMD_REFRESH;
    return CMD_NONE;
}

CmdType parseAndDispatch(const char* line, size_t len, CmdSource source) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, line, len);
    if (err) return CMD_NONE;

    const char* cmdStr = doc["cmd"] | (const char*)nullptr;
    if (!cmdStr) return CMD_NONE;

    // Config command — mutate cfg, persist, no enqueue.
    if (strcmp(cmdStr, "config") == 0) {
        if (doc["wifi_ssid"].is<const char*>()) {
            strncpy(nvs_cfg::cfg.wifi_ssid, doc["wifi_ssid"], sizeof(nvs_cfg::cfg.wifi_ssid) - 1);
        }
        if (doc["wifi_pass"].is<const char*>()) {
            strncpy(nvs_cfg::cfg.wifi_pass, doc["wifi_pass"], sizeof(nvs_cfg::cfg.wifi_pass) - 1);
        }
        if (doc["tcp_port"].is<uint16_t>())   nvs_cfg::cfg.tcp_port    = doc["tcp_port"];
        if (doc["wifi_enabled"].is<bool>())   nvs_cfg::cfg.wifi_enabled = doc["wifi_enabled"];
        if (doc["auto_lock"].is<bool>())      nvs_cfg::cfg.auto_lock   = doc["auto_lock"];
        if (doc["auto_unlock"].is<bool>())    nvs_cfg::cfg.auto_unlock = doc["auto_unlock"];
        if (doc["auto_drl"].is<bool>())       nvs_cfg::cfg.auto_drl    = doc["auto_drl"];
        if (doc["lock_speed"].is<uint8_t>())  nvs_cfg::cfg.lock_speed  = doc["lock_speed"];
        if (doc["unlock_delay"].is<uint8_t>()) nvs_cfg::cfg.unlock_delay = doc["unlock_delay"];
        if (doc["json_on_serial"].is<bool>()) nvs_cfg::cfg.json_on_serial = doc["json_on_serial"];
        nvs_cfg::save();
        return CMD_NONE;
    }

    CmdType t = cmdFromString(cmdStr);
    if (t != CMD_NONE) {
        cmd_queue::push(t, source);
    }
    return t;
}

}  // namespace json_proto
