import SwiftUI

@main
struct ElyanMacApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            RootView(backend: appState.backend)
                .environmentObject(appState)
        }
        .windowStyle(.hiddenTitleBar)
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
