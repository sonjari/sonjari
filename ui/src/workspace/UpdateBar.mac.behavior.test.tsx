// @vitest-environment jsdom
/**
 * 맥 「새 버전이 있습니다 → 지금 업데이트」 (2026-11-22 · 설계_맥앱안업데이트_2026-11-22.ko.md).
 *
 * 전에는 막대가 `kind: "mac"` 을 몰라 위성 갈래로 그려졌고(mine/theirs 가 비어 「undefined」 자리), 앱 꾸러미 설치
 * (`app_update_install`)를 부르는 화면이 하나도 없었다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import { MAC_UPDATE_KEY, UpdateBar } from "./UpdateBar";

const invoke = vi.fn();
vi.mock("../backend", () => ({ isTauri: () => true }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args?: unknown) => invoke(cmd, args) }));

let root: Root;
let container: HTMLDivElement;
let client: JarvisClient;

const appUpdate = {
  ok: true, enabled: true, kind: "mac", available: true, road: "app", mine: "0.4.50", theirs: "0.4.51",
  app: { available: true, ready: true, version: "0.4.51", reason: "" },
  python: { available: true, ready: true, build: "bbbbbbbbbbbb" },
};

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  window.localStorage.clear();
  invoke.mockReset();
  client = { checkUpdate: vi.fn(async () => appUpdate), applyUpdate: vi.fn(), getHealth: vi.fn() } as unknown as JarvisClient;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

const button = (text: string) => [...container.querySelectorAll("button")].find((b) => b.textContent === text);

it("맥 응답이면 판 번호로 「새 버전이 있습니다」와 지금 업데이트 버튼을 보인다", async () => {
  await act(async () => root.render(<UpdateBar client={client} />));
  expect(container.textContent).toContain("새 버전이 있습니다");
  expect(container.textContent).toContain("0.4.50 → 0.4.51");
  expect(container.textContent).not.toContain("undefined");
  expect(button("지금 업데이트")).toBeTruthy();
});

it("누르면 흐린 덮개를 띄우고 앱 꾸러미 설치를 부른다 · 누르기 전 판을 적어 둔다", async () => {
  invoke.mockReturnValue(new Promise(() => undefined)); // 성공하면 앱이 꺼진다 — 응답이 오지 않는다
  await act(async () => root.render(<UpdateBar client={client} />));
  await act(async () => { button("지금 업데이트")!.click(); });
  expect(invoke).toHaveBeenCalledWith("app_update_install", undefined);
  expect(container.querySelector(".updating-overlay")).toBeTruthy();
  expect(JSON.parse(window.localStorage.getItem(MAC_UPDATE_KEY) || "{}")).toEqual({ from: "0.4.50", to: "0.4.51", road: "app" });
});

it("설치가 오류를 돌려주면 덮개를 걷고 까닭을 말한다 · 적어 둔 판을 지운다", async () => {
  invoke.mockRejectedValue("꾸러미를 바꾸지 못했습니다: signature mismatch");
  await act(async () => root.render(<UpdateBar client={client} />));
  await act(async () => { button("지금 업데이트")!.click(); });
  expect(container.querySelector(".updating-overlay")).toBeNull();
  expect(container.textContent).toContain("업데이트하지 못했습니다");
  expect(container.textContent).toContain("signature mismatch");
  expect(button("다시 시도")).toBeTruthy();
  expect(window.localStorage.getItem(MAC_UPDATE_KEY)).toBeNull();
});

it("다시 켜진 뒤 판이 바뀌었으면 「업데이트했습니다」를 한 번 말한다", async () => {
  window.localStorage.setItem(MAC_UPDATE_KEY, JSON.stringify({ from: "0.4.50", to: "0.4.51", road: "app" }));
  client.checkUpdate = vi.fn(async () => ({ ok: true, enabled: true, kind: "mac", available: false, road: "", mine: "0.4.51", theirs: "" })) as never;
  await act(async () => root.render(<UpdateBar client={client} />));
  expect(container.textContent).toContain("업데이트했습니다");
  expect(container.textContent).toContain("0.4.50 → 0.4.51");
  expect(window.localStorage.getItem(MAC_UPDATE_KEY)).toBeNull();
});

it("다시 켜졌는데 옛 판이면 「업데이트하지 못했습니다」라고 말한다(조용히 넘어가지 않는다)", async () => {
  window.localStorage.setItem(MAC_UPDATE_KEY, JSON.stringify({ from: "0.4.50", to: "0.4.51", road: "app" }));
  client.checkUpdate = vi.fn(async () => ({ ...appUpdate, mine: "0.4.50" })) as never;
  await act(async () => root.render(<UpdateBar client={client} />));
  expect(container.textContent).toContain("업데이트하지 못했습니다");
  expect(container.textContent).toContain("0.4.50");
});

it("받을 수 없는 까닭이 있으면 버튼 없이 까닭을 보인다", async () => {
  client.checkUpdate = vi.fn(async () => ({
    ...appUpdate, app: { available: true, ready: false, version: "0.4.51", reason: "파이썬 묶음을 먼저 업데이트해야 합니다" },
  })) as never;
  await act(async () => root.render(<UpdateBar client={client} />));
  expect(container.textContent).toContain("파이썬 묶음을 먼저");
  expect(button("지금 업데이트")).toBeUndefined();
});

it("파이썬만 바뀐 판은 받기 갈래로 가고 build 가 바뀌면 「업데이트했습니다」", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "Date"] });
  client.checkUpdate = vi.fn(async () => ({
    ok: true, enabled: true, kind: "mac", available: true, road: "python", mine: "aaaaaaaa", theirs: "bbbbbbbb",
    app: { available: false }, python: { available: true, ready: true, build: "bbbbbbbbbbbb" },
  })) as never;
  client.applyUpdate = vi.fn(async () => ({ ok: true, applied: true })) as never;
  client.getHealth = vi.fn(async () => ({ build: "bbbbbbbbbbbb" })) as never;
  await act(async () => root.render(<UpdateBar client={client} />));
  await act(async () => { button("지금 업데이트")!.click(); });
  expect(invoke).not.toHaveBeenCalled();
  expect(client.applyUpdate).toHaveBeenCalled();
  await act(async () => { await vi.advanceTimersByTimeAsync(5_100); });
  expect(container.textContent).toContain("업데이트했습니다");
});

it("받을 것이 없으면 아무것도 안 그린다", async () => {
  client.checkUpdate = vi.fn(async () => ({ ok: true, enabled: true, kind: "mac", available: false, road: "", mine: "0.4.50", theirs: "" })) as never;
  await act(async () => root.render(<UpdateBar client={client} />));
  expect(container.textContent).toBe("");
});
