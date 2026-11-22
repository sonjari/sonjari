// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { PrefillLine, splitPrefillMessage } from "./PrefillLine";

const LINE = "쓸 도구와 지침을 읽는 중 · 62% · 30초쯤 남음 · 처음 한 번만 걸려요";

it("백엔드 한 줄을 제목 · 남은 시간 · 아래 한 줄로 나눈다(11-18)", () => {
  expect(splitPrefillMessage(LINE)).toEqual({ title: "쓸 도구와 지침을 읽는 중", left: "30초쯤 남음", note: "처음 한 번만 걸려요" });
  expect(splitPrefillMessage("쓸 도구와 지침을 읽는 중 · 12% · 처음 한 번만 걸려요").left).toBe("");
});

it("막대는 진행률 그대로 · 퍼센트 숫자와 토큰 수는 글에 안 쓴다(디자인 검토)", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => { root.render(<PrefillLine prefill={{ fraction: 0.62, message: LINE }} />); });
  const bar = host.querySelector("[role=progressbar]")!;
  expect(bar.getAttribute("aria-valuenow")).toBe("62");
  expect(bar.textContent).toContain("30초쯤 남음");
  expect(bar.textContent).toContain("처음 한 번만 걸려요");
  expect(bar.textContent).not.toContain("62%");
  expect(bar.textContent).not.toContain("토큰");
  expect((host.querySelector(".workspace-load-track span") as HTMLElement).style.width).toBe("62%");
  await act(async () => root.unmount());
});
