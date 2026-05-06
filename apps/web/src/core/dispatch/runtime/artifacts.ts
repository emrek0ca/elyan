import { createWriteStream } from 'fs';
import { readFile, rm, writeFile } from 'fs/promises';
import { createHash } from 'crypto';
import path from 'path';
import ExcelJS from 'exceljs';
import { z } from 'zod';
import type { DispatchTask, DispatchTaskArtifact, DispatchArtifactKind } from '../types';
import type { RunTraceReport } from '@/core/observability/run-trace';
import type { OperatorRun } from '@/core/operator';
import type { ExecutionExplanation } from '@/core/execution/explain';
import { resolveTaskWorkspacePaths, ensureTaskWorkspace } from './workspace';

type ArtifactSource = {
  text: string;
  sources: Array<{ url: string; title: string }>;
  plan: {
    taskIntent: string;
    routingMode: string;
    reasoningDepth: string;
  };
  classification: {
    intent: string;
    confidence: string;
  };
  modelId: string;
  modelProvider?: string;
  runId?: string;
  observabilityTrace?: RunTraceReport;
  executionExplanation?: ExecutionExplanation;
  learningMetadata?: Record<string, unknown>;
};

const requestedArtifactSchema = z.enum(['pdf', 'pptx', 'markdown', 'spreadsheet', 'code_file']);

function nowIso() {
  return new Date().toISOString();
}

function checksumBytes(buffer: Buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

function assertArtifactPathInsideWorkspace(filePath: string, workspaceRoot: string) {
  const relative = path.relative(workspaceRoot, filePath);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error(`Artifact path escapes the workspace: ${filePath}`);
  }
}

function sanitizeBaseName(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function inferTaskWorkspaceRoot(taskId: string, filePath: string) {
  const marker = `${path.sep}tasks${path.sep}${taskId}${path.sep}`;
  const markerIndex = filePath.indexOf(marker);
  if (markerIndex >= 0) {
    return filePath.slice(0, markerIndex + marker.length - 1);
  }

  return path.dirname(path.dirname(filePath));
}

function summaryLines(task: DispatchTask, response: ArtifactSource, operatorRun?: OperatorRun | null) {
  return [
    `# ${task.title}`,
    '',
    `- Task ID: ${task.id}`,
    `- Status: ${task.status}`,
    `- Progress: ${task.progress}`,
    `- Source: ${task.source}`,
    `- Objective: ${task.objective}`,
    `- Model: ${response.modelId}`,
    `- Provider: ${response.modelProvider ?? 'unknown'}`,
    `- Intent: ${response.classification.intent}`,
    `- Routing: ${response.plan.routingMode}`,
    `- Reasoning depth: ${response.plan.reasoningDepth}`,
    operatorRun?.id ? `- Operator run: ${operatorRun.id}` : '- Operator run: unavailable',
    '',
    '## Result',
    '',
    response.text || 'No response text was returned.',
    '',
    '## Sources',
    '',
    response.sources.length > 0
      ? response.sources.map((source, index) => `${index + 1}. ${source.title} - ${source.url}`).join('\n')
      : 'No sources were returned.',
  ];
}

function taskArtifactMimeType(kind: DispatchArtifactKind) {
  switch (kind) {
    case 'pdf':
      return 'application/pdf';
    case 'pptx':
      return 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
    case 'spreadsheet':
      return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    case 'code_file':
      return 'text/plain';
    case 'markdown':
    default:
      return 'text/markdown';
  }
}

async function writePdfReport(filePath: string, title: string, lines: string[]) {
  const { default: PDFDocument } = await import('pdfkit');
  await new Promise<void>((resolve, reject) => {
    const document = new PDFDocument({ size: 'A4', margin: 48 });
    const output = createWriteStream(filePath);

    output.on('finish', resolve);
    output.on('error', reject);
    document.on('error', reject);

    document.pipe(output);
    document.fontSize(18).text(title, { underline: false });
    document.moveDown();
    document.fontSize(11);

    for (const line of lines) {
      document.text(line.length > 120 ? line.slice(0, 117) + '...' : line);
    }

    document.end();
  });
}

async function writePptxReport(filePath: string, title: string, lines: string[]) {
  const { default: PptxGenJS } = await import('pptxgenjs');
  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_WIDE';

  const slide = pptx.addSlide();
  slide.background = { color: 'FFFFFF' };
  slide.addText(title, {
    x: 0.55,
    y: 0.35,
    w: 12.0,
    h: 0.6,
    fontSize: 26,
    bold: true,
    color: '1B4D5A',
    margin: 0,
  });
  slide.addText(lines.slice(0, 10).join('\n'), {
    x: 0.75,
    y: 1.15,
    w: 11.6,
    h: 5.6,
    fontSize: 16,
    color: '16323A',
    bullet: { indent: 16 },
    margin: 0,
    breakLine: true,
  });

  await pptx.writeFile({ fileName: filePath });
}

async function writeSpreadsheetReport(filePath: string, task: DispatchTask, response: ArtifactSource) {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = 'Elyan';
  workbook.created = new Date('2000-01-01T00:00:00.000Z');
  workbook.modified = new Date('2000-01-01T00:00:00.000Z');

  const summarySheet = workbook.addWorksheet('Summary');
  summarySheet.columns = [
    { header: 'Field', key: 'field', width: 24 },
    { header: 'Value', key: 'value', width: 120 },
  ];
  summarySheet.addRows([
    { field: 'Task ID', value: task.id },
    { field: 'Title', value: task.title },
    { field: 'Status', value: task.status },
    { field: 'Progress', value: task.progress },
    { field: 'Objective', value: task.objective },
    { field: 'Model', value: response.modelId },
    { field: 'Provider', value: response.modelProvider ?? 'unknown' },
    { field: 'Intent', value: response.classification.intent },
    { field: 'Routing', value: response.plan.routingMode },
    { field: 'Reasoning depth', value: response.plan.reasoningDepth },
    { field: 'Result', value: response.text.slice(0, 10_000) },
  ]);

  const sourcesSheet = workbook.addWorksheet('Sources');
  sourcesSheet.columns = [
    { header: 'Title', key: 'title', width: 40 },
    { header: 'URL', key: 'url', width: 80 },
  ];
  sourcesSheet.addRows(response.sources.map((source) => ({ title: source.title, url: source.url })));

  await workbook.xlsx.writeFile(filePath);
}

async function writeCodeArtifact(filePath: string, response: ArtifactSource, operatorRun?: OperatorRun | null) {
  const content = [
    `// Elyan task artifact for ${response.modelId}`,
    `// Generated: ${nowIso()}`,
    '',
    response.text,
    '',
    operatorRun?.artifacts.length
      ? '// Operator artifacts were persisted separately; this file captures the execution result.'
      : '// No operator artifacts were returned for this task.',
  ].join('\n');

  await writeFile(filePath, `${content}\n`, 'utf8');
}

function buildWorkspaceArtifact(task: DispatchTask, title: string, kind: DispatchArtifactKind, filePath: string, content: Buffer | string, metadata?: Record<string, unknown>): DispatchTaskArtifact {
  const buffer = Buffer.isBuffer(content) ? content : Buffer.from(content, 'utf8');
  const checksum = checksumBytes(buffer);
  const generatedAt = nowIso();
  const workspaceRoot = inferTaskWorkspaceRoot(task.id, filePath);
  return {
    id: `artifact_${kind}_${sanitizeBaseName(title).slice(0, 24) || 'artifact'}`,
    kind,
    title,
    filePath,
    mimeType: taskArtifactMimeType(kind),
    sizeBytes: buffer.byteLength,
    createdAt: generatedAt,
    metadata: {
      ...(metadata ?? {}),
      checksum,
      checksumAlgorithm: 'sha256',
      origin: 'storage/tasks',
      source: metadata?.['source'] ?? 'dispatch-runtime',
      sourceCapability: metadata?.['sourceCapability'] ?? 'dispatch-runtime',
      taskOrigin: task.source,
      taskId: task.id,
      timestamp: generatedAt,
      generatedAt,
      workspaceRoot,
      relativePath: path.relative(workspaceRoot, filePath),
      reproducibility: {
        taskId: task.id,
        source: task.source,
        requestedArtifacts: task.requestedArtifacts,
      },
    },
  };
}

async function verifyArtifactIntegrity(filePath: string, expectedChecksum: string) {
  const actual = checksumBytes(await readFile(filePath));
  if (actual !== expectedChecksum) {
    throw new Error(`Artifact integrity check failed for ${filePath}`);
  }
}

export async function cleanupTaskWorkspaceArtifacts(taskId: string) {
  const runtimePaths = resolveTaskWorkspacePaths(taskId);
  // Terminal cleanup removes the full workspace so canceled or recovered tasks do not leave residual state behind.
  await rm(runtimePaths.root, { force: true, recursive: true });
}

export async function persistTaskWorkspaceArtifacts(input: {
  task: DispatchTask;
  response: ArtifactSource;
  operatorRun?: OperatorRun | null;
  requestedArtifacts?: DispatchTask['requestedArtifacts'];
}) {
  const runtimePaths = resolveTaskWorkspacePaths(input.task.id);
  await ensureTaskWorkspace(runtimePaths);

  const artifacts: DispatchTaskArtifact[] = [];
  const summaryPath = path.join(runtimePaths.artifactsDir, 'summary.md');
  assertArtifactPathInsideWorkspace(summaryPath, runtimePaths.root);
  const summary = summaryLines(input.task, input.response, input.operatorRun);
  const summaryContent = `${summary.join('\n')}\n`;
  await writeFile(summaryPath, summaryContent, 'utf8');
  const summaryChecksum = checksumBytes(Buffer.from(summaryContent, 'utf8'));
  await verifyArtifactIntegrity(summaryPath, summaryChecksum);
  artifacts.push(
    buildWorkspaceArtifact(
      input.task,
      'Task summary',
      'markdown',
      summaryPath,
      summaryContent,
      {
        source: 'dispatch-runtime',
        sourceCapability: 'task_summary',
      }
    )
  );

  const manifestPath = runtimePaths.manifestPath;
  const manifest = {
    task: {
      id: input.task.id,
      title: input.task.title,
      status: input.task.status,
      progress: input.task.progress,
      objective: input.task.objective,
      mode: input.task.mode,
      source: input.task.source,
      accountId: input.task.accountId,
      spaceId: input.task.spaceId,
      runId: input.task.runId,
      modelId: input.task.modelId,
      modelProvider: input.task.modelProvider,
    },
    response: {
      text: input.response.text,
      sources: input.response.sources,
      runId: input.response.runId,
      modelId: input.response.modelId,
      modelProvider: input.response.modelProvider,
      classification: input.response.classification,
      plan: input.response.plan,
    },
    operatorRun: input.operatorRun
      ? {
          id: input.operatorRun.id,
          mode: input.operatorRun.mode,
          status: input.operatorRun.status,
          verification: input.operatorRun.verification,
          artifacts: input.operatorRun.artifacts.map((artifact) => ({
            id: artifact.id,
            kind: artifact.kind,
            title: artifact.title,
            createdAt: artifact.createdAt,
            metadata: artifact.metadata,
          })),
        }
      : null,
    requestedArtifacts: input.requestedArtifacts ?? input.task.requestedArtifacts,
  };
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  artifacts.push(
    buildWorkspaceArtifact(
      input.task,
      'Task manifest',
      'markdown',
      manifestPath,
      JSON.stringify(manifest, null, 2),
      {
        source: 'dispatch-runtime',
      }
    )
  );

  const observabilityTrace =
    input.response.observabilityTrace ??
    (input.operatorRun?.artifacts ?? [])
      .map((artifact) => artifact.metadata?.observabilityTrace)
      .find((candidate): candidate is RunTraceReport => Boolean(candidate && typeof candidate === 'object')) ??
    undefined;

  if (observabilityTrace) {
    const observabilityTraceContent = `${JSON.stringify(observabilityTrace, null, 2)}\n`;
    await writeFile(runtimePaths.observabilityTracePath, observabilityTraceContent, 'utf8');
    await verifyArtifactIntegrity(
      runtimePaths.observabilityTracePath,
      checksumBytes(Buffer.from(observabilityTraceContent, 'utf8'))
    );
    artifacts.push(
      buildWorkspaceArtifact(
        input.task,
        'Observability trace',
        'markdown',
        runtimePaths.observabilityTracePath,
        observabilityTraceContent,
        {
          source: 'run-trace',
          sourceCapability: 'observability_trace',
        }
      )
    );
  }

  const requested = new Set((input.requestedArtifacts ?? input.task.requestedArtifacts ?? []).filter((item): item is DispatchArtifactKind => requestedArtifactSchema.safeParse(item).success));

  if (requested.has('pdf')) {
    const pdfPath = path.join(runtimePaths.artifactsDir, 'summary.pdf');
    assertArtifactPathInsideWorkspace(pdfPath, runtimePaths.root);
    await writePdfReport(pdfPath, input.task.title, summary);
    await verifyArtifactIntegrity(pdfPath, checksumBytes(await readFile(pdfPath)));
    artifacts.push(
      buildWorkspaceArtifact(input.task, 'Task summary PDF', 'pdf', pdfPath, await readFile(pdfPath), {
        source: 'dispatch-runtime',
        sourceCapability: 'pdf_summary',
      })
    );
  }

  if (requested.has('pptx')) {
    const pptxPath = path.join(runtimePaths.artifactsDir, 'summary.pptx');
    assertArtifactPathInsideWorkspace(pptxPath, runtimePaths.root);
    await writePptxReport(pptxPath, input.task.title, summary);
    await verifyArtifactIntegrity(pptxPath, checksumBytes(await readFile(pptxPath)));
    artifacts.push(
      buildWorkspaceArtifact(
        input.task,
        'Task summary deck',
        'pptx',
        pptxPath,
        await readFile(pptxPath),
        { source: 'dispatch-runtime', sourceCapability: 'pptx_summary' }
      )
    );
  }

  if (requested.has('spreadsheet')) {
    const xlsxPath = path.join(runtimePaths.artifactsDir, 'summary.xlsx');
    assertArtifactPathInsideWorkspace(xlsxPath, runtimePaths.root);
    await writeSpreadsheetReport(xlsxPath, input.task, input.response);
    await verifyArtifactIntegrity(xlsxPath, checksumBytes(await readFile(xlsxPath)));
    artifacts.push(
      buildWorkspaceArtifact(
        input.task,
        'Task summary workbook',
        'spreadsheet',
        xlsxPath,
        await readFile(xlsxPath),
        { source: 'dispatch-runtime', sourceCapability: 'spreadsheet_summary' }
      )
    );
  }

  if (requested.has('code_file')) {
    const codePath = path.join(runtimePaths.artifactsDir, 'result.txt');
    assertArtifactPathInsideWorkspace(codePath, runtimePaths.root);
    await writeCodeArtifact(codePath, input.response, input.operatorRun);
    await verifyArtifactIntegrity(codePath, checksumBytes(await readFile(codePath)));
    artifacts.push(
      buildWorkspaceArtifact(
        input.task,
        'Execution result',
        'code_file',
        codePath,
        await readFile(codePath),
        { source: 'dispatch-runtime', sourceCapability: 'code_result' }
      )
    );
  }

  return {
    artifacts,
    workspace: runtimePaths,
    manifestPath,
    observabilityTrace,
  };
}
