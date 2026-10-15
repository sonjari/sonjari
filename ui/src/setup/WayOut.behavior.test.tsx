// @vitest-environment jsdom
/**
 * 고른 모델을 그래픽카드에 다 못 올렸을 때 — 빨간 글 한 줄 대신 누를 수 있는 두 길 (2026-10-10 대표).
 *
 * 지키는 것: 닫는 것은 사람이 한다 · 다 닫아도 안 들어가면 「닫으세요」를 말하지 않는다 · 모르는 것은 모른다고 쓴다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { ApplyResult, CatalogModel, SetupApi, WayOutInfo } from "./setupApi";
import { ApplyLine } from "./SetupWizard";
import { WayOut, hasWayOut } from "./WayOut";
import { ModelSection } from "../workspace/ModelSection";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SMALLER = { model_key: "small-9b", name: "작은 모델 9B", num_ctx: 32768, needs_gb: 8.1, download_gb: 6.6,
  installed: true, weak_at: "처음 보는 코드 고치기" };

function info(over: Partial<WayOutInfo> = {}): WayOutInfo {
  return {
    model_key: "big-27b", model_name: "큰 모델 27B", needs_gb: 15.1,
    card: { total_gb: 16, used_gb: 2.6, free_gb: 13.4 },
    close: { apps: ["chrome", "Photoshop"], would_fit: true },
    smaller: SMALLER,
    ...over,
  };
}

async function mount(node: React.ReactNode): Promise<HTMLElement> {
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => { createRoot(host).render(node); });
  return host;
}

const button = (host: HTMLElement, way: "close" | "smaller") =>
  host.querySelector<HTMLButtonElement>(`[data-testid="way-out-${way}"] button`);

it("names what to close and offers the smaller model — two things a person can press", async () => {
  const onRetry = vi.fn();
  const onSmaller = vi.fn();
  const host = await mount(<WayOut info={info()} onRetry={onRetry} onSmaller={onSmaller} />);
  const close = host.querySelector('[data-testid="way-out-close"]')!;
  expect([...close.querySelectorAll("li")].map((li) => li.textContent)).toEqual(["chrome", "Photoshop"]);
  expect(close.textContent).toContain("Sonjari는 다른 프로그램을 끄지 않습니다");
  expect(host.textContent).toContain("큰 모델 27B");
  expect(host.textContent).toContain("작은 모델 9B");
  expect(host.textContent).toContain("처음 보는 코드 고치기");
  await act(async () => { button(host, "close")!.click(); });
  await act(async () => { button(host, "smaller")!.click(); });
  expect(onRetry).toHaveBeenCalledTimes(1);
  expect(onSmaller).toHaveBeenCalledWith(SMALLER);
  expect(button(host, "smaller")!.textContent).toBe("이 모델로 바꾸기");
});

it("does not tell a too-small card to close things", async () => {
  const host = await mount(<WayOut info={info({ card: { total_gb: 12, used_gb: 1, free_gb: 11 }, close: { apps: ["chrome"], would_fit: false } })}
    onRetry={() => undefined} onSmaller={() => undefined} />);
  const close = host.querySelector('[data-testid="way-out-close"]')!;
  expect(close.textContent).toContain("프로그램을 닫아도 들어가지 않습니다");
  expect(close.textContent).not.toContain("chrome");
  expect(button(host, "close")).toBeNull();
  expect(button(host, "smaller")).not.toBeNull();
});

it("says so when it could not tell whether closing would be enough", async () => {
  const host = await mount(<WayOut info={info({ card: { total_gb: null, used_gb: null, free_gb: null }, close: { apps: [], would_fit: null }, smaller: null })}
    onRetry={() => undefined} onSmaller={() => undefined} />);
  expect(host.textContent).toContain("닫으면 들어가는지는 재 보지 못했습니다");
  expect(host.querySelector(".wayout-bar")).toBeNull();
  expect(button(host, "close")).not.toBeNull();
  expect(host.textContent).toContain("더 작은 모델을 찾지 못했습니다");
  expect(button(host, "smaller")).toBeNull();
});

it("a smaller model that is not downloaded yet says how much it will download", async () => {
  const host = await mount(<WayOut info={info({ smaller: { ...SMALLER, installed: false } })} onSmaller={() => undefined} />);
  expect(button(host, "smaller")!.textContent).toBe("이 모델 받기");
  expect(host.textContent).toContain("받을 크기 6.6GB");
  expect(button(host, "close")).toBeNull();
});

it("both buttons wait while something is already being measured or downloaded", async () => {
  const host = await mount(<WayOut info={info()} busy onRetry={() => undefined} onSmaller={() => undefined} />);
  expect(button(host, "close")!.disabled).toBe(true);
  expect(button(host, "smaller")!.disabled).toBe(true);
});

it("shows the two ways only when the backend sent the material", () => {
  expect(hasWayOut(null)).toBe(false);
  expect(hasWayOut({ error: "model_not_fully_on_gpu" })).toBe(false);
  expect(hasWayOut({ error: "model_not_fully_on_gpu", way_out: {} })).toBe(false);
  expect(hasWayOut({ error: "model_not_fully_on_gpu", way_out: info() })).toBe(true);
});

it("the wizard shows the two ways for a model that did not fit, and the old line for other failures", async () => {
  const failed: ApplyResult = { ok: false, error: "model_not_fully_on_gpu", way_out: info() } as ApplyResult;
  const onRetry = vi.fn();
  const host = await mount(<ApplyLine pull={null} applying={false} applied={failed} onRetry={onRetry} onSmaller={() => undefined} />);
  expect(host.querySelector('[data-testid="way-out"]')).not.toBeNull();
  await act(async () => { button(host, "close")!.click(); });
  expect(onRetry).toHaveBeenCalledTimes(1);

  const bare = await mount(<ApplyLine pull={null} applying={false} applied={{ ok: false, error: "model_not_fully_on_gpu" } as ApplyResult} />);
  expect(bare.querySelector('[data-testid="way-out"]')).toBeNull();
  const other = await mount(<ApplyLine pull={null} applying={false}
    applied={{ ok: false, error: "model_did_not_generate", way_out: info() } as ApplyResult} />);
  expect(other.querySelector('[data-testid="way-out"]')).toBeNull();
});

it("in settings, going smaller applies that model with the window the backend picked", async () => {
  const row = (key: string, name: string, installed: boolean): CatalogModel => ({
    key, name, vendor: "시험", family: key, status: "verified", installed, fits: true, download_gb: 6.6,
    vram_gb: { "32768": 8.1, "65536": 9.4 }, contexts: [32768, 65536], recommended_ctx: 65536,
  } as unknown as CatalogModel);
  const applied: Array<[string, number | undefined]> = [];
  const api = {
    models: vi.fn(async () => ({ models: [row("big-27b", "큰 모델 27B", true), row("small-9b", "작은 모델 9B", true)],
      pulls: {}, selection: null, satellite: false })),
    profile: vi.fn(async () => ({ gpus: [{ index: 0, name: "시험 카드", vram_total_gb: 16, vram_used_gb: 2.6,
      driver: "", display_active: false, reserve_gb: 0.5, usable_gb: 15.5 }] })),
    apply: vi.fn(async (key: string, ctx?: number) => {
      applied.push([key, ctx]);
      return key === "big-27b" ? { ok: false, error: "model_not_fully_on_gpu", way_out: info() } : { ok: true };
    }),
  } as unknown as SetupApi;
  const host = await mount(<ModelSection api={api} />);
  const rowButton = () => [...host.querySelectorAll<HTMLLIElement>(".model-row")]
    .find((li) => li.textContent?.includes("큰 모델 27B"))!.querySelector<HTMLButtonElement>(".model-row-btn")!;
  await act(async () => { rowButton().click(); });
  expect(host.querySelector('[data-testid="way-out"]')).not.toBeNull();
  await act(async () => { button(host, "smaller")!.click(); });
  expect(applied[0][0]).toBe("big-27b");
  expect(applied[1]).toEqual(["small-9b", 32768]);
  expect(host.querySelector('[data-testid="way-out"]')).toBeNull();
});
