import Foundation
import SwiftUI

@MainActor
final class AppState: ObservableObject {
    let backend: ElyanBackend
    let chat: ChatStore
    let supervisor: PythonRuntimeSupervisor

    init() {
        let backend = ElyanBackend()
        let supervisor = PythonRuntimeSupervisor()
        self.backend = backend
        self.chat = ChatStore(backend: backend)
        self.supervisor = supervisor
        backend.onSessionChanged = { session in
            Task { @MainActor in
                await supervisor.syncAuthSession(session)
            }
        }
    }
}
