// @vitest-environment jsdom
/**
 * 설정 › 디스코드로 일 시키기 (2026-10-18) — 단계는 백엔드 stage 로 그리고, 토큰은 화면을 지나지 않는다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import type { DiscordAccessRequest, DiscordStatus, DiscordStepResult } from "../types";
import { CONNECTING_POLL_MAX, CONNECTING_POLL_MS, currentStep, DiscordSection, DiscordRequestBanner } from "./DiscordSection";

const opened: string[] = [];
vi.mock("../backend", () => ({ openExternalUrl: vi.fn(async (url: string) => { opened.push(url); }) }));

const BASE: DiscordStatus = {
  enabled: true, installed: true, token_saved: false, running: false, connected: false, owner_process: "",
  stage: "no_token", bot_name: "", app_id: "", message_content: null, servers: null, checked_at: null,
  home_channel_id: "", home_channel_name: "", allowed_user_ids: 0, invite_url: "",
  portal_url: "https://discord.com/developers/applications", portal_bot_url: "", last_error: "",
  default_model_alias: "", aliases: [], user_install_url: "", user_install_enabled: false, servers_note: "", pending_requests: 0,
};

const KNOWN: Partial<DiscordStatus> = {
  token_saved: true, bot_name: "손자리봇", app_id: "123", message_content: true,
  invite_url: "https://discord.com/oauth2/authorize?client_id=123&scope=bot",
  portal_bot_url: "https://discord.com/developers/applications/123/bot",
  user_install_url: "https://discord.com/oauth2/authorize?client_id=123&integration_type=1",
};

const REQUEST: DiscordAccessRequest = {
  user_id: "555", display_name: "나래", username: "narae", first_seen: 1, first_text: "안녕 손자리", count: 2, last_seen: 2,
};

let root: Root;
let container: HTMLDivElement;
let status: DiscordStatus;
let client: JarvisClient;
let calls: Record<string, ReturnType<typeof vi.fn>>;

function step(extra: Partial<DiscordStepResult> = {}): DiscordStepResult {
  return { ...status, ok: true, error: "", message: "", ...extra };
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  opened.length = 0;
  status = { ...BASE };
  calls = {
    discordStatus: vi.fn(async () => status),
    discordTokenFromClipboard: vi.fn(async () => step()),
    discordRecheck: vi.fn(async () => step()),
    discordFinish: vi.fn(async () => step()),
    discordDisconnect: vi.fn(async () => step()),
    discordSetDefaultModel: vi.fn(async (alias: string) => { status = { ...status, default_model_alias: alias }; return step(); }),
    discordRequests: vi.fn(async () => ({ requests: [] as DiscordAccessRequest[], ignored_count: 0 })),
    discordDecideRequest: vi.fn(async () => ({ ...step(), requests: [], ignored_count: 0 })),
    getModelAliases: vi.fn(async () => ({ pc_model: "qwen:27b", aliases: [] })),
    putModelAliases: vi.fn(),
  };
  client = calls as unknown as JarvisClient;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

async function render(node: React.ReactNode) {
  await act(async () => { root.render(node); });
  await act(async () => { await Promise.resolve(); });
}

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((el) => el.textContent?.trim().startsWith(label));
  if (!found) throw new Error(`단추 없음: ${label}\n${container.textContent}`);
  return found as HTMLButtonElement;
}

async function click(label: string) {
  await act(async () => { button(label).click(); });
  await act(async () => { await Promise.resolve(); });
}

it("처음엔 소개와 「연결 시작」 — 누르면 봇 만들기 단계, 토큰 입력칸은 어디에도 없다", async () => {
  await render(<DiscordSection client={client} />);
  expect(container.textContent).toContain("폰 디스코드로 손자리에게 일을 시킵니다.");
  expect(container.textContent).toContain("디스코드 서버를 지납니다");
  expect(container.querySelector(".discord-steps")).toBeNull();
  await click("연결 시작");
  expect(container.querySelector('.discord-step.is-current')?.textContent).toContain("봇 만들기");
  expect(container.textContent).toContain("이메일 인증을 먼저");
  expect(container.querySelectorAll("input, textarea")).toHaveLength(0);
  await click("개발자 포털 열기");
  expect(opened).toEqual(["https://discord.com/developers/applications"]);
});

it("「토큰을 복사했어요」는 본체에 클립보드를 읽게 하고, Application ID 를 복사했으면 Bot 페이지 토큰을 말한다", async () => {
  calls.discordTokenFromClipboard.mockImplementation(async () => step({ ok: false, error: "application_id", message: "복사하신 것은 숫자만 있습니다." }));
  await render(<DiscordSection client={client} />);
  await click("연결 시작");
  await click("토큰을 복사했어요");
  expect(calls.discordTokenFromClipboard).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("복사하신 것은 숫자만 있습니다.");
  expect(container.textContent).toContain("General Information 의 숫자가 아니라 Bot 페이지의 토큰을 복사해 주세요.");
});

it("들이기 단계는 「내 서버에 초대」 하나 — 사용자 설치 링크는 띄우지 않는다(10-18 실측)", async () => {
  status = { ...BASE, ...KNOWN, stage: "need_invite", servers: 0 } as DiscordStatus;
  await render(<DiscordSection client={client} />);
  expect(container.querySelector('.discord-step.is-current')?.textContent).toContain("내 서버에 들이기");
  expect(container.textContent).toContain("서버가 없으면 먼저 하나 만들기");
  expect(container.textContent).not.toContain("내 계정에 추가");
  await click("디스코드 열기");
  await click("내 서버에 초대");
  expect(opened).toEqual(["https://discord.com/channels/@me", KNOWN.invite_url]);
  expect(opened).not.toContain(KNOWN.user_install_url);
});

it("사용자 설치가 켜진 앱이라 백엔드가 ready_to_finish 를 줘도 서버 0곳이면 들이기에 머문다", async () => {
  const shaky = { ...BASE, ...KNOWN, stage: "ready_to_finish", servers: 0, user_install_enabled: true } as DiscordStatus;
  expect(currentStep(shaky)).toBe("invite");
  expect(currentStep({ ...shaky, servers: 1 })).toBe("finish");
  expect(currentStep({ ...shaky, servers: null })).toBe("finish");
  status = shaky;
  calls.discordRecheck.mockImplementation(async () => step({ message: "사용자 설치로 쓰시는 중이면 그대로 마무리하셔도 됩니다." }));
  await render(<DiscordSection client={client} />);
  await click("다 했어요");
  expect(calls.discordFinish).not.toHaveBeenCalled();
  expect(container.textContent).not.toContain("그대로 마무리하셔도");
  expect(container.textContent).toContain("봇이 아직 어느 서버에도 없어요");
});

it("「다 했어요」 뒤 서버에 들어갔으면 바로 마무리한다", async () => {
  status = { ...BASE, ...KNOWN, stage: "need_invite", servers: 0 } as DiscordStatus;
  calls.discordRecheck.mockImplementation(async () => { status = { ...status, stage: "ready_to_finish", servers: 1 }; return step(); });
  calls.discordFinish.mockImplementation(async () => {
    status = { ...status, stage: "connected", connected: true, running: true, owner_process: "self", home_channel_name: "일반", allowed_user_ids: 1 };
    return step({ home_channel_auto: true, welcome_sent: true });
  });
  await render(<DiscordSection client={client} />);
  await click("다 했어요");
  expect(calls.discordFinish).toHaveBeenCalledTimes(1);
  const card = container.querySelector('[data-testid="discord-connected"]');
  expect(card?.textContent).toContain("손자리봇");
  expect(card?.textContent).toContain("#일반");
  expect(card?.textContent).toContain("홈 채널을 #일반 로 정했어요.");
});

it("연결됨 — 기본 모델을 고르면 저장하고, 끊기는 한 번 더 묻는다", async () => {
  status = {
    ...BASE, ...KNOWN, stage: "connected", connected: true, running: true, owner_process: "self", servers: 1,
    allowed_user_ids: 2, aliases: [{ alias: "빠른", tag: "qwen:4b", note: "" }],
  } as DiscordStatus;
  await render(<DiscordSection client={client} />);
  const select = container.querySelector<HTMLSelectElement>("#discord-default-model")!;
  expect([...select.options].map((o) => o.textContent)).toEqual(["PC 와 같음", "빠른 · qwen:4b"]);
  expect(container.textContent).toContain("네이버에서 오늘 서울 날씨 찾아 줘");
  await act(async () => {
    select.value = "빠른";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(calls.discordSetDefaultModel).toHaveBeenCalledWith("빠른");
  await click("연결 끊기");
  expect(calls.discordDisconnect).not.toHaveBeenCalled();
  await click("정말 끊기");
  expect(calls.discordDisconnect).toHaveBeenCalledTimes(1);
});

it("다른 창에서 다리가 돌면 그렇게 말한다", async () => {
  status = { ...BASE, ...KNOWN, stage: "other_process", owner_process: "other", running: true } as DiscordStatus;
  await render(<DiscordSection client={client} />);
  expect(container.textContent).toContain("다른 창에서 다리가 돌고 있어요");
});

it("연결하는 중은 정해진 횟수까지만 다시 읽는다", async () => {
  vi.useFakeTimers();
  status = { ...BASE, ...KNOWN, stage: "connecting", running: true, owner_process: "self", servers: 1 } as DiscordStatus;
  await render(<DiscordSection client={client} />);
  for (let i = 0; i < CONNECTING_POLL_MAX + 5; i++) {
    await act(async () => { vi.advanceTimersByTime(CONNECTING_POLL_MS); });
    await act(async () => { await Promise.resolve(); });
  }
  expect(calls.discordStatus).toHaveBeenCalledTimes(1 + CONNECTING_POLL_MAX);
  expect(container.textContent).toContain("30초가 지나도 아직 붙지 못했어요");
});

it("가족 · 동료 추가 카드 — 앱 아래 알림 자리에서 허용하면 그 사람 ID 로 허용을 보낸다", async () => {
  let waiting = [REQUEST];
  calls.discordRequests.mockImplementation(async () => ({ requests: waiting, ignored_count: 0 }));
  calls.discordDecideRequest.mockImplementation(async () => { waiting = []; return { ...step(), requests: [], ignored_count: 0 }; });
  await render(<DiscordRequestBanner client={client} connected />);
  const card = container.querySelector('[data-testid="discord-request"]');
  expect(card?.textContent).toContain("나래(@narae) 님이 디스코드로 말을 걸었어요");
  expect(card?.textContent).toContain("안녕 손자리");
  await click("허용");
  expect(calls.discordDecideRequest).toHaveBeenCalledWith("555", true);
  expect(container.querySelector('[data-testid="discord-request"]')).toBeNull();
});
