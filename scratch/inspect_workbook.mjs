import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = process.argv[2];
const outputDir = process.argv[3];
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const overview = await workbook.inspect({
  kind: "sheet,table",
  include: "id,name",
  maxChars: 6000,
  tableMaxRows: 5,
  tableMaxCols: 8,
});
console.log(overview.ndjson);
await fs.mkdir(outputDir, { recursive: true });
for (const sheet of workbook.worksheets.items) {
  const rendered = await workbook.render({
    sheetName: sheet.name,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  const safeName = sheet.name.replaceAll(/[\\/:*?"<>|]/g, "_");
  await fs.writeFile(`${outputDir}/${safeName}.png`, new Uint8Array(await rendered.arrayBuffer()));
}
