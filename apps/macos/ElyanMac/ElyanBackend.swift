import Foundation
import Security

/// Direct HTTP client for the Elyan backend at api.elyan.dev.
///
/// Mirrors mobile-elyan's `AppApiClient` + `AuthRepository` + `TaskRepository`
/// exactly: same base URL, same endpoints, same payload shapes (e.g. the
/// `blocks`/`metadata`/`source: "mobile"` body for /v1/chat/messages). This
/// is the only path the macOS app talks to the server through — the Python
/// bridge is not in the loop for auth or chat.
@MainActor
final class ElyanBackend: ObservableObject {

    // MARK: - Configuration

    /// The single backend the macOS app talks to — same host the mobile app
    /// uses (lib/core/config/app_config.dart _releaseApiBaseUri). Kept
    /// nonisolated so the SSE actor can reference it without a hop.
    nonisolated static let baseURL = URL(string: "https://api.elyan.dev")!

    private static let keychainService = "dev.elyan.mac.session"
    private static let keychainAccount = "session.v1"

    // MARK: - Published state

    @Published private(set) var session: ElyanAuthSession?
    var isSignedIn: Bool { session != nil }
    var onSessionChanged: ((ElyanAuthSession?) -> Void)?

    // MARK: - Lifecycle

    private let urlSession: URLSession
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    init() {
        let config = URLSessionConfiguration.default
        config.waitsForConnectivity = true
        config.timeoutIntervalForRequest = 30
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        self.urlSession = URLSession(configuration: config)
        self.session = Self.loadSessionFromKeychain()
    }

    // MARK: - Auth

    /// POST /v1/auth/login — identical body to mobile.
    @discardableResult
    func login(email: String, password: String) async throws -> ElyanAuthSession {
        let body: [String: Any] = [
            "email": email.trimmingCharacters(in: .whitespacesAndNewlines),
            "password": password
        ]
        let raw = try await postJSON(path: "/v1/auth/login", body: body, requireAuth: false)
        let parsed = try Self.parseAuthSession(raw)
        try persistSession(parsed)
        return parsed
    }

    /// POST /v1/auth/register — identical body to mobile.
    @discardableResult
    func register(
        displayName: String,
        email: String,
        password: String,
        termsAccepted: Bool,
        privacyAccepted: Bool
    ) async throws -> ElyanAuthSession {
        let body: [String: Any] = [
            "displayName": displayName.trimmingCharacters(in: .whitespacesAndNewlines),
            "email": email.trimmingCharacters(in: .whitespacesAndNewlines),
            "password": password,
            "legalAcceptance": [
                "termsAccepted": termsAccepted,
                "privacyAccepted": privacyAccepted
            ]
        ]
        let raw = try await postJSON(path: "/v1/auth/register", body: body, requireAuth: false)
        let parsed = try Self.parseAuthSession(raw)
        try persistSession(parsed)
        return parsed
    }

    /// POST /v1/auth/oauth/{provider}
    @discardableResult
    func loginWithOAuth(
        provider: String,
        idToken: String,
        email: String? = nil,
        displayName: String? = nil,
        authorizationCode: String? = nil,
        termsAccepted: Bool = false,
        privacyAccepted: Bool = false
    ) async throws -> ElyanAuthSession {
        var body: [String: Any] = [
            "idToken": idToken
        ]
        if let email, !email.isEmpty { body["email"] = email }
        if let displayName, !displayName.isEmpty { body["displayName"] = displayName }
        if let authorizationCode, !authorizationCode.isEmpty { body["authorizationCode"] = authorizationCode }
        if termsAccepted || privacyAccepted {
            body["legalAcceptance"] = [
                "termsAccepted": termsAccepted,
                "privacyAccepted": privacyAccepted
            ]
        }
        
        let raw = try await postJSON(path: "/v1/auth/oauth/\(provider)", body: body, requireAuth: false)
        let parsed = try Self.parseAuthSession(raw)
        try persistSession(parsed)
        return parsed
    }

    /// POST /v1/auth/refresh
    @discardableResult
    func refresh() async throws -> ElyanAuthSession {
        guard let current = session, !current.refreshToken.isEmpty else {
            throw ElyanBackendError.notAuthenticated
        }
        let raw = try await postJSON(
            path: "/v1/auth/refresh",
            body: ["refreshToken": current.refreshToken],
            requireAuth: false
        )
        let parsed = try Self.parseAuthSession(raw, refreshTokenFallback: current.refreshToken)
        try persistSession(parsed)
        return parsed
    }

    /// POST /v1/auth/logout (best-effort) then clear local session.
    func logout() async {
        if session?.accessToken.isEmpty == false {
            _ = try? await postJSON(path: "/v1/auth/logout", body: [:], requireAuth: true)
        }
        try? clearSession()
    }

    // MARK: - Sessions / History

    /// GET /v1/chat/sessions — list of conversation sessions, newest first.
    func getSessions(limit: Int = 40, cursor: String? = nil) async throws -> [ElyanSession] {
        var queryItems = ["limit=\(max(1, min(limit, 20)))"]
        if let cursor, !cursor.isEmpty {
            queryItems.append("cursor=\(cursor.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? cursor)")
        }
        let raw = try await internalGetJSON(path: "/v1/chat/sessions?\(queryItems.joined(separator: "&"))", requireAuth: true)
        return Self.parseSessions(raw)
    }

    /// GET /v1/chat/sessions/{id}/messages
    func getSessionMessages(sessionId: String) async throws -> [ElyanSessionMessage] {
        let raw = try await internalGetJSON(path: "/v1/chat/sessions/\(sessionId)/messages", requireAuth: true)
        return Self.parseSessionMessages(raw)
    }

    /// DELETE /v1/chat/sessions/{id}
    func deleteSession(sessionId: String) async throws {
        _ = try await deleteJSON(path: "/v1/chat/sessions/\(sessionId)", requireAuth: true)
    }

    // MARK: - Profile

    /// PATCH /v1/auth/me — update displayName
    @discardableResult
    func updateProfile(displayName: String) async throws -> ElyanAuthSession {
        guard let current = session else { throw ElyanBackendError.notAuthenticated }
        let raw = try await patchJSON(
            path: "/v1/auth/me",
            body: ["displayName": displayName.trimmingCharacters(in: .whitespacesAndNewlines)],
            requireAuth: true
        )
        let payload = Self.unwrap(raw)
        let user = (payload["user"] as? [String: Any]) ?? payload
        var updated = current
        if let name = user["displayName"] as? String { updated.displayName = name }
        if let email = user["email"] as? String { updated.email = email }
        try persistSession(updated)
        return updated
    }

    // MARK: - Devices

    /// GET /v1/devices — list of paired desktop devices.
    func getDevices() async throws -> [ElyanDevice] {
        let raw = try await internalGetJSON(path: "/v1/devices", requireAuth: true)
        return Self.parseDevices(raw)
    }

    /// DELETE /v1/devices/{id} — unpair a device.
    func removeDevice(deviceId: String) async throws {
        _ = try await deleteJSON(path: "/v1/devices/\(deviceId)", requireAuth: true)
    }

    // MARK: - Chat

    /// POST /v1/chat/messages with the exact body shape the desktop chat router expects.
    /// Returns the `task` object that carries the id we must use to subscribe
    /// to /v1/realtime/stream?taskId=...
    func sendChatMessage(
        prompt: String,
        sessionId: String? = nil,
        source: String = "desktop"
    ) async throws -> ChatDispatch {
        guard let current = session else { throw ElyanBackendError.notAuthenticated }

        let userBlock: [String: Any] = [
            "type": "text",
            "markdown": prompt,
            "visibility": "user_visible"
        ]
        var body: [String: Any] = [
            "content": prompt,
            "blocks": [userBlock],
            "source": source,
            "requestedCapabilities": [],
            "metadata": [
                "source": source,
                "desktopTransport": [
                    "rawPrivateDataUploaded": false,
                    "derivedContextOnly": true,
                    "scope": "user_chat_session"
                ],
                "renderContract": [
                    "version": "elyan_blocks.v2",
                    "mode": "block_first",
                    "canonicalSurface": "blocks",
                    "legacyContent": "content"
                ],
                "userBlocks": [userBlock]
            ]
        ]
        if let sessionId, !sessionId.isEmpty {
            body["sessionId"] = sessionId
        }

        _ = current // silence unused; the auth header is built inside performRequest.
        let extraHeaders = ["Idempotency-Key": UUID().uuidString]
        let raw = try await postJSON(
            path: "/v1/chat/messages",
            body: body,
            requireAuth: true,
            extraHeaders: extraHeaders
        )
        return try ChatDispatch.parse(raw)
    }

    // MARK: - Request plumbing

    func postJSON(
        path: String,
        body: [String: Any],
        requireAuth: Bool,
        extraHeaders: [String: String] = [:]
    ) async throws -> Any {
        var attemptedRefresh = false
        while true {
            let raw = try await performRequest(
                method: "POST",
                path: path,
                bodyJSON: body,
                requireAuth: requireAuth,
                extraHeaders: extraHeaders
            )
            switch raw {
            case .success(let value):
                return value
            case .unauthorized:
                guard requireAuth, !attemptedRefresh else { throw ElyanBackendError.notAuthenticated }
                attemptedRefresh = true
                _ = try await refresh()
                continue
            }
        }
    }

    func internalGetJSON(path: String, requireAuth: Bool) async throws -> Any {
        var attemptedRefresh = false
        while true {
            let raw = try await performRequest(method: "GET", path: path, bodyJSON: nil, requireAuth: requireAuth, extraHeaders: [:])
            switch raw {
            case .success(let value): return value
            case .unauthorized:
                guard requireAuth, !attemptedRefresh else { throw ElyanBackendError.notAuthenticated }
                attemptedRefresh = true
                _ = try await refresh()
                continue
            }
        }
    }

    func patchJSON(path: String, body: [String: Any], requireAuth: Bool) async throws -> Any {
        var attemptedRefresh = false
        while true {
            let raw = try await performRequest(method: "PATCH", path: path, bodyJSON: body, requireAuth: requireAuth, extraHeaders: [:])
            switch raw {
            case .success(let value): return value
            case .unauthorized:
                guard requireAuth, !attemptedRefresh else { throw ElyanBackendError.notAuthenticated }
                attemptedRefresh = true
                _ = try await refresh()
                continue
            }
        }
    }

    func putJSON(path: String, body: [String: Any], requireAuth: Bool) async throws -> Any {
        var attemptedRefresh = false
        while true {
            let raw = try await performRequest(method: "PUT", path: path, bodyJSON: body, requireAuth: requireAuth, extraHeaders: [:])
            switch raw {
            case .success(let value): return value
            case .unauthorized:
                guard requireAuth, !attemptedRefresh else { throw ElyanBackendError.notAuthenticated }
                attemptedRefresh = true
                _ = try await refresh()
                continue
            }
        }
    }

    @discardableResult
    func deleteJSON(path: String, requireAuth: Bool) async throws -> Any {
        var attemptedRefresh = false
        while true {
            let raw = try await performRequest(method: "DELETE", path: path, bodyJSON: nil, requireAuth: requireAuth, extraHeaders: [:])
            switch raw {
            case .success(let value): return value
            case .unauthorized:
                guard requireAuth, !attemptedRefresh else { throw ElyanBackendError.notAuthenticated }
                attemptedRefresh = true
                _ = try await refresh()
                continue
            }
        }
    }

    /// GET /v1/auth/me to confirm the session is alive.
    @discardableResult
    func getCurrentUser() async throws -> ElyanAuthSession {
        guard let current = session else { throw ElyanBackendError.notAuthenticated }
        var attemptedRefresh = false
        while true {
            let raw = try await performRequest(
                method: "GET",
                path: "/v1/auth/me",
                bodyJSON: nil,
                requireAuth: true,
                extraHeaders: [:]
            )
            switch raw {
            case .success(let value):
                var updated = session ?? current
                if let payload = value as? [String: Any] {
                    let userMap = (payload["user"] as? [String: Any]) ?? payload
                    if let name = userMap["displayName"] as? String { updated.displayName = name }
                    if let mail = userMap["email"] as? String { updated.email = mail }
                    if let id = userMap["id"] as? String { updated.id = id }
                }
                try persistSession(updated)
                return updated
            case .unauthorized:
                guard !attemptedRefresh else { throw ElyanBackendError.notAuthenticated }
                attemptedRefresh = true
                _ = try await refresh()
                continue
            }
        }
    }

    private enum HTTPOutcome {
        case success(Any)
        case unauthorized
    }

    private func performRequest(
        method: String,
        path: String,
        bodyJSON: [String: Any]?,
        requireAuth: Bool,
        extraHeaders: [String: String]
    ) async throws -> HTTPOutcome {
        var request = makeRequest(path: path, method: method)
        if requireAuth {
            guard let token = session?.accessToken, !token.isEmpty else {
                throw ElyanBackendError.notAuthenticated
            }
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let bodyJSON {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: bodyJSON, options: [])
        }
        for (key, value) in extraHeaders {
            request.setValue(value, forHTTPHeaderField: key)
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await urlSession.data(for: request)
        } catch {
            throw ElyanBackendError.transport(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw ElyanBackendError.transport("Non-HTTP response.")
        }
        let status = http.statusCode

        if status == 401, requireAuth {
            return .unauthorized
        }

        let decoded: Any? = data.isEmpty ? nil : (try? JSONSerialization.jsonObject(with: data, options: []))
        guard (200..<300).contains(status) else {
            let message = Self.extractErrorMessage(decoded) ?? "HTTP \(status)"
            throw ElyanBackendError.server(status: status, message: message)
        }
        return .success(decoded ?? [:])
    }

    private func makeRequest(path: String, method: String) -> URLRequest {
        let url = Self.baseURL.appendingPathComponent(path.hasPrefix("/") ? String(path.dropFirst()) : path)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Elyan/1.0 (macOS)", forHTTPHeaderField: "User-Agent")
        return request
    }

    private static func extractErrorMessage(_ decoded: Any?) -> String? {
        guard let dict = decoded as? [String: Any] else { return nil }
        if let nested = dict["error"] as? [String: Any], let msg = nested["message"] as? String { return msg }
        if let msg = dict["error"] as? String { return msg }
        if let msg = dict["message"] as? String { return msg }
        return nil
    }

    // MARK: - Session parsing (mirrors mobile _parseAuthSession)

    private static func parseAuthSession(_ raw: Any, refreshTokenFallback: String = "") throws -> ElyanAuthSession {
        // The backend may wrap the payload as { data: {...} } — unwrap that the
        // same way the mobile `unwrapData` helper does.
        let unwrapped = unwrap(raw)

        let tokens = (unwrapped["tokens"] as? [String: Any])
            ?? (unwrapped["token"] as? [String: Any])
            ?? [:]
        let tokenSource = tokens.isEmpty ? unwrapped : tokens

        let accessToken = (tokenSource["accessToken"] as? String)
            ?? (tokenSource["access_token"] as? String)
            ?? ""
        let refreshToken = (tokenSource["refreshToken"] as? String)
            ?? (tokenSource["refresh_token"] as? String)
            ?? refreshTokenFallback

        guard !accessToken.isEmpty else {
            throw ElyanBackendError.malformedResponse("Auth response did not include an access token.")
        }

        let user = (unwrapped["user"] as? [String: Any]) ?? unwrapped
        return ElyanAuthSession(
            id: (user["id"] as? String) ?? (user["userId"] as? String) ?? "elyan-user",
            displayName: (user["displayName"] as? String) ?? (user["name"] as? String) ?? "",
            email: (user["email"] as? String) ?? "",
            accessToken: accessToken,
            refreshToken: refreshToken
        )
    }

    // MARK: - Keychain-backed session storage

    private func persistSession(_ updated: ElyanAuthSession) throws {
        session = updated
        let data = try encoder.encode(updated)
        Self.writeKeychain(data: data)
        onSessionChanged?(updated)
    }

    private func clearSession() throws {
        session = nil
        Self.deleteKeychain()
        onSessionChanged?(nil)
    }

    private static func loadSessionFromKeychain() -> ElyanAuthSession? {
        guard let data = readKeychain() else { return nil }
        return try? JSONDecoder().decode(ElyanAuthSession.self, from: data)
    }

    private static func keychainQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: keychainAccount
        ]
    }

    private static func writeKeychain(data: Data) {
        var query = keychainQuery()
        SecItemDelete(query as CFDictionary)
        query[kSecValueData as String] = data
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(query as CFDictionary, nil)
    }

    private static func readKeychain() -> Data? {
        var query = keychainQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return data
    }

    private static func deleteKeychain() {
        SecItemDelete(keychainQuery() as CFDictionary)
    }
}

// MARK: - Models

struct ElyanAuthSession: Codable, Equatable {
    var id: String
    var displayName: String
    var email: String
    var accessToken: String
    var refreshToken: String
}

/// Minimal parse of POST /v1/chat/messages, enough to drive the SSE subscription.
struct ChatDispatch {
    let taskId: String
    let sessionId: String?

    static func parse(_ raw: Any) throws -> ChatDispatch {
        let root: [String: Any] = {
            if let dict = raw as? [String: Any] {
                if let data = dict["data"] as? [String: Any] { return data }
                return dict
            }
            return [:]
        }()
        let taskMap = (root["task"] as? [String: Any]) ?? root
        let taskId = (taskMap["id"] as? String)
            ?? (taskMap["taskId"] as? String)
            ?? (root["taskId"] as? String)
            ?? ""
        guard !taskId.isEmpty else {
            throw ElyanBackendError.malformedResponse("Chat dispatch response had no task id.")
        }
        let sessionMap = (root["session"] as? [String: Any]) ?? [:]
        let sessionId = (sessionMap["id"] as? String)
            ?? (sessionMap["sessionId"] as? String)
            ?? (root["sessionId"] as? String)
            ?? (root["chatSessionId"] as? String)
        return ChatDispatch(taskId: taskId, sessionId: sessionId)
    }
}

// MARK: - Errors

enum ElyanBackendError: Error, LocalizedError {
    case notAuthenticated
    case transport(String)
    case server(status: Int, message: String)
    case malformedResponse(String)

    var errorDescription: String? {
        switch self {
        case .notAuthenticated: return "Önce giriş yapmalısın."
        case .transport(let msg): return "Bağlantı hatası: \(msg)"
        case .server(let status, let msg): return "Sunucu (\(status)): \(msg)"
        case .malformedResponse(let msg): return msg
        }
    }
}

// MARK: - Session Models

struct ElyanSession: Identifiable, Equatable, Hashable {
    let id: String
    let title: String
    let lastMessage: String
    let updatedAt: Date
    let messageCount: Int
}

struct ElyanSessionMessage: Identifiable, Equatable, Hashable {
    let id: String
    let role: String // "user" | "assistant"
    let text: String
    let createdAt: Date
}

// MARK: - Device Models

struct ElyanDevice: Identifiable, Equatable {
    let id: String
    let name: String
    let platform: String // "macos" | "windows" | "linux"
    let lastSeenAt: Date?
    let isCurrentDevice: Bool
}

// MARK: - Parse Helpers (extension on ElyanBackend)

extension ElyanBackend {

    static func unwrap(_ raw: Any) -> [String: Any] {
        guard let dict = raw as? [String: Any] else { return [:] }
        if let data = dict["data"] as? [String: Any] { return data }
        return dict
    }

    static func parseSessions(_ raw: Any) -> [ElyanSession] {
        let payload = unwrap(raw)
        let items: [[String: Any]] = {
            if let arr = payload["sessions"] as? [[String: Any]] { return arr }
            if let arr = payload["data"] as? [[String: Any]] { return arr }
            if let arr = raw as? [[String: Any]] { return arr }
            return []
        }()
        let iso = ISO8601DateFormatter()
        return items.compactMap { item in
            guard let id = item["id"] as? String else { return nil }
            let title = (item["title"] as? String) ?? (item["name"] as? String) ?? "Sohbet"
            let lastMessage = (item["lastMessage"] as? String) ?? (item["summary"] as? String) ?? ""
            let updatedStr = (item["updatedAt"] as? String) ?? (item["lastMessageAt"] as? String) ?? ""
            let updatedAt = iso.date(from: updatedStr) ?? Date()
            let count = (item["messageCount"] as? Int) ?? 0
            return ElyanSession(id: id, title: title, lastMessage: lastMessage, updatedAt: updatedAt, messageCount: count)
        }
    }

    static func parseSessionMessages(_ raw: Any) -> [ElyanSessionMessage] {
        let payload = unwrap(raw)
        let items: [[String: Any]] = {
            if let arr = payload["messages"] as? [[String: Any]] { return arr }
            if let arr = raw as? [[String: Any]] { return arr }
            return []
        }()
        let iso = ISO8601DateFormatter()
        return items.compactMap { item in
            guard let id = item["id"] as? String else { return nil }
            let role = (item["role"] as? String) ?? "assistant"
            // Support blocks-style messages
            let text: String = {
                if let t = item["text"] as? String { return t }
                if let blocks = item["blocks"] as? [[String: Any]] {
                    return blocks.compactMap { $0["markdown"] as? String }.joined(separator: "\n")
                }
                if let content = item["content"] as? String { return content }
                return ""
            }()
            let createdStr = (item["createdAt"] as? String) ?? ""
            let createdAt = iso.date(from: createdStr) ?? Date()
            return ElyanSessionMessage(id: id, role: role, text: text, createdAt: createdAt)
        }
    }

    static func parseDevices(_ raw: Any) -> [ElyanDevice] {
        let payload = unwrap(raw)
        let items: [[String: Any]] = {
            if let arr = payload["devices"] as? [[String: Any]] { return arr }
            if let arr = raw as? [[String: Any]] { return arr }
            return []
        }()
        let iso = ISO8601DateFormatter()
        return items.compactMap { item in
            guard let id = item["id"] as? String else { return nil }
            let name = (item["name"] as? String) ?? (item["hostname"] as? String) ?? "Bilinmeyen Cihaz"
            let platform = (item["platform"] as? String) ?? "macos"
            let lastSeenStr = item["lastSeenAt"] as? String
            let lastSeenAt = lastSeenStr.flatMap { iso.date(from: $0) }
            let isCurrent = (item["isCurrentDevice"] as? Bool) ?? false
            return ElyanDevice(id: id, name: name, platform: platform, lastSeenAt: lastSeenAt, isCurrentDevice: isCurrent)
        }
    }
}
