import os
import sys

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)

mac_dir = os.path.join("apps", "macos", "ElyanMac")

# 1. ElyanMacApp.swift
app_swift = """import SwiftUI

@main
struct ElyanMacApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .onAppear {
                    appState.supervisor.start()
                }
        }
        .windowStyle(.hiddenTitleBar)
    }
}
"""
write_file(os.path.join(mac_dir, "ElyanMacApp.swift"), app_swift)

# 2. AppState.swift
app_state_swift = """import Foundation
import SwiftUI

@MainActor
class AppState: ObservableObject {
    @Published var supervisor = PythonRuntimeSupervisor()
    @Published var runtimeReady = false
}
"""
write_file(os.path.join(mac_dir, "AppState.swift"), app_state_swift)

# 3. RuntimeModels.swift
models_swift = """import Foundation

struct RuntimeRequest: Codable {
    let id: String
    let taskId: String
    let capability: String
    let payload: [String: AnyCodable]
}

struct RuntimeResponse: Codable {
    let id: String
    let taskId: String
    let ok: Bool
    let capability: String
    let result: [String: AnyCodable]?
    // Ignore events and artifacts for now to simplify scaffolding
    // let events: [RuntimeEvent]
    // let artifacts: [RuntimeArtifact]
}

struct AnyCodable: Codable {
    let value: Any
    
    init(_ value: Any) {
        self.value = value
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let intVal = try? container.decode(Int.self) { value = intVal }
        else if let doubleVal = try? container.decode(Double.self) { value = doubleVal }
        else if let boolVal = try? container.decode(Bool.self) { value = boolVal }
        else if let stringVal = try? container.decode(String.self) { value = stringVal }
        else { value = "Unknown" }
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        if let intVal = value as? Int { try container.encode(intVal) }
        else if let doubleVal = value as? Double { try container.encode(doubleVal) }
        else if let boolVal = value as? Bool { try container.encode(boolVal) }
        else if let stringVal = value as? String { try container.encode(stringVal) }
    }
}
"""
write_file(os.path.join(mac_dir, "RuntimeModels.swift"), models_swift)

# 4. RuntimeBridgeSwift.swift
bridge_swift = """import Foundation

class RuntimeBridgeSwift {
    private var process: Process?
    private var inputPipe: Pipe?
    private var outputPipe: Pipe?
    
    func startProcess() {
        let process = Process()
        let executable = "/usr/bin/env"
        let bridgePath = FileManager.default.currentDirectoryPath + "/../../../../runtime/bridge.py"
        
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = ["python3", bridgePath]
        
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        
        let inPipe = Pipe()
        let outPipe = Pipe()
        
        process.standardInput = inPipe
        process.standardOutput = outPipe
        
        self.inputPipe = inPipe
        self.outputPipe = outPipe
        self.process = process
        
        outPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { return }
            if let string = String(data: data, encoding: .utf8) {
                print("Runtime:", string)
            }
        }
        
        do {
            try process.run()
        } catch {
            print("Failed to start python runtime: \\(error)")
        }
    }
    
    func stopProcess() {
        process?.terminate()
    }
}
"""
write_file(os.path.join(mac_dir, "RuntimeBridgeSwift.swift"), bridge_swift)

# 5. PythonRuntimeSupervisor.swift
supervisor_swift = """import Foundation

class PythonRuntimeSupervisor: ObservableObject {
    private let bridge = RuntimeBridgeSwift()
    @Published var isRunning = false
    
    func start() {
        bridge.startProcess()
        DispatchQueue.main.async {
            self.isRunning = true
        }
    }
    
    func stop() {
        bridge.stopProcess()
        DispatchQueue.main.async {
            self.isRunning = false
        }
    }
}
"""
write_file(os.path.join(mac_dir, "PythonRuntimeSupervisor.swift"), supervisor_swift)

# 6. ContentView.swift
content_swift = """import SwiftUI

struct ContentView: View {
    @EnvironmentObject var appState: AppState
    
    var body: some View {
        VStack {
            Text("Elyan Mac Native")
                .font(.largeTitle)
                .padding()
            Text(appState.supervisor.isRunning ? "Runtime: Started" : "Runtime: Stopped")
        }
        .frame(minWidth: 400, minHeight: 300)
    }
}
"""
write_file(os.path.join(mac_dir, "ContentView.swift"), content_swift)

# 7. WindowTools.swift (Ported from C++)
window_tools_swift = """import AppKit
import Foundation

class WindowTools {
    static func getActiveWindowInfo() -> [String: Any] {
        guard let app = NSWorkspace.shared.frontmostApplication else {
            return ["available": false]
        }
        
        let pid = app.processIdentifier
        let appName = app.localizedName ?? ""
        let bundleId = app.bundleIdentifier ?? ""
        let executablePath = app.executableURL?.path ?? ""
        
        return [
            "available": true,
            "appName": appName,
            "bundleId": bundleId,
            "executablePath": executablePath,
            "processId": pid
        ]
    }
    
    static func checkAccessibility() -> Bool {
        return AXIsProcessTrusted()
    }
}
"""
write_file(os.path.join(mac_dir, "WindowTools.swift"), window_tools_swift)


# Ruby script to generate xcodeproj
ruby_script = """require 'xcodeproj'

project_path = 'apps/macos/ElyanMac/ElyanMac.xcodeproj'
project = Xcodeproj::Project.new(project_path)

app_target = project.new_target(:application, 'ElyanMac', :osx)

# Add source files
group = project.main_group.find_subpath(File.join('.'), true)
group.set_source_tree('SOURCE_ROOT')

Dir.glob('apps/macos/ElyanMac/*.swift').each do |file|
    file_ref = group.new_reference(File.basename(file))
    app_target.add_file_references([file_ref])
end

# Set settings
app_target.build_configurations.each do |config|
    config.build_settings['PRODUCT_BUNDLE_IDENTIFIER'] = 'com.elyan.mac'
    config.build_settings['INFOPLIST_KEY_NSPrincipalClass'] = 'NSApplication'
    config.build_settings['SWIFT_VERSION'] = '5.0'
    config.build_settings['MACOSX_DEPLOYMENT_TARGET'] = '14.0'
    config.build_settings['GENERATE_INFOPLIST_FILE'] = 'YES'
end

project.save
"""
write_file("scripts/generate_mac_proj.rb", ruby_script)

print("Scaffold python script completed.")
