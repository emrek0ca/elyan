import SwiftUI

/// Ana ayarlar ekranı — mobil'in SettingsScreen navigasyon listesiyle aynı kategorileri sunar.
struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var permissions = PermissionPolicyViewModel()

    var body: some View {
        List {
            // Profil özeti
            Section {
                NavigationLink(destination: ProfileSettingsView().environmentObject(appState)) {
                    HStack(spacing: 14) {
                        ZStack {
                            Circle()
                                .fill(Color.accentColor.opacity(0.15))
                                .frame(width: 48, height: 48)
                            Text((appState.backend.session?.displayName ?? "E").prefix(1).uppercased())
                                .font(.system(size: 20, weight: .bold))
                                .foregroundStyle(.tint)
                        }
                        VStack(alignment: .leading, spacing: 3) {
                            Text(appState.backend.session?.displayName ?? "Kullanıcı")
                                .font(.body.weight(.medium))
                            Text(appState.backend.session?.email ?? "")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 6)
                }
            }

            // Kategoriler
            Section("Uygulama") {
                NavigationLink(destination: BillingView().environmentObject(appState)) {
                    Label("Abonelik", systemImage: "creditcard")
                }
                NavigationLink(destination: AppearanceSettingsView()) {
                    Label("Görünüm", systemImage: "paintbrush")
                }
                NavigationLink(destination: PairingView().environmentObject(appState)) {
                    Label("Masaüstü Eşleştirme", systemImage: "iphone.and.arrow.forward.outward")
                }
            }

            Section("Sistem") {
                runtimeRow
                NavigationLink(destination: permissionsDetail) {
                    Label("İzinler", systemImage: "shield.lefthalf.filled")
                }
            }

            Section {
                Button(role: .destructive) {
                    Task {
                        appState.chat.reset()
                        await appState.backend.logout()
                    }
                } label: {
                    Label("Çıkış Yap", systemImage: "rectangle.portrait.and.arrow.right")
                        .foregroundStyle(.red)
                }
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("Ayarlar")
        .onAppear { permissions.checkPermissions() }
    }

    private var runtimeRow: some View {
        HStack {
            Label("Python Runtime", systemImage: "cpu")
            Spacer()
            HStack(spacing: 6) {
                Circle()
                    .fill(appState.supervisor.runtimeReady ? Color.green : Color.orange)
                    .frame(width: 8, height: 8)
                Text(appState.supervisor.runtimeReady ? "Hazır" : appState.supervisor.lifecycleState)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var permissionsDetail: some View {
        Form {
            Section("macOS İzinleri") {
                HStack {
                    Text("Erişilebilirlik")
                    Spacer()
                    Text(permissions.requiresAccessibility ? "İzin Gerekli" : "Verildi")
                        .foregroundColor(permissions.requiresAccessibility ? .orange : .green)
                }
                if permissions.requiresAccessibility {
                    Button("Sistem Tercihleri'ni Aç") {
                        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle("İzinler")
    }
}
