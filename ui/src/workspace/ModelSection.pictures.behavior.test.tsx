// @vitest-environment jsdom
/**
 * 설정 › 모델 — 지금 쓰는 모델의 그림 읽기를 켜고 끈다 (2026-10-12).
 *
 * 지키는 약속:
 * - 지금 쓰는 모델이고 그림을 끌 수 있는 모델일 때만 줄이 보인다.
 * - 같은 모델 · 지금 쓰는 대화 길이 그대로 다시 올린다. 끄면 `eyes: false`, 켜면 `eyes: true` 가 간다.
 * - 옛 선택 기록(그림을 읽는지 적는 칸이 없다)은 모델 이름이 「글만 읽는」 이름인지로 본다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { CatalogModel, SetupApi } from "../setup/setupApi";
import { ModelSection } from "./ModelSection";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const hosts: HTMLElement[] = [];
afterEach(() => {
  hosts.splice(0).forEach((host) => host.remove());
});

async function mount(node: React.ReactNode): Promise<HTMLElement> {
  const host = document.createElement("div");
  document.body.appendChild(host);
  hosts.push(host);
  await act(async () => { createRoot(host).render(node); });
  return host;
}

const row = (key: string, name: string, extra: Partial<CatalogModel> = {}): CatalogModel => ({
  key, name, vendor: "시험", family: key, status: "verified", installed: true, fits: true, download_gb: 11.4,
  vram_gb: { "49152": 14.2, "65536": 14.6 }, contexts: [49152, 65536], recommended_ctx: 49152, ...extra,
} as unknown as CatalogModel);

const WITH_EYES = row("small-27b", "작은 27B", {
  pictures_optional: true, text_only_tag: "sonjari-text-small-27b", text_only_saves_gb: 1.1,
});

function apiWith(selection: Record<string, unknown> | null, models: CatalogModel[] = [WITH_EYES, row("other-9b", "다른 9B")]) {
  const applied: Array<[string, number | undefined, boolean | undefined]> = [];
  const api = {
    models: vi.fn(async () => ({ models, pulls: {}, selection, satellite: false })),
    profile: vi.fn(async () => ({ gpus: [{ index: 0, name: "시험 카드", vram_total_gb: 16, vram_used_gb: 1.0,
      driver: "", display_active: false, reserve_gb: 0.5, usable_gb: 15.5 }] })),
    apply: vi.fn(async (key: string, ctx?: number, eyes?: boolean) => {
      applied.push([key, ctx, eyes]);
      return { ok: true };
    }),
  } as unknown as SetupApi;
  return { api, applied };
}

const eyesLine = (host: HTMLElement) => host.querySelector<HTMLParagraphElement>(".model-row-eyes");

it("지금 쓰는 모델이 그림을 읽고 있으면 글만 읽기로 바꿀 수 있다", async () => {
  const { api, applied } = apiWith({ catalog_key: "small-27b", chat_model: "hf.co/x/small:q", num_ctx: 49152, reads_pictures: true });
  const host = await mount(<ModelSection api={api} />);
  const line = eyesLine(host)!;
  expect(line.textContent).toContain("그림 읽기 켜짐");
  expect(host.querySelectorAll(".model-row-eyes").length).toBe(1);
  await act(async () => { line.querySelector<HTMLButtonElement>("button")!.click(); });
  expect(applied).toEqual([["small-27b", 49152, false]]);
});

it("글만 읽는 중이면 그림도 읽기로 되돌릴 수 있다", async () => {
  const { api, applied } = apiWith({ catalog_key: "small-27b", chat_model: "sonjari-text-small-27b", num_ctx: 65536, reads_pictures: false });
  const host = await mount(<ModelSection api={api} />);
  const line = eyesLine(host)!;
  expect(line.textContent).toContain("글만 읽는 중");
  expect(line.textContent).toContain("1.1GB");
  await act(async () => { line.querySelector<HTMLButtonElement>("button")!.click(); });
  expect(applied).toEqual([["small-27b", 65536, true]]);
});

it("옛 선택 기록은 모델 이름으로 본다", async () => {
  const { api } = apiWith({ catalog_key: "small-27b", chat_model: "sonjari-text-small-27b", num_ctx: 65536 });
  expect(eyesLine(await mount(<ModelSection api={api} />))!.textContent).toContain("글만 읽는 중");
  const old = apiWith({ catalog_key: "small-27b", chat_model: "hf.co/x/small:q", num_ctx: 49152 });
  expect(eyesLine(await mount(<ModelSection api={old.api} />))!.textContent).toContain("그림 읽기 켜짐");
});

it("그림을 끌 수 없는 모델 · 지금 쓰지 않는 모델에는 줄이 없다", async () => {
  const plain = apiWith({ catalog_key: "other-9b", chat_model: "other:9b", num_ctx: 49152 });
  expect(eyesLine(await mount(<ModelSection api={plain.api} />))).toBeNull();
  const none = apiWith(null);
  expect(eyesLine(await mount(<ModelSection api={none.api} />))).toBeNull();
});
