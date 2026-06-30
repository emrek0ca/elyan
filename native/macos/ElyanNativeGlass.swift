import AppKit
import Foundation

@_cdecl("ElyanNativeGlassIsSupported")
public func ElyanNativeGlassIsSupported() -> Bool {
  if #available(macOS 11.0, *) {
    return true
  }
  return false
}

@_cdecl("ElyanNativeGlassMaterialLevel")
public func ElyanNativeGlassMaterialLevel() -> Int32 {
  if #available(macOS 14.0, *) {
    return 3
  }
  if #available(macOS 12.0, *) {
    return 2
  }
  if #available(macOS 11.0, *) {
    return 1
  }
  return 0
}

@_cdecl("ElyanNativeGlassDefaultCornerRadius")
public func ElyanNativeGlassDefaultCornerRadius() -> Double {
  if #available(macOS 14.0, *) {
    return 22.0
  }
  return 18.0
}

@_cdecl("ElyanNativeGlassBackdropSaturation")
public func ElyanNativeGlassBackdropSaturation() -> Double {
  if #available(macOS 14.0, *) {
    return 1.28
  }
  return 1.16
}

