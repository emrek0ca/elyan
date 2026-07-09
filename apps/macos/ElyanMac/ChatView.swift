import SwiftUI

// MARK: - ElyanTheme
//
// Mobil tasarım dilinin masaüstü karşılığı: sıcak krem zemin, asistan cevabı
// balonsuz doğrudan zeminde, kullanıcı mesajı yumuşak krem balonda, hap
// biçimli composer. Karanlık modda sistem koyu tonlarına düşer. Renkler
// mobil ekranın (flutter) zemininden örneklendi.
enum ElyanTheme {
    /// Sohbet zemini — açıkta sıcak krem, koyuda nötr koyu.
    static let canvas = Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(calibratedRed: 0.106, green: 0.106, blue: 0.098, alpha: 1)
            : NSColor(calibratedRed: 0.949, green: 0.933, blue: 0.898, alpha: 1)
    })

    /// Kullanıcı balonu — zeminden bir tık koyu krem.
    static let userBubble = Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(calibratedRed: 0.180, green: 0.180, blue: 0.168, alpha: 1)
            : NSColor(calibratedRed: 0.898, green: 0.875, blue: 0.827, alpha: 1)
    })

    /// Composer alanı — zeminden hafif açık, hap biçim.
    static let composerField = Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(calibratedRed: 0.145, green: 0.145, blue: 0.137, alpha: 1)
            : NSColor(calibratedRed: 0.984, green: 0.976, blue: 0.957, alpha: 1)
    })

    /// Kart/ikincil yüzey (blok kartları, düşünme göstergesi).
    static let surface = Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(calibratedRed: 0.157, green: 0.157, blue: 0.149, alpha: 1)
            : NSColor(calibratedRed: 0.973, green: 0.961, blue: 0.937, alpha: 1)
    })

    static let hairline = Color.primary.opacity(0.08)
}

// MARK: - ChatView

struct ChatView: View {
    @EnvironmentObject var appState: AppState
    // KRİTİK: ChatStore ayrı bir ObservableObject — appState üzerinden
    // computed property ile erişmek onun @Published mutasyonlarını
    // GÖZLEMLEMEZ (AppState yalnız supervisor.objectWillChange'i iletiyor).
    // Bu yüzden kullanıcı mesajı ve stream delta'ları ekrana ancak başka bir
    // global yenileme (25 sn'lik dispatch watchdog'u) tetiklenince düşüyordu.
    @ObservedObject var chat: ChatStore
    @State private var draft = ""
    @AppStorage("showTimestamps") private var showTimestamps: Bool = false
    @AppStorage("compactBubbles") private var compactBubbles: Bool = false
    @AppStorage("chatFontSize") private var chatFontSize: Double = 14

    var body: some View {
        VStack(spacing: 0) {
            messageScrollArea
            inputArea
        }
        .background(ElyanTheme.canvas)
    }

    // MARK: - Message Scroll Area

    private var messageScrollArea: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: compactBubbles ? 6 : 14) {

                    // Stale indicator — shown briefly while background refresh runs
                    if chat.isStale {
                        HStack(spacing: 6) {
                            ProgressView().controlSize(.mini)
                            Text("Güncelleniyor…")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 4)
                        .transition(.opacity)
                    }

                    // Load more (older messages) — appears at top
                    if chat.hasMoreMessages {
                        LoadMoreButton(isLoading: chat.isLoadingMore) {
                            Task { await chat.loadMoreMessages() }
                        }
                    }

                    // Loading skeleton (first load, no cache)
                    if chat.isLoadingSession && chat.messages.isEmpty {
                        ForEach(0..<3, id: \.self) { i in
                            SkeletonBubble(role: i % 2 == 0 ? .user : .assistant)
                        }
                    }

                    // Empty state
                    if chat.messages.isEmpty && !chat.isLoadingSession {
                        emptyState
                    }

                    // Messages — .equatable(): streaming sırasında yalnız
                    // değişen (kuyruk) baloncuğun body'si koşar; tarihçe
                    // satırları ChatMessage == sayesinde atlanır.
                    ForEach(chat.messages) { message in
                        ChatBubble(
                            message: message,
                            isStreamingTail: chat.isStreaming && message.id == chat.messages.last?.id,
                            showTimestamp: showTimestamps,
                            compact: compactBubbles,
                            fontSize: chatFontSize,
                            onPlanDecision: { messageId, approved in
                                Task { await chat.confirmPlan(messageId: messageId, approved: approved) }
                            },
                            onGrantPermission: { messageId in
                                Task { await chat.grantPermission(messageId: messageId) }
                            },
                            onOpenSystemPermission: { messageId in
                                Task { await chat.openSystemPermission(messageId: messageId) }
                            }
                        )
                        .equatable()
                        .id(message.id)
                    }

                    // Error banner
                    if !chat.lastError.isEmpty {
                        HStack(spacing: 8) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundStyle(.orange)
                            Text(chat.lastError)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.top, 4)
                        .id("error-banner")
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
                .animation(.easeOut(duration: 0.2), value: chat.messages.count)
            }
            .onChange(of: chat.messages.last?.id) { _, lastId in
                // Scroll to bottom only on new message, not on prepend
                guard let lastId else { return }
                withAnimation(.easeOut(duration: 0.15)) {
                    proxy.scrollTo(lastId, anchor: .bottom)
                }
            }
            .onChange(of: chat.messages.last?.text) { _, _ in
                // Smooth scroll during streaming
                if chat.isStreaming, let lastId = chat.messages.last?.id {
                    proxy.scrollTo(lastId, anchor: .bottom)
                }
            }
        }
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image("Logo")
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: 52, height: 52)
                .opacity(0.65)
            VStack(spacing: 6) {
                Text("Elyan")
                    .font(.system(size: 22, weight: .bold, design: .rounded))
                Text("Bir şey yaz, beraber çalışalım.")
                    .foregroundStyle(.secondary)
                    .font(.callout)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 60)
        .padding(.vertical, 12)
    }

    // MARK: - Input Area

    private var inputArea: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("Bir şey sor…", text: $draft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.system(size: chatFontSize))
                .lineLimit(1...8)
                .padding(.horizontal, 16)
                .padding(.vertical, 11)
                .background(ElyanTheme.composerField)
                .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .stroke(ElyanTheme.hairline, lineWidth: 1)
                )
                .onSubmit(send)

            Button(action: send) {
                Image(systemName: chat.isStreaming ? "ellipsis.circle.fill" : "arrow.up.circle.fill")
                    .font(.system(size: 30))
                    .foregroundColor(canSend ? .accentColor : Color.secondary.opacity(0.4))
                    .animation(.easeInOut(duration: 0.15), value: chat.isStreaming)
            }
            .buttonStyle(.plain)
            .disabled(!canSend)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(ElyanTheme.canvas)
    }

    private var canSend: Bool {
        !chat.isStreaming && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func send() {
        let text = draft
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        draft = ""
        Task { await chat.send(text) }
    }
}

// MARK: - ChatBubble

private struct ChatBubble: View, Equatable {
    let message: ChatMessage
    let isStreamingTail: Bool
    var showTimestamp: Bool = false
    var compact: Bool = false
    var fontSize: Double = 14
    /// (messageId, approved) — kullanıcı plan kartında karar verdiğinde.
    var onPlanDecision: (UUID, Bool) -> Void = { _, _ in }
    /// messageId — kullanıcı izin kartında "İzin Ver"e bastığında.
    var onGrantPermission: (UUID) -> Void = { _ in }
    /// messageId — kullanıcı "Sistem Ayarları'nı Aç"a bastığında.
    var onOpenSystemPermission: (UUID) -> Void = { _ in }

    // Kapanış (closure) Equatable olmadığı için sentezlenen == kullanılamaz;
    // yalnız render'ı etkileyen alanları karşılaştırıyoruz.
    static func == (lhs: ChatBubble, rhs: ChatBubble) -> Bool {
        lhs.message == rhs.message
            && lhs.isStreamingTail == rhs.isStreamingTail
            && lhs.showTimestamp == rhs.showTimestamp
            && lhs.compact == rhs.compact
            && lhs.fontSize == rhs.fontSize
    }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            if message.role == .user { Spacer(minLength: 40) }

            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: compact ? 2 : 5) {
                if !compact {
                    Text(message.role == .user ? "Sen" : "Elyan")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 4)
                }

                contentView

                if let plan = message.plan {
                    PlanCard(
                        plan: plan,
                        fontSize: fontSize,
                        onApprove: { onPlanDecision(message.id, true) },
                        onCancel: { onPlanDecision(message.id, false) }
                    )
                }

                if let permission = message.permission {
                    PermissionCard(
                        permission: permission,
                        fontSize: fontSize,
                        onGrant: { onGrantPermission(message.id) },
                        onOpenSettings: { onOpenSystemPermission(message.id) }
                    )
                }

                if message.isHistoryPending || message.isHistoryFailed {
                    HistoryStatusBadge(message: message)
                }

                if showTimestamp {
                    Text(message.timestamp.formatted(date: .omitted, time: .shortened))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 4)
                }
            }

            if message.role == .assistant { Spacer(minLength: 40) }
        }
    }

    @ViewBuilder
    private var contentView: some View {
        if isStreamingTail && message.text.isEmpty && message.blocks.isEmpty {
            // Thinking indicator
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Düşünüyor…")
                    .foregroundStyle(.secondary)
                    .font(.system(size: fontSize))
            }
            .padding(.horizontal, compact ? 10 : 14)
            .padding(.vertical, compact ? 6 : 10)
            .background(ElyanTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: compact ? 12 : 16, style: .continuous))
        } else if message.role == .user {
            // User: always plain text
            Text(message.text)
                .font(.system(size: fontSize))
                .textSelection(.enabled)
                .padding(.horizontal, compact ? 12 : 16)
                .padding(.vertical, compact ? 7 : 11)
                .background(ElyanTheme.userBubble)
                .clipShape(RoundedRectangle(cornerRadius: compact ? 12 : 18, style: .continuous))
        } else if !message.blocks.isEmpty {
            // Assistant: block-first rendering
            BlocksRenderer(blocks: message.blocks, fontSize: fontSize, compact: compact)
        } else {
            // Assistant: markdown fallback
            MarkdownBubble(markdown: message.text, fontSize: fontSize, compact: compact)
        }
    }
}

// MARK: - History status badge
//
// Reopening a session whose last assistant message never reached a terminal
// backend status (e.g. the known chat-task deadlock: fire-and-forget
// in-process processing crashes/times out, the lease sweeper resets it to
// "queued", and nothing ever picks a queued chat task back up) previously
// rendered as a plain, unlabeled — often empty — bubble, indistinguishable
// from a normal reply. This makes the real server-side status visible
// instead of silently showing nothing.
private struct HistoryStatusBadge: View {
    let message: ChatMessage

    var body: some View {
        HStack(spacing: 6) {
            if message.isHistoryPending {
                ProgressView().controlSize(.mini)
                Text("Hâlâ işleniyor…")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            } else if message.isHistoryFailed {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption2)
                    .foregroundStyle(.orange)
                Text(message.historyError?.isEmpty == false ? message.historyError! : "Yanıt alınamadı")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
        }
        .padding(.horizontal, 4)
    }
}

// MARK: - Plan Card
//
// Çok adımlı / yan etkili planlar artık düz metin "onayla yaz" yerine adımları
// listeleyen bir kart + Onayla/İptal butonlarıyla gösterilir. Onaylanınca
// runtime adımları masaüstünde yürütür (needsConfirmation/pendingPlanId zaten
// bridge'den dönüyordu; UI bunu görselleştiriyor).
private struct PlanCard: View {
    let plan: PendingPlan
    var fontSize: Double = 14
    let onApprove: () -> Void
    let onCancel: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: "list.bullet.rectangle")
                    .foregroundStyle(.secondary)
                Text("Onay bekleyen plan")
                    .font(.system(size: fontSize - 1, weight: .semibold))
                Spacer()
                if plan.isConfirming {
                    ProgressView().controlSize(.small)
                }
            }

            if !plan.summary.isEmpty {
                Text(plan.summary)
                    .font(.system(size: fontSize - 1))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if !plan.steps.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(plan.steps.enumerated()), id: \.element.id) { index, step in
                        HStack(alignment: .top, spacing: 8) {
                            Text("\(index + 1)")
                                .font(.system(size: fontSize - 3, weight: .bold))
                                .foregroundStyle(.secondary)
                                .frame(width: 18, height: 18)
                                .background(Color.secondary.opacity(0.15))
                                .clipShape(Circle())
                            Text(step.description)
                                .font(.system(size: fontSize - 1))
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }

            HStack(spacing: 10) {
                Button(action: onApprove) {
                    Text("Onayla")
                        .font(.system(size: fontSize - 1, weight: .semibold))
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(plan.isConfirming)

                Button(action: onCancel) {
                    Text("İptal")
                        .font(.system(size: fontSize - 1))
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(plan.isConfirming)
            }
        }
        .padding(14)
        .frame(maxWidth: 420, alignment: .leading)
        .background(ElyanTheme.surface)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(ElyanTheme.hairline, lineWidth: 1)
        )
    }
}

// MARK: - Permission Card
//
// İzin gerektiren komutlar artık kullanıcıyı Ayarlar'da kaybetmek yerine chat'te
// tek-tıkla verme kartı gösterir: Elyan'ın kendi izni anında açılır (ve komut
// otomatik yeniden çalışır), macOS sistem izni için doğru panel açılır.
private struct PermissionCard: View {
    let permission: PermissionRequest
    var fontSize: Double = 14
    let onGrant: () -> Void
    let onOpenSettings: () -> Void

    private var needsSystem: Bool {
        permission.systemPermissionRequired || !permission.systemPermissionKey.isEmpty
    }
    private var canGrantInApp: Bool { !permission.permissionKey.isEmpty }

    private var systemLabel: String {
        switch permission.systemPermissionKey {
        case "accessibility": return "Erişilebilirlik"
        case "screenRecording": return "Ekran Kaydı"
        case "inputMonitoring": return "Girdi İzleme"
        case "automation": return "Otomasyon"
        default: return "Sistem izni"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: "lock.shield")
                    .foregroundStyle(.orange)
                Text("İzin gerekiyor")
                    .font(.system(size: fontSize - 1, weight: .semibold))
                Spacer()
                if permission.isGranting { ProgressView().controlSize(.small) }
            }

            Text(permission.reason)
                .font(.system(size: fontSize - 1))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if needsSystem {
                Text("macOS \(systemLabel) izni gerekli — açılan panelde Elyan'ı işaretle.")
                    .font(.system(size: fontSize - 3))
                    .foregroundStyle(.tertiary)
            }

            HStack(spacing: 10) {
                if canGrantInApp {
                    Button(action: onGrant) {
                        Text("İzin ver")
                            .font(.system(size: fontSize - 1, weight: .semibold))
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(permission.isGranting)
                } else if needsSystem {
                    Button(action: onOpenSettings) {
                        Text("Sistem Ayarları'nı aç")
                            .font(.system(size: fontSize - 1, weight: .semibold))
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(permission.isGranting)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: 420, alignment: .leading)
        .background(ElyanTheme.surface)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(Color.orange.opacity(0.35), lineWidth: 1)
        )
    }
}

// MARK: - Load More Button

private struct LoadMoreButton: View {
    let isLoading: Bool
    let action: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            if isLoading {
                ProgressView().controlSize(.small)
                Text("Eski mesajlar yükleniyor…")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Button(action: action) {
                    Label("Daha fazla yükle", systemImage: "chevron.up.circle")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
    }
}

// MARK: - SkeletonBubble (shimmer placeholder while loading)

private struct SkeletonBubble: View {
    let role: ChatMessage.Role
    @State private var animate = false

    var body: some View {
        HStack {
            if role == .user { Spacer(minLength: 60) }

            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            Color.primary.opacity(animate ? 0.08 : 0.04),
                            Color.primary.opacity(animate ? 0.04 : 0.08)
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
                .frame(height: 44)
                .frame(maxWidth: role == .user ? 200 : 280)

            if role == .assistant { Spacer(minLength: 60) }
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true)) {
                animate = true
            }
        }
    }
}
