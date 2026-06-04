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

}  // namespace elyan::native
