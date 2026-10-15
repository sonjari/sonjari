/**
 * 에이전트 화면의 **판정** — 화면 없이 검사할 수 있게 여기 모은다 (R2).
 *
 * 여기서 정하는 것은 두 가지다.
 *
 *   1. 그림이 없을 때 **왜 없는지**. "브라우저가 없습니다" 한 줄로 뭉뚱그리면
 *      사람이 할 일을 알 수 없다 — 안 떠 있음 · 붙기 실패 · 앞 동작에 물림 ·
 *      회로 열림은 전부 다른 상황이고 다음 행동도 다르다.
 *
 *   2. 그림이 **있는데도** 말해야 하는 것. `stuck` · `circuit_open` ·
 *      `automation_flag` 는 화면이 멀쩡해 보이는 채로 자비스만 막혀 있는 모양을
 *      만든다. 그게 제일 알아채기 어려운 고장이라 숨기지 않는다.
 */
import { t } from "../i18n";
import type { BrowserFrame, BrowserStatus } from "../types";

export interface ScreenProblem {
  /** 무슨 일인가 — 한 줄. */
  title: string;
  /** 사람이 무엇을 하면 되는가. 할 것이 없으면 무슨 뜻인지. */
  detail: string;
  tone: "mute" | "hold" | "fail";
}

/**
 * 그림을 못 보여 줄 때의 빈 상태. 보여 줄 그림이 있으면 `null`.
 *
 * 순서가 곧 우선순위다. **사람이 할 일이 있는 것부터** 위로 온다.
 */
export function screenProblem(
  status: BrowserStatus | null,
  frame: BrowserFrame | null,
): ScreenProblem | null {
  if (frame?.blob) return null;
  if (frame?.reason.startsWith("backend_unreachable")) {
    return {
      title: t("Sonjari에 닿지 못했습니다"),
      detail: t("Sonjari 백엔드가 실행 중인지 확인해 주세요."),
      tone: "fail",
    };
  }
  if (!status) {
    return { title: t("브라우저 상태를 확인하는 중입니다"), detail: t("잠시만 기다려 주세요."), tone: "mute" };
  }
  if (!status.enabled) {
    return {
      title: t("브라우저 도구가 꺼져 있습니다"),
      detail: t("Sonjari 설정에서 브라우저를 켜야 웹을 볼 수 있습니다."),
      tone: "mute",
    };
  }
  if (status.circuit_open) {
    return {
      title: t("브라우저 재시도를 잠시 막아 두었습니다"),
      detail: t("10분 안에 복구가 3번 반복돼 Sonjari가 스스로 멈췄습니다. 크롬 창과 네트워크를 확인해 주세요."),
      tone: "fail",
    };
  }
  // ★ 2026-09-29 밤 AWS(크롬 없는 윈도우): 「크롬을 껐다 켜면」은 틀린 안내다 — 껐다 켤 브라우저가 없다.
  //   백엔드가 크롬도 엣지도 못 찾으면 `browser_not_found — <사람 말>` 을 보낸다. 코드는 떼고 사람 말만.
  if (status.attach_error?.startsWith("browser_not_found")) {
    return {
      title: t("브라우저를 찾지 못했습니다"),
      detail: status.attach_error.replace(/^browser_not_found\s*—\s*/, ""),
      tone: "fail",
    };
  }
  if (status.attach_error) {
    return {
      title: t("떠 있는 크롬에 붙지 못했습니다"),
      detail: t("{0} — 크롬을 껐다 켜면 Sonjari가 다시 붙습니다.", status.attach_error),
      tone: "fail",
    };
  }
  if (status.stuck) {
    return {
      title: t("브라우저가 앞 동작에 물려 있습니다"),
      detail: t("대개 페이지가 로딩을 못 끝낸 경우입니다. Sonjari가 곧 스스로 되살립니다."),
      tone: "hold",
    };
  }
  if (!status.started) {
    return {
      title: t("브라우저가 아직 안 떠 있습니다"),
      detail: t("Sonjari가 웹을 쓸 일이 생기면 스스로 엽니다. 여기서 억지로 열지는 않습니다."),
      tone: "mute",
    };
  }
  // 여기까지 왔는데 그림이 없으면 상태가 아니라 **이번 한 장**의 문제다.
  if (frame?.reason.includes("browser_busy")) {
    return {
      // ★ 2026-09-23: 「다른 동작」은 「시킨 것 말고 딴짓」으로 읽혔다. 무엇을 하는 중인지와 곧 돌아온다는 것만 말한다.
      title: t("페이지를 다루는 중이라 화면은 잠시 뒤에 보여 드립니다"),
      detail: t("Sonjari가 브라우저로 일하는 동안에는 화면을 찍지 않고 기다립니다. 일은 그대로 진행됩니다."),
      tone: "hold",
    };
  }
  if (frame?.reason.includes("capture_window_minimized")) {
    return {
      title: t("크롬 창이 내려가 있어 화면을 못 가져옵니다"),
      detail: t("Sonjari 일에는 지장이 없습니다. 작업 표시줄에서 크롬 창을 올리면 여기에도 다시 보입니다."),
      tone: "mute",
    };
  }
  if (frame?.reason.includes("capture_timeout_hidden_tab")) {
    return {
      // ★ 2026-09-24 사용자: 「뒤쪽 탭에서 일하고 있어서 못 보여 드린다 — 이게 무슨 말이야」. 기술 말을 빼고 무엇이 되는지만.
      title: t("지금 보는 페이지는 화면을 가져올 수 없습니다"),
      detail: t("Sonjari는 사용자를 방해하지 않으려고 보이지 않는 곳에서 일합니다. 일은 그대로 진행되고, 끝나면 결과가 여기에 나옵니다."),
      tone: "mute",
    };
  }
  // ★ 2026-09-17: 모르는 이유면 원문(`capture_failed: Page.screenshot: Protocol error … Call log …`)을 통째로 보여 줬다.
  //   지어내지 않는 원칙은 지키되(짧고 읽히는 이유는 그대로), 호출 기록까지 붙은 기술 원문은 **이유 이름만** 보인다.
  const raw = frame?.reason ?? "";
  const technical = /Protocol error|Call log|\n/.test(raw) || raw.length > 90;
  return {
    title: t("화면을 가져오지 못했습니다"),
    detail: !raw ? t("이유를 알 수 없습니다.") : technical ? t("이유: {0}", raw.split(":")[0].trim()) : raw,
    tone: "hold",
  };
}

/**
 * 그림이 **있는데도** 붙여야 하는 말. 없으면 빈 배열.
 *
 * `connect_mode` 가 `attached` 가 아니면 자동화 모드로 도는 크롬이고, 그러면
 * Akamai 를 쓰는 곳은 통째로 막힌다 — 화면에는 페이지가 보이는데 도구만 실패하는
 * 모양이 되므로, 그림이 잘 나올 때야말로 이 말이 필요하다.
 */
export function screenWarnings(status: BrowserStatus | null): string[] {
  if (!status) return [];
  const out: string[] = [];
  if (status.stuck) out.push(t("앞 동작에 물려 있습니다 — 화면이 갱신되지 않을 수 있습니다"));
  if (status.circuit_open) out.push(t("재시도를 잠시 막아 둔 상태입니다"));
  if (status.automation_flag === true) {
    out.push(t("자동화 모드로 붙어 있어 일부 사이트(Akamai)는 막힐 수 있습니다"));
  }
  if (status.recoveries >= 3) out.push(t("브라우저를 {0}번 되살렸습니다 — 원인을 봐야 합니다", status.recoveries));
  return out;
}

/** 주소를 짧게. 어디인지가 요점이고 추적 인자는 아니다. */
export function shortUrl(url: string, limit = 72): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    // ★ `about:blank` 도 URL 로 파싱된다 — host 가 비고 pathname 이 "blank" 다.
    //   그대로 자르면 화면에 "blank" 한 낱말이 뜨는데, 빈 창은 진단에서 중요한
    //   신호라(작업이 끝난 뒤 about:blank 만 남는 모양) 원문을 그대로 보여 준다.
    if (!parsed.host) return url.length > limit ? `${url.slice(0, limit - 1)}…` : url;
    const text = `${parsed.host}${parsed.pathname}`.replace(/\/$/, "");
    return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
  } catch {
    return url.length > limit ? `${url.slice(0, limit - 1)}…` : url;
  }
}

/**
 * 이 그림이 몇 초 전 것인가 — **낡았을 때만** 적는다.
 *
 * 방금 찍은 장에 "0초 전"이라고 붙여 두면 아무도 안 읽고, 안 읽히는 표시는
 * 정작 낡았을 때도 안 읽힌다.
 */
export const STALE_AFTER_SEC = 3;

export function staleLabel(frame: BrowserFrame | null): string {
  if (!frame || !frame.blob) return "";
  if (frame.fresh && frame.ageSec < STALE_AFTER_SEC) return "";
  return t("{0}초 전 화면", Math.round(frame.ageSec));
}

/**
 * 화면과 본문 **사이에 긋는 선.** 두 그림이 서로 다른 시각일 때만 말한다.
 *
 * ## 왜 필요한가 (2026-08-20)
 *
 * 이 칸은 지금까지 **화면이냐 본문이냐 하나만** 보여 줬다. 「지금」을 누르면 그림만
 * 나오고, 3걸음을 누르면 글만 나왔다. 그래서 "자비스가 지금 뭘 보고 있나"를 알려면
 * 둘 사이를 계속 오가야 했다.
 *
 * 둘을 같이 놓기로 하면서 **거짓말 하나가 생길 뻔했다.** 관측 보관소에는 그림이
 * 없다(`observations.shape` 는 글·표·초안만 저장한다). 그러니 3걸음을 열어 놓고
 * 그 위에 지금 화면을 얹으면, 사람은 그것을 **3걸음의 화면**으로 읽는다.
 *
 * 그래서 규칙은 하나다: **화면은 언제나 지금이고, 본문이 지금이 아니면 그렇다고
 * 적는다.** 이 저장소가 잘림을 다루는 방식과 같다 — 조용히 넘어가면 사람은 없던
 * 것과 구별하지 못한다.
 */
export interface Seam {
  /** 본문이 무엇인가 — "3걸음" 또는 "마지막 걸음". */
  label: string;
  /** 지금과 다른 시각인가. 참이면 선을 굵게 긋고 시각을 적는다. */
  rewound: boolean;
}

export function seamLabel(
  selected: number | null,
  latest: number | null,
  live: boolean,
): Seam | null {
  // 본문이 없으면 선도 없다. 선만 덩그러니 있으면 뭔가 잘린 것처럼 보인다.
  if (latest === null) return null;
  if (selected === null) {
    // 「지금」을 보는 중 — 본문은 마지막 걸음이다. 도는 중이면 그것이 곧 지금이라
    // 되감았다고 하지 않는다.
    return { label: live ? t("지금 걸음") : t("마지막 걸음"), rewound: false };
  }
  const rewound = selected !== latest;
  // 글자는 **여기서** 만든다. CSS `content:` 로 붙이면 검사도 못 하고 한 군데
  // 더 봐야 한다 — 말은 한 자리에 둔다.
  return { label: rewound ? t("{0}걸음 · 그때", selected) : t("{0}걸음", selected), rewound };
}

/** 몇 초 전인가 — 되감은 걸음 옆에 붙는다. 초 단위는 안 쓴다(1초마다 다시 그린다). */
export function agoLabel(at: number, now: number): string {
  const seconds = Math.max(0, Math.round((now - at) / 1000));
  if (seconds < 45) return t("방금");
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return t("{0}분 전", minutes);
  return t("{0}시간 전", Math.round(minutes / 60));
}
