/*
 * Nissan Almera N18 Car Companion — main entry.
 *
 * Two FreeRTOS tasks share state via a mutex-protected CarState:
 *   - canPollTask : owns the bus, polls DIDs/PIDs, drains cmdQueue
 *   - wifiTask    : STA + TCP client to HUD (idle if cfg.wifi_enabled=false)
 * The main loop here handles serial commands and periodic Serial output.
 *
 * Test without the car:
 *   1. Flash firmware (pio run -t upload --upload-port COM30)
 *   2. Open serial monitor at 115200
 *   3. Try: help / status / config / json on / lock / unlock
 *      All poll calls will fail (no bus), but the rest of the system works.
 *
 * Test with the car:
 *   1. Plug ESP32 into OBD-II via SN65HVD230
 *   2. Turn ignition to ACC or start engine
 *   3. Snapshot every 2s should populate fields
 */

#include <Arduino.h>
#include "config.h"
#include "car_state.h"
#include "nvs_config.h"
#include "can_manager.h"
#include "cmd_queue.h"
#include "poll_task.h"
#include "wifi_task.h"
#include "button_task.h"
#include "config_portal.h"
#include "serial_cmd.h"
#include "json_protocol.h"

static uint32_t lastPrintMs = 0;

static void emitSnapshot() {
    if (nvs_cfg::cfg.json_on_serial) {
        char buf[768];
        size_t n = json_proto::buildStatus(buf, sizeof(buf));
        if (n) Serial.write((const uint8_t*)buf, n);
    } else {
        serial_cmd::printSnapshotText();
    }
}

void setup() {
    Serial.begin(SERIAL_BAUD);
    uint32_t t = millis();
    while (!Serial && millis() - t < 2000) delay(10);
    delay(200);

    Serial.println();
    Serial.println("Almera N18 Car Companion booting...");

    // NVS config first — drives mode selection below.
    nvs_cfg::load();
    nvs_cfg::print();

    // Branch: web config portal vs normal car-companion operation.
    if (nvs_cfg::cfg.config_mode_next_boot) {
        config_portal::run();   // never returns
    }

    // State + queue infrastructure
    car_state::init();
    cmd_queue::init();

    // CAN driver
    if (!can_mgr::init()) {
        Serial.println("FATAL: TWAI init failed");
        while (true) delay(1000);
    }
    Serial.printf("TWAI ready @ %lu bps  TX=GPIO%d  RX=GPIO%d\n",
                  CAN_BITRATE, CAN_TX_PIN, CAN_RX_PIN);

    // Tasks
    poll_task::start(/*stack=*/6144, /*priority=*/3);
    wifi_task::start(/*stack=*/6144, /*priority=*/1);
    button_task::start(/*stack=*/2048, /*priority=*/1);

    serial_cmd::printHelp();
    lastPrintMs = millis() - PRINT_MS;  // emit first snapshot quickly
}

void loop() {
    serial_cmd::poll();

    if (millis() - lastPrintMs >= PRINT_MS) {
        emitSnapshot();
        lastPrintMs = millis();
    }

    delay(20);
}
