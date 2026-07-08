import Foundation
import SwiftUI
import AppKit
import Combine

@MainActor
final class AppState: ObservableObject {
    let backend: ElyanBackend
    let chat: ChatStore
    let supervisor: PythonRuntimeSupervisor

    /// Live view of tasks the mobile side has dispatched to this desktop.
    /// The sidebar chip + Task Inbox screen read this directly.
    @Published private(set) var assignedTasks: [ElyanRuntimeTask] = []
    @Published private(set) var lastDispatchError: String = ""

    private var dispatchWatchdogTask: Task<Void, Never>?
    private let realtimeClient = ElyanSSEClient()
    private var realtimeTask: Task<Void, Never>?
    private var realtimeResubscribeTask: Task<Void, Never>?
    private var wakeObserver: NSObjectProtocol?
    private var supervisorObservation: AnyCancellable?

    var pendingTaskCount: Int {
        assignedTasks.filter { !["completed", "failed", "canceled"].contains($0.status.lowercased()) }.count
    }

    init() {
        let backend = ElyanBackend()
        let supervisor = PythonRuntimeSupervisor()
        self.backend = backend
        self.chat = ChatStore(backend: backend)
        self.supervisor = supervisor
        // Jarvis yolu: komutlar önce yerel runtime'da yürütülür.
        self.chat.localSend = { [weak supervisor] text in
            guard let supervisor else { throw RuntimeBridgeSwiftError.runtimeNotStarted }
            return try await supervisor.sendLocalChat(text)
        }
        self.chat.onSessionActivated = { [weak supervisor] sessionId in
            supervisor?.setLocalConversation(sessionId)
        }
        supervisorObservation = supervisor.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }

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
            } catch ElyanBackendError.notAuthenticated {
                await backend.logout()
            } catch {
                // Geçici ağ/5xx hatası oturumu veya runtime kimliğini silmez.
                // Python runtime kendi bounded retry hattında yeniden dener.
                supervisor.lastError = (error as? LocalizedError)?.errorDescription
                    ?? error.localizedDescription
            }
        }

        // Runtime ayağa kalkar kalkmaz (boot veya crash-restart sonrası)
        // backend'de birikmiş görevleri hemen çek ve yürüt — ilk SSE
        // event'ini beklemek, uygulama kapalıyken mobilden gönderilmiş
        // görevleri süresiz askıda bırakıyordu.
        supervisor.onBecameOperational = { [weak self] in
            await self?.refreshAssignedTasks()
        }

        startDispatchWatchdogLoop()
        startRealtimeSubscription()

        // ElyanSSEClient gives up after 4 reconnect attempts (~12s of
        // exponential backoff) and calls onError once, permanently — nothing
        // previously called startRealtimeSubscription() again after that, so
        // a longer outage (or a stall the socket-level watchdog hasn't yet
        // caught) silently killed task/device/pairing notifications for the
        // rest of the app's life. Mac sleep/wake is the most common trigger;
        // resubscribe immediately on wake instead of waiting on the next
        // login/logout event.
        wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.startRealtimeSubscription()
                // Uyku sırasında birikmiş görevleri de hemen çek.
                await self?.refreshAssignedTasks()
            }
        }
    }

    deinit {
        if let wakeObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(wakeObserver)
        }
    }

    /// WebSocket/SSE kesintilerinde kuyrukta kalan görevleri bounded aralıkla
    /// Python RuntimeBridge üzerinden yeniden kontrol eder. Runtime kimliği,
    /// heartbeat ve lease sahipliği Swift'e taşınmaz.
    private func startDispatchWatchdogLoop() {
        dispatchWatchdogTask?.cancel()
        dispatchWatchdogTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                // Runtime register/heartbeat/task lease hattının tek sahibi
                // Python runtime'dır. Swift yalnız köprü snapshot'ını yeniler.
                await self.refreshAssignedTasks()
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
        realtimeResubscribeTask?.cancel()
        realtimeResubscribeTask = nil
        realtimeTask = Task { [weak self] in
            guard let self, let token = self.backend.session?.accessToken else { return }
            await self.realtimeClient.open(
                accessToken: token,
                taskId: nil,
                onEvent: { [weak self] event in
                    guard Self.isTaskRelevantEvent(event.event.lowercased()) else { return }
                    await self?.refreshAssignedTasks()
                },
                onError: { [weak self] _ in
                    // ElyanSSEClient already exhausted its own 4-attempt
                    // exponential backoff before calling this — it will NOT
                    // retry again on its own. Previously nothing happened
                    // here, so a single outage longer than ~12s permanently
                    // killed task/device/pairing notifications until the next
                    // login/logout. Schedule one longer-interval resubscribe
                    // instead of matching ElyanSSEClient's tight backoff, so
                    // a persistently-down network doesn't spin.
                    await self?.scheduleRealtimeResubscribe()
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

    /// Retries the realtime subscription once after a fixed delay following an
    /// exhausted ElyanSSEClient backoff. Coalesces with any already-pending
    /// retry so repeated errors in a short window don't stack up parallel
    /// resubscribe timers.
    private func scheduleRealtimeResubscribe() {
        guard realtimeResubscribeTask == nil else { return }
        realtimeResubscribeTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 20_000_000_000) // 20s
            guard let self, !Task.isCancelled else { return }
            self.realtimeResubscribeTask = nil
            self.startRealtimeSubscription()
        }
    }

    func refreshAssignedTasks() async {
        if supervisor.isOperational {
            _ = await supervisor.executeAssignedTasks()
        } else {
            await supervisor.refreshTaskInbox()
        }
        assignedTasks = supervisor.taskInbox.map(ElyanRuntimeTask.init(runtimeItem:))
        lastDispatchError = supervisor.isOperational
            ? supervisor.lastError
            : "Yerel çalışma motoru hazır olduğunda görev otomatik başlayacak."
    }
}
