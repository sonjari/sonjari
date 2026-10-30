// 「/레시피」 — 해 보여서 가르치기 (2026-10-28 대표 결정).
//
// 앱 대화창에서 `/레시피`(영어판 `/recipe`) 한 단어를 치면 손자리가 바로 배우기 모드로 들어간다. 이 파일은 화면 쪽의 순수한 부분이다:
//   1. 입력창에 `/` 를 치면 뜨는 작은 명령 목록(고르는 규칙)
//   2. 백엔드가 알려 주는 「배우는 중」 · 「한 번 해 보는 중」 사건을 패널 상태로 쌓는 규칙
// 화면은 명령을 해석하지 않는다 — 글자를 그대로 보내면 백엔드(`self_talk`)가 모델을 부르지 않고 받는다.
import { t, type Lang } from "./i18n";

export interface SlashItem {
  /** 입력창에 채울 명령(현재 화면 언어). */
  command: string;
  /** 한 줄 설명(현재 화면 언어). */
  hint: string;
  /** 어느 언어로 쳐도 이 명령으로 찾는다. */
  names: string[];
}

const COMMANDS: { ko: string; en: string; hint: string }[] = [
  { ko: "/레시피", en: "/recipe", hint: "해 보여서 가르치기" },
];

/** 입력 중인 글이 「명령 낱말을 치는 중」이면 어울리는 명령 목록, 아니면 빈 목록. 공백이 들어가면(이름을 치는 중) 목록은 닫힌다. */
export function slashMenu(draft: string, language: Lang): SlashItem[] {
  if (!draft.startsWith("/") || /\s/.test(draft)) return [];
  const typed = draft.toLowerCase();
  return COMMANDS
    .filter((item) => item.ko.startsWith(typed) || item.en.startsWith(typed))
    .map((item) => ({ command: language === "en" ? item.en : item.ko, hint: t(item.hint), names: [item.ko, item.en] }));
}

/** 입력 글이 이미 완성된 명령 낱말(`/레시피` · `/recipe`) 그대로인가. */
export function isWholeCommand(draft: string): boolean {
  const typed = draft.trim().toLowerCase();
  return COMMANDS.some((item) => item.ko === typed || item.en === typed);
}

export type SlashKey = { kind: "send" } | { kind: "fill"; text: string } | { kind: "move"; index: number } | { kind: "none" };

/** 목록이 열려 있을 때 키 하나가 하는 일. Enter 는 완성된 명령이면 보내고, 덜 친 명령이면 채운다(이름을 이어 칠 수 있게 뒤에 빈칸). */
export function slashKey(draft: string, items: SlashItem[], index: number, key: string): SlashKey {
  if (!items.length) return { kind: "none" };
  if (key === "ArrowDown") return { kind: "move", index: (index + 1) % items.length };
  if (key === "ArrowUp") return { kind: "move", index: (index - 1 + items.length) % items.length };
  if (key === "Tab" || key === "Enter") {
    if (key === "Enter" && isWholeCommand(draft)) return { kind: "send" };
    return { kind: "fill", text: `${items[Math.min(Math.max(index, 0), items.length - 1)].command} ` };
  }
  return { kind: "none" };
}

// ── 배우는 중 패널 ─────────────────────────────────────────────────────────────

export interface LearnStep {
  n: number;
  kind: string;
  name: string;
  where: string;
}

export interface ReplayRow {
  n: number;
  text: string;
  state: "run" | "ok" | "bad";
  note: string;
}

export interface LearnState {
  phase: "idle" | "learning" | "replaying";
  label: string;
  steps: LearnStep[];
  replay: ReplayRow[];
  total: number;
}

export const idleLearn: LearnState = { phase: "idle", label: "", steps: [], replay: [], total: 0 };

const text = (value: unknown, limit = 80): string => String(value ?? "").slice(0, limit);

/** 백엔드 사건 하나를 패널 상태에 반영한다. 모르는 사건은 그대로 돌려준다. */
export function applyLearnEvent(state: LearnState, event: string, payload: Record<string, unknown>): LearnState {
  if (event === "demo_started") {
    return { phase: "learning", label: text(payload.label, 60), steps: [], replay: [], total: 0 };
  }
  if (event === "demo_step") {
    if (state.phase !== "learning") return state;
    const n = Number(payload.n ?? state.steps.length + 1);
    const step: LearnStep = { n, kind: text(payload.kind, 12), name: text(payload.name, 60), where: text(payload.where, 80) };
    return { ...state, steps: [...state.steps.filter((row) => row.n !== n), step].sort((a, b) => a.n - b.n).slice(-40) };
  }
  if (event === "demo_ended") return idleLearn;
  if (event === "demo_replay_started") {
    return { ...state, phase: "replaying", replay: [], total: Number(payload.total ?? 0) };
  }
  if (event === "demo_replay_step") {
    if (state.phase !== "replaying") return state;
    const n = Number(payload.n ?? 0);
    const ok = payload.ok;
    const row: ReplayRow = {
      n, text: text(payload.text, 100), note: text(payload.note, 120),
      state: ok === true ? "ok" : ok === false ? "bad" : "run",
    };
    return { ...state, replay: [...state.replay.filter((item) => item.n !== n), row].sort((a, b) => a.n - b.n) };
  }
  if (event === "demo_replay_done") return idleLearn;
  return state;
}

const KIND_KO: Record<string, string> = { click: "누르기", fill: "입력", press: "키 누르기", select: "고르기", nav: "이동" };
const KIND_EN: Record<string, string> = { click: "Click", fill: "Type", press: "Key", select: "Choose", nav: "Go to" };

/** 패널의 한 줄 — 「누르기 · 로그인 (shop.com)」. 입력한 글 자체는 화면에 싣지 않는다(칸 이름만). */
export function stepSentence(step: LearnStep, language: Lang): string {
  const kind = (language === "en" ? KIND_EN : KIND_KO)[step.kind] ?? step.kind;
  const name = step.name ? ` · ${language === "en" ? step.name : `「${step.name}」`}` : "";
  const where = step.where ? ` (${step.where})` : "";
  return `${kind}${name}${where}`;
}
