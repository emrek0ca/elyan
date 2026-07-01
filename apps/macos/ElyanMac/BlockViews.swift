import SwiftUI
import Charts

// MARK: - BlocksRenderer
// Top-level entry: renders a [ChatBlock] array dispatching to each block view.

struct BlocksRenderer: View {
    let blocks: [ChatBlock]
    var fontSize: Double = 14
    var compact: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 6 : 10) {
            ForEach(blocks) { block in
                BlockDispatch(block: block, fontSize: fontSize, compact: compact)
            }
        }
    }
}

// MARK: - BlockDispatch

private struct BlockDispatch: View {
    let block: ChatBlock
    let fontSize: Double
    let compact: Bool

    var body: some View {
        switch block {
        case .text(let b):
            MarkdownBubble(markdown: b.markdown, fontSize: fontSize, compact: compact)

        case .summary(let b):
            SummaryBlockView(block: b, fontSize: fontSize)

        case .nextSteps(let b):
            NextStepsBlockView(block: b, fontSize: fontSize)

        case .status(let b):
            StatusBlockView(block: b)

        case .taskTrace(let b):
            TaskTraceBlockView(block: b)

        case .infoCard(let b):
            InfoCardBlockView(block: b, fontSize: fontSize)

        case .webSearch(let b):
            WebSearchBlockView(block: b)

        case .code(let b):
            CodeBlockView(block: b)

        case .table(let b):
            TableBlockView(block: b)

        case .chart(let b):
            ChartBlockView(block: b)

        case .math(let b):
            MathBlockView(block: b, fontSize: fontSize)

        case .mathSurface3D(let b):
            MathSurface3DBlockView(block: b)

        case .svg(let b):
            SvgBlockView(block: b)

        case .file(let b):
            FileBlockView(block: b)

        case .attachmentAck(let b):
            AttachmentAckBlockView(block: b)

        case .imageAnalysis(let b):
            ImageAnalysisBlockView(block: b)

        case .actionable(let b):
            ActionableBlockView(block: b)

        case .blockGroup(let b):
            BlockGroupView(block: b, fontSize: fontSize, compact: compact)

        case .document(let b):
            DocumentBlockView(block: b, fontSize: fontSize)

        case .unknown(_, let text):
            if !text.isEmpty {
                MarkdownBubble(markdown: text, fontSize: fontSize, compact: compact)
            } else {
                // Invisible unknown blocks — don't render empty space
                EmptyView()
            }
        }
    }
}

// MARK: - MarkdownBubble

struct MarkdownBubble: View {
    let markdown: String
    var fontSize: Double = 14
    var compact: Bool = false

    private var attributed: AttributedString {
        (try? AttributedString(
            markdown: markdown,
            options: .init(allowsExtendedAttributes: true, interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(markdown)
    }

    var body: some View {
        Text(attributed)
            .font(.system(size: fontSize))
            .textSelection(.enabled)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, compact ? 10 : 14)
            .padding(.vertical, compact ? 6 : 10)
            .background(Color(NSColor.controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: compact ? 8 : 14, style: .continuous))
    }
}

// MARK: - SummaryBlockView

private struct SummaryBlockView: View {
    let block: SummaryBlock
    let fontSize: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let title = block.title {
                Label(title, systemImage: "text.alignleft")
                    .font(.system(size: fontSize, weight: .semibold))
                    .foregroundStyle(.primary)
            }
            Text(block.summary)
                .font(.system(size: fontSize - 1))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.accentColor.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.accentColor.opacity(0.18), lineWidth: 1)
        )
    }
}

// MARK: - NextStepsBlockView

private struct NextStepsBlockView: View {
    let block: NextStepsBlock
    let fontSize: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let title = block.title {
                Text(title)
                    .font(.system(size: fontSize, weight: .semibold))
            }
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(block.items.enumerated()), id: \.offset) { idx, item in
                    HStack(alignment: .top, spacing: 10) {
                        Text("\(idx + 1)")
                            .font(.system(size: 11, weight: .bold, design: .rounded))
                            .foregroundStyle(.white)
                            .frame(width: 20, height: 20)
                            .background(Color.accentColor)
                            .clipShape(Circle())
                        Text(item)
                            .font(.system(size: fontSize - 1))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .padding(12)
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

// MARK: - StatusBlockView

private struct StatusBlockView: View {
    let block: StatusBlock

    private var icon: String {
        switch block.status {
        case .completed:          return "checkmark.circle.fill"
        case .failed, .degraded:  return "xmark.circle.fill"
        case .waiting_approval:   return "person.badge.clock.fill"
        case .needs_desktop:      return "desktopcomputer.and.arrow.down"
        case .retrying:           return "arrow.clockwise.circle.fill"
        case .running:            return "ellipsis.circle.fill"
        }
    }

    private var iconColor: Color {
        switch block.status {
        case .completed:          return .green
        case .failed, .degraded:  return .red
        case .waiting_approval:   return .orange
        case .needs_desktop:      return .blue
        default:                  return .accentColor
        }
    }

    var body: some View {
        HStack(spacing: 10) {
            if block.status.isActive {
                ProgressView().controlSize(.small)
            } else {
                Image(systemName: icon)
                    .foregroundStyle(iconColor)
                    .font(.system(size: 16))
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(block.title)
                    .font(.system(size: 13, weight: .medium))
                if let detail = block.detail {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Material.ultraThin)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(iconColor.opacity(0.25), lineWidth: 1)
        )
    }
}

// MARK: - TaskTraceBlockView

private struct TaskTraceBlockView: View {
    let block: TaskTraceBlock
    @State private var expanded = true

    private var isRunning: Bool { block.status == .running }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            Button(action: { withAnimation(.spring(duration: 0.25)) { expanded.toggle() } }) {
                HStack(spacing: 10) {
                    if isRunning {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: block.status == .completed ? "checkmark.circle.fill" : "xmark.circle.fill")
                            .foregroundStyle(block.status == .completed ? .green : .red)
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        Text(block.title)
                            .font(.system(size: 13, weight: .semibold))
                        if let phase = block.phase {
                            Text(phase)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                }
                .padding(12)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            // Steps
            if expanded {
                Divider()
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(block.steps, id: \.id) { step in
                        TaskStepRow(step: step, isActive: step.id == block.activeStepId)
                    }
                }
                .padding(.vertical, 4)

                // Summary
                if let summary = block.summary {
                    Divider()
                    Text(summary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(12)
                }
            }
        }
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.primary.opacity(0.1), lineWidth: 1)
        )
    }
}

private struct TaskStepRow: View {
    let step: TaskTraceStep
    let isActive: Bool

    private var icon: String {
        let stepId = TaskTraceStep.StepId(rawValue: step.id)
        switch step.status {
        case .completed: return "checkmark.circle.fill"
        case .failed:    return "xmark.circle.fill"
        case .skipped:   return "minus.circle"
        case .running:   return "circle.fill"
        case .pending:   return stepId?.icon ?? "circle"
        }
    }

    private var iconColor: Color {
        switch step.status {
        case .completed: return .green
        case .failed:    return .red
        case .running:   return .accentColor
        default:         return .secondary
        }
    }

    var body: some View {
        HStack(spacing: 10) {
            if step.status == .running {
                ProgressView().controlSize(.mini)
                    .frame(width: 16)
            } else {
                Image(systemName: icon)
                    .font(.system(size: 13))
                    .foregroundStyle(iconColor)
                    .frame(width: 16)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(step.label)
                    .font(.system(size: 12, weight: isActive ? .semibold : .regular))
                    .foregroundStyle(isActive ? .primary : .secondary)
                if let detail = step.detail {
                    Text(detail)
                        .font(.system(size: 11))
                        .foregroundStyle(.tertiary)
                        .lineLimit(2)
                }
            }
            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(isActive ? Color.accentColor.opacity(0.06) : .clear)
    }
}

// MARK: - InfoCardBlockView (attachment_context / context_signal)

private struct InfoCardBlockView: View {
    let block: InfoCardBlock
    let fontSize: Double

    private var typeIcon: String {
        block.type == "context_signal" ? "antenna.radiowaves.left.and.right" : "paperclip"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(block.title, systemImage: typeIcon)
                .font(.system(size: fontSize - 1, weight: .semibold))
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 4) {
                ForEach(block.items, id: \.label) { item in
                    HStack(alignment: .top) {
                        Text(item.label)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(.secondary)
                            .frame(minWidth: 80, alignment: .leading)
                        Text(item.value)
                            .font(.system(size: 11))
                            .foregroundStyle(.primary)
                    }
                }
            }
        }
        .padding(12)
        .background(Material.ultraThin)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

// MARK: - WebSearchBlockView

private struct WebSearchBlockView: View {
    let block: WebSearchBlock
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header row
            Button(action: { withAnimation(.spring(duration: 0.2)) { expanded.toggle() } }) {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                        .font(.system(size: 13))
                    Text("Web araması: \"\(block.query)\"")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Spacer()
                    confidenceBadge
                    Image(systemName: "chevron.down")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                }
                .padding(10)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if expanded {
                Divider()
                VStack(spacing: 1) {
                    ForEach(block.results, id: \.url) { result in
                        SearchResultRow(result: result)
                    }
                }
                .padding(.vertical, 4)
            }
        }
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.primary.opacity(0.1), lineWidth: 1)
        )
    }

    @ViewBuilder private var confidenceBadge: some View {
        let (label, color): (String, Color) = {
            switch block.confidence {
            case .high: return ("Yüksek", .green)
            case .medium: return ("Orta", .orange)
            case .low: return ("Düşük", .red)
            }
        }()
        Text(label)
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.12))
            .clipShape(Capsule())
    }
}

private struct SearchResultRow: View {
    let result: WebSearchResult

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                verificationIcon
                Link(destination: URL(string: result.url) ?? URL(string: "https://")!) {
                    Text(result.title)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.blue)
                        .lineLimit(2)
                }
            }
            if let host = result.sourceHost {
                Text(host)
                    .font(.system(size: 10))
                    .foregroundStyle(.tertiary)
            }
            if let snippet = result.snippet {
                Text(snippet)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    @ViewBuilder private var verificationIcon: some View {
        switch result.verificationState {
        case "verified":
            Image(systemName: "checkmark.seal.fill").foregroundStyle(.green).font(.system(size: 10))
        case "partial":
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange).font(.system(size: 10))
        default:
            EmptyView()
        }
    }
}

// MARK: - CodeBlockView

struct CodeBlockView: View {
    let block: CodeBlock
    @State private var isCollapsed: Bool
    @State private var copied = false

    init(block: CodeBlock) {
        self.block = block
        self._isCollapsed = State(initialValue: block.collapsed)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack {
                if let filename = block.filename {
                    Label(filename, systemImage: "doc.text")
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                } else if let lang = block.language {
                    Text(lang)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                HStack(spacing: 10) {
                    Button(action: copyCode) {
                        Label(copied ? "Kopyalandı" : "Kopyala",
                              systemImage: copied ? "checkmark" : "doc.on.doc")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)

                    Button(action: { withAnimation { isCollapsed.toggle() } }) {
                        Image(systemName: isCollapsed ? "chevron.down.circle" : "chevron.up.circle")
                            .font(.system(size: 14))
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color(NSColor.windowBackgroundColor).opacity(0.5))

            if !isCollapsed {
                Divider()
                ScrollView(.horizontal, showsIndicators: false) {
                    Text(block.code)
                        .font(.system(size: 12, design: .monospaced))
                        .textSelection(.enabled)
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .background(Color(NSColor.controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.primary.opacity(0.1), lineWidth: 1)
        )
    }

    private func copyCode() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(block.code, forType: .string)
        withAnimation { copied = true }
        Task { try? await Task.sleep(nanoseconds: 2_000_000_000); withAnimation { copied = false } }
    }
}

// MARK: - TableBlockView

private struct TableBlockView: View {
    let block: TableBlock
    @State private var sortColumn: Int? = nil
    @State private var ascending = true

    private var displayRows: [[String]] {
        guard let col = sortColumn, col < block.columns.count else { return block.rows }
        return block.rows.sorted {
            let a = col < $0.count ? $0[col] : ""
            let b = col < $1.count ? $1[col] : ""
            return ascending ? a < b : a > b
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let title = block.title {
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
                    .padding(.horizontal, 12)
                    .padding(.top, 10)
                    .padding(.bottom, 6)
            }

            ScrollView(.horizontal) {
                VStack(alignment: .leading, spacing: 0) {
                    // Column headers
                    HStack(spacing: 0) {
                        ForEach(Array(block.columns.enumerated()), id: \.offset) { idx, col in
                            Button(action: {
                                if sortColumn == idx { ascending.toggle() }
                                else { sortColumn = idx; ascending = true }
                            }) {
                                HStack(spacing: 4) {
                                    Text(col)
                                        .font(.system(size: 11, weight: .semibold))
                                        .foregroundStyle(.secondary)
                                    if sortColumn == idx {
                                        Image(systemName: ascending ? "chevron.up" : "chevron.down")
                                            .font(.system(size: 9))
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                .padding(.horizontal, 10)
                                .padding(.vertical, 8)
                                .frame(minWidth: 80, alignment: .leading)
                            }
                            .buttonStyle(.plain)
                            if idx < block.columns.count - 1 {
                                Divider().frame(height: 28)
                            }
                        }
                    }
                    .background(Color.primary.opacity(0.04))

                    Divider()

                    // Data rows
                    ForEach(Array(displayRows.enumerated()), id: \.offset) { rowIdx, row in
                        HStack(spacing: 0) {
                            ForEach(Array(block.columns.enumerated()), id: \.offset) { colIdx, _ in
                                Text(colIdx < row.count ? row[colIdx] : "")
                                    .font(.system(size: 12))
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 7)
                                    .frame(minWidth: 80, alignment: .leading)
                                if colIdx < block.columns.count - 1 {
                                    Divider()
                                }
                            }
                        }
                        .background(rowIdx % 2 == 0 ? Color.clear : Color.primary.opacity(0.025))
                        if rowIdx < displayRows.count - 1 {
                            Divider()
                        }
                    }

                    if let total = block.totalRowCount, total > block.rows.count {
                        Text("+ \(total - block.rows.count) daha")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .padding(10)
                    }
                }
            }

            if let caption = block.caption {
                Text(caption)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 12)
                    .padding(.bottom, 10)
            }
        }
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }
}

// MARK: - ChartBlockView (Swift Charts — macOS 14+)

private struct ChartBlockView: View {
    let block: ChartBlock

    private var combinedLabels: [String] {
        block.labels ?? block.series?.first?.labels ?? []
    }

    private var combinedValues: [Double] {
        block.values ?? block.series?.first?.values ?? []
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let title = block.title {
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
            }

            let labels = combinedLabels
            let values = combinedValues
            let pairs = Array(zip(labels, values))

            if pairs.isEmpty && (block.series?.isEmpty ?? true) {
                Text("Grafik verisi bulunamadı.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                chartBody(labels: labels, values: values)
                    .frame(height: 180)
                    .chartXAxis {
                        AxisMarks(values: .automatic) { _ in
                            AxisValueLabel()
                                .font(.system(size: 10))
                        }
                    }
                    .chartYAxis {
                        AxisMarks(values: .automatic) { _ in
                            AxisValueLabel()
                                .font(.system(size: 10))
                            AxisGridLine()
                        }
                    }
            }

            if let caption = block.caption {
                Text(caption)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    @ViewBuilder
    private func chartBody(labels: [String], values: [Double]) -> some View {
        switch block.chartType {
        case .bar:
            Chart(Array(zip(labels, values)), id: \.0) { label, value in
                BarMark(x: .value("X", label), y: .value("Y", value))
                    .foregroundStyle(Color.accentColor.gradient)
            }
        case .line, .area:
            Chart(Array(zip(labels, values)), id: \.0) { label, value in
                LineMark(x: .value("X", label), y: .value("Y", value))
                    .foregroundStyle(Color.accentColor)
                if block.chartType == .area {
                    AreaMark(x: .value("X", label), y: .value("Y", value))
                        .foregroundStyle(Color.accentColor.opacity(0.15))
                }
            }
        case .scatter:
            Chart(Array(zip(labels, values)), id: \.0) { label, value in
                PointMark(x: .value("X", label), y: .value("Y", value))
                    .foregroundStyle(Color.accentColor)
            }
        default:
            // Fallback: bar chart
            Chart(Array(zip(labels, values)), id: \.0) { label, value in
                BarMark(x: .value("X", label), y: .value("Y", value))
                    .foregroundStyle(Color.accentColor.gradient)
            }
        }
    }
}

// MARK: - MathBlockView

private struct MathBlockView: View {
    let block: MathBlock
    let fontSize: Double

    private var displayContent: String {
        block.latex ?? block.content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let title = block.title {
                Text(title)
                    .font(.system(size: fontSize, weight: .semibold))
            }

            // LaTeX displayed as monospaced (native rendering — no WebKit needed)
            ScrollView(.horizontal, showsIndicators: false) {
                Text(displayContent)
                    .font(.system(size: fontSize, design: .monospaced))
                    .textSelection(.enabled)
                    .padding(10)
            }
            .background(Color(NSColor.controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            if let result = block.result {
                HStack(spacing: 6) {
                    Text("=")
                        .font(.system(size: fontSize, weight: .bold))
                        .foregroundStyle(.secondary)
                    Text(result)
                        .font(.system(size: fontSize, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Color.accentColor)
                        .textSelection(.enabled)
                }
            }

            if let explanation = block.explanation {
                Text(explanation)
                    .font(.system(size: fontSize - 1))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(12)
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

// MARK: - MathSurface3DBlockView

private struct MathSurface3DBlockView: View {
    let block: MathSurface3DBlock

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "chart.xyaxis.line")
                .font(.system(size: 24))
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 4) {
                Text(block.title ?? "3D Yüzey Grafiği")
                    .font(.system(size: 13, weight: .semibold))
                if let expr = block.expression {
                    Text(expr)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
                if let caption = block.caption {
                    Text(caption)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
        }
        .padding(12)
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

// MARK: - SvgBlockView

private struct SvgBlockView: View {
    let block: SvgBlock
    @State private var rendered: NSImage? = nil
    @State private var failed = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let title = block.title {
                Text(title).font(.system(size: 13, weight: .semibold))
            }
            if let image = rendered {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxHeight: 300)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            } else if let url = block.url, let nsUrl = URL(string: url) {
                AsyncImage(url: nsUrl) { phase in
                    switch phase {
                    case .success(let img):
                        img.resizable().aspectRatio(contentMode: .fit).frame(maxHeight: 300)
                    case .failure:
                        svgFallback
                    default:
                        ProgressView().frame(height: 80).frame(maxWidth: .infinity)
                    }
                }
            } else {
                svgFallback
            }
            if let caption = block.caption {
                Text(caption).font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private var svgFallback: some View {
        HStack(spacing: 8) {
            Image(systemName: "photo.badge.arrow.down.fill")
                .foregroundStyle(.secondary)
            Text("SVG içerik")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(height: 60)
        .frame(maxWidth: .infinity)
        .background(Color.primary.opacity(0.04))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - FileBlockView

struct FileBlockView: View {
    let block: FileBlock

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: block.icon)
                .font(.system(size: 22, weight: .medium))
                .foregroundStyle(.tint)
                .frame(width: 32)

            VStack(alignment: .leading, spacing: 2) {
                Text(block.fileName)
                    .font(.system(size: 13, weight: .semibold))
                    .lineLimit(2)
                HStack(spacing: 6) {
                    if let mime = block.mimeType {
                        Text(mime.components(separatedBy: "/").last?.uppercased() ?? mime)
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                    }
                    if let size = block.formattedSize {
                        Text("·").foregroundStyle(.tertiary)
                        Text(size)
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                    }
                }
                if let preview = block.preview {
                    Text(preview)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .padding(.top, 2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }
}

// MARK: - AttachmentAckBlockView

private struct AttachmentAckBlockView: View {
    let block: AttachmentAckBlock

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .font(.system(size: 18))
            VStack(alignment: .leading, spacing: 3) {
                Text(block.summary)
                    .font(.system(size: 13))
                HStack(spacing: 8) {
                    if block.attachmentCount > 0 {
                        Label("\(block.attachmentCount) dosya", systemImage: "paperclip")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                    if let pages = block.pageCount, pages > 0 {
                        Text("·").foregroundStyle(.tertiary)
                        Label("\(pages) sayfa", systemImage: "doc.text")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Color.green.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.green.opacity(0.2), lineWidth: 1)
        )
    }
}

// MARK: - ImageAnalysisBlockView

private struct ImageAnalysisBlockView: View {
    let block: ImageAnalysisBlock
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "camera.metering.unknown")
                    .foregroundStyle(.tint)
                Text("Görsel Analizi")
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
                Button(action: { withAnimation { expanded.toggle() } }) {
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }

            Text(block.description)
                .font(.system(size: 13))
                .fixedSize(horizontal: false, vertical: true)

            if expanded {
                if let detected = block.detectedText, !detected.isEmpty {
                    Divider()
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Algılanan metin")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                        Text(detected)
                            .font(.system(size: 12, design: .monospaced))
                            .textSelection(.enabled)
                    }
                }

                if let tags = block.tags, !tags.isEmpty {
                    Divider()
                    FlowLayout(tags: tags)
                }
            }
        }
        .padding(12)
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

// MARK: - ActionableBlockView

struct ActionableBlockView: View {
    let block: ActionableBlock
    var onTap: (() -> Void)? = nil

    private var icon: String {
        switch block.kind {
        case .approval_needed: return "person.badge.key.fill"
        case .choose_device:   return "desktopcomputer"
        case .retry_option:    return "arrow.clockwise"
        case .openHistory:     return "clock"
        case .restoreContext:  return "arrow.counterclockwise"
        }
    }

    private var buttonColor: Color {
        switch block.kind {
        case .approval_needed: return .orange
        case .retry_option:    return .blue
        default:               return .accentColor
        }
    }

    var body: some View {
        Button(action: { onTap?() }) {
            HStack(spacing: 10) {
                Image(systemName: icon)
                    .foregroundStyle(buttonColor)
                    .font(.system(size: 16))
                VStack(alignment: .leading, spacing: 2) {
                    Text(block.title)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(.primary)
                    if let detail = block.detail {
                        Text(detail)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.tertiary)
            }
            .padding(12)
            .background(buttonColor.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(buttonColor.opacity(0.3), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - BlockGroupView

private struct BlockGroupView: View {
    let block: BlockGroupBlock
    let fontSize: Double
    let compact: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let title = block.title {
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.secondary)
                Divider()
            }
            BlocksRenderer(blocks: block.children, fontSize: fontSize, compact: compact)
        }
        .padding(compact ? 8 : 12)
        .background(Material.ultraThin)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

// MARK: - DocumentBlockView

private struct DocumentBlockView: View {
    let block: DocumentBlock
    let fontSize: Double
    @State private var collapsed = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            Button(action: { withAnimation { collapsed.toggle() } }) {
                HStack(spacing: 8) {
                    Image(systemName: "doc.richtext.fill")
                        .foregroundStyle(.tint)
                    Text(block.title ?? "Belge")
                        .font(.system(size: 13, weight: .semibold))
                    if let summary = block.summary {
                        Text("·")
                            .foregroundStyle(.tertiary)
                        Text(summary)
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(collapsed ? -90 : 0))
                }
                .padding(12)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if !collapsed {
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        ForEach(Array(block.sections.enumerated()), id: \.offset) { _, section in
                            DocumentSectionView(section: section, fontSize: fontSize)
                        }
                    }
                    .padding(14)
                }
                .frame(maxHeight: 400)
            }
        }
        .background(Material.regular)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.primary.opacity(0.1), lineWidth: 1)
        )
    }
}

private struct DocumentSectionView: View {
    let section: DocumentSection
    let fontSize: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let heading = section.heading {
                Text(heading)
                    .font(.system(size: fontSize + (section.level == 1 ? 2 : section.level == 2 ? 1 : 0), weight: .semibold))
            }
            let attributed = (try? AttributedString(
                markdown: section.content,
                options: .init(allowsExtendedAttributes: true, interpretedSyntax: .inlineOnlyPreservingWhitespace)
            )) ?? AttributedString(section.content)
            Text(attributed)
                .font(.system(size: fontSize - 1))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: - FlowLayout (for tags)

private struct FlowLayout: View {
    let tags: [String]

    var body: some View {
        // Simple wrapping layout using adaptive columns
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 60), spacing: 6)], spacing: 6) {
            ForEach(tags, id: \.self) { tag in
                Text(tag)
                    .font(.system(size: 11))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Color.accentColor.opacity(0.1))
                    .clipShape(Capsule())
            }
        }
    }
}

// MARK: - Legacy BlockView (backward compat)

struct BlockView: View {
    let blockType: String
    let content: String

    var body: some View {
        if let block = ChatBlock.parse(from: ["type": blockType, "markdown": content, "text": content, "code": content, "content": content]) {
            BlockDispatch(block: block, fontSize: 14, compact: false)
        } else {
            Text(content).padding()
        }
    }
}
