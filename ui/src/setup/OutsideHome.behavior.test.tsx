// @vitest-environment jsdom
/**
 * 밖에서도 쓰기 — Outside home 체크 목록 (설계_밖에서도쓰기_테일스케일_2026-11-04 §2 · §4).
 *
 * 지키는 것:
 * - 맥: 짝지은 뒤 한 번 권한다([지금 하기] [나중에]). 「나중에」면 작은 한 줄로 남고 다시 조르지 않는다.
 * - 지금 할 차례인 기기 칸에만 단추가 있다. 그쪽 차례면 「그쪽 차례」 글자뿐(이 기기에서 남의 설치를 누를 수 없다).
 * - [설치 열기] 는 백엔드가 준 공식 페이지를 열기만 한다. 단계는 백엔드 stage 를 따른다(누른다고 ✓ 가 되지 않는다).
 * - 집 PC 는 맥이 시작하기 전(idle)에는 아무것도 안 띄우고, 문 여는 단계에서 윈도우 방화벽 안내 한 줄.
 * - 화면에 「위성 · 본체 · 포트 · 토큰 · 노드」 낱말이 없다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../platform", () => ({ isMac: true }));
const opened: string[] = [];
vi.mock("../backend", () => ({ openExternalUrl: async (url: string) => { opened.push(url); } }));

import { OutsideHomeMac, OutsideHomePc } from "./OutsideHome";
import type { OutsideSide, OutsideStatus, SetupApi } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const side = (over: Partial<OutsideSide> = {}): OutsideSide =>
  ({ installed: true, signed_in: true, state: "Running", tailnet_id: "T-ONE", dns_name: "x.example.ts.net", ...over });
const NONE = side({ installed: false, signed_in: false, state: "NotInstalled", tailnet_id: "" });
const BANNED = /위성|본체|포트|토큰|노드/;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); opened.length = 0; });
afterEach(() => { act(() => root.unmount()); host.remove(); });

async function show(node: React.ReactNode) {
  await act(async () => { root.render(node); });
  await act(async () => { await Promise.resolve(); });
}
const byText = (text: string) => Array.from(host.querySelectorAll("button")).find((b) => b.textContent?.includes(text));

function api(status: OutsideStatus, steps: string[] = [], answer: Record<string, unknown> = { ok: true }) {
  return {
    outsideStatus: async () => status,
    outsideStep: async (step: string) => { steps.push(step); return answer; },
  } as unknown as SetupApi;
}

const MAC_BASE: OutsideStatus = { role: "mac", stage: "install", reason: "not_installed_mac", mac: NONE, pc: side(),
  other_name: "HOME-PC", offer: false, later: false, started: true, pc_answered: true };

it("offers once after pairing and remembers 'later' as one small line", async () => {
  const steps: string[] = [];
  await show(<OutsideHomeMac api={api({ ...MAC_BASE, offer: true, started: false }, steps)} />);
  expect(host.textContent).toContain("집 밖에서도 이 PC 를 쓰시겠어요?");
  await act(async () => { byText("나중에")!.click(); });
  expect(steps).toEqual(["later"]);

  await show(<OutsideHomeMac api={api({ ...MAC_BASE, offer: false, later: true, started: false })} />);
  expect(host.textContent).toContain("Outside home: Off");
  expect(host.querySelector(".outside-grid")).toBeNull();          // 목록을 펴 놓고 조르지 않는다
})

it("puts the install button only in this Mac's cell and opens the official page", async () => {
  const steps: string[] = [];
  await show(<OutsideHomeMac api={api(MAC_BASE, steps, { ok: true, url: "https://tailscale.com/download/mac" })} />);
  const buttons = Array.from(host.querySelectorAll(".outside-cell-btn"));
  expect(buttons.map((b) => b.textContent)).toEqual(["설치 열기"]);
  expect(host.querySelector(".outside-cell.is-done")?.textContent).toContain("설치됨");   // 집 PC 칸은 ✓
  await act(async () => { byText("설치 열기")!.click(); });
  await act(async () => { await Promise.resolve(); });
  expect(steps).toEqual(["install"]);
  expect(opened).toEqual(["https://tailscale.com/download/mac"]);
  expect(host.textContent).not.toMatch(BANNED);
});

it("shows 'their turn' instead of a button when the home PC must act", async () => {
  await show(<OutsideHomeMac api={api({ ...MAC_BASE, stage: "login", reason: "sign_in_pc", mac: side(),
    pc: side({ signed_in: false, state: "NeedsLogin", tailnet_id: "" }) })} />);
  expect(host.querySelectorAll(".outside-cell-btn").length).toBe(0);
  expect(host.textContent).toContain("그쪽 차례");
  expect(host.textContent).toContain("HOME-PC 에서 Tailscale 에 로그인해 주세요");
});

it("asks to sign one device in again when the accounts differ", async () => {
  const steps: string[] = [];
  await show(<OutsideHomeMac api={api({ ...MAC_BASE, stage: "same_account", reason: "different_account", mac: side(),
    pc: side({ tailnet_id: "T-TWO" }) }, steps)} />);
  expect(host.textContent).toContain("서로 다른 계정");
  await act(async () => { byText("다른 계정으로 다시 로그인")!.click(); });
  expect(steps).toEqual(["switch_account"]);
});

it("collapses to one line when done", async () => {
  await show(<OutsideHomeMac api={api({ ...MAC_BASE, stage: "done", reason: "", mac: side() })} />);
  expect(host.textContent).toContain("Outside home");
  expect(host.textContent).toContain("카페나 회사에서도 이 PC 를 씁니다.");
  expect(host.querySelector(".outside-grid")).toBeNull();
});

it("stays hidden on the home PC until a Mac starts, then shows the firewall line at the door step", async () => {
  await show(<OutsideHomePc api={api({ role: "pc", stage: "idle", reason: "", mac: null, pc: side() })} />);
  expect(host.textContent).toBe("");
  await show(<OutsideHomePc api={api({ role: "pc", stage: "door", reason: "", mac: side(), pc: side(), other_name: "Mac mini" })} />);
  expect(host.textContent).toContain("Mac mini");
  expect(host.textContent).toContain("액세스를 허용하시겠습니까?");
  expect(host.textContent).not.toMatch(BANNED);
});
