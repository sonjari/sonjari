import { t } from "../i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { JarvisClient } from "../backend";
import type { WhatsNewSlide } from "../types";
import type { UsageSettingsSection } from "./UsageShow";
import { WhatsNewDeck } from "./WhatsNewDeck";

/**
 * **「쓰는 법」 쇼** 네 장 (2026-10-27 대표 · 설계서 generated_reports/usage_show_1027/설계서.md).
 *
 * 글은 설계서 그대로다. 주어는 손자리 — 클로드의 도구 · 손 · 조수처럼 보이게 하지 않는다. 글은 그릴 때 읽는다(`t`) —
 * 모듈을 읽는 순간에는 화면 언어가 아직 안 정해졌을 수 있다.
 */
export function usageSlides(): WhatsNewSlide[] {
  return [
    {
      title: t("손자리는 이 컴퓨터에서 도는 AI 입니다"),
      body: t("웹 조사, 엑셀 · 한글 · 장표, 코드까지 혼자 끝까지 합니다. 읽은 곳은 붙여 드립니다."),
      visual: { kind: "usage", scene: "this-pc" },
    },
    {
      title: t("다른 AI와 일을 나눠 동시에 합니다"),
      body: t("쓰던 AI가 맡긴 일을 이 PC에서 동시에 해냅니다."),
      visual: { kind: "usage", scene: "handoff" },
    },
    {
      title: t("클로드 한도를 덜 씁니다"),
      body: t("읽는 일은 이 PC가 해서, 클로드에는 결과만 갑니다."),
      visual: { kind: "usage", scene: "limit" },
    },
    {
      title: t("어디서든 부를 수 있습니다"),
      body: t("어디서 말해도 이 PC의 손자리가 합니다."),
      visual: { kind: "usage", scene: "anywhere" },
    },
  ];
}

/**
 * 쇼를 띄우는 자리. 두 길로 열린다.
 * - 저절로: 마법사를 마친 사람 중 아직 안 본 사람에게 **한 번**(백엔드 `usage_show` 가 가른다). 어떤 길로든 닫으면 「봤다」를 적는다.
 * - 직접: 사이드바 「쓰는 법」(`manualOpen`). 언제든 다시 열리고, 기록은 건드리지 않는다.
 *
 * 저절로 열려 있는 동안은 부모에게 `onActiveChange(true)` 로 알린다 — 같은 날 「바뀐 것」 줄도 떠야 하면 쓰는 법이 먼저다.
 */
export function UsageShowGate({ client, enabled = true, manualOpen, onManualClose, onActiveChange, onOpenSettings }: {
  client: Pick<JarvisClient, "getUsageShow" | "markUsageShowSeen"> | null;
  /** 파일럿(Claude API 판)처럼 설정이 없는 화면에서는 저절로 띄우지 않는다. */
  enabled?: boolean;
  manualOpen: boolean;
  onManualClose: () => void;
  onActiveChange?: (active: boolean) => void;
  onOpenSettings: (section: UsageSettingsSection) => void;
}) {
  const [auto, setAuto] = useState(false);
  const alive = useRef(true);
  const activeChange = useRef(onActiveChange);
  activeChange.current = onActiveChange;

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  useEffect(() => {
    if (!client || !enabled) return;
    void client.getUsageShow().then((status) => {
      if (!alive.current || !status.show) return;
      setAuto(true);
      activeChange.current?.(true);
    }).catch(() => {
      // 본체가 꺼져 있거나 옛 판이면 조용히 지나간다 — 소개는 덤이다.
    });
  }, [client, enabled]);

  const close = useCallback(() => {
    if (auto) {
      setAuto(false);
      activeChange.current?.(false);
      void client?.markUsageShowSeen().catch(() => undefined);
    }
    onManualClose();
  }, [auto, client, onManualClose]);

  const open = auto || manualOpen;
  if (!open) return null;
  // 창은 몸(body)에 띄운다 — 「바뀐 것」 창과 같은 까닭(낭독기가 장을 넘길 때마다 위 알림 칸을 다시 읽지 않게).
  return createPortal(
    <WhatsNewDeck version="" slides={usageSlides()} changes="" tour="" eyebrow={t("손자리 쓰는 법")}
      onLater={close} onDone={close}
      onOpenSettings={(section) => { close(); onOpenSettings(section); }} />,
    document.body,
  );
}
