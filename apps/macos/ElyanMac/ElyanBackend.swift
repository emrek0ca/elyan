import AppKit
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

    /// Tek-uçuş refresh: eş zamanlı 401 alan istekler AYNI refresh çağrısını
    /// bekler. Eskiden her 401 kendi /v1/auth/refresh çağrısını yapıyordu;
    /// refresh token rotasyonu yüzünden ikinci paralel çağrı geçersiz token'la
    /// gidip başarısız oluyor ve kullanıcı rastgele oturumdan düşüyordu.
    private var inflightRefresh: Task<ElyanAuthSession, Error>?

    /// POST /v1/auth/refresh
    @discardableResult
    func refresh() async throws -> ElyanAuthSession {
        if let inflight = inflightRefresh {
            return try await inflight.value
        }
        guard let current = session, !current.refreshToken.isEmpty else {
            throw ElyanBackendError.notAuthenticated
        }
        let task = Task<ElyanAuthSession, Error> { [weak self] in
            guard let self else { throw ElyanBackendError.notAuthenticated }
            do {
                let raw = try await self.postJSON(
                    path: "/v1/auth/refresh",
                    body: ["refreshToken": current.refreshToken],
                    requireAuth: false
                )
                let parsed = try Self.parseAuthSession(raw, refreshTokenFallback: current.refreshToken)
                try self.persistSession(parsed)
                return parsed
            } catch {
                // Refresh token'ın kendisi geçersizse oturumu yerelde de bitir:
                // aksi hâlde kullanıcı "girişli ama hiçbir istek çalışmıyor"
                // limbosunda kalıyordu (RootView yalnız açılışta doğruluyor).
                if case ElyanBackendError.server(let status, _) = error,
                   status == 401 || status == 403 {
                    try? self.clearSession()
                }
                throw error
            }
        }
        inflightRefresh = task
        defer { inflightRefresh = nil }
        return try await task.value
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
    func getSessionsPage(limit: Int = 20, cursor: String? = nil, forceRefresh: Bool = false) async throws -> ElyanSessionPage {
        var query: [URLQueryItem] = [URLQueryItem(name: "limit", value: "\(max(1, min(limit, 20)))")]
        if let cursor, !cursor.isEmpty {
            query.append(URLQueryItem(name: "cursor", value: cursor))
        }
        let raw = try await internalGetJSON(
            path: "/v1/chat/sessions",
            queryItems: query,
            requireAuth: true,
            cacheTTL: forceRefresh ? 0 : 300
        )
        return Self.parseSessionPage(raw)
    }

    func getSessions(limit: Int = 20, cursor: String? = nil, forceRefresh: Bool = false) async throws -> [ElyanSession] {
        try await getSessionsPage(limit: limit, cursor: cursor, forceRefresh: forceRefresh).sessions
    }

    /// GET /v1/chat/sessions/{id}/messages
    func getSessionMessages(sessionId: String, limit: Int = 50, cursor: String? = nil, forceRefresh: Bool = false) async throws -> (messages: [ElyanSessionMessage], hasMore: Bool, nextCursor: String?) {
        var queryItems: [URLQueryItem] = [URLQueryItem(name: "limit", value: "\(max(1, min(limit, 50)))")]
        if let cursor = cursor {
            queryItems.append(URLQueryItem(name: "cursor", value: cursor))
        }
        let raw = try await internalGetJSON(
            path: "/v1/chat/sessions/\(sessionId)/messages",
            queryItems: queryItems,
            requireAuth: true,
            cacheTTL: forceRefresh ? 0 : 300
        )
        return Self.parseSessionMessages(raw)
    }

    /// DELETE /v1/chat/sessions/{id}
    func deleteSession(sessionId: String) async throws {
        _ = try await deleteJSON(path: "/v1/chat/sessions/\(sessionId)", requireAuth: true)
    }

    // MARK: - Profile

    /// GET /v1/auth/avatar as an NSImage. Returns nil if the user has no
    /// avatar or the request fails — caller should fall back to initials.
    func fetchAvatarImage() async throws -> NSImage? {
        guard let token = session?.accessToken, !token.isEmpty else { return nil }
        var request = makeRequest(path: "/v1/auth/avatar", method: "GET")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        do {
            let (data, response) = try await urlSession.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                return nil
            }
            return NSImage(data: data)
        } catch {
            throw ElyanBackendError.transport(error.localizedDescription)
        }
    }

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

    /// Backend expects POST /v1/devices/:id/deactivate — there is no DELETE
    /// endpoint. Using DELETE silently 404'd, which is why stale devices
    /// stayed in the list forever.
    func removeDevice(deviceId: String) async throws {
        _ = try await postJSON(
            path: "/v1/devices/\(deviceId)/deactivate",
            body: [:],
            requireAuth: true
        )
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

        // Mobile'ın task_repository.dart sendChatMessage'ıyla birebir aynı gövde:
        // yalnız `blocks` (metin bloğu) + `metadata.renderContract` + `metadata.userBlocks`.
        // Üstte ayrı bir `content` alanı YOK — backend `content`'i varsa onu,
        // yoksa blocks[].markdown'dan türetir (schemas.ts); ikisini birden
        // göndermek zararsız olsa da mobille birebir aynı sözleşmeyi korumak
        // için tek kanal (blocks) kullanılıyor.
        let userBlock: [String: Any] = [
            "type": "text",
            "markdown": prompt,
            "visibility": "user_visible"
        ]
        var body: [String: Any] = [
            "blocks": [userBlock],
            "source": source,
            "requestedCapabilities": [],
            "metadata": [
                "source": source,
                "renderContract": [
                    "version": "elyan_blocks.v2",
                    "mode": "block_first",
                    "canonicalSurface": "blocks",
                    "legacyContent": "none"
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
            extraHeaders: extraHeaders,
            invalidatesCache: false
        )
        // Scoped invalidation: only chat session list/messages change when a
        // message is sent — devices/billing/profile caches stay warm.
        invalidateGetCache(pathContaining: "/v1/chat/sessions")
        return try ChatDispatch.parse(raw)
    }

    /// PATCH /v1/goals/{goalId} — mirrors mobile's TaskRepository.updateGoalStatus.
    /// Used by the goal_progress block's pause/finish actions.
    @discardableResult
    func updateGoalStatus(goalId: String, status: String) async throws -> Any {
        let encodedId = goalId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? goalId
        return try await patchJSON(
            path: "/v1/goals/\(encodedId)",
            body: ["status": status],
            requireAuth: true
        )
    }

    // MARK: - Request plumbing

    func postJSON(
        path: String,
        body: [String: Any],
        requireAuth: Bool,
        extraHeaders: [String: String] = [:],
        invalidatesCache: Bool = true
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
            case .success(let value, _):
                // A POST usually mutates something the user is about to look at
                // (send message → session list, create pairing → devices, etc).
                // Drop cache so the next GET returns fresh state. Hot-path
                // callers (chat send) pass invalidatesCache: false and scope
                // the invalidation themselves — nuking EVERY cached GET
                // (devices, billing, profile, avatar…) on every single chat
                // message forced a wave of cold refetches right when the app
                // was busiest.
                if invalidatesCache {
                    invalidateGetCache()
                }
                return value
            case .notModified:
                throw ElyanBackendError.malformedResponse("Unexpected 304 on a POST.")
            case .unauthorized:
                guard requireAuth, !attemptedRefresh else { throw ElyanBackendError.notAuthenticated }
                attemptedRefresh = true
                _ = try await refresh()
                continue
            }
        }
    }

    /// Legacy convenience wrapper — defaults to a 30-second cache so a tab
    /// re-open doesn't hit the server for something the user just saw. Pass
    /// `cacheTTL: 0` when a caller needs fresh data (e.g. auth/me refresh).
    func internalGetJSON(path: String, requireAuth: Bool) async throws -> Any {
        try await internalGetJSON(path: path, queryItems: [], requireAuth: requireAuth, cacheTTL: 30, extraHeaders: [:])
    }

    /// GET with URLComponents-safe query building, optional TTL cache, and
    /// optional custom headers (e.g. `x-pairing-token`).
    func internalGetJSON(
        path: String,
        queryItems: [URLQueryItem],
        requireAuth: Bool,
        cacheTTL: TimeInterval = 0,
        extraHeaders: [String: String] = [:]
    ) async throws -> Any {
        let key = cacheKey(path: path, queryItems: queryItems)
        if cacheTTL > 0, let hit = cachedValue(forKey: key) {
            return hit
        }
        // Cache expired (or forceRefresh/cacheTTL==0) — if we still hold the
        // stale value + its etag, send If-None-Match. A 304 means the payload
        // is byte-identical to what's already in memory: skip re-parsing and
        // re-mapping it into [ElyanSession]/[ElyanSessionMessage], just
        // re-stamp the TTL. Every one of these endpoints (chat sessions,
        // chat session messages) already emits weak ETags server-side
        // (sendConditionalJson, elyan-backend/src/lib/http.ts) — this was
        // previously unused, so a "force refresh" or any TTL expiry (message
        // pages: 5 minutes) always paid for a full re-transfer + re-parse
        // even when the conversation hadn't changed at all.
        let staleEntry = getCache[key]
        var attemptedRefresh = false
        while true {
            let raw = try await performRequest(
                method: "GET",
                path: path,
                bodyJSON: nil,
                requireAuth: requireAuth,
                extraHeaders: extraHeaders,
                queryItems: queryItems,
                ifNoneMatch: staleEntry?.etag
            )
            switch raw {
            case .success(let value, let etag):
                // Store even when cacheTTL == 0 (forceRefresh): the value
                // won't be served without revalidation next time (expiresAt
                // is immediately in the past), but the etag sticks around so
                // that *next* call — forced or not — can still 304 instead
                // of re-transferring.
                storeCached(value, forKey: key, ttl: cacheTTL, etag: etag)
                return value
            case .notModified:
                guard let staleEntry else {
                    // Shouldn't happen (304 implies we sent an etag, which
                    // implies staleEntry existed) — fail safe by treating it
                    // as "nothing to show" rather than force-unwrapping.
                    throw ElyanBackendError.malformedResponse("304 received without a cached prior value.")
                }
                storeCached(staleEntry.value, forKey: key, ttl: cacheTTL, etag: staleEntry.etag)
                return staleEntry.value
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
            case .success(let value, _):
                invalidateGetCache() // list/summary GETs must reflect this write
                return value
            case .notModified:
                throw ElyanBackendError.malformedResponse("Unexpected 304 on a PATCH.")
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
            case .success(let value, _):
                invalidateGetCache()
                return value
            case .notModified:
                throw ElyanBackendError.malformedResponse("Unexpected 304 on a PUT.")
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
            case .success(let value, _):
                invalidateGetCache()
                return value
            case .notModified:
                throw ElyanBackendError.malformedResponse("Unexpected 304 on a DELETE.")
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
            case .success(let value, _):
                var updated = session ?? current
                if let payload = value as? [String: Any] {
                    let root = (payload["data"] as? [String: Any]) ?? payload
                    let userMap = (root["user"] as? [String: Any]) ?? root
                    if let name = userMap["displayName"] as? String { updated.displayName = name }
                    if let mail = userMap["email"] as? String { updated.email = mail }
                    if let id = userMap["id"] as? String { updated.id = id }
                    if let has = userMap["hasAvatar"] as? Bool { updated.hasAvatar = has }
                    if let v = userMap["avatarVersion"] as? Int { updated.avatarVersion = v }
                    else if let v = userMap["avatarVersion"] as? Double { updated.avatarVersion = Int(v) }
                }
                try persistSession(updated)
                return updated
            case .notModified:
                throw ElyanBackendError.malformedResponse("Unexpected 304 on /v1/auth/me.")
            case .unauthorized:
                guard !attemptedRefresh else { throw ElyanBackendError.notAuthenticated }
                attemptedRefresh = true
                _ = try await refresh()
                continue
            }
        }
    }

    private enum HTTPOutcome {
        case success(value: Any, etag: String?)
        // Backend chat/session GET endpoints (`sendConditionalJson`, http.ts)
        // already implement weak ETags + 304 — this client just never sent
        // `If-None-Match` to take advantage of it, so every TTL-expired or
        // force-refreshed GET re-transferred and re-parsed the full payload
        // even when nothing had changed server-side.
        case notModified
        case unauthorized
    }

    private func performRequest(
        method: String,
        path: String,
        bodyJSON: [String: Any]?,
        requireAuth: Bool,
        extraHeaders: [String: String],
        queryItems: [URLQueryItem] = [],
        ifNoneMatch: String? = nil
    ) async throws -> HTTPOutcome {
        var request = makeRequest(path: path, method: method, queryItems: queryItems)
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
        if let ifNoneMatch, !ifNoneMatch.isEmpty {
            request.setValue(ifNoneMatch, forHTTPHeaderField: "If-None-Match")
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
        if status == 304 {
            return .notModified
        }

        let decoded: Any? = data.isEmpty ? nil : (try? JSONSerialization.jsonObject(with: data, options: []))
        guard (200..<300).contains(status) else {
            let message = Self.extractErrorMessage(decoded) ?? "HTTP \(status)"
            throw ElyanBackendError.server(status: status, message: message)
        }
        let etag = http.value(forHTTPHeaderField: "Etag")
        return .success(value: decoded ?? [:], etag: etag)
    }

    /// Builds a URLRequest using URLComponents so `?query=…` and other reserved
    /// characters are encoded correctly. The old `appendingPathComponent`
    /// approach percent-encoded `?` (turning /v1/chat/sessions?limit=20 into
    /// /v1/chat/sessions%3Flimit=20 → hard 404).
    private func makeRequest(path: String, method: String, queryItems: [URLQueryItem] = []) -> URLRequest {
        var components = URLComponents(
            url: Self.baseURL,
            resolvingAgainstBaseURL: false
        ) ?? URLComponents()
        // Preserve any base path (there isn't one today but keeps this defensive).
        let normalizedPath = path.hasPrefix("/") ? path : "/\(path)"
        components.path = normalizedPath
        if !queryItems.isEmpty {
            components.queryItems = queryItems
        }
        let url = components.url ?? Self.baseURL.appendingPathComponent(normalizedPath)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Elyan/1.0 (macOS)", forHTTPHeaderField: "User-Agent")
        return request
    }

    // MARK: - GET cache
    //
    // Tab-switch flows (history, plans, summary, devices) were re-fetching on
    // every appearance, freezing the UI on network latency. A tiny in-memory
    // TTL cache makes navigation feel instant; `forceRefresh` bypasses it for
    // pull-to-refresh or after a mutation.
    private struct CacheEntry {
        let value: Any
        let expiresAt: Date
        // Kept even for a `ttl <= 0` (forceRefresh) entry — expiresAt already
        // in the past means cachedValue(forKey:) will never serve it without
        // a network round-trip, but the etag lets that round-trip come back
        // as a cheap 304 instead of a full re-transfer + re-parse.
        let etag: String?
    }
    private var getCache: [String: CacheEntry] = [:]

    private func cacheKey(path: String, queryItems: [URLQueryItem]) -> String {
        let userId = session?.id ?? "anon"
        let query = queryItems.map { "\($0.name)=\($0.value ?? "")" }.sorted().joined(separator: "&")
        return "\(userId)|\(path)|\(query)"
    }

    private func cachedValue(forKey key: String) -> Any? {
        guard let entry = getCache[key], entry.expiresAt > Date() else { return nil }
        return entry.value
    }

    private func storeCached(_ value: Any, forKey key: String, ttl: TimeInterval, etag: String? = nil) {
        let resolvedEtag = etag ?? getCache[key]?.etag
        getCache[key] = CacheEntry(value: value, expiresAt: Date().addingTimeInterval(ttl), etag: resolvedEtag)
    }

    /// Drop everything cached for the signed-in user — call after mutations
    /// (send message, save profile, checkout, remove device, sign out).
    func invalidateGetCache() {
        getCache.removeAll()
    }

    /// Scoped variant: drop only entries whose cache key contains the given
    /// path fragment (keys are "userId|path|query"). Lets hot paths like chat
    /// send invalidate just the chat caches instead of everything.
    func invalidateGetCache(pathContaining fragment: String) {
        getCache = getCache.filter { !$0.key.contains(fragment) }
    }

    private static func extractErrorMessage(_ decoded: Any?) -> String? {
        guard let dict = decoded as? [String: Any] else { return nil }
        // Root-level "message" (fastify + our badRequest/unauthorized helpers).
        let baseMessage: String? = {
            if let msg = dict["message"] as? String, !msg.isEmpty { return msg }
            if let nested = dict["error"] as? [String: Any], let msg = nested["message"] as? String, !msg.isEmpty { return msg }
            if let msg = dict["error"] as? String, !msg.isEmpty { return msg }
            return nil
        }()

        // Backend validation errors carry a zod-style `details` array with
        // per-field paths — surface them so the user sees which field is
        // actually invalid instead of a generic "Invalid request payload".
        let details: String? = {
            guard let items = dict["details"] as? [[String: Any]], !items.isEmpty else { return nil }
            let lines = items.compactMap { item -> String? in
                let path = ((item["path"] as? [Any])?.map { "\($0)" }.joined(separator: ".")
                    ?? (item["path"] as? String))
                let msg = (item["message"] as? String) ?? (item["code"] as? String) ?? ""
                if let path, !path.isEmpty { return "\(path): \(msg)" }
                return msg.isEmpty ? nil : msg
            }
            return lines.isEmpty ? nil : lines.joined(separator: " · ")
        }()

        switch (baseMessage, details) {
        case (let msg?, let det?): return "\(msg) — \(det)"
        case (let msg?, nil):      return msg
        case (nil, let det?):      return det
        case (nil, nil):           return nil
        }
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
        let hasAvatar = (user["hasAvatar"] as? Bool) ?? false
        let avatarVersion: Int = {
            if let n = user["avatarVersion"] as? Int { return n }
            if let n = user["avatarVersion"] as? Double { return Int(n) }
            if let s = user["avatarVersion"] as? String, let n = Int(s) { return n }
            return 0
        }()
        return ElyanAuthSession(
            id: (user["id"] as? String) ?? (user["userId"] as? String) ?? "elyan-user",
            displayName: (user["displayName"] as? String) ?? (user["name"] as? String) ?? "",
            email: (user["email"] as? String) ?? "",
            accessToken: accessToken,
            refreshToken: refreshToken,
            hasAvatar: hasAvatar,
            avatarVersion: avatarVersion
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
    var hasAvatar: Bool = false
    var avatarVersion: Int = 0
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
    /// True for conversations executed purely on this desktop (local-first
    /// runtime) that never round-tripped to the cloud. These live in the local
    /// bridge conversation store, not backend `/v1/chat/sessions`, so history
    /// detail must be loaded from the bridge instead of the backend.
    var isLocal: Bool = false
}

struct ElyanSessionPage: Equatable {
    let sessions: [ElyanSession]
    let hasMore: Bool
    let nextCursor: String?
}

struct ElyanSessionMessage: Identifiable, Equatable, Hashable {
    let id: String
    let role: String // "user" | "assistant"
    let text: String
    let createdAt: Date
    /// Fully-parsed widget blocks (chart/table/math/svg/…) from the history
    /// payload. History previously flattened blocks into markdown text and
    /// dropped everything non-textual — a chart drawn on mobile rendered as
    /// nothing when the same session was opened on desktop, even though the
    /// live-streaming path renders the identical block JSON fine.
    let blocks: [ChatBlock]
    // Backend `chat_messages` rows always carry a status ("queued" / "running"
    // / "waiting_approval" / "completed" / "failed" / "canceled" —
    // contracts/domain.ts chatMessageStatusValues) and it's already present
    // in the GET /v1/chat/sessions/:id/messages JSON (shapeChatMessageForResponse
    // spreads the raw row). This client previously never decoded it, so
    // reopening a session with a task stuck server-side (e.g. the backend
    // fire-and-forget chat task deadlock — see task-lifecycle notes) showed a
    // static, unlabeled message with no "still processing" or "failed" signal
    // at all — indistinguishable from a normal completed reply.
    let status: String
    let taskId: String?
    let errorMessage: String?

    var isPending: Bool {
        ["queued", "running", "waiting_approval"].contains(status.lowercased())
    }
    var isFailed: Bool {
        ["failed", "canceled"].contains(status.lowercased())
    }

    // Manual conformances: ChatBlock (enum with associated values) isn't
    // Hashable, and block content is fully determined by the message row
    // anyway — id + text + status identify a history message.
    static func == (lhs: ElyanSessionMessage, rhs: ElyanSessionMessage) -> Bool {
        lhs.id == rhs.id
            && lhs.text == rhs.text
            && lhs.status == rhs.status
            && lhs.blocks.count == rhs.blocks.count
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
        hasher.combine(text)
        hasher.combine(status)
    }
}

// MARK: - Device Models

struct ElyanRuntimeTask: Identifiable, Equatable, Hashable {
    let id: String
    let title: String
    let status: String
    let summary: String
    let error: String

    init(runtimeItem: RuntimeTaskItem) {
        self.id = runtimeItem.id
        self.title = runtimeItem.title
        self.status = runtimeItem.status
        self.summary = runtimeItem.summary
        self.error = runtimeItem.error
    }
}

struct ElyanDevice: Identifiable, Equatable {
    let id: String
    let name: String
    let platform: String // "macos" | "windows" | "linux"
    let lastSeenAt: Date?
    let isCurrentDevice: Bool
}

// MARK: - Parse Helpers (extension on ElyanBackend)

/// Backend JS `toISOString()` milisaniyeli tarih üretir ("…T12:34:56.789Z");
/// varsayılan ISO8601DateFormatter bunu PARSE EDEMEZ ve her tarih sessizce
/// `Date()`'e (şimdi) düşüyordu — oturum geçmişi sıralaması ve "son mesaj"
/// zamanları bu yüzden bozuktu. Fractional destekli formatter + fallback.
enum ElyanDateParser {
    static let isoWithFractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
    static let iso = ISO8601DateFormatter()

    static func parse(_ value: String?) -> Date? {
        guard let value, !value.isEmpty else { return nil }
        return isoWithFractional.date(from: value) ?? iso.date(from: value)
    }
}

extension ElyanBackend {

    static func unwrap(_ raw: Any) -> [String: Any] {
        guard let dict = raw as? [String: Any] else { return [:] }
        if let data = dict["data"] as? [String: Any] { return data }
        return dict
    }

    static func parseSessionPage(_ raw: Any) -> ElyanSessionPage {
        let payload = unwrap(raw)
        let items: [[String: Any]] = {
            if let arr = payload["sessions"] as? [[String: Any]] { return arr }
            if let arr = payload["data"] as? [[String: Any]] { return arr }
            if let arr = raw as? [[String: Any]] { return arr }
            return []
        }()
        let sessions: [ElyanSession] = items.compactMap { item in
            guard let id = item["id"] as? String else { return nil }
            let title = (item["title"] as? String) ?? (item["name"] as? String) ?? "Sohbet"
            let lastMessage = (item["lastMessage"] as? String) ?? (item["summary"] as? String) ?? ""
            let updatedStr = (item["updatedAt"] as? String) ?? (item["lastMessageAt"] as? String) ?? ""
            let updatedAt = ElyanDateParser.parse(updatedStr) ?? Date()
            let count = (item["messageCount"] as? Int) ?? 0
            return ElyanSession(id: id, title: title, lastMessage: lastMessage, updatedAt: updatedAt, messageCount: count)
        }
        let meta = payload["meta"] as? [String: Any]
        let nextCursor = (meta?["nextCursor"] as? String)
            ?? (payload["nextCursor"] as? String)
            ?? (payload["cursor"] as? String)
        let hasMore = (meta?["hasMore"] as? Bool)
            ?? (payload["hasMore"] as? Bool)
            ?? (nextCursor?.isEmpty == false)
        return ElyanSessionPage(sessions: sessions, hasMore: hasMore, nextCursor: nextCursor)
    }

    static func parseSessions(_ raw: Any) -> [ElyanSession] {
        parseSessionPage(raw).sessions
    }

    static func isUUID(_ value: String) -> Bool {
        UUID(uuidString: value) != nil
    }

    /// Maps the bridge `conversation.list` payload into sessions, surfacing
    /// only local-only conversations (bridge-generated "conv_..." ids). Backend-
    /// synced conversations carry UUID ids and already appear via
    /// `/v1/chat/sessions`, so filtering by non-UUID id avoids duplicates.
    static func parseLocalSessions(_ conversations: [[String: Any]]) -> [ElyanSession] {
        conversations.compactMap { item in
            guard let id = item["id"] as? String, !id.isEmpty, !isUUID(id) else { return nil }
            let rawTitle = (item["title"] as? String) ?? ""
            let title = rawTitle.isEmpty ? "Yerel sohbet" : rawTitle
            let preview = (item["preview"] as? String) ?? (item["lastMessage"] as? String) ?? ""
            let updatedAt = ElyanDateParser.parse(item["updatedAt"] as? String) ?? Date()
            let count = (item["messageCount"] as? Int) ?? 0
            return ElyanSession(
                id: id, title: title, lastMessage: preview,
                updatedAt: updatedAt, messageCount: count, isLocal: true
            )
        }
    }

    static func parseSessionMessages(_ raw: Any) -> (messages: [ElyanSessionMessage], hasMore: Bool, nextCursor: String?) {
        let payload = unwrap(raw)
        let items: [[String: Any]] = {
            if let arr = payload["messages"] as? [[String: Any]] { return arr }
            if let arr = raw as? [[String: Any]] { return arr }
            return []
        }()
        let meta = payload["meta"] as? [String: Any]
        let hasMore = (meta?["hasMore"] as? Bool) ?? false
        let nextCursor = meta?["nextCursor"] as? String
        
        let messages = items.compactMap { item -> ElyanSessionMessage? in
            guard let id = item["id"] as? String else { return nil }
            let role = (item["role"] as? String) ?? "assistant"
            // Parse the FULL typed block array — the same ChatBlock.parse the
            // live SSE path uses — so charts/tables/math/svg from history
            // render identically to when they were first streamed.
            let rawBlocks = (item["blocks"] as? [[String: Any]]) ?? []
            let blocks = ChatBlock.parseArray(from: rawBlocks)
            // Text fallback (used when a message carries no renderable blocks).
            let text: String = {
                if let t = item["text"] as? String { return t }
                if !rawBlocks.isEmpty {
                    return rawBlocks.compactMap { $0["markdown"] as? String }.joined(separator: "\n")
                }
                if let content = item["content"] as? String { return content }
                return ""
            }()
            let createdStr = (item["createdAt"] as? String) ?? ""
            let createdAt = ElyanDateParser.parse(createdStr) ?? Date()
            let status = (item["status"] as? String) ?? "completed"
            let taskId = item["taskId"] as? String
            let errorMessage = item["error"] as? String
            return ElyanSessionMessage(
                id: id, role: role, text: text, createdAt: createdAt,
                blocks: blocks,
                status: status, taskId: taskId, errorMessage: errorMessage
            )
        }
        return (messages, hasMore, nextCursor)
    }

    static func parseDevices(_ raw: Any) -> [ElyanDevice] {
        let payload = unwrap(raw)
        let items: [[String: Any]] = {
            if let arr = payload["devices"] as? [[String: Any]] { return arr }
            if let arr = raw as? [[String: Any]] { return arr }
            return []
        }()
        return items.compactMap { item in
            guard let id = item["id"] as? String else { return nil }
            let name = (item["name"] as? String) ?? (item["hostname"] as? String) ?? "Bilinmeyen Cihaz"
            let platform = (item["platform"] as? String) ?? "macos"
            let lastSeenAt = ElyanDateParser.parse(item["lastSeenAt"] as? String)
            let isCurrent = (item["isCurrentDevice"] as? Bool) ?? false
            return ElyanDevice(id: id, name: name, platform: platform, lastSeenAt: lastSeenAt, isCurrentDevice: isCurrent)
        }
    }
}
