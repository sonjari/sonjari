// @vitest-environment jsdom
/**
 * 머리의 모델 이름을 **눌러서** 바꾼다 (2026-09-21 제품 요청).
 *
 * 화면 층에서만 나는 고장을 잰다:
 *
 *   ① Code 탭에서 누르면 **코드 역할**로 묻고 고른다 — 대화 모델이 아니라.
 *   ② 사용자가 직접 받은 모델이 「내 모델」로 보이고, 능력을 잰 적 없다고 적힌다.
 *   ③ 도구를 못 부르는 모델은 **보이되 못 눌린다** — 이유를 달고.
 *   ④ 쓰는 중인 모델을 또 누르지 않는다(헛돈다).
 *
 * ★ 백엔드가 아무리 맞아도 화면이 role 을 안 실으면 이 기능은 거짓말이 된다.
 *   실제로 이 저장소는 「말로 시킨 것이 UI 모드를 안 실었다」로 같은 병을 겪었다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ModelPickerView, ModelRole, SetupApi } from "../setup/setupApi";
import { LocalModelPicker } from "./LocalModelPicker";

function grade(measured: boolean) {
  return { model: "x", measured, label: measured ? "사슬 벤치 10/10 실측" : "능력을 잰 적 없음", detail: "" };
}

const VIEW: ModelPickerView = {
  role: "chat",
  current: "qwen3.6:35b-a3b",
  budget_gb: 23.5,
  satellite: false,
  pulls: {},
  models: [
    { tag: "qwen3.6:35b-a3b", name: "Qwen 3.6 35B-A3B", vendor: "Alibaba", listed: true, installed: true,
      fits: true, size_gb: 23, num_ctx: 131072, vision: true, roles: ["chat", "code"],
      grade: grade(true), current: true, blocked: "" },
    { tag: "qwen3.5:9b", name: "Qwen 3.5 9B", vendor: "Alibaba", listed: true, installed: true,
      fits: true, size_gb: 6.1, num_ctx: 65536, vision: false, roles: ["chat"],
      grade: grade(true), current: false, blocked: "" },
    { tag: "mistral-small3.2:24b", name: "mistral-small3.2:24b", vendor: "", listed: false, installed: true,
      fits: true, size_gb: 14, num_ctx: null, vision: false, roles: [],
      grade: grade(false), current: false, blocked: "" },
    { tag: "translategemma:4b", name: "translategemma:4b", vendor: "", listed: false, installed: true,
      fits: false, size_gb: 3.1, num_ctx: null, vision: true, roles: [],
      grade: grade(false), current: false, blocked: "도구를 부를 수 없어 온텔릭이 일을 못 합니다" },
  ],
};

let root: Root;
let container: HTMLDivElement;
let asked: ModelRole[];
let chosen: Array<{ tag: string; role: ModelRole }>;
let api: SetupApi;

function options(): HTMLButtonElement[] {
  return [...container.querySelectorAll<HTMLButtonElement>('[role="option"]')];
}

function optionFor(text: string): HTMLButtonElement {
  const found = options().find((button) => button.textContent?.includes(text));
  if (!found) throw new Error(`「${text}」 줄이 목록에 없다 — 있는 것: ${options().map((b) => b.textContent).join(" / ")}`);
  return found;
}

async function openPicker(role: ModelRole = "chat") {
  await act(async () => {
    root.render(<LocalModelPicker api={api} role={role} label="Qwen3.6 · 128K" context="맥락" />);
  });
  await act(async () => {
    container.querySelector<HTMLButtonElement>(".pilot-model-trigger")!.click();
  });
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  asked = [];
  chosen = [];
  api = {
    modelPicker: vi.fn(async (role: ModelRole) => { asked.push(role); return { ...VIEW, role }; }),
    selectModel: vi.fn(async (tag: string, role: ModelRole) => { chosen.push({ tag, role }); return { ok: true }; }),
    // 2026-09-23 새벽: 고르개가 「카드가 바뀌었나」를 물으러 contextStatus 를 부르게 됐는데 대역에 없어 이 파일이 통째로 깨졌다.
    contextStatus: vi.fn(async () => ({
      chat_model: "qwen3.6:35b-a3b", num_ctx: 131072, ceilings: {}, measuring: false, live: null,
      global: { value: "", ours: false }, watch: { state: "steady" },
    })),
  } as unknown as SetupApi;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

// ── ① 역할 ──────────────────────────────────────────────────────────────────
it("Code 탭에서 누르면 코드 모델을 묻고 코드 모델을 바꾼다", async () => {
  await openPicker("code");

  expect(asked).toContain("code");
  expect(asked).not.toContain("chat");

  await act(async () => { optionFor("Qwen 3.5 9B").click(); });
  expect(chosen).toEqual([{ tag: "qwen3.5:9b", role: "code" }]);
});

it("대화 탭에서 누르면 대화 모델을 바꾼다", async () => {
  await openPicker("chat");
  await act(async () => { optionFor("Qwen 3.5 9B").click(); });
  expect(chosen).toEqual([{ tag: "qwen3.5:9b", role: "chat" }]);
});

// ── ② 사용자가 직접 받은 모델 ────────────────────────────────────────────────
it("직접 받은 모델은 「내 모델」로 보이고 능력을 잰 적 없다고 적는다", async () => {
  await openPicker();
  const row = optionFor("mistral-small3.2:24b");
  expect(row.textContent).toContain("내 모델");
  expect(row.textContent).toContain("능력을 잰 적 없음");
  expect(row.disabled).toBe(false);
});

it("실측한 모델에는 「안 쟀음」 경고를 달지 않는다", async () => {
  await openPicker();
  expect(optionFor("Qwen 3.5 9B").querySelector(".local-model-untested")).toBeNull();
  expect(optionFor("mistral-small3.2:24b").querySelector(".local-model-untested")).not.toBeNull();
});

// ── ③ 못 고르는 것 ──────────────────────────────────────────────────────────
it("도구를 못 부르는 모델은 사라지지 않고 이유를 달고 못 눌린다", async () => {
  await openPicker();
  const row = optionFor("translategemma:4b");
  expect(row.textContent).toContain("도구를 부를 수 없어");
  expect(row.disabled).toBe(true);

  await act(async () => { row.click(); });
  expect(chosen).toEqual([]);
});

// ── ④ 헛돌지 않는다 ─────────────────────────────────────────────────────────
it("쓰는 중인 모델은 다시 고르지 않는다", async () => {
  await openPicker();
  const row = optionFor("Qwen 3.6 35B-A3B");
  expect(row.disabled).toBe(true);
  await act(async () => { row.click(); });
  expect(chosen).toEqual([]);
});

it("쓰는 중인 모델이 목록 밖 것이어도 머리말 아래로 들어가지 않는다", async () => {
  // ★ 실물에서 잡은 것 — 목록이 「이 PC 에 직접 받아 두신 모델」 제목으로 시작했다.
  api.modelPicker = vi.fn(async (role: ModelRole) => ({
    ...VIEW, role,
    models: VIEW.models.map((row) => ({ ...row, current: row.tag === "mistral-small3.2:24b" })),
  }));
  await openPicker();
  const first = container.querySelector(".local-model-options")!.firstElementChild!;
  expect(first.querySelector(".local-model-divider")).toBeNull();
  expect(first.textContent).toContain("mistral-small3.2:24b");
  expect(first.textContent).toContain("지금 쓰는 중");
});

it("위성 PC 에서는 고르개가 아니라 글씨로 남는다", async () => {
  api.modelPicker = vi.fn(async (role: ModelRole) => ({ ...VIEW, role, satellite: true }));
  await act(async () => {
    root.render(<LocalModelPicker api={api} role="chat" label="Qwen3.6 · 128K" context="맥락" />);
  });
  await act(async () => { await Promise.resolve(); });
  expect(container.querySelector(".pilot-model-trigger")).toBeNull();
  expect(container.querySelector(".model-chip")?.textContent).toContain("Qwen3.6");
});

it("백엔드가 거절하면 까닭을 사람 말로 보여 주고 목록을 닫지 않는다", async () => {
  api.selectModel = vi.fn(async () => ({ ok: false, error: "model_not_fully_on_gpu" }));
  await openPicker();
  await act(async () => { optionFor("Qwen 3.5 9B").click(); });
  expect(container.querySelector(".local-model-error")?.textContent)
    .toContain("그래픽카드에 다 올라가지 않아");
  expect(options().length).toBeGreaterThan(0);
});

// ── ⑤ 컨텍스트 칸 고르기 (09-29 대표 요청) ─────────────────────────────────────
const MEASURED = {
  "qwen3.6:35b-a3b": {
    ok: true, model: "qwen3.6:35b-a3b", ceiling: 49152, model_max: 262144, stopped: "not_fully_on_gpu",
    took_sec: 300, measured_at: "2026-09-29T19:10:00",
    steps: [
      { num_ctx: 32768, passed: true, why: "", gpu_share: 1, tokens_per_sec: 150 },
      { num_ctx: 49152, passed: true, why: "", gpu_share: 1, tokens_per_sec: 146 },
      { num_ctx: 65536, passed: false, why: "not_fully_on_gpu", gpu_share: 0.966, tokens_per_sec: 82 },
      { num_ctx: 131072, passed: false, why: "load_failed", tokens_per_sec: 0 },
    ],
  },
};

function measuredApi(chatModel = "qwen3.6:35b-a3b") {
  const applied: Array<[string, boolean, number | undefined]> = [];
  api.contextStatus = vi.fn(async () => ({
    chat_model: chatModel, num_ctx: 65536, ceilings: MEASURED, measuring: false, live: null,
    global: { value: "", ours: false }, watch: { state: "steady" as const },
  }));
  api.applyContext = vi.fn(async (model: string, alsoGlobal: boolean, numCtx?: number) => {
    applied.push([model, alsoGlobal, numCtx]);
    return { ok: true, num_ctx: numCtx };
  });
  return applied;
}

function choice(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll<HTMLButtonElement>(".context-choices button")]
    .find((button) => button.querySelector("b")?.textContent === label);
  if (!found) throw new Error(`「${label}」 칸이 없다`);
  return found;
}

it("Code 탭 고르개에서도 잰 칸마다 속도를 보고 골라 적용한다", async () => {
  const applied = measuredApi();
  await openPicker("code");

  // 못 올린 칸(128K, tok/s 0)은 고를 게 없다. 샌 칸(64K)은 속도와 함께 보인다.
  expect(container.querySelectorAll(".context-choices button").length).toBe(3);
  expect(choice("64K").textContent).toContain("CPU 3%");
  expect(choice("64K").getAttribute("aria-checked")).toBe("true"); // 지금 값
  expect(container.querySelector(".context-apply")?.textContent).toContain("대화 탭도 같은 모델이라 같이 바뀝니다");

  await act(async () => { choice("48K").click(); });
  const apply = container.querySelector<HTMLButtonElement>(".context-apply button.primary")!;
  expect(apply.textContent).toBe("48K 적용");
  await act(async () => { apply.click(); });
  expect(applied).toEqual([["qwen3.6:35b-a3b", false, 49152]]);
});

it("코드 모델이 대화 모델과 다르면 칸 대신 그렇다고만 적는다 — 한 모델에 두 창이면 러너가 서로 쫓아낸다", async () => {
  measuredApi("gemma4:26b");
  await openPicker("code");

  expect(container.querySelector(".context-choices")).toBeNull();
  expect(container.querySelector(".context-ceiling")?.textContent).toContain("대화 모델과 달라");
});

it("고른 칸만 적힌 기록은 잰 기록이 아니다 — 이유 없는 경고도 「다시 재기」도 안 뜬다", async () => {
  // 2026-10-05 영어 첫 실행 촬영: 모델을 적용하자마자 주황색 「알 수 없는 이유」가 떴다. 적용하면 백엔드가
  // 「이 크기로 쓰기로 했다」만 남기는데(잰 값 없음), 화면이 그것을 쟀다가 실패한 기록으로 읽었다.
  api.contextStatus = vi.fn(async () => ({
    chat_model: "qwen3.6:35b-a3b", num_ctx: 131072, measuring: false, live: null,
    ceilings: { "qwen3.6:35b-a3b": { model: "qwen3.6:35b-a3b", chosen: 131072, chosen_at: "2026-10-05T06:15:32" } },
    global: { value: "", ours: false }, watch: { state: "unknown" as const },
  })) as unknown as SetupApi["contextStatus"];
  await openPicker("chat");

  const panel = container.querySelector(".context-ceiling")!;
  expect(panel.querySelector(".context-note.warn")).toBeNull();
  expect(panel.textContent).not.toContain("알 수 없는 이유");
  expect(panel.textContent).toContain("이 PC 에서 아직 안 쟀습니다");
  expect(panel.querySelector(".context-ceiling-head button")?.textContent).toBe("상한 재기");
});

// ── ⑤ 코드 일 추천 (2026-10-01 밤 대표 전략: 16GB 는 9B 메인, 코드 일에는 큰 모델) ──────────────
it("코드 고르개는 이 카드에 들어가는 큰 모델을 권하고, 받으면 코드 역할에만 쓴다", async () => {
  const pulled: Array<{ tag: string; ctx?: number; role?: ModelRole }> = [];
  api.modelPicker = vi.fn(async (role: ModelRole) => ({
    ...VIEW, role, current: "qwen3.5:9b", budget_gb: 14.9,
    suggestion: role === "code" ? {
      tag: "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL", name: "Qwen 3.8 27B · 3비트", size_gb: 13.15, params_b: 27.3,
      current: "qwen3.5:9b", current_params_b: 9, installed: false, measured: false,
      basis: "규칙 추천 — 이 카드에 여유 있게 들어가는 가장 큰 27B 양자화입니다.",
    } : null,
  }));
  api.pullTag = vi.fn(async (tag: string, ctx?: number, role?: ModelRole) => {
    pulled.push({ tag, ctx, role });
    return { ok: true, model_key: tag, status: "pulling", completed: 0, total: 0 };
  }) as unknown as SetupApi["pullTag"];

  await openPicker("code");
  const offer = container.querySelector(".code-upgrade");
  expect(offer?.textContent).toContain("코드 일에 더 큰 모델을 써 볼 수 있습니다");
  expect(offer?.textContent).toContain("규칙 추천");
  expect(offer?.textContent).toContain("대화·브라우저 모델은 그대로");
  await act(async () => { container.querySelector<HTMLButtonElement>(".code-upgrade-go")!.click(); });
  expect(pulled).toEqual([{ tag: "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL", ctx: 65536, role: "code" }]);
});

it("대화 고르개에는 코드 일 추천이 없다", async () => {
  await openPicker("chat");
  expect(container.querySelector(".code-upgrade")).toBeNull();
});
