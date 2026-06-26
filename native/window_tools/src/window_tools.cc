#include <napi.h>

#include "window_tools_platform.h"

namespace {

Napi::Object Capabilities(const Napi::CallbackInfo& info) {
  Napi::Env env = info.Env();
  Napi::Object result = Napi::Object::New(env);

#if defined(__APPLE__)
  result.Set("customTitlebar", Napi::Boolean::New(env, true));
  result.Set("closeAnimation", Napi::Boolean::New(env, true));
  result.Set("trafficLights", Napi::Boolean::New(env, true));
  result.Set("vibrancy", Napi::Boolean::New(env, true));
  result.Set("mica", Napi::Boolean::New(env, false));
  result.Set("clientSideDecorations", Napi::Boolean::New(env, true));
  result.Set("tray", Napi::Boolean::New(env, true));
  result.Set("attention", Napi::Boolean::New(env, true));
#elif defined(_WIN32)
  result.Set("customTitlebar", Napi::Boolean::New(env, true));
  result.Set("closeAnimation", Napi::Boolean::New(env, true));
  result.Set("trafficLights", Napi::Boolean::New(env, false));
  result.Set("vibrancy", Napi::Boolean::New(env, false));
  result.Set("mica", Napi::Boolean::New(env, true));
  result.Set("clientSideDecorations", Napi::Boolean::New(env, true));
  result.Set("tray", Napi::Boolean::New(env, true));
  result.Set("attention", Napi::Boolean::New(env, true));
#else
  result.Set("customTitlebar", Napi::Boolean::New(env, true));
  result.Set("closeAnimation", Napi::Boolean::New(env, true));
  result.Set("trafficLights", Napi::Boolean::New(env, false));
  result.Set("vibrancy", Napi::Boolean::New(env, false));
  result.Set("mica", Napi::Boolean::New(env, false));
  result.Set("clientSideDecorations", Napi::Boolean::New(env, true));
  result.Set("tray", Napi::Boolean::New(env, false));
  result.Set("attention", Napi::Boolean::New(env, true));
#endif

  return result;
}

Napi::Object WindowMetrics(const Napi::CallbackInfo& info) {
  Napi::Env env = info.Env();
  Napi::Object result = Napi::Object::New(env);

#if defined(__APPLE__)
  result.Set("titlebarInset", Napi::Number::New(env, 18));
  result.Set("trafficLightOffsetX", Napi::Number::New(env, 18));
  result.Set("trafficLightOffsetY", Napi::Number::New(env, 16));
#elif defined(_WIN32)
  result.Set("titlebarInset", Napi::Number::New(env, 16));
  result.Set("trafficLightOffsetX", Napi::Number::New(env, 16));
  result.Set("trafficLightOffsetY", Napi::Number::New(env, 14));
#else
  result.Set("titlebarInset", Napi::Number::New(env, 12));
  result.Set("trafficLightOffsetX", Napi::Number::New(env, 12));
  result.Set("trafficLightOffsetY", Napi::Number::New(env, 12));
#endif

  return result;
}

Napi::Object SystemIntegrationStatus(const Napi::CallbackInfo& info) {
  Napi::Env env = info.Env();
  Napi::Object result = Napi::Object::New(env);

  result.Set("automation", Napi::Boolean::New(env, true));
  result.Set("screenCapture", Napi::Boolean::New(env, true));
  result.Set("globalShortcuts", Napi::Boolean::New(env, true));
  result.Set("fileSystemAccess", Napi::Boolean::New(env, true));
  result.Set("processInspection", Napi::Boolean::New(env, true));
  result.Set("permissionRequired", Napi::Boolean::New(env, true));
  result.Set("rendererDirectControl", Napi::Boolean::New(env, false));
  result.Set("sideEffectsRequireTaskId", Napi::Boolean::New(env, true));

#if defined(__APPLE__)
  result.Set("osPermissionModel", Napi::String::New(env, "macos_privacy_tcc"));
  result.Set("accessibilityPermissionRequired", Napi::Boolean::New(env, true));
  result.Set("screenRecordingPermissionRequired", Napi::Boolean::New(env, true));
  result.Set("inputMonitoringPermissionRequired", Napi::Boolean::New(env, true));
  result.Set("automationPermissionRequired", Napi::Boolean::New(env, true));
#elif defined(_WIN32)
  result.Set("osPermissionModel", Napi::String::New(env, "windows_user_session"));
  result.Set("accessibilityPermissionRequired", Napi::Boolean::New(env, false));
  result.Set("screenRecordingPermissionRequired", Napi::Boolean::New(env, false));
  result.Set("inputMonitoringPermissionRequired", Napi::Boolean::New(env, false));
  result.Set("automationPermissionRequired", Napi::Boolean::New(env, false));
#else
  result.Set("osPermissionModel", Napi::String::New(env, "linux_desktop_portal_or_x11"));
  result.Set("accessibilityPermissionRequired", Napi::Boolean::New(env, false));
  result.Set("screenRecordingPermissionRequired", Napi::Boolean::New(env, true));
  result.Set("inputMonitoringPermissionRequired", Napi::Boolean::New(env, true));
  result.Set("automationPermissionRequired", Napi::Boolean::New(env, true));
#endif

  return result;
}

Napi::Object DesktopCapabilitySnapshot(const Napi::CallbackInfo& info) {
  Napi::Env env = info.Env();
  Napi::Object result = Napi::Object::New(env);
  Napi::Object permissions = Napi::Object::New(env);
  Napi::Object active_window = elyan::native::BuildActiveWindowInfo(env);
  Napi::Object operator_info = elyan::native::BuildOperatorInfo(env);

#if defined(__APPLE__)
  result.Set("available", Napi::Boolean::New(env, true));
  result.Set("processInspectionAvailable", Napi::Boolean::New(env, true));
  result.Set("activeWindowAvailable", active_window.Get("available"));
  result.Set("permissionProbeAvailable", Napi::Boolean::New(env, true));
  permissions = elyan::native::BuildPermissionInfo(env);
#elif defined(_WIN32)
  result.Set("available", Napi::Boolean::New(env, true));
  result.Set("processInspectionAvailable", Napi::Boolean::New(env, true));
  result.Set("activeWindowAvailable", Napi::Boolean::New(env, elyan::native::ActiveWindowCapabilityAvailable()));
  result.Set("permissionProbeAvailable", Napi::Boolean::New(env, true));
  permissions.Set("accessibility", Napi::Object::New(env));
  permissions.Set("screenRecording", Napi::Object::New(env));
  permissions.Set("inputMonitoring", Napi::Object::New(env));
  permissions.Set("automation", Napi::Object::New(env));
  permissions.Get("accessibility").As<Napi::Object>().Set("required", Napi::Boolean::New(env, false));
  permissions.Get("accessibility").As<Napi::Object>().Set("granted", Napi::Boolean::New(env, true));
  permissions.Get("accessibility").As<Napi::Object>().Set("status", Napi::String::New(env, "not_required"));
  permissions.Get("screenRecording").As<Napi::Object>().Set("required", Napi::Boolean::New(env, false));
  permissions.Get("screenRecording").As<Napi::Object>().Set("granted", Napi::Boolean::New(env, true));
  permissions.Get("screenRecording").As<Napi::Object>().Set("status", Napi::String::New(env, "not_required"));
  permissions.Get("inputMonitoring").As<Napi::Object>().Set("required", Napi::Boolean::New(env, false));
  permissions.Get("inputMonitoring").As<Napi::Object>().Set("granted", Napi::Boolean::New(env, true));
  permissions.Get("inputMonitoring").As<Napi::Object>().Set("status", Napi::String::New(env, "not_required"));
  permissions.Get("automation").As<Napi::Object>().Set("required", Napi::Boolean::New(env, false));
  permissions.Get("automation").As<Napi::Object>().Set("granted", Napi::Boolean::New(env, true));
  permissions.Get("automation").As<Napi::Object>().Set("status", Napi::String::New(env, "not_required"));
#else
  result.Set("available", Napi::Boolean::New(env, true));
  result.Set("processInspectionAvailable", Napi::Boolean::New(env, true));
  result.Set("activeWindowAvailable", Napi::Boolean::New(env, elyan::native::ActiveWindowCapabilityAvailable()));
  result.Set("permissionProbeAvailable", Napi::Boolean::New(env, true));
  permissions.Set("accessibility", Napi::Object::New(env));
  permissions.Set("screenRecording", Napi::Object::New(env));
  permissions.Set("inputMonitoring", Napi::Object::New(env));
  permissions.Set("automation", Napi::Object::New(env));
  permissions.Get("accessibility").As<Napi::Object>().Set("required", Napi::Boolean::New(env, false));
  permissions.Get("accessibility").As<Napi::Object>().Set("granted", env.Null());
  permissions.Get("accessibility").As<Napi::Object>().Set("status", Napi::String::New(env, "unknown"));
  permissions.Get("screenRecording").As<Napi::Object>().Set("required", Napi::Boolean::New(env, true));
  permissions.Get("screenRecording").As<Napi::Object>().Set("granted", env.Null());
  permissions.Get("screenRecording").As<Napi::Object>().Set("status", Napi::String::New(env, "required"));
  permissions.Get("inputMonitoring").As<Napi::Object>().Set("required", Napi::Boolean::New(env, true));
  permissions.Get("inputMonitoring").As<Napi::Object>().Set("granted", env.Null());
  permissions.Get("inputMonitoring").As<Napi::Object>().Set("status", Napi::String::New(env, "required"));
  permissions.Get("automation").As<Napi::Object>().Set("required", Napi::Boolean::New(env, true));
  permissions.Get("automation").As<Napi::Object>().Set("granted", env.Null());
  permissions.Get("automation").As<Napi::Object>().Set("status", Napi::String::New(env, "required"));
#endif

  result.Set("permissions", permissions);
  result.Set("activeWindow", active_window);
  result.Set("operator", operator_info);
  return result;
}

Napi::Object Init(Napi::Env env, Napi::Object exports) {
  exports.Set("version", Napi::String::New(env, "0.3.0"));
  exports.Set("getPlatformCapabilities", Napi::Function::New(env, Capabilities));
  exports.Set("getWindowMetrics", Napi::Function::New(env, WindowMetrics));
  exports.Set("getSystemIntegrationStatus", Napi::Function::New(env, SystemIntegrationStatus));
  exports.Set("getDesktopCapabilitySnapshot", Napi::Function::New(env, DesktopCapabilitySnapshot));
  return exports;
}

}  // namespace

NODE_API_MODULE(window_tools, Init)
