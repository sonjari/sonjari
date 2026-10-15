// @vitest-environment jsdom
/**
 * 게임 팩 2단계 (2026-09-27) — 열린 에디터 잇기·무대·우리 방·정기 점검.
 * 사람이 보는 약속 셋을 시험으로 둔다: 기본은 밖으로 0건 · 무대는 창을 앞으로 안 가져온다(「직접 하기」만) · 정기 점검은 모델 없이.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import type { UnityEditorView, UnitySchedule } from "../types";
import { EditorBlock, ScheduleBlock } from "./UnityEditorSection";

const VIEW: UnityEditorView = {
  projects: [
    { path: "E:/UnityProjects/Game", name: "Game", installed: false, other_version: false, value: "", editor_open: true, connected: false, reloading: false },
  ],
  room: { calls: 12, by_tool: { "manage_scene:get_hierarchy": { calls: 10, failed: 1 } }, recent: [], shared_count: 0, share_with_coplay: false, install_id: "x" },
  stage: { status: "ready", title: "Game - Main - Unity 6.6" },
  package_version: "10.2.0-ontelic.4",
};

const SCHEDULE: UnitySchedule = {
  id: "s1", recipe: "missing_references", title: "빠진 참조 찾기", project: "E:/UnityProjects/Game", at: "03:00", days: "daily",
  enabled: true, running: false, deferred: "",
  last: { at: 1_790_000_000, scheduled: true, verified: true, failure: "", numbers: { missing_references: 5, missing_scripts: 0 },
          worse: { missing_references: [2, 5] } },
  history: [], watch_labels: { missing_references: "끊긴 참조", missing_scripts: "빠진 스크립트" },
};

let root: Root;
let container: HTMLDivElement;
let client: JarvisClient;
let view: UnityEditorView;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  view = structuredClone(VIEW);
  Object.assign(URL, { createObjectURL: vi.fn(() => "blob:unity"), revokeObjectURL: vi.fn() });
  client = {
    unityEditor: vi.fn(async () => view),
    unityEditorLink: vi.fn(async (_path: string, on: boolean) => {
      view.projects[0] = { ...view.projects[0], installed: on, connected: on };
      return { ok: true, next: "에디터가 새 패키지를 읽고 있습니다(창을 건드리지 않고 20초 안팎).", resolved_now: true };
    }),
    unityShareWithCoplay: vi.fn(async (on: boolean) => {
      view.room = { ...view.room, share_with_coplay: on };
      return { share_with_coplay: on, install_id: "x" };
    }),
    getUnityStageFrame: vi.fn(async (after: number) => {
      await new Promise((resolve) => setTimeout(resolve, 5));
      return { blob: new Blob(["jpg"]), seq: after + 1, width: 1600, height: 900, title: "Game - Main - Unity 6.6", problem: "" };
    }),
    unityTakeOver: vi.fn(async () => ({ ok: true, title: "Game" })),
    unitySchedules: vi.fn(async () => ({ schedules: [SCHEDULE] })),
    unityDrafts: vi.fn(async () => ({
      drafts: [], recipes: ["missing_references", "texture_audit"],
      // 제목을 모르는 것(예전 백엔드 · 카드에 없는 것)은 이름 그대로 보인다.
      recipe_cards: [{ name: "missing_references", title: "빠진 참조 찾기", description: "", ask: "", origin: "pack" as const }],
    })),
    unityScheduleAdd: vi.fn(async () => SCHEDULE),
    unityScheduleAction: vi.fn(async () => ({ ok: true })),
  } as unknown as JarvisClient;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function flush() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)); });
}

function button(text: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((node) => node.textContent?.includes(text));
  if (!found) throw new Error(`no button: ${text}`);
  return found as HTMLButtonElement;
}

it("links an editor with one press and says nothing leaves this PC by default", async () => {
  await act(async () => root.render(<EditorBlock client={client} />));
  await flush();
  expect(container.textContent).toContain("밖으로 보낸 것 0건");
  const share = container.querySelector<HTMLInputElement>(".unity-share input");
  expect(share?.checked).toBe(false);

  await act(async () => button("에디터 잇기").click());
  await flush();
  expect(client.unityEditorLink).toHaveBeenCalledWith("E:/UnityProjects/Game", true);
  // 도움말에도 「이어짐」이라는 글자가 있다 — 그 프로젝트 줄에서 본다.
  expect(container.querySelector(".unity-link")?.textContent).toContain("이어짐");
  expect(container.textContent).toContain("창을 건드리지 않고");
});

it("says what linking writes before the press, keeps the package name small, and has a way out when it does not work", async () => {
  await act(async () => root.render(<EditorBlock client={client} />));
  await flush();
  const text = container.textContent ?? "";
  expect(text).toContain("Packages/manifest.json");
  expect(text).toContain("「풀기」를 누르면 그 줄을 원래대로 돌려 놓습니다.");
  // 부품 이름·버전은 제목 옆이 아니라 작은 글로.
  expect(container.querySelector(".unity-collab-head")?.textContent).not.toContain("MCP for Unity");
  const help = container.querySelector("[data-testid=unity-help]")!;
  expect(help.querySelector("summary")?.textContent).toBe("이었는데 안 될 때");
  expect(help.querySelectorAll("li")).toHaveLength(3);
  expect(help.textContent).toContain("Window › General › Console");
});

it("shows the unity window and only brings it forward on 「직접 하기」", async () => {
  await act(async () => root.render(<EditorBlock client={client} />));
  await flush();
  expect(container.querySelector(".unity-stage img")?.getAttribute("src")).toBe("blob:unity");
  expect(client.unityTakeOver).not.toHaveBeenCalled();
  await act(async () => button("직접 하기").click());
  await flush();
  expect(client.unityTakeOver).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("모델에게 보내지 않습니다");
});

it("sharing with the original maker is an explicit opt-in that names what is sent", async () => {
  await act(async () => root.render(<EditorBlock client={client} />));
  await flush();
  expect(container.textContent).toContain("api-prod.coplay.dev");
  const share = container.querySelector<HTMLInputElement>(".unity-share input")!;
  await act(async () => share.click());
  await flush();
  expect(client.unityShareWithCoplay).toHaveBeenCalledWith(true);
});

it("lists schedules with the number that got worse and can add one", async () => {
  await act(async () => root.render(<ScheduleBlock client={client} projects={["E:/UnityProjects/Game"]} />));
  await flush();
  expect(container.textContent).toContain("모델 없이");
  expect(container.querySelector(".unity-draft .pack-warn")?.textContent).toContain("끊긴 참조 2→5");
  // 고르기 칸은 파일 이름이 아니라 제목을 보인다(제목을 모르는 것은 이름 그대로) — 보내는 값은 이름이다.
  const options = [...container.querySelectorAll<HTMLOptionElement>("select[aria-label=레시피] option")];
  expect(options.map((node) => node.textContent)).toEqual(["빠진 참조 찾기", "texture_audit"]);
  expect(options.map((node) => node.value)).toEqual(["missing_references", "texture_audit"]);
  await act(async () => button("정기 점검 추가").click());
  await flush();
  expect(client.unityScheduleAdd).toHaveBeenCalledWith({ recipe: "missing_references", project: "E:/UnityProjects/Game", at: "03:00", days: "daily" });
  await act(async () => button("지금 한 번").click());
  await flush();
  expect(client.unityScheduleAction).toHaveBeenCalledWith("s1", "run");
});
