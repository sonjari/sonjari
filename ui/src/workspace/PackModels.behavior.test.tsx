// @vitest-environment jsdom
/**
 * 팩을 켤 때 모델 · 실행기 받기 칸 (2026-11-14) — 받기 단추 · 받은 바이트로만 채우는 막대 · 409 · 507 · 해시 불일치 한 줄 · models 없는 팩엔 칸이 없다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import type { PackInfo, PackModelsStatus } from "../types";
import { PacksSection } from "./PacksSection";

vi.mock("../backend", () => ({ isTauri: () => false, pickNativeCodeWorkspace: vi.fn(async () => null) }));

const PERMS = { reads: [], writes: [], runs: [], network: true };
const GEN3D: PackInfo = {
  id: "gen3d", name: "3D 생성 팩", version: "0.1.0", kind: "code", summary: "그림에서 3D 를 만든다", description: "",
  tools: ["gen_3d"], skills: [], domains: ["3d"], permissions: PERMS, bench: "", enabled: true,
  models: [
    { id: "trellis-cpp-cuda-win", kind: "binary", platform: "win-x64-cuda", size: 715_040_905, license: "MIT",
      license_url: "https://github.com/pwilkin/trellis.cpp/blob/main/LICENSE", required: true },
    { id: "trellis2-q8", kind: "weights", size: 9_900_000_000, license: "MIT(원본 TRELLIS.2 · DINOv3 · BiRefNet 각자 라이선스)",
      license_url: "https://huggingface.co/ilintar/trellis2-gguf", required: true },
  ],
};
const PLAIN: PackInfo = { ...GEN3D, id: "game", name: "게임 팩", models: undefined };

function status(over: Partial<PackModelsStatus> & { rows?: [string, number][] } = {}): PackModelsStatus {
  const [binary, weights] = over.rows ?? [["missing", 0], ["missing", 0]];
  const { rows: _rows, ...rest } = over;
  return {
    pack: "gen3d", state: "idle", error: "", all_ready: false, to_download_bytes: 10_615_040_905,
    disk_needed_bytes: 11_000_000_000, disk_free_bytes: 50_000_000_000, disk_ok: true,
    models: [
      { ...GEN3D.models![0], state: binary[0] as never, received: binary[1], error: "" },
      { ...GEN3D.models![1], state: weights[0] as never, received: weights[1], error: "" },
    ],
    ...rest,
  };
}

let root: Root;
let container: HTMLDivElement;
let client: JarvisClient;
let packs: PackInfo[];

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  packs = [GEN3D];
  client = {
    listPacks: vi.fn(async () => ({ packs, problems: [] })),
    packModels: vi.fn(async () => status()),
    fetchPackModels: vi.fn(async () => status({ state: "running" })),
    cancelPackModels: vi.fn(async () => status({ state: "running", cancelling: true })),
  } as unknown as JarvisClient;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function show(): Promise<void> {
  await act(async () => root.render(<PacksSection client={client} />));
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
const button = (label: string) => [...container.querySelectorAll("button")].find((b) => (b.textContent ?? "").trim().startsWith(label));
async function click(label: string): Promise<void> {
  await act(async () => { button(label)!.click(); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

it("models 가 있는 팩에는 이름 · 크기 · 라이선스 링크 · 안 받음 상태 줄이 보이고, 받기를 누르면 fetch 가 불린다", async () => {
  await show();
  const box = container.querySelector("[data-testid=pack-models-gen3d]")!;
  expect(box).not.toBeNull();
  const text = box.textContent ?? "";
  expect(text).toContain("trellis-cpp-cuda-win");
  expect(text).toContain("715 MB");
  expect(text).toContain("9.9 GB");
  expect(box.querySelectorAll("[data-state=missing]")).toHaveLength(2);
  const link = box.querySelector("a.pm-license") as HTMLAnchorElement;
  expect(link.href).toBe("https://github.com/pwilkin/trellis.cpp/blob/main/LICENSE");
  await click("받기");
  expect(client.fetchPackModels).toHaveBeenCalledWith("gen3d");
});

it("진행 막대는 백엔드가 준 받은 바이트 비율이다(시간이 아니다) — 같은 값이면 시간이 가도 그대로", async () => {
  client.packModels = vi.fn(async () => status({ state: "running", rows: [["ready", 715_040_905], ["downloading", 2_475_000_000]] }));
  await show();
  const bar = container.querySelector("[data-state=downloading] [role=progressbar]") as HTMLElement;
  expect(bar.getAttribute("aria-valuenow")).toBe("25"); // 2.475GB / 9.9GB
  expect((bar.firstElementChild as HTMLElement).style.width).toBe("25%");
  expect(container.textContent).toContain("2.5 GB / 9.9 GB");
  expect(container.textContent).not.toMatch(/남은 시간|초 남|분 남/);
  await act(async () => { await new Promise((r) => setTimeout(r, 1300)); });
  expect(bar.getAttribute("aria-valuenow")).toBe("25");
  expect(button("멈추기")).toBeDefined();
  await click("멈추기");
  expect(client.cancelPackModels).toHaveBeenCalledWith("gen3d");
});

it("크기를 모르는 줄은 비율을 짓지 않고 띠만 오간다", async () => {
  const row = status({ state: "running", rows: [["downloading", 123], ["missing", 0]] });
  row.models[0].size = 0;
  client.packModels = vi.fn(async () => row);
  await show();
  const bar = container.querySelector("[data-state=downloading] [role=progressbar]") as HTMLElement;
  expect(bar.classList.contains("is-unknown")).toBe(true);
  expect(bar.getAttribute("aria-valuenow")).toBeNull();
});

it("409(팩 꺼짐) 는 켜라는 한 줄", async () => {
  client.fetchPackModels = vi.fn(async () => { throw Object.assign(new Error("pack_not_enabled"), { status: 409, detail: "pack_not_enabled" }); });
  await show();
  await click("받기");
  const alert = container.querySelector("[role=alert]")!;
  expect(alert.textContent).toContain("팩을 켠 뒤");
  expect(alert.textContent).not.toContain("pack_not_enabled");
});

it("507(디스크 부족) 는 필요한 만큼과 남은 만큼을 말한다", async () => {
  client.fetchPackModels = vi.fn(async () => {
    throw Object.assign(new Error("pack_models_507"), { status: 507, detail: status({ disk_needed_bytes: 21_000_000_000, disk_free_bytes: 3_000_000_000, disk_ok: false, error: "not_enough_disk" }) });
  });
  await show();
  await click("받기");
  const text = container.querySelector("[role=alert]")!.textContent ?? "";
  expect(text).toContain("21.0 GB 필요");
  expect(text).toContain("3.0 GB 남음");
});

it("해시 불일치는 지웠으니 다시 받으라는 한 줄(코드 이름은 안 보인다)", async () => {
  client.packModels = vi.fn(async () => status({
    state: "failed", error: "sha256_mismatch: trellis-cuda-windows-x64.zip (받은 것 abcdef012345…) — 지웠다",
    rows: [["failed", 0], ["missing", 0]],
  }));
  await show();
  const text = container.querySelector("[role=alert]")!.textContent ?? "";
  expect(text).toContain("원본과 달라 지웠습니다");
  expect(text).not.toContain("sha256");
});

it("models 가 없는 팩에는 칸도 단추도 없고 상태를 묻지도 않는다", async () => {
  packs = [PLAIN];
  await show();
  expect(container.querySelector("[data-testid^=pack-models-]")).toBeNull();
  expect(client.packModels).not.toHaveBeenCalled();
});

it("꺼진 팩은 줄만 보이고 받기 단추는 없다 — 상태는 읽기만 해서 켜기 전에 크기 · 자리를 보인다(11-16 저녁)", async () => {
  // 11-14 에는 꺼진 팩의 상태를 묻지 않았다. 11-16 저녁 대표 「켜기를 누르면 필요한 파일이 다운된다고 같이 얘기해 주면서」 —
  // 켜기 전에 크기 · 받는 자리 · 남은 자리를 보이려고 읽는다. 받기(fetch)는 여전히 부르지 않는다.
  packs = [{ ...GEN3D, enabled: false }];
  client.packModels = vi.fn(async () => status({ needs_fetch: true, root: "D:/SonjariPacks" }));
  await show();
  expect(container.querySelector("[data-testid=pack-models-gen3d]")).not.toBeNull();
  expect(button("받기")).toBeUndefined();
  expect(client.packModels).toHaveBeenCalled();
  expect(client.fetchPackModels).not.toHaveBeenCalled();
  const plan = container.querySelector("[data-testid=pack-fetch-plan-gen3d]")?.textContent ?? "";
  expect(plan).toContain("켜면 필요한 파일 약 10.6 GB를 받습니다");
  expect(plan).toContain("받는 자리 D:/SonjariPacks");
  expect(plan).toContain("남은 자리 50.0 GB");
  expect(button("켜고 받기")).toBeDefined();
});

// ── 11-14 맥: 이 기계용 아닌 줄 · 이미 받아진 윈도우 실행기 ──

function macStatus(over: Partial<PackModelsStatus> = {}): PackModelsStatus {
  const base = status({ rows: [["not_for_this_machine", 0], ["missing", 0]] });
  return {
    ...base,
    platform: "macos-arm64",
    to_download_bytes: 9_900_000_000,
    models: [
      base.models[0],
      { id: "trellis-cpp-metal-mac", kind: "binary", platform: "macos-arm64-metal", size: 1_788_682, license: "MIT",
        license_url: "https://github.com/pwilkin/trellis.cpp/blob/main/LICENSE", required: true, state: "missing", received: 0,
        error: "", hand_built: true },
      base.models[1],
    ],
    leftovers: [{ id: "trellis-cpp-cuda-win", platform: "win-x64-cuda", path: "/x/tools/gen3d/trellis-cpp", bytes: 826_000_000 }],
    ...over,
  };
}

it("이 기계용 아닌 줄은 흐리게 「이 기계용 아님」만 — 크기 · 막대가 없고 받기 셈에도 안 든다", async () => {
  client.packModels = vi.fn(async () => macStatus());
  await show();
  const foreign = container.querySelector("[data-state=not_for_this_machine]") as HTMLElement;
  expect(foreign).not.toBeNull();
  expect(foreign.classList.contains("is-not_for_this_machine")).toBe(true);
  expect(foreign.textContent).toContain("이 기계용 아님");
  expect(foreign.textContent).not.toContain("715 MB");
  expect(foreign.querySelector("[role=progressbar]")).toBeNull();
  expect(foreign.querySelector("button")).toBeNull();
  // 받기 단추의 양은 백엔드가 센 이 기계용 몫(9.9GB)이지 윈도우 실행기가 아니다
  expect(button("받기")!.textContent).toContain("9.9 GB");
});

it("이미 받아진 남의 기계용은 크기와 함께 보이고, 지우기는 한 번 더 확인한 뒤에만 부른다", async () => {
  client.packModels = vi.fn(async () => macStatus());
  client.removePackLeftovers = vi.fn(async () => macStatus({ leftovers: [], removed: macStatus().leftovers }));
  await show();
  const box = container.querySelector("[data-testid=pm-leftovers]")!;
  expect(box.textContent).toContain("trellis-cpp-cuda-win");
  expect(box.textContent).toContain("826 MB");
  await click("지우기");
  expect(client.removePackLeftovers).not.toHaveBeenCalled();
  await click("그만");
  expect(client.removePackLeftovers).not.toHaveBeenCalled();
  await click("지우기");
  await click("정말 지우기");
  expect(client.removePackLeftovers).toHaveBeenCalledWith("gen3d");
  expect(container.querySelector("[data-testid=pm-leftovers]")).toBeNull();
});

it("맥 실행기의 받을 곳이 없으면(no_prebuilt) 빌드해 넣으라는 한 줄", async () => {
  client.packModels = vi.fn(async () => macStatus({ state: "failed", error: "no_prebuilt: trellis-cpp-metal-mac 는 받을 곳이 아직 없다" }));
  await show();
  const text = container.querySelector("[role=alert]")!.textContent ?? "";
  expect(text).toContain("빌드한 것을");
  expect(text).not.toContain("no_prebuilt");
});
