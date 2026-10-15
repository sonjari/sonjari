/**
 * 브라우저 무대 작은 창 (`?mode=mini`, 2026-09-24).
 *
 * 바깥 AI 가 맡긴 일이 브라우저를 쓰는 동안 화면 구석에 뜬다(`stageMini.ts` 가 띄우고 닫는다). 크롬 창은 끝까지 안 뜬다 —
 * 이 창이 온텔릭 크롬 화면을 스트림으로 보여 주고, 누르면 여기서 바로 넘겨받는다. 크게 보려면 「작업 화면에서 보기」.
 */
import { t } from "../i18n";
import { Maximize2 } from "lucide-react";
import { useEffect, useState } from "react";
import { focusWorkspaceWindow, JarvisClient, loadBootstrap } from "../backend";
import { LiveStage } from "./LiveStage";
import "../workspace.css";

export function MiniStage() {
  const [client, setClient] = useState<JarvisClient | null>(null);
  useEffect(() => {
    let alive = true;
    void loadBootstrap().then((bootstrap) => {
      if (alive) setClient(new JarvisClient(bootstrap, () => undefined, () => undefined));
    });
    return () => { alive = false; };
  }, []);

  return (
    <main className="stage-mini">
      <header className="stage-mini-head">
        <span className="stage-mini-dot" aria-hidden />
        <strong>{t("Sonjari가 브라우저에서 일하는 중")}</strong>
        <button type="button" onClick={() => void focusWorkspaceWindow()} title={t("Sonjari 작업 화면에서 크게 봅니다")}>
          <Maximize2 size={13} /> {t("작업 화면에서 보기")}
        </button>
      </header>
      <LiveStage
        client={client}
        active={Boolean(client)}
        stage={false}
        caption=""
        where=""
        holdLastFrame
        fallback={<p className="stage-mini-wait">{t("화면을 준비하는 중입니다")}</p>}
      />
    </main>
  );
}

export default MiniStage;
