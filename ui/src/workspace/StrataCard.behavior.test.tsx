// @vitest-environment jsdom
/**
 * 설정 › 모델 › Strata 카드 · 설정 › 연결 › 클로드 다시 켜기 카드 (2026-11-13).
 * 지키는 것: 손님 PC 에선 안 보인다 · 바꾸기는 한 번 묻고 나서만 · 일하는 중 거절은 문구로 · 포기면 다시 켜기 ·
 * 클로드 카드는 옛 연결일 때만 · 단추는 기존 「닫고 · 잇고 · 다시 켜기」 창을 연다(묻기 전엔 아무것도 안 끈다).
 */
import strataSrc from "./StrataCard.tsx?raw";
import freshSrc from "./ClaudeFreshCard.tsx?raw";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import en from "../i18n/en.json";
import type { SetupApi } from "../setup/setupApi";
import type { McpFreshness, StrataStatus, StrataSwitchResult } from "../types";
import { ClaudeFreshCard } from "./ClaudeFreshCard";
import { StrataCard } from "./StrataCard";

function status(extra: Partial<StrataStatus> = {}): StrataStatus {
  return {
    available: true, selected: true, strata: true, bridge: true, gave_up: false, last_error: "",
    model: "strata", context: "128K", ...extra,
  };
}

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
});

function strataClient(s: StrataStatus, switched: StrataSwitchResult = { ok: true, restarting: true }) {
  return {
    strataStatus: vi.fn(async () => s),
    strataSwitch: vi.fn(async (_to: "strata" | "ollama") => switched),
    strataRetry: vi.fn(async () => ({ ...s, gave_up: false })),
  };
}

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((b) => (b.textContent ?? "").trim() === label);
  if (!found) throw new Error(`단추 없음: ${label} — ${container.textContent}`);
  return found as HTMLButtonElement;
}

async function click(label: string) {
  await act(async () => { button(label).click(); });
}

it("Strata 가 없는 PC 에선 아무것도 그리지 않는다", async () => {
  const client = strataClient(status({ available: false }));
  await act(async () => { root.render(<StrataCard client={client} />); });
  expect(client.strataStatus).toHaveBeenCalled();
  expect(container.innerHTML).toBe("");
});

it("Strata 를 쓰는 중이면 그 갈래에 불이 켜지고, 27B 로 바꾸기는 한 번 물은 뒤에만 부른다", async () => {
  const client = strataClient(status());
  await act(async () => { root.render(<StrataCard client={client} />); });

  const active = container.querySelector(".strata-lane.is-active");
  expect(active?.textContent).toContain("Strata");
  expect(active?.textContent).toContain("사용 중");
  expect(active?.querySelector(".gh-dot.is-on")).not.toBeNull();

  await click("3D 작업 — 27B 로 바꾸기");
  expect(client.strataSwitch).not.toHaveBeenCalled();
  expect(container.textContent).toContain("손자리가 1~2분 다시 켜집니다. 맥 손자리도 그동안 쉽니다.");

  await click("그대로 두기");
  expect(client.strataSwitch).not.toHaveBeenCalled();

  await click("3D 작업 — 27B 로 바꾸기");
  await click("27B 로 바꾸기");
  expect(client.strataSwitch).toHaveBeenCalledWith("ollama");
  expect(container.textContent).toContain("바꾸는 중입니다.");
});

it("27B 를 쓰는 중이면 Strata 로 바꾸기를 권하고 strata 로 부른다", async () => {
  const client = strataClient(status({ selected: false, strata: false, bridge: false }));
  await act(async () => { root.render(<StrataCard client={client} />); });
  expect(container.querySelector(".strata-lane.is-active")?.textContent).toContain("27B");
  await click("Strata 로 바꾸기");
  await click("Strata 로 바꾸기");
  expect(client.strataSwitch).toHaveBeenCalledWith("strata");
});

it("일하는 중이라 거절되면 그 까닭을 말한다", async () => {
  const client = strataClient(status(), { ok: false, error: "busy" });
  await act(async () => { root.render(<StrataCard client={client} />); });
  await click("3D 작업 — 27B 로 바꾸기");
  await click("27B 로 바꾸기");
  expect(container.textContent).toContain("손자리가 일하는 중입니다. 끝난 뒤에 바꿔 주세요.");
});

it("켜는 중에는 불 대신 기다림 점 · 포기면 마지막 오류와 다시 켜기", async () => {
  const starting = strataClient(status({ strata: false }));
  await act(async () => { root.render(<StrataCard client={starting} />); });
  expect(container.querySelector(".gh-dot.is-wait")).not.toBeNull();
  expect(container.textContent).toContain("켜는 중");

  const gaveUp = strataClient(status({ strata: false, gave_up: true, last_error: "10분 안에 3번 꺼졌습니다" }));
  await act(async () => { root.render(<StrataCard client={gaveUp} />); });
  await act(async () => { await Promise.resolve(); });
  expect(container.textContent).toContain("10분 안에 3번 꺼졌습니다");
  await click("다시 켜기");
  expect(gaveUp.strataRetry).toHaveBeenCalled();
});

function freshClient(f: Partial<McpFreshness>) {
  return { claudeMcpFreshness: vi.fn(async () => ({ stale: false, app_build: "a", mcp_builds: [], ...f })) };
}

it("클로드 카드는 옛 연결일 때만 나타난다", async () => {
  const api = { connectRestartDesktop: vi.fn() } as unknown as SetupApi;
  await act(async () => { root.render(<ClaudeFreshCard client={freshClient({ stale: false })} setupApi={api} />); });
  expect(container.innerHTML).toBe("");
});

it("옛 연결이면 다시 켜기 단추가 기존 확인 창을 열고, 묻기 전엔 아무것도 끄지 않는다", async () => {
  const connectRestartDesktop = vi.fn();
  const api = { connectRestartDesktop } as unknown as SetupApi;
  await act(async () => {
    root.render(<ClaudeFreshCard client={freshClient({ stale: true, mcp_builds: ["old"] })} setupApi={api} />);
  });
  expect(container.textContent).toContain("클로드가 손자리의 옛 연결을 쓰고 있습니다");
  await click("클로드 다시 켜기");
  expect(container.querySelector("[role=dialog]")).not.toBeNull();
  expect(container.textContent).toContain("닫고 · 잇고 · 다시 켜기");
  expect(connectRestartDesktop).not.toHaveBeenCalled();
});

it("두 카드의 문구는 모두 영어 번역이 있다", () => {
  const dict = en as Record<string, string>;
  for (const [file, src] of [["StrataCard.tsx", strataSrc], ["ClaudeFreshCard.tsx", freshSrc]] as const) {
    const keys = [...src.matchAll(/\bt\("([^"]+)"/g)].map((m) => m[1]);
    expect(keys.length).toBeGreaterThan(3);
    for (const key of keys) expect(dict[key], `${file}: ${key}`).toBeTruthy();
  }
});
