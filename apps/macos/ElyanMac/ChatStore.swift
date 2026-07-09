import Foundation
import SwiftUI

// MARK: - ChatMessage

/// A single step in a multi-step plan awaiting user approval.
struct PlanStep: Identifiable, Equatable {
    let id = UUID()
    let description: String
    let capability: String
}

/// A plan the local runtime produced that needs the user's confirmation before
/// it executes (side-effecting or multi-step). Rendered as an inline card with
/// Onayla / İptal actions; on approval the runtime runs the steps on the desktop.
struct PendingPlan: Equatable {
    let pendingPlanId: String
    let conversationId: String
    let summary: String
    let steps: [PlanStep]
    /// True while the confirm/cancel round-trip is in flight (disables buttons).
    var isConfirming: Bool = false
}

/// A permission wall the runtime hit while trying to run a command. Rendered as
/// an inline card with one-tap grant actions so the user never has to hunt
/// through Settings. `originalText` is re-run automatically once granted.
struct PermissionRequest: Equatable {
    let reason: String
    /// Elyan's own toggle (e.g. "allow_computer_control") — granted in-app.
    let permissionKey: String
    let canGrantPersistently: Bool
    /// macOS TCC permission (e.g. "accessibility", "screenRecording") — opened
    /// in System Settings; the user flips it there.
    let systemPermissionKey: String
    let systemPermissionRequired: Bool
    let originalText: String
    var isGranting: Bool = false
}

struct ChatMessage: Identifiable {
    enum Role: String, Equatable { case user, assistant }
    let id = UUID()
    let role: Role
    var text: String
    var blocks: [ChatBlock]
    let timestamp: Date
    /// Non-nil when this assistant message carries a plan awaiting approval.
    var plan: PendingPlan?
    /// Non-nil when this assistant message is a permission request.
    var permission: PermissionRequest?
    /// Non-nil only for messages loaded from session history whose backend
    /// status wasn't a terminal "completed" (queued/running/waiting_approval/
    /// failed/canceled) — nil for live/local messages so the normal streaming
    /// path (which already has its own "Düşünüyor…" indicator) is untouched.
    var historyStatus: String?
    var historyError: String?
    /// Yerinde blok mutasyonlarının (canlı checklist adım güncellemesi,
    /// finalizeChecklist) sayacı. `==` blocks.count'u vekil kullanır; aynı
    /// blok üzerine yazıldığında sayı değişmediği için .equatable() yeniden
    /// çizimi atlıyordu — spinner runtime "tamamlandı" dese de ekranda sonsuza
    /// dek dönüyordu. Her yerinde blok güncellemesi bu sayacı artırmalı.
    var revision: Int = 0

    init(
        role: Role, text: String, blocks: [ChatBlock] = [], timestamp: Date = Date(),
        plan: PendingPlan? = nil, permission: PermissionRequest? = nil,
        historyStatus: String? = nil, historyError: String? = nil
    ) {
        self.role = role
        self.text = text
        self.blocks = blocks
        self.timestamp = timestamp
        self.plan = plan
        self.permission = permission
        self.historyStatus = historyStatus
        self.historyError = historyError
    }

    var isHistoryPending: Bool {
        guard let historyStatus else { return false }
        return ["queued", "running", "waiting_approval"].contains(historyStatus.lowercased())
    }
    var isHistoryFailed: Bool {
        guard let historyStatus else { return false }
        return ["failed", "canceled"].contains(historyStatus.lowercased())
    }
}

extension ChatMessage: Equatable {
    // Anlamlı eşitlik: SwiftUI'nin değişmeyen baloncukları atlayabilmesi için
    // içerik de karşılaştırılır (salt id karşılaştırması, streaming'de tüm
    // satırların "değişmedi" sayılıp yine de body'lerinin koşmasına ya da
    // .equatable() kullanımında hiç güncellenmemesine yol açıyordu).
    // blocks.count ucuz bir vekildir: blok içeriği değişimlerine pratikte hep
    // text fallback değişimi eşlik eder.
    static func == (lhs: ChatMessage, rhs: ChatMessage) -> Bool {
        lhs.id == rhs.id
            && lhs.text == rhs.text
            && lhs.blocks.count == rhs.blocks.count
            && lhs.revision == rhs.revision
            && lhs.plan == rhs.plan
            && lhs.permission == rhs.permission
            && lhs.historyStatus == rhs.historyStatus
    }
}

// MARK: - ChatStore

/// Owns the live conversation: sends user messages, subscribes to SSE deltas,
/// manages session pagination, and uses ElyanCache for instant transitions
/// between sessions (stale-while-revalidate pattern).
@MainActor
final class ChatStore: ObservableObject {

    @Published private(set) var messages: [ChatMessage] = []
    @Published private(set) var isStreaming = false
    @Published private(set) var isLoadingSession = false
    @Published private(set) var isLoadingMore = false
    @Published private(set) var hasMoreMessages = false
    @Published private(set) var isStale = false   // showing cached data, refresh in progress
    @Published private(set) var sessionId: String?
    @Published var lastError: String = ""

    private var nextCursor: String?
    private let backend: ElyanBackend
    private let cache: ElyanCache = .shared
    private let sseClient = ElyanSSEClient()
    private var streamingAssistantId: UUID?
    private var prefetchTasks: [String: Task<Void, Never>] = [:]

    // Kalıcı realtime kanalı: eskiden HER send() yeni bir per-task SSE
    // bağlantısı açıyordu (POST döndükten SONRA) — her mesajda tam bir
    // TLS+HTTP el sıkışması (yüzlerce ms) ve subscribe tamamlanmadan yayınlanan
    // ilk delta'ların kaçması demekti. "Mesaj çok yavaş gidiyor/geliyor"
    // şikayetinin ana bileşeni buydu. Artık TEK user-channel stream'i açık
    // tutuyoruz (backend user:<userId> kanalı task event'lerini de fan-out
    // eder — AppState'in realtime aboneliğiyle aynı sözleşme) ve gelen
    // event'leri taskId/sessionId ile aktif akışa eşliyoruz.
    private var realtimeOpen = false
    private var currentTaskId: String?
    private var realtimeReopenTask: Task<Void, Never>?

    // Delta birleştirme: her SSE chunk'ında `messages` dizisini mutasyona
    // uğratmak @Published'ı saniyede onlarca kez tetikliyor ve TÜM sohbet
    // listesi (markdown parse dahil) yeniden değerlendiriliyordu — "chat
    // arayüzü kasıyor" şikayetinin ana kaynağı. Gelen delta/bloklar burada
    // birikir, ~33ms'de bir tek seferde uygulanır (mobildeki 16ms flush'ın
    // masaüstü karşılığı).
    private var pendingDeltaText = ""
    private var pendingBlocks: [ChatBlock]?
    private var deltaFlushTask: Task<Void, Never>?

    init(backend: ElyanBackend) {
        self.backend = backend
    }

    // MARK: - Reset

    func reset() {
        // Logout / tam sıfırlama: kalıcı kanal da kapanır (token değişecek).
        Task { await sseClient.cancel() }
        realtimeOpen = false
        realtimeReopenTask?.cancel()
        realtimeReopenTask = nil
        currentTaskId = nil
        deltaFlushTask?.cancel()
        deltaFlushTask = nil
        pendingDeltaText = ""
        pendingBlocks = nil
        messages.removeAll()
        streamingAssistantId = nil
        isStreaming = false
        sessionId = nil
        onSessionActivated?("")
        lastError = ""
        hasMoreMessages = false
        nextCursor = nil
        isLoadingMore = false
        isLoadingSession = false
        isStale = false
    }

    // MARK: - Load Session (stale-while-revalidate)

    func loadSession(_ id: String) async {
        let trimmed = id.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // A message just sent from a brand-new (sessionId == nil) chat gets
        // its session id back from the backend mid-flight and publishes it
        // via `sessionId = sid` — which some callers (or a future/careless
        // caller) could react to by calling loadSession(sid) on the very
        // session whose reply is actively streaming right now. Before this
        // guard, that would cancel the live SSE subscription, wipe the
        // optimistic bubble (`messages.removeAll()` below, since a brand-new
        // session has no cache yet), and reissue a REST fetch that might
        // still race the backend's own write — exactly the "message vanished
        // until it showed up in the sidebar and I clicked it" symptom.
        // There's nothing to "load": we already hold the freshest possible
        // state locally.
        if trimmed == sessionId, isStreaming {
            return
        }

        // Kanalı session açılırken ısıt — kullanıcı ilk mesajını yazana kadar
        // bağlantı çoktan kurulmuş olur.
        ensureRealtimeOpen()

        // Kalıcı kanal AÇIK KALIR (user-scoped, session'a bağlı değil) —
        // yalnız bu session'a ait canlı akış state'i sıfırlanır. Başka bir
        // session'ın yarım akışından gelebilecek geç delta'lar currentTaskId
        // temizlendiği için eşleşmeyip düşer.
        deltaFlushTask?.cancel()
        deltaFlushTask = nil
        pendingDeltaText = ""
        pendingBlocks = nil
        streamingAssistantId = nil
        currentTaskId = nil
        isStreaming = false
        lastError = ""
        sessionId = trimmed
        onSessionActivated?(trimmed)

        // 1. Show cache immediately (zero-latency perceived switch)
        if let (cached, isExpired) = cache.messagePage(sessionId: trimmed, cursor: nil) {
            applyPage(cached, prepend: false)
            isStale = isExpired  // if stale, we'll refresh in background
            if !isExpired { return }   // fresh cache → no network needed
        } else {
            // No cache at all → show loading indicator
            messages.removeAll()
            hasMoreMessages = false
            nextCursor = nil
            isLoadingSession = true
            isStale = false
        }

        // 2. Fetch from network (always after showing cached)
        defer { isLoadingSession = false; isStale = false }
        do {
            let result = try await backend.getSessionMessages(
                sessionId: trimmed, limit: 30, cursor: nil, forceRefresh: false
            )
            let page = CachedMessagePage(
                messages: result.messages,
                hasMore: result.hasMore,
                nextCursor: result.nextCursor
            )
            cache.storeMessagePage(page, sessionId: trimmed, cursor: nil)

            // Only replace UI if we're still looking at this session
            if sessionId == trimmed {
                applyPage(page, prepend: false)
            }
        } catch {
            if messages.isEmpty {
                lastError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            // If cache was shown, suppress error silently — user already sees data
        }
    }

    // MARK: - Prefetch (triggered by hover/focus in sidebar)

    func prefetchSession(_ id: String) {
        let trimmed = id.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed != sessionId else { return }

        // Already cached and fresh?
        if let (_, isExpired) = cache.messagePage(sessionId: trimmed, cursor: nil), !isExpired {
            return
        }

        // Already prefetching?
        if prefetchTasks[trimmed] != nil { return }

        prefetchTasks[trimmed] = Task { [weak self] in
            guard let self else { return }
            do {
                let result = try await backend.getSessionMessages(
                    sessionId: trimmed, limit: 30, cursor: nil, forceRefresh: false
                )
                let page = CachedMessagePage(
                    messages: result.messages,
                    hasMore: result.hasMore,
                    nextCursor: result.nextCursor
                )
                cache.storeMessagePage(page, sessionId: trimmed, cursor: nil)
            } catch {
                // Prefetch failures are silent
            }
            prefetchTasks.removeValue(forKey: trimmed)
        }
    }

    // MARK: - Load More (pagination)

    func loadMoreMessages() async {
        guard let id = sessionId,
              hasMoreMessages,
              !isLoadingMore,
              !isLoadingSession else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }

        // Check cursor-page cache first
        if let (cached, isExpired) = cache.messagePage(sessionId: id, cursor: nextCursor) {
            let topId = messages.first?.id
            applyPage(cached, prepend: true)
            _ = topId  // can be used to restore scroll position
            if !isExpired { return }
        }

        do {
            let result = try await backend.getSessionMessages(
                sessionId: id, limit: 30, cursor: nextCursor, forceRefresh: false
            )
            let page = CachedMessagePage(
                messages: result.messages,
                hasMore: result.hasMore,
                nextCursor: result.nextCursor
            )
            cache.storeMessagePage(page, sessionId: id, cursor: nextCursor)
            if sessionId == id {
                applyPage(page, prepend: true)
            }
        } catch {
            // Pagination failures: silent (user already sees earlier messages)
            print("[ElyanChat] loadMore failed: \(error)")
        }
    }

    // MARK: - Apply page helper

    private func applyPage(_ page: CachedMessagePage, prepend: Bool) {
        let mapped = page.messages.compactMap { m -> ChatMessage? in
            let role: ChatMessage.Role
            switch m.role.lowercased() {
            case "user": role = .user
            case "assistant", "elyan", "system": role = .assistant
            default: return nil
            }
            let isTerminalCompleted = m.status.lowercased() == "completed"
            return ChatMessage(
                role: role, text: m.text, blocks: m.blocks, timestamp: m.createdAt,
                historyStatus: isTerminalCompleted ? nil : m.status,
                historyError: m.errorMessage
            )
        }
        if prepend {
            messages.insert(contentsOf: mapped, at: 0)
            nextCursor = page.nextCursor
            hasMoreMessages = page.hasMore
        } else {
            messages = mapped
            nextCursor = page.nextCursor
            hasMoreMessages = page.hasMore
        }
    }

    // MARK: - Send message

    func send(_ prompt: String) async {
        let trimmed = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        let userMsg = ChatMessage(role: .user, text: trimmed)
        messages.append(userMsg)
        let placeholder = ChatMessage(role: .assistant, text: "")
        messages.append(placeholder)
        streamingAssistantId = placeholder.id
        isStreaming = true
        lastError = ""

        // Optimistic baloncuğun ağ/işlem çağrısından ÖNCE çizilmesini garantiler.
        await Task.yield()

        // ── SAF YEREL OTOMASYON — bulut/LLM/SSE yolu TAMAMEN kaldırıldı ──────
        // Dış bağımlılık yok: komut yalnız deterministik router + gerçek
        // araçlarla masaüstünde çalışır. Bridge düşükse önce toparlanır; hâlâ
        // yanıt veremezse GERÇEK neden gösterilir (eskiden buluta düşüp boş
        // dönerek "Yanıt gelmedi" maskeliyordu — o sınıf hata artık imkânsız).
        guard let localSend else {
            finishLocal(text: "Masaüstü motoru bağlı değil. Uygulamayı yeniden başlat.")
            return
        }

        if let localRecover {
            _ = await localRecover()
        }

        do {
            let reply = try await localSend(trimmed)
            completeStreaming(withLocalReply: reply)
        } catch is RuntimeBridgeSwiftError {
            // Toparlama denendi ama süreç hâlâ ayakta değil — gerçek durumu ver.
            let diag = localStatus?() ?? ""
            let suffix = diag.isEmpty ? "" : "\n(durum: \(diag))"
            finishLocal(text: "Masaüstü motoru başlatılamadı. Birkaç saniye sonra tekrar dene.\(suffix)")
        } catch {
            let base = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            finishLocal(text: "Komut tamamlanamadı: \(base)")
        }
    }

    /// Yerel-yalnız akışta placeholder baloncuğu net bir metinle doldurur ve
    /// streaming durumunu kapatır (SSE yok; bulut maskeleme yok).
    private func finishLocal(text: String) {
        if let id = streamingAssistantId,
           let idx = messages.firstIndex(where: { $0.id == id }) {
            finalizeChecklist(inMessageId: id, success: false)
            if messages[idx].blocks.isEmpty {
                messages[idx].text = text
            } else {
                messages[idx].blocks.append(.text(TextBlock(stableBlockId: nil, markdown: text)))
                messages[idx].revision += 1
            }
        }
        isStreaming = false
        streamingAssistantId = nil
        currentTaskId = nil
    }

    /// AppState tarafından bağlanır: komutu yerel Python runtime'ında koşturur.
    var localSend: ((String) async throws -> PythonRuntimeSupervisor.LocalChatReply)?

    /// Bridge süreci düşükse toparlamayı dener (restart + canlı olana kadar
    /// bekle). true dönerse `localSend` yeniden denenebilir. AppState bağlar.
    var localRecover: (() async -> Bool)?

    /// Masaüstü motorunun anlık tanı metni (lifecycle + son hata). Bridge
    /// başlatılamadığında GERÇEK nedeni chat'te göstermek için. AppState bağlar.
    var localStatus: (() -> String)?

    /// Canlı checklist'i barındıran aktif asistan mesajı (plan yürütme sırasında).
    /// Executor progress event'leri conversation_id taşımadığı için hedef budur.
    private var progressHostId: UUID?

    /// Executor adım event'ini (task_trace bloğu) aktif mesaja iliştirir/günceller.
    /// Aynı stableBlockId'li blok varsa üzerine yazar → checklist canlı tik atar.
    func applyProgressBlock(conversationId: String, block: [String: Any]) {
        guard let parsed = ChatBlock.parse(from: block) else { return }
        let targetId = progressHostId ?? streamingAssistantId
        guard let id = targetId,
              let idx = messages.firstIndex(where: { $0.id == id }) else { return }
        if let existing = messages[idx].blocks.firstIndex(where: { $0.id == parsed.id }) {
            messages[idx].blocks[existing] = parsed
        } else {
            messages[idx].blocks.append(parsed)
        }
        messages[idx].revision += 1
    }

    /// Yürütme çözüldüğünde checklist'i DETERMİNİSTİK sonlandırır: kalan
    /// running/pending adımları kapatır, overall status'u set eder. Final
    /// progress event'i yarışta kaybolsa bile spinner asla takılı kalmaz.
    private func finalizeChecklist(inMessageId id: UUID, success: Bool) {
        guard let idx = messages.firstIndex(where: { $0.id == id }) else { return }
        for bIdx in messages[idx].blocks.indices {
            guard case .taskTrace(var trace) = messages[idx].blocks[bIdx] else { continue }
            for i in trace.steps.indices {
                switch trace.steps[i].status {
                case .running:
                    trace.steps[i].status = success ? .completed : .failed
                case .pending where success:
                    trace.steps[i].status = .completed
                default:
                    break
                }
            }
            trace.status = success ? .completed : .failed
            messages[idx].blocks[bIdx] = .taskTrace(trace)
        }
        messages[idx].revision += 1
    }

    /// Aktif oturum değiştiğinde (yeni sohbet = boş kimlik) yerel runtime'ın
    /// konuşma bağlamını senkron tutmak için AppState tarafından bağlanır.
    var onSessionActivated: ((String) -> Void)?

    private func completeStreaming(withLocalReply reply: PythonRuntimeSupervisor.LocalChatReply) {
        drainPendingStream()
        if let id = streamingAssistantId,
           let idx = messages.firstIndex(where: { $0.id == id }) {
            // Doğrudan send() yolunda da (onay kartsız yürütme) biriken canlı
            // checklist deterministik kapanır — final progress event'i yarışta
            // kaybolsa bile spinner takılı kalmaz (confirmPlan'daki kuralın aynısı).
            finalizeChecklist(inMessageId: id, success: true)
            let finalText = reply.text.trimmingCharacters(in: .whitespacesAndNewlines)
            if messages[idx].blocks.isEmpty {
                messages[idx].text = reply.text
            } else if !finalText.isEmpty {
                // Render block-first: blok varken .text çizilmez; final metin
                // text bloğu olarak eklenmezse kullanıcı sonucu hiç göremez.
                messages[idx].blocks.append(.text(TextBlock(stableBlockId: nil, markdown: finalText)))
                messages[idx].revision += 1
            }
            messages[idx].plan = reply.plan
            messages[idx].permission = reply.permission
        }
        isStreaming = false
        streamingAssistantId = nil
        currentTaskId = nil
    }

    /// Bağlanır: Elyan izin anahtarını açar (state.update).
    var localGrantPermission: ((_ key: String) async -> Bool)?
    /// Bağlanır: macOS sistem izin panelini doğru bölmede açar.
    var localOpenSystemPermission: ((_ systemKey: String) async -> Void)?

    /// Kullanıcı izin kartında "İzin Ver"e bastığında: Elyan toggle'ını açar ve
    /// başarılıysa orijinal komutu otomatik yeniden çalıştırır (kullanıcı tekrar
    /// yazmak zorunda kalmaz). Sistem izni gerekiyorsa ilgili paneli açar.
    func grantPermission(messageId: UUID) async {
        guard let idx = messages.firstIndex(where: { $0.id == messageId }),
              let permission = messages[idx].permission else { return }
        messages[idx].permission?.isGranting = true

        // Elyan'ın kendi izin kümesini aç (operatörde tüm set birlikte açılır).
        var granted = false
        if !permission.permissionKey.isEmpty, let localGrantPermission {
            granted = await localGrantPermission(permission.permissionKey)
        }

        // Kartı temizle.
        if let i = messages.firstIndex(where: { $0.id == messageId }) {
            messages[i].permission = nil
        }

        guard granted, !permission.originalText.isEmpty else {
            if !granted {
                messages.append(ChatMessage(role: .assistant, text: "İzin verilemedi. Lütfen tekrar dene veya Ayarlar’dan elle aç."))
            }
            return
        }

        // Elyan izni açıldı → komutu HEMEN otomatik yeniden çalıştır. macOS sistem
        // izni (Erişilebilirlik/Ekran Kaydı) zaten verilmişse iş biter; verilmemişse
        // yeni yanıt taze bir izin kartı getirir (o da tek tıkla panele yönlendirir).
        await send(permission.originalText)
    }

    /// Sistem izin anahtarını okunur panel adına çevirir.
    static func systemPaneName(_ key: String) -> String {
        switch key {
        case "accessibility": return "Erişilebilirlik"
        case "screenRecording": return "Ekran Kaydı"
        case "inputMonitoring": return "Girdi İzleme"
        case "automation": return "Otomasyon"
        default: return "Gizlilik ve Güvenlik"
        }
    }

    /// Kullanıcı "Sistem Ayarları'nı Aç"a bastığında.
    func openSystemPermission(messageId: UUID) async {
        guard let idx = messages.firstIndex(where: { $0.id == messageId }),
              let permission = messages[idx].permission else { return }
        await localOpenSystemPermission?(permission.systemPermissionKey)
    }

    /// Bağlanır: onay bekleyen bir planı yerel runtime'da onaylar/iptal eder.
    var localConfirmPlan: ((_ conversationId: String, _ pendingPlanId: String, _ approved: Bool) async throws -> PythonRuntimeSupervisor.LocalChatReply)?

    /// Kullanıcı bir plan kartında "Onayla"/"İptal"e bastığında çağrılır. Plan
    /// mesajının kartını "onaylanıyor" durumuna alır, runtime sonucunu bekler ve
    /// sonucu yeni bir asistan baloncuğu olarak ekler; kart kaybolur.
    func confirmPlan(messageId: UUID, approved: Bool) async {
        guard let idx = messages.firstIndex(where: { $0.id == messageId }),
              let plan = messages[idx].plan,
              let localConfirmPlan else { return }
        messages[idx].plan?.isConfirming = true
        // Onay sırasında CANLI baloncuk: executor adım event'leri buraya
        // task_trace (checklist) bloğu olarak akar; sonuç da aynı baloncuğa yerleşir.
        let liveHost = ChatMessage(role: .assistant, text: "")
        messages.append(liveHost)
        progressHostId = liveHost.id
        defer { progressHostId = nil }
        do {
            let reply = try await localConfirmPlan(plan.conversationId, plan.pendingPlanId, approved)
            // Kartı temizle (plan çözüldü).
            if let i = messages.firstIndex(where: { $0.id == messageId }) {
                messages[i].plan = nil
            }
            // Checklist'i deterministik tamamla (spinner takılı kalmaz).
            finalizeChecklist(inMessageId: liveHost.id, success: true)
            // Canlı baloncuğu sonuçla doldur; biriken checklist bloğu (tamamlandı
            // durumunda) korunur. Render block-first olduğu için, checklist varsa
            // final metni bir text bloğu olarak eklenir (yoksa düz text gösterilir).
            if let hostIdx = messages.firstIndex(where: { $0.id == liveHost.id }) {
                messages[hostIdx].plan = reply.plan
                messages[hostIdx].permission = reply.permission
                let finalText = reply.text.trimmingCharacters(in: .whitespacesAndNewlines)
                if !finalText.isEmpty {
                    if messages[hostIdx].blocks.isEmpty {
                        messages[hostIdx].text = finalText
                    } else {
                        messages[hostIdx].blocks.append(.text(TextBlock(stableBlockId: nil, markdown: finalText)))
                    }
                }
            } else {
                messages.append(
                    ChatMessage(role: .assistant, text: reply.text, plan: reply.plan, permission: reply.permission)
                )
            }
        } catch {
            // Onay başarısız — kartı geri getir ki kullanıcı tekrar deneyebilsin.
            if let i = messages.firstIndex(where: { $0.id == messageId }) {
                messages[i].plan?.isConfirming = false
            }
            let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            lastError = msg
            finalizeChecklist(inMessageId: liveHost.id, success: false)
            if let hostIdx = messages.firstIndex(where: { $0.id == liveHost.id }) {
                let note = "İşlem tamamlanamadı: \(msg)"
                if messages[hostIdx].blocks.isEmpty {
                    messages[hostIdx].text = note
                } else {
                    messages[hostIdx].blocks.append(.text(TextBlock(stableBlockId: nil, markdown: note)))
                }
            }
        }
    }

    // MARK: - Realtime channel (persistent, user-scoped)

    /// Kalıcı user-channel SSE'yi (idempotent) açar. send()'ler arasında açık
    /// kalır; bağlantı düşerse ElyanSSEClient kendi içinde Last-Event-ID
    /// replay'li 4 deneme yapar, o da tükenirse burada gecikmeli yeniden
    /// açılır.
    func ensureRealtimeOpen() {
        guard !realtimeOpen else { return }
        guard let token = backend.session?.accessToken, !token.isEmpty else { return }
        realtimeOpen = true
        realtimeReopenTask?.cancel()
        realtimeReopenTask = nil
        Task { [weak self] in
            await self?.sseClient.open(
                accessToken: token,
                taskId: nil,
                onEvent: { [weak self] event in await self?.handle(event: event) },
                onError: { [weak self] error in await self?.realtimeDidFail(error) },
                onClose: { [weak self] in await self?.realtimeDidClose() }
            )
        }
    }

    /// 4 iç deneme de tükendi — aktif akış varsa kullanıcıya söyle, kanalı
    /// bir süre sonra yeniden kurmayı dene.
    private func realtimeDidFail(_ error: Error) async {
        realtimeOpen = false
        if isStreaming {
            await finishStreaming(withFailure: error)
        }
        scheduleRealtimeReopen(afterSeconds: 15)
    }

    /// Sunucu kanalı kapattı (idle timeout, deploy, ağ) — aktif akış yarıda
    /// kaldıysa eski davranışla sonlandır, kanalı kısa gecikmeyle yeniden aç.
    private func realtimeDidClose() async {
        realtimeOpen = false
        if isStreaming {
            await streamDidClose()
        }
        scheduleRealtimeReopen(afterSeconds: 2)
    }

    private func scheduleRealtimeReopen(afterSeconds seconds: Double) {
        guard realtimeReopenTask == nil else { return }
        realtimeReopenTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            guard let self, !Task.isCancelled else { return }
            self.realtimeReopenTask = nil
            self.ensureRealtimeOpen()
        }
    }

    /// User-channel'dan gelen event bu store'un aktif akışına mı ait?
    /// Aynı kullanıcının MOBİLDE başlattığı eşzamanlı bir task'ın delta'ları
    /// da bu kanala düşer — taskId (birincil) / sessionId (ikincil) eşleşmesi
    /// olmadan hiçbir içerik uygulanmaz. Routing bilgisi hiç yoksa yalnız
    /// aktif streaming sırasında kabul edilir (eski per-task davranışın
    /// dengi).
    private func matchesCurrentStream(_ data: [String: Any]) -> Bool {
        let routing = Self.extractRouting(from: data)
        if let tid = routing.taskId, !tid.isEmpty {
            return tid == currentTaskId
        }
        if let sid = routing.sessionId, !sid.isEmpty {
            return sid == sessionId
        }
        return isStreaming
    }

    private func handle(event: ElyanSSEEvent) async {
        switch event.event {
        case "chat.message.delta":
            guard matchesCurrentStream(event.data) else { return }
            let (text, blocks) = Self.extractContent(from: event.data)
            // Delta ve blocks AYNI event'te gelebilir (ör. ack: delta metni +
            // task-trace blokları). İkisini de uygula — eskiden `else if` biri
            // atlanıyordu.
            if !blocks.isEmpty { applyAssistantBlocks(blocks) }
            if !text.isEmpty, !Self.isTaskTraceOnlySnapshot(blocks) { appendDelta(text) }
        case "chat.message.updated":
            guard matchesCurrentStream(event.data) else { return }
            let (text, blocks) = Self.extractContent(from: event.data)
            replaceAssistant(text: text, blocks: Self.removingTaskTraceBlocks(from: blocks))
            finishStreamingSuccessfully()
        case "chat.heartbeat", "chat.message.created":
            break
        default:
            // Task/device/pairing yaşam döngüsü event'leri AppState'in işi;
            // burada yalnız chat içeriği taşıyan bilinmeyen event adlarını
            // (eşleşiyorsa) uygula.
            guard event.event.hasPrefix("chat."), matchesCurrentStream(event.data) else { return }
            let (text, blocks) = Self.extractContent(from: event.data)
            if !blocks.isEmpty { applyAssistantBlocks(blocks) }
            if !text.isEmpty { appendDelta(text) }
        }
    }

    // MARK: - Message mutation helpers (delta coalescing)

    private func appendDelta(_ delta: String) {
        guard !delta.isEmpty else { return }
        pendingDeltaText.append(delta)
        scheduleStreamFlush()
    }

    private func applyAssistantBlocks(_ blocks: [ChatBlock]) {
        // Bloklar kümülatif snapshot'tır: sonuncusu kazanır.
        pendingBlocks = blocks
        scheduleStreamFlush()
    }

    private func scheduleStreamFlush() {
        guard deltaFlushTask == nil else { return }
        deltaFlushTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 33_000_000)
            guard let self, !Task.isCancelled else { return }
            self.deltaFlushTask = nil
            self.flushPendingStream()
        }
    }

    /// Biriken delta + blok snapshot'ını TEK dizi mutasyonuyla uygular.
    private func flushPendingStream() {
        guard let id = streamingAssistantId,
              let idx = messages.firstIndex(where: { $0.id == id }) else {
            pendingDeltaText = ""
            pendingBlocks = nil
            return
        }
        var changed = false
        if !pendingDeltaText.isEmpty {
            messages[idx].text.append(pendingDeltaText)
            pendingDeltaText = ""
            changed = true
        }
        if let blocks = pendingBlocks {
            pendingBlocks = nil
            messages[idx].blocks = blocks
            let textFallback = blocks.compactMap { block -> String? in
                if case .text(let b) = block { return b.markdown }
                if case .summary(let b) = block { return b.summary }
                return nil
            }.joined(separator: "\n\n")
            if !textFallback.isEmpty { messages[idx].text = textFallback }
            changed = true
        }
        _ = changed
    }

    /// Flush zamanlayıcısını iptal edip bekleyeni hemen uygular — stream
    /// biterken son parça asla kaybolmasın.
    private func drainPendingStream() {
        deltaFlushTask?.cancel()
        deltaFlushTask = nil
        flushPendingStream()
    }

    private func replaceAssistant(text: String, blocks: [ChatBlock]) {
        drainPendingStream()
        guard let id = streamingAssistantId,
              let idx = messages.firstIndex(where: { $0.id == id }) else { return }
        messages[idx].blocks = Self.removingTaskTraceBlocks(from: blocks)
        if !text.isEmpty { messages[idx].text = text }
    }

    private func finishStreamingSuccessfully() {
        drainPendingStream()
        isStreaming = false
        streamingAssistantId = nil
        currentTaskId = nil
        // Kalıcı kanal AÇIK KALIR — sonraki send() sıfır el sıkışmayla akar.
    }

    private func finishStreaming(withFailure error: Error) async {
        drainPendingStream()
        let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        lastError = msg
        if let id = streamingAssistantId,
           let idx = messages.firstIndex(where: { $0.id == id }),
           messages[idx].text.isEmpty {
            messages[idx].text = "Hata: \(msg)"
        }
        isStreaming = false
        streamingAssistantId = nil
        currentTaskId = nil
    }

    private func streamDidClose() async {
        guard isStreaming else { return }
        drainPendingStream()
        if let id = streamingAssistantId,
           let idx = messages.firstIndex(where: { $0.id == id }),
           messages[idx].text.isEmpty, messages[idx].blocks.isEmpty {
            // Çıplak "Yanıt alınamadı." bir çıkmazdı. Nedeni + eylemi ver:
            // stream boş kapandıysa bu genellikle masaüstü motoru/bağlantı
            // sorunudur; kullanıcı tekrar deneyince yerel yol toparlanır.
            messages[idx].text = "Yanıt gelmedi — masaüstü motoru yeniden bağlanıyor olabilir. Birkaç saniye sonra tekrar dener misin?"
        }
        isStreaming = false
        streamingAssistantId = nil
        currentTaskId = nil
    }

    // MARK: - Content extraction (SSE)

    /// SSE envelope'undan görünür metni ve blokları çıkarır.
    ///
    /// KRİTİK: backend `buildChatStreamEnvelope` içeriği `data.payload` altına
    /// koyuyor; delta metni `payload.delta`, bloklar `payload.assistantMessage.blocks`
    /// içinde. Eski sürüm yalnız top-level `data`/`data.assistant`'a bakıyordu —
    /// bu yüzden CANLI streaming'de delta hiç parse edilemiyor, cevap sonsuza
    /// dek "Düşünüyor…"da takılıyordu (geçmiş cevaplar REST'ten geldiği için
    /// çalışıyordu, canlı SSE değil). Artık payload + assistantMessage + eski
    /// top-level varyantlarının hepsi taranıyor.
    /// Envelope'dan yönlendirme kimliklerini çıkarır — kalıcı user-channel
    /// üzerinde birden fazla eşzamanlı task'ın (ör. mobilden başlatılmış)
    /// event'leri karışmasın diye. taskId/sessionId payload'da, top-level'da
    /// veya assistantMessage içinde olabilir; hepsi taranır.
    static func extractRouting(from data: [String: Any]) -> (taskId: String?, sessionId: String?) {
        let payload = (data["payload"] as? [String: Any]) ?? data
        let assistantMessage = (payload["assistantMessage"] as? [String: Any])
            ?? (data["assistantMessage"] as? [String: Any])
        let taskId = (payload["taskId"] as? String)
            ?? (data["taskId"] as? String)
            ?? (assistantMessage?["taskId"] as? String)
        let sessionId = (payload["sessionId"] as? String)
            ?? (data["sessionId"] as? String)
            ?? (assistantMessage?["sessionId"] as? String)
        return (taskId, sessionId)
    }

    static func extractContent(from data: [String: Any]) -> (text: String, blocks: [ChatBlock]) {
        let payload = (data["payload"] as? [String: Any]) ?? data

        // Blok taşıyıcı objesi: assistantMessage (yeni sözleşme) > assistant (eski)
        let assistantMessage = (payload["assistantMessage"] as? [String: Any])
            ?? (payload["assistant"] as? [String: Any])
            ?? (data["assistantMessage"] as? [String: Any])
            ?? (data["assistant"] as? [String: Any])

        // Metin: delta (incremental parça) > content (kümülatif) > markdown/message.
        let text = (payload["delta"] as? String)
            ?? (payload["content"] as? String)
            ?? (assistantMessage?["content"] as? String)
            ?? (payload["markdown"] as? String)
            ?? (payload["message"] as? String)
            ?? (data["delta"] as? String)
            ?? (data["content"] as? String)
            ?? ""

        // Bloklar: assistantMessage.blocks > payload.blocks > data.blocks
        let rawBlocks = (assistantMessage?["blocks"] as? [[String: Any]])
            ?? (payload["blocks"] as? [[String: Any]])
            ?? (data["blocks"] as? [[String: Any]])
            ?? []
        let blocks = ChatBlock.parseArray(from: rawBlocks)

        return (text, blocks)
    }

    private static func isTaskTraceOnlySnapshot(_ blocks: [ChatBlock]) -> Bool {
        !blocks.isEmpty && blocks.allSatisfy { block in
            if case .taskTrace = block { return true }
            return false
        }
    }

    private static func removingTaskTraceBlocks(from blocks: [ChatBlock]) -> [ChatBlock] {
        blocks.filter { block in
            if case .taskTrace = block { return false }
            return true
        }
    }
}
