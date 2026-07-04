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
    @Published var pairingClaimed = false
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
    }

    func start(initialSession: ElyanAuthSession? = nil) {
        Task {
            do {
                try bridge.startProcess()
                isRunning = true
                lifecycleState = "connecting"
                pendingAuthSession = initialSession
                pendingAuthSync = true
                _ = await flushPendingAuthSync()
                await refreshAll()
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
        pairingPollTask?.cancel()
        pairingPollTask = nil
        bridge.stopProcess()
        isRunning = false
        runtimeReady = false
        backendReady = false
        runtimeLifecycleState = ""
        lifecycleState = "stopped"
    }

    func syncAuthSession(_ session: ElyanAuthSession?) async {
        pendingAuthSession = session
        pendingAuthSync = true
        _ = await flushPendingAuthSync()
    }


    /// Fetches and directly executes any tasks the mobile app has dispatched
    /// to this desktop, then refreshes the local task inbox so the UI reflects
    /// the result immediately rather than waiting for the next tick.
    @discardableResult
    func executeAssignedTasks(limit: Int = 5) async -> Bool {
        guard isRunning else { return false }
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

    func createPairingSession() async {
        pairingPollTask?.cancel()
        pairingClaimed = false
        pairingCode = ""
        do {
            let response = try await bridge.request(capability: "pairing.create_session", payload: [:], timeoutSeconds: 30)
            // The bridge wraps the backend's BackendResult under "result", whose
            // own "data" field carries the actual pairing payload — not a
            // top-level "data" key on the response itself.
            let backendResult = response.resultMap["result"] as? [String: Any] ?? response.resultMap
            let data = backendResult["data"] as? [String: Any] ?? backendResult
            let code = string(data["manualEntryCode"]) ?? string(data["pairingCode"]) ?? ""
            let session = string(data["sessionId"]) ?? string(data["id"]) ?? ""
            pairingCode = code
            if response.ok, !code.isEmpty {
                pairingSummary = "Telefonunda bu kodu gir: \(code)"
            } else if response.ok {
                pairingSummary = "Eşleştirme oturumu hazır, kod bekleniyor."
            } else {
                pairingSummary = "Eşleştirme oturumu oluşturulamadı."
            }
            if response.ok, !session.isEmpty {
                startPairingClaimPoll(sessionId: session)
            }
        } catch {
            pairingSummary = safeMessage(error)
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
                        return
                    }
                    if status == "expired" || status == "canceled" {
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
