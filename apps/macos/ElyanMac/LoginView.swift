import SwiftUI
import AuthenticationServices
import GoogleSignIn

/// First-run authentication gate. Email/password login + register, against the
/// same /v1/auth endpoints the mobile app uses, so credentials, account, and
/// brain context are shared exactly with mobile.
struct LoginView: View {
    @EnvironmentObject var appState: AppState
    @State private var mode: Mode = .login
    @State private var email = ""
    @State private var password = ""
    @State private var displayName = ""
    @State private var termsAccepted = false
    @State private var privacyAccepted = false
    @State private var error: String = ""
    @State private var isWorking = false

    enum Mode { case login, register }

    var body: some View {
        GeometryReader { proxy in
            let isNarrow = proxy.size.width < 600
            
            if isNarrow {
                VStack(spacing: 0) {
                    heroImage
                        .frame(height: proxy.size.height * 0.35)
                    formContainer
                        .frame(maxHeight: .infinity)
                }
            } else {
                HStack(spacing: 0) {
                    formContainer
                        .frame(width: max(320, proxy.size.width * 0.45))
                    heroImage
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .ignoresSafeArea(.container, edges: .top)
                }
            }
        }
        .frame(minWidth: 400, minHeight: 600)
    }
    
    private var heroImage: some View {
        Image("LoginHero")
            .resizable()
            .aspectRatio(contentMode: .fill)
            .clipped()
    }
    
    private var formContainer: some View {
        ZStack {
            Color(NSColor.windowBackgroundColor).ignoresSafeArea()
            
            ScrollView {
                VStack(spacing: 24) {
                    // Logo
                    Image("Logo")
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 72, height: 72)
                    
                    VStack(spacing: 8) {
                        Text("Elyan'a Hoş Geldiniz")
                            .font(.system(size: 28, weight: .bold, design: .rounded))
                            .multilineTextAlignment(.center)
                        
                        Text(mode == .login ? "Hesabınızla giriş yapın" : "Yeni bir hesap oluşturun")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }

                    VStack(spacing: 16) {
                        if mode == .register {
                            customTextField("Görünen ad", text: $displayName)
                        }
                        customTextField("E-posta", text: $email, isEmail: true)
                        customSecureField("Şifre", text: $password)

                        if mode == .register {
                            VStack(alignment: .leading, spacing: 8) {
                                Toggle("Kullanım koşullarını kabul ediyorum", isOn: $termsAccepted)
                                Toggle("Gizlilik politikasını kabul ediyorum", isOn: $privacyAccepted)
                            }
                            .font(.footnote)
                            .toggleStyle(.checkbox)
                            .padding(.vertical, 4)
                        }
                    }
                    .frame(maxWidth: 300)

                    if !error.isEmpty {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(.red)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: 300)
                    }

                    Button(action: submit) {
                        HStack {
                            if isWorking { ProgressView().controlSize(.small) }
                            Text(mode == .login ? "Giriş yap" : "Hesap oluştur")
                                .font(.system(size: 14, weight: .semibold))
                                .frame(maxWidth: .infinity)
                        }
                        .padding(.vertical, 12)
                        .background(canSubmit ? Color.accentColor : Color.gray.opacity(0.3))
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .disabled(isWorking || !canSubmit)
                    .frame(maxWidth: 300)

                    VStack(spacing: 12) {
                        HStack {
                            VStack { Divider() }
                            Text("veya").font(.footnote).foregroundStyle(.secondary)
                            VStack { Divider() }
                        }
                        .frame(maxWidth: 300)

                        // OAuth Buttons
                        HStack(spacing: 12) {
                            SignInWithAppleButton(.signIn) { request in
                                request.requestedScopes = [.fullName, .email]
                            } onCompletion: { result in
                                switch result {
                                case .success(let auth):
                                    loginWithApple(auth: auth)
                                case .failure(let error):
                                    if (error as NSError).code != ASAuthorizationError.canceled.rawValue {
                                        self.error = error.localizedDescription
                                    }
                                }
                            }
                            .signInWithAppleButtonStyle(.whiteOutline)
                            .frame(height: 40)
                            .frame(maxWidth: .infinity)

                            Button(action: { loginWithGoogle() }) {
                                HStack {
                                    Image(systemName: "g.circle.fill")
                                    Text("Google")
                                }
                                .font(.system(size: 14, weight: .medium))
                                .frame(maxWidth: .infinity)
                                .frame(height: 40)
                                .background(Color(NSColor.controlBackgroundColor))
                                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                                        .strokeBorder(Color.gray.opacity(0.3), lineWidth: 1)
                                )
                            }
                            .buttonStyle(.plain)
                        }
                        .frame(maxWidth: 300)
                    }
                    .padding(.top, 4)

                    Button {
                        withAnimation {
                            error = ""
                            mode = (mode == .login ? .register : .login)
                        }
                    } label: {
                        Text(mode == .login
                            ? "Hesabın yok mu? Hesap oluştur"
                            : "Zaten hesabın var mı? Giriş yap")
                            .font(.footnote)
                            .foregroundStyle(.tint)
                    }
                    .buttonStyle(.plain)
                    .padding(.top, 16)
                }
                .padding(40)
            }
        }
    }

    private func customTextField(_ placeholder: String, text: Binding<String>, isEmail: Bool = false) -> some View {
        TextField(placeholder, text: text)
            .textFieldStyle(.plain)
            .padding(12)
            .background(Color(NSColor.controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(Color.gray.opacity(0.2), lineWidth: 1)
            )
            .textContentType(isEmail ? .emailAddress : .none)
            .disableAutocorrection(true)
    }
    
    private func customSecureField(_ placeholder: String, text: Binding<String>) -> some View {
        SecureField(placeholder, text: text)
            .textFieldStyle(.plain)
            .padding(12)
            .background(Color(NSColor.controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(Color.gray.opacity(0.2), lineWidth: 1)
            )
            .textContentType(mode == .login ? .password : .newPassword)
    }

    private var canSubmit: Bool {
        let hasCredentials = !email.trimmingCharacters(in: .whitespaces).isEmpty
            && !password.isEmpty
        if mode == .login { return hasCredentials }
        return hasCredentials
            && !displayName.trimmingCharacters(in: .whitespaces).isEmpty
            && termsAccepted
            && privacyAccepted
    }

    private func submit() {
        error = ""
        isWorking = true
        Task {
            defer { isWorking = false }
            do {
                if mode == .login {
                    _ = try await appState.backend.login(email: email, password: password)
                } else {
                    _ = try await appState.backend.register(
                        displayName: displayName,
                        email: email,
                        password: password,
                        termsAccepted: termsAccepted,
                        privacyAccepted: privacyAccepted
                    )
                }
            } catch {
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
        }
    }

    private func loginWithApple(auth: ASAuthorization) {
        if let appleIDCredential = auth.credential as? ASAuthorizationAppleIDCredential {
            let idToken = appleIDCredential.identityToken.flatMap { String(data: $0, encoding: .utf8) } ?? ""
            let authCode = appleIDCredential.authorizationCode.flatMap { String(data: $0, encoding: .utf8) } ?? ""
            let email = appleIDCredential.email
            let name = appleIDCredential.fullName.flatMap {
                [$0.givenName, $0.familyName].compactMap { $0 }.joined(separator: " ")
            }

            guard !idToken.isEmpty else {
                self.error = "Apple kimlik doğrulama belgesi alınamadı. Lütfen e-posta/şifre ile giriş yapın."
                return
            }

            error = ""
            isWorking = true
            Task {
                defer { isWorking = false }
                do {
                    _ = try await appState.backend.loginWithOAuth(
                        provider: "apple",
                        idToken: idToken,
                        email: email,
                        displayName: name?.isEmpty == false ? name : nil,
                        authorizationCode: authCode.isEmpty ? nil : authCode,
                        termsAccepted: termsAccepted,
                        privacyAccepted: privacyAccepted
                    )
                } catch {
                    self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                }
            }
        }
    }

    private func loginWithGoogle() {
        guard let window = NSApp.keyWindow ?? NSApp.mainWindow else {
            error = "Google giriş penceresi açılamadı."
            return
        }

        error = ""
        isWorking = true
        GIDSignIn.sharedInstance.configuration = GIDConfiguration(
            clientID: DesktopAppConfig.googleClientID,
            serverClientID: DesktopAppConfig.googleServerClientID
        )
        GIDSignIn.sharedInstance.signIn(withPresenting: window) { result, signInError in
            Task { @MainActor in
                defer { isWorking = false }

                if let signInError {
                    self.error = signInError.localizedDescription
                    return
                }

                guard let result else {
                    self.error = "Google hesabı doğrulanamadı."
                    return
                }

                let idToken = result.user.idToken?.tokenString ?? ""
                guard !idToken.isEmpty else {
                    self.error = "Google kimlik belirteci alınamadı."
                    return
                }

                do {
                    _ = try await appState.backend.loginWithOAuth(
                        provider: "google",
                        idToken: idToken,
                        email: result.user.profile?.email,
                        displayName: result.user.profile?.name,
                        termsAccepted: termsAccepted,
                        privacyAccepted: privacyAccepted
                    )
                } catch {
                    self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                }
            }
        }
    }
}
