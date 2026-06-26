#include "window_tools_platform.h"

#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#import <Carbon/Carbon.h>

namespace elyan::native {

namespace {

std::string NSStringToUtf8(NSString* value) {
  if (value == nil) {
    return "";
  }
  const char* utf8 = [value UTF8String];
  return utf8 == nullptr ? "" : std::string(utf8);
}

std::string IsoTimestampNow() {
  NSISO8601DateFormatter* formatter = [[NSISO8601DateFormatter alloc] init];
  formatter.formatOptions = NSISO8601DateFormatWithInternetDateTime;
  return NSStringToUtf8([formatter stringFromDate:[NSDate date]]);
}

std::string ExecutablePathForApp(NSRunningApplication* app) {
  if (app == nil) {
    return "";
  }
  NSURL* executable_url = [app executableURL];
  if (executable_url == nil) {
    return "";
  }
  return NSStringToUtf8([executable_url path]);
}

std::string BundleIdentifierForApp(NSRunningApplication* app) {
  if (app == nil) {
    return "";
  }
  return NSStringToUtf8([app bundleIdentifier]);
}

std::string WindowTitleForPid(pid_t pid) {
  CFArrayRef window_list = CGWindowListCopyWindowInfo(
      kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
      kCGNullWindowID);
  if (window_list == nullptr) {
    return "";
  }

  NSArray* windows = CFBridgingRelease(window_list);
  for (NSDictionary* window in windows) {
    NSNumber* owner_pid = window[(id)kCGWindowOwnerPID];
    NSNumber* layer = window[(id)kCGWindowLayer];
    if (owner_pid == nil || [owner_pid intValue] != pid) {
      continue;
    }
    if (layer != nil && [layer intValue] != 0) {
      continue;
    }
    NSString* title = window[(id)kCGWindowName];
    if (title != nil && [title length] > 0) {
      return NSStringToUtf8(title);
    }
  }
  return "";
}

Napi::Object PermissionState(
    Napi::Env env,
    bool required,
    bool has_granted,
    bool granted,
    const char* status,
    const char* source,
    bool settings_deep_link_available) {
  Napi::Object result = Napi::Object::New(env);
  result.Set("required", Napi::Boolean::New(env, required));
  if (has_granted) {
    result.Set("granted", Napi::Boolean::New(env, granted));
  } else {
    result.Set("granted", env.Null());
  }
  result.Set("status", Napi::String::New(env, status));
  result.Set("source", Napi::String::New(env, source));
  result.Set("settingsDeepLinkAvailable", Napi::Boolean::New(env, settings_deep_link_available));
  result.Set("lastCheckedAt", Napi::String::New(env, IsoTimestampNow()));
  return result;
}

bool AccessibilityGranted() {
  return AXIsProcessTrusted();
}

Napi::Object AccessibilityPermissionState(Napi::Env env) {
  const bool granted = AccessibilityGranted();
  return PermissionState(
      env,
      true,
      true,
      granted,
      granted ? "granted" : "denied",
      "ax_api",
      true);
}

Napi::Object ScreenRecordingPermissionState(Napi::Env env) {
  bool probe_available = false;
  bool granted = false;
  if (@available(macOS 11.0, *)) {
    probe_available = true;
    granted = CGPreflightScreenCaptureAccess();
  }
  if (probe_available) {
    return PermissionState(
        env,
        true,
        true,
        granted,
        granted ? "granted" : "denied",
        "cg_preflight",
        true);
  }
  return PermissionState(env, true, false, false, "unknown", "cg_preflight_unavailable", true);
}

Napi::Object InputMonitoringPermissionState(Napi::Env env) {
  return PermissionState(
      env,
      true,
      false,
      false,
      "unknown",
      "unknown_unavailable_probe",
      true);
}

Napi::Object AutomationPermissionState(Napi::Env env) {
  NSAppleEventDescriptor* target = [NSAppleEventDescriptor descriptorWithBundleIdentifier:@"com.apple.systemevents"];
  if (target == nil || [target aeDesc] == nullptr) {
    return PermissionState(
        env,
        true,
        false,
        false,
        "unknown",
        "ae_target_unavailable",
        true);
  }

  const OSStatus probe_status =
      AEDeterminePermissionToAutomateTarget([target aeDesc], typeWildCard, typeWildCard, false);
  if (probe_status == noErr) {
    return PermissionState(
        env,
        true,
        true,
        true,
        "granted",
        "ae_determine_permission",
        true);
  }
  if (probe_status == errAEEventWouldRequireUserConsent || probe_status == errAEPrivilegeError) {
    return PermissionState(
        env,
        true,
        true,
        false,
        "denied",
        "ae_determine_permission",
        true);
  }
  return PermissionState(
      env,
      true,
      false,
      false,
      "unknown",
      "ae_probe_unavailable",
      true);
}

}  // namespace

bool ActiveWindowCapabilityAvailable() { return true; }

Napi::Object BuildActiveWindowInfo(Napi::Env env) {
  Napi::Object result = Napi::Object::New(env);
  NSRunningApplication* app = [[NSWorkspace sharedWorkspace] frontmostApplication];
  if (app == nil) {
    result.Set("available", Napi::Boolean::New(env, false));
    result.Set("appName", Napi::String::New(env, ""));
    result.Set("windowTitle", Napi::String::New(env, ""));
    result.Set("processId", env.Null());
    result.Set("source", Napi::String::New(env, "nsworkspace_frontmost"));
    result.Set("confidence", Napi::Number::New(env, 0.0));
    return result;
  }

  const pid_t pid = [app processIdentifier];
  const std::string app_name = NSStringToUtf8([app localizedName]);
  const std::string window_title = WindowTitleForPid(pid);
  const std::string executable_path = ExecutablePathForApp(app);
  const std::string bundle_id = BundleIdentifierForApp(app);
  const bool available = !app_name.empty() || pid > 0;

  result.Set("available", Napi::Boolean::New(env, available));
  result.Set("appName", Napi::String::New(env, app_name));
  result.Set("windowTitle", Napi::String::New(env, window_title));
  result.Set("executablePath", Napi::String::New(env, executable_path));
  result.Set("bundleId", Napi::String::New(env, bundle_id));
  result.Set(
      "source",
      Napi::String::New(
          env,
          window_title.empty() ? "nsworkspace_frontmost" : "cg_window_list+nsworkspace_frontmost"));
  result.Set("confidence", Napi::Number::New(env, window_title.empty() ? 0.92 : 0.98));
  if (pid > 0) {
    result.Set("processId", Napi::Number::New(env, pid));
  } else {
    result.Set("processId", env.Null());
  }
  return result;
}

Napi::Object BuildPermissionInfo(Napi::Env env) {
  Napi::Object permissions = Napi::Object::New(env);
  permissions.Set("accessibility", AccessibilityPermissionState(env));
  permissions.Set("screenRecording", ScreenRecordingPermissionState(env));
  permissions.Set("inputMonitoring", InputMonitoringPermissionState(env));
  permissions.Set("automation", AutomationPermissionState(env));
  return permissions;
}

Napi::Object BuildOperatorInfo(Napi::Env env) {
  Napi::Object result = Napi::Object::New(env);
  const bool accessibility_ready = AccessibilityGranted();
  const Napi::Object screen_recording = ScreenRecordingPermissionState(env);
  const Napi::Object automation = AutomationPermissionState(env);
  const bool screen_ready =
      std::string(screen_recording.Get("status").As<Napi::String>().Utf8Value()) == "granted";
  const std::string automation_status = automation.Get("status").As<Napi::String>().Utf8Value();
  const bool input_ready = accessibility_ready && (automation_status == "granted" || automation_status == "unknown");

  result.Set("available", Napi::Boolean::New(env, true));
  result.Set("mode", Napi::String::New(env, "macos_first"));
  result.Set("screenObservationReady", Napi::Boolean::New(env, screen_ready));
  result.Set("accessibilityReady", Napi::Boolean::New(env, accessibility_ready));
  result.Set("inputControlReady", Napi::Boolean::New(env, input_ready));
  result.Set("emergencyStopAvailable", Napi::Boolean::New(env, false));
  result.Set("failSafeCornerAbort", Napi::Boolean::New(env, true));
  result.Set("browserFirstReady", Napi::Boolean::New(env, false));
  result.Set("activeRunSummary", Napi::Object::New(env));
  result.Set("lastErrorCode", Napi::String::New(env, ""));
  return result;
}

}  // namespace elyan::native
