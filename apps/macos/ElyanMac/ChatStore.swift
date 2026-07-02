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

    init(role: Role, text: String, blocks: [ChatBlock] = [], timestamp: Date = Date()) {
        self.role = role
        self.text = text
        self.blocks = blocks
        self.timestamp = timestamp
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
        Task { await sseClient.cancel() }
        deltaFlushTask?.cancel()
        deltaFlushTask = nil
        pendingDeltaText = ""
        pendingBlocks = nil
        messages.removeAll()
        streamingAssistantId = nil
        isStreaming = false
        sessionId = nil
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
        await sseClient.cancel()
        deltaFlushTask?.cancel()
        deltaFlushTask = nil
        pendingDeltaText = ""
        pendingBlocks = nil
        streamingAssistantId = nil
        isStreaming = false
        lastError = ""
        sessionId = trimmed

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
                sessionId: trimmed, limit: 50, cursor: nil, forceRefresh: true
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
                    sessionId: trimmed, limit: 50, cursor: nil, forceRefresh: false
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
                sessionId: id, limit: 50, cursor: nextCursor, forceRefresh: false
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
            return ChatMessage(role: role, text: m.text, blocks: [], timestamp: m.createdAt)
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

        await sseClient.cancel()

        let userMsg = ChatMessage(role: .user, text: trimmed)
        messages.append(userMsg)
        let placeholder = ChatMessage(role: .assistant, text: "")
        messages.append(placeholder)
        streamingAssistantId = placeholder.id
        isStreaming = true
        lastError = ""

        do {
            let dispatch = try await backend.sendChatMessage(
                prompt: trimmed,
                sessionId: sessionId,
                source: "desktop"
            )
            if let sid = dispatch.sessionId, !sid.isEmpty {
                sessionId = sid
                // Invalidate cache for this session so next open fetches fresh
                cache.invalidateMessages(forSession: sid)
            }
            guard let token = backend.session?.accessToken, !token.isEmpty else {
                throw ElyanBackendError.notAuthenticated
            }
            await subscribe(taskId: dispatch.taskId, token: token)
        } catch {
            await finishStreaming(withFailure: error)
        }
    }

    // MARK: - SSE subscription

    private func subscribe(taskId: String, token: String) async {
        await sseClient.open(
            accessToken: token,
            taskId: taskId,
            onEvent: { [weak self] event in await self?.handle(event: event) },
            onError: { [weak self] error in await self?.finishStreaming(withFailure: error) },
            onClose: { [weak self] in await self?.streamDidClose() }
        )
    }

    private func handle(event: ElyanSSEEvent) async {
        switch event.event {
        case "chat.message.delta":
            if let (text, blocks) = Self.extractContent(from: event.data) {
                if !blocks.isEmpty { applyAssistantBlocks(blocks) }
                else if !text.isEmpty { appendDelta(text) }
            }
        case "chat.message.updated":
            if let (text, blocks) = Self.extractContent(from: event.data) {
                replaceAssistant(text: text, blocks: blocks)
            }
            finishStreamingSuccessfully()
        case "chat.heartbeat", "chat.message.created":
            break
        default:
            if let (text, blocks) = Self.extractContent(from: event.data) {
                if !blocks.isEmpty { applyAssistantBlocks(blocks) }
                else if !text.isEmpty { appendDelta(text) }
            }
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
        if !blocks.isEmpty { messages[idx].blocks = blocks }
        if !text.isEmpty { messages[idx].text = text }
    }

    private func finishStreamingSuccessfully() {
        drainPendingStream()
        isStreaming = false
        streamingAssistantId = nil
        // Terminal olay geldi — akışı kapat ki SSE istemcisinin otomatik
        // yeniden bağlanması tamamlanmış bir stream'i yeniden açmasın.
        Task { await sseClient.cancel() }
    }

    private func finishStreaming(withFailure error: Error) async {
        await sseClient.cancel()
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
    }

    // MARK: - Content extraction (SSE)

    static func extractContent(from data: [String: Any]) -> (text: String, blocks: [ChatBlock])? {
        // Try assistant sub-object first (standard backend envelope)
        let sources: [[String: Any]] = [
            (data["assistant"] as? [String: Any]) ?? [:],
            data
        ]
        for source in sources {
            let rawBlocks = (source["blocks"] as? [[String: Any]]) ?? []
            let blocks = ChatBlock.parseArray(from: rawBlocks)
            let text = (source["delta"] as? String)
                ?? (source["content"] as? String)
                ?? (source["message"] as? String)
                ?? ""
            if !blocks.isEmpty || !text.isEmpty {
                return (text, blocks)
            }
        }
        return nil
    }
}
