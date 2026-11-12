// @vitest-environment jsdom
/**
 * 설정 › 연결 › 깃허브 연결 (2026-11-12) — 화면은 백엔드 상태를 그리고 단추만 누른다.
 * 코드는 한 글자씩 칸에 · 평문 저장은 숨기지 않고 알림 · 토큰은 안 보임 · 내 gh 로그인은 끊기 단추를 안 줌 · 다시 읽기에 끝이 있음.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import type { GithubStatus } from "../types";
import { GITHUB_POLL_MAX, GITHUB_POLL_MS, GithubSection, githubErrorText } from "./GithubSection";

vi.mock("../backend", async (orig) => ({ ...(await orig<typeof import("../backend")>()), openExternalUrl: vi.fn() }));

const base: GithubStatus = {
  gh: { path: "/x/gh", version: "2.103.3", source: "ours", old: false },
  git: { path: "/usr/bin/git", version: "2.50" },
  login: { logged_in: false, user: "", storage: "", config: "" },
  pending: null,
  supported: true,
};

let root: Root;
let container: HTMLDivElement;

function client(status: GithubStatus, extra: Record<string, unknown> = {}) {
  return {
    githubStatus: vi.fn().mockResolvedValue(status),
    githubInstall: vi.fn().mockResolvedValue({ ok: true }),
    githubLoginStart: vi.fn().mockResolvedValue({ ok: true }),
    githubLoginPoll: vi.fn().mockResolvedValue({ state: "waiting" }),
    githubLogout: vi.fn().mockResolvedValue({ ok: true, changed: true }),
    ...extra,
  } as unknown as JarvisClient & Record<string, ReturnType<typeof vi.fn>>;
}

async function show(c: JarvisClient) {
  await act(async () => { root.render(<GithubSection client={c} />); });
  await act(async () => { await Promise.resolve(); });
}

const button = (name: RegExp) =>
  [...container.querySelectorAll("button")].find((b) => name.test(b.textContent ?? "")) as HTMLButtonElement | undefined;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

it("offers to get gh when it is missing", async () => {
  const c = client({ ...base, gh: null });
  await show(c);
  await act(async () => { button(/gh 받기/)!.click(); });
  expect(c.githubInstall).toHaveBeenCalledTimes(1);
});

it("shows the one-time code one character per cell, readable as a whole", async () => {
  await show(client({ ...base, pending: { code: "AB12-CD34", url: "https://github.com/login/device", expires_in: 900 } }));
  const code = container.querySelector(".gh-code")!;
  expect(code.getAttribute("aria-label")).toBe("일회용 코드 A B 1 2 - C D 3 4");
  expect(code.querySelectorAll(".gh-code-cell")).toHaveLength(8);
  expect(container.textContent).toContain("남은 시간 15:00");
});

it("warns when the sign-in sits in a plain file and never shows a token", async () => {
  await show(client({ ...base, login: { logged_in: true, user: "octo", storage: "file", config: "ours" } }));
  expect(container.textContent).toContain("octo 계정으로 연결됨");
  expect(container.textContent).toContain("암호화되지 않은 파일");
  expect(button(/연결 끊기/)).toBeTruthy();
  expect(container.textContent).not.toMatch(/gh[opsu]_/);
});

it("does not offer to disconnect a gh login that belongs to the user", async () => {
  await show(client({ ...base, login: { logged_in: true, user: "octo", storage: "keyring", config: "user" } }));
  expect(container.textContent).toContain("이미 이 계정으로 로그인돼 있어");
  expect(button(/연결 끊기/)).toBeUndefined();
  expect(button(/다른 계정으로 연결/)).toBeTruthy();
});

it("stops polling after the limit", async () => {
  vi.useFakeTimers();
  const poll = vi.fn().mockResolvedValue({ state: "waiting" });
  await show(client({ ...base, pending: { code: "AB12-CD34", url: "u", expires_in: 900 } }, { githubLoginPoll: poll }));
  for (let i = 0; i < GITHUB_POLL_MAX + 20; i += 1) {
    await act(async () => { await vi.advanceTimersByTimeAsync(GITHUB_POLL_MS); });
  }
  expect(poll.mock.calls.length).toBeLessThanOrEqual(GITHUB_POLL_MAX);
  expect(poll.mock.calls.length).toBeGreaterThan(0);
});

it("turns backend error codes into plain words", () => {
  expect(githubErrorText("gh_checksum_mismatch")).toMatch(/지문과 달라/);
  expect(githubErrorText("gh_not_signed:팀")).toMatch(/서명/);
  expect(githubErrorText("download_failed: ConnectError")).toMatch(/방화벽/);
});
