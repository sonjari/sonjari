// @vitest-environment jsdom
/** 「문제 보내기」 — 보여 주고, 동의 전엔 못 보내고, 보낸 뒤 접수 번호를 말한다 (2026-09-29). */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProblemReportDialog, type ProblemReportApi } from "./ProblemReportDialog";

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

type SendResult = { ok: boolean; id?: string; error?: string };

function api(
  send = vi.fn(async (): Promise<SendResult> => ({ ok: true, id: "abc123" })),
): ProblemReportApi & { reportSend: typeof send } {
  return {
    reportPreview: vi.fn(async () => ({ id: "p1", text: "{\n  \"jobs\": [\"스크린샷 타임아웃\"]\n}", to: "https://x" })),
    reportSend: send,
  };
}

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });
const sendButton = () => [...container.querySelectorAll("button")].find((b) => b.textContent?.includes("보내기")) as HTMLButtonElement;

it("보낼 내용을 그대로 보여 주고, 동의 전에는 보내기를 막는다", async () => {
  const fake = api();
  act(() => root.render(<ProblemReportDialog api={fake} onClose={() => {}} />));
  await flush();
  expect(container.querySelector(".report-preview")?.textContent).toContain("스크린샷 타임아웃");
  expect(sendButton().disabled).toBe(true);
  act(() => sendButton().click());
  expect(fake.reportSend).not.toHaveBeenCalled();
});

it("동의하면 미리보기 번호로 보내고 접수 번호를 말한다", async () => {
  const fake = api();
  act(() => root.render(<ProblemReportDialog api={fake} onClose={() => {}} />));
  await flush();
  const box = container.querySelector(".report-consent input") as HTMLInputElement;
  act(() => box.click());
  await act(async () => { sendButton().click(); });
  await flush();
  expect(fake.reportSend).toHaveBeenCalledWith("p1", "", true);
  expect(container.textContent).toContain("보냈습니다");
  expect(container.textContent).toContain("abc123");
});

it("서버가 막으면 이유를 사람 말로 말한다", async () => {
  const fake = api(vi.fn(async (): Promise<SendResult> => ({ ok: false, error: "http_429" })));
  act(() => root.render(<ProblemReportDialog api={fake} onClose={() => {}} />));
  await flush();
  act(() => (container.querySelector(".report-consent input") as HTMLInputElement).click());
  await act(async () => { sendButton().click(); });
  await flush();
  expect(container.querySelector(".report-error")?.textContent).toContain("너무 많이");
});
