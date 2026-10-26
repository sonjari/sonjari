/**
 * 대화마다 고른 **두뇌** — 「내 PC 모델」(기본) 또는 「Claude Agent · 내 API 키」(Haiku 5.5 / Sonnet 5.5 / Opus 5.5) (2026-10-26).
 *
 * 갈림은 모델 칸 하나다(ADR 고침 3). 앱 전체가 바뀌는 파일럿 시범판(`bootstrap.mode === "pilot"`)과 달리, 여기서는 **대화 하나**만 바뀐다.
 *
 * ## 이름 규칙(앤트로픽 상표 · 대표 결정)
 * - 무리 이름은 한국어판 · 영어판 모두 영어 「Claude Agent」. 항목은 「Haiku 5.5 / Sonnet 5.5 / Opus 5.5」.
 * - 「Claude Code」 글자는 화면 어디에도 쓰지 않는다. 공식 로고도 쓰지 않는다 — 주황 점(`--origin-claude`)만.
 */
import { PILOT_MODELS, type PilotModelId } from "../pilot/PilotModelPicker";

export type Brain = "local" | PilotModelId;

export const CLAUDE_AGENT = "Claude Agent";
export const CLAUDE_MODELS = PILOT_MODELS;

const STORE_KEY = "sonjari.brain.by-session.v1";

export function isClaudeBrain(brain: Brain | string | undefined | null): brain is PilotModelId {
  return CLAUDE_MODELS.some((model) => model.id === brain);
}

export function claudeModelLabel(brain: PilotModelId): string {
  return CLAUDE_MODELS.find((model) => model.id === brain)?.label ?? brain;
}

/** 버튼 글자 — 「Claude Agent · Sonnet 5.5」. */
export function claudeButtonLabel(brain: PilotModelId): string {
  return `${CLAUDE_AGENT} · ${claudeModelLabel(brain)}`;
}

function read(): Record<string, Brain> {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORE_KEY) ?? "{}") as Record<string, string>;
    const out: Record<string, Brain> = {};
    for (const [session, brain] of Object.entries(value ?? {})) {
      if (brain === "local" || isClaudeBrain(brain)) out[session] = brain as Brain;
    }
    return out;
  } catch {
    return {};
  }
}

function write(value: Record<string, Brain>) {
  try {
    // 오래된 대화가 끝없이 쌓이지 않게 — 최근 300개만.
    const entries = Object.entries(value).slice(-300);
    window.localStorage.setItem(STORE_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // 저장을 못 해도 이번 화면에서는 고른 대로 간다.
  }
}

/** 그 대화의 두뇌. 고른 적 없으면 내 PC 모델(지금 동작 그대로). */
export function brainFor(sessionId: string): Brain {
  return (sessionId && read()[sessionId]) || "local";
}

export function setBrain(sessionId: string, brain: Brain): void {
  const all = read();
  if (!sessionId) return;
  const key = sessionId;
  if (brain === "local") delete all[key];
  else all[key] = brain;
  write(all);
}
