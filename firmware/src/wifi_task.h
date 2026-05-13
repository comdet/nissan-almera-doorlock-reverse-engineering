/*
 * Phase 4 — WiFi STA + TCP client to HUD.
 *
 * Behavior:
 *   - If cfg.wifi_enabled == false, the task sits idle (no power waste).
 *   - STA mode, connects to cfg.wifi_ssid / wifi_pass with auto-reconnect.
 *   - Opens TCP connection to gateway:cfg.tcp_port. Reconnects with backoff.
 *   - On connect, sends "hello" then periodic "status" frames.
 *   - Reads newline-delimited JSON from socket -> json_proto::parseAndDispatch.
 *
 * Failure of any layer (WiFi or TCP) never affects canPollTask.
 */

#pragma once

#include <stdint.h>

namespace wifi_task {

void start(uint32_t stack = 6144, uint8_t priority = 1);

// Status snapshot for diagnostics / serial 'wifi' command.
struct Info {
    bool     wifi_enabled;
    bool     wifi_connected;
    bool     tcp_connected;
    int8_t   rssi;
    uint32_t ip_v4;          // 0 if not connected
    uint32_t gateway_v4;
    uint32_t tcp_reconnects;
    uint32_t bytes_tx;
    uint32_t bytes_rx;
};

Info snapshot();

}  // namespace wifi_task
