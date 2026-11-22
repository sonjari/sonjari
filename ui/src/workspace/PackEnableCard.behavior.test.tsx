// @vitest-environment jsdom
/**
 * 팩 켜기 카드 · 결과 한 줄(2026-11-16 · ADR-PACK-1).
 *
 * 맥 실측: 일반 승인 카드로 떨어져 「미리보기 없음 + 날것 값」만 보였고, 누른 뒤 켜졌는지 몰랐다.
 * - 카드: 이름 · 하는 일 · 왜 · 권한 넷 · 받을 크기. 「맡기기」 칸은 바깥 클로드가 청한 카드에만.
 * - 결과 한 줄: 켜짐(도구 수 · 끄기) · 켜지 않음.
 */
import { createRef, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PackEnableCard, PackResultLine } from "./DecisionCards";
import type { Approval } from "../types";

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

const card = (jobId = ""): Approval => ({
  nonce: "n1",
  job_id: jobId,
  tool_name: "sonjari_pack_request",
  arguments: { pack: "animator", why: "팔 뚫림을 고치려고" },
  target: {
    kind: "pack_enable", pack: "animator", name: "애니메이터 팩", summary: "동작을 같이 고친다.",
    permissions: { reads: ["~/Documents/Sonjari/animator 아래"], writes: ["작업 폴더"], runs: ["블렌더"], network: "켤 때 받지 않음" },
    tools: 13, download: "받을 모델 없음", why: "팔 뚫림을 고치려고",
  },
});

const button = (label: string) =>
  [...container.querySelectorAll("button")].find((el) => el.textContent?.includes(label)) as HTMLButtonElement;

it("카드는 하는 일 · 왜 · 권한 넷 · 크기를 보이고, 날것 값(JSON)을 보이지 않는다", () => {
  act(() => root.render(<PackEnableCard approval={card()} busy={false} cardRef={createRef()} onDecide={vi.fn()} />));
  const text = container.textContent ?? "";
  expect(text).toContain("애니메이터 팩을 켤까요?");
  expect(text).toContain("도구 13개");
  expect(text).toContain("클로드가 청함");
  expect(text).toContain("~/Documents/Sonjari/animator 아래");
  expect(text).toContain("켤 때 받지 않음");
  expect(text).toContain("받을 모델 없음");
  expect(container.querySelectorAll(".pack-ask-perms dt")).toHaveLength(4);
  expect(text).not.toContain("\"pack\"");
  expect(text).not.toContain("미리보기가 없습니다");
});

it("켜기는 (true, false) · 「켜고 맡기기」 단추는 (true, true) · 켜지 않기는 (false, false)", () => {
  // 11-16 맥 실측: 작은 체크 칸은 못 찾았다 — 맡김은 가로 단추 하나로.
  const onDecide = vi.fn();
  act(() => root.render(<PackEnableCard approval={card()} busy={false} cardRef={createRef()} onDecide={onDecide} />));
  expect(container.querySelector("input[type=checkbox]")).toBeNull();
  act(() => button("애니메이터 팩 켜기").click());
  expect(onDecide).toHaveBeenLastCalledWith(true, false);
  act(() => button("앞으로 팩 켜기는 클로드에게 맡기기").click());
  expect(onDecide).toHaveBeenLastCalledWith(true, true);
  act(() => button("켜지 않기").click());
  expect(onDecide).toHaveBeenLastCalledWith(false, false);
});

it("손자리 안 모델이 청한 카드에는 맡기기 칸이 없다(맡김은 바깥 클로드만)", () => {
  const onDecide = vi.fn();
  act(() => root.render(<PackEnableCard approval={card("job-1")} busy={false} cardRef={createRef()} onDecide={onDecide} />));
  expect(container.querySelector(".pack-ask-delegate")).toBeNull();
  expect(container.textContent).toContain("손자리가 청함");
  act(() => button("애니메이터 팩 켜기").click());
  expect(onDecide).toHaveBeenLastCalledWith(true, false);
});

it("결과 한 줄: 켜짐은 도구 수와 끄기, 켜지 않음은 다시 청하지 않는다는 말", () => {
  const onUndo = vi.fn();
  act(() => root.render(<PackResultLine name="애니메이터 팩" state="on" toolCount={13} delegated onUndo={onUndo} onClose={vi.fn()} />));
  expect(container.textContent).toContain("애니메이터 팩 켜짐 · 도구 13개");
  expect(container.textContent).toContain("맡김 설정대로");
  act(() => button("끄기").click());
  expect(onUndo).toHaveBeenCalledOnce();
  act(() => root.render(<PackResultLine name="애니메이터 팩" state="declined" onClose={vi.fn()} />));
  expect(container.textContent).toContain("애니메이터 팩을 켜지 않았습니다");
  expect(container.textContent).toContain("다시 청하지 않습니다");
  expect(button("끄기")).toBeUndefined();
});
