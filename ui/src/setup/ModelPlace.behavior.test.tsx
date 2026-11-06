// @vitest-environment jsdom
/**
 * 모델 자리 [Mac | Satellite] + 연결 띠 (2026-11-04 대표 설계 · 설계_짝짓기_모델자리 §9).
 *
 * 지키는 것:
 * - 단추는 한 묶음 둘 — 「Mac」 · 「Satellite」(위성은 영어로만). 고른 쪽만 is-on. 이름표 · 설명 줄 · 체크 표시 없음.
 * - Satellite 면 연결 띠 — 연결됨(Connected · 꽉 찬 실) · 끊김(PC not found · [Use Mac] [Retry]) · 찾는 중 · 짝 코드(숫자 6칸).
 * - 구슬은 실제 부르기 사건(HOME_LLM_EVENT)에만 — 사건 없이는 구슬이 없다.
 * - 집 PC 를 모르는 맥에서 Satellite → 찾기 → 짝 코드 → 연결. 틀리면 남은 횟수.
 * - 일하는 중이면 「끝난 뒤」 · 집 PC 모델은 이 기기 것만 바뀐다.
 * - 화면에 「위성 · 본체 · 포트 · 토큰」 낱말이 없다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../platform", () => ({ isMac: true }));

import { HOME_LLM_EVENT, ModelPlaceBar } from "./ModelPlace";
import type { ModelPlaceView, SetupApi } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const HOME: ModelPlaceView = {
  place: "home_pc", home_known: true, paired: true, home_host: "HOME-PC", home_gpu: "RTX 3090 24GB",
  home_model: "swift:27b", home_model_chosen_here: false, chat_model: "swift:27b", num_ctx: 131072, satellite: true,
  home: { reachable: true, models: [
    { tag: "swift:27b", gb: 14.1, family: "qwen3", params: "27B", quant: "IQ3_S" },
    { tag: "ornith:9b", gb: 6.7, family: "qwen3", params: "9B", quant: "Q4_K_M" },
  ] },
};
const MAC: ModelPlaceView = { ...HOME, place: "this_pc", satellite: false, chat_model: "qwen3.5:9b" };

let host: HTMLDivElement;
let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

async function show(api: SetupApi, onChanged?: () => void) {
  await act(async () => { root.render(<ModelPlaceBar api={api} onChanged={onChanged} />); });
  await act(async () => { await Promise.resolve(); });
}
const radio = (label: string) => Array.from(host.querySelectorAll<HTMLButtonElement>('[role="radio"]')).find((b) => b.textContent === label);
const byText = (text: string) => Array.from(host.querySelectorAll("button")).find((b) => b.textContent?.includes(text));
const BANNED = /위성|본체|포트|토큰/;

it("is absent on a PC that cannot borrow (no home PC, no pairing)", async () => {
  await show({ modelPlace: async () => ({ ...MAC, home_known: false }) } as unknown as SetupApi);
  expect(host.textContent).toBe("");
});

it("is one small [Mac | Satellite] pair — no label, no help line, no check mark", async () => {
  await show({ modelPlace: async () => MAC } as unknown as SetupApi);
  const buttons = Array.from(host.querySelectorAll('[role="radio"]')).map((b) => b.textContent);
  expect(buttons).toEqual(["Mac", "Satellite"]);
  expect(radio("Mac")!.className).toContain("is-on");
  expect(radio("Satellite")!.className).not.toContain("is-on");
  expect(host.textContent).not.toContain("모델 자리");
  expect(host.textContent).not.toContain("집 PC 로 돌리려면");
  expect(host.querySelector("svg.lucide-check")).toBeNull();
  expect(host.querySelector(".place-link")).toBeNull();
});

it("switches place at once and tells the caller to reload", async () => {
  const calls: string[] = [];
  const onChanged = vi.fn();
  let view = HOME;
  const api = {
    modelPlace: async () => view,
    setModelPlace: async (place: "this_pc" | "home_pc") => { calls.push(place); view = { ...view, place, chat_model: "qwen3.5:9b" }; return { ok: true, pending: false, ...view }; },
  } as unknown as SetupApi;
  await show(api, onChanged);
  expect(radio("Satellite")?.getAttribute("aria-checked")).toBe("true");
  expect(host.textContent).toContain("Swift 27B");
  await act(async () => { radio("Mac")!.click(); });
  expect(calls).toEqual(["this_pc"]);
  expect(onChanged).toHaveBeenCalled();
  expect(radio("Mac")?.getAttribute("aria-checked")).toBe("true");
  expect(host.textContent).not.toContain("Ornith"); // Mac 자리면 집 PC 목록을 늘어놓지 않는다
  expect(host.textContent).not.toMatch(BANNED);
});

it("shows a connected band — Mac ━━ HOME-PC · card · model · Connected", async () => {
  await show({ modelPlace: async () => HOME } as unknown as SetupApi);
  const band = host.querySelector(".place-link")!;
  expect(band.className).toContain("is-connected");
  expect(band.textContent).toContain("Mac");
  expect(band.textContent).toContain("HOME-PC");
  expect(band.textContent).toContain("RTX 3090 24GB · Swift 27B");
  expect(band.textContent).toContain("Connected");
});

it("moves the bead only on a real model call — out on start, back on end", async () => {
  // 실은 너비를 재야 그린다 — jsdom 은 0 이라 실 자리에만 너비를 준다.
  const original = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement) {
    return this.classList.contains("place-wire") ? ({ width: 160, height: 14 } as DOMRect) : original.call(this);
  };
  try {
    await show({ modelPlace: async () => HOME } as unknown as SetupApi);
    expect(host.querySelector(".place-thread")).not.toBeNull();
    expect(host.querySelector(".wns-bead")).toBeNull(); // 부르기 전엔 구슬이 없다 — 꾸밈으로 돌리지 않는다
    await act(async () => { window.dispatchEvent(new CustomEvent(HOME_LLM_EVENT, { detail: { phase: "start" } })); });
    expect(host.querySelector(".wns-bead")?.getAttribute("class")).toContain("wns-bead-go");
    await act(async () => { window.dispatchEvent(new CustomEvent(HOME_LLM_EVENT, { detail: { phase: "end" } })); });
    expect(host.querySelector(".wns-bead")?.getAttribute("class")).toContain("wns-bead-back");
  } finally {
    HTMLElement.prototype.getBoundingClientRect = original;
  }
});

it("says the change waits for the running job", async () => {
  const api = {
    modelPlace: async () => HOME,
    setModelPlace: async () => ({ ok: true, pending: true, ...HOME }),
  } as unknown as SetupApi;
  await show(api);
  await act(async () => { radio("Mac")!.click(); });
  expect(host.textContent).toContain("끝난 뒤 바뀝니다");
});

it("picks a home PC model for this device only", async () => {
  const picked: string[] = [];
  const api = {
    modelPlace: async () => HOME,
    setHomeModel: async (tag: string) => { picked.push(tag); return { ok: true, ...HOME, chat_model: tag, home_model_chosen_here: true }; },
  } as unknown as SetupApi;
  await show(api);
  expect(host.textContent).toContain("집 PC 의 선택");
  await act(async () => { byText("Ornith 9B")!.click(); });
  expect(picked).toEqual(["ornith:9b"]);
  expect(byText("Ornith 9B")?.getAttribute("aria-selected")).toBe("true");
  expect(host.textContent).not.toMatch(BANNED);
});

it("breaks the thread when the home PC cannot be seen — PC not found · [Use Mac] [Retry]", async () => {
  const calls: string[] = [];
  let loads = 0;
  const api = {
    modelPlace: async () => { loads += 1; return { ...HOME, home: { reachable: false, models: [] } }; },
    setModelPlace: async (place: string) => { calls.push(place); return { ok: true, pending: false, ...MAC }; },
  } as unknown as SetupApi;
  await show(api);
  const band = host.querySelector(".place-link")!;
  expect(band.className).toContain("is-down");
  expect(band.textContent).toContain("PC not found");
  expect(host.querySelector(".place-models")).toBeNull();
  const before = loads;
  await act(async () => { byText("Retry")!.click(); });
  expect(loads).toBe(before + 1);
  await act(async () => { byText("Use Mac")!.click(); });
  expect(calls).toEqual(["this_pc"]);
});

it("pairs from Satellite on a Mac that does not know a home PC yet — find → code → connected", async () => {
  const calls: string[] = [];
  let view: ModelPlaceView = { ...MAC, home_known: false, paired: false, home_host: "" };
  const home = { address: "192.0.2.10:8091", name: "HOME-PC", gpu: "RTX 3090 24GB", version: "x", remembered: false };
  const api = {
    modelPlace: async () => view,
    pairDiscover: async () => { calls.push("discover"); return { found: [home] }; },
    pairStart: async () => { calls.push("start"); return { ok: true, expires_in: 300 }; },
    pairFinish: async (code: string) => {
      calls.push(`finish:${code}`);
      if (code !== "482913") return { ok: false, error: "wrong_code", tries_left: 2 };
      view = HOME;
      return { ok: true };
    },
  } as unknown as SetupApi;
  const sat = vi.fn();
  await act(async () => { root.render(<ModelPlaceBar api={api} onSatellite={sat} />); });
  await act(async () => { await Promise.resolve(); });
  expect(sat).toHaveBeenLastCalledWith(false);
  await act(async () => { radio("Satellite")!.click(); });
  await act(async () => { await Promise.resolve(); });
  expect(sat).toHaveBeenLastCalledWith(true); // 짝짓는 동안에도 Satellite — 칩 창은 Mac 목록을 숨긴다
  expect(host.querySelector(".place-link")?.className).toContain("is-code");
  expect(host.textContent).toContain("Enter the code on your PC");
  expect(host.querySelectorAll(".place-code-cell")).toHaveLength(6);
  const input = host.querySelector<HTMLInputElement>(".place-code input")!;
  const type = async (value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => { await Promise.resolve(); });
  };
  await type("111111");
  expect(host.textContent).toContain("2번 더");
  await type("482913");
  expect(calls).toEqual(["discover", "start", "finish:111111", "finish:482913"]);
  expect(host.querySelector(".place-link")?.className).toContain("is-connected");
  expect(host.textContent).not.toMatch(BANNED);
});

it("says PC not found when nothing answers on the network", async () => {
  const api = {
    modelPlace: async () => ({ ...MAC, home_known: false }),
    pairDiscover: async () => ({ found: [] }),
  } as unknown as SetupApi;
  await show(api);
  await act(async () => { radio("Satellite")!.click(); });
  await act(async () => { await Promise.resolve(); });
  expect(host.textContent).toContain("PC not found");
  expect(host.textContent).toContain("같은 와이파이");
  await act(async () => { byText("Use Mac")!.click(); });
  expect(radio("Mac")?.getAttribute("aria-checked")).toBe("true");
});

it("pairs instead of the old direct route on a Mac set up the old way (knows the home PC but never paired)", async () => {
  // 11-04 실제 시험: 옛 설정 맥은 집 PC 를 「안다」(home_known) 고 보지만 짝은 없다 — Satellite · Retry 는 짝짓기로 가야 한다.
  const calls: string[] = [];
  const api = {
    modelPlace: async () => ({ ...MAC, paired: false }),
    setModelPlace: async (place: string) => { calls.push(`place:${place}`); return { ok: true, pending: false, ...HOME, paired: false }; },
    pairDiscover: async () => { calls.push("discover"); return { found: [] }; },
  } as unknown as SetupApi;
  await show(api);
  await act(async () => { radio("Satellite")!.click(); });
  await act(async () => { await Promise.resolve(); });
  expect(calls).toEqual(["discover"]);
  await act(async () => { byText("Retry")!.click(); });
  await act(async () => { await Promise.resolve(); });
  expect(calls).toEqual(["discover", "discover"]);
});

it("marks the home PC default and tells same-name models apart by source (11-04)", async () => {
  const twinA = "hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF:Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf";
  const twinB = "hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF:IQ3_S";
  const view = { ...HOME, chat_model: twinA, home: { reachable: true, models: [
    { tag: twinA, gb: 13.0, family: "qwen35", params: "27B", quant: "BF16", home_default: true },
    { tag: twinB, gb: 11.8, family: "qwen35", params: "27B", quant: "IQ3_S" },
    { tag: "qwen3.5:9b", gb: 6.6, family: "qwen35", params: "9B", quant: "Q4_K_M" },
  ] } };
  await show({ modelPlace: async () => view } as unknown as SetupApi);
  const rows = Array.from(host.querySelectorAll(".place-model"));
  expect(rows[0].textContent).toContain("집 PC 기본");
  expect(rows[0].querySelector(".place-model-source")?.textContent).toBe("ukisai · IQ3_S-mtp");
  expect(rows[1].querySelector(".place-model-source")?.textContent).toBe("ukisai · IQ3_S");
  expect(rows[2].querySelector(".place-model-source")).toBeNull(); // 이름이 하나뿐이면 꼬리를 달지 않는다
  expect(rows[2].textContent).not.toContain("집 PC 기본");
});

it("names the path in the band and gives the reason with one fix button when away from home (outside §2-3)", async () => {
  await show({ modelPlace: async () => ({ ...HOME, home: { ...HOME.home!, via: "tailnet" } }) } as unknown as SetupApi);
  expect(host.textContent).toContain("Connected · Tailscale");

  const steps: string[] = [];
  await show({
    modelPlace: async () => ({ ...HOME, home: { reachable: false, models: [], why: "tailscale_off" } }),
    outsideStep: async (step: string) => { steps.push(step); return { ok: true }; },
  } as unknown as SetupApi);
  expect(host.textContent).toContain("PC not found");
  expect(host.textContent).toContain("Tailscale 이 꺼져 있습니다");
  await act(async () => { byText("Turn on")!.click(); });
  expect(steps).toEqual(["turn_on"]);
  expect(byText("Use Mac")).toBeTruthy();                         // 혼자 Mac 으로 넘기지 않는다 — 사람이 고른다
});
