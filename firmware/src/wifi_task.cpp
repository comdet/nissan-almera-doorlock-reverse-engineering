#include "wifi_task.h"
#include "nvs_config.h"
#include "json_protocol.h"
#include "cmd_queue.h"
#include "poll_task.h"
#include <Arduino.h>
#include <WiFi.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

namespace wifi_task {

static volatile bool     wifi_connected = false;
static volatile bool     tcp_connected  = false;
static volatile uint32_t tcp_reconnects = 0;
static volatile uint32_t bytes_tx       = 0;
static volatile uint32_t bytes_rx       = 0;

// Line buffer for incoming JSON
static char   rx_line[512];
static size_t rx_len = 0;

static const uint32_t STATUS_PERIOD_MS = 1000;
static const uint32_t BACKOFF_MIN_MS   = 1000;
static const uint32_t BACKOFF_MAX_MS   = 15000;

Info snapshot() {
    Info i {};
    i.wifi_enabled  = nvs_cfg::cfg.wifi_enabled;
    i.wifi_connected = wifi_connected;
    i.tcp_connected = tcp_connected;
    i.tcp_reconnects = tcp_reconnects;
    i.bytes_tx = bytes_tx;
    i.bytes_rx = bytes_rx;
    if (wifi_connected) {
        i.rssi       = WiFi.RSSI();
        i.ip_v4      = (uint32_t)WiFi.localIP();
        i.gateway_v4 = (uint32_t)WiFi.gatewayIP();
    }
    return i;
}

static void onWifiEvent(WiFiEvent_t event) {
    switch (event) {
        case ARDUINO_EVENT_WIFI_STA_GOT_IP:
            wifi_connected = true;
            break;
        case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
            wifi_connected = false;
            tcp_connected  = false;
            break;
        default: break;
    }
}

// Push line to parser, reset buffer. Source = wifi.
static void consumeLine() {
    if (rx_len == 0) return;
    rx_line[rx_len] = '\0';
    json_proto::parseAndDispatch(rx_line, rx_len, SRC_WIFI);
    rx_len = 0;
}

static void handleClient(WiFiClient& client) {
    char buf[512];

    // Greeting
    size_t n = json_proto::buildHello(buf, sizeof(buf));
    if (n) {
        client.write((const uint8_t*)buf, n);
        bytes_tx += n;
    }

    uint32_t last_status = 0;
    rx_len = 0;

    while (client.connected()) {
        // RX
        while (client.available()) {
            int c = client.read();
            if (c < 0) break;
            bytes_rx++;
            if (c == '\n' || c == '\r') {
                consumeLine();
            } else if (rx_len < sizeof(rx_line) - 1) {
                rx_line[rx_len++] = (char)c;
            } else {
                // overflow — discard
                rx_len = 0;
            }
        }

        // TX status periodically
        uint32_t now = millis();
        if (now - last_status >= STATUS_PERIOD_MS) {
            n = json_proto::buildStatus(buf, sizeof(buf));
            if (n) {
                client.write((const uint8_t*)buf, n);
                bytes_tx += n;
            }
            last_status = now;
        }

        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

static void taskFn(void*) {
    WiFi.onEvent(onWifiEvent);

    uint32_t backoff = BACKOFF_MIN_MS;

    for (;;) {
        // If disabled OR car has been parked long enough for low-power mode,
        // shut down WiFi and sleep. Wakes up automatically when poll_task
        // exits PARKED on engine restart.
        if (!nvs_cfg::cfg.wifi_enabled || poll_task::isLowPower()) {
            if (WiFi.getMode() != WIFI_OFF) {
                WiFi.disconnect(true);
                WiFi.mode(WIFI_OFF);
            }
            wifi_connected = false;
            tcp_connected  = false;
            vTaskDelay(pdMS_TO_TICKS(2000));
            continue;
        }

        // Ensure WiFi started in STA mode
        if (WiFi.getMode() != WIFI_STA) {
            WiFi.mode(WIFI_STA);
            WiFi.begin(nvs_cfg::cfg.wifi_ssid, nvs_cfg::cfg.wifi_pass);
        } else if (WiFi.status() != WL_CONNECTED) {
            WiFi.reconnect();
        }

        // Wait for IP (up to ~10s)
        uint32_t deadline = millis() + 10000;
        while (WiFi.status() != WL_CONNECTED && (int32_t)(deadline - millis()) > 0) {
            vTaskDelay(pdMS_TO_TICKS(200));
        }

        if (WiFi.status() != WL_CONNECTED) {
            vTaskDelay(pdMS_TO_TICKS(backoff));
            backoff = (backoff * 2 > BACKOFF_MAX_MS) ? BACKOFF_MAX_MS : backoff * 2;
            continue;
        }
        backoff = BACKOFF_MIN_MS;

        // Connect TCP to gateway (typical HUD AP scenario)
        IPAddress server = WiFi.gatewayIP();
        WiFiClient client;
        if (client.connect(server, nvs_cfg::cfg.tcp_port, 3000)) {
            tcp_connected = true;
            tcp_reconnects++;
            handleClient(client);
            tcp_connected = false;
            client.stop();
        } else {
            vTaskDelay(pdMS_TO_TICKS(2000));
        }
    }
}

void start(uint32_t stack, uint8_t priority) {
    xTaskCreate(taskFn, "wifi", stack, nullptr, priority, nullptr);
}

}  // namespace wifi_task
