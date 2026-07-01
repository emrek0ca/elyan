import Foundation

// MARK: - Cache Entry

private struct CacheEntry<T> {
    let value: T
    let expiresAt: Date
    var etag: String?

    var isExpired: Bool { Date() >= expiresAt }
}

// MARK: - ElyanCache

/// Thread-safe (MainActor) in-memory LRU cache for Elyan data.
/// Keys are Strings; values are type-erased via generics at the call site.
///
/// Design rules:
///  • Hit → return immediately, no network call.
///  • Stale hit → return stale value immediately, caller triggers background refresh.
///  • Miss → caller fetches from network, stores result.
@MainActor
final class ElyanCache {

    static let shared = ElyanCache()

    // MARK: - Typed storage

    /// Session list: userId → pages of sessions
    private var sessionListCache: [String: CacheEntry<[ElyanSession]>] = [:]

    /// Messages: "sessionId|cursor" → paginated message result
    private var messagePageCache: [String: CacheEntry<CachedMessagePage>] = [:]

    /// Prefetch priority queue (last N accessed keys — simple eviction)
    private var messageKeyOrder: [String] = []
    private let maxMessagePages = 100

    private init() {}

    // MARK: - Session List

    func sessions(forUser userId: String) -> ([ElyanSession], Bool)? {
        guard let entry = sessionListCache[userId] else { return nil }
        return (entry.value, entry.isExpired)
    }

    func storeSessions(_ sessions: [ElyanSession], forUser userId: String, ttl: TimeInterval = 60, etag: String? = nil) {
        sessionListCache[userId] = CacheEntry(
            value: sessions,
            expiresAt: Date(timeIntervalSinceNow: ttl),
            etag: etag
        )
    }

    func sessionListEtag(forUser userId: String) -> String? {
        sessionListCache[userId]?.etag
    }

    func invalidateSessions(forUser userId: String) {
        sessionListCache.removeValue(forKey: userId)
    }

    // MARK: - Message Pages

    func messagePage(sessionId: String, cursor: String?) -> (CachedMessagePage, Bool)? {
        let key = cacheKey(sessionId: sessionId, cursor: cursor)
        guard let entry = messagePageCache[key] else { return nil }
        return (entry.value, entry.isExpired)
    }

    func storeMessagePage(
        _ page: CachedMessagePage,
        sessionId: String,
        cursor: String?,
        ttl: TimeInterval = 300,
        etag: String? = nil
    ) {
        let key = cacheKey(sessionId: sessionId, cursor: cursor)
        messagePageCache[key] = CacheEntry(
            value: page,
            expiresAt: Date(timeIntervalSinceNow: ttl),
            etag: etag
        )
        evictIfNeeded(insertedKey: key)
    }

    func messagePageEtag(sessionId: String, cursor: String?) -> String? {
        let key = cacheKey(sessionId: sessionId, cursor: cursor)
        return messagePageCache[key]?.etag
    }

    func invalidateMessages(forSession sessionId: String) {
        let prefix = "\(sessionId)|"
        messagePageCache = messagePageCache.filter { !$0.key.hasPrefix(prefix) }
        messageKeyOrder = messageKeyOrder.filter { !$0.hasPrefix(prefix) }
    }

    // MARK: - LRU eviction

    private func evictIfNeeded(insertedKey: String) {
        messageKeyOrder.removeAll { $0 == insertedKey }
        messageKeyOrder.append(insertedKey)
        while messageKeyOrder.count > maxMessagePages {
            let oldest = messageKeyOrder.removeFirst()
            messagePageCache.removeValue(forKey: oldest)
        }
    }

    private func cacheKey(sessionId: String, cursor: String?) -> String {
        "\(sessionId)|\(cursor ?? "first")"
    }

    // MARK: - Purge all

    func purgeAll() {
        sessionListCache.removeAll()
        messagePageCache.removeAll()
        messageKeyOrder.removeAll()
    }
}

// MARK: - CachedMessagePage

struct CachedMessagePage {
    let messages: [ElyanSessionMessage]
    let hasMore: Bool
    let nextCursor: String?
}
