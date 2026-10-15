// t("…{0}", 인자) 의 **인자 안에** 든 한글 문장을 감싼다 (2026-10-03 영어판 디자인 점검).
// 1차 필터(i18n-wrap.mjs)는 t() 안의 글자를 「이미 감싼 것」으로 보고 건너뛰어,
// t("Ollama {0} 가 돌고 있습니다{1}.", v, managed ? " — Sonjari가 켰습니다" : " — 그대로 씁니다") 의 뒤쪽이 영어 화면에 남았다.
//   node scripts/i18n-wrap-args.mjs --dry | (없으면 고친다)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "src");
const HANGUL = /[가-힣]/;
const DRY = process.argv.includes("--dry");
const found = [];

const walk = (dir) => {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) { if (entry.name !== "fixtures") walk(full); continue; }
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\.|\.d\.ts$|fixtureSetupApi/.test(entry.name)) continue;
    const text = fs.readFileSync(full, "utf8");
    const sf = ts.createSourceFile(full, text, ts.ScriptTarget.Latest, true, full.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const edits = [];
    const visit = (node) => {
      if (ts.isCallExpression(node) && node.expression.getText(sf) === "t") {
        node.arguments.slice(1).forEach((arg) => {
          const inner = (n) => {
            if ((ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) && HANGUL.test(n.text)) {
              edits.push({ start: n.getStart(sf), end: n.getEnd(), code: `t(${JSON.stringify(n.text)})`, key: n.text });
              return;
            }
            if (ts.isCallExpression(n) && n.expression.getText(sf) === "t") return;
            ts.forEachChild(n, inner);
          };
          inner(arg);
        });
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
    if (!edits.length) continue;
    for (const e of edits) found.push({ file: path.relative(SRC, full), key: e.key });
    if (DRY) continue;
    let out = text;
    for (const e of edits.sort((a, b) => b.start - a.start)) out = out.slice(0, e.start) + e.code + out.slice(e.end);
    fs.writeFileSync(full, out, "utf8");
  }
};
walk(SRC);
console.log(JSON.stringify(found, null, 1));
