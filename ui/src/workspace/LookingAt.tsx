/**
 * 지금 읽는 그림 조각 — 모델이 일하면서 하는 말 줄 바로 아래 (2026-10-10).
 *
 * 상품 상세·채용 공고가 **통이미지**인 페이지는 글자로 읽히지 않는다. 손자리는 그 그림을 세로로 잘라 조각마다 모델에게
 * 읽히는데(조각 하나에 3~4초, 많으면 여덟 번), 그동안 화면에는 「본문 읽기」 한 줄만 떠 있어서 멈춘 것처럼 보였다.
 * 대표: 「그림을 본다고 하는 것은 클로드처럼 스크린샷을 딱 띄워 주자」.
 *
 * 보이는 것은 셋이다.
 *   왼쪽 눈금  긴 그림 한 장의 축소판. 칸 하나가 조각 하나 — 읽은 칸 · 지금 칸 · 남은 칸.
 *   가운데     지금 칸을 키운 것. 읽는 줄이 위에서 아래로 지나간다.
 *   오른쪽     무엇을 하는 중인지 한 줄, 몇 번째인지(기계가 센 값이라 고정폭), 왜 오래 걸리는지 한 줄.
 *
 * 색은 기계 쪽 바닥(찬 흑연)이다 — 사람의 대화 줄 안에서 「기계가 보고 있는 것」이라는 뜻을 온도로 말한다.
 * 유채색은 손자리 자신(brand)뿐. signal 은 사람이 눌러야 할 때만 쓰는 색이라 여기에 쓰지 않는다.
 *
 * 자리: 처음엔 「일하는 중」 상자 안에 넣었다. 대표: 「그쪽은 말이 올 때마다 사용자한테는 가려진다 — 모델이 중간에 말을
 * 던지는 자리에 넣자」. 말이 쌓이면 화면이 아래를 따라가므로 눈이 가 있는 곳은 말 줄의 끝이다.
 *
 * 이 그림은 걸음 기록에 남지 않는다. 읽은 **글**은 그 걸음의 근거로 남고, 그림은 읽는 동안에만 비춘다.
 */
import { AnimatePresence, motion } from "framer-motion";
import type { CSSProperties } from "react";
import { t } from "../i18n";
import type { Looking } from "../types";
import "./lookingAt.css";

const FRAME_WIDTH = 132;
const FRAME_MIN = 72;
const FRAME_MAX = 192;

/** 조각 그림의 비율대로 틀 높이를 잡는다 — 마지막 조각처럼 짧은 것은 짧게, 긴 것은 한도까지만. */
export function frameHeight(width: number, height: number): number {
  if (!(width > 0) || !(height > 0)) return FRAME_MAX;
  return Math.round(Math.min(FRAME_MAX, Math.max(FRAME_MIN, (FRAME_WIDTH * height) / width)));
}

export function LookingAt({ looking }: { looking: Looking }) {
  const tiles = Math.max(1, Math.floor(looking.tiles) || 1);
  const tile = Math.min(tiles, Math.max(1, Math.floor(looking.tile) || 1));
  const height = frameHeight(looking.width, looking.height);
  // 만든 화면을 눈으로 보는 중이면 말이 다르다 — 조각을 읽는 것이 아니라 통째로 찍은 한 장을 본다.
  const page = looking.kind === "page";
  const count = page
    ? t("페이지 전체 한 장")
    : looking.images > 1
      ? t("그림 {0}/{1} · 조각 {2}/{3}", looking.image, looking.images, tile, tiles)
      : t("조각 {0}/{1}", tile, tiles);

  return (
    <figure className="looking-at" style={{ "--looking-h": `${height}px` } as CSSProperties}>
      <ol className="looking-rail" aria-hidden>
        {Array.from({ length: tiles }, (_, index) => (
          <li key={index} className={index + 1 < tile ? "read" : index + 1 === tile ? "now" : ""} />
        ))}
      </ol>
      <div className="looking-frame">
        <AnimatePresence initial={false}>
          <motion.img
            key={`${looking.image}:${tile}`}
            src={looking.picture}
            alt={page ? t("손자리가 만든 화면") : t("지금 읽는 그림 조각")}
            draggable={false}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22 }}
          />
        </AnimatePresence>
        <i className="looking-scan" aria-hidden />
      </div>
      <figcaption>
        <strong>{page ? t("만든 화면을 눈으로 보는 중") : t("그림 속 글자를 읽는 중")}</strong>
        <span className="looking-count" role="status">{count}</span>
        <small>
          {page
            ? t("보이지 않는 창에서 따로 찍어 봅니다. 쓰시는 화면은 건드리지 않습니다.")
            : t("글자로 안 읽히는 그림이라 잘라서 하나씩 읽습니다.")}
        </small>
      </figcaption>
    </figure>
  );
}

export default LookingAt;
