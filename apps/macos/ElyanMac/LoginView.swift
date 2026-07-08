import SwiftUI
import AuthenticationServices
import GoogleSignIn

struct LoginView: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.colorScheme) private var colorScheme
    @State private var mode: Mode = .login
    @State private var email = ""
    @State private var password = ""
    @State private var displayName = ""
    @State private var termsAccepted = false
    @State private var privacyAccepted = false
    @State private var error: String = ""
    @State private var isWorking = false
    @State private var isHoveringGoogle = false
    @State private var isHoveringSubmit = false

    enum Mode { case login, register }

    var body: some View {
        GeometryReader { proxy in
            let isNarrow = proxy.size.width < 760

            if isNarrow {
                VStack(spacing: 0) {
                    heroPane
                        .frame(height: max(260, proxy.size.height * 0.42))
                    formContainer
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .ignoresSafeArea()
            } else {
                HStack(spacing: 0) {
                    formContainer
                        .frame(maxWidth: .infinity, maxHeight: .infinity)

                    heroPane
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .ignoresSafeArea()
            }
        }
        .frame(minWidth: 760, minHeight: 620)
        .background(ElyanTheme.canvas)
    }

    private var heroPane: some View {
        // GeometryReader gives the image the pane's EXACT size, so scaledToFill
        // fills edge-to-edge (bleeds off any gradient/background). Without this
        // SwiftUI resolves Image against its natural size and leaves side bands
        // of the parent showing through.
        GeometryReader { geo in
            Image("LoginHero")
                .resizable()
                .interpolation(.high)
                .antialiased(true)
                .scaledToFill()
                .frame(width: geo.size.width, height: geo.size.height)
                .clipped()
        }
        .background(Color.black)
    }
    
    private var formContainer: some View {
        ZStack {
            ElyanTheme.canvas
            
            ScrollView(.vertical, showsIndicators: false) {
                VStack(spacing: 32) {
                    // Logo & Header
                    VStack(spacing: 16) {
                        Image("Logo")
                            .renderingMode(.template)
                            .resizable()
                            .aspectRatio(contentMode: .fit)
                            .frame(width: 80, height: 80)
                            // Tint the (templated) logo — white on dark, brand on light.
                            .foregroundStyle(colorScheme == .dark ? Color.white : Color.accentColor)
                            .shadow(color: Color.accentColor.opacity(0.3), radius: 20, x: 0, y: 10)
                        
                        VStack(spacing: 8) {
                            Text("Elyan'a Hoş Geldiniz")
                                .font(.system(size: 32, weight: .bold, design: .rounded))
                                .multilineTextAlignment(.center)
                            
                            Text(mode == .login ? "Hesabınızla giriş yapın" : "Yeni bir hesap oluşturun")
                                .font(.system(size: 15, weight: .medium))
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                        }
                    }
                    .padding(.bottom, 8)

                    // Form Fields
                    VStack(spacing: 16) {
                        if mode == .register {
                            customTextField("Görünen ad", text: $displayName, icon: "person.fill")
                        }
                        customTextField("E-posta adresi", text: $email, isEmail: true, icon: "envelope.fill")
                        customSecureField("Şifre", text: $password, icon: "lock.fill")

                        if mode == .register {
                            VStack(alignment: .leading, spacing: 12) {
                                Toggle(isOn: $termsAccepted) {
                                    Text("Kullanım koşullarını kabul ediyorum")
                                        .font(.system(size: 13))
                                        .foregroundStyle(.secondary)
                                }
                                Toggle(isOn: $privacyAccepted) {
                                    Text("Gizlilik politikasını kabul ediyorum")
                                        .font(.system(size: 13))
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .toggleStyle(.checkbox)
                            .padding(.vertical, 8)
                            .padding(.horizontal, 4)
                        }
                    }
                    .frame(maxWidth: 320)

                    if !error.isEmpty {
                        HStack(spacing: 8) {
                            Image(systemName: "exclamationmark.triangle.fill")
                            Text(error)
                        }
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.red)
                        .padding(12)
                        .frame(maxWidth: 320, alignment: .leading)
                        .background(Color.red.opacity(0.1))
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }

                    // Submit Button
                    Button(action: submit) {
                        HStack {
                            if isWorking {
                                ProgressView()
                                    .controlSize(.small)
                                    .padding(.trailing, 4)
                            }
                            Text(mode == .login ? "Giriş yap" : "Hesap oluştur")
                                .font(.system(size: 15, weight: .semibold))
                        }
                        .frame(maxWidth: .infinity)
                        .frame(height: 44)
                        .background(
                            canSubmit 
                                ? (isHoveringSubmit ? Color.accentColor.opacity(0.9) : Color.accentColor) 
                                : Color.white.opacity(0.1)
                        )
                        .foregroundStyle(canSubmit ? .white : .secondary)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .shadow(color: canSubmit ? Color.accentColor.opacity(0.3) : .clear, radius: 8, x: 0, y: 4)
                        .animation(.easeInOut(duration: 0.2), value: canSubmit)
                        .animation(.easeInOut(duration: 0.2), value: isHoveringSubmit)
                    }
                    .buttonStyle(.plain)
                    .disabled(isWorking || !canSubmit)
                    .frame(maxWidth: 320)
                    .onHover { hovering in
                        isHoveringSubmit = hovering
                    }

                    // Divider
                    HStack(spacing: 16) {
                        VStack { Divider().background(Color.white.opacity(0.1)) }
                        Text("veya").font(.system(size: 13, weight: .medium)).foregroundStyle(.tertiary)
                        VStack { Divider().background(Color.white.opacity(0.1)) }
                    }
                    .frame(maxWidth: 320)

                    // OAuth Buttons
                    VStack(spacing: 12) {
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
                        .signInWithAppleButtonStyle(.white)
                        .frame(height: 44)
                        .frame(maxWidth: .infinity)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

                        Button(action: { loginWithGoogle() }) {
                            HStack(spacing: 12) {
                                // Google generic icon using a multicolored SF Symbol or custom approach.
                                // We'll just use a clean "G" or standard layout.
                                Image(systemName: "g.circle.fill")
                                    .font(.system(size: 18))
                                Text("Google ile devam et")
                                    .font(.system(size: 15, weight: .medium))
                            }
                            .frame(maxWidth: .infinity)
                            .frame(height: 44)
                            .background(isHoveringGoogle ? Color.white.opacity(0.08) : Color.white.opacity(0.05))
                            .foregroundStyle(.primary)
                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                            .overlay(
                                RoundedRectangle(cornerRadius: 12, style: .continuous)
                                    .strokeBorder(Color.white.opacity(0.1), lineWidth: 1)
                            )
                            .animation(.easeInOut(duration: 0.2), value: isHoveringGoogle)
                        }
                        .buttonStyle(.plain)
                        .onHover { hovering in
                            isHoveringGoogle = hovering
                        }
                    }
                    .frame(maxWidth: 320)

                    Text("Devam ederek Kullanım Koşulları'nı ve Gizlilik Politikası'nı kabul etmiş olursun.")
                        .font(.system(size: 12))
                        .foregroundStyle(.tertiary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 300)
                        .padding(.top, 4)

                    // Footer Toggle
                    Button {
                        withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
                            error = ""
                            mode = (mode == .login ? .register : .login)
                            email = ""
                            password = ""
                            displayName = ""
                        }
                    } label: {
                        Text(mode == .login
                            ? "Hesabın yok mu? Hesap oluştur"
                            : "Zaten hesabın var mı? Giriş yap")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(Color.accentColor)
                            .padding(.top, 8)
                    }
                    .buttonStyle(.plain)
                }
                .padding(.vertical, 60)
                .padding(.horizontal, 40)
                .frame(maxWidth: .infinity, alignment: .center)
            }
        }
    }

    private func customTextField(_ placeholder: String, text: Binding<String>, isEmail: Bool = false, icon: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 16))
                .foregroundStyle(.secondary)
                .frame(width: 20)
            
            TextField(placeholder, text: text)
                .textFieldStyle(.plain)
                .font(.system(size: 15))
                .textContentType(isEmail ? .emailAddress : .none)
                .disableAutocorrection(true)
        }
        .padding(.horizontal, 16)
        .frame(height: 48)
        .background(Color.white.opacity(0.05))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Color.white.opacity(0.1), lineWidth: 1)
        )
    }
    
    private func customSecureField(_ placeholder: String, text: Binding<String>, icon: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 16))
                .foregroundStyle(.secondary)
                .frame(width: 20)
                
            SecureField(placeholder, text: text)
                .textFieldStyle(.plain)
                .font(.system(size: 15))
                .textContentType(mode == .login ? .password : .newPassword)
        }
        .padding(.horizontal, 16)
        .frame(height: 48)
        .background(Color.white.opacity(0.05))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Color.white.opacity(0.1), lineWidth: 1)
        )
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
                        termsAccepted: true,
                        privacyAccepted: true
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
                        termsAccepted: true,
                        privacyAccepted: true
                    )
                } catch {
                    self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                }
            }
        }
    }
}
