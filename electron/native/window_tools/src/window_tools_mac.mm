#include "window_tools_platform.h"

#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>

namespace elyan::native {

namespace {

std::string NSStringToUtf8(NSString* value) {
  if (value == nil) {
    return "";
  }
  const char* utf8 = [value UTF8String];
  return utf8 == nullptr ? "" : std::string(utf8);
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
  if (pid > 0) {
    result.Set("processId", Napi::Number::New(env, pid));
  } else {
    result.Set("processId", env.Null());
  }
  return result;
}

}  // namespace elyan::native
