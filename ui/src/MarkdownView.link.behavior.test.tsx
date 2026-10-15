// @vitest-environment jsdom
/**
 * 답 속 링크 (2026-09-29 대표 실사용) — 데스크톱 앱에서 「AWS EC2 대시보드 열기」를 눌러도 아무 반응이 없었다.
 * 09-29 에는 손자리 크롬 새 탭으로 열었는데, 2026-10-01 밤 베타 테스터 노트북에서 「표의 링크를 눌러도 안 된다」 —
 * 무대 모드(크롬이 화면 밖)·크롬이 안 뜬 때는 아무것도 안 보였다. 이제 **기본 브라우저**로 연다(`open_external_url`).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const invoke = vi.fn(async (_cmd: string, _args?: unknown) => undefined);
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args?: unknown) => invoke(cmd, args) }));
vi.mock("./backend", () => ({ isTauri: () => true }));

import { MarkdownView } from "./MarkdownView";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  invoke.mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

async function click(markdown: string): Promise<{ prevented: boolean; windowOpen: ReturnType<typeof vi.fn> }> {
  const windowOpen = vi.fn();
  vi.spyOn(window, "open").mockImplementation(windowOpen as unknown as typeof window.open);
  act(() => root.render(<MarkdownView>{markdown}</MarkdownView>));
  const anchor = host.querySelector("a") as HTMLAnchorElement;
  const event = new MouseEvent("click", { bubbles: true, cancelable: true });
  await act(async () => { anchor.dispatchEvent(event); await Promise.resolve(); await Promise.resolve(); });
  return { prevented: event.defaultPrevented, windowOpen };
}

it("opens a web link in the default browser instead of doing nothing", async () => {
  const { prevented, windowOpen } = await click("👉 [AWS EC2 대시보드 열기](https://console.aws.amazon.com/ec2/home)");
  expect(prevented).toBe(true);
  expect(invoke).toHaveBeenCalledWith("open_external_url", { url: "https://console.aws.amazon.com/ec2/home" });
  expect(windowOpen).not.toHaveBeenCalled();
});

it("a link inside a table opens too, even without https://", async () => {
  const { prevented } = await click("| 회사 | 주소 |\n|---|---|\n| (주)두레 | [링크](www.saramin.co.kr/zf_user/jobs/view?rec_idx=1) |");
  expect(prevented).toBe(true);
  expect(invoke).toHaveBeenCalledWith("open_external_url", { url: "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=1" });
});

it("falls back to window.open when the app cannot open it", async () => {
  invoke.mockRejectedValueOnce(new Error("no"));
  const { windowOpen } = await click("[열기](https://example.com/)");
  expect(windowOpen).toHaveBeenCalledWith("https://example.com/", "_blank", "noreferrer");
});

it("leaves non-web links alone", async () => {
  const { prevented } = await click("[메일](mailto:someone@example.com)");
  expect(prevented).toBe(false);
  expect(invoke).not.toHaveBeenCalled();
});
