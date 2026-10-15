// @vitest-environment jsdom
/**
 * 설정 › 팩 (0판, 2026-09-27) — 켜기 전에 무엇을 하는지 먼저 보이고, 켜면 유니티 마법사가 다음 할 일 하나를 준다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import type { PackInfo, UnityRecipeCard, UnitySetupView } from "../types";
import { PacksSection, permissionLines } from "./PacksSection";

vi.mock("../backend", () => ({ isTauri: () => false, pickNativeCodeWorkspace: vi.fn(async () => null) }));

const GAME: PackInfo = {
  id: "game", name: "게임 팩", version: "0.1.0", kind: "code",
  summary: "유니티 프로젝트를 점검한다", description: "",
  tools: ["unity_project_info", "unity_list_recipes", "unity_run_recipe"], skills: ["game-unity"], domains: ["game"],
  permissions: {
    reads: ["허락한 유니티 프로젝트 폴더"], writes: ["Assets/Editor/SonjariRecipes — 도는 동안만"],
    runs: ["Unity.exe — 배치 모드"], network: "쓰지 않는다",
  },
  bench: "bench/game_pack", enabled: false,
};

const READY: UnitySetupView = {
  hub: { installed: true, path: "C:/Hub/Unity Hub.exe" },
  editors: [{ version: "6000.6.3f1", path: "C:/Editor/Unity.exe" }],
  license: true,
  projects: [{ path: "E:/UnityProjects/Game", name: "Game", version: "6000.6.3f1", editor_installed: true, editor_open: false, allowed: true }],
  next: { kind: "ready", text: "준비됐습니다 — 「유니티 Game 프로젝트 텍스처 점검해줘」처럼 말해 보세요." },
};

const CARDS: UnityRecipeCard[] = [
  { name: "missing_references", title: "빠진 참조 찾기", description: "프리팹과 씬에서 「Missing」으로 뜨는 칸을 한 번에 찾습니다.",
    ask: "유니티 프로젝트에서 빠진 참조 찾아 줘", origin: "pack" },
  { name: "texture_audit", title: "텍스처 설정 점검", description: "너무 큰 텍스처를 찾습니다.", ask: "유니티 프로젝트 텍스처 점검해 줘", origin: "pack" },
  // 사람이 등록한 것에는 예시 문장이 없을 수 있다.
  { name: "big_meshes", title: "큰 메시 찾기 (등록)", description: "삼각형이 많은 메시를 찾는다.", ask: "", origin: "registered" },
];

let root: Root;
let container: HTMLDivElement;
let client: JarvisClient;
let state: PackInfo;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  state = { ...GAME };
  client = {
    listPacks: vi.fn(async () => ({ packs: [state], problems: [] })),
    setPack: vi.fn(async (_id: string, on: boolean) => (state = { ...state, enabled: on })),
    unitySetup: vi.fn(async () => READY),
    unityPickProject: vi.fn(async () => READY),
    unityOpenHub: vi.fn(async () => ({ ok: true, opened: "hub" as const })),
    unityDrafts: vi.fn(async () => ({
      drafts: [
        { name: "find_large_meshes", title: "큰 메시 찾기", description: "", risk: "L1", findings: [], author: "Claude",
          verified: true, failure: "", ran_at: 1 },
        { name: "fix_names", title: "이름 고치기", description: "", risk: "L2",
          findings: [{ line: 12, what: "에셋 바꾸기·저장", code: "AssetDatabase.RenameAsset(p, n);" }], author: "Codex",
          verified: false, failure: "compile_error", ran_at: 1 },
      ],
      recipes: ["missing_references", "texture_audit"],
      recipe_cards: CARDS,
    })),
    unityDraftAction: vi.fn(async () => ({ ok: true })),
  } as unknown as JarvisClient;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function flush(): Promise<void> {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

it("꺼져 있으면 읽는 것·쓰는 것·실행하는 것·인터넷을 먼저 보여 주고, 마법사는 안 뜬다", async () => {
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();
  const text = container.textContent ?? "";
  for (const label of ["읽는 것", "쓰는 것", "실행하는 것", "인터넷", "Unity.exe — 배치 모드", "쓰지 않는다"]) {
    expect(text).toContain(label);
  }
  expect(text).toContain("동의");
  expect(container.querySelector("[data-testid=unity-wizard]")).toBeNull();
  expect(client.unitySetup).not.toHaveBeenCalled();
});

it("켜기를 누르면 마법사가 유니티를 찾아 다음 할 일 한 줄을 보여 준다", async () => {
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();
  const button = [...container.querySelectorAll("button")].find((node) => node.textContent === "켜기")!;
  await act(async () => button.click());
  await flush();
  expect(client.setPack).toHaveBeenCalledWith("game", true);
  const wizard = container.querySelector("[data-testid=unity-wizard]");
  expect(wizard).not.toBeNull();
  const text = wizard?.textContent ?? "";
  expect(text).toContain("6000.6.3f1");
  expect(text).toContain("허락됨");
  expect(text).toContain("준비됐습니다");
  expect(text).toContain("파일 내용은 열어 보지 않습니다");
});

it("권한 줄은 인터넷을 참·거짓으로 줘도 말로 바꾼다", () => {
  const lines = permissionLines({ ...GAME, permissions: { ...GAME.permissions, network: false } });
  expect(lines.find((line) => line.label === "인터넷")?.value).toBe("쓰지 않습니다");
});

it("클로드·코덱스 초안이 보이고, 성공한 것만 등록 단추가 살아 있고, 바꾸는 코드는 줄까지 보인다", async () => {
  state = { ...GAME, enabled: true };
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();
  await flush();
  const collab = container.querySelector("[data-testid=unity-collab]");
  expect(collab).not.toBeNull();
  const text = collab?.textContent ?? "";
  expect(text).toContain("클로드·코덱스와 같이 쓰기");
  expect(text).toContain("큰 메시 찾기");
  expect(text).toContain("읽기만 함");
  expect(text).toContain("바꾸는 코드 1줄");
  expect(text).toContain("12줄 · 에셋 바꾸기·저장");
  // 쓸 수 있는 것의 목록은 이 칸이 아니라 「바로 시킬 수 있는 점검」이 제목으로 보여 준다(아래 시험).
  expect(text).not.toContain("missing_references");
  const promote = [...(collab?.querySelectorAll("button") ?? [])].filter((node) => node.textContent === "레시피로 등록");
  expect(promote).toHaveLength(2);
  expect((promote[0] as HTMLButtonElement).disabled).toBe(false);
  expect((promote[1] as HTMLButtonElement).disabled).toBe(true);
  await act(async () => (promote[0] as HTMLButtonElement).click());
  await flush();
  expect(client.unityDraftAction).toHaveBeenCalledWith("find_large_meshes", "promote");
});

// ── 게임 팩을 처음 켠 사람 (2026-10-12) — 무엇을 해 주는지 · 뭐라고 말하면 되는지가 화면에 있다 ──────────────

it("맨 위에 이 팩으로 할 수 있는 일이 있고, 점검은 파일 이름이 아니라 제목 · 한 줄 · 말할 문장으로 보인다", async () => {
  state = { ...GAME, enabled: true };
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();
  await flush();
  const wizard = container.querySelector("[data-testid=unity-wizard]")!;
  expect(wizard.firstElementChild?.getAttribute("data-testid")).toBe("unity-intro");
  expect(wizard.firstElementChild?.textContent).toContain("이 팩으로 할 수 있는 일");

  const checks = container.querySelector("[data-testid=unity-checks]")!;
  const text = checks.textContent ?? "";
  expect(text).toContain("빠진 참조 찾기");
  expect(text).toContain("「Missing」으로 뜨는 칸을 한 번에 찾습니다.");
  expect(text).toContain("「유니티 프로젝트에서 빠진 참조 찾아 줘」");
  expect(text).not.toContain("missing_references");
  expect(text).not.toContain("마치면 쓸 수 있습니다");
  // 처음 쓰는 사람의 순서: 바로 시킬 수 있는 것이 「클로드·코덱스와 같이 쓰기」보다 먼저다.
  const collab = container.querySelector("[data-testid=unity-collab]")!;
  expect(checks.compareDocumentPosition(collab) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("점검의 「복사」는 그 문장을 그대로 복사하고, 문장이 없는 점검에는 복사 칸이 없다", async () => {
  const writeText = vi.fn(async () => undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  state = { ...GAME, enabled: true };
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();
  await flush();
  const rows = [...container.querySelectorAll("[data-testid=unity-checks] .unity-check")];
  expect(rows).toHaveLength(3);
  await act(async () => (rows[1].querySelector("button") as HTMLButtonElement).click());
  await flush();
  expect(writeText).toHaveBeenCalledWith("유니티 프로젝트 텍스처 점검해 줘");
  expect(rows[1].textContent).toContain("복사됨");
  expect(rows[0].textContent).not.toContain("복사됨");
  expect(rows[2].textContent).toContain("큰 메시 찾기 (등록)");
  expect(rows[2].querySelector("button")).toBeNull();
});

it("준비가 덜 됐으면 점검 칸이 「바로 위 상자의 일을 마치면 쓸 수 있다」고 말한다", async () => {
  state = { ...GAME, enabled: true };
  (client.unitySetup as ReturnType<typeof vi.fn>).mockImplementation(async () => ({
    ...READY, license: false, next: { kind: "open_hub", text: "라이선스가 안 보입니다. 허브에 로그인하면 개인용 무료 라이선스를 받을 수 있습니다." },
  }));
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();
  await flush();
  expect(container.querySelector("[data-testid=unity-checks]")?.textContent).toContain("바로 위 상자에 적힌 일을 마치면 쓸 수 있습니다.");
});

it("예전 백엔드가 점검 카드를 안 줘도 화면이 서 있다 — 그 칸만 없다", async () => {
  state = { ...GAME, enabled: true };
  (client.unityDrafts as ReturnType<typeof vi.fn>).mockImplementation(async () => ({ drafts: [], recipes: ["texture_audit"] }));
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();
  await flush();
  expect(container.querySelector("[data-testid=unity-checks]")).toBeNull();
  expect(container.querySelector("[data-testid=unity-collab]")).not.toBeNull();
});

// ── 내 스킬팩 (2026-10-11) — 받은 폴더를 넣는 자리를 단추 하나로 열고, 넣은 뒤 다시 읽는다 ──────────────

const MINE: PackInfo = {
  id: "price-watch-demo", name: "가격 조사 스킬팩", version: "1.0.0", kind: "content",
  summary: "가게 가격 모으기", description: "", tools: [], skills: ["price-watch"], domains: [],
  permissions: { reads: [], writes: [], runs: [], network: "손자리가 여는 페이지만" },
  bench: "", enabled: false, origin: "user", triggers: { "price-watch": ["가격 조사", "가격조사"] },
};

function button(label: string): HTMLButtonElement {
  return [...container.querySelectorAll("button")].find((node) => node.textContent?.trim() === label) as HTMLButtonElement;
}

it("「내 스킬팩 넣기」를 누르면 스킬팩 폴더가 열린다 — 경로를 보내지 않고 이름만 보낸다", async () => {
  const openFolder = vi.fn(async () => ({ ok: true, path: "C:/Users/me/Documents/Sonjari/skillpacks" }));
  Object.assign(client, {
    openFolder,
    listPacks: vi.fn(async () => ({ packs: [state], problems: [], user_dir: "C:/Users/me/Documents/Sonjari/skillpacks" })),
  });
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();

  expect(container.textContent).toContain("C:/Users/me/Documents/Sonjari/skillpacks");
  await act(async () => button("내 스킬팩 넣기").click());
  await flush();

  expect(openFolder).toHaveBeenCalledWith("skillpacks");
});

it("폴더를 넣고 「다시 읽기」를 누르면 새 스킬팩이 목록에 나타난다", async () => {
  const rescanPacks = vi.fn(async () => ({ packs: [state, MINE], problems: [], user_dir: "C:/skillpacks" }));
  Object.assign(client, { rescanPacks });
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();
  expect(container.querySelector("[data-testid=pack-price-watch-demo]")).toBeNull();

  await act(async () => button("다시 읽기").click());
  await flush();

  expect(rescanPacks).toHaveBeenCalledTimes(1);
  const card = container.querySelector("[data-testid=pack-price-watch-demo]");
  expect(card?.textContent).toContain("가격 조사 스킬팩");
  expect(card?.textContent).toContain("직접 넣은 스킬팩");
  expect(card?.textContent).toContain("가격 조사 · 가격조사");
});

it("팩이 내 말 뒤에 붙이는 문장을 켜기 전에 보여 준다 — 모르는 사이에 요청이 바뀌면 안 된다", async () => {
  const ask = "말한 상품을 스킬에 적힌 가게마다 찾아 판매 가격과 배송비를 엑셀 파일로 정리해 줘";
  Object.assign(client, {
    listPacks: vi.fn(async () => ({ packs: [{ ...MINE, asks: { "price-watch": ask } }], problems: [] })),
  });
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();

  const card = container.querySelector("[data-testid=pack-price-watch-demo]");
  expect(card?.textContent).toContain("내 말 뒤에 이 문장을 붙입니다");
  expect(card?.textContent).toContain(ask);
  expect(container.querySelector("[data-testid=pack-game]")).toBeNull();
});

it("팩이 그 일을 어떤 일로 다루게 하는지 켜기 전에 보여 준다 — 도구와 검사가 달라진다", async () => {
  Object.assign(client, {
    listPacks: vi.fn(async () => ({ packs: [{ ...MINE, work: { "price-watch": "web" } }], problems: [] })),
  });
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();

  const card = container.querySelector("[data-testid=pack-price-watch-demo]");
  expect(card?.textContent).toContain("이런 일로 다룹니다");
  expect(card?.textContent).toContain("웹을 보고 와서 정리하는 일");
  expect(card?.textContent).toContain("숫자를 읽은 자료와 대조합니다");
});

it("일의 갈래를 적지 않은 팩에는 그 줄이 없다", async () => {
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();

  expect(container.textContent).not.toContain("이런 일로 다룹니다");
});

it("우리와 같이 온 팩에는 「직접 넣은」 표시가 없다", async () => {
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();

  expect(container.querySelector("[data-testid=pack-game]")?.textContent).not.toContain("직접 넣은 스킬팩");
});

it("폴더를 못 열었으면 그렇다고 말한다", async () => {
  Object.assign(client, { openFolder: vi.fn(async () => { throw new Error("backend_503"); }) });
  await act(async () => root.render(<PacksSection client={client} />));
  await flush();

  await act(async () => button("내 스킬팩 넣기").click());
  await flush();

  expect(container.querySelector("[role=alert]")?.textContent).toContain("스킬팩 폴더를 열지 못했습니다");
});
