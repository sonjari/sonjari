// @vitest-environment jsdom
/**
 * 튜토리얼(퀘스트 판) — 설계 `docs/설계_튜토리얼_퀘스트판_2026-10-16.ko.md`.
 *
 * 지키는 약속:
 * - 퀘스트 ① 은 잰 첫 일 문장을 채우고, 사람이 **답 속 주소를 직접 열어야** 끝난다(「직접 확인함」 + 연 주소).
 * - 답에 열어 볼 주소가 없으면 잘된 척하지 않는다 — 「이번엔 끝내지 못했어요」와 둘째 문장(날씨)으로 다시 해 보기.
 * - 엑셀은 사람이 확인한 것이 아니라 받은 것이라 도장 말이 다르다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QuestBoard } from "./QuestBoard";
import { FIRST_TASKS_KO } from "./tutorialState";
import { LINK_OPENED_EVENT, useTutorial } from "./useTutorial";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
  vi.useRealTimers();
});

type Api = ReturnType<typeof useTutorial>;

function mount(setDraft = vi.fn(), openReport = vi.fn()) {
  const api: { current: Api | null } = { current: null };
  function Harness() {
    api.current = useTutorial({ english: false, setDraft, focusDraft: () => {}, setStage: () => {}, openReport });
    return <p className="bubble">{api.current.bubble?.title ?? ""}</p>;
  }
  act(() => root.render(<Harness />));
  return { api, setDraft, openReport, bubble: () => host.querySelector(".bubble")?.textContent ?? "" };
}

function answerWith(html: string) {
  const article = document.createElement("article");
  article.className = "workspace-message message-assistant";
  article.innerHTML = `<div class="workspace-markdown">${html}</div>`;
  document.body.appendChild(article);
}

describe("퀘스트 ① — 크롬이 움직이는 걸 보기", () => {
  it("잰 첫 일 문장을 채우고, 답의 주소를 직접 열어야 끝난다", () => {
    const { api, setDraft, bubble } = mount();
    act(() => api.current!.start("watch"));
    expect(setDraft).toHaveBeenCalledWith(FIRST_TASKS_KO[0].prompt);
    expect(bubble()).toBe("이 문장을 그대로 보내 보세요.");

    act(() => api.current!.onSent());
    expect(bubble()).toBe("지금 손자리가 크롬에서 찾고 있어요.");

    answerWith('쪽수 552쪽 · 출처: <a href="https://www.yes24.com/product/goods/1">yes24</a>');
    act(() => api.current!.onJobEnded("completed"));
    act(() => { vi.advanceTimersByTime(1300); });
    expect(bubble()).toBe("손자리는 실제로 읽은 페이지만 근거로 말해요.");
    expect(document.querySelector("[data-coach='source']")?.getAttribute("href")).toContain("yes24.com");
    expect(api.current!.quests.done.watch).toBeUndefined(); // 아직 사람이 안 열었다

    act(() => { window.dispatchEvent(new CustomEvent(LINK_OPENED_EVENT, { detail: { url: "https://www.yes24.com/product/goods/1" } })); });
    expect(api.current!.quests.done.watch?.host).toBe("yes24.com");
    expect(bubble()).toBe("확인했어요. 이게 손자리가 일하는 방식이에요.");
    expect(JSON.parse(localStorage.getItem("sonjari.tutorial.v1") || "{}").done.watch.host).toBe("yes24.com");
  });

  it("답에 열어 볼 주소가 없으면 잘된 척하지 않고 둘째 문장으로 다시 해 보게 한다", () => {
    const { api, setDraft, openReport, bubble } = mount();
    act(() => api.current!.start("watch"));
    act(() => api.current!.onSent());
    answerWith("쪽수는 552쪽입니다.");
    act(() => api.current!.onJobEnded("completed"));
    act(() => { vi.advanceTimersByTime(1300); });
    expect(bubble()).toBe("이번엔 끝내지 못했어요.");
    expect(api.current!.bubble?.body).toContain("열어 볼 주소가 없었어요");
    expect(api.current!.quests.done.watch).toBeUndefined();

    const labels = api.current!.bubble!.actions!.map((action) => action.label);
    expect(labels).toEqual(["다른 문장으로 다시 해 보기", "알려 주기", "그만 보기"]);
    act(() => api.current!.bubble!.actions![0].onClick());
    expect(setDraft).toHaveBeenLastCalledWith(FIRST_TASKS_KO[1].prompt);

    // 둘째 문장도 안 되면 더 권하지 않는다 — 알려 주기와 그만 보기만.
    act(() => api.current!.onSent());
    act(() => api.current!.onJobEnded("failed"));
    expect(api.current!.bubble!.actions!.map((action) => action.label)).toEqual(["알려 주기", "그만 보기"]);
    act(() => api.current!.bubble!.actions![0].onClick());
    expect(openReport).toHaveBeenCalled();
  });

  it("「엑셀로 받아 보기」로 시작하면 확인 뒤 바로 엑셀 문장으로 이어 간다", () => {
    const { api, setDraft, bubble } = mount();
    act(() => api.current!.start("excel"));
    act(() => api.current!.onSent());
    answerWith('<a href="https://www.yes24.com/x">yes24</a>');
    act(() => api.current!.onJobEnded("completed"));
    act(() => { vi.advanceTimersByTime(1300); });
    act(() => { window.dispatchEvent(new CustomEvent(LINK_OPENED_EVENT, { detail: { url: "https://www.yes24.com/x" } })); });
    expect(setDraft).toHaveBeenLastCalledWith("방금 찾은 것을 엑셀 파일로 만들어 줘");
    act(() => api.current!.onSent());
    act(() => api.current!.onJobEnded("completed"));
    expect(api.current!.quests.done.excel).toBeTruthy();
    expect(bubble()).toBe("엑셀 파일을 만들었어요.");
  });
});

describe("퀘스트 판", () => {
  it("할 일 셋 · 끝낸 일의 도장 말은 사람이 한 일 그대로다", () => {
    const onStart = vi.fn();
    const onDismiss = vi.fn();
    act(() => root.render(
      <QuestBoard state={{ dismissed: false, done: { watch: { at: 1, host: "yes24.com" }, excel: { at: 2 } } }}
        tierGb={8} english={false} onStart={onStart} onDismiss={onDismiss} onCardSeen={() => {}} />,
    ));
    const rows = [...host.querySelectorAll(".quest-row")];
    expect(rows).toHaveLength(3);
    expect(rows[0].querySelector(".quest-stamp")?.textContent).toBe("직접 확인함yes24.com");
    expect(rows[1].querySelector(".quest-stamp")?.textContent).toBe("받았어요");
    expect(host.querySelector(".quest-count")?.textContent).toBe("3개 중 2개");

    const card = rows[2].querySelector<HTMLButtonElement>(".quest-start")!;
    act(() => card.click());
    expect(host.querySelector(".quest-card-facts")?.textContent).toContain("8GB");
    expect(host.querySelector(".quest-card-facts")?.textContent).toContain("9줄 중 가운데 5줄");

    act(() => host.querySelector<HTMLButtonElement>(".quest-later")!.click());
    expect(onDismiss).toHaveBeenCalled();
  });

  it("그래픽카드를 모르면 지어내지 않고 모른다고 말한다", () => {
    act(() => root.render(
      <QuestBoard state={{ dismissed: false, done: {} }} english={false} onStart={() => {}} onDismiss={() => {}} onCardSeen={() => {}} />,
    ));
    act(() => host.querySelectorAll<HTMLButtonElement>(".quest-start")[2].click());
    expect(host.querySelector(".quest-card-facts")?.textContent).toContain("아직 확인하지 못했어요");
  });
});

describe("퀘스트 ③ — 클로드에게 맡겨 보기", () => {
  it("클로드가 맡긴 일이 실제로 끝났을 때만 체크된다 · 실패는 체크하지 않는다", () => {
    const { api } = mount();
    act(() => api.current!.onAgentStarted("j-fail", "mcp"));
    act(() => api.current!.onJobEnded("failed", "j-fail"));
    expect(api.current!.quests.done.claude).toBeUndefined();

    act(() => api.current!.onAgentStarted("j-ok", "mcp"));
    act(() => api.current!.onJobEnded("completed", "j-ok"));
    expect(api.current!.quests.done.claude).toBeTruthy();
  });

  it("퀘스트 ① 이 도는 중에 클로드 일이 끝나도 ① 의 흐름을 흐트러뜨리지 않는다", () => {
    const { api, bubble } = mount();
    act(() => api.current!.start("watch"));
    act(() => api.current!.onSent());
    act(() => api.current!.onAgentStarted("mcp-1", "mcp"));
    act(() => api.current!.onJobEnded("completed", "mcp-1"));
    expect(bubble()).toBe("지금 손자리가 크롬에서 찾고 있어요.");
  });

  it("클로드가 이어진 PC 에서만 보인다", () => {
    act(() => root.render(
      <QuestBoard state={{ dismissed: false, done: {} }} english={false} onStart={() => {}} onDismiss={() => {}} onCardSeen={() => {}} />,
    ));
    expect(host.textContent).not.toContain("클로드에게 맡겨 보기");
    expect(host.querySelector(".quest-count")?.textContent).toBe("3개 중 0개");
    act(() => root.render(
      <QuestBoard state={{ dismissed: false, done: { claude: { at: 1 } } }} english={false} claudeConnected
        onStart={() => {}} onDismiss={() => {}} onCardSeen={() => {}} />,
    ));
    expect(host.textContent).toContain("맡겼어요");
    expect(host.querySelector(".quest-count")?.textContent).toBe("4개 중 1개");
  });
});
