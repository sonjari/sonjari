/**
 * 팩을 켤 때 모델 · 실행기를 받는 칸 (2026-11-14 · 설계 §3-10).
 *
 * - 줄마다 이름 · 크기 · 라이선스 · 상태. 누른 것이 동의라서 받기 전에 크기와 라이선스가 먼저 보인다.
 * - 막대는 **백엔드가 준 받은 바이트(디스크에 실제로 있는 양)** 로만 채운다. 시간으로 채우지도, 남은 시간을 말하지도 않는다.
 *   크기를 모르는 줄(size 0)은 비율을 못 구하니 띠만 오간다.
 * - 거절은 상태 번호와 백엔드 글에서 「무엇이 잘못됐고 어떻게 하면 되는지」 한 줄로 바꾼다.
 * - 다른 운영체제 · 칩용 줄(`not_for_this_machine`)은 흐리게 「이 기계용 아님」만 — 받기 막대 · 단추를 붙이지 않는다(11-14 맥).
 * - 이 기계용이 아닌데 이미 받아진 것(leftovers)은 크기와 함께 보이고, 「지우기」는 한 번 더 확인한 뒤에만 지운다.
 */
import { t } from "../i18n";
import { Ban, CheckCircle2, Circle, CircleDashed, Download, ExternalLink, Loader2, Square, Trash2, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { JarvisClient } from "../backend";
import type { PackInfo, PackModelRow, PackModelsStatus } from "../types";

/** 받는 동안 상태를 다시 읽는 간격 — 진행값은 이 읽기로만 갱신한다. */
const POLL_MS = 1000;

export function formatBytes(bytes: number): string {
  if (!(bytes > 0)) return "0 MB";
  const mb = bytes / 1e6;
  if (mb < 1000) return `${Math.max(1, Math.round(mb))} MB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

/** 받은 비율(0~100). 크기를 모르면 null — 그때는 띠만 오간다. */
export function receivedPercent(row: Pick<PackModelRow, "received" | "size">): number | null {
  if (!(row.size > 0)) return null;
  return Math.max(0, Math.min(100, Math.floor((row.received / row.size) * 100)));
}

/** 거절 · 실패를 사람 말 한 줄로. 코드 이름은 보이지 않는다. */
export function modelsProblem(reason: unknown, status?: PackModelsStatus | null): string {
  const http = (reason as { status?: number } | null)?.status;
  const detail = (reason as { detail?: unknown } | null)?.detail;
  const code = typeof detail === "string"
    ? detail
    : detail && typeof detail === "object" && typeof (detail as { error?: unknown }).error === "string"
      ? String((detail as { error: string }).error)
      : reason instanceof Error ? reason.message : String(reason ?? "");
  if (http === 409 || code.startsWith("pack_not_enabled")) {
    return t("팩이 꺼져 있어 받을 수 없습니다. 팩을 켠 뒤 다시 눌러 주세요.");
  }
  if (http === 507 || code.startsWith("not_enough_disk")) {
    const snapshot = (detail && typeof detail === "object" ? detail : status) as Partial<PackModelsStatus> | null | undefined;
    if (snapshot?.disk_needed_bytes) {
      return t("디스크 빈 공간이 모자랍니다. {0} 필요, {1} 남음. 자리를 비운 뒤 다시 눌러 주세요.",
        formatBytes(snapshot.disk_needed_bytes), formatBytes(snapshot.disk_free_bytes ?? 0));
    }
    return t("디스크 빈 공간이 모자랍니다. 자리를 비운 뒤 다시 눌러 주세요.");
  }
  if (code.startsWith("sha256_mismatch")) {
    return t("받은 파일이 원본과 달라 지웠습니다. 다시 받아 보고, 또 같으면 팩 만든 쪽에 알려 주세요.");
  }
  if (/^(network|incomplete|http_\d+)/.test(code)) {
    return t("받는 도중 끊겼습니다. 인터넷을 확인하고 다시 누르면 받은 데서 이어 받습니다.");
  }
  if (code.startsWith("no_prebuilt")) {
    return t("이 기계용 실행기는 받을 곳이 아직 없습니다. 빌드한 것을 정해진 폴더에 넣거나 거울 폴더에 두고 다시 눌러 주세요.");
  }
  if (code.startsWith("busy")) {
    return t("받는 중에는 지울 수 없습니다. 받기가 끝난 뒤 다시 눌러 주세요.");
  }
  if (code.startsWith("blocked_url") || code.startsWith("unsafe_")) {
    return t("팩이 허락되지 않은 주소나 경로를 가리켜 멈췄습니다. 믿을 수 있는 곳에서 받은 팩인지 확인해 주세요.");
  }
  return t("받지 못했습니다: {0}", code || t("알 수 없는 오류"));
}

/**
 * 「켜고 받기」 뒤 결과 한 줄의 진행(11-16 저녁). 이 기계용 · 꼭 있어야 하는 줄만 센다.
 * 설정한 자리에 있는 줄(configured)은 개수에는 들어가되(이미 됨) 받을 바이트에는 안 들어간다.
 */
export function packFetchProgress(status: PackModelsStatus): { state: "waiting" | "running" | "ready" | "failed"; done: number; count: number; received: number; total: number; problem?: string } {
  const mine = status.models.filter((row) => row.state !== "not_for_this_machine" && row.required);
  const fetched = mine.filter((row) => !row.configured);
  const done = mine.filter((row) => row.state === "ready").length;
  const total = fetched.reduce((sum, row) => sum + Math.max(0, row.size), 0);
  const received = fetched.reduce((sum, row) => sum + Math.min(Math.max(0, row.received), Math.max(0, row.size)), 0);
  const base = { done, count: mine.length, received, total };
  if (status.all_ready) return { ...base, state: "ready" };
  if (status.state === "failed" || status.state === "cancelled" || status.state === "done") {
    return { ...base, state: "failed", problem: status.error ? modelsProblem(status.error, status) : undefined };
  }
  return { ...base, state: status.state === "running" ? "running" : "waiting" };
}

/** 받기 전에 보이는 한 줄 — 「켜면 약 N 을 받습니다 · 받는 자리 · 남은 자리」 또는 자리가 모자란 까닭. */
export function packFetchPlan(status: PackModelsStatus | null): { line: string; blocked: boolean } | null {
  if (!status) return null;
  if (!status.needs_fetch) {
    return status.models.some((row) => row.configured)
      ? { line: t("필요한 파일은 설정한 자리에 이미 있습니다. 켜면 바로 씁니다."), blocked: false }
      : null;
  }
  const where = status.root ? t("받는 자리 {0}", status.root) : "";
  const free = t("남은 자리 {0}", formatBytes(status.disk_free_bytes));
  if (!status.disk_ok) {
    return {
      line: t("자리가 모자랍니다. 필요 {0} · 남은 자리 {1}", formatBytes(status.disk_needed_bytes), formatBytes(status.disk_free_bytes))
        + " — " + t("설정 › 일반 › 팩 파일 자리에서 큰 드라이브를 고른 뒤 다시 눌러 주세요."),
      blocked: true,
    };
  }
  const main = status.to_download_bytes > 0
    ? t("켜면 필요한 파일 약 {0}를 받습니다", formatBytes(status.to_download_bytes))
    : t("켜면 필요한 파일을 미리 받아 둔 자리에서 들입니다");
  return { line: [main, where, free].filter(Boolean).join(" · "), blocked: false };
}

function RowIcon({ state }: { state: PackModelRow["state"] }) {
  if (state === "not_for_this_machine") return <Ban size={16} className="pm-todo" aria-label={t("이 기계용 아님")} />;
  if (state === "ready") return <CheckCircle2 size={16} className="pm-ok" aria-label={t("받음")} />;
  if (state === "downloading") return <Loader2 size={16} className="pm-work spin" aria-label={t("받는 중")} />;
  if (state === "failed") return <TriangleAlert size={16} className="pm-bad" aria-label={t("실패")} />;
  if (state === "partial") return <CircleDashed size={16} className="pm-todo" aria-label={t("일부 받음")} />;
  return <Circle size={16} className="pm-todo" aria-label={t("안 받음")} />;
}

function Bar({ row }: { row: PackModelRow }) {
  const percent = receivedPercent(row);
  return percent === null
    ? <span className="pm-bar is-unknown" role="progressbar" aria-label={t("받는 중")}><i /></span>
    : <span className="pm-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <i style={{ width: `${percent}%` }} />
      </span>;
}

export function PackModels({ pack, client, onStatus }: { pack: PackInfo; client: JarvisClient; onStatus?: (status: PackModelsStatus) => void }) {
  const [status, setStatus] = useState<PackModelsStatus | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  /** 지우기는 두 번 누른다 — 첫 번은 묻기만. */
  const [confirmRemove, setConfirmRemove] = useState(false);
  const alive = useRef(true);
  const models = pack.models ?? [];

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await client.packModels(pack.id);
      if (alive.current) {
        setStatus(next);
        onStatus?.(next);
      }
    } catch (reason) {
      if (alive.current) setProblem(modelsProblem(reason));
    }
  }, [client, pack.id, onStatus]);

  // 꺼진 팩도 한 번 읽는다(11-16 저녁) — 켜기 전에 「켜면 약 N 을 받습니다 · 자리」를 보이려고(읽기만 · 받지 않는다).
  // 켜고 끌 때 다시 읽고, 받는 중에는 간격으로 다시 읽는다.
  useEffect(() => {
    if (models.length > 0) void refresh();
  }, [pack.enabled, models.length, refresh]);

  const running = status?.state === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, refresh]);

  if (models.length === 0) return null;

  const start = async () => {
    setBusy(true);
    setProblem("");
    try {
      const next = await client.fetchPackModels(pack.id);
      if (alive.current) setStatus(next);
    } catch (reason) {
      if (alive.current) setProblem(modelsProblem(reason, status));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    try {
      const next = await client.cancelPackModels(pack.id);
      if (alive.current) setStatus(next);
    } catch (reason) {
      if (alive.current) setProblem(modelsProblem(reason, status));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const removeLeftovers = async () => {
    setBusy(true);
    setProblem("");
    try {
      const next = await client.removePackLeftovers(pack.id);
      if (alive.current) setStatus(next);
    } catch (reason) {
      if (alive.current) setProblem(modelsProblem(reason, status));
    } finally {
      if (alive.current) {
        setBusy(false);
        setConfirmRemove(false);
      }
    }
  };

  const rows: PackModelRow[] = status
    ? status.models
    : models.map((m) => ({ ...m, state: "missing" as const, received: 0, error: "" }));
  const leftovers = status?.leftovers ?? [];
  const leftoverBytes = leftovers.reduce((sum, row) => sum + row.bytes, 0);
  const failedText = status?.state === "failed" && !problem ? modelsProblem(status.error, status) : "";
  const rowError = (row: PackModelRow) => (row.state === "failed" && row.error && !failedText ? modelsProblem(row.error, status) : "");
  const allReady = Boolean(status?.all_ready);
  const anyPartial = rows.some((r) => r.state === "partial");

  return (
    <div className="pack-models" data-testid={`pack-models-${pack.id}`}>
      <ul className="pm-list">
        {rows.map((row) => (
          <li key={row.id} className={`pm-row is-${row.state}`} data-state={row.state}>
            <RowIcon state={row.state} />
            <span className="pm-name">{row.id}</span>
            {row.state === "not_for_this_machine"
              ? <span className="pm-foreign">{t("이 기계용 아님")}</span>
              : row.configured
                ? <span className="pm-foreign" title={row.path}>{t("설정한 자리에 있음 · 받지 않아도 됨")}</span>
                : <span className="pm-size">{formatBytes(row.size)}</span>}
            <a className="pm-license" href={row.license_url} target="_blank" rel="noreferrer" title={row.license}>
              <ExternalLink size={12} aria-hidden="true" /> {row.license.split("(")[0].trim()}
            </a>
            {row.state === "downloading" && (
              <>
                <Bar row={row} />
                <span className="pm-bytes">{formatBytes(row.received)} / {formatBytes(row.size)}</span>
              </>
            )}
            {row.state === "partial" && <span className="pm-bytes">{formatBytes(row.received)} / {formatBytes(row.size)}</span>}
            {rowError(row) && <span className="pm-error" role="alert">{rowError(row)}</span>}
          </li>
        ))}
      </ul>
      {leftovers.length > 0 && (
        <div className="pm-leftovers" data-testid="pm-leftovers">
          <span>
            {t("이 기계에서 못 쓰는 것이 받아져 있습니다: {0} · {1}", leftovers.map((row) => row.id).join(", "), formatBytes(leftoverBytes))}
          </span>
          {confirmRemove ? (
            <>
              <button type="button" className="setup-btn-quiet" onClick={() => void removeLeftovers()} disabled={busy}>
                <Trash2 size={13} aria-hidden="true" /> {t("정말 지우기")}
              </button>
              <button type="button" className="setup-btn-quiet" onClick={() => setConfirmRemove(false)} disabled={busy}>
                {t("그만")}
              </button>
            </>
          ) : (
            <button type="button" className="setup-btn-quiet" onClick={() => setConfirmRemove(true)} disabled={busy || running}>
              <Trash2 size={13} aria-hidden="true" /> {t("지우기")}
            </button>
          )}
        </div>
      )}
      {(problem || failedText) && <p className="pm-error" role="alert">{problem || failedText}</p>}
      {pack.enabled && !allReady && (
        <div className="pm-actions">
          {running ? (
            <button type="button" className="setup-btn-quiet" onClick={() => void stop()} disabled={busy || Boolean(status?.cancelling)}>
              <Square size={13} aria-hidden="true" /> {status?.cancelling ? t("멈추는 중") : t("멈추기")}
            </button>
          ) : (
            <button type="button" className="setup-btn-go" onClick={() => void start()} disabled={busy}>
              {busy ? <Loader2 size={14} className="spin" /> : <Download size={14} aria-hidden="true" />}{" "}
              {anyPartial ? t("이어 받기") : t("받기")}
              {status && status.to_download_bytes > 0 && <span className="pm-total"> {formatBytes(status.to_download_bytes)}</span>}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
