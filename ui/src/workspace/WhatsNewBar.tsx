import { t, lang } from "../i18n";
import { Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { JarvisClient } from "../backend";
import type { WhatsNewStatus } from "../types";
import { MarkdownView } from "../MarkdownView";
import { WhatsNewDeck } from "./WhatsNewDeck";

/**
 * **업데이트 뒤 「바뀐 것 · 이미 되는 것」** 한 줄 (2026-10-20 대표).
 *
 * 「기능 추가나 개선은 사용자가 알아야 되는데 지금은 아예 모른다 · 디스코드처럼 되는 게 많은데 한번 알려 주는 게 필요하다」.
 * 판 번호가 바뀐 뒤 처음 켰을 때만 한 줄을 띄운다. 닫으면 백엔드에 「봤다」를 적어 다음 업데이트까지 다시 안 뜬다.
 * 글은 백엔드(`whats_new/<판>.json`)에 한 벌만 있다 — 대화의 「뭐가 바뀌었어?」도 같은 글이다.
 * 막 깐 사람에게는 안 띄운다(마법사가 먼저다 — 백엔드가 가른다).
 *
 * ★ 2026-10-21: 슬라이드가 있는 판이면 「바뀐 것 보기」가 가운데 슬라이드 창을 연다(`WhatsNewDeck`). 「나중에 보기」는
 * 창만 닫고 이 줄은 남긴다. 슬라이드가 없는 옛 판(0.4.27~29)은 지금처럼 이 자리에서 목록을 펼친다.
 */
export function WhatsNewBar({ client }: { client: JarvisClient | null }) {
  const [status, setStatus] = useState<WhatsNewStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [deck, setDeck] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  useEffect(() => {
    if (!client) return;
    void client.getWhatsNew(lang()).then((next) => {
      if (alive.current) setStatus(next);
    }).catch(() => {
      // 본체가 꺼져 있거나 옛 판이면 조용히 지나간다 — 알림은 덤이다.
    });
  }, [client]);

  const later = useCallback(() => setDeck(false), []);

  if (!status?.show) return null;

  const slides = status.slides ?? [];
  const close = () => {
    const version = status.version;
    setStatus(null);
    setOpen(false);
    setDeck(false);
    void client?.markWhatsNewSeen(version).catch(() => undefined);
  };

  return (
    <div className="update-bar good whats-new-bar" role="status">
      <Sparkles size={14} />
      <b>{t("Sonjari {0} 로 업데이트됐습니다", status.version)}</b>
      {slides.length > 0 ? (
        <button type="button" onClick={() => setDeck(true)} aria-haspopup="dialog">{t("바뀐 것 보기")}</button>
      ) : (
        <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
          {open ? t("접기") : t("바뀐 것 보기")}
        </button>
      )}
      <button type="button" onClick={close}>{t("닫기")}</button>
      {open && slides.length === 0 && (
        <div className="whats-new-body">
          <MarkdownView>{status.changes || ""}</MarkdownView>
          {status.tour ? <MarkdownView className="whats-new-tour">{status.tour}</MarkdownView> : null}
          <p className="whats-new-hint">{t("대화창에 「뭐가 바뀌었어?」라고 물어도 다시 볼 수 있습니다.")}</p>
        </div>
      )}
      {/* 창은 몸(body)에 띄운다 — 이 줄은 알림 칸(role=status)이라 안에 두면 장을 넘길 때마다 화면 낭독기가 줄 전체를 다시 읽는다. */}
      {deck && slides.length > 0 && createPortal(
        <WhatsNewDeck version={status.version} slides={slides} changes={status.changes || ""} tour={status.tour || ""}
          onLater={later} onDone={close} />,
        document.body,
      )}
    </div>
  );
}
