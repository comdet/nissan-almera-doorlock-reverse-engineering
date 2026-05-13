#include "poll_task.h"
#include "config.h"
#include "car_state.h"
#include "can_manager.h"
#include "decode.h"
#include "cmd_queue.h"
#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

namespace poll_task {

// Buffers stay file-local — task accesses them serially.
static uint8_t didBuf[64];
static uint8_t obdBuf[8];

static volatile uint32_t pollOk   = 0;
static volatile uint32_t pollFail = 0;

// DRL state machine
static bool     drl_active   = false;
static uint32_t drl_last_tp  = 0;
static const uint32_t DRL_TP_INTERVAL_MS = 1200;

// Track whether we have a "refresh now" pending — bumps all timers due.
static volatile bool refresh_pending = false;

uint32_t getPollOk()   { return pollOk; }
uint32_t getPollFail() { return pollFail; }
bool     isDrlActive() { return drl_active; }

// ---------------- Polling helpers (each writes into car_state under lock) ----------------

static void obdPoll(uint8_t pid, void (*dec)(const uint8_t*, size_t, CarState&)) {
    size_t n = can_mgr::obdQuery(pid, obdBuf, sizeof(obdBuf));
    if (n) {
        car_state::Guard g;
        if (g.ok()) {
            dec(obdBuf, n, car_state::state);
            pollOk++;
            return;
        }
    }
    pollFail++;
}

static void didPoll(uint32_t req_id, uint32_t resp_id, uint16_t did,
                    void (*dec)(const uint8_t*, size_t, CarState&),
                    uint32_t* ts_field) {
    size_t n = can_mgr::udsReadDid(req_id, resp_id, did, didBuf, sizeof(didBuf));
    if (n) {
        car_state::Guard g;
        if (g.ok()) {
            dec(didBuf, n, car_state::state);
            if (ts_field) *ts_field = millis();
            pollOk++;
            return;
        }
    }
    pollFail++;
}

static void pollFast() {
    obdPoll(PID_RPM,      decode::obdRpm);
    obdPoll(PID_SPEED,    decode::obdSpeed);
    obdPoll(PID_THROTTLE, decode::obdThrottle);
    car_state::Guard g; if (g.ok()) car_state::state.ts_obd_fast = millis();
}

static void pollMed() {
    obdPoll(PID_COOLANT, decode::obdCoolant);
    obdPoll(PID_BATTERY, decode::obdBattery);
    didPoll(BCM_REQ,   BCM_RESP,   DID_DOOR_BODY, decode::did0109, &car_state::state.ts_did_0109);
    didPoll(LIGHT_REQ, LIGHT_RESP, DID_HANDBRAKE, decode::did0E07, &car_state::state.ts_did_0e07);
    car_state::Guard g; if (g.ok()) car_state::state.ts_obd_med = millis();
}

static void pollSlow() {
    obdPoll(PID_AMBIENT, decode::obdAmbient);
    obdPoll(PID_MIL_DTC, decode::obdMil);
    didPoll(ENG_REQ,   ENG_RESP,   DID_ENGINE_RUN, decode::did1304, &car_state::state.ts_did_1304);
    didPoll(BODY2_REQ, BODY2_RESP, DID_GEAR,       decode::did0108, &car_state::state.ts_did_0108);
    car_state::Guard g; if (g.ok()) car_state::state.ts_obd_slow = millis();
}

// ---------------- Command execution ----------------

static void execCmd(const Cmd& c) {
    switch (c.type) {
        case CMD_LOCK:
            can_mgr::udsIoControlShortAdj(BCM_REQ, BCM_RESP, 0x0202, 0x00, 0x01, /*close=*/true);
            break;
        case CMD_UNLOCK:
            can_mgr::udsIoControlShortAdj(BCM_REQ, BCM_RESP, 0x0202, 0x00, 0x02, /*close=*/true);
            break;
        case CMD_DRL_ON:
            // Keep session open so keep-alive can extend it.
            if (can_mgr::udsIoControlShortAdj(BCM_REQ, BCM_RESP, 0x023F, 0x00, 0x01, /*close=*/false)) {
                drl_active   = true;
                drl_last_tp  = millis();
            }
            break;
        case CMD_DRL_OFF:
            can_mgr::udsIoControlShortAdj(BCM_REQ, BCM_RESP, 0x023F, 0x00, 0x00, /*close=*/true);
            drl_active = false;
            break;
        case CMD_REFRESH:
            refresh_pending = true;
            break;
        default:
            break;
    }
}

// ---------------- Task body ----------------

static void taskFn(void*) {
    uint32_t lastFast = 0;
    uint32_t lastMed  = 0;
    uint32_t lastSlow = 0;

    // Stagger initial poll a bit so they don't all stack on first tick.
    uint32_t boot = millis();
    lastFast = boot;
    lastMed  = boot;
    lastSlow = boot;

    for (;;) {
        // 1. Drain queue with short timeout (acts as our pacer when idle).
        Cmd c;
        if (cmd_queue::pop(c, 50)) {
            execCmd(c);
        }

        uint32_t now = millis();

        // 2. DRL keep-alive
        if (drl_active && (now - drl_last_tp >= DRL_TP_INTERVAL_MS)) {
            can_mgr::udsTesterPresent(BCM_REQ, BCM_RESP);
            drl_last_tp = millis();
        }

        // 3. Refresh now? Just force all groups due.
        if (refresh_pending) {
            refresh_pending = false;
            lastFast = lastMed = lastSlow = now - 1;
        }

        // 4. Scheduled polls
        if (now - lastFast >= POLL_FAST_MS) {
            pollFast();
            lastFast = millis();
        }
        if (now - lastMed >= POLL_MED_MS) {
            pollMed();
            lastMed = millis();
        }
        if (now - lastSlow >= POLL_SLOW_MS) {
            pollSlow();
            lastSlow = millis();
        }

        // Yield briefly to keep other tasks (comms) responsive.
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

void start(uint32_t stack, uint8_t priority) {
    xTaskCreate(taskFn, "canPoll", stack, nullptr, priority, nullptr);
}

}  // namespace poll_task
