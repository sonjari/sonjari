// @vitest-environment jsdom
/**
 * 설정 › 서기 (2026-10-22) — 경로를 손으로 치지 않고 프로젝트를 체크로 고른다 · 켜기 전 약속 셋 · 켠 뒤 장부 · 못 하는 까닭.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import type { ScribeStatus, SettingRow, SettingValue } from "../types";
import { ScribeSection, scribeAgo, scribeWarning, toggleFolder } from "./ScribeSection";
import { TAKEOVER_PHRASES, TakeoverHowTo } from "./TakeoverHowTo";

const HOME = "C:\\Users\\me\\.claude\\projects";

function status(extra: Partial<ScribeStatus> = {}): ScribeStatus {
  return {
    enabled: true, cards: 12, closed: 3, topics: 4, last_read_at: 1000 - 120, reading: 1,
    hooks: { installed: true, events: ["PostCompact", "SessionStart"] },
    projects: [
      { folder: `${HOME}\\E--app`, name: "E--app", workdir: "E:\\내 가게", sessions: 117, last_at: 1000 - 3600, chosen: true },
      { folder: `${HOME}\\D--side`, name: "D--side", workdir: "D:\\side", sessions: 2, last_at: 1000 - 86400 * 3, chosen: false },
      { folder: `${HOME}\\C--tmp`, name: "C--tmp", workdir: "C:\\Users\\me\\AppData\\Local\\Temp\\x", sessions: 1, last_at: 900, chosen: false, temp: true },
    ],
    ...extra,
  };
}

function row(key: string, value: SettingValue): SettingRow {
  return { key, group: "scribe", label: key, kind: key === "scribe_enabled" ? "bool" : "list", help: "", choices: [], min: null, max: null,
    lab: false, value, source: "user", live: true, unavailable: "", restart_required: false } as unknown as SettingRow;
}

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.spyOn(Date, "now").mockReturnValue(1000 * 1000);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function render(view: ScribeStatus, enabled: boolean, folders: string[], save = vi.fn(async () => true)) {
  const client = { getScribeStatus: vi.fn(async () => view) } as unknown as JarvisClient;
  const rows = [row("scribe_enabled", enabled), row("scribe_folders", folders)];
  await act(async () => {
    root.render(<ScribeSection client={client} rows={rows} save={save}
      control={(item) => <li key={item.key} data-key={item.key}>{item.key}</li>} />);
  });
  return save;
}

it("프로젝트는 작업 폴더 이름으로 보이고, 체크하면 그 기록 폴더가 고른 목록에 붙는다", async () => {
  const save = await render(status(), true, [`${HOME}\\E--app`]);
  const text = container.textContent ?? "";
  expect(text).toContain("E:\\내 가게");
  expect(text).toContain("대화 117개 · 마지막 1시간 전");
  expect(text).not.toContain("E--app"); // 기록 폴더 이름(한글이 - 로 바뀐 것)은 안 보인다
  const boxes = [...container.querySelectorAll<HTMLInputElement>(".scribe-project-list input")];
  expect(boxes.map((box) => box.checked)).toEqual([true, false, false]);
  await act(async () => { boxes[1].click(); });
  expect(save).toHaveBeenCalledWith("scribe_folders", [`${HOME}\\E--app`, `${HOME}\\D--side`]);
});

it("임시 폴더 대화는 접어 두고, 켜기 전 약속 셋과 켠 뒤 장부를 보인다", async () => {
  await render(status(), true, [`${HOME}\\E--app`]);
  expect(container.querySelector(".scribe-temp summary")?.textContent).toBe("임시 폴더에서 연 대화 1개");
  expect(container.querySelectorAll(".scribe-promises li")).toHaveLength(3);
  const ledger = container.querySelector(".scribe-ledger")?.textContent ?? "";
  expect(ledger).toContain("쌓인 카드12");
  expect(ledger).toContain("마지막으로 읽음2분 전");
  expect(ledger).toContain("클로드 코드 훅들어감");
  expect(container.querySelector('[data-key="scribe_enabled"]')).not.toBeNull();
});

it("꺼져 있으면 장부를 안 보이고, 켰는데 고른 곳이 없으면 그 까닭을 말한다", async () => {
  await render(status({ projects: status().projects.map((item) => ({ ...item, chosen: false })) }), false, []);
  expect(container.querySelector(".scribe-ledger")).toBeNull();
  const none = status({ projects: status().projects.map((item) => ({ ...item, chosen: false })) });
  expect(scribeWarning(none, true)).toContain("하나 이상 골라");
  expect(scribeWarning(status({ hooks: { installed: false, events: [] } }), true)).toContain("훅이 아직");
  expect(scribeWarning(status(), true)).toBe("");
  expect(scribeWarning(none, false)).toBe("");
});

it("고른 목록 바꾸기 — 같은 폴더를 두 번 넣지 않고, 대소문자가 달라도 같은 폴더", () => {
  expect(toggleFolder(["C:\\A"], "c:\\a", true)).toEqual(["c:\\a"]);
  expect(toggleFolder(["C:\\A", "C:\\B"], "c:\\a", false)).toEqual(["C:\\B"]);
  expect(scribeAgo(0, 100)).toBe("기록 없음");
  expect(scribeAgo(100 - 86400 * 2, 100)).toBe("2일 전");
});

it("이어받기 안내 — 손자리 창에 그대로 말할 예시와, 이 PC 의 Claude Code · Codex 만 된다는 조건", async () => {
  await act(async () => { root.render(<TakeoverHowTo />); });
  const text = container.textContent ?? "";
  for (const phrase of TAKEOVER_PHRASES) expect(text).toContain(`「${phrase}」`);
  expect(text).toContain("웹이나 휴대폰 채팅은");
  expect(text).toContain("Codex");
});
