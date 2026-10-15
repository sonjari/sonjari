import { t } from "../i18n";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ArrowUpCircle, Check, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { JarvisClient } from "../backend";
import type { UpdateStatus } from "../types";
import { UpdatingOverlay } from "./UpdatingOverlay";

/**
 * **받을 게 있습니다** — 위성 전용 알림 (2026-08-24).
 *
 * ## 왜 자동으로 안 받나
 *
 * 기동할 때 조용히 받게 하면 손이 안 가서 좋지만, **실패했을 때 아무도 모른다.**
 * 이 저장소는 그 구멍으로 여러 번 당했다 — 되돌리기가 조용히 실패해 스케줄러가
 * 엿새 죽어 있었고, TTS 가 다섯 번 죽는 동안 아무 데도 안 찍혔다.
 *
 * 사람이 누르면 사람이 안다. 그리고 되돌리기도 사람이 아는 상태에서 일어난다.
 *
 * ## 왜 「없으면 아예 안 그린다」인가
 *
 * 늘 떠 있는 상태 표시는 사람이 읽는 법을 잊는다. 받을 게 있을 때만 한 줄이
 * 나타나고, 받고 나면 사라진다.
 *
 * ## 기다리는 방식
 *
 * 누르면 백엔드가 **곧 죽는다**(자기 파일을 갈아치우려면 내려가야 한다). 그래서
 * 응답은 「시작했다」이고, 여기서는 `/health` 가 **기대한 판**으로 돌아올 때까지
 * 지켜본다. 200 이 오는 것은 증거가 아니다 — 안 죽은 옛 프로세스일 수 있다.
 */
const CHECK_INTERVAL_MS = 20 * 60 * 1000;
const FOCUS_RECHECK_MS = 60 * 1000;
const WAIT_LIMIT_MS = 4 * 60 * 1000;
/** 스토어판 업데이트를 누른 뒤, 도우미가 결과를 적었는지 물어보는 간격. */
const STORE_RESULT_POLL_MS = 3000;

/**
 * 업데이트가 왜 안 됐는지 사람의 다음 할 일로 (2026-10-05 AWS 영어 윈도우 첫 실행).
 *
 * 채널이 403 을 줬다(데이터센터·일부 회사망). 윈도우의 원문은 「Deployment failed with HRESULT: 0x80190193 …」 세 줄이다 —
 * 읽어도 무엇을 해야 할지 모른다. 막힌 것이면 「직접 받으라」고 말하고, 아니면 원문 첫 줄만 보여 준다.
 */
export function updateFailureText(error: string | undefined): string {
  const raw = (error || "").trim();
  if (/\b403\b|0x80190193/i.test(raw)) {
    return t("이 네트워크에서는 업데이트 주소가 막혀 있습니다(403). 설치 페이지에서 새 버전을 직접 받아 주세요");
  }
  const first = raw.split(/\r?\n/)[0] ?? "";
  return first ? (first.length > 160 ? `${first.slice(0, 160)}…` : first) : t("원인을 알 수 없습니다");
}

type Phase = "idle" | "applying" | "done" | "failed";
/** 스토어판: 덮개를 띄운 채 앱이 꺼지기를 기다린다 · 너무 오래 안 꺼지면 멈춘 것이다. */
type StorePhase = "idle" | "updating" | "stuck";

export function UpdateBar({ client, storePollMs = STORE_RESULT_POLL_MS }: { client: JarvisClient | null; storePollMs?: number }) {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [note, setNote] = useState("");
  const [storePhase, setStorePhase] = useState<StorePhase>("idle");
  const alive = useRef(true);

  // 켤 때 true 로 되돌린다 — 떼었다 다시 붙으면(StrictMode 등) false 로 남아 결과를 버린다(HealthBar 와 같은 고장).
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const check = useCallback(async () => {
    if (!client || phase !== "idle") return;
    try {
      const next = await client.checkUpdate();
      if (alive.current) setStatus(next);
    } catch {
      // 본체가 꺼져 있는 것은 흔한 일이다. 그때마다 빨간 것을 띄우면
      // 사람이 무시하는 법을 배운다.
    }
  }, [client, phase]);

  useEffect(() => {
    void check();
    const timer = window.setInterval(() => void check(), CHECK_INTERVAL_MS);
    // ★ 2026-09-20 노트북: 켤 때·20분마다만 봐서, 켜 둔 뒤 올라간 새 판이 최대 20분 동안 안 보였다.
    //   사람이 창으로 **돌아올 때**도 본다(1분에 한 번 이하 — 창을 오갈 때마다 서버를 두드리지 않게).
    let last = Date.now();
    const onFocus = () => {
      if (Date.now() - last < FOCUS_RECHECK_MS) return;
      last = Date.now();
      void check();
    };
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [check]);

  const apply = async () => {
    if (!client || !status?.theirs) return;
    setPhase("applying");
    setNote(t("받는 중입니다"));
    try {
      const started = await client.applyUpdate();
      if (!started.ok || !started.applied) {
        setPhase("failed");
        setNote(started.reason || t("시작하지 못했습니다"));
        return;
      }
    } catch (reason) {
      setPhase("failed");
      setNote(reason instanceof Error ? reason.message : t("시작하지 못했습니다"));
      return;
    }

    // 여기서부터 백엔드는 내려간다. **판이 바뀐 것을 눈으로 볼 때까지** 기다린다.
    setNote(t("갈아치우고 다시 켜는 중입니다"));
    const until = Date.now() + WAIT_LIMIT_MS;
    const want = status.theirs;
    while (Date.now() < until && alive.current) {
      await new Promise((wake) => window.setTimeout(wake, 5000));
      try {
        const health = await client.getHealth();
        const now = String((health as { build?: string }).build || "");
        if (now && now === want) {
          setPhase("done");
          setNote(t("새 판으로 올라왔습니다 · {0}", want.slice(0, 8)));
          window.setTimeout(() => alive.current && setStatus(null), 6000);
          return;
        }
      } catch {
        // 내려가 있는 동안은 당연히 안 된다. 계속 지켜본다.
      }
    }
    setPhase("failed");
    setNote(t("시간 안에 새 판이 안 올라왔습니다. 되돌렸을 수 있습니다 — 로그를 보세요."));
  };

  // ★ 스토어판 「지금 업데이트」 (2026-09-18 밤 사용자 요청). 예전에는 「껐다 켜면 윈도우가 바꿔 줍니다」라는
  //   글뿐이었고, 윈도우는 **다음에 켤 때** 바꿔서 두 번 켜야 할 때가 있었다. 이제 누르면 앱 밖의 도우미가 지금
  //   깔고 새 버전을 다시 연다(`store_update.apply`). 이 앱은 곧 꺼진다 — 응답은 「시작했다」일 뿐이다.
  const applyStore = async () => {
    if (!client) return;
    setStorePhase("updating");
    try {
      const started = await client.applyUpdate();
      if (!started.ok || !started.applied) {
        setStorePhase("idle");
        setNote(started.reason || t("업데이트를 시작하지 못했습니다"));
        return;
      }
    } catch (reason) {
      setStorePhase("idle");
      setNote(reason instanceof Error ? reason.message : t("업데이트를 시작하지 못했습니다"));
      return;
    }
    // 여기부터는 윈도우가 이 앱을 끄기를 기다린다. 끝내 안 꺼지면 덮개를 걷고 말한다 — 덮개에 갇히면 안 된다.
    //
    // ★ 2026-10-05 AWS 영어 윈도우 첫 실행: 채널이 403 을 줘서 도우미는 **2초 만에** 실패를 적었는데, 화면은 그걸 안 보고
    //   4분을 「업데이트하는 중」으로 서 있다가 「껐다 켜면 윈도우가 마저 바꿉니다」라고 했다 — 끝날 일이 아니었다.
    //   성공하면 이 앱은 꺼지므로, **꺼지지 않은 채 결과가 적혔다면 실패**다. 그 결과를 바로 읽어 사실대로 말한다.
    const until = Date.now() + WAIT_LIMIT_MS;
    while (Date.now() < until && alive.current) {
      await new Promise((wake) => window.setTimeout(wake, storePollMs));
      try {
        const next = await client.checkUpdate();
        if (next.kind === "store" && next.just_updated) {
          if (!alive.current) return;
          setStatus(next);
          setStorePhase("idle");
          return;
        }
      } catch {
        // 앱이 꺼지는 중이면 당연히 안 된다. 계속 지켜본다.
      }
    }
    if (alive.current) setStorePhase("stuck");
  };

  const justUpdated = status?.kind === "store" ? status.just_updated : undefined;
  const show = phase !== "idle" || Boolean(status?.available) || Boolean(justUpdated)
    || storePhase !== "idle" || Boolean(note);
  if (!show) return null;

  if (status?.kind === "store") {
    if (storePhase === "updating") {
      return <UpdatingOverlay from={status.mine} to={status.theirs} />;
    }
    // 새 버전으로 다시 열린 직후 — **무엇이 됐는지 한 번** 말한다. 실패도 말한다(조용히 옛 판이면 된 줄 안다).
    if (justUpdated && storePhase === "idle") {
      const ok = Boolean(justUpdated.ok);
      return (
        <AnimatePresence>
          <motion.div className={`update-bar ${ok ? "good" : "bad"}`} role="status"
                      initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
            {ok ? <Check size={14} /> : <AlertTriangle size={14} />}
            <b>{ok ? t("업데이트했습니다") : t("업데이트하지 못했습니다")}</b>
            <span>
              {ok
                ? `${justUpdated.from} → ${justUpdated.installed || justUpdated.to}`
                : t("{0} · 지금은 {1} 입니다", updateFailureText(justUpdated.error), justUpdated.installed || justUpdated.from)}
            </span>
            <button onClick={() => setStatus(null)}>{t("알겠습니다")}</button>
          </motion.div>
        </AnimatePresence>
      );
    }
    return (
      <AnimatePresence>
        <motion.div className={`update-bar${storePhase === "stuck" || note ? " bad" : ""}`} role="status"
                    initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
          {storePhase === "stuck" || note ? <AlertTriangle size={14} /> : <ArrowUpCircle size={14} />}
          <b>
            {storePhase === "stuck" ? t("업데이트가 끝나지 않았습니다") : note ? t("업데이트를 시작하지 못했습니다") : t("새 버전이 있습니다")}
          </b>
          <span>
            {storePhase === "stuck"
              ? t("결과를 확인하지 못했습니다. Sonjari를 껐다 켜 보고, 그대로면 설치 페이지에서 새 버전을 받아 주세요")
              : note || `${status.mine} → ${status.theirs}`}
          </span>
          {status.available && storePhase === "idle" && (
            <button onClick={() => { setNote(""); void applyStore(); }}>{note ? t("다시 시도") : t("지금 업데이트")}</button>
          )}
          <button onClick={() => { setStatus(null); setNote(""); setStorePhase("idle"); }}>{t("나중에")}</button>
        </motion.div>
      </AnimatePresence>
    );
  }

  return (
    <AnimatePresence>
      <motion.div
        className={`update-bar${phase === "failed" ? " bad" : ""}${phase === "done" ? " good" : ""}`}
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
      >
        {phase === "applying" ? <Loader2 size={14} className="spin" />
          : phase === "done" ? <Check size={14} />
          : <ArrowUpCircle size={14} />}
        <b>
          {phase === "idle" ? t("본체에 새 판이 있습니다") : note}
        </b>
        {phase === "idle" && (
          <>
            <span>
              {status?.mine?.slice(0, 8)} → {status?.theirs?.slice(0, 8)}
              {status?.total_bytes ? ` · ${(status.total_bytes / 1e6).toFixed(1)}MB` : ""}
            </span>
            <button onClick={() => void apply()}>{t("지금 받기")}</button>
          </>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
