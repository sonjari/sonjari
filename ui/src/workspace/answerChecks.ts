/**
 * 답 끝에 붙어 오는 「확인할 것」을 답 본문에서 떼어 낸다 (2026-10-13, 대표).
 *
 * 서버는 답을 검사한 뒤 확인하지 못한 것을 답 글 끝에 `⚠ **…**` 문단으로 덧붙인다(읽은 자료에 없는 비율 · 읽지 않고 적은
 * 이름 · 줄의 값이 그 페이지와 다름 …). 맡긴 쪽(다른 AI)은 그 글을 읽고 확인하면 되지만, 화면에서는 맞는 답 아래에 경고
 * 문단이 둘씩 매달려 「이 답을 믿으라는 건지 말라는 건지」가 됐다 — 그날만 헛경고를 세 번 봤다.
 *
 * 없애지 않고 **자리를 옮긴다**: 답 본문은 깨끗하게 끝나고, 확인할 것은 오른쪽 판의 「시킨 것」 아래에 노란 줄로,
 * 답 아래에는 접힌 한 줄(「확인할 것 2」)로 둔다.
 *
 * 떼는 것은 **끝에 붙은 것만**이다. 답 한가운데의 ⚠ 는 모델이 쓴 글이라 건드리지 않는다.
 */
export interface AnswerCheck {
  /** 한 줄 요약 — 굵게 온 부분에서 구체적인 값(쌍점 뒤)을 뗀 것. 「읽은 자료에 없는 비율이 있습니다」 */
  title: string;
  /** 무엇이 그런지 — 쌍점 뒤의 값. 「10%」 */
  what: string;
  /** 서버가 보낸 문단 그대로(⚠ 는 뗌). 펼쳤을 때 보여 준다. */
  detail: string;
}

const MARK = "⚠";
/**
 * 서버가 경고 **뒤에** 덧붙이는 다른 꼬리 — 만든 파일 목록 · 시킨 것 대조 · ℹ 도구 기록.
 *
 * ★ 2026-10-22: 떼기를 「맨 끝 문단이 ⚠ 일 때」만 했더니, 경고 뒤에 이 꼬리가 하나라도 붙은 답은 경고를 하나도 못 뗐다.
 *   10-13 뒤 경고가 붙은 답 169개 중 60개(36%)가 그랬다(만든 파일 35 · 시킨 것 대조 18 · ℹ 도구 기록 7). 그 꼬리들을 건너뛰어
 *   경고만 떼고, 꼬리 자체는 본문 끝에 그대로 둔다(파일 목록은 사람이 열어야 하는 것이다).
 */
const OUR_TAIL = /^(?:ℹ|\*\*(?:시킨 것 대조|Checklist)\*\*|만든 파일:|Files (?:made|created):)/;

export function splitAnswerChecks(content: string): { body: string; checks: AnswerCheck[] } {
  const text = String(content ?? "");
  const blocks = text.split(/\n{2,}/);
  let first = blocks.length;
  while (first > 0) {
    const head = blocks[first - 1].trimStart();
    if (!head.startsWith(MARK) && !OUR_TAIL.test(head)) break;
    first -= 1;
  }
  const tail = blocks.slice(first);
  const warnings = tail.filter((block) => block.trimStart().startsWith(MARK));
  if (warnings.length === 0 || first === 0) return { body: text, checks: [] };
  const kept = [...blocks.slice(0, first), ...tail.filter((block) => !block.trimStart().startsWith(MARK))];
  const checks = warnings.map((block) => {
    const detail = block.trim().slice(MARK.length).trim();
    const bold = /^\*\*([\s\S]+?)\*\*/.exec(detail);
    const head = (bold ? bold[1] : detail.split(/(?<=[.。])\s/)[0]).trim().replace(/[.。]+$/, "");
    const colon = head.search(/[:：]\s/);
    return {
      title: (colon > 0 ? head.slice(0, colon) : head).trim(),
      what: colon > 0 ? head.slice(colon + 1).trim() : "",
      detail: detail.replace(/\*\*/g, ""),
    };
  });
  return { body: kept.join("\n\n").trimEnd(), checks };
}
