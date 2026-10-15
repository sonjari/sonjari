import { t } from "../i18n";
import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";

/**
 * **업데이트하는 동안 화면 전체를 흐리게 덮는다** (2026-09-18 밤 사용자 요청).
 *
 * 스토어판은 실행 중인 자기를 못 바꿔서, 설치하려면 윈도우가 앱을 끈다. 아무 말 없이 창이 사라지면
 * 사람은 고장 난 줄 안다 — 오늘 크롬이 「팍 떴다 스르륵」 사라져 놀랐던 것과 같은 종류다. 그래서 끄기 전에
 * **무슨 일이 일어나고, 무엇을 기다리면 되는지**를 말한다.
 *
 * 진행률 숫자는 쓰지 않는다. 앱이 꺼지는 순간부터 우리는 진행 상황을 알 수 없다 — 지어낸 %는 거짓말이다.
 */
export function UpdatingOverlay({ from, to }: { from?: string; to?: string }) {
  return (
    <motion.div
      className="updating-overlay"
      role="alertdialog"
      aria-live="assertive"
      aria-label={t("업데이트하는 중")}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
    >
      <motion.div
        className="updating-card"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.32, delay: 0.08, ease: "easeOut" }}
      >
        <Loader2 size={22} className="spin" aria-hidden />
        <h2>{t("업데이트하는 중입니다")}</h2>
        {from && to && (
          <p className="updating-versions">
            {from} <span aria-hidden>→</span> {to}
          </p>
        )}
        <ol className="updating-steps">
          <li>{t("새 버전을 받아 설치합니다")}</li>
          <li>{t("창이 잠깐 닫혔다가 새 버전으로 스스로 다시 열립니다")}</li>
        </ol>
        {/* 걸리는 시간은 재 보지 않았다(포장본 약 200MB — 인터넷 속도에 달렸다). 숫자를 지어내지 않는다. */}
        <p className="updating-hint">{t("끄지 말고 기다려 주세요. 인터넷 속도에 따라 몇 분 걸릴 수 있습니다.")}</p>
      </motion.div>
    </motion.div>
  );
}
