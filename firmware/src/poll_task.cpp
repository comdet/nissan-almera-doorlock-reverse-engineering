#include "poll_task.h"
#include "config.h"
#include "car_state.h"
#include "can_manager.h"
#include "decode.h"
#include "cmd_queue.h"
#include "nvs_config.h"
#include <Arduino.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

namespace poll_task {

// ============================================================================
// Buffers (task accesses them serially)
// ============================================================================

static uint8_t didBuf[64];
static uint8_t obdBuf[8];

static volatile uint32_t pollOk   = 0;
static volatile uint32_t pollFail = 0;

// Time of the most recent successful poll — drives the "no-response" low-
// power fallback. Initialised to boot time in taskFn so we don't trip
// immediately at startup.
static uint32_t last_ok_poll_ms = 0;

uint32_t getPollOk()   { return pollOk; }
uint32_t getPollFail() { return pollFail; }

// ============================================================================
// DRL keep-alive state
// ============================================================================

static bool     drl_active   = false;
static uint32_t drl_last_tp  = 0;

bool isDrlActive() { return drl_active; }

// ============================================================================
// Driving State Machine — see STATE_MACHINE.md for full description
// ============================================================================

enum class DrvState : uint8_t {
    ACC_ON,           // key ACC, waiting for engine start
    ENGINE_ON,        // engine running, not yet moving
    DRIVING,          // moving, below lock speed
    LOCKED_CRUISING,  // locked, moving
    LOCKED_STOPPED,   // locked, stopped (red light / gas station / etc)
    REARM,            // door opened during stop — wait for speed to re-lock
    ENGINE_OFF,       // RPM=0 + gear=P, counting down to auto-unlock
    PARKED,           // engine off and unlocked
};

static const char* STATE_NAMES[] = {
    "ACC_ON", "ENGINE_ON", "DRIVING", "LOCKED_CRUISING",
    "LOCKED_STOPPED", "REARM", "ENGINE_OFF", "PARKED",
};

static DrvState state = DrvState::ACC_ON;
static uint32_t state_entered_ms = 0;

const char* getStateName() { return STATE_NAMES[(uint8_t)state]; }

// In low-power when EITHER:
//   - PARKED for >= LOWPOWER_ENTER_MS (normal flow: engine off, settled), OR
//   - no successful CAN response for >= NO_RESP_LOWPOWER_MS in a non-driving
//     state (handles boot-with-no-car, ACC off without state machine ever
//     reaching PARKED).
// While driving the bus is always alive so the second condition can't fire.
bool isLowPower() {
    const uint32_t now = millis();
    if (state == DrvState::PARKED && (now - state_entered_ms) >= LOWPOWER_ENTER_MS) {
        return true;
    }
    const bool driving = (state == DrvState::DRIVING
                       || state == DrvState::LOCKED_CRUISING
                       || state == DrvState::LOCKED_STOPPED
                       || state == DrvState::REARM
                       || state == DrvState::ENGINE_ON);
    if (!driving && (now - last_ok_poll_ms) >= NO_RESP_LOWPOWER_MS) {
        return true;
    }
    return false;
}

static void transitionTo(DrvState ns) {
    if (state == ns) return;
    Serial.printf("[state] %s -> %s\n", STATE_NAMES[(uint8_t)state], STATE_NAMES[(uint8_t)ns]);
    state = ns;
    state_entered_ms = millis();
}

// Door event tracking for circular locking (open then close while stopped)
static bool prev_any_door_open = false;
static bool door_event_pending = false;

// Last gear that was actually readable from the ECU. Engine ECU 0x7E1 may
// stop responding the instant the engine is killed, so the current gear
// snapshot can read "?" even though the driver had just shifted to P. We
// fall back to this for the ENGINE_OFF transition test.
static char last_known_gear[3] = "?";

// Engine-off countdown
static uint32_t engine_off_at = 0;

// Track whether we have a "refresh now" pending — bumps all timers due.
static volatile bool refresh_pending = false;

// ============================================================================
// Polling primitives — each writes into car_state under the mutex
// ============================================================================

static void obdPoll(uint8_t pid, void (*dec)(const uint8_t*, size_t, CarState&)) {
    size_t n = can_mgr::obdQuery(pid, obdBuf, sizeof(obdBuf));
    if (n) {
        car_state::Guard g;
        if (g.ok()) {
            dec(obdBuf, n, car_state::state);
            pollOk++;
            last_ok_poll_ms = millis();
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
            last_ok_poll_ms = millis();
            return;
        }
    }
    pollFail++;
}

// Per-DID convenience wrappers
static void pollRPM()      { obdPoll(PID_RPM,      decode::obdRpm); }
static void pollSpeed()    { obdPoll(PID_SPEED,    decode::obdSpeed); }
static void pollThrottle() { obdPoll(PID_THROTTLE, decode::obdThrottle); }
static void pollCoolant()  { obdPoll(PID_COOLANT,  decode::obdCoolant); }
static void pollBattery()  { obdPoll(PID_BATTERY,  decode::obdBattery); }
static void pollAmbient()  { obdPoll(PID_AMBIENT,  decode::obdAmbient); }
static void pollMil()      { obdPoll(PID_MIL_DTC,  decode::obdMil); }

static void pollBCM() {
    didPoll(BCM_REQ, BCM_RESP, DID_DOOR_BODY, decode::did0109,
            &car_state::state.ts_did_0109);
}
static void pollGear() {
    didPoll(ENG_REQ, ENG_RESP, DID_GEAR, decode::did1301,
            &car_state::state.ts_did_1301);
}
static void pollHbrk() {
    didPoll(LIGHT_REQ, LIGHT_RESP, DID_HANDBRAKE, decode::did0E07,
            &car_state::state.ts_did_0e07);
}
static void pollEngStatus() {
    didPoll(ENG_REQ, ENG_RESP, DID_ENGINE_RUN, decode::did1304,
            &car_state::state.ts_did_1304);
}

// Helper: returns true and updates *last if interval has elapsed.
static bool due(uint32_t* last, uint32_t interval_ms) {
    uint32_t now = millis();
    if (now - *last >= interval_ms) {
        *last = now;
        return true;
    }
    return false;
}

// ============================================================================
// State snapshot — read fields under the mutex once per iteration
// ============================================================================

struct StateSnap {
    int16_t rpm;
    int16_t speed;
    char    gear[3];
    bool    any_door_open;
    bool    locked;
};

static StateSnap snapshot() {
    StateSnap s = {-1, -1, "?", false, false};
    car_state::Guard g;
    if (!g.ok()) return s;
    const CarState& cs = car_state::state;
    s.rpm   = cs.rpm;
    s.speed = cs.speed;
    strncpy(s.gear, cs.gear, sizeof(s.gear));
    s.gear[sizeof(s.gear) - 1] = '\0';
    s.any_door_open = cs.door_driver_open || cs.door_passenger_open
                   || cs.door_rear_left_open || cs.door_rear_right_open
                   || cs.door_trunk_open;
    s.locked = cs.locked;
    return s;
}

// ============================================================================
// State Machine — transitions + auto-feature triggers
// ============================================================================

// Real engine-off vs idle-stop. Engine off requires RPM=0 plus the driver
// having selected P. ECU 0x7E1 frequently stops responding the moment the
// engine cuts, so the current snapshot may read "?" even when the driver
// just shifted to P. Fall back to the most recent readable gear in that case.
//
//   rpm=0 + gear=P                         → real off            (normal)
//   rpm=0 + gear=? + last_known_gear=P    → real off            (ECU silent)
//   rpm=0 + gear=D|N + ...                → idle stop, NOT off  (CVT auto stop)
static bool isRealEngineOff(const StateSnap& s) {
    if (s.rpm != 0) return false;
    if (strcmp(s.gear, "P") == 0) return true;
    if (s.gear[0] == '?' && strcmp(last_known_gear, "P") == 0) return true;
    return false;
}

static void onEnterEngineOn() {
    if (nvs_cfg::cfg.auto_drl) {
        cmd_queue::push(CMD_DRL_ON, SRC_AUTO);
    }
}

static void onEnterParked() {
    if (drl_active) {
        cmd_queue::push(CMD_DRL_OFF, SRC_AUTO);
    }
}

static void updateStateMachine() {
    StateSnap s = snapshot();

    // Remember the most recent valid gear so isRealEngineOff() can still
    // distinguish "parked then turned off" from "idle stop" after the engine
    // ECU goes silent.
    if (s.gear[0] != '?' && s.gear[0] != '\0') {
        strncpy(last_known_gear, s.gear, sizeof(last_known_gear));
        last_known_gear[sizeof(last_known_gear) - 1] = '\0';
    }

    // Door open→close edge detection (used by circular locking)
    if (prev_any_door_open && !s.any_door_open) {
        door_event_pending = true;
    }
    prev_any_door_open = s.any_door_open;

    const bool engine_running = s.rpm > 0;
    const bool real_off       = isRealEngineOff(s);
    const uint8_t lock_speed  = nvs_cfg::cfg.lock_speed;

    switch (state) {

    case DrvState::ACC_ON:
        if (engine_running) {
            transitionTo(DrvState::ENGINE_ON);
            onEnterEngineOn();
        }
        break;

    case DrvState::ENGINE_ON:
        if (real_off) {
            engine_off_at = millis();
            transitionTo(DrvState::ENGINE_OFF);
        } else if (s.speed > 0) {
            transitionTo(DrvState::DRIVING);
        }
        break;

    case DrvState::DRIVING:
        if (real_off) {
            engine_off_at = millis();
            transitionTo(DrvState::ENGINE_OFF);
        } else if (s.speed >= lock_speed) {
            if (nvs_cfg::cfg.auto_lock) {
                cmd_queue::push(CMD_LOCK, SRC_AUTO);
            }
            transitionTo(DrvState::LOCKED_CRUISING);
        }
        break;

    case DrvState::LOCKED_CRUISING:
        if (real_off) {
            engine_off_at = millis();
            transitionTo(DrvState::ENGINE_OFF);
        } else if (s.speed == 0) {
            door_event_pending = false;  // arm fresh detection for this stop
            transitionTo(DrvState::LOCKED_STOPPED);
        }
        break;

    case DrvState::LOCKED_STOPPED:
        if (real_off) {
            engine_off_at = millis();
            transitionTo(DrvState::ENGINE_OFF);
            break;
        }
        // Idle stop (RPM=0 + gear=D/N) keeps us here — no transition.
        if (s.speed > 0) {
            transitionTo(DrvState::LOCKED_CRUISING);
            break;
        }
        if (door_event_pending) {
            door_event_pending = false;
            Serial.println("[auto] door open->close while locked, re-arm");
            transitionTo(DrvState::REARM);
        }
        break;

    case DrvState::REARM:
        if (real_off) {
            engine_off_at = millis();
            transitionTo(DrvState::ENGINE_OFF);
        } else if (s.speed >= lock_speed) {
            if (nvs_cfg::cfg.auto_lock) {
                cmd_queue::push(CMD_LOCK, SRC_AUTO);
                Serial.println("[auto] circular lock");
            }
            transitionTo(DrvState::LOCKED_CRUISING);
        }
        break;

    case DrvState::ENGINE_OFF:
        if (engine_running) {
            Serial.println("[auto] engine restart during countdown — cancel unlock");
            transitionTo(DrvState::ENGINE_ON);
            // Don't re-trigger DRL — it should already be active from the previous run.
            break;
        }
        if (millis() - engine_off_at >= (uint32_t)nvs_cfg::cfg.unlock_delay * 1000UL) {
            if (nvs_cfg::cfg.auto_unlock) {
                cmd_queue::push(CMD_UNLOCK, SRC_AUTO);
            }
            transitionTo(DrvState::PARKED);
            onEnterParked();
        }
        break;

    case DrvState::PARKED:
        if (engine_running) {
            transitionTo(DrvState::ENGINE_ON);
            onEnterEngineOn();
        }
        break;
    }
}

// ============================================================================
// State-Driven Polling
// ============================================================================

// Per-state schedulers (each owns the timers it needs).
static uint32_t last_fast = 0;
static uint32_t last_med  = 0;
static uint32_t last_slow = 0;
static uint32_t last_bcm  = 0;
static uint32_t last_gear = 0;
static uint32_t last_hbrk = 0;
static uint32_t last_eng  = 0;

static void pollForState() {
    // Low-power override: in ALL states except active driving, if the bus
    // has been silent long enough we just ping RPM occasionally.
    if (isLowPower()) {
        if (due(&last_fast, POLL_PARK_LP_RPM_MS)) pollRPM();
        return;
    }

    switch (state) {

    case DrvState::ACC_ON:
        // Just RPM (detect engine start) + occasional battery
        if (due(&last_fast, POLL_ACC_RPM_MS))   pollRPM();
        if (due(&last_med,  POLL_ACC_BATT_MS))  pollBattery();
        break;

    case DrvState::ENGINE_ON:
        if (due(&last_fast, POLL_ENGON_FAST_MS)) { pollRPM(); pollSpeed(); }
        if (due(&last_med,  POLL_ENGON_MED_MS))  { pollCoolant(); pollBattery(); }
        if (due(&last_bcm,  POLL_ENGON_BCM_MS))    pollBCM();
        if (due(&last_gear, POLL_ENGON_GEAR_MS))   pollGear();
        if (due(&last_hbrk, POLL_ENGON_HBRK_MS))   pollHbrk();
        if (due(&last_eng,  POLL_ENGON_ENG_MS))    pollEngStatus();
        break;

    case DrvState::DRIVING:
    case DrvState::LOCKED_CRUISING:
        // Full HUD data — OBD fast, BCM free during DRL session
        if (due(&last_fast, POLL_DRV_FAST_MS)) {
            pollRPM(); pollSpeed(); pollThrottle();
        }
        if (due(&last_med,  POLL_DRV_MED_MS))  { pollCoolant(); pollBattery(); }
        if (due(&last_slow, POLL_DRV_SLOW_MS)) { pollAmbient(); pollMil(); }
        if (due(&last_bcm,  POLL_DRV_BCM_MS))    pollBCM();
        if (due(&last_gear, POLL_DRV_GEAR_MS))   pollGear();  // keep fresh for ENGINE_OFF check
        break;

    case DrvState::LOCKED_STOPPED:
    case DrvState::REARM:
        // Stopped — watch RPM/Speed + doors (for circular lock) + gear (idle stop check)
        if (due(&last_fast, POLL_STOP_FAST_MS)) { pollRPM(); pollSpeed(); }
        if (due(&last_bcm,  POLL_STOP_BCM_MS))    pollBCM();
        if (due(&last_gear, POLL_STOP_GEAR_MS))   pollGear();
        break;

    case DrvState::ENGINE_OFF:
        // 3s countdown — just RPM to detect restart
        if (due(&last_fast, POLL_OFF_RPM_MS))     pollRPM();
        break;

    case DrvState::PARKED:
        if ((millis() - state_entered_ms) < LOWPOWER_ENTER_MS) {
            // Window 0–30s: safety check (gear/handbrake/doors)
            if (due(&last_bcm,  POLL_PARK_BCM_MS))    pollBCM();
            if (due(&last_gear, POLL_PARK_GEAR_MS))   pollGear();
            if (due(&last_hbrk, POLL_PARK_HBRK_MS))   pollHbrk();
        } else {
            // Low-power: only ping RPM every 30s to detect engine restart.
            // WiFi is suspended by wifi_task (which checks isLowPower()).
            if (due(&last_fast, POLL_PARK_LP_RPM_MS)) pollRPM();
        }
        break;
    }
}

// ============================================================================
// Command execution
// ============================================================================

static void execCmd(const Cmd& c) {
    Serial.printf("[cmd] %s from %s\n",
                  cmd_queue::typeLabel(c.type),
                  cmd_queue::sourceLabel(c.source));
    switch (c.type) {
        case CMD_LOCK:
            can_mgr::udsIoControlShortAdj(BCM_REQ, BCM_RESP, 0x0202, 0x00, 0x01, /*close=*/true);
            break;
        case CMD_UNLOCK:
            can_mgr::udsIoControlShortAdj(BCM_REQ, BCM_RESP, 0x0202, 0x00, 0x02, /*close=*/true);
            break;
        case CMD_DRL_ON:
            // Keep session open so TesterPresent keep-alive can extend it.
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
        case CMD_DUMP: {
            // Read every known DID and dump raw hex to Serial — handy for
            // hunting down which byte changes when toggling features like
            // idle stop. Runs on the CAN-poll task so the bus stays safe.
            static const struct {
                const char*  label;
                uint32_t     req;
                uint32_t     resp;
                uint16_t     did;
            } DIDS[] = {
                { "BCM 0x0109   ", BCM_REQ,   BCM_RESP,   DID_DOOR_BODY  },
                { "Light 0x0E07 ", LIGHT_REQ, LIGHT_RESP, DID_HANDBRAKE  },
                { "Engine 0x1301", ENG_REQ,   ENG_RESP,   DID_GEAR       },
                { "Engine 0x1304", ENG_REQ,   ENG_RESP,   DID_ENGINE_RUN },
            };
            Serial.println();
            Serial.println("====== DID DUMP (raw bytes) ======");
            Serial.printf("[t=%lu ms]\n", millis());
            for (auto& d : DIDS) {
                uint8_t buf[64];
                size_t n = can_mgr::udsReadDid(d.req, d.resp, d.did, buf, sizeof(buf));
                Serial.printf("%s len=%2u:", d.label, (unsigned)n);
                if (n == 0) {
                    Serial.print(" (no response)");
                } else {
                    for (size_t i = 0; i < n; i++) Serial.printf(" %02X", buf[i]);
                    // Also show index ruler for the first DID to make diffing easy
                    Serial.println();
                    Serial.print("              idx:");
                    for (size_t i = 0; i < n; i++) Serial.printf(" %02u", (unsigned)i);
                }
                Serial.println();
            }
            Serial.println("====== END DUMP ======");
            Serial.println();
            break;
        }
        default:
            break;
    }
}

// ============================================================================
// Task body
// ============================================================================

static void taskFn(void*) {
    state_entered_ms = millis();
    last_ok_poll_ms  = millis();
    bool last_lp = false;

    for (;;) {
        const bool lp = isLowPower();
        if (lp != last_lp) {
            Serial.printf("[power] %s\n", lp ? "→ LOW-POWER (WiFi off, RPM ping only)"
                                              : "→ ACTIVE");
            last_lp = lp;
        }

        // 1. Drain queue with short timeout (acts as our pacer when idle).
        Cmd c;
        if (cmd_queue::pop(c, 50)) {
            execCmd(c);
        }

        // 2. DRL keep-alive — keep BCM in ExtSession so commands stay valid.
        if (drl_active && (millis() - drl_last_tp >= DRL_TP_INTERVAL_MS)) {
            can_mgr::udsTesterPresent(BCM_REQ, BCM_RESP);
            drl_last_tp = millis();
        }

        // 3. Refresh request? Force all groups due.
        if (refresh_pending) {
            refresh_pending = false;
            uint32_t now = millis();
            last_fast = last_med = last_slow = now - 100000UL;
            last_bcm  = last_gear = last_hbrk = last_eng = now - 100000UL;
        }

        // 4. State-driven polling
        pollForState();

        // 5. Update state machine (may push auto-feature commands)
        updateStateMachine();

        // Yield. In low-power, sleep much longer to let CPU idle —
        // the OS auto-clock-gates when no task is runnable.
        vTaskDelay(pdMS_TO_TICKS(isLowPower() ? LOWPOWER_TASK_DELAY_MS : 5));
    }
}

void start(uint32_t stack, uint8_t priority) {
    xTaskCreate(taskFn, "canPoll", stack, nullptr, priority, nullptr);
}

}  // namespace poll_task
