// 화면 코드에서 사람이 읽는 한글 문장을 찾는다 (2026-10-02 영어판 1단계).
// node scripts/i18n-scan.mjs            → 종류별 개수와 파일별 개수
// node scripts/i18n-scan.mjs --list     → 문장 목록(JSON)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "src");
const HANGUL = /[가-힣]/;

export function sourceFiles(dir = ROOT) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.|\.d\.ts$/.test(entry.name)) out.push(full);
  }
  return out;
}

/** 한 파일의 한글 문장 위치 — kind: string(따옴표) · jsx(태그 사이 글) · template(${} 없는 백틱) · tpl_expr(${} 있는 백틱) */
export function findStrings(file) {
  const text = fs.readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const found = [];
  const visit = (node) => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return;
    let kind = "";
    if (ts.isStringLiteral(node)) kind = "string";
    else if (ts.isNoSubstitutionTemplateLiteral(node)) kind = "template";
    else if (ts.isJsxText(node)) kind = "jsx";
    else if (ts.isTemplateExpression(node)) kind = "tpl_expr";
    if (kind) {
      const raw = node.getText(sf);
      if (HANGUL.test(raw)) {
        // 이미 t("…") 로 감싼 것은 건너뛴다.
        const parent = node.parent;
        const wrapped = parent && ts.isCallExpression(parent) && parent.expression.getText(sf) === "t";
        if (!wrapped) found.push({ kind, start: node.getStart(sf), end: node.getEnd(), raw, line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1 });
      }
      if (kind !== "tpl_expr") return;
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return found;
}

if (import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/").split("/").pop())) {
  const byKind = {};
  const byFile = [];
  const list = [];
  for (const file of sourceFiles()) {
    const rows = findStrings(file);
    if (!rows.length) continue;
    byFile.push([path.relative(ROOT, file), rows.length]);
    for (const row of rows) {
      byKind[row.kind] = (byKind[row.kind] || 0) + 1;
      list.push({ file: path.relative(ROOT, file), line: row.line, kind: row.kind, raw: row.raw });
    }
  }
  if (process.argv.includes("--list")) {
    console.log(JSON.stringify(list, null, 1));
  } else {
    console.log("종류별", byKind, "합계", list.length, "· 고유 문장", new Set(list.map((r) => r.raw)).size);
    byFile.sort((a, b) => b[1] - a[1]);
    for (const [file, n] of byFile) console.log(String(n).padStart(5), file);
  }
}
