import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
const D = process.argv[2];
const SRC = path.resolve("src");
const merged = {};
for (let i = 1; i <= 4; i++) Object.assign(merged, JSON.parse(fs.readFileSync(path.join(D, `out${i}.json`), "utf8")));
// 코드 안 t("…") 의 첫 인자를 전부 모은다.
const used = new Set();
const walk = (dir) => { for (const e of fs.readdirSync(dir, { withFileTypes: true })) { const f = path.join(dir, e.name);
  if (e.isDirectory()) walk(f); else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\./.test(e.name)) {
    const sf = ts.createSourceFile(f, fs.readFileSync(f, "utf8"), ts.ScriptTarget.Latest, true, f.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const v = (n) => { if (ts.isCallExpression(n) && n.expression.getText(sf) === "t" && n.arguments[0] && ts.isStringLiteral(n.arguments[0])) used.add(n.arguments[0].text); ts.forEachChild(n, v); };
    v(sf); } } };
walk(SRC);
const missing = [...used].filter((k) => !(k in merged));
const unused = Object.keys(merged).filter((k) => !used.has(k));
const sameAsKo = Object.entries(merged).filter(([k, v]) => /[\uAC00-\uD7A3]/.test(v));
console.log(`사전 ${Object.keys(merged).length} · 코드 열쇠 ${used.size} · 사전에 없음 ${missing.length} · 안 쓰이는 사전 ${unused.length} · 번역에 한글 남음 ${sameAsKo.length}`);
fs.writeFileSync(path.join(D, "missing.json"), JSON.stringify(missing, null, 1));
fs.writeFileSync(path.join(D, "merged.json"), JSON.stringify(merged, null, 1));
for (const [k, v] of sameAsKo.slice(0, 8)) console.log("  한글 남음:", JSON.stringify(k).slice(0, 60), "→", JSON.stringify(v).slice(0, 60));
