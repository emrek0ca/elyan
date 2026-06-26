#pragma once

#include <napi.h>

namespace elyan::native {

bool ActiveWindowCapabilityAvailable();
Napi::Object BuildActiveWindowInfo(Napi::Env env);
Napi::Object BuildPermissionInfo(Napi::Env env);
Napi::Object BuildOperatorInfo(Napi::Env env);

}  // namespace elyan::native
