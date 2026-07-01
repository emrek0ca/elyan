import SwiftUI

// MARK: - ChatView

struct ChatView: View {
    @EnvironmentObject var appState: AppState
    @State private var draft = ""
    @AppStorage("showTimestamps") private var showTimestamps: Bool = false
    @AppStorage("compactBubbles") private var compactBubbles: Bool = false
    @AppStorage("chatFontSize") private var chatFontSize: Double = 14

    private var chat: ChatStore { appState.chat }

    var body: some View {
        VStack(spacing: 0) {
            messageScrollArea
            Divider()
            inputArea
        }
        .background(Color(NSColor.windowBackgroundColor))
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

                    // Messages
                    ForEach(chat.messages) { message in
                        ChatBubble(
                            message: message,
                            isStreamingTail: chat.isStreaming && message.id == chat.messages.last?.id,
                            showTimestamp: showTimestamps,
                            compact: compactBubbles,
                            fontSize: chatFontSize
                        )
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
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(Color(NSColor.controlBackgroundColor).opacity(0.6))
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(Color.primary.opacity(0.1), lineWidth: 1)
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
        .background(Material.bar)
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

private struct ChatBubble: View {
    let message: ChatMessage
    let isStreamingTail: Bool
    var showTimestamp: Bool = false
    var compact: Bool = false
    var fontSize: Double = 14

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
            .background(Color(NSColor.controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: compact ? 8 : 14, style: .continuous))
        } else if message.role == .user {
            // User: always plain text
            Text(message.text)
                .font(.system(size: fontSize))
                .textSelection(.enabled)
                .padding(.horizontal, compact ? 10 : 14)
                .padding(.vertical, compact ? 6 : 10)
                .background(Color.accentColor.opacity(0.18))
                .clipShape(RoundedRectangle(cornerRadius: compact ? 8 : 14, style: .continuous))
        } else if !message.blocks.isEmpty {
            // Assistant: block-first rendering
            BlocksRenderer(blocks: message.blocks, fontSize: fontSize, compact: compact)
        } else {
            // Assistant: markdown fallback
            MarkdownBubble(markdown: message.text, fontSize: fontSize, compact: compact)
        }
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
