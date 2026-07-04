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

    // Goals (loop/goal engine — mobile parity)
    case goalProgress(GoalProgressBlock)

    // UX
    case actionable(ActionableBlock)
    case blockGroup(BlockGroupBlock)
    case document(DocumentBlock)

    // Unknown / future-proof fallback
    case reasoningTrace(ReasoningTraceBlock)
    case terminal(TerminalBlock)
    case automation(AutomationBlock)
    case pdfGenerate(PdfGenerateBlock)
    case pdfViewer(PdfViewerBlock)
    case desktopSuggestion(DesktopSuggestionBlock)
    case memoryEcho(MemoryEchoBlock)
    case proactiveTouch(ProactiveTouchBlock)
    case artifact(ArtifactBlock)
    case documentSkeleton(DocumentSkeletonBlock)
    // Future-proof: any unrecognized block type with readable fields renders
    // from its common fields (title / body / items / link) instead of raw JSON.
    case generic(GenericBlock)
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
        case .goalProgress(let b):   return b.stableBlockId ?? "goal-\(b.goalId)"
        case .actionable(let b):     return b.stableBlockId ?? "act-\(b.kind.rawValue)"
        case .blockGroup(let b):     return b.stableBlockId ?? "group"
        case .document(let b):       return b.stableBlockId ?? "doc"
        case .reasoningTrace(let b): return b.stableBlockId ?? "reasoning"
        case .terminal(let b):       return b.stableBlockId ?? "term-\(b.command ?? "")"
        case .automation(let b):     return b.stableBlockId ?? "auto-\(b.automationId ?? b.title)"
        case .pdfGenerate(let b):    return b.stableBlockId ?? "pdfgen-\(b.title ?? "")"
        case .pdfViewer(let b):      return b.stableBlockId ?? "pdfview-\(b.fileId ?? b.title ?? "")"
        case .desktopSuggestion(let b): return b.stableBlockId ?? "desktop-\(b.detectedIntent ?? "")"
        case .memoryEcho(let b):     return b.stableBlockId ?? "memory-\(b.question.prefix(16))"
        case .proactiveTouch(let b): return b.stableBlockId ?? "proactive-\(b.cta.prefix(16))"
        case .artifact(let b):       return b.stableBlockId ?? "artifact-\(b.artifactId ?? b.url.prefix(24).description)"
        case .documentSkeleton(let b): return b.stableBlockId ?? "doc-skeleton"
        case .generic(let b):        return b.stableBlockId ?? "generic-\(b.rawType)"
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

        case "goal_progress":
            guard let goalId = dict["goalId"] as? String ?? dict["goal_id"] as? String, !goalId.isEmpty else { return nil }
            let ofSteps = max(1, min(10_000, (dict["ofSteps"] as? Int) ?? (dict["of_steps"] as? Int) ?? 1))
            let step = max(0, min(ofSteps, (dict["step"] as? Int) ?? 0))
            let advancedTo = (dict["advancedTo"] as? String)
                ?? (dict["advanced_to"] as? String)
                ?? (dict["summary"] as? String)
                ?? (dict["markdown"] as? String)
                ?? ""
            return .goalProgress(GoalProgressBlock(
                stableBlockId: stable,
                goalId: goalId,
                step: step,
                ofSteps: ofSteps,
                advancedTo: advancedTo,
                blocker: dict["blocker"] as? String,
                done: dict["done"] as? Bool ?? false
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

        case "reasoning_trace":
            return .reasoningTrace(ReasoningTraceBlock(
                stableBlockId: stable,
                status: dict["status"] as? String ?? "completed",
                content: (dict["content"] as? String) ?? (dict["markdown"] as? String) ?? ""
            ))

        case "terminal":
            let exit = (dict["exitCode"] as? Int) ?? (dict["exit_code"] as? Int)
            return .terminal(TerminalBlock(
                stableBlockId: stable,
                output: (dict["output"] as? String) ?? (dict["content"] as? String) ?? "",
                command: (dict["command"] as? String) ?? (dict["cmd"] as? String),
                exitCode: exit,
                truncated: (dict["truncated"] as? Bool) ?? false
            ))

        case "automation":
            return .automation(AutomationBlock(
                stableBlockId: stable,
                title: dict["title"] as? String ?? "Otomasyon",
                description: (dict["description"] as? String) ?? (dict["summary"] as? String) ?? "",
                schedule: dict["schedule"] as? String,
                triggerType: (dict["triggerType"] as? String) ?? (dict["trigger_type"] as? String),
                steps: (dict["steps"] as? [Any])?.compactMap { $0 as? String } ?? [],
                automationId: (dict["automationId"] as? String) ?? (dict["automation_id"] as? String)
            ))

        case "pdf_generate":
            let pages = (dict["estimatedPages"] as? Int) ?? (dict["pages"] as? Int) ?? 1
            let sections = (dict["sections"] as? [[String: Any]])?.map {
                PdfGenerateSection(
                    title: $0["title"] as? String,
                    content: ($0["content"] as? String) ?? ($0["markdown"] as? String) ?? ""
                )
            } ?? []
            return .pdfGenerate(PdfGenerateBlock(
                stableBlockId: stable,
                title: dict["title"] as? String,
                estimatedPages: pages,
                language: dict["language"] as? String ?? "tr",
                sections: sections
            ))

        case "pdf_viewer":
            let pageCount = (dict["pageCount"] as? Int) ?? (dict["page_count"] as? Int)
            return .pdfViewer(PdfViewerBlock(
                stableBlockId: stable,
                title: (dict["title"] as? String) ?? (dict["name"] as? String),
                fileId: (dict["fileId"] as? String) ?? (dict["file_id"] as? String) ?? (dict["id"] as? String),
                localPath: (dict["localPath"] as? String) ?? (dict["local_path"] as? String),
                remoteUrl: (dict["remoteUrl"] as? String) ?? (dict["remote_url"] as? String) ?? (dict["url"] as? String),
                pageCount: pageCount,
                thumbnailUrl: (dict["thumbnailUrl"] as? String) ?? (dict["thumbnail_url"] as? String)
            ))

        case "desktop_suggestion":
            return .desktopSuggestion(DesktopSuggestionBlock(
                stableBlockId: stable,
                reason: (dict["reason"] as? String) ?? (dict["summary"] as? String) ?? "",
                requiredCapabilities: (dict["requiredCapabilities"] as? [Any])?.compactMap { $0 as? String }
                    ?? (dict["required_capabilities"] as? [Any])?.compactMap { $0 as? String } ?? [],
                detectedIntent: (dict["detectedIntent"] as? String) ?? (dict["detected_intent"] as? String)
            ))

        case "memory_echo":
            return .memoryEcho(MemoryEchoBlock(
                stableBlockId: stable,
                recall: (dict["recall"] as? String) ?? (dict["content"] as? String) ?? "",
                question: (dict["question"] as? String) ?? "",
                confidence: (dict["confidence"] as? Double) ?? 0
            ))

        case "proactive_touch":
            return .proactiveTouch(ProactiveTouchBlock(
                stableBlockId: stable,
                suggestion: (dict["suggestion"] as? String) ?? (dict["content"] as? String) ?? "",
                cta: (dict["cta"] as? String) ?? "",
                context: (dict["context"] as? String) ?? (dict["reason"] as? String)
            ))

        case "artifact":
            return .artifact(ArtifactBlock(
                stableBlockId: stable,
                artifactType: (dict["artifactType"] as? String) ?? (dict["artifact_type"] as? String) ?? "image",
                url: (dict["url"] as? String) ?? (dict["uri"] as? String) ?? (dict["src"] as? String) ?? "",
                artifactId: (dict["artifactId"] as? String) ?? (dict["artifact_id"] as? String),
                title: dict["title"] as? String,
                mime: (dict["mime"] as? String) ?? (dict["mimeType"] as? String),
                summary: dict["summary"] as? String,
                preview: dict["preview"] as? String
            ))

        case "document_block_skeleton":
            return .documentSkeleton(DocumentSkeletonBlock(
                stableBlockId: stable,
                title: dict["title"] as? String
            ))

        default:
            // Future-proof: extract common fields so a new/unknown backend block
            // still renders readably instead of leaking raw JSON.
            if let generic = GenericBlock.parse(rawType: rawType, dict: dict, stableBlockId: stable) {
                return .generic(generic)
            }
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

struct GoalProgressBlock: Equatable {
    var stableBlockId: String?
    var goalId: String
    var step: Int
    var ofSteps: Int
    var advancedTo: String
    var blocker: String?
    var done: Bool

    var progressRatio: Double {
        guard ofSteps > 0 else { return 0 }
        return min(1, max(0, Double(step) / Double(ofSteps)))
    }
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

// MARK: - Widget block data types ported from mobile (elyan_blocks.v2)

struct ReasoningTraceBlock: Equatable {
    var stableBlockId: String?
    var status: String   // "running" | "completed"
    var content: String
    var isRunning: Bool { status.lowercased() == "running" }
}

struct TerminalBlock: Equatable {
    var stableBlockId: String?
    var output: String
    var command: String?
    var exitCode: Int?
    var truncated: Bool
}

struct AutomationBlock: Equatable {
    var stableBlockId: String?
    var title: String
    var description: String
    var schedule: String?
    var triggerType: String?
    var steps: [String]
    var automationId: String?
}

struct PdfGenerateSection: Equatable {
    var title: String?
    var content: String
}

struct PdfGenerateBlock: Equatable {
    var stableBlockId: String?
    var title: String?
    var estimatedPages: Int
    var language: String
    var sections: [PdfGenerateSection]
}

struct PdfViewerBlock: Equatable {
    var stableBlockId: String?
    var title: String?
    var fileId: String?
    var localPath: String?
    var remoteUrl: String?
    var pageCount: Int?
    var thumbnailUrl: String?
}

struct DesktopSuggestionBlock: Equatable {
    var stableBlockId: String?
    var reason: String
    var requiredCapabilities: [String]
    var detectedIntent: String?
}

struct MemoryEchoBlock: Equatable {
    var stableBlockId: String?
    var recall: String
    var question: String
    var confidence: Double
}

struct ProactiveTouchBlock: Equatable {
    var stableBlockId: String?
    var suggestion: String
    var cta: String
    var context: String?
}

struct ArtifactBlock: Equatable {
    var stableBlockId: String?
    var artifactType: String  // "chart_image" | "image" | "svg"
    var url: String
    var artifactId: String?
    var title: String?
    var mime: String?
    var summary: String?
    var preview: String?
}

struct DocumentSkeletonBlock: Equatable {
    var stableBlockId: String?
    var title: String?
}

/// Future-proof generic view of any unrecognized block: pulls the common field
/// aliases so a new backend block type renders readably instead of raw JSON.
struct GenericBlock: Equatable {
    var stableBlockId: String?
    var rawType: String
    var title: String?
    var body: String?
    var bullets: [String]
    var link: String?

    var isEmpty: Bool {
        (title?.isEmpty ?? true) && (body?.isEmpty ?? true) && bullets.isEmpty && (link?.isEmpty ?? true)
    }

    static func parse(rawType: String, dict: [String: Any], stableBlockId: String?) -> GenericBlock? {
        func firstString(_ keys: [String]) -> String? {
            for key in keys {
                if let value = dict[key] as? String, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    return value
                }
            }
            return nil
        }
        func bullets(_ keys: [String]) -> [String] {
            for key in keys {
                if let list = dict[key] as? [Any], !list.isEmpty {
                    let items: [String] = list.compactMap { item in
                        if let s = item as? String { return s }
                        if let map = item as? [String: Any] {
                            let label = map["label"] as? String ?? map["title"] as? String ?? map["name"] as? String
                            let value = map["value"] as? String ?? map["text"] as? String ?? map["content"] as? String
                            if let l = label, let v = value { return "\(l): \(v)" }
                            return label ?? value
                        }
                        return nil
                    }
                    if !items.isEmpty { return items }
                }
            }
            return []
        }
        let block = GenericBlock(
            stableBlockId: stableBlockId,
            rawType: rawType,
            title: firstString(["title", "heading", "header", "label", "name", "caption", "subject"]),
            body: firstString(["content", "text", "markdown", "body", "message", "summary", "description", "detail", "note", "answer"]),
            bullets: bullets(["items", "steps", "points", "bullets", "lines", "list", "entries", "rows", "values"]),
            link: firstString(["url", "href", "link", "source", "sourceUrl"])
        )
        return block.isEmpty ? nil : block
    }
}

// MARK: - ChatBlock Equatable (id-based to avoid recursive Equatable issue)
extension ChatBlock: Equatable {
    static func == (lhs: ChatBlock, rhs: ChatBlock) -> Bool {
        lhs.id == rhs.id
    }
}
