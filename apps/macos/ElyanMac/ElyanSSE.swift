import Foundation

/// Lightweight Server-Sent Events client for /v1/realtime/stream.
///
/// Backend frames look like:
///   id: <event-id>
///   event: chat.message.delta
///   data: {"sessionId":"...", "assistant": {...}}
///
/// Mobile normalizes some legacy aliases (`message.delta` -> `chat.message.delta`,
/// etc.) — we do the same so the chat layer only deals with one set of names.
struct ElyanSSEEvent {
    let id: String?
    let event: String
    let data: [String: Any]
}

actor ElyanSSEClient {
    private let urlSession: URLSession
    private var currentTask: Task<Void, Never>?

    init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = 0
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.waitsForConnectivity = true
        // SSE is a long-lived stream; turn off pipelining/keep-alive surprises.
        config.httpAdditionalHeaders = ["Accept": "text/event-stream"]
        self.urlSession = URLSession(configuration: config)
    }

    /// Opens an SSE stream to /v1/realtime/stream?taskId=... and yields parsed
    /// events. Mirrors mobile-elyan's RealtimeRepository.connect(...).
    func open(
        accessToken: String,
        taskId: String,
        baseURL: URL = ElyanBackend.baseURL,
        onEvent: @escaping @Sendable (ElyanSSEEvent) async -> Void,
        onError: @escaping @Sendable (Error) async -> Void,
        onClose: @escaping @Sendable () async -> Void
    ) {
        cancel()
        let session = urlSession

        currentTask = Task.detached(priority: .utility) {
            var components = URLComponents(
                url: baseURL.appendingPathComponent("v1/realtime/stream"),
                resolvingAgainstBaseURL: false
            )!
            components.queryItems = [URLQueryItem(name: "taskId", value: taskId)]
            guard let url = components.url else { return }

            var request = URLRequest(url: url)
            request.httpMethod = "GET"
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
            request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
            request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
            request.setValue("Elyan/1.0 (macOS)", forHTTPHeaderField: "User-Agent")

            do {
                let (bytes, response) = try await session.bytes(for: request)
                if Task.isCancelled { await onClose(); return }

                if let http = response as? HTTPURLResponse,
                   !(200..<300).contains(http.statusCode) {
                    await onError(ElyanBackendError.server(
                        status: http.statusCode,
                        message: "Realtime stream HTTP \(http.statusCode)"
                    ))
                    await onClose()
                    return
                }

                var pending = SSEFrame()
                for try await line in bytes.lines {
                    if Task.isCancelled { break }
                    if line.isEmpty {
                        if let event = pending.flush() {
                            await onEvent(event)
                        }
                        continue
                    }
                    pending.consume(line: line)
                }
                await onClose()
            } catch {
                if Task.isCancelled { await onClose(); return }
                await onError(error)
                await onClose()
            }
        }
    }

    func cancel() {
        currentTask?.cancel()
        currentTask = nil
    }
}

/// Accumulates the id:/event:/data: lines until a blank line ends the frame.
private struct SSEFrame {
    private var id: String?
    private var event: String?
    private var dataLines: [String] = []

    mutating func consume(line: String) {
        // SSE comments start with ":" — ignore.
        if line.hasPrefix(":") { return }
        if let separator = line.firstIndex(of: ":") {
            let field = String(line[..<separator])
            var value = String(line[line.index(after: separator)...])
            if value.hasPrefix(" ") { value.removeFirst() }
            switch field {
            case "id": id = value
            case "event": event = value
            case "data": dataLines.append(value)
            default: break
            }
        } else {
            // A bare field name with no value (rare).
            switch line {
            case "id": id = ""
            case "event": event = ""
            case "data": dataLines.append("")
            default: break
            }
        }
    }

    mutating func flush() -> ElyanSSEEvent? {
        defer { id = nil; event = nil; dataLines.removeAll() }
        guard !dataLines.isEmpty else { return nil }

        let rawEvent = (event ?? "message").trimmingCharacters(in: .whitespaces)
        let normalizedEvent = Self.normalize(eventName: rawEvent)
        let joined = dataLines.joined(separator: "\n")
        let payload: [String: Any] = {
            guard let data = joined.data(using: .utf8),
                  let any = try? JSONSerialization.jsonObject(with: data, options: []),
                  let dict = any as? [String: Any] else {
                return ["raw": joined]
            }
            return dict
        }()
        return ElyanSSEEvent(id: id, event: normalizedEvent, data: payload)
    }

    /// Same aliasing the mobile client applies in `_normalizeChatRealtimeEventName`.
    private static func normalize(eventName: String) -> String {
        let lower = eventName.lowercased()
        if lower.hasPrefix("chat.message.") { return lower }
        switch lower {
        case "message.created": return "chat.message.created"
        case "message.delta": return "chat.message.delta"
        case "message.completed", "message.error": return "chat.message.updated"
        case "heartbeat": return "chat.heartbeat"
        default: return lower
        }
    }
}
