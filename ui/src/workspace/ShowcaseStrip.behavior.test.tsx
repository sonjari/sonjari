// @vitest-environment jsdom
/**
 * 답이 기댄 페이지 (2026-10-18 대표 결정) — 답 아래 사진 카드. 꾸밈이 아니라 증거다.
 * 비면 아무것도 안 그린다 · 안착한 답에만 붙는다 · 누르면 크게 보기와 「원래 페이지 열기」.
 * 사이트 · 제목은 전부 지어낸 것이다(시험 표본에 실제 값을 넣지 않는다).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationMessage, ShowcaseShot } from "../types";
import { MessageView } from "./MessageView";
import { createShowcaseSource, readClock, ShowcaseStrip, siteName, type ShowcaseSource } from "./ShowcaseStrip";

const SHOTS: ShowcaseShot[] = [
  { path: "C:/x/step_004.jpg", url: "https://www.compare.example/item/k1?sort=price", title: "가상 키보드 K1 최저가", read_at: new Date(2026, 9, 18, 0, 14).getTime() / 1000, matched: 3, step: 4 },
  { path: "C:/x/step_007.jpg", url: "https://maker.example/k1/spec", title: "K1 사양", read_at: new Date(2026, 9, 18, 0, 15).getTime() / 1000, matched: 1, step: 7 },
];

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

function source(shots: ShowcaseShot[], opened: string[] = []): ShowcaseSource {
  return {
    list: vi.fn(async () => shots),
    image: vi.fn(async (_job: string, index: number) => `blob:shot-${index}`),
    open: (url: string) => { opened.push(url); },
  };
}

async function render(node: React.ReactNode) {
  await act(async () => root.render(node));
  // 목록 → 사진 두 단계의 약속을 비운다.
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

describe("ShowcaseStrip", () => {
  it("draws one card per page with site, title, read time and how many answer facts it held", async () => {
    await render(<ShowcaseStrip jobId="job-1" source={source(SHOTS)} />);
    const cards = container.querySelectorAll(".showcase-card");
    expect(cards.length).toBe(2);
    expect(container.querySelector(".showcase-label")?.textContent).toBe("답이 기댄 페이지");
    expect(cards[0].querySelector(".showcase-site")?.textContent).toBe("compare.example");
    expect(cards[0].querySelector(".showcase-title")?.textContent).toBe("가상 키보드 K1 최저가");
    expect(cards[0].querySelector(".showcase-clock")?.textContent).toBe("00:14 읽음");
    expect(cards[0].querySelector(".showcase-matched")?.textContent).toBe("답과 맞은 것 3개");
    expect(cards[0].querySelector("img")?.getAttribute("src")).toBe("blob:shot-0");
  });

  it("draws nothing at all when the job leaned on no page", async () => {
    await render(<ShowcaseStrip jobId="job-1" source={source([])} />);
    expect(container.querySelector(".showcase")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("drops a card whose picture could not be fetched instead of leaving an empty frame", async () => {
    const half: ShowcaseSource = { ...source(SHOTS), image: vi.fn(async (_job: string, index: number) => (index === 0 ? null : "blob:shot-1")) };
    await render(<ShowcaseStrip jobId="job-1" source={half} />);
    const cards = container.querySelectorAll(".showcase-card");
    expect(cards.length).toBe(1);
    expect(cards[0].querySelector(".showcase-site")?.textContent).toBe("maker.example");
  });

  it("opens the larger view on click, and the original page goes to the default browser", async () => {
    const opened: string[] = [];
    await render(<ShowcaseStrip jobId="job-1" source={source(SHOTS, opened)} />);
    await act(async () => (container.querySelector(".showcase-card") as HTMLButtonElement).click());
    const dialog = document.body.querySelector(".showcase-lightbox");
    expect(dialog).not.toBeNull();
    expect(dialog?.querySelector("img")?.getAttribute("src")).toBe("blob:shot-0");
    const openButton = [...(dialog?.querySelectorAll("button") ?? [])].find((button) => button.textContent?.includes("원래 페이지 열기"));
    await act(async () => openButton?.click());
    expect(opened).toEqual(["https://www.compare.example/item/k1?sort=price"]);
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(document.body.querySelector(".showcase-lightbox")).toBeNull();
  });
});

describe("MessageView · 답이 기댄 페이지", () => {
  const message = (metadata: Record<string, unknown>, extra: Partial<ConversationMessage> = {}): ConversationMessage => ({
    id: 1, session_id: "s", role: "assistant", content: "최저가는 89,000원입니다.", kind: "chat", metadata, created_at: 0, ...extra,
  });

  it("hangs the cards under a settled answer that carries its job number", async () => {
    const shown = source(SHOTS);
    await render(<MessageView message={message({ job_id: "job-1", grounding: { basis: "observed" } })} showcase={shown} />);
    expect(shown.list).toHaveBeenCalledWith("job-1");
    expect(container.querySelectorAll(".showcase-card").length).toBe(2);
  });

  it.each([
    ["an unfinished job's note", { job_id: "job-1", unfinished: "failed" }, {}],
    ["an answer written from memory", { job_id: "job-1", grounding: { basis: "memory" } }, {}],
    ["an old answer without a job number", {}, {}],
    ["the person's own message", { job_id: "job-1" }, { role: "user" as const }],
  ])("asks nothing for %s", async (_label, metadata, extra) => {
    const shown = source(SHOTS);
    await render(<MessageView message={message(metadata, extra)} showcase={shown} />);
    expect(shown.list).not.toHaveBeenCalled();
    expect(container.querySelector(".showcase")).toBeNull();
  });
});

describe("createShowcaseSource", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:made") });
  });
  afterEach(() => vi.useRealTimers());

  it("asks again while the job is not yet written as finished — the answer lands a moment before the result", async () => {
    const getJob = vi.fn()
      .mockResolvedValueOnce({ status: "running", result: null })
      .mockResolvedValueOnce({ status: "completed", result: { showcase: SHOTS } });
    const made = createShowcaseSource(() => ({ getJob, fetchShowcaseShot: vi.fn(async () => new Blob(["x"])) }), () => undefined);
    const pending = made.list("job-1");
    await vi.advanceTimersByTimeAsync(2000);
    expect(await pending).toHaveLength(2);
    expect(getJob).toHaveBeenCalledTimes(2);
    // 끝난 판은 다시 안 묻는다.
    await made.list("job-1");
    expect(getJob).toHaveBeenCalledTimes(2);
  });

  it("gives an empty list for a finished job without pictures, and keeps at most two", async () => {
    const getJob = vi.fn(async () => ({ status: "completed", result: { showcase: [] } }));
    const made = createShowcaseSource(() => ({ getJob, fetchShowcaseShot: vi.fn(async () => null) }), () => undefined);
    expect(await made.list("job-1")).toEqual([]);
    expect(getJob).toHaveBeenCalledTimes(1);
    const three = createShowcaseSource(() => ({
      getJob: vi.fn(async () => ({ status: "completed", result: { showcase: [...SHOTS, SHOTS[0]] } })),
      fetchShowcaseShot: vi.fn(async () => null),
    }), () => undefined);
    expect(await three.list("job-2")).toHaveLength(2);
  });

  it("does not hold on to a picture that failed, so a later look can try again", async () => {
    const fetchShowcaseShot = vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce(new Blob(["x"]));
    const made = createShowcaseSource(() => ({ getJob: vi.fn(), fetchShowcaseShot }), () => undefined);
    expect(await made.image("job-1", 0)).toBeNull();
    await Promise.resolve();
    expect(await made.image("job-1", 0)).toBe("blob:made");
    expect(await made.image("job-1", 0)).toBe("blob:made");
    expect(fetchShowcaseShot).toHaveBeenCalledTimes(2);
  });
});

describe("small helpers", () => {
  it("names the site without www", () => {
    expect(siteName("https://www.compare.example/a")).toBe("compare.example");
    expect(siteName("not a url")).toBe("");
  });
  it("writes the read time as 24-hour hh:mm and nothing for an unknown time", () => {
    expect(readClock(new Date(2026, 9, 18, 0, 14).getTime() / 1000)).toBe("00:14");
    expect(readClock(0)).toBe("");
  });
});
