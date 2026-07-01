import Foundation
import SwiftUI

@MainActor
final class AppState: ObservableObject {
    let backend: ElyanBackend
    let chat: ChatStore
    let supervisor: PythonRuntimeSupervisor

    /// Live view of tasks the mobile side has dispatched to this desktop.
    /// The sidebar chip + Task Inbox screen read this directly.
    @Published private(set) var assignedTasks: [ElyanRuntimeTask] = []
    @Published private(set) var lastDispatchError: String = ""

    private var heartbeatTask: Task<Void, Never>?
    private var dispatchPollTask: Task<Void, Never>?

    var pendingTaskCount: Int {
        assignedTasks.filter { !["completed", "failed", "canceled"].contains($0.status.lowercased()) }.count
    }

    init() {
        let backend = ElyanBackend()
        let supervisor = PythonRuntimeSupervisor()
        self.backend = backend
        self.chat = ChatStore(backend: backend)
        self.supervisor = supervisor

        // Bring back the runtime token from the previous launch so mobile
        // sees this Mac as online immediately, not only after the next
        // manual pairing.
        backend.restoreRuntimeToken()

        backend.onSessionChanged = { session in
            Task { @MainActor in
                await supervisor.syncAuthSession(session)
            }
        }

        startRuntimeHeartbeatLoop()
        startDispatchPollLoop()
    }

    /// Fires an online heartbeat every 25s. The backend flips a paired
    /// desktop to "offline" if it hasn't heard from it recently, so this loop
    /// keeps mobile's device chip green as long as the app is running.
    private func startRuntimeHeartbeatLoop() {
        heartbeatTask?.cancel()
        heartbeatTask = Task { [backend] in
            while !Task.isCancelled {
                await backend.runtimeHeartbeat(status: "online")
                try? await Task.sleep(nanoseconds: 25_000_000_000)
            }
        }
    }

    /// Polls mobile-dispatched tasks every 10s and immediately reports back
    /// "accepted" for anything we haven't seen yet, so the mobile UI moves
    /// out of "queued" the moment the desktop picks the task up. Actual
    /// capability execution is not implemented on the native app yet; the
    /// user completes/fails tasks manually from the inbox.
    private func startDispatchPollLoop() {
        dispatchPollTask?.cancel()
        dispatchPollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refreshAssignedTasks()
                try? await Task.sleep(nanoseconds: 10_000_000_000)
            }
        }
    }

    func refreshAssignedTasks() async {
        do {
            let fresh = try await backend.getAssignedRuntimeTasks()
            let previouslyKnown = Set(assignedTasks.map(\.id))
            assignedTasks = fresh
            lastDispatchError = ""

            // Auto-ack newly seen queued tasks so mobile's spinner advances
            // to "kabul edildi / işleniyor" instead of stalling on "sırada".
            for task in fresh where !previouslyKnown.contains(task.id) {
                if task.status.lowercased() == "queued" {
                    _ = try? await backend.updateRuntimeTaskStatus(
                        taskId: task.id,
                        status: "running",
                        message: "Elyan Mac görevi aldı"
                    )
                }
            }
        } catch {
            lastDispatchError = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    /// Called by the Task Inbox UI when the user marks a task done or
    /// declines it. Wraps the raw API call and refreshes the list so the
    /// row disappears immediately.
    func resolveTask(_ task: ElyanRuntimeTask, completed: Bool, message: String? = nil) async {
        _ = try? await backend.updateRuntimeTaskStatus(
            taskId: task.id,
            status: completed ? "completed" : "failed",
            message: message,
            error: completed ? nil : (message ?? "Kullanıcı tamamlanmadı olarak işaretledi.")
        )
        await refreshAssignedTasks()
    }
}
