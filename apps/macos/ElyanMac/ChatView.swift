import SwiftUI

struct ChatView: View {
    @EnvironmentObject var appState: AppState
    @State private var draft = ""
    @AppStorage("showTimestamps") private var showTimestamps: Bool = false
    @AppStorage("compactBubbles") private var compactBubbles: Bool = false
    @AppStorage("chatFontSize") private var chatFontSize: Double = 14

    private var chat: ChatStore { appState.chat }

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: compactBubbles ? 6 : 12) {
                        if chat.messages.isEmpty {
                            VStack(spacing: 16) {
                                Image("Logo")
                                    .resizable()
                                    .aspectRatio(contentMode: .fit)
                                    .frame(width: 52, height: 52)
                                    .opacity(0.7)
                                VStack(spacing: 6) {
                                    Text("Elyan")
                                        .font(.system(size: 20, weight: .bold, design: .rounded))
                                    Text("Bir şey yaz, beraber çalışalım.")
                                        .foregroundStyle(.secondary)
                                        .font(.callout)
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.top, 60)
                            .padding(.vertical, 12)
                        }

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

                        if !chat.lastError.isEmpty {
                            HStack {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .foregroundStyle(.orange)
                                Text(chat.lastError)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.top, 4)
                        }
                    }
                    .padding(20)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .onChange(of: chat.messages.count) {
                    if let lastId = chat.messages.last?.id {
                        withAnimation(.easeOut(duration: 0.15)) {
                            proxy.scrollTo(lastId, anchor: .bottom)
                        }
                    }
                }
                .onChange(of: chat.messages.last?.text) {
                    if let lastId = chat.messages.last?.id {
                        proxy.scrollTo(lastId, anchor: .bottom)
                    }
                }
            }

            Divider()

            HStack(alignment: .bottom) {
                TextField("Bir şey sor…", text: $draft, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.system(size: chatFontSize))
                    .lineLimit(1...5)
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
                        .foregroundColor(canSend ? .accentColor : .secondary.opacity(0.5))
                }
                .buttonStyle(.plain)
                .disabled(!canSend)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(Material.bar)
        }
        .background(Color(NSColor.windowBackgroundColor))
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

private struct ChatBubble: View {
    let message: ChatMessage
    let isStreamingTail: Bool
    var showTimestamp: Bool = false
    var compact: Bool = false
    var fontSize: Double = 14

    var body: some View {
        HStack(alignment: .top) {
            if message.role == .user { Spacer(minLength: 40) }
            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: compact ? 2 : 4) {
                if !compact {
                    Text(message.role == .user ? "Sen" : "Elyan")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                Group {
                    if message.text.isEmpty && isStreamingTail {
                        HStack(spacing: 6) {
                            ProgressView().controlSize(.small)
                            Text("Düşünüyor…").foregroundStyle(.secondary)
                        }
                    } else {
                        Text(message.text)
                            .font(.system(size: fontSize))
                            .textSelection(.enabled)
                    }
                }
                .padding(.horizontal, compact ? 10 : 14)
                .padding(.vertical, compact ? 6 : 10)
                .background(
                    message.role == .user
                        ? Color.accentColor.opacity(0.18)
                        : Color.secondary.opacity(0.12)
                )
                .clipShape(RoundedRectangle(cornerRadius: compact ? 8 : 12, style: .continuous))

                if showTimestamp {
                    Text(message.timestamp.formatted(date: .omitted, time: .shortened))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
            if message.role == .assistant { Spacer(minLength: 40) }
        }
    }
}
