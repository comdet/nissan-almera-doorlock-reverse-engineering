/*
 * Command queue — comms tasks (serial/wifi/auto-features) push here.
 * canPollTask is the sole consumer and the only thread that touches the bus.
 */

#pragma once

#include <stdint.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

enum CmdType : uint8_t {
    CMD_NONE = 0,
    CMD_LOCK,
    CMD_UNLOCK,
    CMD_DRL_ON,
    CMD_DRL_OFF,
    CMD_REFRESH,   // re-poll all DIDs/PIDs immediately
    CMD_DUMP,      // read every known DID and print raw bytes to Serial (debug)
};

enum CmdSource : uint8_t {
    SRC_SERIAL = 0,
    SRC_WIFI,
    SRC_AUTO,
    SRC_INTERNAL,
};

struct Cmd {
    CmdType   type;
    CmdSource source;
    uint32_t  ts_enqueued;   // millis() when pushed
};

namespace cmd_queue {

void init(uint8_t capacity = 8);

// Push a command. Returns false if full or queue not init.
bool push(CmdType type, CmdSource source);

// Pop a command (consumer). Returns false on timeout.
bool pop(Cmd& out, uint32_t timeout_ms);

// Convert enum to short label for logging/JSON.
const char* typeLabel(CmdType t);
const char* sourceLabel(CmdSource s);

}  // namespace cmd_queue
