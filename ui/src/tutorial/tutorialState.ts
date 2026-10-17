/**
 * 튜토리얼(퀘스트 판)의 상태 — 설계 `docs/설계_튜토리얼_퀘스트판_2026-10-16.ko.md`.
 *
 * ## 지키는 것
 * - **첫 일 문장은 잰 것만.** 아래 두 문장은 2026-10-16 이 PC 에서 24GB · 8GB · 6GB 급 흉내로 각 3판을 돌려
 *   9판 중 9판 통과한 것이다(설계 7절). 뉴스 · 위키는 작은 카드에서 무너져 뺐다.
 * - 영어 문장은 아직 안 쟀다 — 영어 화면에서는 문장을 미리 채우지 않고 「아직 재 보지 않았다」고 말한다.
 * - 진행은 이 PC 의 브라우저 저장소에 둔다. 저장소를 못 쓰면(사생활 창 · 막힘) 튜토리얼은 그냥 처음 상태로 뜬다 — 그게 틀린 화면이 되지는 않는다.
 */

import { t } from "../i18n";

export type QuestId = "watch" | "excel" | "card" | "claude";

export type QuestState = {
  /** 「다음에 하기」를 눌러 판을 접었나. */
  dismissed: boolean;
  /** 끝낸 퀘스트와 그 증거 — 사용자가 직접 열어 본 주소의 호스트. */
  done: Partial<Record<QuestId, { at: number; host?: string }>>;
};

const KEY = "sonjari.tutorial.v1";

export const EMPTY: QuestState = { dismissed: false, done: {} };

export function loadQuests(): QuestState {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as Partial<QuestState>;
    return { dismissed: Boolean(parsed.dismissed), done: typeof parsed.done === "object" && parsed.done ? parsed.done : {} };
  } catch {
    return EMPTY;
  }
}

export function saveQuests(state: QuestState): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* 저장소를 못 쓰는 창 — 다음에 처음 상태로 뜰 뿐이다. */
  }
}

/** 첫 일 — 세 카드 급 흉내에서 각 3/3(2026-10-16). 첫째가 안 되면 둘째로 다시 해 본다. */
export const FIRST_TASKS_KO = [
  { prompt: "YES24에서 「혼자 공부하는 파이썬」을 찾아 쪽수와 출판사를 알려 줘", host: "yes24.com" },
  { prompt: "네이버에서 오늘 서울 날씨를 찾아 최고 기온과 최저 기온을 알려 줘", host: "naver.com" },
] as const;

/**
 * 영어 화면의 첫 일 (2026-10-17 · 이 PC 흉내 24GB · 8GB · 6GB 3판씩 · 결과 `문서\Sonjari-measure\tutorial_en_1017`).
 * 에펠탑(위키백과)은 맞혔지만 같은 질문을 다시 하면 지난 대화에서 답해 크롬이 안 움직여서 뺐다 — 별 수 · 날씨처럼 매번 바뀌는 값이라야
 * 다시 해도 크롬이 움직인다.
 * GitHub 은 정답(라이선스 MIT)으로 매겨 24GB 3/3 · 8GB 3/3 · 6GB 2/3(한 판이 「Apache 2.0」). 날씨는 답을 열어 보니 9판 중 8판이
 * 오늘 기온(6GB 한 판은 10월 평균)이고, 한국 새벽엔 런던 날짜가 하루 늦어 16 · 17일이 섞인다 — 그래서 둘째(다시 해 보기)로 둔다.
 * 한국어 첫 일(책 9/9)보다 약하다. 더 나은 영어 첫 일은 다음 측정 거리.
 */
export const FIRST_TASKS_EN = [
  { prompt: "Find the ollama/ollama repository on GitHub and tell me its license and how many stars it has", host: "github.com" },
  { prompt: "Look up today's weather in London and tell me the high and low temperatures", host: "" },
] as const;

export const EXCEL_FOLLOW_EN = "Turn what you just found into an Excel file";

/** 퀘스트 ② — 같은 대화에서 이어 묻는다(24GB 3/3 · 6GB 흉내 3/3 · 8GB 흉내 2/3 — 진 판은 앞 판이 브라우저 고장으로 멈춘 판). */
export const EXCEL_FOLLOW_KO = "방금 찾은 것을 엑셀 파일로 만들어 줘";

/** 답이 끝난 뒤 사람이 열어 볼 수 있는 주소가 있는가 — 마지막 손자리 답 안의 http(s) 링크. */
export function lastAnswerLink(root: ParentNode = document): HTMLAnchorElement | null {
  const answers = root.querySelectorAll<HTMLElement>(".message-assistant .workspace-markdown");
  const last = answers[answers.length - 1];
  if (!last) return null;
  return [...last.querySelectorAll<HTMLAnchorElement>("a[href]")].find((a) => /^https?:\/\//i.test(a.getAttribute("href") || "")) ?? null;
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** 카드 급(추천의 `tier_gb`)마다 잰 것 — 퀘스트 ④. 숫자는 시험지(EXAM.md)와 튜토리얼 측정에서 그대로. 안 잰 칸은 안 쟀다고 적는다. */
export type CardFacts = { label: string; lines: { what: string; measured: string }[]; note: string };

export function cardFacts(tierGb: number | undefined): CardFacts | null {
  if (!tierGb || tierGb <= 0) return null;
  if (tierGb >= 20) {
    return { label: "24GB", note: t("이 PC 급에서 직접 잰 값이에요."), lines: [
      { what: t("가게 셋 가격 조사"), measured: t("9줄 중 9줄") },
      { what: t("책 · 날씨 찾아보기"), measured: t("3판 중 3판") },
    ] };
  }
  if (tierGb >= 12) {
    return { label: "16GB", note: t("이 급은 아직 이 표에 넣을 만큼 재지 않았어요."), lines: [] };
  }
  if (tierGb >= 7) {
    return { label: "8GB", note: t("가격 조사는 8GB 노트북에서, 찾아보기는 큰 PC 에서 이 급의 모델과 창으로 흉내 내 쟀어요."), lines: [
      { what: t("가게 셋 가격 조사"), measured: t("9줄 중 가운데 5줄") },
      { what: t("책 · 날씨 찾아보기"), measured: t("3판 중 3판") },
    ] };
  }
  return { label: "6GB", note: t("가격 조사는 6GB 노트북에서, 찾아보기는 큰 PC 에서 흉내 내 쟀어요(실제보다 후할 수 있어요)."), lines: [
    { what: t("가게 셋 가격 조사"), measured: t("9줄 중 가운데 1줄") },
    { what: t("책 · 날씨 찾아보기"), measured: t("3판 중 3판") },
  ] };
}
