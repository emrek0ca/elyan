import Foundation

// MARK: - ChatBlock (discriminated union — mirrors elyan_blocks.v2)

/// One block in an Elyan assistant response. Parsed from the JSON blocks array
/// that the backend sends in SSE delta/updated events.
///
/// Each case corresponds exactly to a backend block type defined in
/// elyan-backend/src/contracts/domain.ts.
enum ChatBlock: Identifiable {
    // Basic content
    case text(TextBlock)
    case summary(SummaryBlock)
    case nextSteps(NextStepsBlock)

    // Status & progress
    case status(StatusBlock)
    case taskTrace(TaskTraceBlock)

    // Context info
    case infoCard(InfoCardBlock)         // attachment_context | context_signal

    // Research
    case webSearch(WebSearchBlock)

    // Code & data
    case code(CodeBlock)
    case table(TableBlock)
    case chart(ChartBlock)

    // Math & visuals
    case math(MathBlock)
    case mathSurface3D(MathSurface3DBlock)
    case svg(SvgBlock)

    // File / attachment
    case file(FileBlock)
    case attachmentAck(AttachmentAckBlock)
    case imageAnalysis(ImageAnalysisBlock)

    // UX
    case actionable(ActionableBlock)
    case blockGroup(BlockGroupBlock)
    case document(DocumentBlock)

    // Unknown / future-proof fallback
    case unknown(type: String, rawText: String)

    // MARK: Identifiable

    var id: String {
        switch self {
        case .text(let b):           return b.stableBlockId ?? "text-\(b.markdown.prefix(20))"
        case .summary(let b):        return b.stableBlockId ?? "summary"
        case .nextSteps(let b):      return b.stableBlockId ?? "next_steps"
        case .status(let b):         return b.stableBlockId ?? "status-\(b.title)"
        case .taskTrace(let b):      return b.stableBlockId ?? b.taskId
        case .infoCard(let b):       return b.stableBlockId ?? "info-\(b.type)"
        case .webSearch(let b):      return b.stableBlockId ?? "ws-\(b.query.prefix(20))"
        case .code(let b):           return b.stableBlockId ?? "code-\(b.language ?? "")"
        case .table(let b):          return b.stableBlockId ?? "table"
        case .chart(let b):          return b.stableBlockId ?? "chart-\(b.chartType)"
        case .math(let b):           return b.stableBlockId ?? "math"
        case .mathSurface3D(let b):  return b.stableBlockId ?? "math3d"
        case .svg(let b):            return b.stableBlockId ?? "svg"
        case .file(let b):           return b.stableBlockId ?? "file-\(b.fileName)"
        case .attachmentAck(let b):  return b.stableBlockId ?? "ack"
        case .imageAnalysis(let b):  return b.stableBlockId ?? "imganalysis"
        case .actionable(let b):     return b.stableBlockId ?? "act-\(b.kind.rawValue)"
        case .blockGroup(let b):     return b.stableBlockId ?? "group"
        case .document(let b):       return b.stableBlockId ?? "doc"
        case .unknown(let t, _):     return "unknown-\(t)"
        }
    }

    // MARK: - Parse from JSON dictionary

    static func parse(from dict: [String: Any]) -> ChatBlock? {
        guard let rawType = dict["type"] as? String else { return nil }
        let stable = dict["stableBlockId"] as? String

        switch rawType {
        case "text":
            guard let md = dict["markdown"] as? String, !md.isEmpty else { return nil }
            return .text(TextBlock(stableBlockId: stable, markdown: md))

        case "summary":
            guard let summary = dict["summary"] as? String else { return nil }
            return .summary(SummaryBlock(
                stableBlockId: stable,
                title: dict["title"] as? String,
                summary: summary
            ))

        case "next_steps":
            guard let items = dict["items"] as? [String], !items.isEmpty else { return nil }
            return .nextSteps(NextStepsBlock(
                stableBlockId: stable,
                title: dict["title"] as? String,
                items: items
            ))

        case "status":
            guard let title = dict["title"] as? String else { return nil }
            let statusStr = dict["status"] as? String ?? "running"
            return .status(StatusBlock(
                stableBlockId: stable,
                status: StatusBlock.Status(rawValue: statusStr) ?? .running,
                title: title,
                detail: dict["detail"] as? String
            ))

        case "task_trace":
            guard let taskId = dict["taskId"] as? String,
                  let title = dict["title"] as? String,
                  let statusStr = dict["status"] as? String,
                  let rawSteps = dict["steps"] as? [[String: Any]] else { return nil }
            let steps = rawSteps.compactMap { TaskTraceStep.parse(from: $0) }
            return .taskTrace(TaskTraceBlock(
                stableBlockId: stable,
                taskId: taskId,
                status: TaskTraceBlock.Status(rawValue: statusStr) ?? .running,
                title: title,
                phase: dict["phase"] as? String,
                summary: dict["summary"] as? String,
                progressLabel: dict["progressLabel"] as? String,
                activeStepId: dict["activeStepId"] as? String,
                steps: steps
            ))

        case "attachment_context", "context_signal":
            guard let title = dict["title"] as? String,
                  let rawItems = dict["items"] as? [[String: Any]] else { return nil }
            let items = rawItems.compactMap { InfoCardItem.parse(from: $0) }
            return .infoCard(InfoCardBlock(
                stableBlockId: stable,
                type: rawType,
                title: title,
                items: items
            ))

        case "web_search":
            guard let query = dict["query"] as? String,
                  let rawResults = dict["results"] as? [[String: Any]] else { return nil }
            let results = rawResults.compactMap { WebSearchResult.parse(from: $0) }
            return .webSearch(WebSearchBlock(
                stableBlockId: stable,
                query: query,
                queries: dict["queries"] as? [String] ?? [query],
                confidence: WebSearchBlock.Confidence(rawValue: dict["confidence"] as? String ?? "medium") ?? .medium,
                results: results
            ))

        case "code":
            guard let code = dict["code"] as? String else { return nil }
            return .code(CodeBlock(
                stableBlockId: stable,
                code: code,
                language: dict["language"] as? String,
                filename: dict["filename"] as? String,
                title: dict["title"] as? String,
                collapsed: dict["collapsed"] as? Bool ?? false
            ))

        case "table":
            guard let cols = dict["columns"] as? [String],
                  let rows = dict["rows"] as? [[String]] else { return nil }
            return .table(TableBlock(
                stableBlockId: stable,
                title: dict["title"] as? String,
                summary: dict["summary"] as? String,
                columns: cols,
                rows: rows,
                totalRowCount: dict["totalRowCount"] as? Int,
                caption: dict["caption"] as? String,
                density: TableBlock.Density(rawValue: dict["density"] as? String ?? "comfortable") ?? .comfortable
            ))

        case "chart":
            guard let chartTypeStr = dict["chartType"] as? String else { return nil }
            return .chart(ChartBlock(
                stableBlockId: stable,
                chartType: ChartBlock.ChartType(rawValue: chartTypeStr) ?? .bar,
                title: dict["title"] as? String,
                labels: dict["labels"] as? [String],
                values: dict["values"] as? [Double],
                series: (dict["series"] as? [[String: Any]])?.compactMap { ChartSeries.parse(from: $0) },
                xLabel: dict["xLabel"] as? String,
                yLabel: dict["yLabel"] as? String,
                caption: dict["caption"] as? String
            ))

        case "math":
            guard let content = dict["content"] as? String else { return nil }
            return .math(MathBlock(
                stableBlockId: stable,
                title: dict["title"] as? String,
                content: content,
                latex: dict["latex"] as? String,
                displayMode: dict["displayMode"] as? Bool ?? true,
                result: dict["result"] as? String,
                explanation: dict["explanation"] as? String
            ))

        case "math_surface_3d":
            return .mathSurface3D(MathSurface3DBlock(
                stableBlockId: stable,
                title: dict["title"] as? String,
                expression: dict["expression"] as? String,
                caption: dict["caption"] as? String
            ))

        case "svg":
            return .svg(SvgBlock(
                stableBlockId: stable,
                title: dict["title"] as? String,
                svg: (dict["svg"] as? String) ?? (dict["markup"] as? String),
                url: dict["url"] as? String,
                caption: dict["caption"] as? String
            ))

        case "file":
            guard let fileName = dict["fileName"] as? String else { return nil }
            return .file(FileBlock(
                stableBlockId: stable,
                fileName: fileName,
                mimeType: dict["mimeType"] as? String,
                sizeBytes: dict["sizeBytes"] as? Int,
                preview: dict["preview"] as? String
            ))

        case "attachment_ack":
            guard let summary = dict["summary"] as? String else { return nil }
            return .attachmentAck(AttachmentAckBlock(
                stableBlockId: stable,
                summary: summary,
                attachmentCount: dict["attachmentCount"] as? Int ?? 0,
                pageCount: dict["pageCount"] as? Int,
                hasTable: dict["hasTable"] as? Bool,
                hasImage: dict["hasImage"] as? Bool
            ))

        case "image_analysis":
            guard let description = dict["description"] as? String else { return nil }
            return .imageAnalysis(ImageAnalysisBlock(
                stableBlockId: stable,
                description: description,
                detectedText: dict["detectedText"] as? String,
                tags: dict["tags"] as? [String]
            ))

        case "actionable":
            guard let kindStr = dict["kind"] as? String,
                  let title = dict["title"] as? String else { return nil }
            return .actionable(ActionableBlock(
                stableBlockId: stable,
                kind: ActionableBlock.Kind(rawValue: kindStr) ?? .retry_option,
                title: title,
                detail: dict["detail"] as? String
            ))

        case "block_group":
            guard let children = dict["children"] as? [[String: Any]] else { return nil }
            let parsed = children.compactMap { ChatBlock.parse(from: $0) }
            return .blockGroup(BlockGroupBlock(
                stableBlockId: stable,
                title: dict["title"] as? String,
                children: parsed
            ))

        case "document_block":
            guard let rawSections = dict["sections"] as? [[String: Any]] else { return nil }
            let sections = rawSections.compactMap { DocumentSection.parse(from: $0) }
            return .document(DocumentBlock(
                stableBlockId: stable,
                title: dict["title"] as? String,
                sections: sections,
                format: dict["format"] as? String,
                summary: dict["summary"] as? String
            ))

        default:
            let text = (dict["markdown"] as? String)
                ?? (dict["text"] as? String)
                ?? (dict["content"] as? String)
                ?? ""
            return .unknown(type: rawType, rawText: text)
        }
    }

    // MARK: - Parse array

    static func parseArray(from blocks: [[String: Any]]) -> [ChatBlock] {
        blocks.compactMap { parse(from: $0) }
    }
}

// MARK: - Block Data Types

struct TextBlock: Equatable {
    var stableBlockId: String?
    var markdown: String
}

struct SummaryBlock: Equatable {
    var stableBlockId: String?
    var title: String?
    var summary: String
}

struct NextStepsBlock: Equatable {
    var stableBlockId: String?
    var title: String?
    var items: [String]
}

struct StatusBlock: Equatable {
    enum Status: String, Equatable {
        case running, waiting_approval, needs_desktop, completed, failed, retrying, degraded
        var isActive: Bool { self == .running || self == .retrying }
        var isError: Bool { self == .failed || self == .degraded }
        var isSuccess: Bool { self == .completed }
    }
    var stableBlockId: String?
    var status: Status
    var title: String
    var detail: String?
}

struct TaskTraceStep: Equatable {
    enum Status: String, Equatable {
        case pending, running, completed, failed, skipped
    }
    enum StepId: String, Equatable {
        case intent, route, plan, context, tool, verify, response
        var icon: String {
            switch self {
            case .intent: return "text.magnifyingglass"
            case .route: return "arrow.triangle.branch"
            case .plan: return "list.bullet.clipboard"
            case .context: return "brain"
            case .tool: return "hammer"
            case .verify: return "checkmark.shield"
            case .response: return "bubble.left.and.bubble.right"
            }
        }
    }
    var id: String
    var label: String
    var status: Status
    var detail: String?

    static func parse(from dict: [String: Any]) -> TaskTraceStep? {
        guard let id = dict["id"] as? String,
              let label = dict["label"] as? String,
              let statusStr = dict["status"] as? String else { return nil }
        return TaskTraceStep(
            id: id,
            label: label,
            status: Status(rawValue: statusStr) ?? .pending,
            detail: dict["detail"] as? String
        )
    }
}

struct TaskTraceBlock: Equatable {
    enum Status: String, Equatable {
        case running, completed, failed, waiting_approval
    }
    var stableBlockId: String?
    var taskId: String
    var status: Status
    var title: String
    var phase: String?
    var summary: String?
    var progressLabel: String?
    var activeStepId: String?
    var steps: [TaskTraceStep]
}

struct InfoCardItem: Equatable {
    var label: String
    var value: String
    static func parse(from dict: [String: Any]) -> InfoCardItem? {
        guard let label = dict["label"] as? String,
              let value = dict["value"] as? String else { return nil }
        return InfoCardItem(label: label, value: value)
    }
}

struct InfoCardBlock: Equatable {
    var stableBlockId: String?
    var type: String  // "attachment_context" | "context_signal"
    var title: String
    var items: [InfoCardItem]
}

struct WebSearchResult: Equatable {
    var title: String
    var url: String
    var snippet: String?
    var sourceHost: String?
    var verificationState: String  // "verified" | "partial" | "unverified"
    static func parse(from dict: [String: Any]) -> WebSearchResult? {
        guard let title = dict["title"] as? String,
              let url = dict["url"] as? String else { return nil }
        return WebSearchResult(
            title: title,
            url: url,
            snippet: dict["snippet"] as? String,
            sourceHost: dict["sourceHost"] as? String,
            verificationState: dict["verificationState"] as? String ?? "unverified"
        )
    }
}

struct WebSearchBlock: Equatable {
    enum Confidence: String { case high, medium, low }
    var stableBlockId: String?
    var query: String
    var queries: [String]
    var confidence: Confidence
    var results: [WebSearchResult]
}

struct CodeBlock: Equatable {
    var stableBlockId: String?
    var code: String
    var language: String?
    var filename: String?
    var title: String?
    var collapsed: Bool
}

struct TableBlock: Equatable {
    enum Density: String { case compact, comfortable, spacious }
    var stableBlockId: String?
    var title: String?
    var summary: String?
    var columns: [String]
    var rows: [[String]]
    var totalRowCount: Int?
    var caption: String?
    var density: Density
}

struct ChartSeries: Equatable {
    var name: String?
    var labels: [String]?
    var values: [Double]?
    static func parse(from dict: [String: Any]) -> ChartSeries? {
        let values = (dict["values"] as? [Double]) ?? (dict["values"] as? [Int])?.map { Double($0) }
        return ChartSeries(
            name: dict["name"] as? String,
            labels: dict["labels"] as? [String],
            values: values
        )
    }
}

struct ChartBlock: Equatable {
    enum ChartType: String {
        case bar, line, pie, area, scatter, geometry, function_, surface3d, mesh, heatmap
        init?(rawValue: String) {
            switch rawValue {
            case "bar": self = .bar
            case "line": self = .line
            case "pie": self = .pie
            case "area": self = .area
            case "scatter": self = .scatter
            case "function": self = .function_
            default: return nil
            }
        }
    }
    var stableBlockId: String?
    var chartType: ChartType
    var title: String?
    var labels: [String]?
    var values: [Double]?
    var series: [ChartSeries]?
    var xLabel: String?
    var yLabel: String?
    var caption: String?
}

struct MathBlock: Equatable {
    var stableBlockId: String?
    var title: String?
    var content: String     // plain text math expression or LaTeX
    var latex: String?      // LaTeX override
    var displayMode: Bool
    var result: String?
    var explanation: String?
}

struct MathSurface3DBlock: Equatable {
    var stableBlockId: String?
    var title: String?
    var expression: String?
    var caption: String?
}

struct SvgBlock: Equatable {
    var stableBlockId: String?
    var title: String?
    var svg: String?        // inline SVG markup
    var url: String?        // remote SVG URL
    var caption: String?
}

struct FileBlock: Equatable {
    var stableBlockId: String?
    var fileName: String
    var mimeType: String?
    var sizeBytes: Int?
    var preview: String?

    var icon: String {
        guard let mime = mimeType else { return "doc.fill" }
        if mime.contains("pdf") { return "doc.richtext.fill" }
        if mime.contains("image") { return "photo.fill" }
        if mime.contains("video") { return "video.fill" }
        if mime.contains("audio") { return "waveform" }
        if mime.contains("spreadsheet") || mime.contains("excel") { return "tablecells.fill" }
        if mime.contains("word") || mime.contains("document") { return "doc.text.fill" }
        if mime.contains("zip") || mime.contains("tar") { return "archivebox.fill" }
        return "doc.fill"
    }

    var formattedSize: String? {
        guard let bytes = sizeBytes else { return nil }
        let kb = Double(bytes) / 1024
        if kb < 1024 { return String(format: "%.1f KB", kb) }
        let mb = kb / 1024
        if mb < 1024 { return String(format: "%.1f MB", mb) }
        return String(format: "%.1f GB", mb / 1024)
    }
}

struct AttachmentAckBlock: Equatable {
    var stableBlockId: String?
    var summary: String
    var attachmentCount: Int
    var pageCount: Int?
    var hasTable: Bool?
    var hasImage: Bool?
}

struct ImageAnalysisBlock: Equatable {
    var stableBlockId: String?
    var description: String
    var detectedText: String?
    var tags: [String]?
}

struct ActionableBlock: Equatable {
    enum Kind: String, Equatable {
        case approval_needed, choose_device, retry_option = "retryOption", openHistory = "open_history", restoreContext = "restore_context"
        init?(rawValue: String) {
            switch rawValue {
            case "approval_needed": self = .approval_needed
            case "choose_device": self = .choose_device
            case "retry_option": self = .retry_option
            case "open_history": self = .openHistory
            case "restore_context": self = .restoreContext
            default: return nil
            }
        }
    }
    var stableBlockId: String?
    var kind: Kind
    var title: String
    var detail: String?
}

struct BlockGroupBlock {
    var stableBlockId: String?
    var title: String?
    var children: [ChatBlock]
}

struct DocumentSection: Equatable {
    var heading: String?
    var content: String
    var level: Int?
    var role: String?
    static func parse(from dict: [String: Any]) -> DocumentSection? {
        guard let content = dict["content"] as? String else { return nil }
        return DocumentSection(
            heading: dict["heading"] as? String,
            content: content,
            level: dict["level"] as? Int,
            role: dict["role"] as? String
        )
    }
}

struct DocumentBlock: Equatable {
    var stableBlockId: String?
    var title: String?
    var sections: [DocumentSection]
    var format: String?
    var summary: String?
}

// MARK: - ChatBlock Equatable (id-based to avoid recursive Equatable issue)
extension ChatBlock: Equatable {
    static func == (lhs: ChatBlock, rhs: ChatBlock) -> Bool {
        lhs.id == rhs.id
    }
}
