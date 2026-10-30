/**
 * 코드 모드 진행 줄의 재료 (2026-10-27).
 *
 * 모델이 생각만 하고 도구를 아직 안 부른 동안 화면은 「계획 단계를 진행하고 있습니다」 한 줄뿐이었다.
 * 모델을 더 부르지 않고(속도 손해 0) **이미 흘러오는 생각 글**에서 프로그램이 결정론으로 뽑는다:
 * 글자 수와, 생각 끝부분에서 마지막으로 언급된 파일 이름 하나.
 */
import { t } from "../i18n";

/** 파일로 치는 확장자. 긴 것이 앞에 와야 `tsx` 가 `ts` 로 잘리지 않는다(뒤 `\b` 가 막기는 한다). */
const EXTENSIONS = "tsx|ts|jsx|json|js|py|md|css|html|ps1|toml|yaml|yml";

/**
 * 파일 이름 모양: 이름 조각 + `.확장자`, 앞이 이름 글자가 아니고 뒤에서 이름이 끝나는 것.
 * 경로는 이 정규식이 맞추는 것이 아니라 **마지막 구분자 뒤**만 남기는 방식으로 걷는다(윈도 경로 `\` 도 같다).
 */
const FILE = new RegExp(`(?<![\\w.\\-@])[\\w.\\-@]+\\.(?:${EXTENSIONS})\\b(?![\\w@])`, "gi");

/** 주소는 파일이 아니다 — `https://x.dev/a/plan.py` 의 `plan.py` 는 이 PC 파일이 아니라 웹 주소 끝일 뿐이다. */
const URL_LIKE = /\b(?:[a-z][a-z0-9+.\-]*:\/\/|www\.)\S+/gi;

/** `Node.js` · `Next.js` 처럼 파일이 아니라 도구 이름인 낱말. 소문자로 견준다. */
const PRODUCT_NAMES = new Set([
  "node.js", "next.js", "nuxt.js", "vue.js", "react.js", "express.js", "three.js", "d3.js",
  "chart.js", "socket.js", "angular.js", "backbone.js", "ember.js", "nest.js", "p5.js", "anime.js",
]);

/** 끝부분만 본다 — 생각은 40,000자까지 쌓이고, 지금 보고 있는 것은 맨 끝에 있다. */
const TAIL_CHARS = 1_500;

/**
 * 생각 글의 **끝부분**에서 마지막에 나온 파일 이름 하나(디렉터리는 뗀다). 없으면 빈 문자열.
 *
 * - 확장자가 붙은 이름만: `.py .ts .tsx .js .jsx .json .md .css .html .ps1 .toml .yaml .yml`
 * - 확장자 없는 낱말(`plan`)은 파일로 치지 않는다.
 * - URL 안의 것은 파일로 치지 않는다. `Node.js` 같은 도구 이름도.
 */
export function lastFileNameIn(text: string): string {
  if (!text) return "";
  let tail = text.length > TAIL_CHARS ? text.slice(-TAIL_CHARS) : text;
  // 자른 자리가 낱말 가운데일 수 있다 — 첫 공백까지는 버린다(이름 앞쪽이 잘린 채 뽑히는 것을 막는다).
  if (tail.length < text.length) {
    const cut = tail.search(/\s/);
    tail = cut >= 0 ? tail.slice(cut) : "";
  }
  const clean = tail.replace(URL_LIKE, " ");
  let found = "";
  for (const match of clean.matchAll(FILE)) {
    const name = match[0].split(/[\\/]/).pop() ?? "";
    if (!name || PRODUCT_NAMES.has(name.toLowerCase())) continue;
    found = name;
  }
  return found;
}

/** 도구가 없는 걸음의 진행 줄: 「생각 중 · 3,200자 · 보고 있는 파일: plan.py」. 파일이 없으면 글자 수까지만. */
export function thinkingLine(chars: number, file: string): string {
  const size = chars.toLocaleString("en-US");
  return file
    ? t("생각 중 · {0}자 · 보고 있는 파일: {1}", size, file)
    : t("생각 중 · {0}자", size);
}

/**
 * 도구를 쓴 뒤 모델이 **다시 생각하기 시작했다**고 볼 만큼의 생각 글 증가량 (2026-10-27).
 *
 * 백엔드는 진행 알림을 도구를 쓸 때만 보낸다. 그래서 도구 하나가 끝나고 모델이 다음 걸음을 생각하는 동안(코드 판 시간의 대부분)
 * 마지막 알림은 앞 도구의 것으로 남는다. 마지막 알림을 받은 뒤 생각 글이 이만큼 늘면 지금은 도구가 아니라 생각하는 중이다.
 *
 * 200자를 고른 근거(운영 `data/model_calls.jsonl`, purpose=step · think=true 2,861번 부름):
 * 걸음마다 쓴 생각 글은 중앙 297자 · 하위 25% 86자 · 상위 25% 1,227자이고 43% 가 200자 미만이다. 글자당 토큰은 중앙 2.0자/토큰이라
 * 200자는 약 100토큰, 이 PC 모델 속도로 몇 초다. 그보다 작게 잡으면 짧게 끝나는 걸음(전체의 절반 가까이)마다 줄이 「도구 문구 → 생각 중 →
 * 도구 문구」로 깜빡이고, 크게 잡으면 긴 생각 내내 앞 도구 문구가 남는다. 짧은 걸음은 도구 문구가 그대로 맞고 몇 초 안에 새 알림이 온다.
 */
export const THINKING_RESUMED_CHARS = 200;

/** 생각 글이 **지금까지 받은 총량**을 세는 장치. 화면의 생각 글은 맨 끝 40,000자만 남기므로 길이만 보면 그 뒤로는 늘지 않는다. */
export interface ThinkingMeter {
  /** 직전에 본 생각 글(남은 부분). */
  last: string;
  /** 지금까지 받은 글자 수(잘려 나간 것 포함). */
  total: number;
}

/** 겹침을 찾을 때 쓰는 직전 글 끝부분의 길이. */
const OVERLAP_PROBE = 200;

/**
 * 새 생각 글을 보고 총량을 갱신한다.
 * - 직전 글 뒤에 이어 붙었으면 늘어난 만큼 더한다.
 * - 앞이 잘려 나가며 밀렸으면(40,000자 상한) 직전 글의 끝부분이 새 글 어디에 있는지 찾아 그 뒤로 늘어난 만큼 더한다.
 * - 이어지지 않으면(판이 바뀌어 지워짐) 새 글 길이로 다시 시작한다.
 */
export function advanceThinkingMeter(prev: ThinkingMeter | null, text: string): ThinkingMeter {
  if (!prev) return { last: text, total: text.length };
  if (text === prev.last) return prev;
  if (text.startsWith(prev.last)) return { last: text, total: prev.total + text.length - prev.last.length };
  const probe = prev.last.slice(-OVERLAP_PROBE);
  if (probe) {
    const at = text.lastIndexOf(probe);
    if (at >= 0) return { last: text, total: prev.total + text.length - (at + probe.length) };
  }
  return { last: text, total: text.length };
}
