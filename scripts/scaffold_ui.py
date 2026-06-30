import os

mac_dir = os.path.join("apps", "macos", "ElyanMac")

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)

# 1. PermissionPolicyViewModel.swift
perm_swift = """import Foundation

class PermissionPolicyViewModel: ObservableObject {
    @Published var requiresAccessibility = false
    @Published var requiresDiskAccess = false
    
    func checkPermissions() {
        requiresAccessibility = !WindowTools.checkAccessibility()
        // Disk access check can be added here
    }
}
"""
write_file(os.path.join(mac_dir, "PermissionPolicyViewModel.swift"), perm_swift)

# 2. ChatView.swift
chat_swift = """import SwiftUI

struct ChatView: View {
    var body: some View {
        VStack {
            ScrollView {
                VStack(spacing: 16) {
                    Text("Welcome to Elyan")
                        .font(.title)
                        .padding()
                    
                    // Chat blocks go here
                    BlockView(blockType: "text", content: "Hello! I am ready to help.")
                }
                .padding()
            }
            
            HStack {
                TextField("Type a message...", text: .constant(""))
                    .textFieldStyle(RoundedBorderTextFieldStyle())
                Button("Send") { }
            }
            .padding()
        }
        .background(Material.regular)
    }
}
"""
write_file(os.path.join(mac_dir, "ChatView.swift"), chat_swift)

# 3. TaskInboxView.swift
inbox_swift = """import SwiftUI

struct TaskInboxView: View {
    var body: some View {
        List {
            Section(header: Text("Active Tasks")) {
                Text("No active tasks.")
            }
            Section(header: Text("History")) {
                Text("Task #123 - Completed")
            }
        }
        .listStyle(SidebarListStyle())
        .background(Material.thin)
    }
}
"""
write_file(os.path.join(mac_dir, "TaskInboxView.swift"), inbox_swift)

# 4. TaskApprovalView.swift
approval_swift = """import SwiftUI

struct TaskApprovalView: View {
    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "exclamationmark.shield.fill")
                .resizable()
                .frame(width: 50, height: 50)
                .foregroundColor(.orange)
            
            Text("Action Requires Approval")
                .font(.headline)
            Text("The agent wants to execute a command that modifies the file system.")
                .multilineTextAlignment(.center)
            
            HStack {
                Button("Deny") { }
                    .buttonStyle(.bordered)
                Button("Approve") { }
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding()
        .background(Material.thick)
        .cornerRadius(12)
        .shadow(radius: 10)
    }
}
"""
write_file(os.path.join(mac_dir, "TaskApprovalView.swift"), approval_swift)

# 5. SettingsView.swift
settings_swift = """import SwiftUI

struct SettingsView: View {
    @StateObject private var permissions = PermissionPolicyViewModel()
    
    var body: some View {
        Form {
            Section(header: Text("Authentication")) {
                Button("Sign In") { }
                Button("Sign Out") { }
            }
            Section(header: Text("Permissions")) {
                HStack {
                    Text("Accessibility")
                    Spacer()
                    Text(permissions.requiresAccessibility ? "Denied" : "Granted")
                        .foregroundColor(permissions.requiresAccessibility ? .red : .green)
                }
            }
        }
        .padding()
        .onAppear {
            permissions.checkPermissions()
        }
    }
}
"""
write_file(os.path.join(mac_dir, "SettingsView.swift"), settings_swift)

# 6. BlockViews.swift
blocks_swift = """import SwiftUI

struct BlockView: View {
    let blockType: String
    let content: String
    
    var body: some View {
        VStack(alignment: .leading) {
            if blockType == "text" {
                Text(content)
                    .padding()
                    .background(Color.blue.opacity(0.1))
                    .cornerRadius(8)
            } else if blockType == "status" {
                HStack {
                    ProgressView()
                    Text(content)
                }
                .padding()
                .background(Color.gray.opacity(0.1))
                .cornerRadius(8)
            } else if blockType == "artifact" {
                HStack {
                    Image(systemName: "doc.fill")
                    Text(content)
                }
                .padding()
                .background(Color.green.opacity(0.1))
                .cornerRadius(8)
            } else {
                Text(content)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
"""
write_file(os.path.join(mac_dir, "BlockViews.swift"), blocks_swift)

# 7. Update ContentView.swift
content_swift = """import SwiftUI

struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @State private var selection: String? = "Chat"
    
    var body: some View {
        NavigationView {
            List(selection: $selection) {
                NavigationLink(destination: ChatView(), tag: "Chat", selection: $selection) {
                    Label("Chat", systemImage: "bubble.left.and.bubble.right")
                }
                NavigationLink(destination: TaskInboxView(), tag: "Inbox", selection: $selection) {
                    Label("Task Inbox", systemImage: "tray.fill")
                }
                NavigationLink(destination: SettingsView(), tag: "Settings", selection: $selection) {
                    Label("Settings", systemImage: "gear")
                }
            }
            .listStyle(SidebarListStyle())
            
            // Default view
            Text("Select an item")
        }
        .toolbar {
            ToolbarItem(placement: .status) {
                HStack {
                    Circle()
                        .fill(appState.supervisor.isRunning ? Color.green : Color.red)
                        .frame(width: 8, height: 8)
                    Text(appState.supervisor.isRunning ? "Runtime Ready" : "Runtime Stopped")
                        .font(.caption)
                }
            }
        }
        .frame(minWidth: 800, minHeight: 600)
    }
}
"""
write_file(os.path.join(mac_dir, "ContentView.swift"), content_swift)

print("Scaffold UI python script completed.")
