#include "cmd_queue.h"
#include <Arduino.h>

namespace cmd_queue {

static QueueHandle_t q = nullptr;

void init(uint8_t capacity) {
    if (!q) q = xQueueCreate(capacity, sizeof(Cmd));
}

bool push(CmdType type, CmdSource source) {
    if (!q) return false;
    Cmd c { type, source, millis() };
    return xQueueSend(q, &c, 0) == pdTRUE;
}

bool pop(Cmd& out, uint32_t timeout_ms) {
    if (!q) return false;
    return xQueueReceive(q, &out, pdMS_TO_TICKS(timeout_ms)) == pdTRUE;
}

const char* typeLabel(CmdType t) {
    switch (t) {
        case CMD_LOCK:    return "lock";
        case CMD_UNLOCK:  return "unlock";
        case CMD_DRL_ON:  return "drl_on";
        case CMD_DRL_OFF: return "drl_off";
        case CMD_REFRESH: return "refresh";
        case CMD_DUMP:    return "dump";
        case CMD_SCAN:    return "scan";
        default:          return "none";
    }
}

const char* sourceLabel(CmdSource s) {
    switch (s) {
        case SRC_WIFI:     return "wifi";
        case SRC_AUTO:     return "auto";
        case SRC_INTERNAL: return "internal";
        default:           return "serial";
    }
}

}  // namespace cmd_queue
