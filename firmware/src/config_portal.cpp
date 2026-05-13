#include "config_portal.h"
#include "config.h"
#include "nvs_config.h"
#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>

namespace config_portal {

static WebServer server(CFG_AP_PORT);

// ---------------- HTML helpers ----------------

static String htmlEscape(const String& s) {
    String o; o.reserve(s.length() + 8);
    for (char c : s) {
        switch (c) {
            case '&': o += "&amp;";  break;
            case '<': o += "&lt;";   break;
            case '>': o += "&gt;";   break;
            case '"': o += "&quot;"; break;
            default:  o += c;        break;
        }
    }
    return o;
}

static String checkbox(const char* name, bool checked, const char* label) {
    String s = "<label><input type='checkbox' name='";
    s += name; s += "'";
    if (checked) s += " checked";
    s += "> "; s += label; s += "</label><br>";
    return s;
}

static String text(const char* name, const String& value, const char* label,
                   const char* placeholder = "", const char* type = "text",
                   int minv = -1, int maxv = -1) {
    String s = "<label>"; s += label; s += "<br><input type='"; s += type;
    s += "' name='"; s += name; s += "' value='"; s += htmlEscape(value); s += "'";
    if (placeholder && *placeholder) { s += " placeholder='"; s += placeholder; s += "'"; }
    if (minv >= 0) { s += " min='"; s += minv; s += "'"; }
    if (maxv >= 0) { s += " max='"; s += maxv; s += "'"; }
    s += "></label><br>";
    return s;
}

static void renderPage(String& out, const char* note = "") {
    out = F(
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Almera Config</title>"
        "<style>"
        "body{font-family:sans-serif;max-width:480px;margin:1em auto;padding:0 1em;color:#222}"
        "h1{font-size:1.2em}h2{font-size:1em;margin-top:1.5em;border-bottom:1px solid #ccc}"
        "input[type=text],input[type=password],input[type=number]"
        "{width:100%;padding:0.4em;box-sizing:border-box;margin:0.2em 0 0.8em;font-size:1em}"
        "label{display:block;margin:0.5em 0}"
        "button{padding:0.6em 1.2em;font-size:1em;margin-right:0.5em}"
        ".note{background:#eef;border:1px solid #99c;padding:0.6em;margin:0.5em 0;border-radius:4px}"
        ".danger{background:#fdd;border-color:#a44}"
        "</style></head><body>"
        "<h1>Almera N18 — Config Portal</h1>"
    );
    if (note && *note) {
        out += "<div class='note'>"; out += note; out += "</div>";
    }
    out += F("<form method='POST' action='/save'>");

    out += F("<h2>WiFi (Station — connect to HUD)</h2>");
    out += checkbox("wifi_enabled", nvs_cfg::cfg.wifi_enabled, "Enable WiFi (turn on when HUD exists)");
    out += text   ("wifi_ssid", nvs_cfg::cfg.wifi_ssid, "SSID", "CarHUD");
    out += text   ("wifi_pass", nvs_cfg::cfg.wifi_pass, "Password", "", "password");
    out += text   ("tcp_port",  String(nvs_cfg::cfg.tcp_port), "TCP port", "35000", "number", 1, 65535);

    out += F("<h2>Auto-features</h2>");
    out += checkbox("auto_lock",   nvs_cfg::cfg.auto_lock,   "Auto-lock when speed exceeds threshold");
    out += checkbox("auto_unlock", nvs_cfg::cfg.auto_unlock, "Auto-unlock after engine off");
    out += checkbox("auto_drl",    nvs_cfg::cfg.auto_drl,    "Auto-DRL when engine running");
    out += text   ("lock_speed",  String(nvs_cfg::cfg.lock_speed),
                   "Lock speed threshold (km/h)", "20", "number", 1, 100);
    out += text   ("unlock_delay", String(nvs_cfg::cfg.unlock_delay),
                   "Unlock delay after engine off (seconds)", "3", "number", 0, 60);

    out += F("<h2>Output</h2>");
    out += checkbox("json_on_serial", nvs_cfg::cfg.json_on_serial,
                    "Emit JSON on Serial (instead of pretty text)");

    out += F("<p><button type='submit'>Save &amp; Reboot</button>"
             "<button type='submit' formaction='/cancel'>Cancel</button></p>"
             "</form>"
             "<form method='POST' action='/factory_reset'>"
             "<div class='note danger'>Reset everything to defaults — this wipes WiFi credentials too.</div>"
             "<button type='submit'>Factory Reset</button>"
             "</form>"
             "</body></html>");
}

// ---------------- Handlers ----------------

static bool hasArgBool(const char* name) {
    // Checkboxes only POST a value when checked.
    return server.hasArg(name);
}

static void handleRoot() {
    String page; renderPage(page);
    server.send(200, "text/html; charset=utf-8", page);
}

static void handleSave() {
    // Update cfg from form values
    nvs_cfg::cfg.wifi_enabled  = hasArgBool("wifi_enabled");
    nvs_cfg::cfg.auto_lock     = hasArgBool("auto_lock");
    nvs_cfg::cfg.auto_unlock   = hasArgBool("auto_unlock");
    nvs_cfg::cfg.auto_drl      = hasArgBool("auto_drl");
    nvs_cfg::cfg.json_on_serial = hasArgBool("json_on_serial");

    if (server.hasArg("wifi_ssid")) {
        String s = server.arg("wifi_ssid");
        strncpy(nvs_cfg::cfg.wifi_ssid, s.c_str(), sizeof(nvs_cfg::cfg.wifi_ssid) - 1);
        nvs_cfg::cfg.wifi_ssid[sizeof(nvs_cfg::cfg.wifi_ssid) - 1] = '\0';
    }
    if (server.hasArg("wifi_pass")) {
        String s = server.arg("wifi_pass");
        strncpy(nvs_cfg::cfg.wifi_pass, s.c_str(), sizeof(nvs_cfg::cfg.wifi_pass) - 1);
        nvs_cfg::cfg.wifi_pass[sizeof(nvs_cfg::cfg.wifi_pass) - 1] = '\0';
    }
    if (server.hasArg("tcp_port"))     nvs_cfg::cfg.tcp_port     = (uint16_t)server.arg("tcp_port").toInt();
    if (server.hasArg("lock_speed"))   nvs_cfg::cfg.lock_speed   = (uint8_t) server.arg("lock_speed").toInt();
    if (server.hasArg("unlock_delay")) nvs_cfg::cfg.unlock_delay = (uint8_t) server.arg("unlock_delay").toInt();

    nvs_cfg::cfg.config_mode_next_boot = false;
    nvs_cfg::save();

    server.send(200, "text/html; charset=utf-8",
        F("<!DOCTYPE html><html><body style='font-family:sans-serif;text-align:center;margin-top:3em'>"
          "<h2>Saved — rebooting…</h2><p>You can close this page.</p></body></html>"));
    delay(500);
    ESP.restart();
}

static void handleCancel() {
    nvs_cfg::cfg.config_mode_next_boot = false;
    nvs_cfg::save();
    server.send(200, "text/html; charset=utf-8",
        F("<!DOCTYPE html><html><body style='font-family:sans-serif;text-align:center;margin-top:3em'>"
          "<h2>Cancelled — rebooting…</h2></body></html>"));
    delay(500);
    ESP.restart();
}

static void handleFactoryReset() {
    nvs_cfg::resetDefaults();
    server.send(200, "text/html; charset=utf-8",
        F("<!DOCTYPE html><html><body style='font-family:sans-serif;text-align:center;margin-top:3em'>"
          "<h2>Defaults restored — rebooting…</h2></body></html>"));
    delay(500);
    ESP.restart();
}

static void handleNotFound() {
    // Captive-portal style: redirect anything else to root.
    server.sendHeader("Location", "/", true);
    server.send(302, "text/plain", "");
}

// ---------------- Entry point ----------------

void run() {
    Serial.println();
    Serial.println("==== CONFIG PORTAL MODE ====");

    // Clear the flag immediately — if the user power-cycles while in the
    // portal, the next boot returns to normal mode automatically.
    nvs_cfg::cfg.config_mode_next_boot = false;
    nvs_cfg::save();

    WiFi.persistent(false);
    WiFi.mode(WIFI_AP);
    bool ok = WiFi.softAP(CFG_AP_SSID, CFG_AP_PASS);
    IPAddress ip = WiFi.softAPIP();

    Serial.printf("AP SSID  : %s\n", CFG_AP_SSID);
    Serial.printf("AP PASS  : %s\n", CFG_AP_PASS);
    Serial.printf("AP start : %s\n", ok ? "ok" : "FAIL");
    Serial.printf("URL      : http://%u.%u.%u.%u/\n",
                  ip[0], ip[1], ip[2], ip[3]);
    Serial.println("Connect to AP, open URL, edit, then Save & Reboot.");
    Serial.println("(Long-press BOOT again or power-cycle to escape if browser is unavailable.)");

    server.on("/",              HTTP_GET,  handleRoot);
    server.on("/save",          HTTP_POST, handleSave);
    server.on("/cancel",        HTTP_POST, handleCancel);
    server.on("/factory_reset", HTTP_POST, handleFactoryReset);
    server.onNotFound(handleNotFound);
    server.begin();

    // Watch for an additional long-press to bail out without saving.
    pinMode(BUTTON_PIN, INPUT_PULLUP);
    uint32_t press_start = 0;
    bool     was_pressed = false;

    for (;;) {
        server.handleClient();

        bool pressed = digitalRead(BUTTON_PIN) == LOW;
        uint32_t now = millis();
        if (pressed && !was_pressed) {
            press_start = now;
        } else if (pressed && (now - press_start >= BUTTON_HOLD_MS)) {
            Serial.println("[button] long-press in portal — exiting config mode.");
            nvs_cfg::cfg.config_mode_next_boot = false;
            nvs_cfg::save();
            delay(200);
            ESP.restart();
        }
        was_pressed = pressed;

        delay(5);
    }
}

}  // namespace config_portal
