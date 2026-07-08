import SwiftUI

/// Profil ve hesap ayarları — mobil'in SettingsScreen profil bölümüne karşılık gelir.
struct ProfileSettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var displayName: String = ""
    @State private var isSaving = false
    @State private var saveError: String = ""
    @State private var saveSuccess = false
    @State private var showDeleteConfirm = false
    @State private var passwordError: String = ""
    @State private var passwordSuccess = false
    @State private var currentPassword = ""
    @State private var newPassword = ""
    @State private var confirmPassword = ""
    @State private var isChangingPassword = false
    @State private var tab: Tab = .profile

    enum Tab { case profile, security }

    var body: some View {
        ScrollView {
            VStack(spacing: 28) {
                Picker("", selection: $tab) {
                    Text("Profil").tag(Tab.profile)
                    Text("Güvenlik").tag(Tab.security)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 8)

                if tab == .profile {
                    profileSection
                } else {
                    securitySection
                }
            }
            .padding(24)
        }
        .navigationTitle("Hesap")
        .onAppear {
            displayName = appState.backend.session?.displayName ?? ""
        }
    }

    // MARK: - Profile Section

    private var profileSection: some View {
        VStack(spacing: 20) {
            // Avatar placeholder
            ZStack {
                Circle()
                    .fill(Color.accentColor.opacity(0.15))
                    .frame(width: 80, height: 80)
                Text(displayName.prefix(1).uppercased())
                    .font(.system(size: 32, weight: .bold))
                    .foregroundStyle(.tint)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Görünen Ad")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TextField("İsim girin", text: $displayName)
                    .textFieldStyle(.roundedBorder)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("E-posta")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(appState.backend.session?.email ?? "—")
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.secondary.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }

            if !saveError.isEmpty {
                Text(saveError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }
            if saveSuccess {
                HStack {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                    Text("Profil güncellendi").foregroundStyle(.green)
                }
                .font(.callout)
            }

            Button(action: saveProfile) {
                HStack {
                    if isSaving { ProgressView().controlSize(.small) }
                    Text("Kaydet")
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .background(Color.accentColor)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(isSaving || displayName.trimmingCharacters(in: .whitespaces).isEmpty)

            Divider()

            // Danger zone
            VStack(spacing: 12) {
                Text("Tehlikeli Bölge")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button(role: .destructive) {
                    showDeleteConfirm = true
                } label: {
                    Text("Hesabı Sil")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(Color.red.opacity(0.1))
                        .foregroundStyle(.red)
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
                .buttonStyle(.plain)
            }
        }
        .confirmationDialog("Hesabını kalıcı olarak silmek istediğine emin misin?",
                            isPresented: $showDeleteConfirm,
                            titleVisibility: .visible) {
            Button("Hesabı Sil", role: .destructive) {
                Task { await deleteAccount() }
            }
            Button("İptal", role: .cancel) {}
        }
    }

    // MARK: - Security Section

    private var securitySection: some View {
        VStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Mevcut Şifre")
                    .font(.caption).foregroundStyle(.secondary)
                SecureField("••••••••", text: $currentPassword)
                    .textFieldStyle(.roundedBorder)
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("Yeni Şifre")
                    .font(.caption).foregroundStyle(.secondary)
                SecureField("En az 8 karakter", text: $newPassword)
                    .textFieldStyle(.roundedBorder)
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("Yeni Şifre (Tekrar)")
                    .font(.caption).foregroundStyle(.secondary)
                SecureField("Yeni şifre ile aynı", text: $confirmPassword)
                    .textFieldStyle(.roundedBorder)
            }

            if !passwordError.isEmpty {
                Text(passwordError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }
            if passwordSuccess {
                HStack {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                    Text("Şifre başarıyla güncellendi").foregroundStyle(.green)
                }
                .font(.callout)
            }

            Button(action: changePassword) {
                HStack {
                    if isChangingPassword { ProgressView().controlSize(.small) }
                    Text("Şifreyi Güncelle")
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .background(Color.accentColor)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(isChangingPassword || currentPassword.isEmpty || newPassword.count < 8)
        }
    }

    // MARK: - Actions

    private func saveProfile() {
        saveError = ""
        saveSuccess = false
        isSaving = true
        Task {
            defer { isSaving = false }
            do {
                _ = try await appState.backend.updateProfile(displayName: displayName)
                saveSuccess = true
            } catch {
                saveError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
        }
    }

    private func changePassword() {
        passwordError = ""
        passwordSuccess = false
        guard newPassword == confirmPassword else {
            passwordError = "Yeni şifreler eşleşmiyor."
            return
        }
        guard newPassword.count >= 8 else {
            passwordError = "Yeni şifre en az 8 karakter olmalı."
            return
        }
        isChangingPassword = true
        Task {
            defer { isChangingPassword = false }
            do {
                _ = try await appState.backend.postJSON(
                    path: "/v1/auth/password",
                    body: ["currentPassword": currentPassword, "nextPassword": newPassword],
                    requireAuth: true
                )
                currentPassword = ""
                newPassword = ""
                confirmPassword = ""
                passwordSuccess = true
            } catch {
                passwordError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
        }
    }

    private func deleteAccount() async {
        do {
            _ = try await appState.backend.deleteJSON(path: "/v1/auth/me", requireAuth: true)
            await appState.backend.logout()
        } catch {
            saveError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}
