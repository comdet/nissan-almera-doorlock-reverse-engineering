#include "can_manager.h"
#include "config.h"
#include <Arduino.h>
#include <string.h>

namespace can_mgr {

static const uint8_t PAD = 0xFF;

bool init() {
    twai_general_config_t g = TWAI_GENERAL_CONFIG_DEFAULT(
        (gpio_num_t)CAN_TX_PIN, (gpio_num_t)CAN_RX_PIN, TWAI_MODE_NORMAL);
    g.rx_queue_len = 64;
    g.tx_queue_len = 16;

    twai_timing_config_t t = TWAI_TIMING_CONFIG_500KBITS();
    twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    if (twai_driver_install(&g, &t, &f) != ESP_OK) return false;
    if (twai_start() != ESP_OK) {
        twai_driver_uninstall();
        return false;
    }
    return true;
}

void deinit() {
    twai_stop();
    twai_driver_uninstall();
}

bool sendFrame(uint32_t id, const uint8_t* data, uint8_t len) {
    if (len > 8) return false;
    twai_message_t m = {};
    m.identifier = id;
    m.data_length_code = len;
    m.extd = 0;
    m.rtr = 0;
    m.ss  = 0;
    memcpy(m.data, data, len);
    return twai_transmit(&m, pdMS_TO_TICKS(50)) == ESP_OK;
}

bool waitFrame(uint32_t expected_id, twai_message_t* out, uint32_t timeout_ms) {
    uint32_t deadline = millis() + timeout_ms;
    twai_message_t m;
    while ((int32_t)(deadline - millis()) > 0) {
        // Poll with short tick — quicker than blocking the whole window.
        if (twai_receive(&m, pdMS_TO_TICKS(20)) == ESP_OK) {
            if (m.identifier == expected_id) {
                *out = m;
                return true;
            }
            // not our id — drop and keep looking
        }
    }
    return false;
}

// Drain all frames currently in the RX queue (used to clear stale data).
static void drainRx() {
    twai_message_t m;
    while (twai_receive(&m, 0) == ESP_OK) { /* discard */ }
}

bool udsSetSession(uint32_t req_id, uint32_t resp_id, uint8_t session) {
    drainRx();
    uint8_t payload[8] = { 0x02, SID_SESSION_CTRL, session, PAD, PAD, PAD, PAD, PAD };
    if (!sendFrame(req_id, payload, 8)) return false;

    twai_message_t resp;
    uint32_t deadline = millis() + TIMEOUT_FRAME_MS;
    while ((int32_t)(deadline - millis()) > 0) {
        if (!waitFrame(resp_id, &resp, TIMEOUT_FRAME_MS)) return false;
        if (resp.data_length_code < 2) continue;
        // Positive: [_ 0x50 session ...] / Negative: [_ 0x7F 0x10 NRC]
        if (resp.data[1] == 0x50) return true;
        if (resp.data[1] == 0x7F) {
            if (resp.data_length_code >= 4 && resp.data[3] == NRC_RESPONSE_PENDING) {
                continue;  // wait for final
            }
            return false;
        }
    }
    return false;
}

size_t udsReadDid(uint32_t req_id, uint32_t resp_id, uint16_t did,
                  uint8_t* out, size_t max_len) {
    if (!udsSetSession(req_id, resp_id, SESSION_EXTENDED)) {
        return 0;
    }

    // Tiny gap between session response and the read request — matches Python timing.
    delay(INTER_FRAME_MS);
    drainRx();

    uint8_t dh = (uint8_t)((did >> 8) & 0xFF);
    uint8_t dl = (uint8_t)(did & 0xFF);
    uint8_t req[8] = { 0x03, SID_READ_DID, dh, dl, PAD, PAD, PAD, PAD };
    if (!sendFrame(req_id, req, 8)) {
        udsSetSession(req_id, resp_id, SESSION_DEFAULT);
        return 0;
    }

    size_t written  = 0;
    bool   ff_seen  = false;
    size_t total_len = 0;
    uint32_t deadline = millis() + TIMEOUT_PENDING_MS;
    twai_message_t resp;

    while ((int32_t)(deadline - millis()) > 0) {
        if (!waitFrame(resp_id, &resp, 100)) continue;
        if (resp.data_length_code < 1) continue;

        // Negative response detection ahead of PCI parsing.
        // SF negative response: [03 7F 22 NRC]
        if (!ff_seen && resp.data_length_code >= 4 &&
            resp.data[1] == SID_NEG_RESP && resp.data[2] == SID_READ_DID) {
            if (resp.data[3] == NRC_RESPONSE_PENDING) {
                continue;  // wait — ECU busy (slow multiframe DIDs)
            }
            udsSetSession(req_id, resp_id, SESSION_DEFAULT);
            return 0;
        }

        uint8_t pci = (resp.data[0] >> 4) & 0x0F;

        if (pci == 0x0 && !ff_seen) {
            // Single Frame
            size_t n = resp.data[0] & 0x0F;
            if (n > 7) n = 7;
            if (n > max_len) n = max_len;
            memcpy(out, &resp.data[1], n);
            written = n;
            break;
        }

        if (pci == 0x1 && !ff_seen) {
            // First Frame
            total_len = ((resp.data[0] & 0x0F) << 8) | resp.data[1];
            size_t avail = (resp.data_length_code >= 2) ? (size_t)(resp.data_length_code - 2) : 0;
            size_t copy  = (avail > max_len) ? max_len : avail;
            memcpy(out, &resp.data[2], copy);
            written = copy;
            ff_seen = true;

            // Flow Control: continue all, no gap
            uint8_t fc[8] = { 0x30, 0x00, 0x00, PAD, PAD, PAD, PAD, PAD };
            sendFrame(req_id, fc, 8);
            continue;
        }

        if (pci == 0x2 && ff_seen) {
            // Consecutive Frame
            size_t avail = (resp.data_length_code >= 1) ? (size_t)(resp.data_length_code - 1) : 0;
            size_t want  = (written < total_len) ? (total_len - written) : 0;
            size_t copy  = avail;
            if (copy > want) copy = want;
            if (written + copy > max_len) copy = max_len - written;
            memcpy(out + written, &resp.data[1], copy);
            written += copy;
            if (written >= total_len) break;
        }
    }

    // Return to default session (best effort)
    udsSetSession(req_id, resp_id, SESSION_DEFAULT);

    return written;
}

size_t obdQuery(uint8_t pid, uint8_t* out, size_t max_len) {
    drainRx();

    uint8_t req[8] = { 0x02, 0x01, pid, 0, 0, 0, 0, 0 };
    if (!sendFrame(OBD_BROADCAST, req, 8)) return 0;

    twai_message_t resp;
    uint32_t deadline = millis() + TIMEOUT_FRAME_MS;
    while ((int32_t)(deadline - millis()) > 0) {
        if (!waitFrame(OBD_RESP_ECM, &resp, 100)) continue;
        if (resp.data_length_code < 3) continue;
        // Expect Single Frame [len 0x41 PID data...]
        uint8_t len = resp.data[0] & 0x0F;
        if (resp.data[1] != 0x41) continue;
        if (resp.data[2] != pid) continue;
        // data starts at byte 3, length = len-2 (subtract 0x41 + PID)
        size_t n = (len >= 2) ? (size_t)(len - 2) : 0;
        if (n > 5) n = 5;  // cap at remaining bytes in 8-byte frame
        if (n > max_len) n = max_len;
        memcpy(out, &resp.data[3], n);
        return n;
    }
    return 0;
}

uint32_t getRxMissed() {
    twai_status_info_t s;
    if (twai_get_status_info(&s) == ESP_OK) return s.rx_missed_count;
    return 0;
}

uint32_t getTxFailed() {
    twai_status_info_t s;
    if (twai_get_status_info(&s) == ESP_OK) return s.tx_failed_count;
    return 0;
}

// ---------------- UDS commands ----------------

bool udsTesterPresent(uint32_t req_id, uint32_t resp_id) {
    drainRx();
    uint8_t payload[8] = { 0x02, SID_TESTER_PRES, 0x00, PAD, PAD, PAD, PAD, PAD };
    if (!sendFrame(req_id, payload, 8)) return false;
    twai_message_t resp;
    return waitFrame(resp_id, &resp, TIMEOUT_FRAME_MS);
}

bool udsIoControlShortAdj(uint32_t req_id, uint32_t resp_id, uint16_t did,
                          uint8_t state_a, uint8_t state_b, bool close) {
    if (!udsSetSession(req_id, resp_id, SESSION_EXTENDED)) return false;
    delay(INTER_FRAME_MS);
    udsTesterPresent(req_id, resp_id);

    drainRx();
    uint8_t dh = (uint8_t)((did >> 8) & 0xFF);
    uint8_t dl = (uint8_t)(did & 0xFF);
    // 06 2F DH DL 03 A B FF — controlParam 0x03 = shortTermAdjustment
    uint8_t payload[8] = { 0x06, SID_IO_CONTROL, dh, dl, 0x03, state_a, state_b, 0xFF };
    if (!sendFrame(req_id, payload, 8)) {
        if (close) udsSetSession(req_id, resp_id, SESSION_DEFAULT);
        return false;
    }

    twai_message_t resp;
    bool positive = false;
    uint32_t deadline = millis() + TIMEOUT_FRAME_MS;
    while ((int32_t)(deadline - millis()) > 0) {
        if (!waitFrame(resp_id, &resp, 100)) continue;
        if (resp.data_length_code < 2) continue;
        // Positive: [_ 0x6F ...] / Negative: [_ 0x7F 0x2F NRC]
        if (resp.data[1] == 0x6F) { positive = true; break; }
        if (resp.data[1] == 0x7F) {
            if (resp.data_length_code >= 4 && resp.data[3] == NRC_RESPONSE_PENDING) continue;
            break;
        }
    }

    if (close) udsSetSession(req_id, resp_id, SESSION_DEFAULT);
    return positive;
}

}  // namespace can_mgr
