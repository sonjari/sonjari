// 작업이 실패했을 때 입력칸 아래에 찍는 말 (2026-10-04 새벽 대표 스크린샷).
//
// 전에는 백엔드가 준 **오류 이름을 그대로** 찍었다 — `coding_verification_missing` 이 화면 맨 아래에 떴다.
// 운영 기록의 실패 원인 1위(35건)가 그 이름이고 2위(33건)가 `timed out` 이다. 사람이 읽을 말이 아니다.
// 여기서 사람 말로 바꾼다. 모르는 이름은 뭉뚱그린 한 문장으로 — 원문은 개발자 도구에 남긴다(문제 보내기가 가져간다).
import { t } from "../i18n";

const GENERIC = "작업을 끝내지 못했습니다. 같은 질문을 다시 보내면 이어서 시도합니다.";

const RULES: Array<[RegExp, string]> = [
  [
    /^coding_verification_missing\b/,
    "코드는 고쳤지만, 마지막 상태를 실행해서 확인한 기록이 없어 「완료」로 닫지 못했습니다. 만든 파일은 그대로 있습니다. 「확인만 다시 해줘」라고 보내면 이어서 확인합니다.",
  ],
  [
    /^code_budget_exhausted\b/,
    "정해 둔 작업 시간을 다 써서 멈췄습니다. 여기까지 만든 파일은 그대로 있습니다. 「이어서 해줘」라고 보내면 이어갑니다.",
  ],
  [/^(?:agent|ollama)_empty_response\b/, "모델이 빈 답을 냈습니다. 같은 질문을 다시 보내 주세요."],
  [/^timed out\b|timeout|ReadTimeout/i, "모델이 제한 시간 안에 답하지 못했습니다. 같은 질문을 다시 보내면 이어서 시도합니다."],
  [
    /11434|^ollama_|WinError 1005[34]|WinError 10061|Connection (?:refused|reset)|ConnectError/i,
    "모델 서버(Ollama)에 닿지 못했거나 서버가 오류를 냈습니다. 위 상태 줄에서 모델이 떠 있는지 확인한 뒤 다시 보내 주세요.",
  ],
  [/^camera_frame_unavailable\b/, "카메라 화면을 가져오지 못했습니다. 카메라가 켜져 있는지 확인해 주세요."],
];

//: 「멈췄지만 한 것은 그대로 있고, 이어서 시키면 된다」 — 사고가 아니라 **안내**다. 빨간색으로 띄우지 않는다
//  (2026-10-04 대표: 「하단에 새빨간 에러」). 여기 든 문장은 화면에서 호박색(사람이 눌러야 움직인다)으로 나온다.
const NOTICE_PATTERNS: RegExp[] = [/^coding_verification_missing\b/, /^code_budget_exhausted\b/];

/** 이 실패 문구가 **안내**(파일은 남아 있고 이어갈 수 있다)인가 — 화면이 색을 고를 때 쓴다. */
export function isFailureNotice(shown: string): boolean {
  if (!shown) return false;
  return RULES.some(([pattern, sentence]) => NOTICE_PATTERNS.some((notice) => notice.source === pattern.source) && t(sentence) === shown);
}

/** 백엔드의 실패 이름·예외 문장을 사람이 읽을 한 문장으로. */
export function jobFailureText(error: unknown): string {
  const raw = String(error ?? "").trim();
  if (!raw) return t(GENERIC);
  for (const [pattern, sentence] of RULES) {
    if (pattern.test(raw)) {
      console.warn("Sonjari job failed:", raw);
      return t(sentence);
    }
  }
  // 이미 사람 말이면(한글이 들어 있고 밑줄 이름이 아니면) 그대로 둔다 — 도구가 이유를 적어 보낸 경우다.
  if (/[가-힣]/.test(raw) && !/^[a-z][a-z0-9_]*(?::|$)/.test(raw) && !/WinError|Traceback/.test(raw)) return raw;
  console.warn("Sonjari job failed:", raw);
  return t(GENERIC);
}
