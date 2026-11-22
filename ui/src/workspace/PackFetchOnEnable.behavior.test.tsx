// @vitest-environment jsdom
/**
 * 「켜고 받기」(2026-11-16 저녁 · 대표 「켜기를 누르면 필요한 파일이 다운된다고 같이 얘기해 주면서」).
 *
 * - 팩 켜기 카드: 받을 파일이 남았으면 크기 · 받는 자리 · 남은 자리 + 단추 「켜고 받기」. 자리가 모자라면 단추를 막고 까닭.
 *   이미 있으면(설정한 자리 포함) 「이미 있습니다」 + 「○○ 켜기」. 파일 없는 팩은 받기 줄이 없다.
 * - 결과 한 줄: 받는 중 n/m · GB(받은 바이트로만) → 켜짐 · 준비됨 · 실패면 까닭.
 * - 설정 › 팩: 꺼진 팩도 크기를 먼저 보이고 단추는 「켜고 받기」 · 누르면 setPack(id, true, {fetch: true}).
 *   설정한 자리에 있는 줄은 「설정한 자리에 있음」 · 받기 단추 없음.
 */
import { createRef, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import type { Approval, PackInfo, PackModelsStatus } from "../types";
import { PackEnableCard, PackResultLine } from "./DecisionCards";
import { packFetchProgress } from "./PackModels";
import { PacksSection } from "./PacksSection";

vi.mock("../backend", () => ({ isTauri: () => false, pickNativeCodeWorkspace: vi.fn(async () => null) }));

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const button = (label: string) =>
  [...container.querySelectorAll("button")].find((el) => (el.textContent ?? "").trim().startsWith(label)) as HTMLButtonElement | undefined;

function card(target: Partial<NonNullable<Approval["target"]>>): Approval {
  return {
    nonce: "n1", job_id: "", tool_name: "sonjari_pack_request", arguments: { pack: "gen3d", why: "피규어" },
    target: {
      kind: "pack_enable", pack: "gen3d", name: "3D 생성 팩", summary: "사진 한 장으로 3D 를 만든다.",
      permissions: { reads: [], writes: [], runs: [], network: "켤 때 받음" }, tools: 11, why: "피규어를 만들려고",
      has_models: true, ...target,
    },
  };
}

describe("팩 켜기 카드", () => {
  it("받을 파일이 남았으면 크기 · 받는 자리 · 남은 자리를 보이고 단추는 「켜고 받기」", () => {
    const onDecide = vi.fn();
    act(() => root.render(<PackEnableCard approval={card({
      fetch_on_enable: true, download_bytes: 10_615_040_905, disk_needed_bytes: 11_330_081_810,
      disk_free_bytes: 120_000_000_000, disk_ok: true, place: "D:/SonjariPacks",
    })} busy={false} cardRef={createRef()} onDecide={onDecide} />));
    const line = container.querySelector("[data-testid=pack-ask-fetch]")?.textContent ?? "";
    expect(line).toContain("켜면 필요한 파일 약 10.6 GB를 받습니다");
    expect(line).toContain("받는 자리 D:/SonjariPacks");
    expect(line).toContain("남은 자리 120.0 GB");
    const go = button("켜고 받기")!;
    expect(go.disabled).toBe(false);
    act(() => go.click());
    expect(onDecide).toHaveBeenCalledWith(true, false);
    expect(button("켜고 받기, 앞으로")).toBeDefined();
  });

  it("자리가 모자라면 두 단추 다 막히고 까닭(필요 · 남은 · 설정 자리)을 보인다", () => {
    act(() => root.render(<PackEnableCard approval={card({
      fetch_on_enable: true, download_bytes: 10_615_040_905, disk_needed_bytes: 11_330_081_810,
      disk_free_bytes: 3_000_000_000, disk_ok: false, place: "C:/Users/me/AppData/Sonjari",
    })} busy={false} cardRef={createRef()} onDecide={vi.fn()} />));
    const alert = container.querySelector("[role=alert]")?.textContent ?? "";
    expect(alert).toContain("자리가 모자랍니다. 필요 11.3 GB · 남은 자리 3.0 GB");
    expect(alert).toContain("설정 › 일반 › 팩 파일 자리");
    expect(button("켜고 받기")!.disabled).toBe(true);
    expect(button("켜고 받기, 앞으로")!.disabled).toBe(true);
    expect(button("켜지 않기")!.disabled).toBe(false);
  });

  it("이미 있으면(설정한 자리 포함) 「이미 있습니다」 · 단추는 「○○ 켜기」", () => {
    act(() => root.render(<PackEnableCard approval={card({ fetch_on_enable: false, download_bytes: 0, disk_ok: true })}
      busy={false} cardRef={createRef()} onDecide={vi.fn()} />));
    expect(container.textContent).toContain("필요한 파일은 이 PC 에 이미 있습니다");
    expect(button("3D 생성 팩 켜기")).toBeDefined();
    expect(button("켜고 받기")).toBeUndefined();
  });

  it("파일이 없는 팩은 받기 줄이 없다 · 숫자 없는 옛 카드는 백엔드 글을 그대로", () => {
    act(() => root.render(<PackEnableCard approval={card({ has_models: false, fetch_on_enable: false })}
      busy={false} cardRef={createRef()} onDecide={vi.fn()} />));
    expect(container.querySelector("[data-testid=pack-ask-fetch]")).toBeNull();
    act(() => root.render(<PackEnableCard approval={card({ has_models: undefined, fetch_on_enable: undefined, download: "받을 모델 없음" })}
      busy={false} cardRef={createRef()} onDecide={vi.fn()} />));
    expect(container.querySelector("[data-testid=pack-ask-fetch]")?.textContent).toContain("받을 모델 없음");
  });
});

describe("결과 한 줄 — 받는 진행", () => {
  it("받는 중 n/m · 받은 GB / 전체 GB · 막대는 받은 바이트로", () => {
    act(() => root.render(<PackResultLine name="3D 생성 팩" state="on" toolCount={11}
      fetch={{ state: "running", done: 1, count: 2, received: 5_000_000_000, total: 10_615_040_905 }} onClose={vi.fn()} onUndo={vi.fn()} />));
    const text = container.textContent ?? "";
    expect(text).toContain("3D 생성 팩 켜짐 · 필요한 파일 받는 중");
    expect(text).toContain("받는 중 1/2 · 5.0 GB / 10.6 GB");
    expect(container.querySelector("[role=progressbar]")?.getAttribute("aria-valuenow")).toBe("47");
    expect(button("끄기")).toBeUndefined();  // 받는 중에는 끄기를 안 띄운다(받기는 설정 › 팩에서 멈춘다)
  });

  it("다 받으면 「켜짐 · 준비됨」 · 실패면 까닭", () => {
    act(() => root.render(<PackResultLine name="3D 생성 팩" state="on"
      fetch={{ state: "ready", done: 2, count: 2, received: 1, total: 1 }} onClose={vi.fn()} />));
    expect(container.textContent).toContain("3D 생성 팩 켜짐 · 준비됨");
    act(() => root.render(<PackResultLine name="3D 생성 팩" state="on"
      fetch={{ state: "failed", done: 0, count: 2, received: 0, total: 1, problem: "받는 도중 끊겼습니다." }} onClose={vi.fn()} />));
    expect(container.textContent).toContain("파일을 다 받지 못했습니다");
    expect(container.textContent).toContain("받는 도중 끊겼습니다.");
  });

  it("받기가 없으면 예전 한 줄 그대로", () => {
    act(() => root.render(<PackResultLine name="애니메이터 팩" state="on" toolCount={13} onClose={vi.fn()} />));
    expect(container.textContent).toContain("애니메이터 팩 켜짐 · 도구 13개");
    expect(container.querySelector("[data-testid=pack-result-fetch]")).toBeNull();
  });
});

const ROW = { kind: "binary" as const, license: "MIT", license_url: "https://example.invalid/LICENSE", required: true, error: "" };
function models(over: Partial<PackModelsStatus> = {}): PackModelsStatus {
  return {
    pack: "gen3d", state: "idle", error: "", all_ready: false, needs_fetch: true, root: "D:/SonjariPacks",
    to_download_bytes: 9_900_000_000, disk_needed_bytes: 9_900_000_000, disk_free_bytes: 50_000_000_000, disk_ok: true,
    models: [
      { ...ROW, id: "trellis-cpp-cuda-win", platform: "win-x64-cuda", size: 715_040_905, state: "ready", received: 715_040_905, configured: true, path: "D:/models/trellis.cpp/cuda" },
      { ...ROW, id: "trellis2-q8", kind: "weights", size: 9_900_000_000, state: "missing", received: 0 },
      { ...ROW, id: "trellis-cpp-metal-mac", platform: "macos-arm64-metal", size: 1_788_647, state: "not_for_this_machine", received: 0 },
    ],
    ...over,
  };
}

describe("받는 진행 셈", () => {
  it("이 기계용 · 꼭 있어야 하는 줄만 세고, 설정한 자리의 줄은 개수엔 들어가되 받을 바이트엔 안 들어간다", () => {
    const running = packFetchProgress(models({ state: "running", models: models().models.map((row) =>
      row.id === "trellis2-q8" ? { ...row, state: "downloading" as const, received: 4_950_000_000 } : row) }));
    expect(running).toMatchObject({ state: "running", done: 1, count: 2, received: 4_950_000_000, total: 9_900_000_000 });
    expect(packFetchProgress(models({ all_ready: true, needs_fetch: false })).state).toBe("ready");
    expect(packFetchProgress(models({ state: "failed", error: "network: 끊김" }))).toMatchObject({ state: "failed" });
    expect(packFetchProgress(models()).state).toBe("waiting");
  });
});

describe("설정 › 팩", () => {
  const GEN3D: PackInfo = {
    id: "gen3d", name: "3D 생성 팩", version: "0.1.0", kind: "code", summary: "그림에서 3D 를 만든다", description: "",
    tools: ["gen_3d"], skills: [], domains: ["3d"], permissions: { reads: [], writes: [], runs: [], network: true }, bench: "", enabled: false,
    models: [
      { id: "trellis-cpp-cuda-win", kind: "binary", platform: "win-x64-cuda", size: 715_040_905, license: "MIT", license_url: "https://example.invalid", required: true },
      { id: "trellis2-q8", kind: "weights", size: 9_900_000_000, license: "MIT", license_url: "https://example.invalid", required: true },
    ],
  };
  let client: JarvisClient;
  let pack: PackInfo;

  async function show(status: PackModelsStatus): Promise<void> {
    client = {
      listPacks: vi.fn(async () => ({ packs: [pack], problems: [] })),
      packModels: vi.fn(async () => status),
      fetchPackModels: vi.fn(async () => status),
      setPack: vi.fn(async (_id: string, on: boolean) => (pack = { ...pack, enabled: on })),
    } as unknown as JarvisClient;
    await act(async () => root.render(<PacksSection client={client} />));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  }

  beforeEach(() => { pack = { ...GEN3D }; });

  it("꺼진 팩 · 받을 것 남음 → 「켜고 받기」 · 누르면 setPack(id, true, {fetch: true})", async () => {
    await show(models());
    expect(container.querySelector("[data-testid=pack-fetch-plan-gen3d]")?.textContent).toContain("켜면 필요한 파일 약 9.9 GB를 받습니다");
    await act(async () => { button("켜고 받기")!.click(); });
    expect(client.setPack).toHaveBeenCalledWith("gen3d", true, { fetch: true });
  });

  it("설정한 자리에 다 있으면 「설정한 자리에 있음」 · 단추는 그냥 「켜기」 · 켜도 받기 단추가 없다", async () => {
    const all = models({ needs_fetch: false, all_ready: true, to_download_bytes: 0, models: models().models.map((row) =>
      row.state === "missing" ? { ...row, state: "ready" as const, received: row.size, configured: true, path: "D:/models/q8" } : row) });
    await show(all);
    expect(container.textContent).toContain("설정한 자리에 있음 · 받지 않아도 됨");
    expect(container.querySelector("[data-testid=pack-fetch-plan-gen3d]")?.textContent).toContain("설정한 자리에 이미 있습니다");
    expect(button("켜고 받기")).toBeUndefined();
    await act(async () => { button("켜기")!.click(); });
    expect(client.setPack).toHaveBeenCalledWith("gen3d", true);
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(button("받기")).toBeUndefined();
  });

  it("자리가 모자라면 켜기 단추가 막히고 까닭이 보인다", async () => {
    await show(models({ disk_ok: false, disk_needed_bytes: 9_900_000_000, disk_free_bytes: 2_000_000_000 }));
    expect(button("켜고 받기")!.disabled).toBe(true);
    const alert = container.querySelector("[data-testid=pack-fetch-plan-gen3d]")?.textContent ?? "";
    expect(alert).toContain("자리가 모자랍니다. 필요 9.9 GB · 남은 자리 2.0 GB");
    expect(alert).toContain("설정 › 일반 › 팩 파일 자리");
  });
});
