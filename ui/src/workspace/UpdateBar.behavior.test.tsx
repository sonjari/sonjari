// @vitest-environment jsdom
/**
 * 켜 둔 뒤 올라간 새 판이 **창으로 돌아오면 보인다** (2026-09-20 노트북 실측).
 *
 * 노트북 241판: 백엔드는 `available: true`(241 → 250)인데 화면에는 버튼이 없었다 — 화면은 켤 때와 20분마다만
 * 물었고, 250 은 켜 둔 뒤에 올라갔다. 사람은 최대 20분 동안 새 판을 못 본다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import { UpdateBar } from "./UpdateBar";

vi.mock("../backend", () => ({ isTauri: () => false }));

let root: Root;
let container: HTMLDivElement;
let answers: Array<Record<string, unknown>>;
let client: JarvisClient;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  answers = [
    { ok: true, enabled: true, kind: "store", available: false, mine: "0.4.26263.241" },
    { ok: true, enabled: true, kind: "store", available: true, mine: "0.4.26263.241", theirs: "0.4.26263.250" },
  ];
  client = { checkUpdate: vi.fn(async () => answers.shift() ?? answers.at(-1)) } as unknown as JarvisClient;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

it("창으로 돌아오면 다시 물어 새 판 버튼을 띄운다", async () => {
  await act(async () => root.render(<UpdateBar client={client} />));
  expect(container.textContent).not.toContain("지금 업데이트");
  vi.setSystemTime(Date.now() + 61_000);
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  expect(client.checkUpdate).toHaveBeenCalledTimes(2);
  expect(container.textContent).toContain("지금 업데이트");
});

it("창을 자주 오가도 1분에 한 번만 묻는다", async () => {
  await act(async () => root.render(<UpdateBar client={client} />));
  await act(async () => { window.dispatchEvent(new Event("focus")); window.dispatchEvent(new Event("focus")); });
  expect(client.checkUpdate).toHaveBeenCalledTimes(1);
});

// ── 2026-10-05 AWS 영어 윈도우 첫 실행: 「지금 업데이트」가 2초 만에 실패했는데 4분을 「업데이트하는 중」으로 서 있었다 ──
//
// 채널이 403 을 줬다(데이터센터·일부 회사망). 도우미는 결과 파일에 실패를 바로 적었지만 화면은 그걸 안 봤고,
// 4분 뒤 「껐다 켜면 윈도우가 마저 바꿉니다」라고 했다 — 끝날 일이 아니었다.

it("업데이트가 실패로 끝나면 덮개를 바로 걷고 왜 안 됐는지 말한다", async () => {
  const { updateFailureText } = await import("./UpdateBar");
  const windowsSaid = "Deployment failed with HRESULT: 0x80190193, Forbidden (403).\r\n\r\nForbidden (403).";
  const available = { ok: true, enabled: true, kind: "store", available: true, mine: "0.4.26278.218", theirs: "0.4.26278.346" };
  const failed = { ...available, just_updated: { ok: false, from: "0.4.26278.218", to: "0.4.26278.346", installed: "0.4.26278.218", error: windowsSaid } };
  // 실패가 **언제** 적히는지는 시험이 정한다. 전에는 응답 순서(첫 번째만 성공)에 맡겼는데, 5ms 뒤 두 번째 응답이 와서
  // 기계가 바쁘면(전체 시험을 같이 돌릴 때) 「업데이트하는 중」을 보기도 전에 실패 화면이 됐다(2026-10-05 1/332 실패).
  let helperWroteFailure = false;
  const failing = {
    checkUpdate: vi.fn(async () => (helperWroteFailure ? failed : available)),
    applyUpdate: vi.fn(async () => ({ ok: true, applied: true })),
  } as unknown as JarvisClient;

  await act(async () => root.render(<UpdateBar client={failing} storePollMs={5} />));
  const go = [...container.querySelectorAll("button")].find((button) => button.textContent === "지금 업데이트");
  expect(go).toBeTruthy();
  await act(async () => { go!.click(); });
  expect(container.textContent).toContain("업데이트하는 중입니다");

  helperWroteFailure = true;
  await act(async () => { await new Promise((wake) => setTimeout(wake, 120)); });

  expect(container.textContent).not.toContain("업데이트하는 중입니다");
  expect(container.textContent).toContain("업데이트하지 못했습니다");
  expect(container.textContent).toContain("업데이트 주소가 막혀 있습니다(403)");
  expect(container.textContent).not.toContain("HRESULT");
  expect(updateFailureText("")).toBe("원인을 알 수 없습니다");
  expect(updateFailureText("The package could not be opened.\r\nmore")).toBe("The package could not be opened.");
});
