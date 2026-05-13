#include "button_task.h"
#include "config.h"
#include "nvs_config.h"
#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

namespace button_task {

static volatile bool pressed_now = false;

bool isPressed() { return pressed_now; }

static void taskFn(void*) {
    pinMode(BUTTON_PIN, INPUT_PULLUP);

    bool     stable    = false;          // debounced state
    bool     last_raw  = HIGH;
    uint32_t last_edge = 0;
    uint32_t press_start = 0;
    bool     triggered = false;          // edge-triggers once per press

    for (;;) {
        bool raw = digitalRead(BUTTON_PIN) == LOW;  // active low

        // Debounce: state only changes after the raw reading is stable for 30ms.
        uint32_t now = millis();
        if (raw != last_raw) {
            last_raw  = raw;
            last_edge = now;
        } else if (now - last_edge > 30 && stable != raw) {
            stable = raw;
            pressed_now = stable;
            if (stable) {
                press_start = now;
                triggered   = false;
            }
        }

        // Long-press → set NVS flag + reboot. Fires once until release.
        if (stable && !triggered && (now - press_start >= BUTTON_HOLD_MS)) {
            triggered = true;
            Serial.println();
            Serial.println("[button] long-press -> entering CONFIG mode, rebooting...");
            nvs_cfg::cfg.config_mode_next_boot = true;
            nvs_cfg::save();
            delay(200);
            ESP.restart();
        }

        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

void start(uint32_t stack, uint8_t priority) {
    xTaskCreate(taskFn, "button", stack, nullptr, priority, nullptr);
}

}  // namespace button_task
