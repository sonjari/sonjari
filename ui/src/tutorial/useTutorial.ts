import { useCallback, useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import type { CoachStep } from "./CoachBubble";
import { EXCEL_FOLLOW_KO, FIRST_TASKS_KO, hostOf, lastAnswerLink, loadQuests, saveQuests, type QuestId, type QuestState } from "./tutorialState";

/** 답 속 링크를 사람이 눌렀을 때 `MarkdownView` 가 보내는 창 사건. */
export const LINK_OPENED_EVENT = "sonjari:link-opened";

type Phase = "idle" | "ready" | "running" | "verify" | "offerExcel" | "excelReady" | "excelRunning" | "excelDone" | "failed";

/**
 * 퀘스트 ① · ② 의 흐름 — 설계 3절.
 *
 *   ready(보내기를 짚음) → running(「Sonjari의 컴퓨터」를 크게 · 짚음) → verify(답 속 주소를 짚음)
 *     → 사람이 그 주소를 직접 열면 ① 끝 · 도장 → (원하면) excelReady → excelRunning → ② 끝
 *   어디서든 실패하면 failed — 숨기지 않고 「다른 문장으로 다시」 · 「알려 주기」.
 */
export function useTutorial({ english, setDraft, focusDraft, setStage, openReport }: {
  english: boolean;
  setDraft: (value: string) => void;
  focusDraft: () => void;
  setStage: (value: boolean | null) => void;
  openReport: () => void;
}) {
  const [quests, setQuests] = useState<QuestState>(() => loadQuests());
  const [phase, setPhase] = useState<Phase>("idle");
  const [failure, setFailure] = useState<"nolink" | "failed">("failed");
  const taskRef = useRef(0);
  const excelAfterRef = useRef(false);
  const phaseRef = useRef<Phase>("idle");
  /** 바깥 AI(클로드 등)가 맡긴 일의 번호 — 퀘스트 ③ 은 그 일이 **실제로 끝났을 때만** 체크한다. */
  const delegatedRef = useRef<Set<string>>(new Set());
  phaseRef.current = phase;

  const finish = useCallback((id: QuestId, host?: string) => {
    setQuests((current) => {
      const next = { ...current, done: { ...current.done, [id]: { at: Date.now(), ...(host ? { host } : {}) } } };
      saveQuests(next);
      return next;
    });
  }, []);

  const stop = useCallback(() => {
    setPhase("idle");
    setStage(null);
  }, [setStage]);

  const ready = useCallback((index: number) => {
    taskRef.current = index;
    if (!english) setDraft(FIRST_TASKS_KO[index].prompt);
    setPhase("ready");
    window.setTimeout(focusDraft, 0);
  }, [english, setDraft, focusDraft]);

  const start = useCallback((quest: "watch" | "excel") => {
    excelAfterRef.current = quest === "excel";
    ready(0);
  }, [ready]);

  const dismiss = useCallback(() => {
    setQuests((current) => { const next = { ...current, dismissed: true }; saveQuests(next); return next; });
    stop();
  }, [stop]);

  const cardSeen = useCallback(() => finish("card"), [finish]);

  const excelReady = useCallback(() => {
    if (!english) setDraft(EXCEL_FOLLOW_KO);
    setPhase("excelReady");
    window.setTimeout(focusDraft, 0);
  }, [english, setDraft, focusDraft]);

  /** 대화 화면이 무언가를 보낼 때. 튜토리얼이 기다리던 보내기면 다음 걸음으로. */
  const onSent = useCallback(() => {
    if (phaseRef.current === "ready") {
      setPhase("running");
      setStage(true);
    } else if (phaseRef.current === "excelReady") {
      setPhase("excelRunning");
    }
  }, [setStage]);

  /** 일이 시작될 때 — 누가 맡긴 일인지(`agent_started` 의 origin). */
  const onAgentStarted = useCallback((jobId: string, origin: string) => {
    if (jobId && origin === "mcp") delegatedRef.current.add(jobId);
  }, []);

  /** 판이 끝났을 때(완료 · 실패 · 멈춤). */
  const onJobEnded = useCallback((status: "completed" | "failed" | "cancelled", jobId = "") => {
    if (jobId && delegatedRef.current.has(jobId)) {
      delegatedRef.current.delete(jobId);
      if (status === "completed") finish("claude");
      return;
    }
    const now = phaseRef.current;
    if (now === "running") {
      setStage(null);
      if (status !== "completed") { setFailure("failed"); setPhase("failed"); return; }
      // 답이 그려진 뒤에 주소를 찾는다.
      window.setTimeout(() => {
        const link = lastAnswerLink();
        if (!link) { setFailure("nolink"); setPhase("failed"); return; }
        document.querySelectorAll("[data-coach='source']").forEach((el) => el.removeAttribute("data-coach"));
        link.setAttribute("data-coach", "source");
        setPhase("verify");
      }, 1200);
    } else if (now === "excelRunning") {
      if (status === "completed") { finish("excel"); setPhase("excelDone"); }
      else { setFailure("failed"); setPhase("failed"); }
    }
  }, [finish, setStage]);

  useEffect(() => {
    const opened = (event: Event) => {
      if (phaseRef.current !== "verify") return;
      const url = String((event as CustomEvent<{ url?: string }>).detail?.url || "");
      finish("watch", hostOf(url) || undefined);
      if (excelAfterRef.current) excelReady();
      else setPhase("offerExcel");
    };
    window.addEventListener(LINK_OPENED_EVENT, opened);
    return () => window.removeEventListener(LINK_OPENED_EVENT, opened);
  }, [finish, excelReady]);

  let bubble: CoachStep | null = null;
  if (phase === "ready") {
    bubble = english
      ? { target: ".workspace-composer textarea", step: [1, 4], title: t("찾아볼 것을 적고 보내 보세요."),
          body: t("손자리가 이 컴퓨터의 크롬을 직접 움직여 찾아요.") }
      : { target: ".send-button", step: [1, 4], title: t("이 문장을 그대로 보내 보세요."),
          body: t("손자리가 이 컴퓨터의 크롬을 직접 움직여 찾아요.") };
  } else if (phase === "running") {
    bubble = { target: ".computer-pane", step: [2, 4], title: t("지금 손자리가 크롬에서 찾고 있어요."),
      body: t("로그인된 사이트도 그대로 보여요. 멈추고 싶으면 「여기서 멈추기」를 누르세요.") };
  } else if (phase === "verify") {
    bubble = { target: "[data-coach='source']", step: [3, 4], title: t("손자리는 실제로 읽은 페이지만 근거로 말해요."),
      body: t("이 주소를 눌러 직접 확인해 보세요.") };
  } else if (phase === "offerExcel") {
    bubble = { step: [4, 4], title: t("확인했어요. 이게 손자리가 일하는 방식이에요."),
      body: t("읽은 곳은 언제든 직접 열어 볼 수 있어요. 이어서 찾은 것을 엑셀로 받아 볼까요?"),
      actions: [{ label: t("엑셀로 받아 보기"), primary: true, onClick: excelReady }, { label: t("나중에"), onClick: stop }] };
  } else if (phase === "excelReady") {
    bubble = english
      ? { target: ".workspace-composer textarea", title: t("방금 찾은 것을 엑셀로 달라고 적어 보내 보세요.") }
      : { target: ".send-button", title: t("이 문장을 그대로 보내 보세요."), body: t("같은 대화에서 이어 물으면 앞에서 찾은 것을 씁니다.") };
  } else if (phase === "excelDone") {
    bubble = { title: t("엑셀 파일을 만들었어요."), body: t("답에 적힌 자리에서 열 수 있어요. 손자리가 만든 파일은 문서 폴더의 Sonjari 안에 모여요."),
      actions: [{ label: t("다 했어요"), primary: true, onClick: stop }] };
  } else if (phase === "failed") {
    // 둘째 문장(날씨)이 남아 있을 때만 「다른 문장으로」를 준다 — 둘 다 안 되면 더 권하지 않는다.
    const retry = !english && taskRef.current === 0;
    bubble = { title: t("이번엔 끝내지 못했어요."),
      body: failure === "nolink" ? t("이번 답에는 열어 볼 주소가 없었어요. 잘된 척하지 않고 그대로 보여 드려요.")
        : t("손자리가 이 일을 끝내지 못했어요. 무엇이 있었는지 알려 주시면 고쳐서 다음 판에 넣어요."),
      actions: [
        ...(retry ? [{ label: t("다른 문장으로 다시 해 보기"), primary: true, onClick: () => ready(1) }] : []),
        { label: t("알려 주기"), onClick: () => { openReport(); stop(); } },
        { label: t("그만 보기"), onClick: stop },
      ] };
  }

  const showBoard = !quests.dismissed && !(quests.done.watch && quests.done.excel && quests.done.card);
  return { quests, phase, bubble, showBoard, start, dismiss, cardSeen, onSent, onAgentStarted, onJobEnded, stop };
}
