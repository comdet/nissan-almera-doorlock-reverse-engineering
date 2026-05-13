#include "car_state.h"

namespace car_state {

CarState state;
static SemaphoreHandle_t mtx = nullptr;

void init() {
    if (!mtx) mtx = xSemaphoreCreateMutex();
}

bool lock(uint32_t timeout_ms) {
    if (!mtx) return false;
    return xSemaphoreTake(mtx, pdMS_TO_TICKS(timeout_ms)) == pdTRUE;
}

void unlock() {
    if (mtx) xSemaphoreGive(mtx);
}

}  // namespace car_state
