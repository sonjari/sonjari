// @vitest-environment jsdom
/**
 * 「쓰는 법」 쇼 (2026-10-27 대표 · 설계서 generated_reports/usage_show_1027/설계서.md).
 *
 * 지키는 것: 장 넷이 순서대로 · 「예시 화면」 표시 · 안 본 사람에게만 한 번(닫으면 「봤다」) · 메뉴로 다시 열림(기록은 안 건드림) ·
 * 슬로건은 번역하지 않고 두 언어에 같다 · 4장 단추가 설정의 그 칸을 연다 · 영수증 숫자는 날짜 · 하한 표시와 함께.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Sidebar } from "./Sidebar";
import { UsageShowGate, usageSlides } from "./UsageShowGate";
import { UsageShowStage } from "./UsageShow";
import { WhatsNewBar } from "./WhatsNewBar";
import type { JarvisClient } from "../backend";

vi.mock("../backend", () => ({ isTauri: () => false }));

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  vi.useFakeTimers();
  Object.assign(globalThis, {
    IS_REACT_ACT_ENVIRONMENT: true,
    ResizeObserver: class { observe() {} disconnect() {} unobserve() {} },
  });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
  vi.useRealTimers();
});

function fakeClient(show: boolean) {
  return {
    getUsageShow: vi.fn(async () => ({ show, version: 1, seen: show ? 0 : 1 })),
    markUsageShowSeen: vi.fn(async () => ({ ok: true })),
  };
}

const button = (label: string) => [...document.querySelectorAll("button")].find((b) => b.textContent?.trim() === label)!;
const dialog = () => document.querySelector("[role=dialog]");
const press = (key: string) => window.dispatchEvent(new KeyboardEvent("keydown", { key }));

async function mountGate(client: ReturnType<typeof fakeClient>, extra: Partial<Parameters<typeof UsageShowGate>[0]> = {}) {
  const props = { manualOpen: false, onManualClose: vi.fn(), onOpenSettings: vi.fn(), onActiveChange: vi.fn(), ...extra };
  await act(async () => root.render(<UsageShowGate client={client} {...props} />));
  return props;
}

// ── 글 ─────────────────────────────────────────────────────────────────────

it("장 넷의 제목 · 본문은 설계서 그대로다", () => {
  const slides = usageSlides();
  expect(slides.map((slide) => slide.title)).toEqual([
    "손자리는 이 컴퓨터에서 도는 AI 입니다",
    "다른 AI와 일을 나눠 동시에 합니다",
    "클로드 한도를 덜 씁니다",
    "어디서든 부를 수 있습니다",
  ]);
  expect(slides.map((slide) => slide.body)).toEqual([
    "웹 조사, 엑셀 · 한글 · 장표, 코드까지 혼자 끝까지 합니다. 읽은 곳은 붙여 드립니다.",
    "쓰던 AI가 맡긴 일을 이 PC에서 동시에 해냅니다.",
    "읽는 일은 이 PC가 해서, 클로드에는 결과만 갑니다.",
    "어디서 말해도 이 PC의 손자리가 합니다.",
  ]);
  expect(slides.map((slide) => slide.visual && "scene" in slide.visual && slide.visual.scene)).toEqual(["this-pc", "handoff", "limit", "anywhere"]);
  // 대표가 이미 뺀 말: 손자리를 클로드의 도구 · 손 · 조수로 보이게 하는 빗댐
  const all = JSON.stringify(slides);
  for (const banned of ["일꾼", "비서", "조수", "도구", "머리", "부속"]) expect(all).not.toContain(banned);
});

// ── 언제 뜨나 ──────────────────────────────────────────────────────────────

it("안 본 사람에게는 저절로 뜨고, 장 넷이 순서대로 넘어가고, 장마다 「예시 화면」이 붙는다", async () => {
  const client = fakeClient(true);
  const props = await mountGate(client);
  expect(dialog()).not.toBeNull();
  expect(props.onActiveChange).toHaveBeenCalledWith(true);
  const titles: string[] = [];
  for (let i = 0; i < 4; i += 1) {
    titles.push(dialog()?.querySelector("h2")?.textContent ?? "");
    expect(dialog()?.querySelector(".wns-example")?.textContent).toBe("예시 화면");
    if (i < 3) await act(async () => { button("다음").click(); });
  }
  expect(titles).toEqual(usageSlides().map((slide) => slide.title));
  expect(document.querySelectorAll(".wn-dots button")).toHaveLength(4);
});

it("이미 본 사람에게는 안 뜬다", async () => {
  const client = fakeClient(false);
  const props = await mountGate(client);
  expect(dialog()).toBeNull();
  expect(props.onActiveChange).not.toHaveBeenCalled();
});

it("파일럿처럼 설정이 없는 화면에서는 저절로 뜨지 않는다(묻지도 않는다)", async () => {
  const client = fakeClient(true);
  await mountGate(client, { enabled: false });
  expect(client.getUsageShow).not.toHaveBeenCalled();
  expect(dialog()).toBeNull();
});

it("「다 봤어요」 · Esc · 「나중에 보기」 어느 길로 닫아도 한 번 뜬 것으로 적고 다시 안 뜬다", async () => {
  for (const close of [
    () => button("다 봤어요").click(),
    () => press("Escape"),
    () => button("나중에 보기").click(),
  ]) {
    const client = fakeClient(true);
    const props = await mountGate(client);
    await act(async () => { press("ArrowRight"); press("ArrowRight"); press("ArrowRight"); });
    await act(async () => { close(); });
    expect(client.markUsageShowSeen).toHaveBeenCalledTimes(1);
    expect(props.onActiveChange).toHaveBeenLastCalledWith(false);
    await act(async () => root.render(<div />));
    document.body.innerHTML = "";
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  }
});

it("메뉴로 다시 열면 열리고, 이미 본 기록은 건드리지 않는다", async () => {
  const client = fakeClient(false);
  const props = await mountGate(client, { manualOpen: true });
  expect(dialog()).not.toBeNull();
  await act(async () => { button("나중에 보기").click(); });
  expect(props.onManualClose).toHaveBeenCalled();
  expect(client.markUsageShowSeen).not.toHaveBeenCalled();
});

it("사이드바에 「쓰는 법」 항목이 있고 누르면 연다", async () => {
  const onOpenUsageShow = vi.fn();
  await act(async () => root.render(
    <Sidebar open onToggle={() => {}} mode="cowork" onModeChange={() => {}} sessions={[]} sessionId="" connected state="idle" busy={false}
      client={null} jobs={[]} schedules={[]} now={0} onNewConversation={() => {}} onOpenConversation={() => {}} onCancelSchedule={() => {}}
      onOpenCapabilities={() => {}} onOpenSettings={() => {}} onOpenUsageShow={onOpenUsageShow} />,
  ));
  const item = [...container.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === "쓰는 법")!;
  expect(item).toBeTruthy();
  await act(async () => { item.click(); });
  expect(onOpenUsageShow).toHaveBeenCalled();
});

it("쓰는 법이 떠 있는 동안은 「바뀐 것」 줄을 접어 둔다 — 같은 날 둘 다 떠야 하면 쓰는 법이 먼저", async () => {
  const whatsNew = {
    getWhatsNew: vi.fn(async () => ({ show: true, version: "0.4.35.0", changes: "고친 것", tour: "" })),
    markWhatsNewSeen: vi.fn(async () => ({ ok: true })),
  } as unknown as JarvisClient;
  await act(async () => root.render(<WhatsNewBar client={whatsNew} hold />));
  expect(container.textContent).toBe("");
  await act(async () => root.render(<WhatsNewBar client={whatsNew} hold={false} />));
  expect(container.textContent).toContain("0.4.35.0");
});

// ── 장면 ───────────────────────────────────────────────────────────────────

it("1장: 슬로건은 영문 그대로 한 번 크게 서고, 올라앉은 뒤 세 컷이 차례로 지나가 빨간 시험이 초록이 된다 · 촬영 조건이 구석에 있다", async () => {
  await act(async () => root.render(<UsageShowStage scene="this-pc" />));
  expect(container.querySelector(".us-hero.is-on .us-slogan-main")?.textContent).toBe("Watch AI work in your browser.");
  expect(container.querySelector(".us-hero .us-slogan-sub")?.textContent).toBe("Runs on your PC.");
  expect(container.querySelector(".us-hero .us-slogan-note")?.textContent).toBe("크롬, 파일, 엑셀, 한글을 직접 다루고 읽은 곳을 붙여 드립니다.");
  expect(container.querySelector(".us-rail-cond")?.textContent).toContain("RTX 3090 · Qwen3.8 27B");
  // 슬로건 낱말에 「Chrome」을 넣지 않는다(상표 · 엣지도 지원)
  expect(container.querySelector(".us-hero .us-slogan-main")?.textContent).not.toMatch(/chrome/i);

  await act(async () => { vi.advanceTimersByTime(3000); });
  expect(container.querySelector(".us-hero.is-on")).toBeNull();
  expect(container.querySelector(".us-cut.is-active")?.getAttribute("aria-label")).toBe("웹에서 읽기");
  await act(async () => { vi.advanceTimersByTime(3000); });
  expect(container.querySelector(".us-cut.is-active")?.getAttribute("aria-label")).toBe("파일로 받기");
  await act(async () => { vi.advanceTimersByTime(1500); });
  expect(container.querySelector(".us-file.is-on")?.textContent).toContain(".xlsx");
  await act(async () => { vi.advanceTimersByTime(700); });
  expect(container.querySelector(".us-cut.is-active")?.getAttribute("aria-label")).toBe("코드까지 고치기");
  expect(container.querySelector(".us-term.is-red")).not.toBeNull();
  expect(container.textContent).toContain("이 PC에서 생각 중");
  await act(async () => { vi.advanceTimersByTime(3000); });
  expect(container.querySelector(".us-term.is-green")?.textContent).toContain("1개 통과");
});

it("2장: 맡김 → 손자리가 받았습니다 → 두 쪽이 동시에 → 표가 돌아오고 클로드가 마무리한다", async () => {
  await act(async () => root.render(<UsageShowStage scene="handoff" />));
  expect(container.textContent).toContain("경쟁사 가격 조사해서 우리 가격표 페이지 고쳐 줘");
  expect(container.textContent).toContain("기다리는 중");
  await act(async () => { vi.advanceTimersByTime(3000); });
  expect(container.querySelector(".wns-handoff.is-on")).not.toBeNull();
  await act(async () => { vi.advanceTimersByTime(1500); });
  expect(container.textContent).toContain("손자리가 받았습니다");
  expect(container.querySelector(".us-both")?.textContent).toContain("동시에");
  // 동시에: 왼쪽 diff 줄이 생기는 동안 오른쪽이 가격을 읽는다
  expect(container.querySelectorAll(".us-line.is-on").length).toBeGreaterThan(0);
  expect(container.querySelector(".us-rivals li.is-reading, .us-rivals li.is-read")).not.toBeNull();
  await act(async () => { vi.advanceTimersByTime(3200); });
  expect(container.querySelectorAll(".us-rivals li.is-read")).toHaveLength(4);
  expect(container.querySelector(".wns-handoff.is-done")).not.toBeNull();
  await act(async () => { vi.advanceTimersByTime(1500); });
  expect(container.querySelector(".us-line.is-flash")?.textContent).toContain("8,500 ~ 12,000");
  expect(container.querySelector(".us-both")).toBeNull();
});

it("3장: 같은 화면의 다음 박자 — 클로드 막대는 거의 그대로, 이 PC 막대는 차고, 영수증에는 날짜 · 판 · 하한이 붙는다", async () => {
  await act(async () => root.render(<UsageShowStage scene="limit" />));
  // 2장의 이어짐: 처음부터 맡김 줄 · 받았습니다 칸 · 이미 걸린 실
  expect(container.querySelector(".us-hand[data-chapter='3']")).not.toBeNull();
  expect(container.querySelector(".wns-handoff.is-on")).not.toBeNull();
  expect(container.querySelector(".wns-got.is-on")?.textContent).toContain("손자리가 받았습니다");
  expect(container.querySelector(".us-receipt.is-on")).toBeNull();
  await act(async () => { vi.advanceTimersByTime(4300); });
  expect(container.querySelector<HTMLElement>(".us-meter-pc b")?.style.width).toBe("100%");
  expect(container.querySelector(".us-meter-claude b.is-nudged")).not.toBeNull();
  // 막대에는 숫자를 붙이지 않는다
  expect(container.querySelector(".us-meter-claude")?.textContent).toBe("클로드 사용량");
  const receipt = container.querySelector(".us-receipt.is-on");
  expect(receipt?.textContent).toContain("이 PC에서 읽고 클로드로 안 보낸 양");
  expect(receipt?.textContent).toContain("6,401");
  expect(receipt?.textContent).toContain("최소");
  expect(receipt?.textContent).toContain("10월 26일");
  expect(receipt?.textContent).toContain("하한");
});

it("4장: 실 세 가닥이 이 PC 로 모이고, 단추가 설정의 연결 · 디스코드 칸을 연다", async () => {
  const open = vi.fn();
  await act(async () => root.render(<UsageShowStage scene="anywhere" onOpenSettings={open} />));
  expect(container.querySelectorAll(".us-source")).toHaveLength(3);
  await act(async () => { vi.advanceTimersByTime(6000); });
  expect(container.querySelectorAll(".us-pcnode li.is-got")).toHaveLength(3);
  await act(async () => { button("Claude 에 잇기").click(); });
  expect(open).toHaveBeenLastCalledWith("connect");
  await act(async () => { button("디스코드 잇기").click(); });
  expect(open).toHaveBeenLastCalledWith("discord");
});

it("4장에서 단추를 누르면 쇼를 닫고 설정의 그 칸으로 간다", async () => {
  const client = fakeClient(false);
  const props = await mountGate(client, { manualOpen: true });
  await act(async () => { press("ArrowRight"); press("ArrowRight"); press("ArrowRight"); });
  await act(async () => { button("디스코드 잇기").click(); });
  expect(props.onOpenSettings).toHaveBeenCalledWith("discord");
  expect(props.onManualClose).toHaveBeenCalled();
});
