import { t } from "../i18n";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Check, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { JarvisClient } from "../backend";
import type { SelfCheckOrgan, SelfCheckStatus } from "../types";

/**
 * **켤 때 스스로 점검한 결과** — 고장일 때만 한 줄 (2026-09-18).
 *
 * ## 왜
 *
 * 노트북 온텔릭은 서버는 켜지고 목록도 답하는데 모델을 하나도 못 올리는 채로 있었다. 점검 도구는 있었지만
 * 사람이 「너 괜찮아?」라고 물을 때만 돌았다. 그래서 켤 때 엔진·모델을 한 번 보고(`boot_check`), 여기서는
 * **고장이 있을 때만** 그 한 줄을 보여 준다 — 늘 떠 있는 상태 표시는 사람이 읽는 법을 잊는다(업데이트 줄과 같은 규칙).
 *
 * ## 고치기
 *
 * 백엔드가 「이 버튼으로 고칠 수 있다」고 말한 것(`healer`)만 누를 수 있다. 고쳤다는 말은 증거가 아니라서,
 * 누른 뒤 백엔드가 **다시 점검한 결과**로 줄을 바꾼다.
 */
const POLL_MS = 15_000;
const QUIET_AFTER_MS = 10 * 60 * 1000;

const HEALER_LABEL: Record<string, string> = {
  repair_ollama: t("Ollama 고치기"),
  reload_model: t("모델 다시 올리기"),
  restart_tts: t("음성 다시 켜기"),
  restart_browser: t("브라우저 다시 켜기"),
};

export function HealthBar({ client }: { client: JarvisClient | null }) {
  const [status, setStatus] = useState<SelfCheckStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  // 진단 파일 안내는 고장 설명과 **다른 말**이다 — 본문 뒤에 이어 붙이면 「너무 느립니다 … — 진단 파일을 …」처럼
  // 한 문장으로 읽혀 무엇이 고장이고 무엇이 안내인지 갈리지 않았다(2026-09-18 노트북). 그래서 따로 쥐고 따로 그린다.
  const [diagnostics, setDiagnostics] = useState("");
  const [dismissed, setDismissed] = useState(false);
  const alive = useRef(true);
  const started = useRef(Date.now());

  // ★ 켤 때 true 로 **되돌려야** 한다. 개발 모드(StrictMode)는 붙였다 떼었다 다시 붙이는데, 떼면서 false 가 된 채로
  //   남아 점검 결과를 영영 안 그렸다(2026-09-18 리허설에서 발견). 릴리스에서는 안 보이지만 한 번 떼었다 붙는 순간 같은 일이다.
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const read = useCallback(async () => {
    if (!client) return;
    try {
      const next = await client.getSelfCheck();
      if (alive.current) setStatus(next);
    } catch {
      // 본체가 꺼져 있는 것은 흔한 일이다 — 그때마다 빨간 것을 띄우면 무시하는 법을 배운다.
    }
  }, [client]);

  // 켤 때 점검은 몇십 초 뒤에 끝난다 — 결과가 올 때까지만 자주 묻고, 받고 나면 가끔 묻는다.
  // ★ `status` 를 의존성에 넣으면 안 된다. 결과가 올 때마다 효과가 다시 돌며 **즉시 또 묻고**, 그 답이 또 새 결과라
  //   요청이 요청을 불렀다 — 리허설 실측 5초에 232번(2026-09-18). 타이머는 최신 결과를 ref 로만 본다.
  const statusRef = useRef<SelfCheckStatus | null>(null);
  statusRef.current = status;
  useEffect(() => {
    void read();
    const timer = window.setInterval(() => {
      const last = statusRef.current;
      // ★ 고장이 떠 있으면 10분이 지나도 계속 묻는다(2026-09-29 밤 AWS). 새 PC 는 마법사가 10분을 넘기기도 하는데,
      //   그 뒤에 묻기를 멈추면 백엔드가 「이제 괜찮다」고 해도 빨간 줄이 안 사라진다.
      const stillDown = Boolean(last?.organs?.some((organ) => organ.state === "down"));
      if (last && !last.pending && !stillDown && Date.now() - started.current > QUIET_AFTER_MS) return;
      void read();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [read]);

  const down: SelfCheckOrgan[] = (status?.organs ?? []).filter((organ) => organ.state === "down");
  if (dismissed || (!busy && !down.length && !note)) return null;

  const exportDiagnostics = async () => {
    if (!client) return;
    try {
      await client.exportDiagnostics();
      await client.openFolder("diagnostics");
      setDiagnostics(t("진단 파일을 만들고 폴더를 열었습니다 — 그 파일을 보내 주시면 원인을 볼 수 있습니다."));
    } catch (reason) {
      setDiagnostics(t("진단 파일을 만들지 못했습니다 — {0}", reason instanceof Error ? reason.message : String(reason)));
    }
  };

  const heal = async (action: string) => {
    if (!client) return;
    setBusy(true);
    setNote(t("고치는 중입니다 — 끝나면 다시 점검합니다"));
    try {
      const result = await client.healSelf(action);
      const after = await client.getSelfCheck();
      if (alive.current) setStatus(after);
      setNote(result.fixed ? t("고쳤습니다. 다시 점검해 보니 괜찮습니다.") : result.why || result.error || t("아직 그대로입니다"));
    } catch (reason) {
      setNote(reason instanceof Error ? reason.message : t("고치지 못했습니다"));
    } finally {
      setBusy(false);
    }
  };

  const fixedNow = !busy && note && !down.length;
  // 두 번째 줄 — 고치기 결과(아직 그대로면)와 진단 파일 안내. 본문과 섞지 않는다.
  const followUp = [!busy && !fixedNow ? note : "", !busy && !fixedNow ? diagnostics : ""].filter(Boolean);
  return (
    <AnimatePresence>
      <motion.div
        className={`update-bar health-bar${fixedNow ? " good" : " bad"}`}
        role="status"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
      >
        {busy ? <Loader2 size={14} className="spin" /> : fixedNow ? <Check size={14} /> : <AlertTriangle size={14} />}
        <b>{fixedNow ? t("점검 통과") : busy ? note : t("Sonjari 점검에서 문제가 보입니다")}</b>
        {!busy && <span>{fixedNow ? note : down.map((organ) => organ.detail).join(" · ")}</span>}
        {!busy && (
          <div className="health-bar-actions">
            {!fixedNow && down.filter((organ) => organ.healer).slice(0, 1).map((organ) => (
              <button key={organ.healer} onClick={() => void heal(organ.healer)}>
                {HEALER_LABEL[organ.healer] ?? t("고치기")}
              </button>
            ))}
            {/* 고칠 버튼이 없거나 고쳐도 그대로면 — 원인이 보이는 파일을 만들어 폴더를 연다(설정 화면의 그 기능).
                오늘 노트북 진단은 PowerShell 명령 여덟 번이었다. 그 여덟 번이 이 파일 하나에 들어 있다. */}
            {!fixedNow && (
              <button onClick={() => void exportDiagnostics()}>
                {diagnostics ? t("진단 파일 다시 만들기") : t("진단 파일 만들기")}
              </button>
            )}
            {(fixedNow || !down.some((organ) => organ.healer)) && (
              <button onClick={() => setDismissed(true)}>{t("알겠습니다")}</button>
            )}
          </div>
        )}
        {followUp.length > 0 && (
          <p className="health-bar-note">{followUp.join(" ")}</p>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
