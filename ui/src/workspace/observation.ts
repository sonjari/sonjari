import { t, locale } from "../i18n";
/**
 * 걸음이 **본 것**의 판정 — 화면 없이 검사할 수 있게 여기 모은다 (P10·P11).
 *
 * 화면이 하는 일은 셋뿐이다: 어느 걸음을 고를지, 그 걸음이 어느 칸에 속하는지,
 * 그리고 **무엇이 잘렸는지 뭐라고 말할지.** 셋 다 판정이라 여기 둔다.
 *
 * ## 왜 종류로 그리나
 *
 * 도구가 102개다(2026-08-19 실측: 브라우저 30 · 구글 13 · 카메라 11 …). 도구마다
 * 화면을 만들면 새로 만든 도구는 영원히 안 보인다 — 우리는 같은 구멍으로 눈금이
 * 두 번 샜다. 그래서 백엔드가 관측에 **종류**를 붙이고(`observations.py::shape`)
 * 화면은 종류만 본다. 새 도구는 그날부터 보인다.
 *
 * ## 잘림은 반드시 말한다
 *
 * 세 군데서 잘린다 — 도구 자신 · 보관소 · 모델 대화. 잘렸는데 안 적으면 사람은
 * 「없던 내용」과 구별할 수 없다. 사고 Q 에서 본문 23%가 그렇게 사라졌고, 그건
 * 에러가 아니라 **침묵**으로 왔다.
 */

export type ObservationKind =
  | "page" | "code" | "document" | "table" | "files" | "draft" | "artifact" | "note";

export interface StepRow {
  step: number;
  tool: string;
  ok: boolean;
  status: string;
  error: string;
  kind: ObservationKind;
  title: string;
  at: number;
  took_ms: number;
  truncated: boolean;
}

export interface Truncation {
  /** 도구가 스스로 끊었다(`max_chars`). */
  tool?: boolean;
  /** 보관소가 끊었다(120,000자). */
  store?: boolean;
  /** 원문은 몇 자였나. */
  char_count?: number;
  /** 모델 대화에 실제로 실린 글자 수. */
  to_model?: number;
  /** 모델 대화 상한(30,000자)에서 잘렸나. */
  model_cut?: boolean;
}

export interface Observation extends StepRow {
  job_id: string;
  arguments: Record<string, string>;
  payload: Record<string, unknown>;
  truncation: Truncation;
}

export type TabKey = "screen" | "file" | "data" | "made";

/**
 * 칸 넷. 순서가 곧 화면 순서다.
 *
 * ★ 새 종류를 만들면 여기 넣어라. 안 넣으면 그 관측은 어느 칸에도 안 잡히고,
 *   화면에서 **조용히 사라진다.** `tabOf` 가 잡아 주지만(데이터로 떨어진다)
 *   그건 마지막 그물이지 제자리가 아니다.
 */
export const TABS: Array<{ key: TabKey; label: string; kinds: ObservationKind[] }> = [
  { key: "screen", label: t("화면"), kinds: ["page"] },
  { key: "file", label: t("파일"), kinds: ["code", "document", "files"] },
  { key: "data", label: t("데이터"), kinds: ["table", "note"] },
  { key: "made", label: t("만든 것"), kinds: ["draft", "artifact"] },
];

const KIND_TO_TAB = new Map<ObservationKind, TabKey>(
  TABS.flatMap((tab) => tab.kinds.map((kind) => [kind, tab.key] as const)),
);

/** 모르는 종류는 데이터로 보낸다 — 안 보여 주는 것보다 낫다. */
export function tabOf(kind: ObservationKind): TabKey {
  return KIND_TO_TAB.get(kind) ?? "data";
}

export const KIND_LABEL: Record<ObservationKind, string> = {
  page: t("웹 화면"),
  code: t("코드"),
  document: t("문서"),
  table: t("표"),
  files: t("목록"),
  draft: t("초안"),
  artifact: t("만든 파일"),
  note: t("결과"),
};

/** 칸마다 몇 걸음이 들어 있나. 0인 칸은 화면에서 눌리지 않는다. */
export function tabCounts(rows: StepRow[]): Record<TabKey, number> {
  const counts: Record<TabKey, number> = { screen: 0, file: 0, data: 0, made: 0 };
  for (const row of rows) counts[tabOf(row.kind)] += 1;
  return counts;
}

/** 그 칸의 **가장 최근** 걸음. 없으면 null — 사람은 대개 마지막 것을 보고 싶어 한다. */
export function latestOfTab(rows: StepRow[], tab: TabKey): number | null {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (tabOf(rows[index].kind) === tab) return rows[index].step;
  }
  return null;
}

/**
 * 자동으로 따라갈 것인가.
 *
 * 일이 도는 동안에는 **마지막 걸음**을 계속 따라간다. 하지만 사람이 걸음 하나를
 * 눌러서 보고 있는 중이라면 따라가면 안 된다 — 읽던 화면이 발밑에서 바뀌는 것이
 * 제일 나쁘다. 그래서 "사람이 골랐는가"를 기억하고, 그때는 그 자리에 머문다.
 */
export function followingStep(rows: StepRow[], pinned: number | null): number | null {
  if (pinned !== null && rows.some((row) => row.step === pinned)) return pinned;
  return rows.length ? rows[rows.length - 1].step : null;
}

/** ← → 로 옮길 다음 걸음. 끝에서는 안 움직인다(감기지 않는다). */
export function stepBeside(rows: StepRow[], current: number | null, delta: number): number | null {
  if (!rows.length) return null;
  const order = rows.map((row) => row.step);
  // 아무것도 안 골랐으면 **마지막 걸음을 보고 있는 것**이다(따라가는 중).
  const at = current === null ? order.length - 1 : order.indexOf(current);
  if (at < 0) return order[order.length - 1];
  const here = order[at];
  const next = at + delta;
  // 끝에서는 제자리다. `current` 를 그대로 돌려주면 안 된다 — 따라가는 중이었다면
  // 그건 null 이고, 그러면 눌렀는데 고른 것이 **풀려 버린다.**
  if (next < 0 || next >= order.length) return here;
  return order[next];
}

const NUMBER = new Intl.NumberFormat(locale());

/**
 * 무엇이 잘렸는지 **사람 말로**. 없으면 빈 배열.
 *
 * 자리마다 다른 문장을 쓰지 않으려고 여기 모은다. "8,000자만 갔습니다"를 화면
 * 세 곳에서 각자 적으면 언젠가 셋이 갈라지고, 갈라진 쪽이 조용히 틀린다.
 */
export function truncationNotes(item: Observation, storedChars: number): string[] {
  const cut = item.truncation ?? {};
  const notes: string[] = [];
  const original = typeof cut.char_count === "number" ? cut.char_count : 0;

  if (cut.store && original > storedChars) {
    notes.push(
      t("원문 {0}자 중 {1}자를 보관했습니다.", NUMBER.format(original), NUMBER.format(storedChars)),
    );
  } else if (cut.tool && original) {
    notes.push(
      t("도구가 {0}자에서 끊었습니다 — 뒷부분이 필요하면 다시 읽어야 합니다.", NUMBER.format(original)),
    );
  }
  if (cut.model_cut && typeof cut.to_model === "number") {
    notes.push(
      t("Sonjari에게는 앞 {0}자만 갔습니다. 아래 본문은 그보다 깁니다.", NUMBER.format(cut.to_model)),
    );
  }
  return notes;
}

/** 이 걸음이 실패했을 때 화면에 적을 한 줄. 성공이면 빈 문자열. */
export function failureLine(item: StepRow): string {
  if (item.ok) return "";
  if (item.error) return t("실패했습니다 — {0}", item.error);
  return t("실패했습니다. Sonjari가 이유를 남기지 않았습니다.");
}

// ─────────────────────────────────────────────────────────────────────────────
// 무엇을 보고 있나 (2026-08-23)
//
// step 은 **번호가 아니라 생각**이어야 한다는 것이 이 날의 요구였다. 「걸음 7」은
// 아무것도 말하지 않는다 — 그 자리에서 자비스가 무엇을 눈으로 훑었고 거기서
// 무엇을 알아냈는지가 사람이 알고 싶은 것이다.
//
// ## 연출과 주장을 구별한다
//
// 훑는 시늉은 만들기 쉽다. 줄 위로 빛을 스르륵 흘리면 열심히 읽는 것처럼 보인다.
// **그런데 아무 줄이나 훑으면 그건 연기다.** 우리는 모델이 42번째 줄을 봤는지
// 모르고, 모르는 것을 아는 척 그리면 화면이 거짓말을 하기 시작한다 — 이 저장소가
// 이미 세 번 당한 실패다(안 한 일을 했다고 답한 건, 코드 0줄 읽고 「Based on Code」
// 라고 쓴 건, 예외가 없다는 이유로 성공이라 보고한 건).
//
// 그래서 둘을 갈라 놓는다:
//
//     쓸어내리기   들어올 때 한 번 지나가는 빛. **아무 주장도 안 한다** — "이걸
//                  읽는 중"이라는 입장 인사지, 어느 줄이라는 말이 아니다.
//     걸린 줄      계속 남는 표시. **이건 주장이다.** 그래서 실제로 찾던 말이
//                  들어 있는 줄에만 붙는다. 찾던 말이 없으면 한 줄도 안 붙인다.
//
// ## 한 줄 소감도 세어서 말한다
//
// "이 페이지엔 이런 게 있네요"를 모델에게 시키면 그럴듯한 문장이 나오고, 그게
// 맞는지는 아무도 모른다. 그래서 **payload 를 세어서** 만든다. 링크가 84개면
// 84개라고 쓰고, 셀 것이 없으면 아무 말도 안 한다. 비전을 읽게 하고 판정은
// 코드가 하는 것과 같은 규칙이다.

/** 어느 열이 역할·종류를 담고 있나. 이름을 손으로 관리하지 않고 모양으로 고른다. */
function roleColumn(columns: string[]): number {
  for (const name of ["role", "tag", "kind", "type"]) {
    const at = columns.indexOf(name);
    if (at >= 0) return at;
  }
  return -1;
}

const ROLE_WORD: Record<string, string> = {
  link: t("링크"), a: t("링크"),
  button: t("버튼"), input: t("입력칸"), textbox: t("입력칸"), textarea: t("입력칸"),
  select: t("고르는칸"), combobox: t("고르는칸"), checkbox: t("체크칸"),
  img: t("그림"), image: t("그림"), table: t("표"), form: t("입력폼"),
};

/** 값이 많은 순으로 「링크 84 · 버튼 12」. 셀 것이 없으면 빈 글자. */
function tally(columns: string[], rows: string[][], limit = 3): string {
  const at = roleColumn(columns);
  if (at < 0) return "";
  const counts = new Map<string, number>();
  for (const row of rows) {
    const raw = (row[at] || "").toLowerCase().trim();
    if (!raw) continue;
    const word = ROLE_WORD[raw] || raw;
    counts.set(word, (counts.get(word) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((one, two) => two[1] - one[1])
    .slice(0, limit)
    .map(([word, count]) => `${word} ${count}`)
    .join(" · ");
}

function lineCount(text: string): number {
  return text ? text.split("\n").length : 0;
}

/**
 * 이 step 이 본 것을 **한 줄로**. 전부 payload 를 세어서 만든다.
 *
 * 셀 것이 없으면 빈 글자를 준다 — 그때는 화면이 이 줄을 아예 안 그린다.
 * 억지로 한 문장 만들어 놓으면 사람이 그걸 근거로 읽는다.
 */
export function takeaway(item: Observation | null): string {
  if (!item) return "";
  const payload = item.payload as Record<string, any>;
  const rows: string[][] = Array.isArray(payload.rows) ? payload.rows : [];
  const columns: string[] = Array.isArray(payload.columns) ? payload.columns : [];

  switch (item.kind) {
    case "page": {
      const parts: string[] = [];
      const elements = payload.elements;
      if (elements?.columns && elements?.rows) {
        const counted = tally(elements.columns, elements.rows);
        if (counted) parts.push(counted);
      }
      const chars = typeof payload.text === "string" ? payload.text.length : 0;
      if (chars) parts.push(t("본문 {0}자", chars.toLocaleString()));
      if (!parts.length) return "";
      const title = String(payload.title || "").trim();
      return title ? `${parts.join(" · ")} — 「${title}」` : parts.join(" · ");
    }
    case "code": {
      const text = String(payload.text || "");
      const lines = Number(payload.line_count) || lineCount(text);
      if (!lines) return "";
      // 정의부 세기. 언어를 가리지 않는 얕은 규칙이라 **대략**이라고 말한다.
      const defs = (text.match(/^\s*(?:def |class |function |export function |const \w+ = \()/gm) || []).length;
      const where = String(payload.language || "").trim();
      const head = t("{0}줄{1}", lines.toLocaleString(), where ? ` · ${where}` : "");
      return defs ? t("{0} · 정의 {1}개쯤", head, defs) : head;
    }
    case "document": {
      const text = String(payload.text || "");
      const lines = lineCount(text);
      if (!lines) return "";
      const heads = (text.match(/^#{1,6} .+$/gm) || []).length;
      const head = t("{0}줄 · {1}자", lines.toLocaleString(), text.length.toLocaleString());
      return heads ? t("{0} · 제목 {1}개", head, heads) : head;
    }
    case "table":
    case "files": {
      const count = Number(payload.row_count) || rows.length;
      if (!count) return "";
      const counted = tally(columns, rows);
      const head = t("{0}개 · 열 {1}", count.toLocaleString(), columns.length);
      return counted ? `${head} — ${counted}` : head;
    }
    case "draft": {
      const fields = payload.fields && typeof payload.fields === "object" ? payload.fields : {};
      const named = Object.keys(fields).filter((key) => !["action_id", "kind", "ok"].includes(key));
      return named.length ? t("보낼 것 {0}칸을 채웠습니다 — 승인 대기", named.length) : t("승인 대기");
    }
    default:
      return "";
  }
}

/** 인자에서 **찾던 말**을 뽑는다. 이게 있어야 「걸린 줄」이 주장이 된다. */
const TERM_KEYS = ["query", "pattern", "keyword", "search", "text", "name", "term", "q"];

export function readingTerms(item: Observation | null): string[] {
  if (!item) return [];
  const found: string[] = [];
  for (const [key, value] of Object.entries(item.arguments || {})) {
    if (!TERM_KEYS.includes(key.toLowerCase())) continue;
    const raw = String(value || "").trim();
    // 너무 짧은 것은 아무 줄에나 걸린다 — 표시가 의미를 잃는다.
    if (raw.length < 2 || raw.length > 80) continue;
    found.push(raw.toLowerCase());
  }
  return found;
}

/**
 * 찾던 말이 실제로 들어 있는 줄 번호(0부터). **없으면 빈 집합** — 이 표시는
 * 주장이라서, 근거가 없으면 한 줄도 안 붙인다.
 */
export function markedLines(text: string, terms: string[], limit = 40): Set<number> {
  const marks = new Set<number>();
  if (!text || !terms.length) return marks;
  const lines = text.split("\n");
  for (let at = 0; at < lines.length && marks.size < limit; at += 1) {
    const line = lines[at].toLowerCase();
    if (terms.some((term) => line.includes(term))) marks.add(at);
  }
  return marks;
}
