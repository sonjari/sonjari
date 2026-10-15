// @vitest-environment jsdom
/**
 * 설정 › 모델 — 목록 밖 모델(허깅페이스에서 고른 것)을 쓰는 중에도 그림 읽기를 켜고 끈다 (2026-10-13).
 *
 * 목록에는 그 모델의 줄이 없어서, 그림 읽기를 바꾸는 줄이 설 자리가 없었다. 백엔드가 「지금 쓰는 모델의 그림 읽기」를
 * 따로 알려 주면(`eyes`) 목록 위에 한 줄을 둔다.
 *
 * 지키는 약속:
 * - 목록 밖 모델이고 바꿀 수 있을 때만 줄이 보인다. 옛 백엔드(그 칸이 없다)는 예전 화면 그대로다.
 * - 그림을 읽는 쪽 이름(`source_tag`)에 켬/끔을 실어, 지금 쓰는 대화 길이 그대로 다시 올린다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { ModelsView, SetupApi } from "../setup/setupApi";
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

const PICKED = "hf.co/someone/Sample-4B-GGUF:UD-Q3_K_XL";
const PLAIN = "sonjari-text-someone-sample-4b-gguf-ud-q3_k_xl";

function apiWith(eyes: ModelsView["eyes"] | undefined, chat = PICKED) {
  const applied: Array<[string, number | undefined, boolean | undefined]> = [];
  const api = {
    models: vi.fn(async () => ({ models: [], pulls: {}, satellite: false, ...(eyes ? { eyes } : {}),
      selection: { catalog_key: "", chat_model: chat, num_ctx: 49152, reads_pictures: eyes?.reads_pictures } })),
    profile: vi.fn(async () => ({ gpus: [{ index: 0, name: "시험 카드", vram_total_gb: 6, vram_used_gb: 1.0,
      driver: "", display_active: true, reserve_gb: 1, usable_gb: 5 }] })),
    applyTag: vi.fn(async (tag: string, ctx?: number, on?: boolean) => {
      applied.push([tag, ctx, on]);
      return { ok: true };
    }),
  } as unknown as SetupApi;
  return { api, applied };
}

const line = (host: HTMLElement) => host.querySelector<HTMLElement>(".model-loose-eyes");

it("그림을 읽는 목록 밖 모델은 글만 읽기로 바꿀 수 있다", async () => {
  const { api, applied } = apiWith({ tag: PICKED, reads_pictures: true, can_switch: true, source_tag: PICKED, saves_gb: 0.64, listed: false });
  const host = await mount(<ModelSection api={api} />);

  expect(line(host)!.textContent).toContain("그림 읽기 켜짐");
  await act(async () => { line(host)!.querySelector("button")!.click(); });

  expect(applied).toEqual([[PICKED, 49152, false]]);
});

it("글만 읽는 중이면 원래 이름으로 그림 읽기를 다시 켠다", async () => {
  const { api, applied } = apiWith(
    { tag: PLAIN, reads_pictures: false, can_switch: true, source_tag: PICKED, saves_gb: 0.64, listed: false }, PLAIN);
  const host = await mount(<ModelSection api={api} />);

  expect(line(host)!.textContent).toContain("글만 읽는 중");
  expect(line(host)!.textContent).toContain("0.6GB");
  expect(line(host)!.textContent).not.toContain("sonjari-text-"), "날것의 머리는 보이지 않는다";
  await act(async () => { line(host)!.querySelector("button")!.click(); });

  expect(applied).toEqual([[PICKED, 49152, true]]);
});

it("목록 모델이거나 · 바꿀 수 없거나 · 옛 백엔드면 줄이 없다", async () => {
  const listed = apiWith({ tag: "qwen3.5:9b", reads_pictures: true, can_switch: true, source_tag: "qwen3.5:9b", saves_gb: 0.6, listed: true });
  expect(line(await mount(<ModelSection api={listed.api} />))).toBeNull();
  const inside = apiWith({ tag: PICKED, reads_pictures: true, can_switch: false, source_tag: PICKED, saves_gb: 0, listed: false });
  expect(line(await mount(<ModelSection api={inside.api} />))).toBeNull();
  expect(line(await mount(<ModelSection api={apiWith(undefined).api} />))).toBeNull();
});

it("못 바꿨으면 까닭을 그 줄 아래에 적는다", async () => {
  const { api } = apiWith({ tag: PICKED, reads_pictures: true, can_switch: true, source_tag: PICKED, saves_gb: 0.64, listed: false });
  (api.applyTag as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: false, error: "model_not_fully_on_gpu" });
  const host = await mount(<ModelSection api={api} />);

  await act(async () => { line(host)!.querySelector("button")!.click(); });

  expect(line(host)!.querySelector('[role="alert"]')?.textContent).toContain("그래픽카드에 다 올라가지 않아");
});
