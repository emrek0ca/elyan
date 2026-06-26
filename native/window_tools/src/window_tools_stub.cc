#include "window_tools_platform.h"

namespace elyan::native {

bool ActiveWindowCapabilityAvailable() { return false; }

Napi::Object BuildActiveWindowInfo(Napi::Env env) {
  Napi::Object result = Napi::Object::New(env);
  result.Set("available", Napi::Boolean::New(env, false));
  result.Set("appName", Napi::String::New(env, ""));
  result.Set("windowTitle", Napi::String::New(env, ""));
  result.Set("processId", env.Null());
  result.Set("executablePath", Napi::String::New(env, ""));
  result.Set("bundleId", Napi::String::New(env, ""));
  return result;
}

Napi::Object BuildPermissionInfo(Napi::Env env) {
  return Napi::Object::New(env);
}

Napi::Object BuildOperatorInfo(Napi::Env env) {
  Napi::Object result = Napi::Object::New(env);
  result.Set("available", Napi::Boolean::New(env, false));
  result.Set("mode", Napi::String::New(env, "scaffold_only"));
  result.Set("screenObservationReady", Napi::Boolean::New(env, false));
  result.Set("accessibilityReady", Napi::Boolean::New(env, false));
  result.Set("inputControlReady", Napi::Boolean::New(env, false));
  result.Set("emergencyStopAvailable", Napi::Boolean::New(env, false));
  result.Set("failSafeCornerAbort", Napi::Boolean::New(env, true));
  result.Set("browserFirstReady", Napi::Boolean::New(env, false));
  result.Set("activeRunSummary", Napi::Object::New(env));
  result.Set("lastErrorCode", Napi::String::New(env, "operator_not_ready"));
  return result;
}

}  // namespace elyan::native
