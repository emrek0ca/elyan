import SwiftUI

struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @State private var selection: NavItem = .chat
    @AppStorage("colorScheme") private var storedScheme: String = "system"

    enum NavItem: String, CaseIterable, Identifiable {
        case chat, history, pairing, settings
        var id: String { rawValue }

        var label: String {
            switch self {
            case .chat: return "Sohbet"
            case .history: return "Geçmiş"
            case .pairing: return "Eşleştirme"
            case .settings: return "Ayarlar"
            }
        }
        var icon: String {
            switch self {
            case .chat: return "bubble.left.and.bubble.right.fill"
            case .history: return "clock.fill"
            case .pairing: return "iphone.and.arrow.forward.outward"
            case .settings: return "gearshape.fill"
            }
        }
    }

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            detailView
        }
        .frame(minWidth: 820, minHeight: 580)
        .onAppear {
            // Re-apply saved theme on app open
            applyStoredScheme()
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        VStack(spacing: 0) {
            // Logo
            VStack(spacing: 8) {
                Image("Logo")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 40, height: 40)
                Text("Elyan")
                    .font(.system(size: 15, weight: .bold, design: .rounded))
            }
            .padding(.top, 20)
            .padding(.bottom, 12)

            Divider()
                .padding(.horizontal, 12)
                .padding(.bottom, 8)

            // Navigation items
            ForEach(NavItem.allCases) { item in
                SidebarNavButton(
                    item: item,
                    isSelected: selection == item,
                    badge: item == .chat && appState.supervisor.pendingTaskCount > 0
                        ? appState.supervisor.pendingTaskCount : 0
                ) {
                    selection = item
                }
            }

            Spacer()

            Divider()
                .padding(.horizontal, 12)
                .padding(.top, 8)

            // User info + status
            HStack(spacing: 10) {
                ZStack {
                    Circle()
                        .fill(Color.accentColor.opacity(0.15))
                        .frame(width: 32, height: 32)
                    Text((appState.backend.session?.displayName ?? "E").prefix(1).uppercased())
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(.tint)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(appState.backend.session?.displayName ?? "Kullanıcı")
                        .font(.caption.weight(.medium))
                        .lineLimit(1)
                    HStack(spacing: 4) {
                        Circle()
                            .fill(appState.backend.isSignedIn ? Color.green : Color.orange)
                            .frame(width: 6, height: 6)
                        Text(appState.backend.isSignedIn ? "Bağlı" : "Çevrimdışı")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
        }
        .frame(width: 190)
        .background(.bar)
    }

    // MARK: - Detail

    @ViewBuilder
    private var detailView: some View {
        switch selection {
        case .chat:
            ChatView()
                .environmentObject(appState)
        case .history:
            SessionHistoryView()
                .environmentObject(appState)
        case .pairing:
            PairingView()
                .environmentObject(appState)
        case .settings:
            SettingsView()
                .environmentObject(appState)
        }
    }

    private func applyStoredScheme() {
        guard let app = NSApplication.shared.windows.first else { return }
        switch storedScheme {
        case "light": app.appearance = NSAppearance(named: .aqua)
        case "dark": app.appearance = NSAppearance(named: .darkAqua)
        default: app.appearance = nil
        }
    }
}

// MARK: - Sidebar Button

private struct SidebarNavButton: View {
    let item: ContentView.NavItem
    let isSelected: Bool
    let badge: Int
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                ZStack(alignment: .topTrailing) {
                    Image(systemName: item.icon)
                        .font(.system(size: 14, weight: isSelected ? .semibold : .regular))
                        .frame(width: 22)
                    if badge > 0 {
                        Text("\(badge)")
                            .font(.system(size: 9, weight: .bold))
                            .padding(3)
                            .background(Color.red)
                            .foregroundStyle(.white)
                            .clipShape(Circle())
                            .offset(x: 8, y: -6)
                    }
                }
                Text(item.label)
                    .font(.system(size: 13, weight: isSelected ? .semibold : .regular))
                Spacer()
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(isSelected ? Color.accentColor.opacity(0.15) : Color.clear)
            .foregroundStyle(isSelected ? Color.accentColor : Color.primary)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 8)
        .padding(.vertical, 2)
    }
}
