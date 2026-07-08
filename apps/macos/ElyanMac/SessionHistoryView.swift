import SwiftUI

/// Sohbet geçmişi — backend'den /v1/sessions çekerek session listesi gösterir.
/// Mobil'in SessionListScreen + ChatHistoryScreen akışıyla birebir aynı backend uçlarını kullanır.
struct SessionHistoryView: View {
    @EnvironmentObject var appState: AppState
    @State private var sessions: [ElyanSession] = []
    @State private var selected: ElyanSession? = nil
    @State private var isLoading = false
    @State private var isLoadingMore = false
    @State private var hasMoreSessions = false
    @State private var nextCursor: String? = nil
    @State private var error: String = ""
    @State private var confirmDelete: ElyanSession? = nil

    var body: some View {
        NavigationView {
            sessionList
            if let session = selected {
                SessionDetailView(session: session)
                    .environmentObject(appState)
            } else {
                emptyState
            }
        }
        .task { await loadSessions() }
    }

    private var sessionList: some View {
        VStack(spacing: 0) {
            if isLoading && sessions.isEmpty {
                ProgressView()
                    .padding(.top, 40)
                Spacer()
            } else if !error.isEmpty && sessions.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle")
                        .font(.largeTitle)
                        .foregroundStyle(.orange)
                    Text(error)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                    Button("Tekrar dene") { Task { await loadSessions() } }
                        .buttonStyle(.bordered)
                }
                .padding(24)
                Spacer()
            } else if sessions.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "bubble.left.and.bubble.right")
                        .font(.system(size: 40))
                        .foregroundStyle(.secondary)
                    Text("Henüz sohbet yok")
                        .font(.headline)
                    Text("Chat ekranından ilk mesajını gönder.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .padding(24)
                Spacer()
            } else {
                List(sessions, selection: $selected) { session in
                    SessionRow(session: session, isSelected: selected?.id == session.id)
                        .tag(session)
                        .contextMenu {
                            Button(role: .destructive) {
                                confirmDelete = session
                            } label: {
                                Label("Sil", systemImage: "trash")
                            }
                        }
                }
                .listStyle(.sidebar)
                if hasMoreSessions {
                    Button {
                        Task { await loadMoreSessions() }
                    } label: {
                        if isLoadingMore {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("Daha fazla")
                        }
                    }
                    .buttonStyle(.borderless)
                    .padding(.vertical, 8)
                    .disabled(isLoadingMore)
                }
            }
        }
        .frame(minWidth: 220)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button { Task { await loadSessions() } } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(isLoading)
            }
        }
        .confirmationDialog(
            "Bu sohbeti silmek istediğine emin misin?",
            isPresented: Binding(get: { confirmDelete != nil }, set: { if !$0 { confirmDelete = nil } }),
            titleVisibility: .visible
        ) {
            Button("Sil", role: .destructive) {
                if let s = confirmDelete { Task { await deleteSession(s) } }
            }
            Button("İptal", role: .cancel) { confirmDelete = nil }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "bubble.left.and.text.bubble.right")
                .font(.system(size: 56))
                .foregroundStyle(.secondary)
            Text("Bir sohbet seç")
                .font(.title3)
                .foregroundStyle(.secondary)
        }
    }

    private func loadSessions() async {
        if isLoading { return }
        isLoading = true
        error = ""
        do {
            let page = try await appState.backend.getSessionsPage(limit: 12)
            sessions = page.sessions
            hasMoreSessions = page.hasMore
            nextCursor = page.nextCursor
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        isLoading = false
    }

    private func loadMoreSessions() async {
        guard !isLoadingMore, hasMoreSessions else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        do {
            let page = try await appState.backend.getSessionsPage(limit: 12, cursor: nextCursor)
            let existingIds = Set(sessions.map(\.id))
            sessions.append(contentsOf: page.sessions.filter { !existingIds.contains($0.id) })
            hasMoreSessions = page.hasMore
            nextCursor = page.nextCursor
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func deleteSession(_ session: ElyanSession) async {
        do {
            try await appState.backend.deleteSession(sessionId: session.id)
            sessions.removeAll { $0.id == session.id }
            if selected?.id == session.id { selected = nil }
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}

private struct SessionRow: View {
    let session: ElyanSession
    let isSelected: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(session.title)
                .font(.system(.body, weight: .medium))
                .lineLimit(1)
            if !session.lastMessage.isEmpty {
                Text(session.lastMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            HStack {
                Text(session.updatedAt.formatted(.relative(presentation: .named)))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                Spacer()
                if session.messageCount > 0 {
                    Text("\(session.messageCount) mesaj")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

/// Bir session'ın mesajlarını gösteren detay ekranı
struct SessionDetailView: View {
    @EnvironmentObject var appState: AppState
    let session: ElyanSession

    @State private var messages: [ElyanSessionMessage] = []
    @State private var isLoading = false
    @State private var isLoadingMore = false
    @State private var hasMoreMessages = false
    @State private var nextCursor: String? = nil
    @State private var error: String = ""

    var body: some View {
        VStack(spacing: 0) {
            if isLoading {
                ProgressView()
                    .padding(.top, 60)
                Spacer()
            } else if !error.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle").font(.largeTitle).foregroundStyle(.orange)
                    Text(error).font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    Button("Tekrar dene") { Task { await load() } }.buttonStyle(.bordered)
                }
                .padding(24)
                Spacer()
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 12) {
                            if hasMoreMessages {
                                Button {
                                    Task { await loadMoreMessages() }
                                } label: {
                                    if isLoadingMore {
                                        ProgressView().controlSize(.small)
                                    } else {
                                        Text("Daha eski mesajlar")
                                    }
                                }
                                .buttonStyle(.borderless)
                            }
                            ForEach(messages) { msg in
                                HistoryBubble(message: msg)
                                    .id(msg.id)
                            }
                        }
                        .padding(20)
                    }
                    .onAppear {
                        if let last = messages.last?.id {
                            proxy.scrollTo(last, anchor: .bottom)
                        }
                    }
                }
            }
        }
        .navigationTitle(session.title)
        .task { await load() }
    }

    private func load() async {
        if isLoading { return }
        isLoading = true
        error = ""
        do {
            let result = try await appState.backend.getSessionMessages(sessionId: session.id, limit: 30)
            messages = result.messages
            hasMoreMessages = result.hasMore
            nextCursor = result.nextCursor
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        isLoading = false
    }

    private func loadMoreMessages() async {
        guard !isLoadingMore, hasMoreMessages else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        do {
            let result = try await appState.backend.getSessionMessages(
                sessionId: session.id,
                limit: 30,
                cursor: nextCursor
            )
            let existingIds = Set(messages.map(\.id))
            let older = result.messages.filter { !existingIds.contains($0.id) }
            messages.insert(contentsOf: older, at: 0)
            hasMoreMessages = result.hasMore
            nextCursor = result.nextCursor
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}

private struct HistoryBubble: View {
    let message: ElyanSessionMessage
    private var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack(alignment: .top) {
            if isUser { Spacer(minLength: 40) }
            VStack(alignment: isUser ? .trailing : .leading, spacing: 4) {
                Text(isUser ? "Sen" : "Elyan")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(message.text.isEmpty ? "…" : message.text)
                    .textSelection(.enabled)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(isUser ? Color.accentColor.opacity(0.15) : Color.secondary.opacity(0.1))
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                Text(message.createdAt.formatted(date: .omitted, time: .shortened))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            if !isUser { Spacer(minLength: 40) }
        }
    }
}
