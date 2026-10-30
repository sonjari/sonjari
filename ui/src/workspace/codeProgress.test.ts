import { afterEach, describe, expect, it } from "vitest";
import { setLangForTest } from "../i18n";
import { advanceThinkingMeter, lastFileNameIn, thinkingLine } from "./codeProgress";

afterEach(() => setLangForTest("ko"));

it("확장자가 붙은 파일 이름을 뽑는다", () => {
  expect(lastFileNameIn("I should open plan.py and check the loop")).toBe("plan.py");
  for (const name of ["a.ts", "b.tsx", "c.js", "d.jsx", "e.json", "f.md", "g.css", "h.html", "i.ps1", "j.toml", "k.yaml", "l.yml"]) {
    expect(lastFileNameIn(`look at ${name} now`)).toBe(name);
  }
});

it("경로에서는 파일 이름만 남긴다 — 슬래시도 윈도 역슬래시도", () => {
  expect(lastFileNameIn("read src/alture_jarvis/plan.py next")).toBe("plan.py");
  expect(lastFileNameIn(String.raw`open C:\Users\user\proj\ui\src\App.tsx first`)).toBe("App.tsx");
  expect(lastFileNameIn("see ./ui/src/workspace/ComputerPane.tsx.")).toBe("ComputerPane.tsx");
});

it("마지막에 나온 것 하나만 — 앞에 나온 파일은 버린다", () => {
  expect(lastFileNameIn("first agent.py, then plan.py, finally tokens.css and done")).toBe("tokens.css");
});

it("확장자 없는 낱말은 파일로 치지 않는다", () => {
  expect(lastFileNameIn("the plan and the Makefile and README need a look")).toBe("");
  expect(lastFileNameIn("plan. py is not it")).toBe("");
  expect(lastFileNameIn("the plan.pyc and plan.pyx are not listed")).toBe("");
});

it("URL 안의 것은 파일로 치지 않는다", () => {
  expect(lastFileNameIn("docs at https://example.com/guide/setup.md say so")).toBe("");
  expect(lastFileNameIn("see www.example.org/a/b.json too")).toBe("");
  // URL 앞에 진짜 파일이 있으면 그것이 남는다.
  expect(lastFileNameIn("edit plan.py per https://example.com/a/b.json")).toBe("plan.py");
});

it("Node.js 같은 도구 이름은 파일로 치지 않는다", () => {
  expect(lastFileNameIn("using Node.js and Next.js here")).toBe("");
  expect(lastFileNameIn("using Node.js to run build.js")).toBe("build.js");
});

it("한글 문장 속 파일 이름과 따옴표 · 쉼표 · 줄 번호를 걷는다", () => {
  expect(lastFileNameIn("그래서 `plan.py`를 먼저 읽어야 한다")).toBe("plan.py");
  expect(lastFileNameIn("(config.toml), 그리고 'main.py':42 를 본다")).toBe("main.py");
});

it("끝부분만 본다 — 아주 앞에 나온 파일은 지금 보는 것이 아니다", () => {
  const text = `open old.py ${"x ".repeat(2_000)} then thinking only`;
  expect(lastFileNameIn(text)).toBe("");
  expect(lastFileNameIn(`${text} and new.py`)).toBe("new.py");
});

it("빈 글은 빈 문자열", () => {
  expect(lastFileNameIn("")).toBe("");
});

it("진행 줄: 파일이 있으면 같이, 없으면 글자 수까지", () => {
  expect(thinkingLine(3200, "plan.py")).toBe("생각 중 · 3,200자 · 보고 있는 파일: plan.py");
  expect(thinkingLine(3200, "")).toBe("생각 중 · 3,200자");
  setLangForTest("en");
  expect(thinkingLine(3200, "plan.py")).toBe("Thinking · 3,200 chars · looking at: plan.py");
});

// ── 생각 글 총량 세기 (2026-10-27) ──
describe("advanceThinkingMeter", () => {
  it("처음 보면 길이가 총량", () => {
    expect(advanceThinkingMeter(null, "abc").total).toBe(3);
  });
  it("이어 붙으면 늘어난 만큼 더한다", () => {
    const a = advanceThinkingMeter(null, "abc");
    expect(advanceThinkingMeter(a, "abcdef").total).toBe(6);
    expect(advanceThinkingMeter(a, "abc")).toBe(a);
  });
  it("앞이 잘려 밀려도(길이 그대로) 늘어난 만큼 더한다", () => {
    const base = Array.from({ length: 500 }, (_, i) => `row${String(i).padStart(4, "0")};`).join("");
    const a = advanceThinkingMeter(null, base);
    const slid = (base + "ZZZZZ").slice(-base.length);
    expect(advanceThinkingMeter(a, slid).total).toBe(a.total + 5);
  });
  it("이어지지 않으면(판이 바뀌어 지워짐) 새 글 길이로 다시 시작", () => {
    const a = advanceThinkingMeter(null, "x".repeat(900));
    expect(advanceThinkingMeter(a, "").total).toBe(0);
    expect(advanceThinkingMeter(a, "새 글").total).toBe(3);
  });
});
