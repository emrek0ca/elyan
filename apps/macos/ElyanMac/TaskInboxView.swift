import SwiftUI

/// Shows tasks the mobile app has dispatched to this desktop. Assignment is
/// SSE-pushed (`AppState.refreshAssignedTasks`, triggered by task/command/
/// runtime realtime events) rather than polled; the Python runtime is the
/// sole executor when operational (`supervisor.executeAssignedTasks()`) and
/// Swift only auto-acks as a degraded fallback when the runtime isn't
/// available (see AppState.refreshAssignedTasks). Runtime completion is
/// evidence-driven; the UI can cancel or approve but cannot fabricate a
/// completed state. A task the runtime marked
/// `waiting_approval` gets a real approve/deny sheet wired to
/// `supervisor.approveTask` instead.
struct TaskInboxView: View {
    @EnvironmentObject var appState: AppState
    @State private var approvalItem: RuntimeTaskItem?

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if appState.assignedTasks.isEmpty {
                emptyState
            } else {
                list
            }
        }
        .background(Color(NSColor.windowBackgroundColor))
        .task { await appState.refreshAssignedTasks() }
        .sheet(item: $approvalItem) { item in
            TaskApprovalView(
                task: item,
                onApprove: {
                    Task {
                        await appState.supervisor.approveTask(taskId: item.id, approved: true)
                        approvalItem = nil
                        await appState.refreshAssignedTasks()
                    }
                },
                onDeny: {
                    Task {
                        await appState.supervisor.approveTask(taskId: item.id, approved: false)
                        approvalItem = nil
                        await appState.refreshAssignedTasks()
                    }
                }
            )
        }
    }

    /// The Python bridge's own task inbox is the authoritative source for
    /// `approvalRequest` payloads (title/message/labels) — the REST
    /// `ElyanRuntimeTask` model the list above renders from doesn't carry
    /// that detail. Match by id to find the matching bridge-side record.
    private func approvalItem(for task: ElyanRuntimeTask) -> RuntimeTaskItem? {
        guard task.status.lowercased() == "waiting_approval" else { return nil }
        return appState.supervisor.taskInbox.first { $0.id == task.id && $0.isWaitingApproval }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Mobilden görevler")
                    .font(.title3.bold())
                Text("Telefondan gönderilen işler burada listelenir.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button {
                Task { await appState.refreshAssignedTasks() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
        }
        .padding(20)
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Spacer(minLength: 40)
            Image(systemName: "tray")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(.tertiary)
            Text("Henüz görev yok")
                .font(.headline)
            Text("Mobilde bir görev gönderdiğinde burada görürsün.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 320)
            if !appState.lastDispatchError.isEmpty {
                Text(appState.lastDispatchError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding(.top, 8)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 360)
            }
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(24)
    }

    private var list: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(appState.assignedTasks) { task in
                    TaskRow(task: task,
                            pendingApproval: approvalItem(for: task),
                            onReview: { item in
                                approvalItem = item
                            })
                }
            }
            .padding(20)
        }
    }
}

private struct TaskRow: View {
    let task: ElyanRuntimeTask
    var pendingApproval: RuntimeTaskItem? = nil
    var onReview: (RuntimeTaskItem) -> Void = { _ in }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                Circle()
                    .fill(statusColor.opacity(0.2))
                    .frame(width: 10, height: 10)
                    .padding(.top, 6)
                VStack(alignment: .leading, spacing: 4) {
                    Text(task.title)
                        .font(.system(size: 14, weight: .semibold))
                    if !task.summary.isEmpty {
                        Text(task.summary)
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                    Text(statusLabel)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(statusColor)
                }
                Spacer()
            }
            if !task.error.isEmpty {
                Text(task.error)
                    .font(.system(size: 11))
                    .foregroundStyle(.red)
            }
            if let pendingApproval {
                HStack(spacing: 8) {
                    Spacer()
                    Button("İncele ve Onayla") { onReview(pendingApproval) }
                        .buttonStyle(.borderedProminent)
                }
            }
        }
        .padding(14)
        .background(Color(NSColor.controlBackgroundColor).opacity(0.6))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }

    private var statusColor: Color {
        switch task.status.lowercased() {
        case "completed": return .green
        case "failed", "canceled": return .red
        case "waiting_approval": return .orange
        default: return .accentColor
        }
    }

    private var statusLabel: String {
        switch task.status.lowercased() {
        case "queued": return "Sırada"
        case "running", "planning": return "Çalışıyor"
        case "waiting_approval": return "Onay bekliyor"
        case "completed": return "Tamamlandı"
        case "failed": return "Başarısız"
        case "canceled": return "İptal edildi"
        default: return task.status.capitalized
        }
    }
}
