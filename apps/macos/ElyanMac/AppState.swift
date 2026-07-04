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
    private let realtimeClient = ElyanSSEClient()
    private var realtimeTask: Task<Void, Never>?

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

        backend.onSessionChanged = { [weak self] session in
            Task { @MainActor in
                guard let self else { return }
                await self.supervisor.syncAuthSession(session)
                self.startRealtimeSubscription()
            }
        }

        supervisor.onAuthRefreshNeeded = { [weak backend, weak supervisor] in
            guard let backend, let supervisor else { return }
            do {
                _ = try await backend.refresh()
                await supervisor.syncAuthSession(backend.session)
            } catch {
                await backend.logout()
            }
        }

        startRuntimeHeartbeatLoop()
        startRealtimeSubscription()
    }

    /// Fires an online heartbeat every 25s — ama YALNIZ Python runtime
    /// çalışmıyorken. Runtime operasyonelken kendi kayıt/heartbeat/WS hattı
    /// cihaz varlığının tek sahibidir; buradaki ikinci HTTP heartbeat ayrı bir
    /// runtime bağlantısı gibi görünüp backend'in task lease dağıtımını
    /// şaşırtıyordu (görevlerin mobilde "sırada" takılı kalmasının bir nedeni).
    /// Swift HTTP heartbeat sadece degraded fallback'te devrede kalır ki
    /// Python başlatılamasa bile cihaz çevrimdışı görünmesin.
    private func startRuntimeHeartbeatLoop() {
        heartbeatTask?.cancel()
        heartbeatTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                if !self.supervisor.isOperational {
                    await self.backend.runtimeHeartbeat(status: "online")
                }
                try? await Task.sleep(nanoseconds: 25_000_000_000)
            }
        }
    }

    /// Subscribes to the backend's realtime SSE stream to get notified of newly
    /// dispatched tasks immediately, instead of polling every 10 seconds.
    ///
    /// KRİTİK: taskId'siz açılan bu akış backend'in `user:<userId>` kanalına
    /// bağlanır — bu kanal, aktif bir chat task'ının `task:<taskId>` kanalıyla
    /// BİRLİKTE her `message.delta`'sını da alır (event-bus.ts channelsFor()
    /// her event'i userId VE taskId varsa ikisine birden fan-out ediyor; bu
    /// backend tasarımı kasıtlı — mobile de aynı geniş kanalı device/pairing
    /// bildirimleri için kullanıyor). Mobile bunu event tipine göre filtreleyip
    /// yalnız task/command/runtime/device/pairing olaylarında liste yeniliyor
    /// (realtime_controller.dart); burada bu filtre YOKTU — her chat delta'sında
    /// (streaming sırasında saniyede ~30 kez) tam bir REST round-trip
    /// tetikleniyordu. Bu, "chat yüzeyi ağır donuyor" şikayetinin en büyük
    /// kaynağıydı: render maliyetinden bağımsız, ağ+ana thread üzerinde saniyede
    /// onlarca gereksiz istek. Mobile'daki AYNI filtre burada da uygulanıyor.
    private func startRealtimeSubscription() {
        realtimeTask?.cancel()
        realtimeTask = Task { [weak self] in
            guard let self, let token = self.backend.session?.accessToken else { return }
            await self.realtimeClient.open(
                accessToken: token,
                taskId: nil,
                onEvent: { [weak self] event in
                    guard Self.isTaskRelevantEvent(event.event.lowercased()) else { return }
                    await self?.refreshAssignedTasks()
                },
                onError: { _ in
                    // If it errors, we can just let it backoff/retry which is handled inside ElyanSSEClient
                },
                onClose: {
                }
            )
        }
    }

    /// Mobile'ın realtime_controller.dart'ıyla aynı sınıflandırma: yalnız
    /// görev/cihaz/eşleştirme yaşam döngüsü olayları — chat/message/block
    /// olayları kasıtlı olarak dışarıda (onlar ChatStore'un kendi task-scoped
    /// akışının işi).
    nonisolated private static func isTaskRelevantEvent(_ type: String) -> Bool {
        type.hasPrefix("task.")
            || type.hasPrefix("command.")
            || type.hasPrefix("runtime.")
            || type == "device.status_changed"
            || type == "pairing.claimed"
    }

    func refreshAssignedTasks() async {
        do {
            let fresh = try await backend.getAssignedRuntimeTasks()
            let previouslyKnown = Set(assignedTasks.map(\.id))
            assignedTasks = fresh
            lastDispatchError = ""

            let newQueued = fresh.filter {
                !previouslyKnown.contains($0.id) && $0.status.lowercased() == "queued"
            }
            guard !newQueued.isEmpty else { return }

            if supervisor.isOperational {
                // Görev yürütmenin tek sahibi Python runtime'dır (AGENTS.md
                // sınırı). Buradan ayrıca "running" ack'lemek, runtime'ın kendi
                // lease/ack akışıyla çakışıp görevleri iki durum arasında
                // sıkıştırıyordu. Yeni görev görüldüğünde bir sonraki 3sn poll
                // tick'ini beklemeden yürütmeyi hemen tetikle.
                await supervisor.executeAssignedTasks()
            } else {
                // Degraded fallback: runtime yoksa mobil spinner'ı "sırada"da
                // bırakma — manuel inbox akışı için kabul et.
                for task in newQueued {
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
