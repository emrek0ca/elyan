import type { CapabilityDefinition } from './types';
import { csvExportCapability, csvParseCapability } from './csv';
import { docxReadCapability, docxWriteCapability } from './documents';
import { fuzzyFindCapability } from './fuzzy-find';
import { chartGenerateCapability } from './chart';
import { browserAutomationCapability, webReadDynamicCapability } from './browser';
import { imageProcessCapability } from './image';
import { archiveCapability } from './archive';
import { markdownRenderCapability } from './markdown';
import { metadataCapability } from './metadata';
import { ocrCapability } from './ocr';
import { mathExactCapability, decimalMathCapability } from './math';
import { optimizationSolveCapability } from './optimization';
import { pdfExtractCapability } from './pdf';
import { pdfWorkflowCapability } from './pdf-lib';
import { searchIndexCapability } from './search-index';
import { spreadsheetReadCapability, spreadsheetWriteCapability } from './spreadsheet';
import { webCrawlCapability } from './crawl';
import { mcpBridgeCapability, toolBridgeCapability } from './bridge';

export const defaultCapabilityCatalog: CapabilityDefinition[] = [
  fuzzyFindCapability,
  mathExactCapability,
  decimalMathCapability,
  optimizationSolveCapability,
  csvParseCapability,
  csvExportCapability,
  docxReadCapability,
  docxWriteCapability,
  pdfExtractCapability,
  pdfWorkflowCapability,
  imageProcessCapability,
  spreadsheetReadCapability,
  spreadsheetWriteCapability,
  archiveCapability,
  ocrCapability,
  metadataCapability,
  markdownRenderCapability,
  searchIndexCapability,
  webReadDynamicCapability,
  webCrawlCapability,
  browserAutomationCapability,
  chartGenerateCapability,
  toolBridgeCapability,
  mcpBridgeCapability,
];
