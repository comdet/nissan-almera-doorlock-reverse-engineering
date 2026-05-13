/*
 * BOOT button (GPIO9) long-press detector.
 *
 * On a hold of BUTTON_HOLD_MS ms, sets the next-boot flag in NVS and reboots
 * into config portal mode. Tap (short press) is ignored.
 *
 * The button shares GPIO9 with the boot-mode strap, but is only sampled
 * *after* boot, so normal SPI boot is unaffected.
 */

#pragma once

#include <stdint.h>

namespace button_task {

void start(uint32_t stack = 2048, uint8_t priority = 1);

// True for as long as the button is currently held (debounced).
bool isPressed();

}  // namespace button_task
