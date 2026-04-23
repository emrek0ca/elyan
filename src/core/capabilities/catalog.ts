import type { CapabilityDefinition } from './types';
import { csvExportCapability, csvParseCapability } from './csv';
import { docxReadCapability, docxWriteCapability } from './documents';
import { fuzzyFindCapability } from './fuzzy-find';
import { chartGenerateCapability } from './chart';
import { browserAutomationCapability, webReadDynamicCapability } from './browser';
import { imageProcessCapability } from './image';
import { mathExactCapability, decimalMathCapability } from './math';
import { pdfExtractCapability } from './pdf';
import { webCrawlCapability } from './crawl';
import { mcpBridgeCapability, toolBridgeCapability } from './bridge';

export const defaultCapabilityCatalog: CapabilityDefinition[] = [
  fuzzyFindCapability,
  mathExactCapability,
  decimalMathCapability,
  csvParseCapability,
  csvExportCapability,
  docxReadCapability,
  docxWriteCapability,
  pdfExtractCapability,
  imageProcessCapability,
  webReadDynamicCapability,
  webCrawlCapability,
  browserAutomationCapability,
  chartGenerateCapability,
  toolBridgeCapability,
  mcpBridgeCapability,
];

