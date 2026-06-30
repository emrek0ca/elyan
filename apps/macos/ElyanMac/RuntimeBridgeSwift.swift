import Foundation

enum RuntimeBridgeSwiftError: Error, LocalizedError {
    case repoRootNotFound
    case bridgeScriptNotFound(URL)
    case runtimeNotStarted
    case processLaunchFailed(String)
    case writeFailed(String)
    case responseTimeout(String)
    case responseDecodeFailed(String)

    var errorDescription: String? {
        switch self {
        case .repoRootNotFound:
            return "Elyan repo kökü bulunamadı."
        case .bridgeScriptNotFound(let url):
            return "Python runtime bridge bulunamadı: \(url.path)"
        case .runtimeNotStarted:
            return "Python runtime henüz başlatılmadı."
        case .processLaunchFailed(let message):
            return "Python runtime başlatılamadı: \(message)"
        case .writeFailed(let message):
            return "Runtime ile bağlantı koptu: \(message)"
        case .responseTimeout(let id):
            return "Runtime yanıt zaman aşımı: \(id)"
        case .responseDecodeFailed(let line):
            return "Runtime yanıtı çözümlenemedi: \(line.prefix(120))"
        }
    }
}

final class RuntimeBridgeSwift: @unchecked Sendable {
    private var process: Process?
    private var inputPipe: Pipe?
    private var outputPipe: Pipe?
    private var errorPipe: Pipe?
    private var stdoutBuffer = Data()
    private let queue = DispatchQueue(label: "dev.elyan.mac.runtime-bridge")
    private var pending: [String: (Result<RuntimeResponse, Error>) -> Void] = [:]

    var onUnsolicitedResponse: ((RuntimeResponse) -> Void)?
    var onDiagnostic: ((String) -> Void)?
    var isRunning: Bool {
        process?.isRunning == true
    }

    func startProcess() throws {
        if process?.isRunning == true {
            return
        }

        let repoRoot = try resolveRepoRoot()
        let bridgeURL = repoRoot.appendingPathComponent("runtime/bridge.py")
        guard FileManager.default.fileExists(atPath: bridgeURL.path) else {
            throw RuntimeBridgeSwiftError.bridgeScriptNotFound(bridgeURL)
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", "-u", bridgeURL.path]
        process.currentDirectoryURL = repoRoot

        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["ELYAN_REPO_ROOT"] = repoRoot.path
        process.environment = env

        let inPipe = Pipe()
        let outPipe = Pipe()
        let errPipe = Pipe()

        process.standardInput = inPipe
        process.standardOutput = outPipe
        process.standardError = errPipe

        self.inputPipe = inPipe
        self.outputPipe = outPipe
        self.errorPipe = errPipe
        self.process = process

        outPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            self.queue.async {
                self.consumeStdout(data)
            }
        }

        errPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty, let string = String(data: data, encoding: .utf8) else { return }
            self.onDiagnostic?(string.trimmingCharacters(in: .whitespacesAndNewlines))
        }

        process.terminationHandler = { [weak self] terminated in
            self?.queue.async {
                let callbacks = self.map { Array($0.pending.values) } ?? []
                self?.pending.removeAll()
                for callback in callbacks {
                    callback(.failure(RuntimeBridgeSwiftError.processLaunchFailed("exit \(terminated.terminationStatus)")))
                }
            }
        }

        do {
            try process.run()
        } catch {
            throw RuntimeBridgeSwiftError.processLaunchFailed(error.localizedDescription)
        }
    }

    func stopProcess() {
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        errorPipe?.fileHandleForReading.readabilityHandler = nil
        inputPipe?.fileHandleForWriting.closeFile()
        process?.terminate()
        process = nil
        inputPipe = nil
        outputPipe = nil
        errorPipe = nil

        queue.async {
            let callbacks = Array(self.pending.values)
            self.pending.removeAll()
            for callback in callbacks {
                callback(.failure(RuntimeBridgeSwiftError.runtimeNotStarted))
            }
        }
    }

    func request(
        capability: String,
        payload: [String: Any] = [:],
        timeoutSeconds: TimeInterval = 30
    ) async throws -> RuntimeResponse {
        guard process?.isRunning == true, let inputPipe else {
            throw RuntimeBridgeSwiftError.runtimeNotStarted
        }

        let request = RuntimeRequest(
            capability: capability,
            payload: payload.mapValues { AnyCodable($0) }
        )
        let encoded = try JSONEncoder().encode(request)

        return try await withCheckedThrowingContinuation { continuation in
            queue.async {
                self.pending[request.id] = { result in
                    continuation.resume(with: result)
                }

                do {
                    try inputPipe.fileHandleForWriting.write(contentsOf: encoded + Data([0x0A]))
                } catch {
                    // Broken pipe (process died mid-write): fail this request instead of
                    // letting FileHandle's legacy write(_:) raise an uncatchable exception.
                    if let callback = self.pending.removeValue(forKey: request.id) {
                        callback(.failure(RuntimeBridgeSwiftError.writeFailed(error.localizedDescription)))
                    }
                    return
                }

                DispatchQueue.global().asyncAfter(deadline: .now() + timeoutSeconds) {
                    self.queue.async {
                        guard let callback = self.pending.removeValue(forKey: request.id) else { return }
                        callback(.failure(RuntimeBridgeSwiftError.responseTimeout(request.id)))
                    }
                }
            }
        }
    }

    private func consumeStdout(_ data: Data) {
        stdoutBuffer.append(data)

        while let newlineRange = stdoutBuffer.firstRange(of: Data([0x0A])) {
            let lineData = stdoutBuffer.subdata(in: 0..<newlineRange.lowerBound)
            stdoutBuffer.removeSubrange(0..<newlineRange.upperBound)
            guard !lineData.isEmpty, let line = String(data: lineData, encoding: .utf8) else {
                continue
            }
            do {
                let response = try JSONDecoder().decode(RuntimeResponse.self, from: lineData)
                if let callback = pending.removeValue(forKey: response.id) {
                    callback(.success(response))
                } else {
                    DispatchQueue.main.async {
                        self.onUnsolicitedResponse?(response)
                    }
                }
            } catch {
                onDiagnostic?(RuntimeBridgeSwiftError.responseDecodeFailed(line).localizedDescription)
            }
        }
    }

    private func resolveRepoRoot() throws -> URL {
        let manager = FileManager.default
        var candidates: [URL] = []

        if let override = ProcessInfo.processInfo.environment["ELYAN_REPO_ROOT"], !override.isEmpty {
            candidates.append(URL(fileURLWithPath: override))
        }

        candidates.append(URL(fileURLWithPath: manager.currentDirectoryPath))
        candidates.append(Bundle.main.bundleURL)
        candidates.append(URL(fileURLWithPath: #filePath))

        for candidate in candidates {
            var current = candidate.hasDirectoryPath ? candidate : candidate.deletingLastPathComponent()
            for _ in 0..<8 {
                let bridge = current.appendingPathComponent("runtime/bridge.py")
                if manager.fileExists(atPath: bridge.path) {
                    return current
                }
                let parent = current.deletingLastPathComponent()
                if parent.path == current.path {
                    break
                }
                current = parent
            }
        }

        throw RuntimeBridgeSwiftError.repoRootNotFound
    }
}

private extension Data {
    static func + (lhs: Data, rhs: Data) -> Data {
        var copy = lhs
        copy.append(rhs)
        return copy
    }
}
