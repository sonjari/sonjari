// 1차 필터 — 사람이 읽는 한글 문장만 t("…") 로 감싼다 (2026-10-02 영어판 1단계).
//
// 비교·찾기·이름표·타입처럼 **글자가 곧 동작**인 자리는 감싸지 않고 검토 목록(i18n-skipped.json)으로 뺀다.
// 거기를 감싸면 영어 화면에서 「=== "완료"」가 영영 거짓이 된다. 남은 것은 시험을 돌리며 손으로 잡는다.
//
// node scripts/i18n-wrap.mjs --dry   → 바꾸지 않고 개수만
// node scripts/i18n-wrap.mjs         → 파일을 고치고 i18n-keys.json · i18n-skipped.json 을 쓴다
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "..", "src");
const HANGUL = /[가-힣]/;
const DRY = process.argv.includes("--dry");

const SKIP_FILES = /(^|[\\/])fixtures[\\/]|fixtureSetupApi\.ts$|[\\/]i18n\.ts$/;
// 이 이름의 메서드·함수에 넘긴 글자는 찾기·비교·저장 열쇠다.
const SKIP_CALLS = new Set([
  "includes", "startsWith", "endsWith", "indexOf", "lastIndexOf", "test", "match", "matchAll", "replace", "replaceAll",
  "split", "search", "RegExp", "querySelector", "querySelectorAll", "closest", "getAttribute", "setAttribute",
  "getItem", "setItem", "removeItem", "has", "get", "delete", "fetch", "invoke", "emit", "listen", "postMessage",
  "addEventListener", "removeEventListener", "getByText", "getByRole", "queryByText", "findByText", "t",
]);
// 이 이름의 속성 값은 이름표다(화면 글이 아니다).
const SKIP_KEYS = new Set([
  "id", "key", "kind", "type", "code", "status", "mode", "value", "tool", "action", "className", "icon", "tone",
  "variant", "href", "url", "path", "pattern", "match", "regex", "re", "name", "role", "testid", "source", "intent",
  "event", "stage", "phase", "state", "reason", "slug", "lang", "locale",
]);
const SKIP_JSX_ATTRS = new Set([
  "className", "key", "id", "role", "type", "name", "href", "src", "value", "htmlFor", "data-testid", "mode", "kind",
  "variant", "tone", "icon", "style", "target", "rel", "autoComplete", "inputMode", "lang",
]);
const SKIP_VAR = /(?:_RE|RE|PATTERN|PATTERNS|WORDS|KEYWORDS|MARKERS|TERMS|MATCH|MATCHERS|HINTS?_WORDS)$/;

function calleeName(expr) {
  if (ts.isIdentifier(expr)) return expr.text;
  if (ts.isPropertyAccessExpression(expr)) return expr.name.text;
  return "";
}

function looksLikeRegex(text) {
  return /\\[dswbDSWB]|\(\?[:=!<]|\[\^|\$\)|\^\(/.test(text);
}

/** 감싸면 안 되는 자리면 그 이유, 괜찮으면 "". */
function skipReason(node) {
  const text = ts.isJsxText(node) ? node.getText() : node.text ?? node.getText();
  if (looksLikeRegex(text)) return "regex_like";
  let child = node;
  let parent = node.parent;
  // 괄호·as·! 를 걷어 낸 실제 부모.
  while (parent && (ts.isParenthesizedExpression(parent) || ts.isAsExpression(parent) || ts.isNonNullExpression(parent) || ts.isSatisfiesExpression?.(parent))) {
    child = parent;
    parent = parent.parent;
  }
  if (!parent) return "";
  if (ts.isLiteralTypeNode(parent)) return "type";
  if (ts.isBinaryExpression(parent)) {
    const op = parent.operatorToken.kind;
    if ([ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken, ts.SyntaxKind.EqualsEqualsToken,
         ts.SyntaxKind.ExclamationEqualsToken, ts.SyntaxKind.InKeyword].includes(op)) return "compare";
  }
  if (ts.isCaseClause(parent)) return "case";
  if (ts.isElementAccessExpression(parent) && parent.argumentExpression === child) return "element_key";
  if ((ts.isCallExpression(parent) || ts.isNewExpression(parent)) && parent.expression !== child) {
    const name = calleeName(parent.expression);
    if (SKIP_CALLS.has(name)) return `call:${name}`;
  }
  if (ts.isPropertyAssignment(parent)) {
    if (parent.name === child) return "prop_name";
    const key = parent.name.getText().replace(/^["']|["']$/g, "");
    if (SKIP_KEYS.has(key)) return `prop:${key}`;
  }
  if (ts.isJsxAttribute(parent)) {
    const attr = parent.name.getText();
    if (SKIP_JSX_ATTRS.has(attr) || attr.startsWith("data-")) return `attr:${attr}`;
  }
  // 위로 올라가며: 타입 안 · new Set/Map · 이름이 찾기용인 변수.
  for (let up = parent; up; up = up.parent) {
    if (ts.isTypeNode(up) && !ts.isTypeLiteralNode(up)) return "type";
    if (ts.isNewExpression(up) && ["Set", "Map", "RegExp"].includes(calleeName(up.expression))) return "set_or_map";
    if (ts.isVariableDeclaration(up) && ts.isIdentifier(up.name) && SKIP_VAR.test(up.name.text)) return `var:${up.name.text}`;
    if (ts.isFunctionLike(up) || ts.isSourceFile(up)) break;
  }
  return "";
}

function templateCall(node, sf) {
  let key = node.head.text;
  const args = [];
  node.templateSpans.forEach((span, index) => {
    key += `{${index}}` + span.literal.text;
    args.push(span.expression.getText(sf));
  });
  return { key, code: `t(${JSON.stringify(key)}, ${args.join(", ")})` };
}

function files(dir = SRC) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...files(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.|\.d\.ts$/.test(entry.name)) out.push(full);
  }
  return out;
}

const keys = new Map();
const skipped = [];
let wrapped = 0;
let touchedFiles = 0;

for (const file of files()) {
  const rel = path.relative(SRC, file).replace(/\\/g, "/");
  if (SKIP_FILES.test(file)) continue;
  const text = fs.readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const edits = [];
  const visit = (node) => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return;
    const isLiteral = ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node);
    const isTemplate = ts.isTemplateExpression(node);
    const isJsx = ts.isJsxText(node);
    if ((isLiteral || isTemplate || isJsx) && HANGUL.test(node.getText(sf))) {
      const reason = skipReason(node);
      const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
      if (reason) {
        skipped.push({ file: rel, line, reason, text: node.getText(sf).slice(0, 160) });
        if (!isTemplate) return;
      } else if (isJsx) {
        const raw = node.getText(sf);
        const trimmed = raw.trim();
        const key = trimmed.replace(/\s+/g, " ");
        const at = raw.indexOf(trimmed);
        edits.push({ start: node.getStart(sf) + at, end: node.getStart(sf) + at + trimmed.length, code: `{t(${JSON.stringify(key)})}` });
        keys.set(key, (keys.get(key) || 0) + 1);
        return;
      } else if (isLiteral) {
        const key = node.text;
        const call = `t(${JSON.stringify(key)})`;
        const inJsxAttr = ts.isJsxAttribute(node.parent);
        edits.push({ start: node.getStart(sf), end: node.getEnd(), code: inJsxAttr ? `{${call}}` : call });
        keys.set(key, (keys.get(key) || 0) + 1);
        return;
      } else {
        const { key, code } = templateCall(node, sf);
        edits.push({ start: node.getStart(sf), end: node.getEnd(), code });
        keys.set(key, (keys.get(key) || 0) + 1);
        return; // 안쪽 ${} 의 한글은 다음 판에서 다시 훑는다(겹친 고치기를 피한다)
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  if (!edits.length) continue;
  wrapped += edits.length;
  touchedFiles += 1;
  if (DRY) continue;
  let out = text;
  for (const edit of edits.sort((a, b) => b.start - a.start)) out = out.slice(0, edit.start) + edit.code + out.slice(edit.end);
  if (!/^import \{[^}]*\bt\b[^}]*\} from "[^"]*i18n";/m.test(out)) {
    const relImport = path.relative(path.dirname(file), path.join(SRC, "i18n")).replace(/\\/g, "/");
    const spec = relImport.startsWith(".") ? relImport : `./${relImport}`;
    // 맨 위 지시문(주석·"use …") 다음, 첫 import 앞에 넣는다.
    const firstImport = out.search(/^import /m);
    const line = `import { t } from "${spec}";\n`;
    out = firstImport >= 0 ? out.slice(0, firstImport) + line + out.slice(firstImport) : line + out;
  }
  fs.writeFileSync(file, out, "utf8");
}

const byReason = {};
for (const row of skipped) byReason[row.reason.split(":")[0]] = (byReason[row.reason.split(":")[0]] || 0) + 1;
console.log(`감쌈 ${wrapped}곳 · 파일 ${touchedFiles}개 · 고유 문장 ${keys.size}개 · 검토 목록 ${skipped.length}곳`, byReason);
if (!DRY) {
  fs.writeFileSync(path.join(HERE, "i18n-keys.json"), JSON.stringify([...keys.keys()].sort(), null, 1), "utf8");
  fs.writeFileSync(path.join(HERE, "i18n-skipped.json"), JSON.stringify(skipped, null, 1), "utf8");
}
