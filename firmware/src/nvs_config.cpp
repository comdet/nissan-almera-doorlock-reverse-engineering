#include "nvs_config.h"
#include <Preferences.h>
#include <string.h>

namespace nvs_cfg {

Config cfg;

static const char* NS = "almera";  // NVS namespace

// Defaults — match FIRMWARE_PLAN.md
static void applyDefaults() {
    strncpy(cfg.wifi_ssid, "CarHUD", sizeof(cfg.wifi_ssid));
    strncpy(cfg.wifi_pass, "12345678", sizeof(cfg.wifi_pass));
    cfg.tcp_port      = 35000;
    cfg.wifi_enabled  = false;  // off by default until HUD exists
    cfg.auto_lock     = true;
    cfg.auto_unlock   = true;
    cfg.auto_drl      = true;
    cfg.lock_speed    = 20;
    cfg.unlock_delay  = 1;
    cfg.json_on_serial = false;
    cfg.config_mode_next_boot = false;
}

bool load() {
    applyDefaults();

    Preferences p;
    if (!p.begin(NS, /*readOnly=*/true)) {
        // Namespace doesn't exist yet — persist defaults.
        if (p.begin(NS, false)) {
            p.end();
        }
        return save();
    }

    // Strings: getString returns "" if missing, so guard with isKey.
    if (p.isKey("wifi_ssid")) {
        String s = p.getString("wifi_ssid", "");
        strncpy(cfg.wifi_ssid, s.c_str(), sizeof(cfg.wifi_ssid) - 1);
        cfg.wifi_ssid[sizeof(cfg.wifi_ssid) - 1] = '\0';
    }
    if (p.isKey("wifi_pass")) {
        String s = p.getString("wifi_pass", "");
        strncpy(cfg.wifi_pass, s.c_str(), sizeof(cfg.wifi_pass) - 1);
        cfg.wifi_pass[sizeof(cfg.wifi_pass) - 1] = '\0';
    }
    if (p.isKey("tcp_port"))     cfg.tcp_port     = p.getUShort("tcp_port", cfg.tcp_port);
    if (p.isKey("wifi_en"))      cfg.wifi_enabled = p.getBool("wifi_en", cfg.wifi_enabled);
    if (p.isKey("auto_lock"))    cfg.auto_lock    = p.getBool("auto_lock", cfg.auto_lock);
    if (p.isKey("auto_unlock"))  cfg.auto_unlock  = p.getBool("auto_unlock", cfg.auto_unlock);
    if (p.isKey("auto_drl"))     cfg.auto_drl     = p.getBool("auto_drl", cfg.auto_drl);
    if (p.isKey("lock_speed"))   cfg.lock_speed   = p.getUChar("lock_speed", cfg.lock_speed);
    if (p.isKey("unlock_del"))   cfg.unlock_delay = p.getUChar("unlock_del", cfg.unlock_delay);
    if (p.isKey("json_serial"))  cfg.json_on_serial = p.getBool("json_serial", cfg.json_on_serial);
    if (p.isKey("cfg_next"))     cfg.config_mode_next_boot = p.getBool("cfg_next", false);

    p.end();
    return true;
}

bool save() {
    Preferences p;
    if (!p.begin(NS, /*readOnly=*/false)) return false;
    p.putString("wifi_ssid", cfg.wifi_ssid);
    p.putString("wifi_pass", cfg.wifi_pass);
    p.putUShort("tcp_port",  cfg.tcp_port);
    p.putBool  ("wifi_en",   cfg.wifi_enabled);
    p.putBool  ("auto_lock", cfg.auto_lock);
    p.putBool  ("auto_unlock", cfg.auto_unlock);
    p.putBool  ("auto_drl",  cfg.auto_drl);
    p.putUChar ("lock_speed", cfg.lock_speed);
    p.putUChar ("unlock_del", cfg.unlock_delay);
    p.putBool  ("json_serial", cfg.json_on_serial);
    p.putBool  ("cfg_next",    cfg.config_mode_next_boot);
    p.end();
    return true;
}

bool resetDefaults() {
    Preferences p;
    if (p.begin(NS, false)) {
        p.clear();
        p.end();
    }
    applyDefaults();
    return save();
}

void print() {
    Serial.println("-- Config --");
    Serial.printf("  wifi_enabled : %s\n", cfg.wifi_enabled ? "true" : "false");
    Serial.printf("  wifi_ssid    : %s\n", cfg.wifi_ssid);
    Serial.printf("  wifi_pass    : %s\n", strlen(cfg.wifi_pass) ? "***" : "(empty)");
    Serial.printf("  tcp_port     : %u\n", cfg.tcp_port);
    Serial.printf("  auto_lock    : %s  speed>=%u km/h\n",
                  cfg.auto_lock ? "true" : "false", cfg.lock_speed);
    Serial.printf("  auto_unlock  : %s  delay=%us\n",
                  cfg.auto_unlock ? "true" : "false", cfg.unlock_delay);
    Serial.printf("  auto_drl     : %s\n", cfg.auto_drl ? "true" : "false");
    Serial.printf("  json_serial  : %s\n", cfg.json_on_serial ? "true" : "false");
}

}  // namespace nvs_cfg
