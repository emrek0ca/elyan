import AppKit
import Foundation

private enum LauncherError: LocalizedError {
    case damagedPackage
    case installationFailed(String)
    case terminalFailed

    var errorDescription: String? {
        switch self {
        case .damagedPackage:
            return "Kurulum paketi eksik veya bozuk. Elyan'i yeniden indirin."
        case let .installationFailed(message):
            return "Elyan kurulamadı: \(message)"
        case .terminalFailed:
            return "Kurulum penceresi acilamadi."
        }
    }
}

private func showError(_ error: Error) {
    let alert = NSAlert()
    alert.alertStyle = .critical
    alert.messageText = "Elyan acilamadi"
    alert.informativeText = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    alert.runModal()
}

private func installedApplicationURL() throws -> URL {
    let source = Bundle.main.bundleURL.standardizedFileURL
    guard source.path.hasPrefix("/Volumes/") else {
        return source
    }

    let fileManager = FileManager.default
    let applications = fileManager.homeDirectoryForCurrentUser.appendingPathComponent("Applications", isDirectory: true)
    let destination = applications.appendingPathComponent("Elyan.app", isDirectory: true)
    let temporary = applications.appendingPathComponent(".Elyan.app.installing", isDirectory: true)
    do {
        try fileManager.createDirectory(at: applications, withIntermediateDirectories: true)
        if fileManager.fileExists(atPath: temporary.path) {
            try fileManager.removeItem(at: temporary)
        }
        try fileManager.copyItem(at: source, to: temporary)
        if fileManager.fileExists(atPath: destination.path) {
            try fileManager.removeItem(at: destination)
        }
        try fileManager.moveItem(at: temporary, to: destination)
        return destination
    } catch {
        try? fileManager.removeItem(at: temporary)
        throw LauncherError.installationFailed(error.localizedDescription)
    }
}

private func portablePython(in payload: URL) -> URL? {
    let root = payload.appendingPathComponent("python", isDirectory: true)
    guard let enumerator = FileManager.default.enumerator(
        at: root,
        includingPropertiesForKeys: [.isRegularFileKey, .isExecutableKey],
        options: [.skipsHiddenFiles]
    ) else {
        return nil
    }
    for case let candidate as URL in enumerator {
        guard candidate.lastPathComponent == "python3" else { continue }
        let values = try? candidate.resourceValues(forKeys: [.isRegularFileKey, .isExecutableKey])
        if values?.isRegularFile == true && values?.isExecutable == true {
            return candidate
        }
    }
    return nil
}

private func openInstallerTerminal(application: URL) throws {
    let payload = application
        .appendingPathComponent("Contents", isDirectory: true)
        .appendingPathComponent("Resources", isDirectory: true)
        .appendingPathComponent("payload", isDirectory: true)
    let bootstrap = payload.appendingPathComponent("bootstrap.py")
    guard FileManager.default.fileExists(atPath: bootstrap.path), let python = portablePython(in: payload) else {
        throw LauncherError.damagedPackage
    }

    let script = """
    on run argv
      set launchCommand to quoted form of item 1 of argv & " " & quoted form of item 2 of argv & " --payload " & quoted form of item 3 of argv
      tell application "Terminal"
        activate
        do script launchCommand
      end tell
    end run
    """
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
    process.arguments = ["-e", script, python.path, bootstrap.path, payload.path]
    try process.run()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        throw LauncherError.terminalFailed
    }
}

do {
    let application = try installedApplicationURL()
    if application.standardizedFileURL != Bundle.main.bundleURL.standardizedFileURL {
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        let semaphore = DispatchSemaphore(value: 0)
        var openError: Error?
        NSWorkspace.shared.openApplication(at: application, configuration: configuration) { _, error in
            openError = error
            semaphore.signal()
        }
        semaphore.wait()
        if let openError {
            throw LauncherError.installationFailed(openError.localizedDescription)
        }
    } else {
        try openInstallerTerminal(application: application)
    }
} catch {
    showError(error)
    exit(1)
}
