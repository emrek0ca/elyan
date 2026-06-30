import Foundation

struct RuntimeRequest: Codable {
    let id: String
    let taskId: String
    let capability: String
    let payload: [String: AnyCodable]

    init(
        id: String = "req_\(UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(12))",
        taskId: String? = nil,
        capability: String,
        payload: [String: AnyCodable] = [:]
    ) {
        self.id = id
        self.taskId = taskId ?? "task_\(id.dropFirst(4))"
        self.capability = capability
        self.payload = payload
    }
}

struct RuntimeResponse: Codable {
    let id: String
    let taskId: String
    let ok: Bool
    let capability: String
    let result: [String: AnyCodable]?
    let events: [AnyCodable]
    let artifacts: [AnyCodable]
    let error: RuntimeBridgeError?
    let durationMs: Int
    let requestId: String?
}

struct RuntimeBridgeError: Codable, Error {
    let code: String
    let message: String
}

struct AnyCodable: Codable {
    let value: Any

    init(_ value: Any) {
        self.value = value
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            value = NSNull()
        } else if let boolVal = try? container.decode(Bool.self) {
            value = boolVal
        } else if let intVal = try? container.decode(Int.self) {
            value = intVal
        } else if let doubleVal = try? container.decode(Double.self) {
            value = doubleVal
        } else if let stringVal = try? container.decode(String.self) {
            value = stringVal
        } else if let arrayVal = try? container.decode([AnyCodable].self) {
            value = arrayVal.map(\.value)
        } else if let dictionaryVal = try? container.decode([String: AnyCodable].self) {
            value = dictionaryVal.mapValues(\.value)
        } else {
            value = NSNull()
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case is NSNull:
            try container.encodeNil()
        case let boolVal as Bool:
            try container.encode(boolVal)
        case let intVal as Int:
            try container.encode(intVal)
        case let doubleVal as Double:
            try container.encode(doubleVal)
        case let stringVal as String:
            try container.encode(stringVal)
        case let arrayVal as [Any]:
            try container.encode(arrayVal.map { AnyCodable($0) })
        case let dictionaryVal as [String: Any]:
            try container.encode(dictionaryVal.mapValues { AnyCodable($0) })
        case let codableVal as AnyCodable:
            try codableVal.encode(to: encoder)
        default:
            try container.encodeNil()
        }
    }

    var dictionaryValue: [String: Any] {
        value as? [String: Any] ?? [:]
    }

    var arrayValue: [Any] {
        value as? [Any] ?? []
    }

    var stringValue: String {
        value as? String ?? ""
    }

    var boolValue: Bool {
        value as? Bool ?? false
    }

    var intValue: Int {
        value as? Int ?? 0
    }
}

/// A mobile-dispatched task as reflected in the runtime's local task inbox
/// (`result.runtime.taskInbox.items` from a `runtime.bootstrap` response).
struct RuntimeTaskItem: Identifiable, Hashable {
    let id: String
    let title: String
    let status: String
    let summary: String
    let error: String
    let updatedAt: String
    let approvalRequest: RuntimeApprovalRequest?

    var isWaitingApproval: Bool { status == "waiting_approval" && approvalRequest != nil }
    var isTerminal: Bool { ["completed", "failed", "canceled"].contains(status) }

    init?(dictionary: [String: Any]) {
        guard let id = dictionary["id"] as? String, !id.isEmpty else { return nil }
        self.id = id
        self.title = Self.nonEmpty(dictionary["title"]) ?? "Yeni görev"
        self.status = Self.nonEmpty(dictionary["status"]) ?? "queued"
        self.summary = (dictionary["summary"] as? String) ?? ""
        self.error = (dictionary["error"] as? String) ?? ""
        self.updatedAt = (dictionary["updatedAt"] as? String) ?? ""

        if let approval = dictionary["approvalRequest"] as? [String: Any],
           let approvalTitle = Self.nonEmpty(approval["title"]) {
            self.approvalRequest = RuntimeApprovalRequest(
                title: approvalTitle,
                message: (approval["message"] as? String) ?? "",
                summary: (approval["summary"] as? String) ?? "",
                confirmLabel: Self.nonEmpty(approval["confirmLabel"]) ?? "Onayla",
                rejectLabel: Self.nonEmpty(approval["rejectLabel"]) ?? "Reddet"
            )
        } else {
            self.approvalRequest = nil
        }
    }

    private static func nonEmpty(_ value: Any?) -> String? {
        guard let text = value as? String, !text.isEmpty else { return nil }
        return text
    }
}

struct RuntimeApprovalRequest: Hashable {
    let title: String
    let message: String
    let summary: String
    let confirmLabel: String
    let rejectLabel: String
}
