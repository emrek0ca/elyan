import SwiftUI
import GoogleSignIn

@main
struct ElyanApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var appState = AppState()

    init() {
        // Google Sign-In configuration'ını UYGULAMA BAŞINDA bir kez kur —
        // login butonuna basılana kadar beklemek yerine. Info.plist'teki
        // GIDClientID/GIDServerClientID otomatik okunur; burada açıkça set
        // etmek, config'in butona ilk basışta hazır olmama ihtimalini eler.
        GIDSignIn.sharedInstance.configuration = GIDConfiguration(
            clientID: DesktopAppConfig.googleClientID,
            serverClientID: DesktopAppConfig.googleServerClientID
        )
        // Önceki Google oturumu varsa sessizce geri yükle (kullanıcı her
        // açılışta yeniden Google onayı vermek zorunda kalmasın).
        GIDSignIn.sharedInstance.restorePreviousSignIn()
    }

    var body: some Scene {
        WindowGroup {
            RootView(backend: appState.backend)
                .environmentObject(appState)
                .onOpenURL { url in
                    _ = GIDSignIn.sharedInstance.handle(url)
                }
        }
        .windowStyle(.hiddenTitleBar)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    // macOS'ta bazı OAuth geri-çağrı akışları AppKit üzerinden URL teslim
    // eder; SwiftUI .onOpenURL'e ek olarak burada da yakalayıp GoogleSignIn'e
    // veriyoruz ki callback hiçbir yolda düşmesin.
    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls {
            _ = GIDSignIn.sharedInstance.handle(url)
        }
    }
}

/// Routes between login and the main app surface. The backend client publishes
/// the signed-in session, so signing in/out automatically swaps the view.
struct RootView: View {
    @EnvironmentObject var appState: AppState
    @ObservedObject var backend: ElyanBackend

    var body: some View {
        Group {
            if backend.isSignedIn {
                ContentView()
            } else {
                LoginView()
            }
        }
        .task {
            appState.supervisor.start(initialSession: backend.session)
            // Best-effort silent refresh on launch so a stale access token
            // doesn't make a logged-in user look logged out.
            if backend.isSignedIn {
                do {
                    _ = try await backend.getCurrentUser()
                } catch {
                    // The token is bad; surface the login screen.
                    await backend.logout()
                }
            }
        }
    }
}
