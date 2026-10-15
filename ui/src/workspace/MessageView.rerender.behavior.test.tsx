// @vitest-environment jsdom
/**
 * 대화가 길어도, 바뀌지 않은 지난 말은 다시 그리지 않는다 (2026-10-07 대표: 「대화창이 길어질수록 화면이 느리다 — 옛날 GPT 웹 같다」).
 *
 * 작업 화면은 한 덩어리라서 입력 칸에 한 글자를 쳐도, 답이 한 토큰 와도, 1초 시계가 한 번 가도 통째로 다시 그린다.
 * 그때마다 지난 답 전부의 마크다운(표·수식 변환 포함)을 처음부터 다시 풀었다 — 드는 값이 대화 길이에 비례했다.
 */
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { MessageView } from "./MessageView";
import { timeLabel } from "./format";
import type { ConversationMessage } from "../types";

// 눈금: 지난 말 한 줄은 그려질 때마다 시각 글자를 한 번 만든다(`timeLabel`). 그 횟수가 곧 「다시 그려진 줄 수」다.
// (처음엔 바깥 틀이 그려진 횟수를 셌다 — 지난 말이 그대로여도 틀은 매번 그려져서 고친 뒤에도 20 이 나왔다.)
vi.mock("./format", async (original) => {
  const actual = await original<typeof import("./format")>();
  return { ...actual, timeLabel: vi.fn(actual.timeLabel) };
});

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ANSWER = [
  "## 세 가지를 견줬습니다",
  "",
  "| 항목 | 가 | 나 | 다 |",
  "|---|---|---|---|",
  ...Array.from({ length: 12 }, (_, i) => `| ${i + 1}번 줄 | **${i * 3}개** | ${i * 7}원 | [근거](https://example.test/${i}) |`),
  "",
  "- 첫째, 표의 값은 각 페이지에서 **직접 읽은 것**입니다.",
  "- 둘째, 확인하지 못한 칸은 `확인 못 함`이라고 적었습니다.",
  "- 셋째, 범위는 1~3쪽입니다.",
  "",
  "1. 먼저 목록을 엽니다.",
  "2. 그다음 상세를 읽습니다.",
].join("\n");

function conversation(count: number): ConversationMessage[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    role: i % 2 ? "assistant" : "user",
    content: i % 2 ? ANSWER : `질문 ${i + 1}`,
    created_at: 1_790_000_000 + i,
    metadata: {},
  })) as unknown as ConversationMessage[];
}

let host: HTMLDivElement | null = null;
afterEach(() => {
  host?.remove();
  host = null;
});

it("typing in the box does not redraw the messages that did not change", async () => {
  const messages = conversation(80);
  let tick: () => void = () => undefined;
  // 작업 화면의 모양 그대로: 부모가 상태를 들고 있고(입력 칸의 글), 지난 말들은 같은 props 로 다시 건네진다.
  // 넘기는 함수도 그 화면처럼 그릴 때마다 새로 만들어지는 함수가 아니어야 한다 — 고정된 것을 넘긴다.
  const observeAgain = () => undefined;
  function Screen() {
    const [typed, setTyped] = useState(0);
    tick = () => setTyped((n) => n + 1);
    return (
      <div data-typed={typed}>
        {messages.map((message) => <MessageView key={message.id} message={message} onObserveAgain={observeAgain} />)}
      </div>
    );
  }
  host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const startedMount = performance.now();
  await act(async () => { root.render(<Screen />); });
  const mountMs = performance.now() - startedMount;
  expect(host.querySelectorAll("table").length).toBe(40);
  expect(vi.mocked(timeLabel)).toHaveBeenCalledTimes(80);   // 처음 한 번은 줄마다 그린다

  vi.mocked(timeLabel).mockClear();
  const started = performance.now();
  for (let i = 0; i < 20; i++) {
    await act(async () => { tick(); });
  }
  const typingMs = performance.now() - started;
  // 재는 값을 남긴다(판정은 아래의 「다시 그린 횟수」로 한다 — 시간은 기계마다 다르다).
  const redrawn = vi.mocked(timeLabel).mock.calls.length;
  console.log(`[long-conversation] 메시지 80개 · 처음 그리기 ${mountMs.toFixed(0)}ms · 글자 20번 치기 ${typingMs.toFixed(0)}ms · 다시 그려진 줄 ${redrawn}`);
  expect(redrawn).toBe(0);
  await act(async () => { root.unmount(); });
});
