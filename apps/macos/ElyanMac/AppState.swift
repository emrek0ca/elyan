import Foundation
import SwiftUI

@MainActor
final class AppState: ObservableObject {
    let backend: ElyanBackend
    let chat: ChatStore
    let supervisor: PythonRuntimeSupervisor

    init() {
        let backend = ElyanBackend()
        self.backend = backend
        self.chat = ChatStore(backend: backend)
        self.supervisor = PythonRuntimeSupervisor()
    }
}
