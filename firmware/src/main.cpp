/*
 * ESP32-C3 SLCAN (Serial-Line CAN) Adapter
 *
 * Firmware สำหรับ ESP32-C3 + SN65HVD230 CAN transceiver
 * ทำตัวเป็น SLCAN adapter เพื่อให้ python-can สื่อสารผ่าน slcan interface
 *
 * SLCAN Protocol (LAWICEL):
 *   O        — Open CAN channel
 *   C        — Close CAN channel
 *   S6       — Set speed 500kbps
 *   tIIILDD  — Transmit standard frame (t + 3-char ID + 1-char DLC + hex data)
 *   T...     — Transmit extended frame
 *   F        — Read status flags
 *   V        — Version
 *   N        — Serial number
 *
 * การต่อสาย ESP32-C3 กับ SN65HVD230:
 *   ESP32-C3 GPIO4 (TX) → SN65HVD230 D (Driver Input)
 *   ESP32-C3 GPIO5 (RX) → SN65HVD230 R (Receiver Output)
 *   ESP32-C3 3.3V       → SN65HVD230 VCC
 *   ESP32-C3 GND        → SN65HVD230 GND
 *   SN65HVD230 CANH     → CAN Bus H
 *   SN65HVD230 CANL     → CAN Bus L
 *   SN65HVD230 Rs       → GND (slope control: high speed mode)
 *
 * ใช้งานกับ python-can:
 *   import can
 *   bus = can.interface.Bus(interface='slcan', channel='/dev/ttyACM0', bitrate=500000)
 */

#include <Arduino.h>
#include <driver/twai.h>

// ===================== Pin Configuration =====================
// เปลี่ยน pin ได้ตามต้องการ (ESP32-C3 ใช้ GPIO ไหนก็ได้ผ่าน GPIO Matrix)
// หลีกเลี่ยง GPIO2, GPIO8, GPIO9 (strapping pins)
#define CAN_TX_PIN  GPIO_NUM_4
#define CAN_RX_PIN  GPIO_NUM_5

// ===================== SLCAN Configuration =====================
#define SLCAN_SERIAL       Serial        // USB CDC serial
#define SLCAN_BAUD         115200        // serial baud rate (USB CDC ไม่ใช้จริง แต่ตั้งไว้)
#define SLCAN_CMD_BUF_SIZE 64
#define SLCAN_MTU          32            // max SLCAN command length

// ===================== State =====================
static bool canOpen = false;
static uint32_t canSpeed = 500000;       // default 500kbps
static char cmdBuf[SLCAN_CMD_BUF_SIZE];
static uint8_t cmdLen = 0;

// ===================== CAN Speed Table =====================
// SLCAN S command: S0-S8
static const uint32_t slcanSpeedTable[] = {
    10000,    // S0 = 10kbps
    20000,    // S1 = 20kbps
    50000,    // S2 = 50kbps
    100000,   // S3 = 100kbps
    125000,   // S4 = 125kbps
    250000,   // S5 = 250kbps
    500000,   // S6 = 500kbps
    800000,   // S7 = 800kbps
    1000000   // S8 = 1000kbps
};

// ===================== Helper Functions =====================

static uint8_t hexCharToNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return 0;
}

static char nibbleToHexChar(uint8_t n) {
    n &= 0x0F;
    return (n < 10) ? ('0' + n) : ('A' + n - 10);
}

// ===================== CAN Init / Deinit =====================

static bool canInit(uint32_t speed) {
    twai_timing_config_t timingConfig;

    switch (speed) {
        case 10000:   timingConfig = TWAI_TIMING_CONFIG_10KBITS();   break;
        case 20000:   timingConfig = TWAI_TIMING_CONFIG_20KBITS();   break;
        case 25000:   timingConfig = TWAI_TIMING_CONFIG_25KBITS();   break;
        case 50000:   timingConfig = TWAI_TIMING_CONFIG_50KBITS();   break;
        case 100000:  timingConfig = TWAI_TIMING_CONFIG_100KBITS();  break;
        case 125000:  timingConfig = TWAI_TIMING_CONFIG_125KBITS();  break;
        case 250000:  timingConfig = TWAI_TIMING_CONFIG_250KBITS();  break;
        case 500000:  timingConfig = TWAI_TIMING_CONFIG_500KBITS();  break;
        case 800000:  timingConfig = TWAI_TIMING_CONFIG_800KBITS();  break;
        case 1000000: timingConfig = TWAI_TIMING_CONFIG_1MBITS();    break;
        default:      timingConfig = TWAI_TIMING_CONFIG_500KBITS();  break;
    }

    twai_general_config_t generalConfig = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_LISTEN_ONLY);
    generalConfig.rx_queue_len = 64;
    generalConfig.tx_queue_len = 16;

    twai_filter_config_t filterConfig = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    esp_err_t err = twai_driver_install(&generalConfig, &timingConfig, &filterConfig);
    if (err != ESP_OK) return false;

    err = twai_start();
    if (err != ESP_OK) {
        twai_driver_uninstall();
        return false;
    }

    return true;
}

static void canDeinit() {
    twai_stop();
    twai_driver_uninstall();
}

// ===================== SLCAN → CAN TX =====================

static bool slcanTransmitStandard(const char *cmd, uint8_t len) {
    // Format: tIIILDD..DD
    // t + 3 hex chars (ID) + 1 hex char (DLC) + 2*DLC hex chars (data)
    if (len < 5) return false;

    uint32_t id = (hexCharToNibble(cmd[1]) << 8) |
                  (hexCharToNibble(cmd[2]) << 4) |
                   hexCharToNibble(cmd[3]);
    uint8_t dlc = hexCharToNibble(cmd[4]);
    if (dlc > 8) return false;
    if (len < (5 + dlc * 2)) return false;

    twai_message_t msg;
    msg.identifier = id;
    msg.data_length_code = dlc;
    msg.extd = 0;
    msg.rtr = 0;
    msg.ss = 1;  // single shot mode for reliability

    for (uint8_t i = 0; i < dlc; i++) {
        msg.data[i] = (hexCharToNibble(cmd[5 + i * 2]) << 4) |
                       hexCharToNibble(cmd[6 + i * 2]);
    }

    esp_err_t err = twai_transmit(&msg, pdMS_TO_TICKS(100));
    return (err == ESP_OK);
}

static bool slcanTransmitExtended(const char *cmd, uint8_t len) {
    // Format: TIIIIIIIILDD..DD
    // T + 8 hex chars (29-bit ID) + 1 hex char (DLC) + 2*DLC hex chars (data)
    if (len < 10) return false;

    uint32_t id = 0;
    for (uint8_t i = 1; i <= 8; i++) {
        id = (id << 4) | hexCharToNibble(cmd[i]);
    }
    uint8_t dlc = hexCharToNibble(cmd[9]);
    if (dlc > 8) return false;
    if (len < (10 + dlc * 2)) return false;

    twai_message_t msg;
    msg.identifier = id;
    msg.data_length_code = dlc;
    msg.extd = 1;
    msg.rtr = 0;
    msg.ss = 1;

    for (uint8_t i = 0; i < dlc; i++) {
        msg.data[i] = (hexCharToNibble(cmd[10 + i * 2]) << 4) |
                       hexCharToNibble(cmd[11 + i * 2]);
    }

    esp_err_t err = twai_transmit(&msg, pdMS_TO_TICKS(100));
    return (err == ESP_OK);
}

static bool slcanTransmitRtrStandard(const char *cmd, uint8_t len) {
    // Format: rIIIL
    if (len < 5) return false;

    uint32_t id = (hexCharToNibble(cmd[1]) << 8) |
                  (hexCharToNibble(cmd[2]) << 4) |
                   hexCharToNibble(cmd[3]);
    uint8_t dlc = hexCharToNibble(cmd[4]);
    if (dlc > 8) return false;

    twai_message_t msg;
    msg.identifier = id;
    msg.data_length_code = dlc;
    msg.extd = 0;
    msg.rtr = 1;
    msg.ss = 1;

    esp_err_t err = twai_transmit(&msg, pdMS_TO_TICKS(100));
    return (err == ESP_OK);
}

static bool slcanTransmitRtrExtended(const char *cmd, uint8_t len) {
    // Format: RIIIIIIIIL
    if (len < 10) return false;

    uint32_t id = 0;
    for (uint8_t i = 1; i <= 8; i++) {
        id = (id << 4) | hexCharToNibble(cmd[i]);
    }
    uint8_t dlc = hexCharToNibble(cmd[9]);
    if (dlc > 8) return false;

    twai_message_t msg;
    msg.identifier = id;
    msg.data_length_code = dlc;
    msg.extd = 1;
    msg.rtr = 1;
    msg.ss = 1;

    esp_err_t err = twai_transmit(&msg, pdMS_TO_TICKS(100));
    return (err == ESP_OK);
}

// ===================== CAN RX → SLCAN =====================

static void canReceiveToSlcan() {
    twai_message_t msg;

    // Read all available messages from RX queue
    while (twai_receive(&msg, 0) == ESP_OK) {
        if (msg.rtr) {
            // RTR frame
            if (msg.extd) {
                SLCAN_SERIAL.print('R');
                for (int i = 7; i >= 0; i--) {
                    SLCAN_SERIAL.print(nibbleToHexChar((msg.identifier >> (i * 4)) & 0x0F));
                }
            } else {
                SLCAN_SERIAL.print('r');
                SLCAN_SERIAL.print(nibbleToHexChar((msg.identifier >> 8) & 0x0F));
                SLCAN_SERIAL.print(nibbleToHexChar((msg.identifier >> 4) & 0x0F));
                SLCAN_SERIAL.print(nibbleToHexChar(msg.identifier & 0x0F));
            }
            SLCAN_SERIAL.print(nibbleToHexChar(msg.data_length_code));
        } else {
            // Data frame
            if (msg.extd) {
                SLCAN_SERIAL.print('T');
                for (int i = 7; i >= 0; i--) {
                    SLCAN_SERIAL.print(nibbleToHexChar((msg.identifier >> (i * 4)) & 0x0F));
                }
            } else {
                SLCAN_SERIAL.print('t');
                SLCAN_SERIAL.print(nibbleToHexChar((msg.identifier >> 8) & 0x0F));
                SLCAN_SERIAL.print(nibbleToHexChar((msg.identifier >> 4) & 0x0F));
                SLCAN_SERIAL.print(nibbleToHexChar(msg.identifier & 0x0F));
            }
            SLCAN_SERIAL.print(nibbleToHexChar(msg.data_length_code));

            for (uint8_t i = 0; i < msg.data_length_code; i++) {
                SLCAN_SERIAL.print(nibbleToHexChar(msg.data[i] >> 4));
                SLCAN_SERIAL.print(nibbleToHexChar(msg.data[i] & 0x0F));
            }
        }
        SLCAN_SERIAL.print('\r');  // SLCAN uses CR as delimiter
    }
}

// ===================== SLCAN Command Processing =====================

static void processSlcanCommand(const char *cmd, uint8_t len) {
    if (len == 0) return;

    bool ok = false;

    switch (cmd[0]) {
        case 'O':  // Open CAN channel
            if (!canOpen) {
                if (canInit(canSpeed)) {
                    canOpen = true;
                    ok = true;
                }
            }
            break;

        case 'C':  // Close CAN channel
            if (canOpen) {
                canDeinit();
                canOpen = false;
            }
            ok = true;
            break;

        case 'S':  // Set CAN speed
            if (!canOpen && len >= 2) {
                uint8_t idx = hexCharToNibble(cmd[1]);
                if (idx <= 8) {
                    canSpeed = slcanSpeedTable[idx];
                    ok = true;
                }
            }
            break;

        case 's':  // Set CAN speed (BTR registers) - not supported, just ACK
            ok = true;
            break;

        case 't':  // Transmit standard frame
            if (canOpen) {
                ok = slcanTransmitStandard(cmd, len);
            }
            break;

        case 'T':  // Transmit extended frame
            if (canOpen) {
                ok = slcanTransmitExtended(cmd, len);
            }
            break;

        case 'r':  // Transmit RTR standard
            if (canOpen) {
                ok = slcanTransmitRtrStandard(cmd, len);
            }
            break;

        case 'R':  // Transmit RTR extended
            if (canOpen) {
                ok = slcanTransmitRtrExtended(cmd, len);
            }
            break;

        case 'F':  // Read status flags — enhanced with TWAI debug
            if (canOpen) {
                twai_status_info_t status;
                if (twai_get_status_info(&status) == ESP_OK) {
                    // Encode state + error counts into status byte
                    uint8_t flags = 0;
                    if (status.state == TWAI_STATE_BUS_OFF) flags |= 0x80;
                    if (status.tx_error_counter > 0) flags |= 0x20;
                    if (status.rx_error_counter > 0) flags |= 0x10;
                    if (status.rx_missed_count > 0) flags |= 0x04;
                    char buf[128];
                    snprintf(buf, sizeof(buf),
                        "F%02X\r"
                        "# state=%d tx_err=%lu rx_err=%lu "
                        "tx_q=%lu rx_q=%lu "
                        "msgs_to_tx=%lu msgs_to_rx=%lu "
                        "rx_missed=%lu arb_lost=%lu bus_err=%lu\r",
                        flags,
                        (int)status.state,
                        status.tx_error_counter,
                        status.rx_error_counter,
                        status.msgs_to_tx,
                        status.msgs_to_rx,
                        status.tx_failed_count,
                        status.rx_missed_count,
                        status.rx_missed_count,
                        status.arb_lost_count,
                        status.bus_error_count);
                    SLCAN_SERIAL.print(buf);
                } else {
                    SLCAN_SERIAL.print("F00\r");
                }
            } else {
                SLCAN_SERIAL.print("F00\r# CAN not open\r");
            }
            return;  // already sent response

        case 'V':  // Hardware version
            SLCAN_SERIAL.print("V0101\r");
            return;

        case 'N':  // Serial number
            SLCAN_SERIAL.print("NC3CA\r");
            return;

        case 'Z':  // Timestamp on/off — accept but ignore
            ok = true;
            break;

        case 'M':  // Acceptance mask — accept but ignore (we accept all)
        case 'm':
            ok = true;
            break;

        default:
            break;
    }

    if (ok) {
        SLCAN_SERIAL.print('\r');     // CR = OK (SLCAN standard)
    } else {
        SLCAN_SERIAL.print('\a');     // BEL = Error (SLCAN standard)
    }
}

// ===================== Arduino Setup & Loop =====================

void setup() {
    SLCAN_SERIAL.begin(SLCAN_BAUD);

    // Wait for USB CDC to connect (ESP32-C3 USB)
    while (!SLCAN_SERIAL) {
        delay(10);
    }

    // Small delay for stability
    delay(100);
}

void loop() {
    // 1. Read incoming SLCAN commands from serial
    while (SLCAN_SERIAL.available()) {
        char c = SLCAN_SERIAL.read();

        if (c == '\r' || c == '\n') {
            // End of command
            if (cmdLen > 0) {
                cmdBuf[cmdLen] = '\0';
                processSlcanCommand(cmdBuf, cmdLen);
                cmdLen = 0;
            }
        } else {
            if (cmdLen < SLCAN_CMD_BUF_SIZE - 1) {
                cmdBuf[cmdLen++] = c;
            } else {
                // Buffer overflow — reset
                cmdLen = 0;
            }
        }
    }

    // 2. Forward received CAN frames to serial as SLCAN
    if (canOpen) {
        canReceiveToSlcan();
    }
}
