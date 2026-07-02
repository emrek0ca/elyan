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
///
/// Dayanıklılık: bağlantı yanıt ortasında koparsa (ağ geçişi, uyku, proxy)
/// istemci `Last-Event-ID` ile OTOMATİK yeniden bağlanır — backend replay
/// desteklediği için kaçan delta'lar kayıpsız geri gelir. Eskiden tek kopuş
/// tüm cevabı öldürüyor ve kullanıcı "Yanıt alınamadı." görüyordu.
struct ElyanSSEEvent {
    let id: String?
    let event: String
    let data: [String: Any]
}

actor ElyanSSEClient {
    private let urlSession: URLSession
    private var currentTask: Task<Void, Never>?

    private static let maxReconnectAttempts = 4
    private static let reconnectBaseDelayNs: UInt64 = 800_000_000 // 0.8s, üstel artar

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
            var lastEventId: String?
            var attempt = 0

            while !Task.isCancelled {
                do {
                    let sawEvent = try await Self.connectOnce(
                        session: session,
                        accessToken: accessToken,
                        taskId: taskId,
                        baseURL: baseURL,
                        lastEventId: lastEventId,
                        onEvent: { event in
                            if let id = event.id, !id.isEmpty { lastEventId = id }
                            await onEvent(event)
                        }
                    )
                    // Sunucu akışı normal kapattı (görev bitti ya da idle) —
                    // yeniden bağlanma, üst katman terminal olayı zaten aldı.
                    _ = sawEvent
                    break
                } catch {
                    if Task.isCancelled { break }
                    attempt += 1
                    if attempt > Self.maxReconnectAttempts {
                        await onError(error)
                        break
                    }
                    // Üstel geri çekilme: 0.8s, 1.6s, 3.2s, 6.4s
                    let delay = Self.reconnectBaseDelayNs << UInt64(min(attempt - 1, 4))
                    try? await Task.sleep(nanoseconds: delay)
                    continue
                }
            }
            await onClose()
        }
    }

    /// Tek bir bağlantı denemesi: açar, frame'leri akıtır, sunucu kapatınca
    /// döner. HTTP hata durumları ve ağ kopmaları throw eder (retry kararını
    /// çağıran döngü verir).
    private static func connectOnce(
        session: URLSession,
        accessToken: String,
        taskId: String,
        baseURL: URL,
        lastEventId: String?,
        onEvent: @escaping @Sendable (ElyanSSEEvent) async -> Void
    ) async throws -> Bool {
        var components = URLComponents(
            url: baseURL.appendingPathComponent("v1/realtime/stream"),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [URLQueryItem(name: "taskId", value: taskId)]
        guard let url = components.url else {
            throw ElyanBackendError.malformedResponse("Realtime stream URL oluşturulamadı.")
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        request.setValue("Elyan/1.0 (macOS)", forHTTPHeaderField: "User-Agent")
        if let lastEventId, !lastEventId.isEmpty {
            // Backend Last-Event-ID'den replay yapar; kopuşta kaçan olaylar
            // kayıpsız geri gelir.
            request.setValue(lastEventId, forHTTPHeaderField: "Last-Event-ID")
        }

        let (bytes, response) = try await session.bytes(for: request)
        if Task.isCancelled { return false }

        if let http = response as? HTTPURLResponse,
           !(200..<300).contains(http.statusCode) {
            throw ElyanBackendError.server(
                status: http.statusCode,
                message: "Realtime stream HTTP \(http.statusCode)"
            )
        }

        var sawEvent = false
        var pending = SSEFrame()
        for try await line in bytes.lines {
            if Task.isCancelled { break }
            if line.isEmpty {
                if let event = pending.flush() {
                    sawEvent = true
                    await onEvent(event)
                }
                continue
            }
            pending.consume(line: line)
        }
        return sawEvent
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
