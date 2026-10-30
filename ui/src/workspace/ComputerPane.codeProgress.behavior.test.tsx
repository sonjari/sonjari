// @vitest-environment jsdom
/**
 * 코드 모드 진행이 보인다 (2026-10-27 현장: 느리다 · 「…단계를 진행하고 있습니다」로 퉁쳐서 답답하다).
 * ① 생각 상자는 펼친 채 시작 + 도는 동안 「이 PC에서 생각 중」 ② 처음에 나눈 일 체크 목록 ③ 도구 없는 걸음의 진행 줄.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { setLangForTest } from "../i18n";
import type { AgentProgress, PlanItem, WorkspaceMode } from "../types";
import { ComputerPane } from "./ComputerPane";

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  setLangForTest("ko");
});

const PLAN: PlanItem[] = [
  { kind: "action", label: "plan.py 의 반복문 읽기", met: true, saw: "읽음" },
  { kind: "action", label: "시험 돌려 확인", met: false, saw: "" },
];

const TOOL_STEP: AgentProgress = {
  key: "k1", jobId: "j1", phase: "tool", message: "plan.py 를 읽고 있습니다", step: 2, tool: "local_read_text_file", status: "running",
};

function draw(opts: {
  mode?: WorkspaceMode;
  live?: boolean;
  jobId?: string;
  thinkingText?: string;
  plan?: PlanItem[];
  progress?: AgentProgress[];
} = {}) {
  act(() => {
    root.render(
      <ComputerPane
        client={null}
        mode={opts.mode ?? "code"}
        open
        live={opts.live ?? true}
        jobId={opts.jobId ?? "j1"}
        progress={opts.progress ?? []}
        plan={opts.plan ?? []}
        thinkingText={opts.thinkingText}
        elapsedLabel="42초"
        onCancel={() => undefined}
      />,
    );
  });
}

const title = () => container.querySelector(".code-operation-title")?.textContent;
const thinkHead = () => container.querySelector(".code-think > button");

it("코드 모드 생각 상자는 펼친 채 시작하고 본문은 7줄 높이 상자(fixed)다", () => {
  draw({ thinkingText: "Let me look at plan.py first." });
  const box = container.querySelector(".code-think");
  expect(box?.classList.contains("open")).toBe(true);
  expect(box?.classList.contains("fixed")).toBe(true);
  expect(thinkHead()?.getAttribute("aria-expanded")).toBe("true");
  expect(container.querySelector(".code-think-body pre")?.textContent).toBe("Let me look at plan.py first.");
});

it("사람이 접으면 그 판 동안은 접힌 채 — 새 판이 오면 다시 펼친 채 시작", () => {
  draw({ thinkingText: "thinking about plan.py" });
  act(() => (thinkHead() as HTMLButtonElement).click());
  expect(container.querySelector(".code-think-body")).toBeNull();
  // 글이 늘어도 접힌 채
  draw({ thinkingText: "thinking about plan.py and more of it" });
  expect(container.querySelector(".code-think-body")).toBeNull();
  // 새 판
  draw({ jobId: "j2", thinkingText: "new job thinking" });
  expect(container.querySelector(".code-think-body")).not.toBeNull();
});

it("「이 PC에서 생각 중」은 판이 도는 동안만 머리줄에 보인다", () => {
  draw({ thinkingText: "hmm" });
  expect(thinkHead()?.textContent).toContain("이 PC에서 생각 중");
  draw({ live: false, thinkingText: "hmm" });
  expect(thinkHead()?.textContent).not.toContain("이 PC에서 생각 중");
});

it("클로드가 직접 하는 판(claude-…)에는 「이 PC에서 생각 중」을 붙이지 않는다 — 그 생각은 이 PC 것이 아니다", () => {
  draw({ jobId: "claude-abc", thinkingText: "hmm" });
  expect(container.querySelector(".code-think")).not.toBeNull();
  expect(thinkHead()?.textContent).not.toContain("이 PC에서 생각 중");
});

it("영어 화면이면 영어로 말한다", () => {
  setLangForTest("en");
  draw({ thinkingText: "hmm", plan: PLAN });
  expect(thinkHead()?.textContent).toContain("Thinking on this PC");
  expect(container.querySelector(".code-plan-check-head")?.textContent).toBe("Tasks planned up front");
});

it("처음에 나눈 일: 이름 + 됐으면 체크, 맨 위에 선다", () => {
  draw({ plan: PLAN, thinkingText: "hmm" });
  const list = container.querySelector(".code-plan-check");
  expect(list).not.toBeNull();
  const items = [...list!.querySelectorAll("li")];
  expect(items.map((li) => li.querySelector(".code-plan-check-label")?.textContent)).toEqual(["plan.py 의 반복문 읽기", "시험 돌려 확인"]);
  expect(items.map((li) => li.classList.contains("met"))).toEqual([true, false]);
  expect(items[0].querySelector("svg")).not.toBeNull();
  expect(items[1].querySelector("svg")).toBeNull();
  // 코드 칸에서 가장 위(작업 척추 · 생각 상자보다 앞)
  const inner = container.querySelector(".computer-inner")!;
  const order = [...inner.children].map((el) => el.className);
  expect(order.findIndex((c) => String(c).includes("code-plan-check")))
    .toBeLessThan(order.findIndex((c) => String(c).includes("code-operation")));
});

it("목록이 비면 안 그린다 · 코드가 아닌 모드에서도 안 그린다 · 많으면 6개 + 「외 n개」", () => {
  draw({ plan: [] });
  expect(container.querySelector(".code-plan-check")).toBeNull();
  draw({ mode: "cowork", plan: PLAN });
  expect(container.querySelector(".code-plan-check")).toBeNull();
  const many = Array.from({ length: 9 }, (_, i) => ({ kind: "action", label: `일 ${i + 1}`, met: false, saw: "" }));
  draw({ plan: many });
  expect(container.querySelectorAll(".code-plan-check li")).toHaveLength(6);
  expect(container.querySelector(".code-plan-check-more")?.textContent).toBe("외 3개");
});

it("도구 없는 걸음: 「생각 중 · 글자 · 보고 있는 파일」", () => {
  const text = "I need to understand the planner. Let me read src/alture_jarvis/plan.py to see the flow.";
  draw({ thinkingText: text });
  expect(title()).toBe(`생각 중 · ${text.length}자 · 보고 있는 파일: plan.py`);
});

it("파일 이름이 없으면 글자 수까지만", () => {
  draw({ thinkingText: "Let me think about the loop." });
  expect(title()).toBe("생각 중 · 28자");
});

it("글자 수는 천 단위 쉼표", () => {
  draw({ thinkingText: "a ".repeat(1_600) });
  expect(title()).toBe("생각 중 · 3,200자");
});

it("생각 글이 아직 없으면 지금 그대로(…단계를 진행하고 있습니다)", () => {
  draw({ thinkingText: "" });
  expect(title()).toBe("계획 단계를 진행하고 있습니다");
});

it("도구가 있는 걸음은 지금 동작 그대로", () => {
  draw({ thinkingText: "reading plan.py", progress: [TOOL_STEP] });
  expect(title()).toBe("plan.py 를 읽고 있습니다");
});

it("도구 없이 구체적인 말을 보낸 걸음(비켜 주는 중 · 정리 중)은 그 말을 지킨다", () => {
  const waiting: AgentProgress = { key: "k2", jobId: "j1", phase: "waiting", message: "사람의 요청을 먼저 하도록 잠시 비켜 줍니다", step: 0, tool: "", status: "running" };
  draw({ thinkingText: "reading plan.py", progress: [waiting] });
  expect(title()).toBe("사람의 요청을 먼저 하도록 잠시 비켜 줍니다");
});

it("계획 단계의 일반 문구는 생각 줄로 바뀐다", () => {
  const planning: AgentProgress = { key: "k3", jobId: "j1", phase: "planning", message: "요청을 분석하고 실행 계획을 세우고 있습니다", step: 0, tool: "", status: "running" };
  draw({ thinkingText: "about to open tokens.css", progress: [planning] });
  expect(title()).toBe("생각 중 · 24자 · 보고 있는 파일: tokens.css");
});

it("판이 끝나면 생각 줄을 쓰지 않는다", () => {
  draw({ live: false, thinkingText: "reading plan.py", progress: [TOOL_STEP] });
  expect(title()).not.toContain("생각 중");
});

// ── 도구를 쓴 뒤 다시 생각하는 동안 (2026-10-27) ──
// 백엔드는 도구를 쓸 때만 진행 알림을 보낸다. 마지막 알림 뒤로 생각 글이 200자 넘게 늘었으면 지금은 생각하는 중이다.

it("도구 걸음 알림 뒤 생각 글이 200자 넘게 늘면 생각 줄로 바뀐다", () => {
  const first = "Let me read plan.py now.";
  draw({ thinkingText: first, progress: [TOOL_STEP] });
  expect(title()).toBe("plan.py 를 읽고 있습니다");
  const grown = `${first} ${"x".repeat(240)} then tokens.css next`;
  draw({ thinkingText: grown, progress: [TOOL_STEP] });
  expect(title()).toBe(`생각 중 · ${grown.length.toLocaleString("en-US")}자 · 보고 있는 파일: tokens.css`);
});

it("생각 글이 문턱(200자) 아래로만 늘면 도구 문구 그대로 — 짧은 걸음에서 줄이 깜빡이지 않는다", () => {
  const first = "Let me read plan.py now.";
  draw({ thinkingText: first, progress: [TOOL_STEP] });
  draw({ thinkingText: first + "y".repeat(199), progress: [TOOL_STEP] });
  expect(title()).toBe("plan.py 를 읽고 있습니다");
  draw({ thinkingText: first + "y".repeat(200), progress: [TOOL_STEP] });
  expect(title()).toContain("생각 중");
});

it("새 도구 알림이 오면 도구 문구로 돌아가고, 거기서 다시 200자 넘게 늘어야 생각 줄이 된다", () => {
  const first = "Let me read plan.py now.";
  const big = first + "z".repeat(300);
  draw({ thinkingText: first, progress: [TOOL_STEP] });
  draw({ thinkingText: big, progress: [TOOL_STEP] });
  expect(title()).toContain("생각 중");
  const next: AgentProgress = { ...TOOL_STEP, key: "k9", step: 3, message: "tokens.css 를 읽고 있습니다" };
  draw({ thinkingText: big, progress: [TOOL_STEP, next] });
  expect(title()).toBe("tokens.css 를 읽고 있습니다");
  draw({ thinkingText: big + "w".repeat(150), progress: [TOOL_STEP, next] });
  expect(title()).toBe("tokens.css 를 읽고 있습니다");
  draw({ thinkingText: big + "w".repeat(260), progress: [TOOL_STEP, next] });
  expect(title()).toContain("생각 중");
});

it("판이 끝나면(live=false) 생각이 늘었어도 생각 줄은 안 보인다", () => {
  const first = "Let me read plan.py now.";
  draw({ thinkingText: first, progress: [TOOL_STEP] });
  draw({ live: false, thinkingText: first + "q".repeat(500), progress: [TOOL_STEP] });
  expect(title()).not.toContain("생각 중");
  expect(title()).toBe("plan.py 를 읽고 있습니다");
});

it("구체적인 말을 보낸 도구 없는 걸음은 생각이 늘어도 그 말을 지킨다", () => {
  const waiting: AgentProgress = { key: "k2", jobId: "j1", phase: "waiting", message: "사람의 요청을 먼저 하도록 잠시 비켜 줍니다", step: 0, tool: "", status: "running" };
  draw({ thinkingText: "a", progress: [waiting] });
  draw({ thinkingText: "a" + "b".repeat(500), progress: [waiting] });
  expect(title()).toBe("사람의 요청을 먼저 하도록 잠시 비켜 줍니다");
});

it("생각 글이 40,000자 상한에서 앞이 잘려 길이가 그대로여도 늘어난 것으로 센다", () => {
  const cap = 40_000;
  // 줄마다 다른 번호를 붙여 겹침 찾기가 헷갈리지 않게 한다.
  const body = Array.from({ length: 4_000 }, (_, i) => `line${String(i).padStart(5, "0")}`).join("\n");
  const base = body.slice(0, cap);
  draw({ thinkingText: base, progress: [TOOL_STEP] });
  expect(title()).toBe("plan.py 를 읽고 있습니다");
  const extra = "N".repeat(260);
  const slid = (base + extra).slice(-cap);
  expect(slid.length).toBe(cap);
  draw({ thinkingText: slid, progress: [TOOL_STEP] });
  expect(title()).toContain("생각 중");
});

it("claude- 판은 생각이 늘어도 「이 PC에서 생각 중」을 붙이지 않는다(머리줄은 그대로)", () => {
  const step: AgentProgress = { ...TOOL_STEP, jobId: "claude-abc" };
  draw({ jobId: "claude-abc", thinkingText: "hmm", progress: [step] });
  draw({ jobId: "claude-abc", thinkingText: "hmm" + "k".repeat(300), progress: [step] });
  expect(thinkHead()?.textContent).not.toContain("이 PC에서 생각 중");
});
