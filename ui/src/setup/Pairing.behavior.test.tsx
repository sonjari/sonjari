// @vitest-environment jsdom
/**
 * 짝짓기 화면 (2026-11-03 설계_짝짓기_모델자리 §2-1 · §3-2).
 *
 * 지키는 것: 집 PC 띠는 코드를 셋씩 띄워 크게 · 「허락」 단추 없이 [거절] 하나 · 시간이 지나면 사라진다 ·
 * (맥 쪽 찾기 → 숫자 6개는 11-04 부터 ModelPlace 의 연결 띠 — 그 시험은 ModelPlace.behavior.test) ·
 * 화면에 「위성 · 본체 · 포트 · 토큰」이 없다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { PairRequestBanner, PairedDevices } from "./Pairing";
import type { SetupApi } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

async function show(node: React.ReactNode) {
  await act(async () => { root.render(node); });
  await act(async () => { await Promise.resolve(); });
}
const byText = (text: string) => Array.from(host.querySelectorAll("button")).find((b) => b.textContent?.includes(text));
const BANNED = /위성|본체|포트|토큰/;

it("shows the code big on the home PC with only a reject button", async () => {
  const rejected: string[] = [];
  const api = {
    pairPending: async () => ({ requests: [{ request_id: "r1", child_name: "mac-mini", code: "482913", expires_at: Date.now() / 1000 + 300 }] }),
    pairReject: async (id: string) => { rejected.push(id); return { ok: true }; },
  } as unknown as SetupApi;
  await show(<PairRequestBanner api={api} />);
  expect(host.querySelector(".pair-code")?.textContent).toBe("482 913");
  expect(host.textContent).toContain("mac-mini");
  expect(byText("허락")).toBeUndefined();
  await act(async () => { byText("거절")!.click(); });
  expect(rejected).toEqual(["r1"]);
  expect(host.textContent).not.toMatch(BANNED);
});

it("hides an expired code", async () => {
  const api = { pairPending: async () => ({ requests: [{ request_id: "r1", child_name: "m", code: "111111", expires_at: Date.now() / 1000 - 1 }] }) } as unknown as SetupApi;
  await show(<PairRequestBanner api={api} />);
  expect(host.textContent).toBe("");
});

it("lists borrowing devices on the home PC and cuts one", async () => {
  let devices = [{ device_id: "d1", name: "mac-mini", paired_at: 1, last_used: 0 }];
  const api = {
    pairDevices: async () => ({ devices }),
    pairRevoke: async () => { devices = []; return { ok: true }; },
  } as unknown as SetupApi;
  await show(<PairedDevices api={api} />);
  expect(host.textContent).toContain("mac-mini");
  await act(async () => { byText("끊기")!.click(); });
  await act(async () => { await Promise.resolve(); });
  expect(host.textContent).toBe("");
});
