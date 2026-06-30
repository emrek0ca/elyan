import SwiftUI

/// Presented as a sheet when a mobile-dispatched task is waiting for local
/// confirmation (status == "waiting_approval"). Shows the real approval
/// request the bridge prepared (title/message/labels), not placeholder copy.
struct TaskApprovalView: View {
    let task: RuntimeTaskItem
    let onApprove: () -> Void
    let onDeny: () -> Void

    private var approval: RuntimeApprovalRequest? { task.approvalRequest }

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "exclamationmark.shield.fill")
                .resizable()
                .frame(width: 44, height: 44)
                .foregroundColor(.orange)

            VStack(spacing: 8) {
                Text(approval?.title ?? "Onay gerekli")
                    .font(.headline)

                let detail: String = {
                    if let message = approval?.message, !message.isEmpty { return message }
                    return task.summary
                }()
                if !detail.isEmpty {
                    Text(detail)
                        .font(.callout)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: 12) {
                Button(approval?.rejectLabel ?? "Reddet") {
                    onDeny()
                }
                .buttonStyle(.bordered)

                Button(approval?.confirmLabel ?? "Onayla") {
                    onApprove()
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(28)
        .frame(minWidth: 360, maxWidth: 460)
        .background(Material.thick)
        .cornerRadius(12)
        .shadow(radius: 10)
    }
}
