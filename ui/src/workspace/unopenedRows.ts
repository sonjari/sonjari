/**
 * 한 번도 안 연 곳의 줄 — 오른쪽 판 「시킨 것」 아래 한 줄 (2026-10-24).
 *
 * 백엔드(`unopened_places.py`)가 판 끝에 센다: 답의 표 · 만든 파일의 줄 가운데 **그 줄의 곳(주소)을 이 판에서 한 번도
 * 열지 않았는데** 값 칸이 채워진 줄. 판 기록 `verification.unopened_place_rows` 에 남는다.
 * 이 사실은 예전에 답 글 끝의 ⚠ 문단으로 보였는데, 대조 덩어리를 창 답에서 걷으면서(§55-44) 사람 눈에는 어디에도 안 보이게 됐다.
 * 그래서 이 칸이 판 기록을 **그대로** 읽어 한 줄로 둔다 — 글을 다시 파싱하지 않는다.
 *
 * 받는 곳은 둘이다(먼저 있는 것):
 *   1. 판이 끝날 때 오는 `agent_progress`(phase=verification)의 evidence — 이 창이 지켜본 판.
 *   2. 대화 기록의 답 메타데이터 `agent_verification` — 대화를 다시 읽은 뒤에도 같은 판이면 남는다.
 */
import type { ConversationMessage } from "../types";
import type { AnswerCheck } from "./answerChecks";

export interface UnopenedRow {
  /** 줄의 이름(첫 이름 칸). */
  name: string;
  /** 그 줄의 주소 칸. */
  url: string;
  /** 주소의 곳(호스트) — 이 판에서 한 번도 안 닿은 곳. */
  place: string;
  /** 채워져 있던 값 칸(많아야 8개). */
  values: string[];
  /** 같은 줄의 「확인 불가」 칸 수 — 0 보다 크면 「못 열었다」고 적은 줄에 값이 같이 있는 모순이다. */
  unknown: number;
}

/** 판 기록(verification) 하나에서 줄들을 꺼낸다. 모양이 어긋난 칸은 버린다 — 없는 것을 있는 척하지 않는다. */
export function unopenedRowsOf(verification: unknown): UnopenedRow[] {
  if (!verification || typeof verification !== "object") return [];
  const raw = (verification as Record<string, unknown>).unopened_place_rows;
  if (!Array.isArray(raw)) return [];
  const rows: UnopenedRow[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const row = entry as Record<string, unknown>;
    const name = String(row.name ?? "").trim();
    const place = String(row.place ?? "").trim();
    if (!name || !place) continue;
    rows.push({
      name,
      place,
      url: String(row.url ?? ""),
      values: Array.isArray(row.values) ? row.values.map(String) : [],
      unknown: Number(row.unknown ?? 0) || 0,
    });
  }
  return rows;
}

/** 대화 기록에서 **그 판의** 답을 찾아 줄들을 꺼낸다. 다른 판의 답에서 꺼내면 다른 작업의 경고를 이 판에 붙이게 된다. */
export function unopenedRowsForJob(messages: ConversationMessage[], jobId: string): UnopenedRow[] {
  if (!jobId) return [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role !== "assistant" || String(message.metadata?.job_id ?? "") !== jobId) continue;
    return unopenedRowsOf(message.metadata?.agent_verification);
  }
  return [];
}

/** 예전 답(대조 덩어리를 걷기 전)은 같은 사실을 ⚠ 문단으로도 싣고 있다 — 줄이 있으면 그 노란 줄은 빼서 두 번 말하지 않는다. */
const OLD_NOTE = /열어 보지 않은 곳의 줄|never opened in this run/;

export function withoutUnopenedCheck(checks: AnswerCheck[], rows: UnopenedRow[]): AnswerCheck[] {
  if (!rows.length) return checks;
  return checks.filter((check) => !OLD_NOTE.test(`${check.title} ${check.detail}`));
}
