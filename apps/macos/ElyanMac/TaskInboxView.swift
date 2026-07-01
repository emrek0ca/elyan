import SwiftUI

/// Shows tasks the mobile app has dispatched to this desktop. AppState polls
/// GET /v1/runtime/tasks/assigned every ~10s and auto-acks new ones as
/// "running" so the mobile UI advances out of "sırada". The user then closes
/// each task manually with Tamamlandı / Reddet — the native app doesn't run
/// desktop capabilities on its own yet.
struct TaskInboxView: View {
    @EnvironmentObject var appState: AppState

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
                            onComplete: {
                                Task { await appState.resolveTask(task, completed: true) }
                            },
                            onReject: {
                                Task { await appState.resolveTask(task, completed: false) }
                            })
                }
            }
            .padding(20)
        }
    }
}

private struct TaskRow: View {
    let task: ElyanRuntimeTask
    let onComplete: () -> Void
    let onReject: () -> Void

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
            HStack(spacing: 8) {
                Button("Reddet", role: .destructive, action: onReject)
                    .buttonStyle(.bordered)
                Spacer()
                Button("Tamamlandı", action: onComplete)
                    .buttonStyle(.borderedProminent)
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
