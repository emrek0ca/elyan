import SwiftUI

struct TaskInboxView: View {
    @EnvironmentObject var appState: AppState
    @State private var approvalTarget: RuntimeTaskItem?

    private var supervisor: PythonRuntimeSupervisor { appState.supervisor }

    var body: some View {
        List {
            Section(header: Text("Active Tasks")) {
                if supervisor.taskInbox.isEmpty {
                    Text(supervisor.backendReady ? "Mobilden henüz görev gelmedi." : "Backend bağlantısı bekleniyor.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(supervisor.taskInbox) { item in
                        TaskInboxRow(item: item) {
                            approvalTarget = item
                        }
                    }
                }
            }
            Section(header: Text("Connection")) {
                HStack {
                    Text(supervisor.backendReady ? "Backend connected" : "Backend waiting")
                    Spacer()
                    if supervisor.isExecutingAssignedTasks {
                        ProgressView()
                            .controlSize(.small)
                    }
                }
                if !supervisor.runtimeLifecycleState.isEmpty {
                    HStack {
                        Text("Pairing")
                        Spacer()
                        Text(supervisor.runtimeLifecycleState)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .listStyle(SidebarListStyle())
        .background(Material.thin)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await supervisor.executeAssignedTasks() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .disabled(!supervisor.isRunning)
            }
        }
        .sheet(item: $approvalTarget) { task in
            TaskApprovalView(
                task: task,
                onApprove: {
                    approvalTarget = nil
                    Task { await supervisor.approveTask(taskId: task.id, approved: true) }
                },
                onDeny: {
                    approvalTarget = nil
                    Task { await supervisor.approveTask(taskId: task.id, approved: false) }
                }
            )
        }
        .task {
            await supervisor.refreshAll()
        }
    }
}

private struct TaskInboxRow: View {
    let item: RuntimeTaskItem
    let onReview: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                Text(item.title)
                    .font(.body)
                Spacer()
                TaskStatusBadge(status: item.status)
            }

            if !item.summary.isEmpty {
                Text(item.summary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            if !item.error.isEmpty {
                Text(item.error)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .lineLimit(2)
            }

            if item.isWaitingApproval {
                Button("Review", action: onReview)
                    .buttonStyle(.bordered)
                    .controlSize(.small)
            }
        }
        .padding(.vertical, 4)
    }
}

private struct TaskStatusBadge: View {
    let status: String

    private var label: String {
        switch status {
        case "queued": return "Sırada"
        case "planning": return "Planlanıyor"
        case "running": return "Çalışıyor"
        case "waiting_approval": return "Onay bekliyor"
        case "completed": return "Tamamlandı"
        case "failed": return "Başarısız"
        case "canceled": return "İptal"
        default: return status.capitalized
        }
    }

    private var color: Color {
        switch status {
        case "completed": return .green
        case "failed": return .red
        case "canceled": return .gray
        case "waiting_approval": return .orange
        case "running", "planning": return .blue
        default: return .secondary
        }
    }

    var body: some View {
        Text(label)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
}
