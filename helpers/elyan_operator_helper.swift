import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

let args = CommandLine.arguments
let mode = args.count > 1 ? args[1] : ""
let outputPath = args.count > 2 ? args[2] : ""
let payloadPath = args.count > 3 ? args[3] : ""
let abortFlagPath = ProcessInfo.processInfo.environment["ELYAN_OPERATOR_ABORT_FLAG_PATH"] ?? ""

func writeOutputFile(_ text: String) {
    guard !outputPath.isEmpty else { return }
    let url = URL(fileURLWithPath: outputPath)
    let directory = url.deletingLastPathComponent()
    try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    try? Data(text.utf8).write(to: url, options: .atomic)
}

func emit(_ payload: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: payload, options: []),
       let text = String(data: data, encoding: .utf8) {
        writeOutputFile(text)
        print(text)
    } else {
        let fallback = "{\"ok\":false,\"error\":\"json_encode_failed\"}"
        writeOutputFile(fallback)
        print(fallback)
    }
}

func stringValue(_ value: Any?) -> String {
    if let text = value as? String {
        return text
    }
    if let number = value as? NSNumber {
        return number.stringValue
    }
    return ""
}

func doubleValue(_ value: Any?) -> Double {
    if let number = value as? NSNumber {
        return number.doubleValue
    }
    if let number = value as? Double {
        return number
    }
    if let number = value as? Int {
        return Double(number)
    }
    if let text = value as? String, let number = Double(text) {
        return number
    }
    return 0
}

func boolValue(_ value: Any?) -> Bool {
    if let bool = value as? Bool {
        return bool
    }
    if let number = value as? NSNumber {
        return number.boolValue
    }
    if let text = value as? String {
        return ["1", "true", "yes", "on"].contains(text.lowercased())
    }
    return false
}

func nsString(_ value: CFTypeRef?) -> String {
    guard let value else { return "" }
    return value as? String ?? ""
}

func frontmostApp() -> NSRunningApplication? {
    NSWorkspace.shared.frontmostApplication
}

func loadPayload() -> [String: Any] {
    guard !payloadPath.isEmpty else { return [:] }
    let url = URL(fileURLWithPath: payloadPath)
    guard let data = try? Data(contentsOf: url),
          let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        return [:]
    }
    return payload
}

func abortRequested() -> Bool {
    guard !abortFlagPath.isEmpty else { return false }
    return FileManager.default.fileExists(atPath: abortFlagPath)
}

func screenBounds() -> CGRect {
    NSScreen.main?.frame ?? CGRect(x: 0, y: 0, width: 0, height: 0)
}

func failSafeTriggered() -> Bool {
    let location = NSEvent.mouseLocation
    let bounds = screenBounds()
    let threshold = 8.0
    let corners = [
        CGPoint(x: bounds.minX, y: bounds.minY),
        CGPoint(x: bounds.minX, y: bounds.maxY),
        CGPoint(x: bounds.maxX, y: bounds.minY),
        CGPoint(x: bounds.maxX, y: bounds.maxY),
    ]
    return corners.contains { corner in
        abs(location.x - corner.x) <= threshold && abs(location.y - corner.y) <= threshold
    }
}

func accessibilityGranted() -> Bool {
    AXIsProcessTrusted()
}

func requireAccessibility() -> Bool {
    if accessibilityGranted() {
        return true
    }
    emit([
        "ok": false,
        "error": "permission_denied",
        "detail": "macOS erişilebilirlik izni gerekiyor.",
    ])
    return false
}

func emitRect(_ rect: CGRect) -> [String: Any] {
    [
        "x": rect.origin.x,
        "y": rect.origin.y,
        "w": rect.width,
        "h": rect.height,
    ]
}

func roleType(_ role: String) -> String {
    let lowered = role.lowercased()
    if lowered.contains("button") {
        return "button"
    }
    if lowered.contains("textfield") || lowered.contains("text field") || lowered.contains("textarea") {
        return "input"
    }
    if lowered.contains("checkbox") || lowered.contains("check box") {
        return "checkbox"
    }
    if lowered.contains("menu") {
        return "menu"
    }
    if lowered.contains("image") {
        return "image"
    }
    if lowered.contains("icon") {
        return "icon"
    }
    if lowered.contains("statictext") || lowered.contains("static text") {
        return "text"
    }
    return "unknown"
}

func readAttribute(_ element: AXUIElement, _ attribute: CFString) -> CFTypeRef? {
    var value: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(element, attribute, &value)
    return result == .success ? value : nil
}

func readFrame(_ element: AXUIElement) -> CGRect? {
    guard let positionValue = readAttribute(element, kAXPositionAttribute as CFString),
          let sizeValue = readAttribute(element, kAXSizeAttribute as CFString) else {
        return nil
    }
    var point = CGPoint.zero
    var size = CGSize.zero
    guard AXValueGetType(positionValue as! AXValue) == .cgPoint,
          AXValueGetValue(positionValue as! AXValue, .cgPoint, &point),
          AXValueGetType(sizeValue as! AXValue) == .cgSize,
          AXValueGetValue(sizeValue as! AXValue, .cgSize, &size) else {
        return nil
    }
    return CGRect(origin: point, size: size)
}

func readChildren(_ element: AXUIElement) -> [AXUIElement] {
    guard let raw = readAttribute(element, kAXChildrenAttribute as CFString) else {
        return []
    }
    return (raw as? [AXUIElement]) ?? []
}

func textForElement(_ element: AXUIElement) -> String {
    let candidates: [CFString] = [
        kAXTitleAttribute as CFString,
        kAXDescriptionAttribute as CFString,
        kAXValueAttribute as CFString,
        kAXHelpAttribute as CFString,
        kAXPlaceholderValueAttribute as CFString,
    ]
    for candidate in candidates {
        let text = nsString(readAttribute(element, candidate)).trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty {
            return text
        }
    }
    return ""
}

func accessibilitySnapshot() {
    guard requireAccessibility() else { return }
    guard let app = frontmostApp() else {
        emit(["ok": false, "error": "no_frontmost_app", "detail": "Önde uygulama bulunamadı."])
        return
    }
    let root = AXUIElementCreateApplication(app.processIdentifier)
    let focusedWindow = readAttribute(root, kAXFocusedWindowAttribute as CFString) as? AXUIElement
    let target = focusedWindow ?? root

    var queue: [(AXUIElement, Int)] = [(target, 0)]
    var elements: [[String: Any]] = []
    var visited = 0
    while !queue.isEmpty && visited < 200 {
        let (node, depth) = queue.removeFirst()
        visited += 1
        let role = nsString(readAttribute(node, kAXRoleAttribute as CFString)).trimmingCharacters(in: .whitespacesAndNewlines)
        let text = textForElement(node)
        if let frame = readFrame(node), frame.width > 1, frame.height > 1 {
            elements.append([
                "id": "ax_\(visited)",
                "type": roleType(role),
                "role": role,
                "text": text,
                "bbox": emitRect(frame),
                "confidence": 0.99,
                "source": "accessibility",
                "depth": depth,
                "enabled": boolValue(readAttribute(node, kAXEnabledAttribute as CFString)),
                "focused": boolValue(readAttribute(node, kAXFocusedAttribute as CFString)),
            ])
        }
        if depth < 5 {
            for child in readChildren(node) {
                queue.append((child, depth + 1))
            }
        }
    }

    emit([
        "ok": true,
        "active_app": app.localizedName ?? "",
        "bundle_id": app.bundleIdentifier ?? "",
        "elements": elements,
    ])
}

func leftMousePoint(_ x: Double, _ y: Double) -> CGPoint {
    CGPoint(x: x, y: y)
}

func postMouseEvent(type: CGEventType, x: Double, y: Double, button: CGMouseButton = .left, clickState: Int64 = 1) {
    guard let event = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: leftMousePoint(x, y), mouseButton: button) else {
        return
    }
    event.setIntegerValueField(.mouseEventClickState, value: clickState)
    event.post(tap: .cghidEventTap)
}

func typeText(_ text: String) {
    for scalar in text.unicodeScalars {
        guard let keyDown = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true),
              let keyUp = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false) else {
            continue
        }
        var value = UInt16(scalar.value)
        keyDown.keyboardSetUnicodeString(stringLength: 1, unicodeString: &value)
        keyUp.keyboardSetUnicodeString(stringLength: 1, unicodeString: &value)
        keyDown.post(tap: .cghidEventTap)
        keyUp.post(tap: .cghidEventTap)
    }
}

let modifierMap: [String: CGEventFlags] = [
    "cmd": .maskCommand,
    "command": .maskCommand,
    "shift": .maskShift,
    "alt": .maskAlternate,
    "option": .maskAlternate,
    "ctrl": .maskControl,
    "control": .maskControl,
]

let keyCodeMap: [String: CGKeyCode] = [
    "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5, "h": 4,
    "i": 34, "j": 38, "k": 40, "l": 37, "m": 46, "n": 45, "o": 31, "p": 35,
    "q": 12, "r": 15, "s": 1, "t": 17, "u": 32, "v": 9, "w": 13, "x": 7,
    "y": 16, "z": 6,
    "enter": 36, "return": 36, "tab": 48, "space": 49, "escape": 53, "esc": 53,
    "up": 126, "down": 125, "left": 123, "right": 124,
]

func hotkey(_ keys: [String]) {
    let normalized = keys.map { $0.lowercased() }
    let modifiers = normalized.reduce(CGEventFlags()) { partial, key in
        partial.union(modifierMap[key] ?? [])
    }
    let primary = normalized.last(where: { keyCodeMap[$0] != nil }) ?? ""
    guard let keyCode = keyCodeMap[primary],
          let keyDown = CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: true),
          let keyUp = CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: false) else {
        return
    }
    keyDown.flags = modifiers
    keyUp.flags = modifiers
    keyDown.post(tap: .cghidEventTap)
    keyUp.post(tap: .cghidEventTap)
}

func focusWindow() {
    let payload = loadPayload()
    let appName = stringValue(payload["appName"]).trimmingCharacters(in: .whitespacesAndNewlines)
    let bundleId = stringValue(payload["bundleId"]).trimmingCharacters(in: .whitespacesAndNewlines)
    guard !appName.isEmpty || !bundleId.isEmpty else {
        emit(["ok": false, "error": "invalid_argument", "detail": "Odaklanacak uygulama belirtilmedi."])
        return
    }
    let apps = NSWorkspace.shared.runningApplications
    let target = apps.first { app in
        let matchesName = !appName.isEmpty && (app.localizedName ?? "").caseInsensitiveCompare(appName) == .orderedSame
        let matchesBundle = !bundleId.isEmpty && (app.bundleIdentifier ?? "").caseInsensitiveCompare(bundleId) == .orderedSame
        return matchesName || matchesBundle
    }
    guard let target else {
        emit(["ok": false, "error": "app_not_found", "detail": "Uygulama bulunamadı."])
        return
    }
    let activated = target.activate(options: [.activateIgnoringOtherApps])
    emit([
        "ok": activated,
        "app_name": target.localizedName ?? "",
        "bundle_id": target.bundleIdentifier ?? "",
        "process_id": Int(target.processIdentifier),
        "detail": activated ? "focused" : "focus_failed",
    ])
}

func inputAction() {
    guard requireAccessibility() else { return }
    if abortRequested() {
        emit(["ok": false, "error": "operator_abort_requested", "detail": "Visual operator durduruldu."])
        return
    }
    if failSafeTriggered() {
        emit(["ok": false, "error": "failsafe_corner_abort", "detail": "Fare köşede olduğu için operator durduruldu."])
        return
    }
    let payload = loadPayload()
    let action = stringValue(payload["actionType"]).lowercased()
    let duration = max(0.02, doubleValue(payload["duration"]))
    switch action {
    case "click":
        let x = doubleValue(payload["x"])
        let y = doubleValue(payload["y"])
        postMouseEvent(type: .leftMouseDown, x: x, y: y)
        postMouseEvent(type: .leftMouseUp, x: x, y: y)
    case "double_click":
        let x = doubleValue(payload["x"])
        let y = doubleValue(payload["y"])
        postMouseEvent(type: .leftMouseDown, x: x, y: y, clickState: 2)
        postMouseEvent(type: .leftMouseUp, x: x, y: y, clickState: 2)
        postMouseEvent(type: .leftMouseDown, x: x, y: y, clickState: 2)
        postMouseEvent(type: .leftMouseUp, x: x, y: y, clickState: 2)
    case "right_click":
        let x = doubleValue(payload["x"])
        let y = doubleValue(payload["y"])
        postMouseEvent(type: .rightMouseDown, x: x, y: y, button: .right)
        postMouseEvent(type: .rightMouseUp, x: x, y: y, button: .right)
    case "drag":
        let fromX = doubleValue(payload["fromX"])
        let fromY = doubleValue(payload["fromY"])
        let toX = doubleValue(payload["toX"])
        let toY = doubleValue(payload["toY"])
        postMouseEvent(type: .leftMouseDown, x: fromX, y: fromY)
        let steps = max(3, Int(duration * 20))
        for index in 1...steps {
            if abortRequested() {
                postMouseEvent(type: .leftMouseUp, x: fromX, y: fromY)
                emit(["ok": false, "error": "operator_abort_requested", "detail": "Visual operator durduruldu."])
                return
            }
            let progress = Double(index) / Double(steps)
            let x = fromX + (toX - fromX) * progress
            let y = fromY + (toY - fromY) * progress
            postMouseEvent(type: .leftMouseDragged, x: x, y: y)
            usleep(useconds_t((duration / Double(steps)) * 1_000_000))
        }
        postMouseEvent(type: .leftMouseUp, x: toX, y: toY)
    case "scroll":
        let delta = Int32(doubleValue(payload["delta"]))
        if let event = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1, wheel1: delta, wheel2: 0, wheel3: 0) {
            event.post(tap: .cghidEventTap)
        }
    case "type_text":
        let value = stringValue(payload["text"])
        for scalar in value.unicodeScalars {
            if abortRequested() {
                emit(["ok": false, "error": "operator_abort_requested", "detail": "Visual operator durduruldu."])
                return
            }
            typeText(String(scalar))
        }
    case "hotkey":
        if abortRequested() {
            emit(["ok": false, "error": "operator_abort_requested", "detail": "Visual operator durduruldu."])
            return
        }
        let keys = (payload["keys"] as? [String]) ?? []
        hotkey(keys)
    case "wait":
        let waitSteps = max(1, Int(duration * 10))
        for _ in 0..<waitSteps {
            if abortRequested() {
                emit(["ok": false, "error": "operator_abort_requested", "detail": "Visual operator durduruldu."])
                return
            }
            usleep(useconds_t((duration / Double(waitSteps)) * 1_000_000))
        }
    default:
        emit(["ok": false, "error": "unsupported_action", "detail": "Desteklenmeyen operator aksiyonu."])
        return
    }
    emit(["ok": true, "detail": "executed", "action_type": action])
}

switch mode {
case "accessibility_snapshot":
    accessibilitySnapshot()
case "focus_window":
    focusWindow()
case "input_action":
    inputAction()
default:
    emit(["ok": false, "error": "unsupported_mode", "detail": "Desteklenmeyen operator helper modu."])
}
