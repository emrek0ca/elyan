import SwiftUI

/// Main app shell after login. Sidebar lists past chat sessions inline
/// (Claude Code style) so tapping one continues the conversation right in
/// the chat surface via `ChatStore.loadSession(...)`. The old separate
/// History / Settings screens are gone — the profile chip at the bottom is
/// now the entry point for Settings and Sign Out.
struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @State private var selection: SidebarItem? = .chat
    @State private var sessions: [ElyanSession] = []
    @State private var isLoadingSessions = false
    @State private var isLoadingMoreSessions = false
    @State private var sessionsLoaded = false
    @State private var hasMoreSessions = false
    @State private var sessionsCursor: String? = nil
    @State private var sessionsError: String = ""
    @State private var confirmDeleteSession: ElyanSession? = nil
    @AppStorage("colorScheme") private var storedScheme: String = "system"

    // Navigation history for back/forward toolbar buttons
    @State private var navHistory: [SidebarItem] = [.chat]
    @State private var historyIndex: Int = 0
    // Geri/ileri ile gezinirken .onChange'in aynı hedefi geçmişe TEKRAR
    // eklemesini engeller — yoksa geri/ileri geçmişi kendini çoğaltıp bozardı.
    @State private var isHistoryNavigating = false

    enum SidebarItem: Hashable {
        case chat
        case pairing
        case taskInbox
        case settings
        case session(String)
    }

    // MARK: - Navigation helpers

    private var canGoBack: Bool { historyIndex > 0 }
    private var canGoForward: Bool { historyIndex < navHistory.count - 1 }

    /// Programatik gezinme — selection'ı set eder; geçmiş senkronizasyonunu
    /// `.onChange(of: selection)` TEK noktadan yapar (sidebar tıklaması da aynı
    /// yoldan geçtiği için geri/ileri geçmişi artık tutarlı).
    private func navigate(to item: SidebarItem) {
        guard item != selection else { return }
        selection = item
    }

    private func goBack() {
        guard canGoBack else { return }
        isHistoryNavigating = true
        historyIndex -= 1
        selection = navHistory[historyIndex]
    }

    private func goForward() {
        guard canGoForward else { return }
        isHistoryNavigating = true
        historyIndex += 1
        selection = navHistory[historyIndex]
    }

    var body: some View {
        NavigationSplitView {
            sidebar
                .navigationSplitViewColumnWidth(min: 210, ideal: 230, max: 280)
        } detail: {
            detailView
                .frame(minWidth: 560)
        }
        .navigationSplitViewStyle(.balanced)
        .frame(minWidth: 860, minHeight: 600)
        .toolbar {
            ToolbarItemGroup(placement: .navigation) {
                Button(action: goBack) {
                    Image(systemName: "chevron.left")
                }
                .disabled(!canGoBack)
                .help("Geri")

                Button(action: goForward) {
                    Image(systemName: "chevron.right")
                }
                .disabled(!canGoForward)
                .help("İleri")
            }
        }
        .onAppear { applyStoredScheme() }
        // Only react to session changes that are different from the currently
        // displayed session — prevents loadSession wiping an in-progress chat.
        .onReceive(appState.chat.$sessionId.dropFirst()) { sid in
            guard let sid else { return }
            if case .session(let currentId) = selection, currentId == sid { return }
            if selection == .chat, appState.chat.messages.isEmpty == false { return }
            navigate(to: .session(sid))
            if sessionsLoaded {
                Task { await refreshSessions(force: true) }
            }
        }
        .onChange(of: selection) { _, newValue in
            guard let item = newValue else { return }
            // Geçmiş senkronizasyonu — TEK nokta. Geri/ileri ise historyIndex
            // zaten ayarlandı, tekrar ekleme; yeni bir hedefse dalı buda+ekle.
            if isHistoryNavigating {
                isHistoryNavigating = false
            } else if !navHistory.indices.contains(historyIndex) || navHistory[historyIndex] != item {
                navHistory = Array(navHistory.prefix(historyIndex + 1))
                navHistory.append(item)
                historyIndex = navHistory.count - 1
            }
            switch item {
            case .chat:
                appState.chat.reset()
            case .session(let id):
                Task { await appState.chat.loadSession(id) }
            default:
                break
            }
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        List(selection: $selection) {
            // App header row — not selectable
            HStack(spacing: 8) {
                Image("Logo")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 22, height: 22)
                Text("Elyan")
                    .font(.system(size: 14, weight: .semibold, design: .rounded))
            }
            .padding(.vertical, 6)
            .padding(.horizontal, 4)

            Section {
                Label("Yeni sohbet", systemImage: "square.and.pencil")
                    .tag(SidebarItem.chat)

                Label {
                    HStack {
                        Text("Mobilden görevler")
                        Spacer()
                        if appState.pendingTaskCount > 0 {
                            Text("\(appState.pendingTaskCount)")
                                .font(.system(size: 10, weight: .bold))
                                .padding(.horizontal, 6)
                                .padding(.vertical, 1)
                                .background(Color.accentColor)
                                .foregroundStyle(.white)
                                .clipShape(Capsule())
                        }
                    }
                } icon: {
                    Image(systemName: "tray.and.arrow.down")
                }
                .tag(SidebarItem.taskInbox)

                Label("Cihaz eşleştir", systemImage: "iphone.and.arrow.forward.outward")
                    .tag(SidebarItem.pairing)
            }

            Section("Geçmiş") {
                if !sessionsLoaded {
                    Button {
                        Task { await refreshSessions() }
                    } label: {
                        Label("Geçmişi göster", systemImage: "clock")
                    }
                    .disabled(isLoadingSessions)
                } else if sessions.isEmpty && !isLoadingSessions {
                    Text(sessionsError.isEmpty ? "Henüz sohbet yok." : sessionsError)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if isLoadingSessions && sessions.isEmpty {
                    ProgressView().controlSize(.small)
                }

                ForEach(sessions) { session in
                    SessionRowNative(
                        session: session,
                        onDelete: { confirmDeleteSession = session }
                    )
                    .tag(SidebarItem.session(session.id))
                }

                if sessionsLoaded && hasMoreSessions {
                    Button {
                        Task { await loadMoreSessions() }
                    } label: {
                        if isLoadingMoreSessions {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("Daha fazla")
                        }
                    }
                    .disabled(isLoadingMoreSessions)
                }
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            profileFooter
        }
        .confirmationDialog(
            "Bu sohbeti sil?",
            isPresented: Binding(
                get: { confirmDeleteSession != nil },
                set: { if !$0 { confirmDeleteSession = nil } }
            ),
            titleVisibility: .visible,
            presenting: confirmDeleteSession
        ) { s in
            Button("Sil", role: .destructive) {
                Task { await deleteSession(s) }
            }
            Button("Vazgeç", role: .cancel) { confirmDeleteSession = nil }
        } message: { _ in
            Text("Bu sohbet ve mesajları kalıcı olarak silinir.")
        }
    }

    // MARK: - Profile Footer (fixed bottom of sidebar)

    private var profileFooter: some View {
        VStack(spacing: 0) {
            Divider()
            ProfileMenuChip(
                backend: appState.backend,
                onSettings: { navigate(to: .settings) },
                onSignOut: { Task { await signOut() } }
            )
        }
        .background(Material.bar)
    }

    // MARK: - Detail

    @ViewBuilder
    private var detailView: some View {
        switch selection ?? .chat {
        case .chat, .session:
            ChatView(chat: appState.chat)
                .environmentObject(appState)
        case .pairing:
            PairingView()
                .environmentObject(appState)
        case .taskInbox:
            TaskInboxView()
                .environmentObject(appState)
        case .settings:
            SettingsView()
                .environmentObject(appState)
        }
    }

    // MARK: - Actions

    private func deleteSession(_ session: ElyanSession) async {
        do {
            try await appState.backend.deleteSession(sessionId: session.id)
            sessions.removeAll { $0.id == session.id }
            if selection == .session(session.id) {
                navigate(to: .chat)
            }
        } catch {
            sessionsError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        confirmDeleteSession = nil
    }

    private func refreshSessions(force: Bool = false) async {
        if isLoadingSessions { return }
        isLoadingSessions = true
        defer { isLoadingSessions = false }
        do {
            let page = try await appState.backend.getSessionsPage(limit: 12, forceRefresh: force)
            sessions = page.sessions
            sessionsLoaded = true
            hasMoreSessions = page.hasMore
            sessionsCursor = page.nextCursor
            sessionsError = ""
        } catch {
            sessionsLoaded = true
            sessionsError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func loadMoreSessions() async {
        guard !isLoadingMoreSessions, hasMoreSessions else { return }
        isLoadingMoreSessions = true
        defer { isLoadingMoreSessions = false }
        do {
            let page = try await appState.backend.getSessionsPage(limit: 12, cursor: sessionsCursor)
            let existingIds = Set(sessions.map(\.id))
            sessions.append(contentsOf: page.sessions.filter { !existingIds.contains($0.id) })
            hasMoreSessions = page.hasMore
            sessionsCursor = page.nextCursor
            sessionsError = ""
        } catch {
            sessionsError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func signOut() async {
        navigate(to: .chat)
        appState.chat.reset()
        await appState.backend.logout()
        sessions.removeAll()
        sessionsLoaded = false
        hasMoreSessions = false
        sessionsCursor = nil
        sessionsError = ""
    }

    private func applyStoredScheme() {
        guard let app = NSApplication.shared.windows.first else { return }
        switch storedScheme {
        case "light": app.appearance = NSAppearance(named: .aqua)
        case "dark":  app.appearance = NSAppearance(named: .darkAqua)
        default:      app.appearance = nil
        }
    }
}

// MARK: - Sidebar Session Row

private struct SessionRowNative: View {
    let session: ElyanSession
    let onDelete: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(displayTitle)
                .lineLimit(1)
            if !session.lastMessage.isEmpty {
                Text(session.lastMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, 2)
        .contextMenu {
            Button("Sil", role: .destructive) { onDelete() }
        }
    }

    private var displayTitle: String {
        let trimmed = session.title.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "Yeni sohbet" : trimmed
    }
}

// MARK: - Profile Menu Chip (sidebar bottom)

private struct ProfileMenuChip: View {
    @ObservedObject var backend: ElyanBackend
    let onSettings: () -> Void
    let onSignOut: () -> Void

    @State private var avatarImage: NSImage? = nil
    @State private var lastFetchedAvatarKey: String = ""
    @State private var showPopover = false

    private var session: ElyanAuthSession? { backend.session }

    var body: some View {
        Button(action: { showPopover.toggle() }) {
            HStack(spacing: 10) {
                avatarView
                VStack(alignment: .leading, spacing: 1) {
                    Text(session?.displayName ?? "Kullanıcı")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    Text(session?.email ?? "")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                Image(systemName: "ellipsis")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .popover(isPresented: $showPopover, arrowEdge: .top) {
            VStack(alignment: .leading, spacing: 0) {
                // User info header
                HStack(spacing: 10) {
                    avatarView
                    VStack(alignment: .leading, spacing: 2) {
                        Text(session?.displayName ?? "Kullanıcı")
                            .font(.system(size: 13, weight: .semibold))
                        Text(session?.email ?? "")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 12)

                Divider()

                Button(action: { showPopover = false; onSettings() }) {
                    Label("Ayarlar", systemImage: "gearshape")
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                Divider()

                Button(action: { showPopover = false; onSignOut() }) {
                    Label("Oturumu kapat", systemImage: "rectangle.portrait.and.arrow.right")
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .foregroundStyle(.red)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            .frame(minWidth: 200)
        }
        .task(id: avatarFetchKey) { await refreshAvatar() }
    }

    @ViewBuilder private var avatarView: some View {
        ZStack {
            Circle().fill(Color.accentColor.opacity(0.15))
            if let image = avatarImage {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .clipShape(Circle())
            } else {
                Text(initials)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.tint)
            }
        }
        .frame(width: 28, height: 28)
        .fixedSize()
    }

    private var avatarFetchKey: String {
        let userId = session?.id ?? ""
        let version = session?.avatarVersion ?? 0
        return "\(userId)|\(session?.hasAvatar == true ? 1 : 0)|\(version)"
    }

    private func refreshAvatar() async {
        guard let session, session.hasAvatar, !session.accessToken.isEmpty else {
            avatarImage = nil; return
        }
        if avatarFetchKey == lastFetchedAvatarKey, avatarImage != nil { return }
        do {
            let image = try await backend.fetchAvatarImage()
            avatarImage = image
            lastFetchedAvatarKey = avatarFetchKey
        } catch { avatarImage = nil }
    }

    private var initials: String {
        let source = session?.displayName ?? session?.email ?? "E"
        let letter = source.trimmingCharacters(in: .whitespacesAndNewlines).prefix(1)
        return letter.isEmpty ? "E" : letter.uppercased()
    }
}
