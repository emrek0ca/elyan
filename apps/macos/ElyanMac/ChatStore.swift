import Foundation
import SwiftUI

/// Owns the live conversation: sends user messages through ElyanBackend's
/// /v1/chat/messages, then opens an SSE stream and feeds delta tokens into
/// the in-progress assistant message until the server says it's done.
///
/// One-to-one with the mobile pipeline (POST → SSE deltas → completed).
@MainActor
final class ChatStore: ObservableObject {

    @Published private(set) var messages: [ChatMessage] = []
    @Published private(set) var isStreaming = false
    @Published private(set) var sessionId: String?
    @Published var lastError: String = ""

    private let backend: ElyanBackend
    private let sseClient = ElyanSSEClient()
    private var streamingAssistantId: UUID?

    init(backend: ElyanBackend) {
        self.backend = backend
    }

    func reset() {
        Task { await sseClient.cancel() }
        messages.removeAll()
        streamingAssistantId = nil
        isStreaming = false
        sessionId = nil
        lastError = ""
    }

    /// Posts the user prompt to the backend, then subscribes to its task stream.
    func send(_ prompt: String) async {
        let trimmed = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // Cancel any in-flight stream — we're starting a new turn.
        await sseClient.cancel()

        let userMessage = ChatMessage(role: .user, text: trimmed)
        messages.append(userMessage)
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
            }
            guard let token = backend.session?.accessToken, !token.isEmpty else {
                throw ElyanBackendError.notAuthenticated
            }
            await subscribe(taskId: dispatch.taskId, token: token)
        } catch {
            await finishStreaming(withFailure: error)
        }
    }

    private func subscribe(taskId: String, token: String) async {
        await sseClient.open(
            accessToken: token,
            taskId: taskId,
            onEvent: { [weak self] event in
                await self?.handle(event: event)
            },
            onError: { [weak self] error in
                await self?.finishStreaming(withFailure: error)
            },
            onClose: { [weak self] in
                await self?.streamDidClose()
            }
        )
    }

    private func handle(event: ElyanSSEEvent) async {
        switch event.event {
        case "chat.message.delta":
            if let text = Self.extractAssistantText(from: event.data) {
                appendDelta(text)
            }
        case "chat.message.updated":
            if let text = Self.extractAssistantText(from: event.data), !text.isEmpty {
                replaceAssistant(text)
            }
            // The mobile flow ends the turn on message.updated/completed.
            finishStreamingSuccessfully()
        case "chat.message.created":
            // Server confirms the turn started; nothing UI-visible needed here.
            break
        case "chat.heartbeat":
            // Liveness signal; ignore.
            break
        default:
            // Unknown event — surface raw text if the server sent something.
            if let text = Self.extractAssistantText(from: event.data) {
                appendDelta(text)
            }
        }
    }

    private func appendDelta(_ delta: String) {
        guard let id = streamingAssistantId,
              let index = messages.firstIndex(where: { $0.id == id }) else { return }
        messages[index].text.append(delta)
    }

    private func replaceAssistant(_ text: String) {
        guard let id = streamingAssistantId,
              let index = messages.firstIndex(where: { $0.id == id }) else { return }
        messages[index].text = text
    }

    private func finishStreamingSuccessfully() {
        isStreaming = false
        streamingAssistantId = nil
    }

    private func finishStreaming(withFailure error: Error) async {
        await sseClient.cancel()
        let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        lastError = message
        if let id = streamingAssistantId,
           let index = messages.firstIndex(where: { $0.id == id }) {
            if messages[index].text.isEmpty {
                messages[index].text = "Hata: \(message)"
            } else {
                messages[index].text.append("\n\nHata: \(message)")
            }
        }
        isStreaming = false
        streamingAssistantId = nil
    }

    private func streamDidClose() async {
        // The connection closed without an explicit completion event. If we
        // never received any text, surface a soft error so the user isn't
        // left staring at an empty bubble.
        guard isStreaming else { return }
        if let id = streamingAssistantId,
           let index = messages.firstIndex(where: { $0.id == id }),
           messages[index].text.isEmpty {
            messages[index].text = "Yanıt alınamadı."
        }
        isStreaming = false
        streamingAssistantId = nil
    }

    /// Walks the assistant payload the server sends in delta/updated events
    /// and pulls out either the streamed markdown text or the rendered
    /// content, matching the fields mobile reads in task_controller.dart.
    private static func extractAssistantText(from data: [String: Any]) -> String? {
        // Prefer the assistant sub-object — server uses `delta` for streaming
        // additions and `content` for the cumulative final text.
        if let assistant = data["assistant"] as? [String: Any] {
            if let delta = assistant["delta"] as? String, !delta.isEmpty { return delta }
            if let content = assistant["content"] as? String, !content.isEmpty { return content }
            if let message = assistant["message"] as? String, !message.isEmpty { return message }
            if let blocks = assistant["blocks"] as? [[String: Any]] {
                if let combined = combinedMarkdown(from: blocks) { return combined }
            }
        }
        if let delta = data["delta"] as? String, !delta.isEmpty { return delta }
        if let content = data["content"] as? String, !content.isEmpty { return content }
        if let message = data["message"] as? String, !message.isEmpty { return message }
        if let blocks = data["blocks"] as? [[String: Any]],
           let combined = combinedMarkdown(from: blocks) {
            return combined
        }
        return nil
    }

    private static func combinedMarkdown(from blocks: [[String: Any]]) -> String? {
        var pieces: [String] = []
        for block in blocks {
            if let md = block["markdown"] as? String, !md.isEmpty { pieces.append(md) }
            else if let text = block["text"] as? String, !text.isEmpty { pieces.append(text) }
        }
        return pieces.isEmpty ? nil : pieces.joined(separator: "\n\n")
    }
}

struct ChatMessage: Identifiable, Equatable {
    enum Role: String { case user, assistant }
    let id = UUID()
    let role: Role
    var text: String
    let timestamp: Date
    
    init(role: Role, text: String) {
        self.role = role
        self.text = text
        self.timestamp = Date()
    }
}
