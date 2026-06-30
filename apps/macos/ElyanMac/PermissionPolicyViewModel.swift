import Foundation

class PermissionPolicyViewModel: ObservableObject {
    @Published var requiresAccessibility = false
    @Published var requiresDiskAccess = false
    
    func checkPermissions() {
        requiresAccessibility = !WindowTools.checkAccessibility()
        // Disk access check can be added here
    }
}
