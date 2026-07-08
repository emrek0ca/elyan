import Foundation
import SwiftUI

// MARK: - ChatMessage

struct ChatMessage: Identifiable {
    enum Role: String, Equatable { case user, assistant }
    let id = UUID()
    let role: Role
    var text: String
    var blocks: [ChatBlock]
    let timestamp: Date
    /// Non-nil only for messages loaded from session history whose backend
    /// status wasn't a terminal "completed" (queued/running/waiting_approval/
    /// failed/canceled) — nil for live/local messages so the normal streaming
    /// path (which already has its own "Düşünüyor…" indicator) is untouched.
    var historyStatus: String?
    var historyError: String?

    init(
        role: Role, text: String, blocks: [ChatBlock] = [], timestamp: Date = Date(),
        historyStatus: String? = nil, historyError: String? = nil
    ) {
        self.role = role
        self.text = text
        self.blocks = blocks
        self.timestamp = timestamp
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

        // Kanal POST'tan ÖNCE ısınır: dispatch döner dönmez ilk delta'lar
        // zaten açık olan stream'den akar — eski per-task modeldeki
        // "POST bitti, şimdi bağlan" boşluğu yok.
        ensureRealtimeOpen()

        let userMsg = ChatMessage(role: .user, text: trimmed)
        messages.append(userMsg)
        let placeholder = ChatMessage(role: .assistant, text: "")
        messages.append(placeholder)
        streamingAssistantId = placeholder.id
        isStreaming = true
        lastError = ""

        // SwiftUI'nin @Published mutasyonlarını bir render'a çevirmesi için
        // RunLoop'a bir "nefes" verilmeden hemen ağ çağrısına geçiliyordu —
        // kullanıcının kendi mesajı, sonraki @Published mutasyonu (cevap ya
        // da hata) gelene kadar ekranda hiç görünmüyordu (canlı testte
        // doğrulandı: messages.append hemen çalışıyor ama arayüz ancak
        // stream/hata sonucunu da alınca "birden" doluyormuş gibi
        // güncelleniyordu). Tek bir yield, optimistic baloncuğun ağ
        // çağrısından ÖNCE ekrana çizilmesini garantiler.
        await Task.yield()

        // YEREL-ÖNCELİKLİ YOL (Jarvis): bulut, masaüstü kaynaklı komutları
        // masaüstüne geri göndermeyip kendi LLM'iyle "masaüstü ortamı yok"
        // diye reddediyordu. Komut yerel runtime'da (deterministik router +
        // gerçek araçlar) çalışır; sonuç senkron döner. Bridge kapalıysa
        // eski bulut yoluna düşülür.
        if let localSend {
            do {
                let reply = try await localSend(trimmed)
                completeStreaming(withLocalReply: reply)
                return
            } catch is RuntimeBridgeSwiftError {
                // Bridge ayakta değil — bulut yoluna devam.
            } catch {
                await finishStreaming(withFailure: error)
                return
            }
        }

        do {
            let dispatch = try await backend.sendChatMessage(
                prompt: trimmed,
                sessionId: sessionId,
                source: "desktop"
            )
            currentTaskId = dispatch.taskId
            if let sid = dispatch.sessionId, !sid.isEmpty {
                sessionId = sid
                // Invalidate cache for this session so next open fetches fresh
                cache.invalidateMessages(forSession: sid)
            }
        } catch {
            await finishStreaming(withFailure: error)
        }
    }

    /// AppState tarafından bağlanır: komutu yerel Python runtime'ında koşturur.
    var localSend: ((String) async throws -> PythonRuntimeSupervisor.LocalChatReply)?

    /// Aktif oturum değiştiğinde (yeni sohbet = boş kimlik) yerel runtime'ın
    /// konuşma bağlamını senkron tutmak için AppState tarafından bağlanır.
    var onSessionActivated: ((String) -> Void)?

    private func completeStreaming(withLocalReply reply: PythonRuntimeSupervisor.LocalChatReply) {
        drainPendingStream()
        if let id = streamingAssistantId,
           let idx = messages.firstIndex(where: { $0.id == id }) {
            messages[idx].text = reply.text
        }
        isStreaming = false
        streamingAssistantId = nil
        currentTaskId = nil
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
            messages[idx].text = "Yanıt alınamadı."
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
