// @vitest-environment jsdom
/**
 * 「한 번도 안 연 곳의 줄」은 오른쪽 판 「시킨 것」 아래 한 줄로 선다 (2026-10-24).
 * 답 글에서 대조 덩어리를 걷은 뒤(§55-44) 이 경고는 사람 눈에 어디에도 안 보였다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { setLangForTest } from "../i18n";
import { ComputerPane } from "./ComputerPane";
import type { UnopenedRow } from "./unopenedRows";

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

const ROWS: UnopenedRow[] = [
  { name: "Brief AI", url: "https://brief.example.tech/ai", place: "brief.example.tech", values: ["매일", "예"], unknown: 1 },
  { name: "The Weekly", url: "https://weekly.example.org", place: "weekly.example.org", values: ["매주"], unknown: 0 },
];

function draw(unopened?: UnopenedRow[]) {
  act(() => {
    root.render(
      <ComputerPane
        client={null}
        open
        live={false}
        jobId="j1"
        progress={[]}
        plan={[{ kind: "count", label: "곳마다 직접 열어 보기", met: true, saw: "3개 열어 읽음" }]}
        unopened={unopened}
        elapsedLabel="42초"
        onCancel={() => undefined}
      />,
    );
  });
}

it("줄이 있으면 시킨 것 아래 한 줄로 개수를 말하고, 펼치면 어느 줄 · 어느 곳인지 보인다", () => {
  draw(ROWS);
  const box = container.querySelector(".computer-plan");
  expect(box?.textContent).toContain("시킨 것");
  const details = container.querySelector<HTMLDetailsElement>(".computer-plan details");
  expect(details).not.toBeNull();
  expect(details!.open).toBe(false);
  expect(details!.querySelector("summary")?.textContent).toBe("열지 않은 곳 2줄 — 값은 다른 글에서 옮긴 것");
  act(() => details!.querySelector("summary")!.click());
  expect(details!.open).toBe(true);
  const items = [...details!.querySelectorAll("li")].map((li) => li.textContent);
  expect(items).toEqual([
    "Brief AIbrief.example.tech · 「확인 불가」 칸과 함께",
    "The Weeklyweekly.example.org",
  ]);
  // 무엇이 채워져 있었는지는 줄에 올리면 보인다.
  expect(details!.querySelector("li")?.getAttribute("title")).toBe("https://brief.example.tech/ai · 매일 · 예");
});

it("줄이 없으면 아무 줄도 안 그린다(시킨 것은 그대로)", () => {
  draw([]);
  expect(container.querySelector(".computer-plan")?.textContent).toContain("곳마다 직접 열어 보기");
  expect(container.querySelector(".computer-plan details")).toBeNull();
  draw(undefined);
  expect(container.querySelector(".computer-plan details")).toBeNull();
});

it("시킨 것이 없는 판이어도 줄이 있으면 칸이 선다", () => {
  act(() => {
    root.render(
      <ComputerPane client={null} open live={false} jobId="j1" progress={[]} plan={[]} unopened={ROWS.slice(1)}
        elapsedLabel="1초" onCancel={() => undefined} />,
    );
  });
  expect(container.querySelector(".computer-plan summary")?.textContent).toBe("열지 않은 곳 1줄 — 값은 다른 글에서 옮긴 것");
});

it("영어 화면이면 영어로 말한다", () => {
  setLangForTest("en");
  draw(ROWS);
  expect(container.querySelector(".computer-plan summary")?.textContent).toBe("2 rows from places never opened — values copied from other pages");
  expect(container.querySelector(".computer-plan details li em")?.textContent).toBe("brief.example.tech · beside an unverified cell");
});
