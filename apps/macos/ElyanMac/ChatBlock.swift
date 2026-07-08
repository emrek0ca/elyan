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

    // MARK: - Parse helpers

    private static func stringValue(_ value: Any?) -> String? {
        if let string = value as? String {
            let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }
        if let number = value as? NSNumber {
            return number.stringValue
        }
        return nil
    }

    private static func firstString(_ dict: [String: Any], keys: [String]) -> String? {
        for key in keys {
            if let value = stringValue(dict[key]) {
                return value
            }
        }
        return nil
    }

    private static func intValue(_ value: Any?) -> Int? {
        if let int = value as? Int { return int }
        if let double = value as? Double { return Int(double) }
        if let string = stringValue(value) { return Int(string) }
        return nil
    }

    private static func doubleValue(_ value: Any?) -> Double? {
        if let double = value as? Double { return double }
        if let int = value as? Int { return Double(int) }
        if let string = stringValue(value) { return Double(string) }
        return nil
    }

    private static func boolValue(_ value: Any?, default fallback: Bool = false) -> Bool {
        if let bool = value as? Bool { return bool }
        if let number = value as? NSNumber { return number.boolValue }
        if let string = stringValue(value)?.lowercased() {
            if ["true", "1", "yes"].contains(string) { return true }
            if ["false", "0", "no"].contains(string) { return false }
        }
        return fallback
    }

    private static func stringArray(_ value: Any?) -> [String] {
        guard let values = value as? [Any] else { return [] }
        return values.compactMap { stringValue($0) }
    }

    private static func doubleArray(_ value: Any?) -> [Double]? {
        guard let values = value as? [Any] else { return nil }
        let mapped = values.compactMap { doubleValue($0) }
        return mapped.isEmpty ? nil : mapped
    }

    private static func dictArray(_ value: Any?) -> [[String: Any]] {
        if let dicts = value as? [[String: Any]] { return dicts }
        guard let values = value as? [Any] else { return [] }
        return values.compactMap { $0 as? [String: Any] }
    }

    private static func tableRows(from value: Any?, columns: [String]) -> [[String]] {
        guard let values = value as? [Any] else { return [] }
        return values.compactMap { row in
            if let strings = row as? [String] {
                return strings
            }
            if let anyValues = row as? [Any] {
                return anyValues.map { stringValue($0) ?? "" }
            }
            if let dict = row as? [String: Any] {
                let keys = columns.isEmpty ? dict.keys.sorted() : columns
                return keys.map { stringValue(dict[$0]) ?? "" }
            }
            return nil
        }
    }

    private static func tableColumns(from explicit: Any?, rowsValue: Any?) -> [String] {
        let columns = stringArray(explicit)
        if !columns.isEmpty { return columns }
        guard let firstRow = (rowsValue as? [Any])?.first as? [String: Any] else { return [] }
        return firstRow.keys.sorted()
    }

    private static func chartLabels(from rows: [[String: Any]]) -> [String]? {
        let labels = rows.compactMap { firstString($0, keys: ["label", "name", "x", "category", "title"]) }
        return labels.isEmpty ? nil : labels
    }

    private static func chartValues(from rows: [[String: Any]]) -> [Double]? {
        let values = rows.compactMap { doubleValue($0["value"] ?? $0["y"] ?? $0["amount"]) }
        return values.isEmpty ? nil : values
    }

    // MARK: - Parse from JSON dictionary

    static func parse(from dict: [String: Any]) -> ChatBlock? {
        guard let rawTypeValue = firstString(dict, keys: ["type"]) else { return nil }
        let rawType = rawTypeValue.lowercased()
        let stable = firstString(dict, keys: ["stableBlockId", "stable_block_id", "cacheDigest", "cache_digest", "id"])

        switch rawType {
        case "text":
            guard let md = firstString(dict, keys: ["markdown", "text", "content"]) else { return nil }
            return .text(TextBlock(stableBlockId: stable, markdown: md))

        case "summary":
            guard let summary = firstString(dict, keys: ["summary", "markdown", "text", "content"]) else { return nil }
            return .summary(SummaryBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title", "heading"]),
                summary: summary
            ))

        case "next_steps":
            let items = stringArray(dict["items"]).isEmpty ? stringArray(dict["steps"]) : stringArray(dict["items"])
            guard !items.isEmpty else { return nil }
            return .nextSteps(NextStepsBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title", "heading"]),
                items: items
            ))

        case "status":
            let title = firstString(dict, keys: ["title", "message", "summary"]) ?? "Durum"
            let statusStr = firstString(dict, keys: ["status", "state"]) ?? "running"
            return .status(StatusBlock(
                stableBlockId: stable,
                status: StatusBlock.Status(rawValue: statusStr) ?? .running,
                title: title,
                detail: firstString(dict, keys: ["detail", "description", "content", "markdown"])
            ))

        case "task_trace":
            let taskId = firstString(dict, keys: ["taskId", "task_id"]) ?? stable ?? "task_trace"
            let title = firstString(dict, keys: ["title", "message"]) ?? "Görev yürütülüyor"
            let statusStr = firstString(dict, keys: ["status", "state"]) ?? "running"
            let rawSteps = dictArray(dict["steps"])
            let steps = rawSteps.compactMap { TaskTraceStep.parse(from: $0) }
            return .taskTrace(TaskTraceBlock(
                stableBlockId: stable,
                taskId: taskId,
                status: TaskTraceBlock.Status(rawValue: statusStr) ?? .running,
                title: title,
                phase: firstString(dict, keys: ["phase"]),
                summary: firstString(dict, keys: ["summary", "markdown", "content"]),
                progressLabel: firstString(dict, keys: ["progressLabel", "progress_label"]),
                activeStepId: firstString(dict, keys: ["activeStepId", "active_step_id"]),
                steps: steps
            ))

        case "attachment_context", "context_signal":
            let title = firstString(dict, keys: ["title", "heading"]) ?? "Bağlam"
            let rawItems = dictArray(dict["items"])
            let items = rawItems.compactMap { InfoCardItem.parse(from: $0) }
            return .infoCard(InfoCardBlock(
                stableBlockId: stable,
                type: rawType,
                title: title,
                items: items
            ))

        case "web_search":
            let query = firstString(dict, keys: ["query", "title", "summary"]) ?? ""
            var rawResults = dictArray(dict["results"])
            if rawResults.isEmpty { rawResults = dictArray(dict["sources"]) }
            if rawResults.isEmpty { rawResults = dictArray(dict["items"]) }
            if rawResults.isEmpty, let url = firstString(dict, keys: ["url", "link", "href"]) {
                rawResults = [["title": firstString(dict, keys: ["title", "source", "host"]) ?? url, "url": url]]
            }
            let results = rawResults.compactMap { WebSearchResult.parse(from: $0) }
            return .webSearch(WebSearchBlock(
                stableBlockId: stable,
                query: query,
                queries: stringArray(dict["queries"]).isEmpty ? (query.isEmpty ? [] : [query]) : stringArray(dict["queries"]),
                confidence: WebSearchBlock.Confidence(rawValue: firstString(dict, keys: ["confidence"]) ?? "medium") ?? .medium,
                results: results
            ))

        case "code":
            guard let code = firstString(dict, keys: ["code", "content", "markdown"]) else { return nil }
            return .code(CodeBlock(
                stableBlockId: stable,
                code: code,
                language: firstString(dict, keys: ["language", "lang"]),
                filename: firstString(dict, keys: ["filename", "fileName", "name"]),
                title: firstString(dict, keys: ["title"]),
                collapsed: boolValue(dict["collapsed"])
            ))

        case "table":
            let rawRows = dict["rows"] ?? dict["data"] ?? dict["items"]
            let cols = tableColumns(from: dict["columns"] ?? dict["headers"], rowsValue: rawRows)
            let rows = tableRows(from: rawRows, columns: cols)
            guard !cols.isEmpty else { return nil }
            return .table(TableBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title"]),
                summary: firstString(dict, keys: ["summary", "description", "markdown"]),
                columns: cols,
                rows: rows,
                totalRowCount: intValue(dict["totalRowCount"] ?? dict["total_row_count"]),
                caption: firstString(dict, keys: ["caption"]),
                density: TableBlock.Density(rawValue: firstString(dict, keys: ["density"]) ?? "comfortable") ?? .comfortable
            ))

        case "chart":
            let pointRows = dictArray(dict["points"]).isEmpty
                ? (dictArray(dict["data"]).isEmpty ? dictArray(dict["items"]) : dictArray(dict["data"]))
                : dictArray(dict["points"])
            let chartTypeStr = firstString(dict, keys: ["chartType", "chart_type", "kind", "block_type"]) ?? "bar"
            return .chart(ChartBlock(
                stableBlockId: stable,
                chartType: ChartBlock.ChartType(rawValue: chartTypeStr) ?? .bar,
                title: firstString(dict, keys: ["title"]),
                labels: stringArray(dict["labels"]).isEmpty
                    ? (stringArray(dict["categories"]).isEmpty ? (chartLabels(from: pointRows) ?? stringArray(dict["x"])) : stringArray(dict["categories"]))
                    : stringArray(dict["labels"]),
                values: doubleArray(dict["values"] ?? dict["y"]) ?? chartValues(from: pointRows),
                series: (dictArray(dict["series"]).isEmpty ? dictArray(dict["datasets"]) : dictArray(dict["series"]))
                    .compactMap { ChartSeries.parse(from: $0) },
                xLabel: firstString(dict, keys: ["xLabel", "x_label"]),
                yLabel: firstString(dict, keys: ["yLabel", "y_label"]),
                caption: firstString(dict, keys: ["caption", "summary"])
            ))

        case "math":
            guard let content = firstString(dict, keys: ["content", "latex", "tex", "equation", "expression", "markdown"]) else { return nil }
            return .math(MathBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title", "label"]),
                content: content,
                latex: firstString(dict, keys: ["latex", "tex"]),
                displayMode: boolValue(dict["displayMode"] ?? dict["display_mode"], default: true),
                result: firstString(dict, keys: ["result", "answer"]),
                explanation: firstString(dict, keys: ["explanation", "detail", "summary"])
            ))

        case "math_surface_3d":
            return .mathSurface3D(MathSurface3DBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title", "label"]),
                expression: firstString(dict, keys: ["expression", "expr", "formula", "function"]),
                caption: firstString(dict, keys: ["caption", "summary"])
            ))

        case "svg":
            return .svg(SvgBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title"]),
                svg: firstString(dict, keys: ["svg", "SVG", "markup", "source", "xml", "content", "code"]),
                url: firstString(dict, keys: ["url", "src"]),
                caption: firstString(dict, keys: ["caption", "summary"])
            ))

        case "file":
            guard let fileName = firstString(dict, keys: ["fileName", "filename", "name", "title"]) else { return nil }
            return .file(FileBlock(
                stableBlockId: stable,
                fileName: fileName,
                mimeType: firstString(dict, keys: ["mimeType", "mime_type", "contentType", "mime"]),
                sizeBytes: intValue(dict["sizeBytes"] ?? dict["size"] ?? dict["fileSize"]),
                preview: firstString(dict, keys: ["preview", "summary", "description"])
            ))

        case "attachment_ack":
            guard let summary = firstString(dict, keys: ["summary", "markdown", "text", "content"]) else { return nil }
            return .attachmentAck(AttachmentAckBlock(
                stableBlockId: stable,
                summary: summary,
                attachmentCount: intValue(dict["attachmentCount"] ?? dict["attachment_count"]) ?? 1,
                pageCount: intValue(dict["pageCount"] ?? dict["page_count"]),
                hasTable: dict["hasTable"] as? Bool ?? dict["has_table"] as? Bool,
                hasImage: dict["hasImage"] as? Bool ?? dict["has_image"] as? Bool
            ))

        case "image_analysis":
            guard let description = firstString(dict, keys: ["description", "markdown", "text", "content", "summary"]) else { return nil }
            return .imageAnalysis(ImageAnalysisBlock(
                stableBlockId: stable,
                description: description,
                detectedText: firstString(dict, keys: ["detectedText", "detected_text", "ocr"]),
                tags: stringArray(dict["tags"]).isEmpty ? stringArray(dict["labels"]) : stringArray(dict["tags"])
            ))

        case "goal_progress":
            guard let goalId = firstString(dict, keys: ["goalId", "goal_id", "id"]) else { return nil }
            let ofSteps = max(1, min(10_000, intValue(dict["ofSteps"] ?? dict["of_steps"] ?? dict["total"]) ?? 1))
            let step = max(0, min(ofSteps, intValue(dict["step"] ?? dict["current"]) ?? 0))
            let advancedTo = firstString(dict, keys: ["advancedTo", "advanced_to", "summary", "markdown", "text"])
                ?? ""
            return .goalProgress(GoalProgressBlock(
                stableBlockId: stable,
                goalId: goalId,
                step: step,
                ofSteps: ofSteps,
                advancedTo: advancedTo,
                blocker: firstString(dict, keys: ["blocker"]),
                done: boolValue(dict["done"] ?? dict["complete"] ?? dict["completed"])
            ))

        case "actionable":
            let kindStr = firstString(dict, keys: ["kind", "typeHint", "actionType"]) ?? "retry_option"
            let title = firstString(dict, keys: ["title", "label", "actionLabel", "message"]) ?? "İşlem gerekli"
            return .actionable(ActionableBlock(
                stableBlockId: stable,
                kind: ActionableBlock.Kind(rawValue: kindStr) ?? .retry_option,
                title: title,
                detail: firstString(dict, keys: ["detail", "description", "summary", "markdown"])
            ))

        case "block_group":
            var children = dictArray(dict["children"])
            if children.isEmpty { children = dictArray(dict["blocks"]) }
            if children.isEmpty { children = dictArray(dict["items"]) }
            let parsed = children.compactMap { ChatBlock.parse(from: $0) }
            return .blockGroup(BlockGroupBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title", "heading"]),
                children: parsed
            ))

        case "document_block":
            var sections = dictArray(dict["sections"]).compactMap { DocumentSection.parse(from: $0) }
            if sections.isEmpty, let content = firstString(dict, keys: ["content", "markdown", "text"]) {
                sections = [DocumentSection(heading: nil, content: content, level: nil, role: nil)]
            }
            return .document(DocumentBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title", "name"]),
                sections: sections,
                format: firstString(dict, keys: ["format", "mimeType", "mime_type"]),
                summary: firstString(dict, keys: ["summary", "description", "markdown"])
            ))

        case "reasoning_trace":
            return .reasoningTrace(ReasoningTraceBlock(
                stableBlockId: stable,
                status: firstString(dict, keys: ["status", "state"]) ?? "completed",
                content: firstString(dict, keys: ["content", "markdown", "text"]) ?? ""
            ))

        case "terminal":
            let exit = intValue(dict["exitCode"] ?? dict["exit_code"])
            return .terminal(TerminalBlock(
                stableBlockId: stable,
                output: firstString(dict, keys: ["output", "content", "text", "markdown"]) ?? "",
                command: firstString(dict, keys: ["command", "cmd"]),
                exitCode: exit,
                truncated: boolValue(dict["truncated"])
            ))

        case "automation":
            return .automation(AutomationBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title", "name"]) ?? "Otomasyon",
                description: firstString(dict, keys: ["description", "summary", "markdown", "text"]) ?? "",
                schedule: firstString(dict, keys: ["schedule", "cron", "when"]),
                triggerType: firstString(dict, keys: ["triggerType", "trigger_type", "trigger"]),
                steps: stringArray(dict["steps"]),
                automationId: firstString(dict, keys: ["automationId", "automation_id", "id"])
            ))

        case "pdf_generate":
            let pages = intValue(dict["estimatedPages"] ?? dict["estimated_pages"] ?? dict["pages"]) ?? 1
            let sections = dictArray(dict["sections"]).map {
                PdfGenerateSection(
                    title: firstString($0, keys: ["title", "heading"]),
                    content: firstString($0, keys: ["content", "markdown", "text"]) ?? ""
                )
            }
            return .pdfGenerate(PdfGenerateBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title", "name"]),
                estimatedPages: pages,
                language: firstString(dict, keys: ["language", "lang"]) ?? "tr",
                sections: sections
            ))

        case "pdf_viewer":
            let pageCount = intValue(dict["pageCount"] ?? dict["page_count"])
            return .pdfViewer(PdfViewerBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title", "name"]),
                fileId: firstString(dict, keys: ["fileId", "file_id", "documentId", "document_id", "id"]),
                localPath: firstString(dict, keys: ["localPath", "local_path", "path"]),
                remoteUrl: firstString(dict, keys: ["remoteUrl", "remote_url", "url", "downloadUrl", "download_url"]),
                pageCount: pageCount,
                thumbnailUrl: firstString(dict, keys: ["thumbnailUrl", "thumbnail_url"])
            ))

        case "desktop_suggestion":
            return .desktopSuggestion(DesktopSuggestionBlock(
                stableBlockId: stable,
                reason: firstString(dict, keys: ["reason", "summary", "markdown", "text"]) ?? "",
                requiredCapabilities: stringArray(dict["requiredCapabilities"]).isEmpty
                    ? stringArray(dict["required_capabilities"])
                    : stringArray(dict["requiredCapabilities"]),
                detectedIntent: firstString(dict, keys: ["detectedIntent", "detected_intent", "intent"])
            ))

        case "memory_echo":
            return .memoryEcho(MemoryEchoBlock(
                stableBlockId: stable,
                recall: firstString(dict, keys: ["recall", "memory", "title", "content"]) ?? "",
                question: firstString(dict, keys: ["question", "markdown", "text"]) ?? "",
                confidence: doubleValue(dict["confidence"]) ?? 0
            ))

        case "proactive_touch":
            return .proactiveTouch(ProactiveTouchBlock(
                stableBlockId: stable,
                suggestion: firstString(dict, keys: ["suggestion", "content", "markdown", "text"]) ?? "",
                cta: firstString(dict, keys: ["cta", "action", "label"]) ?? "",
                context: firstString(dict, keys: ["context", "reason", "summary"])
            ))

        case "artifact":
            return .artifact(ArtifactBlock(
                stableBlockId: stable,
                artifactType: firstString(dict, keys: ["artifactType", "artifact_type", "typeHint"]) ?? "image",
                url: firstString(dict, keys: ["url", "uri", "src", "path"]) ?? "",
                artifactId: firstString(dict, keys: ["artifactId", "artifact_id", "id"]),
                title: firstString(dict, keys: ["title", "name"]),
                mime: firstString(dict, keys: ["mime", "mimeType", "mime_type", "contentType"]),
                summary: firstString(dict, keys: ["summary", "description", "markdown"]),
                preview: firstString(dict, keys: ["preview", "previewText", "preview_text", "content"])
            ))

        case "document_block_skeleton":
            return .documentSkeleton(DocumentSkeletonBlock(
                stableBlockId: stable,
                title: firstString(dict, keys: ["title", "name"])
            ))

        default:
            // Future-proof: extract common fields so a new/unknown backend block
            // still renders readably instead of leaking raw JSON.
            if let generic = GenericBlock.parse(rawType: rawType, dict: dict, stableBlockId: stable) {
                return .generic(generic)
            }
            let text = firstString(dict, keys: ["markdown", "text", "content", "summary"])
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
        func str(_ keys: [String]) -> String? {
            for key in keys {
                if let value = dict[key] as? String, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    return value
                }
            }
            return nil
        }
        guard let id = str(["id", "stepId", "step_id"]),
              let label = str(["label", "title", "name"]) else { return nil }
        let statusStr = str(["status", "state"]) ?? "pending"
        return TaskTraceStep(
            id: id,
            label: label,
            status: Status(rawValue: statusStr) ?? .pending,
            detail: str(["detail", "description", "summary"])
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
        let label = (dict["label"] as? String) ?? (dict["title"] as? String) ?? (dict["name"] as? String)
        let value = (dict["value"] as? String) ?? (dict["text"] as? String) ?? (dict["content"] as? String)
        guard let label, let value else { return nil }
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
        let url = (dict["url"] as? String) ?? (dict["link"] as? String) ?? (dict["href"] as? String)
        guard let url, !url.isEmpty else { return nil }
        let title = (dict["title"] as? String) ?? (dict["name"] as? String) ?? (dict["source"] as? String) ?? url
        return WebSearchResult(
            title: title,
            url: url,
            snippet: (dict["snippet"] as? String) ?? (dict["summary"] as? String) ?? (dict["description"] as? String),
            sourceHost: (dict["sourceHost"] as? String) ?? (dict["source_host"] as? String) ?? (dict["host"] as? String),
            verificationState: (dict["verificationState"] as? String) ?? (dict["verification_state"] as? String) ?? "unverified"
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
        func strings(_ value: Any?) -> [String]? {
            guard let values = value as? [Any] else { return nil }
            let mapped = values.compactMap { $0 as? String }
            return mapped.isEmpty ? nil : mapped
        }
        func doubles(_ value: Any?) -> [Double]? {
            guard let values = value as? [Any] else { return nil }
            let mapped = values.compactMap { item -> Double? in
                if let double = item as? Double { return double }
                if let int = item as? Int { return Double(int) }
                if let string = item as? String { return Double(string) }
                return nil
            }
            return mapped.isEmpty ? nil : mapped
        }
        let values = doubles(dict["values"] ?? dict["data"] ?? dict["y"])
        return ChartSeries(
            name: (dict["name"] as? String) ?? (dict["title"] as? String) ?? (dict["label"] as? String),
            labels: strings(dict["labels"] ?? dict["categories"] ?? dict["x"]),
            values: values
        )
    }
}

struct ChartBlock: Equatable {
    enum ChartType: String {
        case bar, line, pie, area, scatter, geometry, function_, surface3d, mesh, heatmap
        init?(rawValue: String) {
            switch rawValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
            case "bar", "bar_chart": self = .bar
            case "line", "line_chart": self = .line
            case "pie", "pie_chart", "donut", "doughnut": self = .pie
            case "area", "area_chart": self = .area
            case "scatter", "scatter_plot": self = .scatter
            case "geometry": self = .geometry
            case "function", "fn": self = .function_
            case "surface3d", "surface_3d", "3d_surface": self = .surface3d
            case "mesh": self = .mesh
            case "heatmap", "heat_map": self = .heatmap
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
        let content = (dict["content"] as? String)
            ?? (dict["markdown"] as? String)
            ?? (dict["text"] as? String)
            ?? ""
        guard !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return DocumentSection(
            heading: (dict["heading"] as? String) ?? (dict["title"] as? String),
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
