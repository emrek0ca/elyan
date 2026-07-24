export type TableExportData = {
  title?: string;
  columns: string[];
  rows: string[][];
};

export type DocumentSection = {
  heading?: string;
  content: string;
  level?: number;
};

export type DocumentExportData = {
  title: string;
  summary?: string;
  sections: DocumentSection[];
};

function slug(value: string): string {
  return (value || 'elyan-output')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .slice(0, 80) || 'elyan-output';
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvCell(value: string): string {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

export function tableToCsv(table: TableExportData): string {
  return [table.columns, ...table.rows].map((row) => row.map(csvCell).join(',')).join('\n');
}

export function documentToMarkdown(document: DocumentExportData): string {
  const lines = [`# ${document.title}`];
  if (document.summary) lines.push('', document.summary);
  for (const section of document.sections) {
    const level = Math.min(3, Math.max(2, Number(section.level) || 2));
    if (section.heading) lines.push('', `${'#'.repeat(level)} ${section.heading}`);
    if (section.content) lines.push('', section.content);
  }
  return `${lines.join('\n').trim()}\n`;
}

export function exportTableCsv(table: TableExportData): void {
  downloadBlob(new Blob([tableToCsv(table)], { type: 'text/csv;charset=utf-8' }), `${slug(table.title || 'table')}.csv`);
}

export async function exportTableXlsx(table: TableExportData): Promise<void> {
  const { default: writeXlsxFile } = await import('write-excel-file/browser');
  const rows = [
    table.columns.map((value) => ({ value, fontWeight: 'bold', backgroundColor: '#F2EFE8' })),
    ...table.rows.map((row) => row.map((value) => ({ value }))),
  ];
  await writeXlsxFile(rows, { sheet: 'Elyan' }).toFile(`${slug(table.title || 'table')}.xlsx`);
}

export async function exportTablePdf(table: TableExportData): Promise<void> {
  const [{ jsPDF }, autoTableModule] = await Promise.all([import('jspdf'), import('jspdf-autotable')]);
  const autoTable = autoTableModule.default;
  const doc = new jsPDF({ orientation: table.columns.length > 5 ? 'landscape' : 'portrait', unit: 'pt', format: 'a4' });
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(14);
  doc.text(table.title || 'Elyan table', 40, 44);
  autoTable(doc, {
    head: [table.columns],
    body: table.rows,
    startY: 64,
    styles: { font: 'helvetica', fontSize: 8, cellPadding: 6, lineColor: [230, 226, 216], lineWidth: 0.4 },
    headStyles: { fillColor: [111, 143, 112], textColor: 255, fontStyle: 'bold' },
    alternateRowStyles: { fillColor: [250, 248, 243] },
  });
  doc.save(`${slug(table.title || 'table')}.pdf`);
}

export function exportDocumentMarkdown(document: DocumentExportData): void {
  downloadBlob(new Blob([documentToMarkdown(document)], { type: 'text/markdown;charset=utf-8' }), `${slug(document.title)}.md`);
}

export async function exportDocumentDocx(documentData: DocumentExportData): Promise<void> {
  const { Document, HeadingLevel, Packer, Paragraph, TextRun } = await import('docx');
  const doc = new Document({
    sections: [{
      properties: {},
      children: [
        new Paragraph({ text: documentData.title, heading: HeadingLevel.TITLE }),
        ...(documentData.summary ? [new Paragraph({ children: [new TextRun(documentData.summary)], spacing: { after: 240 } })] : []),
        ...documentData.sections.flatMap((section) => [
          ...(section.heading ? [new Paragraph({ text: section.heading, heading: Number(section.level) <= 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3 })] : []),
          ...section.content.split(/\n{2,}/).map((part) => new Paragraph({ children: [new TextRun(part.replace(/\s+/g, ' ').trim())] })),
        ]),
      ],
    }],
  });
  const blob = await Packer.toBlob(doc);
  downloadBlob(blob, `${slug(documentData.title)}.docx`);
}

export async function exportDocumentPdf(documentData: DocumentExportData): Promise<void> {
  const { jsPDF } = await import('jspdf');
  const doc = new jsPDF({ unit: 'pt', format: 'a4' });
  const margin = 48;
  const width = doc.internal.pageSize.getWidth() - margin * 2;
  let y = margin;
  const addText = (value: string, size: number, bold = false) => {
    doc.setFont('helvetica', bold ? 'bold' : 'normal');
    doc.setFontSize(size);
    const lines = doc.splitTextToSize(value, width);
    for (const line of lines) {
      if (y > 780) { doc.addPage(); y = margin; }
      doc.text(line, margin, y);
      y += size + 5;
    }
    y += 6;
  };
  addText(documentData.title, 18, true);
  if (documentData.summary) addText(documentData.summary, 10);
  for (const section of documentData.sections) {
    if (section.heading) addText(section.heading, 13, true);
    if (section.content) addText(section.content.replace(/[#*_`>-]/g, ''), 10);
  }
  doc.save(`${slug(documentData.title)}.pdf`);
}
