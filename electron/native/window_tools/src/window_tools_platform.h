#pragma once

#include <napi.h>

namespace elyan::native {

bool ActiveWindowCapabilityAvailable();
Napi::Object BuildActiveWindowInfo(Napi::Env env);

}  // namespace elyan::native
