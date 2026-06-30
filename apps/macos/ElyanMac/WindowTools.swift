import AppKit
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
