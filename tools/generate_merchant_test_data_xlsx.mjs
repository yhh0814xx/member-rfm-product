import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error("usage: helper input.json output.xlsx");

const rows = JSON.parse(await fs.readFile(inputPath, "utf8"));
const headers = [
  "InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate",
  "UnitPrice", "CustomerID", "Country",
];
const values = rows.map((row) => [
  row.InvoiceNo,
  row.StockCode,
  row.Description,
  Number(row.Quantity),
  new Date(row.InvoiceDate.replace(" ", "T")),
  Number(row.UnitPrice),
  row.CustomerID,
  row.Country,
]);

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Transactions");
sheet.getRange("A1:H1").values = [headers];
sheet.getRangeByIndexes(1, 0, values.length, headers.length).values = values;
sheet.getRange("A1:H1").format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF" },
  rowHeight: 24,
};
sheet.getRange(`D2:D${values.length + 1}`).format.numberFormat = "0";
sheet.getRange(`E2:E${values.length + 1}`).format.numberFormat = "yyyy-mm-dd hh:mm";
sheet.getRange(`F2:F${values.length + 1}`).format.numberFormat = "0.00";
sheet.getRange(`A1:H${values.length + 1}`).format.font = { name: "Aptos", size: 10 };
sheet.getRange("A1:H1").format.font = { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" };
sheet.getRange("A:A").format.columnWidth = 16;
sheet.getRange("B:B").format.columnWidth = 12;
sheet.getRange("C:C").format.columnWidth = 31;
sheet.getRange("D:D").format.columnWidth = 11;
sheet.getRange("E:E").format.columnWidth = 20;
sheet.getRange("F:F").format.columnWidth = 12;
sheet.getRange("G:G").format.columnWidth = 14;
sheet.getRange("H:H").format.columnWidth = 18;
sheet.freezePanes.freezeRows(1);
sheet.showGridLines = false;
const table = sheet.tables.add(`A1:H${values.length + 1}`, true, "TransactionsTable");
table.style = "TableStyleMedium2";

const check = await workbook.inspect({
  kind: "table",
  range: "Transactions!A1:H8",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 8,
  maxChars: 3000,
});
process.stdout.write(check.ndjson + "\n");
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
  maxChars: 2000,
});
process.stdout.write(errors.ndjson + "\n");
const preview = await workbook.render({
  sheetName: "Transactions",
  range: "A1:H22",
  scale: 1,
  format: "png",
});
await fs.writeFile(outputPath.replace(/\.xlsx$/i, "_preview.png"), new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
