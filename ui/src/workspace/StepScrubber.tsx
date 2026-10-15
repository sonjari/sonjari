/**
 * **걸음 눈금자** — 이 화면의 서명 (P10).
 *
 * 도구 호출 하나가 눈금 하나다. 누르면 그때 자비스가 본 것이 그대로 다시 열린다.
 *
 * ## 왜 이 모양인가
 *
 * 자비스는 Playwright 위에서 돈다. 그 트레이스 뷰어가 하는 일이 정확히 이것이다 —
 * 동작 목록을 시간축에 세우고, 아무 동작이나 고르면 그 순간의 화면·DOM·네트워크를
 * 보여 준다. **우리 제품의 소재에서 나온 모양**이지 대시보드에서 빌려온 장식이 아니다.
 *
 * ## 규칙
 *
 * - 눈금의 **높이**는 상태다. 실패한 걸음은 짧고 붉다 — 성공만 예쁘게 그리면
 *   고장이 안 보인다.
 * - 밖을 바꾼 걸음(쓰기)은 놋쇠 테를 두른다. 열어 보지 않아도 "여기서 뭔가 나갔다"가
 *   보여야 한다.
 * - **지금** 칸이 맨 뒤에 있다. 일이 도는 동안 사람은 대개 지금을 본다.
 * - 사람이 눈금을 누르면 따라가기가 멈춘다(`followingStep`). 읽던 화면이 발밑에서
 *   바뀌는 것이 제일 나쁘다.
 */
import { t } from "../i18n";
import { motion, useReducedMotion } from "framer-motion";
import { isWriteTool, toolLabel } from "../trajectory";
import type { StepRow } from "./observation";
import { KIND_LABEL } from "./observation";

/**
 * 눈금 하나에 새길 글리프. **이름이 아니라 모양**이라야 14px 안에 들어간다.
 *
 * 이모지를 안 쓴다(ui-review 규칙). 단색 기호라 어느 테마에서든 같은 무게로 앉는다.
 */
const KIND_GLYPH: Record<string, string> = {
  code: "{ }",
  document: "¶",
  table: "▦",
  files: "▤",
  page: "⌘",
  draft: "✎",
};

export function StepScrubber(props: {
  rows: StepRow[];
  /** 지금 열어 놓은 걸음. `null` 이면 「지금」을 보고 있다. */
  selected: number | null;
  /** 도는 중인가 — 「지금」 칸을 그릴지 정한다. */
  live: boolean;
  onSelect: (step: number | null) => void;
}) {
  const { rows, selected, live } = props;
  const still = useReducedMotion();
  if (!rows.length && !live) return null;

  return (
    <div className="scrub">
      <div className="scrub-head">
        <span>{rows.length ? t("{0}걸음", rows.length) : t("걸음")}</span>
        <em>{selected === null ? t("지금 보는 중") : t("눌러서 그때로")}</em>
      </div>
      <div className="scrub-ticks" role="tablist" aria-label={t("걸음 눈금자")}>
        {rows.map((row) => {
          const on = selected === row.step;
          const write = isWriteTool(row.tool);
          return (
            <button
              key={row.step}
              type="button"
              role="tab"
              aria-selected={on}
              className={`tick${on ? " on" : ""}${write ? " write" : ""}${row.ok ? "" : " fail"}`}
              onClick={() => props.onSelect(row.step)}
              title={t("{0}번째 걸음 · {1} · {2}{3}", row.step, toolLabel(row.tool), KIND_LABEL[row.kind] ?? row.kind, row.ok ? "" : t(" · 실패"))}
            >
              {/* 새 걸음은 **자라서** 붙는다. 0 에서 시작하는 이유는 「붙었다」가
                  보여야 하기 때문이다 — 그냥 나타나면 목록이 길어진 것만 보인다. */}
              {/* ★ 눈금에 **무엇을 본 걸음인지**를 새긴다 (2026-08-23).
                  그 전에는 회색 막대 둘이라, 눈금자가 「몇 걸음인지」만 말하고
                  「무엇을 했는지」는 열어 봐야 알았다. 필름스트립이 프레임 하나로
                  장면을 알려 주듯, 눈금 하나가 갈래를 알려 준다. */}
              <motion.i
                data-kind={row.kind}
                initial={still ? false : { scaleY: 0, opacity: 0 }}
                animate={{ scaleY: 1, opacity: 1 }}
                style={{ transformOrigin: "bottom" }}
                transition={{ duration: still ? 0 : 0.26, ease: [0.22, 1, 0.36, 1] }}
              >
                <u aria-hidden>{KIND_GLYPH[row.kind] ?? "·"}</u>
              </motion.i>
              <b>{row.step}</b>
            </button>
          );
        })}
        {live && (
          <button
            type="button"
            role="tab"
            aria-selected={selected === null}
            className={`tick now${selected === null ? " on" : ""}`}
            onClick={() => props.onSelect(null)}
            title={t("지금 화면")}
          >
            <i />
            <b>{t("지금")}</b>
          </button>
        )}
      </div>
    </div>
  );
}

export default StepScrubber;
