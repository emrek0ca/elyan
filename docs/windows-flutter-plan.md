# Windows Flutter Desktop Plan

## Architecture Overview
The Windows desktop application for Elyan will be built using Flutter. Similar to the macOS SwiftUI app, it will act as a presentation layer and process supervisor for the Python runtime. The core architecture remains identical:

`Flutter Windows App -> Dart RuntimeBridge -> Python Supervisor -> bridge.py -> IPC -> structured result -> UI`

## Components
1. **Dart RuntimeBridge**: Port of the Swift RuntimeBridge to Dart. It will spawn the Python process using `Process.start()` and communicate over standard IO (JSON lines).
2. **UI Layer**: A Flutter implementation of the Elyan design system ("Liquid Glass" equivalent for Windows, incorporating Fluent Design cues like Mica if possible).
3. **Platform Channels / FFI**: Any Windows-specific native capabilities (like active window tracking, global shortcuts, or system permissions) will be implemented via Flutter platform channels or Dart FFI calling Win32 APIs, replacing the old Node.js C++ addons.

## Integration Steps
1. Create a standard Flutter Windows app (`flutter create --platforms windows elyan_windows`).
2. Implement the `RuntimeIPCContract` in Dart (JSON serialization/deserialization).
3. Implement the `PythonRuntimeSupervisor` to handle the asynchronous launching of `bridge.py`, tracking its status, and handling restarts.
4. Integrate the Flutter app into the existing build pipeline.

## Limitations & Security
- Strict adherence to the capability safety policy. The Flutter app will not execute arbitrary shell commands directly; everything goes through the Python capability registry.
- Private directories and files will not be accessed without explicit user initiation and task boundaries.
