import Foundation

@MainActor
final class PythonRuntimeSupervisor: ObservableObject {
    private let bridge = RuntimeBridgeSwift()
    private var canQueryRuntimeSession = false
    private var pendingAuthSession: ElyanAuthSession?
    private var pendingAuthSync = false
    private var lastAuthFingerprint = ""
    @Published var isRunning = false
    @Published var runtimeReady = false
    @Published var backendReady = false
    @Published var signedIn = false
    @Published var lifecycleState = "starting"
    @Published var runtimeLifecycleState = ""
    @Published var lastError = ""
    @Published var lastDiagnostic = ""
    @Published var activeConversationId = ""
    @Published var taskInbox: [RuntimeTaskItem] = []
    @Published var pairingSummary = ""
    @Published var pairingCode = ""
    @Published var pairingQrText = ""
    @Published var pairingClaimed = false
    @Published var pairingExpired = false
    @Published var isExecutingAssignedTasks = false

    var pendingTaskCount: Int {
        taskInbox.filter { !$0.isTerminal }.count
    }

    var isOperational: Bool {
        isRunning && runtimeReady && backendReady
    }

    var statusText: String {
        if isOperational {
            return signedIn ? "connected" : "ready"
        }
        if isRunning && runtimeReady {
            return "runtime ready"
        }
        return lifecycleState
    }

    private var pairingPollTask: Task<Void, Never>?
    var onAuthRefreshNeeded: (() async -> Void)?
    /// Runtime tam operasyonel hale geldiğinde (boot veya crash-restart
    /// sonrası) bir kez tetiklenir — AppState bunu backend'de bekleyen
    /// görevleri HEMEN çekip yürütmek için kullanır; yoksa uygulama açılışında
    /// kuyrukta bekleyen görevler ilk SSE event'ine kadar el değmeden kalırdı.
    var onBecameOperational: (() async -> Void)?

    private var crashRestartAttempts = 0
    private var crashRestartTask: Task<Void, Never>?
    private static let maxCrashRestartAttempts = 3
    private var lastStartSession: ElyanAuthSession?

    init() {
        bridge.onUnsolicitedResponse = { [weak self] response in
            Task { @MainActor in
                self?.handleUnsolicited(response)
            }
        }
        bridge.onDiagnostic = { [weak self] diagnostic in
            Task { @MainActor in
                self?.lastDiagnostic = diagnostic
            }
        }
        bridge.onProcessTerminated = { [weak self] status in
            Task { @MainActor in
                self?.handleUnexpectedTermination(status: status)
            }
        }
    }

    func start(initialSession: ElyanAuthSession? = nil) {
        lastStartSession = initialSession
        Task {
            do {
                try bridge.startProcess()
                isRunning = true
                lifecycleState = "connecting"
                pendingAuthSession = initialSession
                pendingAuthSync = true
                _ = await flushPendingAuthSync()
                await refreshAll()
                // A clean, successful start resets the crash counter so a
                // later unrelated crash gets the full retry budget again.
                crashRestartAttempts = 0
                if isOperational {
                    await onBecameOperational?()
                }
            } catch {
                isRunning = false
                runtimeReady = false
                backendReady = false
                lifecycleState = "degraded"
                lastError = safeMessage(error)
            }
        }
    }

    func stop() {
        crashRestartTask?.cancel()
        crashRestartTask = nil
        pairingPollTask?.cancel()
        pairingPollTask = nil
        bridge.stopProcess()
        isRunning = false
        runtimeReady = false
        backendReady = false
        runtimeLifecycleState = ""
        lifecycleState = "stopped"
    }

    /// A crash previously left `isRunning`/`lifecycleState` stale (nothing
    /// updated them until the next request happened to fail) and nothing
    /// ever restarted the process — the user's only signal was a status dot
    /// quietly going orange. This reflects the crash immediately and retries
    /// with a bounded backoff instead of staying silently dead forever.
    private func handleUnexpectedTermination(status: Int32) {
        isRunning = false
        runtimeReady = false
        backendReady = false
        lifecycleState = "crashed"
        lastError = "Python runtime beklenmedik şekilde sonlandı (exit \(status))."

        guard crashRestartAttempts < Self.maxCrashRestartAttempts else {
            lastError += " Otomatik yeniden başlatma denemeleri tükendi; manuel olarak yeniden başlatın."
            return
        }
        crashRestartAttempts += 1
        let delaySeconds = [2.0, 5.0, 15.0][min(crashRestartAttempts - 1, 2)]
        crashRestartTask?.cancel()
        crashRestartTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delaySeconds * 1_000_000_000))
            guard let self, !Task.isCancelled else { return }
            self.start(initialSession: self.lastStartSession)
        }
    }

    func syncAuthSession(_ session: ElyanAuthSession?) async {
        pendingAuthSession = session
        pendingAuthSync = true
        _ = await flushPendingAuthSync()
    }

    // MARK: - Local-first chat (Jarvis yolu)

    /// Yerel sohbet bağlamının kimliği. Boşsa bridge yeni konuşma açar ve
    /// dönen kimlik burada saklanır; cloud session'a geçişte üzerine yazılır.
    private var localConversationId = ""

    func setLocalConversation(_ id: String) {
        localConversationId = id
    }

    struct LocalChatReply {
        let text: String
        let needsConfirmation: Bool
    }

    /// Komutu YEREL runtime'da çalıştırır (deterministik router + araçlar).
    /// Bulut round-trip'i yok: "safariyi aç" gerçekten Safari'yi açar ve
    /// sonuç senkron döner. Bridge çalışmıyorsa fırlatır — çağıran buluta
    /// düşebilir.
    func sendLocalChat(_ text: String) async throws -> LocalChatReply {
        guard isRunning, runtimeReady else {
            throw RuntimeBridgeSwiftError.runtimeNotStarted
        }
        let response = try await bridge.request(
            capability: "conversation.send",
            payload: [
                "conversationId": localConversationId,
                "text": text,
            ],
            timeoutSeconds: 180
        )
        let map = response.resultMap
        if let cid = string(map["conversationId"]), !cid.isEmpty {
            localConversationId = cid
        }
        let content = string(map["assistantMessage"]) ?? ""
        guard response.ok, !content.isEmpty else {
            let message = string((map["error"] as? [String: Any])?["message"])
                ?? "Yerel runtime yanıt üretemedi."
            throw NSError(
                domain: "ElyanLocalChat",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: message]
            )
        }
        return LocalChatReply(
            text: content,
            needsConfirmation: bool(map["needsConfirmation"])
        )
    }


    /// Fetches and directly executes any tasks the mobile app has dispatched
    /// to this desktop, then refreshes the local task inbox so the UI reflects
    /// the result immediately rather than waiting for the next tick.
    @discardableResult
    func executeAssignedTasks(limit: Int = 5) async -> Bool {
        guard isRunning, !isExecutingAssignedTasks else { return false }
        isExecutingAssignedTasks = true
        defer { isExecutingAssignedTasks = false }
        do {
            let response = try await bridge.request(
                capability: "runtime.tasks.execute_assigned",
                payload: ["limit": limit],
                timeoutSeconds: 90
            )
            // Execution mutates the local task inbox as a side effect; pull the
            // fresh list regardless of `ok` (a partial failure can still have
            // processed some tasks).
            await refreshConnectionAndTasks()
            return response.ok
        } catch {
            lastError = safeMessage(error)
            return false
        }
    }

    /// Lightweight refresh used by the poll loop: a single `runtime.bootstrap`
    /// call carries connection state, sign-in state, and the live task inbox.
    private func refreshConnectionAndTasks() async {
        _ = await flushPendingAuthSync()
        do {
            let response = try await bridge.request(capability: "runtime.bootstrap", timeoutSeconds: 30)
            applyBootstrap(response)
            lifecycleState = isOperational ? "connected" : (runtimeReady ? "runtime_ready" : "degraded")
        } catch {
            lastError = safeMessage(error)
            lifecycleState = runtimeReady ? "ready_with_backend_issue" : "degraded"
        }
    }

    func refreshTaskInbox() async {
        guard isRunning else { return }
        await refreshConnectionAndTasks()
    }

    private func flushPendingAuthSync() async -> Bool {
        guard isRunning, pendingAuthSync else { return false }
        let session = pendingAuthSession
        let fingerprint = authFingerprint(for: session)
        guard fingerprint != lastAuthFingerprint else {
            pendingAuthSync = false
            return false
        }

        do {
            let response = try await bridge.request(
                capability: "backend.auth_sync_session",
                payload: authPayload(for: session),
                timeoutSeconds: 20
            )
            pendingAuthSync = false
            lastAuthFingerprint = fingerprint
            applySyncedAuth(response)
            return true
        } catch {
            lastError = safeMessage(error)
            return false
        }
    }

    /// Approves or denies a mobile-dispatched task that's waiting for local
    /// confirmation, then immediately resumes execution instead of waiting for
    /// the next poll tick.
    func approveTask(taskId: String, approved: Bool, notes: String = "") async {
        guard !taskId.isEmpty else { return }
        do {
            _ = try await bridge.request(
                capability: "backend.tasks.approval",
                payload: ["taskId": taskId, "approved": approved, "notes": notes],
                timeoutSeconds: 30
            )
            await executeAssignedTasks()
        } catch {
            lastError = safeMessage(error)
        }
    }

    func refreshAll() async {
        let didSyncAuth = await flushPendingAuthSync()
        do {
            let bootstrap = try await bridge.request(capability: "runtime.bootstrap", timeoutSeconds: 45)
            applyBootstrap(bootstrap)

            if didSyncAuth {
                lifecycleState = isOperational ? "connected" : (runtimeReady ? "runtime_ready" : "degraded")
                return
            }

            let mobile = try await bridge.request(capability: "backend.mobile_bootstrap", timeoutSeconds: 25)
            applyMobileBootstrap(mobile)

            lifecycleState = isOperational ? "connected" : (runtimeReady ? "runtime_ready" : "degraded")

            let auth = try await bridge.request(capability: "backend.auth_me", timeoutSeconds: 20)
            applyAuth(auth)

            if canQueryRuntimeSession {
                let session = try await bridge.request(capability: "runtime.session", timeoutSeconds: 10)
                applyRuntimeSession(session)
            }

            lifecycleState = isOperational ? "connected" : (runtimeReady ? "runtime_ready" : "degraded")
        } catch {
            lastError = safeMessage(error)
            lifecycleState = runtimeReady ? "ready_with_backend_issue" : "degraded"
        }
    }

    private func applySyncedAuth(_ response: RuntimeResponse) {
        signedIn = response.ok && ((response.resultMap["signedIn"] as? Bool) ?? signedIn)
        if let auth = response.resultMap["authMe"] as? [String: Any] {
            applyAuthMap(auth)
        }
        if let mobile = response.resultMap["mobileBootstrap"] as? [String: Any] {
            applyMobileBootstrapMap(mobile)
        }
        if let session = response.resultMap["runtimeSession"] as? [String: Any] {
            applyRuntimeSessionMap(session)
        }
        lifecycleState = isOperational ? "connected" : (runtimeReady ? "runtime_ready" : "degraded")
    }

    func createPairingSession(forceNew: Bool = false) async {
        pairingPollTask?.cancel()
        pairingClaimed = false
        pairingExpired = false
        pairingCode = ""
        pairingQrText = ""

        // Retry loop: pairing.create_session hits the backend over the Python
        // bridge — a cold Python subprocess plus a cold backend can genuinely
        // take longer than the old flat 30s. Try up to 3 times with a longer
        // per-attempt budget and a short backoff; surface progress to the UI so
        // the user isn't staring at a frozen button.
        let attempts = 3
        let perAttemptTimeout: TimeInterval = 45
        var lastError: Error?

        let payload: [String: Any] = [
            "deviceLabel": Host.current().localizedName ?? "Elyan Mac",
            "platform": "macos",
            "runtimeVersion": "1.0.0",
            "forceNew": forceNew,
        ]

        for attempt in 1...attempts {
            if attempt > 1 {
                pairingSummary = "Bağlantı zayıf, tekrar deneniyor (\(attempt)/\(attempts))…"
                try? await Task.sleep(nanoseconds: UInt64(1_500_000_000 * (attempt - 1)))
            }
            do {
                let response = try await bridge.request(
                    capability: "pairing.create_session",
                    payload: payload,
                    timeoutSeconds: perAttemptTimeout
                )
                // Bridge wraps BackendResult under "result"; its "data" carries
                // the pairing payload.
                let backendResult = response.resultMap["result"] as? [String: Any] ?? response.resultMap
                let data = backendResult["data"] as? [String: Any] ?? backendResult
                let code = string(data["manualEntryCode"]) ?? string(data["pairingCode"]) ?? ""
                let session = string(data["sessionId"]) ?? string(data["id"]) ?? ""

                if response.ok, !code.isEmpty {
                    pairingCode = code
                    pairingQrText = string(data["qrText"]) ?? code
                    pairingSummary = "Telefonunda bu kodu gir: \(code)"
                    if !session.isEmpty {
                        startPairingClaimPoll(sessionId: session)
                    }
                    return
                }
                // The backend answered but without a code — no point retrying,
                // there's a policy/config problem to surface.
                pairingSummary = response.ok
                    ? "Eşleştirme oturumu hazır, kod bekleniyor."
                    : "Eşleştirme oturumu oluşturulamadı. Tekrar dene."
                return
            } catch {
                lastError = error
                // fall through to retry
            }
        }

        if let error = lastError {
            pairingSummary = safeMessage(error)
        } else {
            pairingSummary = "Eşleştirme oturumu oluşturulamadı. Tekrar dene."
        }
    }

    /// After showing a pairing code, poll for the mobile side claiming it so
    /// the UI can confirm pairing succeeded instead of leaving the user
    /// guessing. The bridge also auto-registers the runtime once claimed
    /// (see pairing_get_session in bridge.py), so a final refreshAll() here
    /// just brings the UI's `canQueryRuntimeSession`/`signedIn` state forward
    /// immediately rather than waiting for the next poll tick.
    private func startPairingClaimPoll(sessionId: String) {
        pairingPollTask?.cancel()
        pairingPollTask = Task { [weak self] in
            guard let self else { return }
            for _ in 0..<150 where !Task.isCancelled {
                do {
                    let response = try await self.bridge.request(
                        capability: "pairing.get_session",
                        payload: ["sessionId": sessionId],
                        timeoutSeconds: 15
                    )
                    let backendResult = response.resultMap["result"] as? [String: Any] ?? response.resultMap
                    let data = backendResult["data"] as? [String: Any] ?? backendResult
                    let status = string(data["status"]) ?? ""
                    if status == "claimed" {
                        self.pairingClaimed = true
                        self.pairingSummary = "Eşleştirme tamamlandı."
                        await self.refreshAll()
                        if self.isOperational {
                            await self.onBecameOperational?()
                        }
                        return
                    }
                    if status == "expired" || status == "canceled" {
                        self.pairingExpired = true
                        self.pairingSummary = "Eşleştirme kodu süresi doldu. Yeniden deneyin."
                        return
                    }
                } catch {
                    // Transient network hiccup — keep polling until the budget runs out.
                }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }

    private func authPayload(for session: ElyanAuthSession?) -> [String: Any] {
        guard let session else {
            return ["signedIn": false]
        }
        return [
            "signedIn": true,
            "id": session.id,
            "email": session.email,
            "displayName": session.displayName,
            "accessToken": session.accessToken,
            "refreshToken": session.refreshToken,
        ]
    }

    private func authFingerprint(for session: ElyanAuthSession?) -> String {
        guard let session else { return "signed_out" }
        return [
            session.id,
            session.email,
            session.displayName,
            session.accessToken,
            session.refreshToken,
        ].joined(separator: "|")
    }

    private func handleUnsolicited(_ response: RuntimeResponse) {
        if response.capability == "bridge.ready" {
            runtimeReady = response.ok
            lifecycleState = response.ok ? "runtime_started" : "degraded"
        } else if response.capability == "backend.auth_refresh_needed" {
            Task { @MainActor in
                await onAuthRefreshNeeded?()
            }
        }
    }

    private func applyBootstrap(_ response: RuntimeResponse) {
        runtimeReady = response.ok
        let result = response.resultMap
        let backend = result["backend"] as? [String: Any] ?? [:]
        backendReady = bool((backend["health"] as? [String: Any])?["ok"]) || bool(result["ok"])
        let state = result["state"] as? [String: Any] ?? [:]
        let runtime = state["runtime"] as? [String: Any] ?? [:]
        canQueryRuntimeSession = !(string(runtime["runtimeToken"]) ?? "").isEmpty
        runtimeLifecycleState = string(runtime["lifecycleState"]) ?? ""
        lifecycleState = response.ok ? "runtime_ready" : "degraded"
        signedIn = authReady(from: state)
        activeConversationId = string((state["conversation"] as? [String: Any])?["activeId"]) ?? activeConversationId

        // `status()` (nested under the top-level "runtime" key, distinct from the
        // raw state snapshot above) carries the live local task inbox — the same
        // data the background relay thread updates as mobile tasks are received.
        let runtimeStatus = result["runtime"] as? [String: Any] ?? [:]
        applyTaskInbox(runtimeStatus["taskInbox"] as? [String: Any])
    }

    private func applyTaskInbox(_ taskInbox: [String: Any]?) {
        guard let items = taskInbox?["items"] as? [[String: Any]] else { return }
        self.taskInbox = items.compactMap(RuntimeTaskItem.init(dictionary:))
            .sorted { $0.updatedAt > $1.updatedAt }
    }

    private func applyAuth(_ response: RuntimeResponse) {
        if response.ok {
            signedIn = true
        } else if !signedIn, let message = response.error?.message {
            lastError = message
        }
    }

    private func applyAuthMap(_ auth: [String: Any]) {
        if bool(auth["ok"]) {
            signedIn = true
        } else if !signedIn, let error = auth["error"] as? [String: Any], let message = string(error["message"]) {
            lastError = message
        }
    }

    private func applyMobileBootstrap(_ response: RuntimeResponse) {
        backendReady = backendReady || response.ok
        let backendResult = response.resultMap["result"] as? [String: Any] ?? response.resultMap
        let data = backendResult["data"] as? [String: Any] ?? backendResult
        if data["user"] is [String: Any] {
            signedIn = true
        }
        if response.ok {
            lifecycleState = runtimeReady ? "connected" : lifecycleState
        }
    }

    private func applyMobileBootstrapMap(_ mobile: [String: Any]) {
        backendReady = backendReady || bool(mobile["ok"])
        let backendResult = mobile["result"] as? [String: Any] ?? mobile
        let data = backendResult["data"] as? [String: Any] ?? backendResult
        if data["user"] is [String: Any] {
            signedIn = true
        }
        if bool(mobile["ok"]) {
            lifecycleState = runtimeReady ? "connected" : lifecycleState
        }
    }

    private func applyRuntimeSession(_ response: RuntimeResponse) {
        let result = response.resultMap
        let runtime = result["runtime"] as? [String: Any] ?? result
        runtimeReady = response.ok || bool(runtime["ready"])
        runtimeLifecycleState = string(runtime["lifecycleState"]) ?? runtimeLifecycleState
        lifecycleState = isOperational ? "connected" : lifecycleState
    }

    private func applyRuntimeSessionMap(_ session: [String: Any]) {
        let runtime = session["runtime"] as? [String: Any] ?? session
        runtimeReady = bool(session["ok"]) || bool(runtime["ready"])
        runtimeLifecycleState = string(runtime["lifecycleState"]) ?? runtimeLifecycleState
        lifecycleState = isOperational ? "connected" : lifecycleState
    }

    private func authReady(from state: [String: Any]) -> Bool {
        guard let account = state["account"] as? [String: Any] else { return false }
        return !(string(account["accessToken"]) ?? "").isEmpty || !(string(account["refreshToken"]) ?? "").isEmpty
    }

    private func safeMessage(_ error: Error) -> String {
        if let localized = (error as? LocalizedError)?.errorDescription, !localized.isEmpty {
            return localized
        }
        return error.localizedDescription
    }
}

private extension RuntimeResponse {
    var resultMap: [String: Any] {
        result?.mapValues(\.value) ?? [:]
    }
}

private func string(_ value: Any?) -> String? {
    let text = String(describing: value ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    return text.isEmpty || text == "Optional(nil)" ? nil : text
}

private func bool(_ value: Any?) -> Bool {
    if let value = value as? Bool { return value }
    if let value = value as? NSNumber { return value.boolValue }
    return false
}
