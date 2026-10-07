import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const [path, previewDir, mode = 'preview'] = process.argv.slice(2);
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
await fs.mkdir(previewDir, { recursive: true });
if (mode === 'edit') {
  for (const sheet of wb.worksheets.items) {
    const rows = sheet.getUsedRange().values;
    const widths = [];
    for (let col = 0; col < rows[3].length; col++) {
      let longest = 0;
      for (const row of rows.slice(3)) {
        for (const line of String(row[col] ?? '').split('\n')) {
          longest = Math.max(longest, [...line].reduce((n, c) => n + (c.codePointAt(0) > 127 ? 2 : 1), 0));
        }
      }
      widths[col] = Math.max(15, Math.min(60, longest + 2));
      sheet.getRangeByIndexes(0, col, rows.length, 1).format.columnWidth = widths[col];
    }
    sheet.getUsedRange().format.wrapText = true;
    sheet.getUsedRange().format.verticalAlignment = 'top';
    for (let row = 3; row < rows.length; row++) {
      let lines = 1;
      for (let col = 0; col < widths.length; col++) {
        const n = String(rows[row][col] ?? '').split('\n').reduce((total, line) => total + Math.max(1, Math.ceil([...line].reduce((n, c) => n + (c.codePointAt(0) > 127 ? 2 : 1), 0) / Math.max(8, widths[col] - 3))), 0);
        lines = Math.max(lines, n);
      }
      sheet.getRangeByIndexes(row, 0, 1, widths.length).format.rowHeight = Math.min(409, Math.max(28, lines * 16 + 8));
    }
    sheet.getRange('A1').format.rowHeight = 25;
    sheet.getRange('A2').format.rowHeight = 34;
    sheet.getRangeByIndexes(3, 0, 1, widths.length).format.verticalAlignment = 'center';
  }
  await (await SpreadsheetFile.exportXlsx(wb)).save(path);
}
console.log((await wb.inspect({kind:'sheet',include:'id,name',maxChars:1500})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:5},maxChars:500})).ndjson);
for (const [index, sheet] of wb.worksheets.items.entries()) {
  const range = sheet.name.includes('资产') ? 'A4:F7' : sheet.name.includes('范围') ? 'A4:C13' : 'A4:D7';
  const blob = await wb.render({sheetName:sheet.name,range,scale:1,format:'png'});
  await fs.writeFile(`${previewDir}/${index}.png`, new Uint8Array(await blob.arrayBuffer()));
}
