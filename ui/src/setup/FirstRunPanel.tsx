/**
 * 첫 실행 1단계에 붙는 두 칸 (W1·W2, 2026-09-15).
 *
 * - **Ollama** — 이미 돌면 「쓰는 중」만 말한다. 없으면 버튼 한 번: 공식 릴리스 zip 을 받아
 *   해시를 대조하고 자비스 데이터 폴더에 풀어 켠다. 누른 것이 동의다 — 누르기 전엔 아무것도 안 받는다.
 * - **이전 기억** — 사용자 폴더의 복제본(앱을 지워도 남는다)이 있고 지금 기억이 비어 있을 때만
 *   「이전 기억을 가져올까요?」를 묻는다.
 *
 * 로고: 제3자 로고는 브랜드 가이드 확인 전이라 **중립 아이콘 자리**만 둔다(`data-logo-slot`).
 * 화면은 계산하지 않는다 — 단계·해시 결과는 백엔드가 준다.
 */
import { t } from "../i18n";
import { Cpu, History } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { BackupStatus, OllamaStatus, SetupApi } from "./setupApi";
import { pollUnlessBusy } from "./poll";

const PHASE_TEXT: Record<string, string> = {
  resolving: t("공식 릴리스를 확인하는 중"),
  downloading: t("받는 중"),
  verifying: t("받은 파일의 해시를 공식 값과 대조하는 중"),
  extracting: t("푸는 중"),
  starting: t("켜는 중"),
  ready: t("켜졌습니다"),
  error: t("설치하지 못했습니다"),
};

export function ollamaLine(status: OllamaStatus | null): string {
  if (!status) return t("Ollama 가 있는지 보는 중입니다…");
  // ★ 2026-09-18 노트북: 서버는 켜져 있고 목록도 답하는데 모델을 돌리는 파일(llama-server)이 없어 **모델이 하나도
  //   안 올라갔다.** 그때 이 줄은 「돌고 있습니다」였다 — 멀쩡해 보이는 말이 고장을 덮었다.
  if (status.runner_missing) return t("Ollama 설치가 덜 됐습니다 — 모델을 돌리는 파일이 없습니다. 다시 설치해 주세요.");
  if (status.running) return t("Ollama {0} 가 돌고 있습니다{1}.", status.version, status.managed ? t(" — Sonjari가 켰습니다") : t(" — 그대로 씁니다"));
  const phase = status.install.phase;
  if (phase === "downloading" && status.install.total) {
    const percent = Math.min(100, Math.round(((status.install.received ?? 0) / status.install.total) * 100));
    return `${PHASE_TEXT.downloading} · ${percent}%`;
  }
  if (phase === "error") return t("{0} ({1})", PHASE_TEXT.error, status.install.error || t("원인 모름"));
  if (phase !== "idle" && PHASE_TEXT[phase]) return PHASE_TEXT[phase];
  return t("Ollama 가 없습니다. Sonjari의 로컬 AI 엔진입니다.");
}

/**
 * `ollamaOnly` — 모델 단계에 붙는 꼴(2026-10-06 스토어 공개판 첫 설치, RTX 3050 사무실 PC).
 *   Ollama 를 안 깐 채 「받고 적용하기」를 누르면 「위의 『Ollama 설치』를 먼저 눌러 주세요」가 떴는데, 그 단추는
 *   **앞 단계에만** 있었다 — 글이 화면에 없는 것을 가리켰다. 글이 뜰 수 있는 자리에는 그 단추도 같이 둔다.
 *   이 꼴은 Ollama 가 **돌고 있으면 아무것도 안 그리고**, 이전 기억 칸도 안 보인다.
 */
export function FirstRunPanel({ api, onOllamaReady, ollamaOnly = false }: { api: SetupApi | null; onOllamaReady?: () => void; ollamaOnly?: boolean }) {
  const [ollama, setOllama] = useState<OllamaStatus | null>(null);
  const [backup, setBackup] = useState<BackupStatus | null>(null);
  const [restore, setRestore] = useState<"ask" | "busy" | "done" | "skipped" | string>("ask");
  const timer = useRef<number | null>(null);
  // ★ 2026-10-05 AWS 영어 윈도우 첫 실행: 여기서 Ollama 를 깔아 「돌고 있습니다」가 됐는데, 옆의 PC 점검 표는
  //   처음 잰 값 그대로 「꺼져 있거나 설치되지 않았습니다」였다. 꺼져 있던 것이 켜진 순간을 알려 표를 다시 재게 한다.
  const wasRunning = useRef<boolean | null>(null);
  const running = ollama ? ollama.running : null;
  useEffect(() => {
    if (running === null) return;
    if (wasRunning.current === false && running) onOllamaReady?.();
    wasRunning.current = running;
  }, [running, onOllamaReady]);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    void api.ollamaStatus().then((view) => alive && setOllama(view)).catch(() => undefined);
    void api.backupStatus().then((view) => alive && setBackup(view)).catch(() => undefined);
    return () => {
      alive = false;
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [api]);

  const installing = ollama !== null && !ollama.running && !["idle", "ready", "error"].includes(ollama.install.phase);
  useEffect(() => {
    if (!api || !installing) return;
    return pollUnlessBusy(() => api.ollamaStatus().then(setOllama), 800);
  }, [api, installing]);

  const install = async () => {
    if (!api) return;
    const started = await api.ollamaInstall();
    if (!started.ok) {
      setOllama((current) => current && { ...current, install: { phase: "error", error: started.error } });
      return;
    }
    setOllama((current) => current && { ...current, can_install: false, install: { phase: started.phase ?? "resolving" } });
  };

  const bringBack = async () => {
    if (!api || !backup?.latest) return;
    setRestore("busy");
    const done = await api.backupRestore(backup.latest.generation);
    setRestore(done.ok ? "done" : done.error || "error");
  };

  const showRestore = Boolean(!ollamaOnly && backup?.enabled && backup.latest && backup.memory_empty && restore !== "skipped");

  if (ollamaOnly && (!ollama || (ollama.running && !ollama.runner_missing))) return null;

  return (
    <div className="firstrun">
      <div className="firstrun-row" data-testid="ollama-row">
        <span className="firstrun-logo" data-logo-slot="ollama" aria-hidden="true">
          <Cpu size={18} strokeWidth={1.6} />
        </span>
        <span className="firstrun-text">
          <b>Ollama</b>
          <span>{ollamaLine(ollama)}</span>
        </span>
        {ollama?.can_install && (
          <button type="button" className="setup-btn-go" onClick={() => void install()}>
            {ollama.runner_missing ? t("Ollama 다시 설치") : t("Ollama 설치")}
          </button>
        )}
      </div>
      {ollama?.can_install && (
        <p className="firstrun-fine">{t("공식 GitHub 릴리스에서 받아 해시를 대조한 뒤에만 켭니다. 받은 모델은 사용자 폴더에 남습니다.")}</p>
      )}

      {showRestore && backup?.latest && (
        <div className="firstrun-row" data-testid="restore-row">
          <span className="firstrun-logo" aria-hidden="true">
            <History size={18} strokeWidth={1.6} />
          </span>
          <span className="firstrun-text">
            <b>{t("이전 기억을 가져올까요?")}</b>
            <span>
              {restore === "done"
                ? t("가져왔습니다. 대화와 배운 사실이 돌아왔습니다.")
                : restore === "busy"
                  ? t("가져오는 중…")
                  : restore === "ask"
                    ? t("{0} 복제본 · 대화 {1}줄 · 배운 사실 {2}개", new Date(backup.latest.created_at * 1000).toLocaleString(), backup.latest.tables.conversation_messages ?? 0, backup.latest.tables.facts ?? 0)
                    : t("가져오지 못했습니다 ({0})", restore)}
            </span>
          </span>
          {restore === "ask" && (
            <span className="firstrun-actions">
              <button type="button" className="setup-btn-go" onClick={() => void bringBack()}>
                {t("가져오기")}
              </button>
              <button type="button" className="setup-btn-quiet" onClick={() => setRestore("skipped")}>
                {t("새로 시작")}
              </button>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
