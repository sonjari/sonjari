/**
 * 화면의 자. 재설계 각 단계 전후로 같은 것을 잰다.
 *
 *   node scripts/measure_ui.mjs
 *
 * ★ 눈금을 고칠 때는 분모를 먼저 본다.
 *   초판은 `workspace.css` 만 세고 있었다(제품 CSS 는 둘이다).
 *   2판은 px 리터럴을 세다가, P2 에서 전부 토큰이 되자 **0 을 성공으로 착각**했다.
 *   그래서 지금은 "리터럴 + 토큰"을 같이 세고, 값의 단계 수는 토큰 정의에서 읽는다.
 *   새 CSS 파일을 만들면 FILES 에 넣어라. 안 넣으면 그 파일은 조용히 안 세어진다.
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const PRODUCT = ["workspace.css", "styles.css"];
const TOKENS = "tokens.css";
/** 제품 화면이 아닌 것. 리허설 조종대는 토큰을 따르지 않는다(그게 의도다). */
const EXCLUDED = ["fixtures/fixtures.css"];

const COLOR = /#[0-9a-fA-F]{3,8}\b|rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*(?:,\s*[\d.]+\s*)?\)/g;
const read = (n) => (existsSync(join(SRC, n)) ? readFileSync(join(SRC, n), "utf8") : "");
const strip = (css) => css.replace(/\/\*[\s\S]*?\*\//g, "");
const count = (s, re) => (s.match(re) ?? []).length;

const body = strip(PRODUCT.map(read).join("\n"));
const tokens = strip(read(TOKENS));
const defs = (prefix) => [...tokens.matchAll(new RegExp(`(${prefix}[a-z0-9-]*)\\s*:`, "g"))].map((m) => m[1]);

// ── 색 ────────────────────────────────────────────────────────────────────
const colorLiterals = count(body, COLOR);
const colorTokenUses = count(body, /rgb\(var\(--/g);
/**
 * ★ **재료 토큰**을 화면 코드가 직접 쓰는 횟수 (P9, 목표 0).
 *
 * P1 이 하드코딩을 없앤 자리에 `--c-ink-47` 같은 **재료 이름**을 두었다. 이름이 뜻을
 * 말하지 않으니 다음 사람은 눈대중으로 고르고, 밝기 1.5% 차이 나는 회색 셋이 한
 * 화면에서 서로 다른 뜻인 척하게 된다. P9 에서 557곳을 역할 이름으로 옮겼다.
 * 이 줄이 0 이 아니면 되돌아가고 있는 것이다.
 */
const materialTokenUses = count(body, /var\(--c-/g);

// ── 치수: 리터럴이 남았는지 + 단계가 몇 개인지 ─────────────────────────────
const dim = (prop, prefix) => ({
  literals: [...body.matchAll(new RegExp(`${prop}:\\s*([\\d.]+)px`, "g"))].map((m) => Number(m[1])),
  uses: count(body, new RegExp(`${prop}:\\s*var\\(${prefix}`, "g")),
  steps: defs(prefix).length,
});
const size = dim("font-size", "--fs-");
const radius = dim("border-radius", "--r-");
const weightLiterals = [...body.matchAll(/font-weight:\s*(\d+)/g)].map((m) => Number(m[1]));
const weight = { literals: weightLiterals, uses: count(body, /font-weight:\s*var\(--fw-/g), steps: defs("--fw-").length };
const tiny = size.literals.filter((v) => v < 11);

// ── 품질 바닥 ─────────────────────────────────────────────────────────────
const has = (needle) => PRODUCT.filter((f) => read(f).includes(needle)).length;

// ── 대비 ──────────────────────────────────────────────────────────────────
const lum = (r, g, b) => {
  const f = (u) => ((u /= 255) <= 0.03928 ? u / 12.92 : ((u + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const ratio = (a, b) => { const [x, y] = [lum(...a), lum(...b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const channel = Object.fromEntries(
  [...tokens.matchAll(/(--[a-z0-9-]+):\s*(\d+) (\d+) (\d+);/g)].map((m) => [m[1], [+m[2], +m[3], +m[4]]]),
);
/**
 * 대비를 재는 바닥. **토큰에서 읽는다.**
 *
 * ★ 여기 값을 손으로 박아 두면 바닥색을 바꾸는 날 이 자가 조용히 **옛 바닥**을
 *   재게 된다 — 눈금이 틀리는 네 번째 모양이다. 2026-08-19 저녁에 실제로 그럴
 *   뻔했다(#090a0c → #0b0c12). 화면이 쓰는 값과 자가 쓰는 값은 한 곳에서 나와야 한다.
 */
// P9 부터 역할 토큰이 채널을 **직접** 갖는다(별칭 한 겹이 사라졌다).
// 못 찾으면 옛 바닥으로 재는 대신 **터진다** — 조용히 틀린 바닥으로 재느니 낫다.
const BG = channel["--surface-2"];
if (!BG) throw new Error("tokens.css 에서 --surface-2 를 못 읽었다. 이 자는 화면과 같은 값으로만 잰다.");
const over = (c, a) => c.map((v, i) => Math.round(v * a + BG[i] * (1 - a)));
/** 글자색으로 쓰인 모든 선언. 크기가 적혀 있든 없든(상속) 전부 본다. */
/**
 * 글자색은 **바닥 위에서** 재야 한다. 이 자는 바닥을 하나(`--surface-2`)로 가정하는데,
 * 강조색 단추 위의 글자처럼 바닥이 다른 것도 있다. 그런 선언에는 CSS 에
 * `/* on-accent *\/` 를 적어 둔다.
 *
 * ★ **빼지 않고 따로 센다.** 조용히 제외하면 그 자리는 영영 아무도 안 본다 —
 *   눈금이 틀리는 다섯 번째 모양이 정확히 그것이다(분모에서 소리 없이 빠지기).
 */
// ★ 표시는 **주석 안에** 있으므로 지우지 않은 원문에서 찾는다. `strip()` 을 먼저
//   돌리면 표시까지 같이 지워져서 아무것도 안 잡힌다(2026-08-19 실측: 0건).
//   대신 주석 안에 있는 예시 선언을 세지 않도록 주석 구간을 계산해 걸러 낸다.
const raw = PRODUCT.map(read).join(String.fromCharCode(10));  // 줄바꿈 이스케이프 없이
const commentRanges = [...raw.matchAll(/\/\*[\s\S]*?\*\//g)].map((m) => [m.index, m.index + m[0].length]);
const insideComment = (at) => commentRanges.some(([from, to]) => at >= from && at < to);
const textColors = [...raw.matchAll(/(?:^|[;{\s])color:\s*rgb\(var\((--[a-z0-9-]+)\)(?:\s*\/\s*([\d.]+))?\)(;?[ 	]*\/\* on-accent \*\/)?/g)]
  .filter((m) => !insideComment(m.index))
  .map((m) => ({ token: m[1], alpha: m[2] ? Number(m[2]) : 1, onAccent: Boolean(m[3]) }))
  .filter((r) => channel[r.token])
  .map((r) => ({ ...r, cr: ratio(over(channel[r.token], r.alpha), BG) }));
const onAccent = textColors.filter((r) => r.onAccent);
const failing = textColors.filter((r) => !r.onAccent && r.cr < 4.5);

const uniq = (l) => new Set(l).size;
const rows = [
  ["색 — 하드코딩 리터럴", colorLiterals, "목표 0"],
  ["색 — 토큰 경유", colorTokenUses, ""],
  ["색 — 재료 토큰 직접 사용", materialTokenUses, "목표 0 (P9)"],
  ["색 토큰: 재료 / 역할", `${defs("--c-").length} / ${defs("--").length - defs("--c-").length}`, ""],
  ["", "", ""],
  ["font-size — px 리터럴", size.literals.length, "목표 0"],
  ["  그중 11px 미만", tiny.length, "목표 0"],
  ["font-size — 토큰 사용", size.uses, ""],
  ["font-size — 단계 수", size.steps, "목표 6 이하"],
  ["font-weight — px 리터럴", weight.literals.length, "목표 0"],
  ["font-weight — 단계 수", weight.steps, "목표 3"],
  ["border-radius — px 리터럴", radius.literals.length, "목표 0"],
  ["border-radius — 단계 수", radius.steps, "목표 5 — r-0 은 눈금·밑줄용"],
  ["", "", ""],
  ["focus-visible 쓰는 파일", has(":focus-visible"), `/ ${PRODUCT.length}`],
  ["reduced-motion 쓰는 파일", has("prefers-reduced-motion"), `/ ${PRODUCT.length}`],
  ["글자색 대비 4.5 미달", failing.length, "목표 0"],
  ["  바닥이 다른 글자색", onAccent.length, "손으로 확인함 (on-accent)"],
];

console.log("\n  자비스 화면 눈금 —", new Date().toISOString().slice(0, 10));
console.log("  " + "─".repeat(58));
for (const [label, value, note] of rows) {
  if (!label) { console.log(""); continue; }
  console.log(`  ${label.padEnd(28)} ${String(value).padStart(8)}  ${note}`);
}
if (size.literals.length) console.log(`\n  남은 크기 리터럴: ${[...new Set(size.literals)].sort((a, b) => a - b).join(", ")}px`);
if (failing.length) {
  console.log("\n  대비 미달 글자색:");
  for (const r of failing.slice(0, 12)) console.log(`    ${r.cr.toFixed(2).padStart(5)}  ${r.token}${r.alpha < 1 ? ` (알파 ${r.alpha})` : ""}`);
}
console.log(`\n  (대비 기준 바닥: rgb(${BG.join(" ")}) — tokens.css 의 --surface-2 에서 읽었다)`);
console.log(`  (분모에서 뺀 것: ${EXCLUDED.join(", ")} — 제품 화면이 아니다)\n`);
