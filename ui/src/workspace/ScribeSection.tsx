/**
 * 설정 › 서기 (2026-10-22 대표 — 실험실에서 꺼냄).
 *
 * 클로드 코드는 대화가 길어지면 앞을 요약(압축)하고, 그때 오래된 결정을 잃는다. 서기는 손자리가 쉴 때 그 대화를 읽어
 * 정한 것 · 버린 것 · 남은 일을 카드로 적어 두고, 압축되거나 새 대화를 열 때 클로드에게 다시 넣어 준다.
 *
 * ## 지키는 것
 *
 * - **경로를 손으로 치지 않는다.** 이 PC 의 클로드 코드 프로젝트를 백엔드가 찾아 주고(`/v1/scribe/status`) 사람은 체크로 고른다.
 *   이름은 기록 폴더(`E----------`, 한글이 `-` 로 바뀜)가 아니라 그 대화를 연 **작업 폴더**로 보여 준다.
 * - 켜기 전에 하는 일을 먼저 보인다: 기록은 PC 밖으로 안 나감 · 클로드 코드 설정에 훅을 넣음(백업 · 끄면 뺌) · 쉴 때만 읽음.
 * - 저장은 설정 화면의 같은 길(`save`)로 — 저장 중 · 저장됨 · 오류 표시와 순서가 다른 칸과 같다.
 * - 임시 폴더에서 연 대화(측정 · 시험)는 접어 둔다. 지우거나 숨기지는 않는다.
 */
import { t } from "../i18n";
import { Clock3, FileCog, HardDrive, Loader2, NotebookPen, RotateCw, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import type { JarvisClient } from "../backend";
import type { ScribeProject, ScribeStatus, SettingRow, SettingValue } from "../types";
import "./scribe.css";

/** 마지막으로 바뀐 때 — 분 · 시간 · 일. 초는 안 쓴다(목록은 다시 그리지 않는다). */
export function scribeAgo(at: number, now: number): string {
  if (!at) return t("기록 없음");
  const minutes = Math.max(0, Math.round((now - at) / 60));
  if (minutes < 1) return t("방금");
  if (minutes < 60) return t("{0}분 전", minutes);
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t("{0}시간 전", hours);
  return t("{0}일 전", Math.round(hours / 24));
}

/** 고른 폴더 목록을 바꾼다 — 같은 폴더를 두 번 넣지 않고, 순서는 처음 고른 순서. 윈도우 경로라 대소문자는 하나로 본다. */
export function toggleFolder(chosen: string[], folder: string, on: boolean): string[] {
  const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();
  const rest = chosen.filter((item) => !same(item, folder));
  return on ? [...rest, folder] : rest;
}

/** 켰는데 일을 못 하는 까닭 — 사람이 고칠 수 있는 것만. 없으면 빈 문자열. */
export function scribeWarning(status: ScribeStatus, enabled: boolean): string {
  if (!enabled) return "";
  if (!status.projects.some((item) => item.chosen)) return t("읽을 프로젝트를 아래에서 하나 이상 골라 주세요. 고르기 전에는 아무것도 읽지 않습니다.");
  if (!status.hooks.installed) return t("클로드 코드 설정에 훅이 아직 들어가지 않았습니다. 설정 파일이 깨져 있으면 손대지 않습니다. 손자리를 다시 켜면 다시 넣어 봅니다.");
  return "";
}

export function ScribeSection({ client, rows, control, save }: {
  client: JarvisClient;
  rows: SettingRow[];
  control: (row: SettingRow) => ReactNode;
  save: (key: string, value: SettingValue) => Promise<boolean>;
}) {
  const [status, setStatus] = useState<ScribeStatus | null>(null);
  const [error, setError] = useState("");
  const [busyFolder, setBusyFolder] = useState("");
  const enabledRow = rows.find((row) => row.key === "scribe_enabled");
  const foldersRow = rows.find((row) => row.key === "scribe_folders");
  const enabled = Boolean(enabledRow?.value);

  const load = useCallback(() => {
    client.getScribeStatus()
      .then((next) => { setStatus(next); setError(""); })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [client]);

  // 켜고 끄거나 폴더를 바꾸면 훅 · 카드 상태가 바뀐다 — 설정 값이 바뀔 때마다 다시 읽는다.
  useEffect(load, [load, enabled, JSON.stringify(foldersRow?.value ?? [])]);

  const chosen = useMemo(() => (Array.isArray(foldersRow?.value) ? (foldersRow?.value as string[]) : []), [foldersRow]);
  const pick = async (project: ScribeProject, on: boolean) => {
    setBusyFolder(project.folder);
    try {
      await save("scribe_folders", toggleFolder(chosen, project.folder, on));
    } finally {
      setBusyFolder("");
    }
  };

  const now = Date.now() / 1000;
  const projects = status?.projects ?? [];
  const main = projects.filter((item) => !item.temp || item.chosen);
  const temp = projects.filter((item) => item.temp && !item.chosen);
  const warning = status ? scribeWarning(status, enabled) : "";

  const project = (item: ScribeProject) => {
    const id = `scribe-project-${item.name}`;
    const busy = busyFolder === item.folder;
    return (
      <li key={item.folder} className={`scribe-project${item.chosen ? " is-chosen" : ""}`}>
        <input id={id} type="checkbox" checked={item.chosen} disabled={!!busyFolder}
          onChange={(event) => void pick(item, event.target.checked)} />
        <label htmlFor={id}>
          <span className="scribe-project-where">{item.workdir || item.name}</span>
          <span className="scribe-project-meta">
            {item.missing ? t("폴더가 없습니다") : t("대화 {0}개 · 마지막 {1}", item.sessions, scribeAgo(item.last_at, now))}
          </span>
        </label>
        {busy && <Loader2 size={14} className="spin" aria-label={t("저장하는 중")} />}
      </li>
    );
  };

  return (
    <div className="settings-block scribe">
      <div className="scribe-lede">
        <span className="scribe-lede-icon" aria-hidden><NotebookPen size={16} /></span>
        <div>
          <p className="scribe-lede-title">{t("클로드 코드가 대화를 압축해도 정한 것을 잊지 않게")} <em className="settings-lab">{t("베타")}</em></p>
          <p className="settings-note">{t("클로드 코드는 대화가 길어지면 앞부분을 요약하고, 그때 오래된 결정이 빠집니다. 서기는 대화를 읽어 정한 것 · 버린 것 · 남은 일을 카드로 적어 두었다가, 압축되거나 새 대화를 열 때 클로드에게 다시 넣어 줍니다.")}</p>
        </div>
      </div>

      <ul className="scribe-promises" aria-label={t("켜면 이렇게 됩니다")}>
        <li><HardDrive size={14} aria-hidden /><span>{t("대화 기록은 이 PC 안에서만 읽습니다. 밖으로 보내지 않습니다.")}</span></li>
        <li><FileCog size={14} aria-hidden /><span>{t("클로드 코드 설정 파일에 훅 셋을 넣습니다. 넣기 전에 원래 파일을 백업하고, 끄면 손자리가 넣은 것만 뺍니다.")}</span></li>
        <li><Clock3 size={14} aria-hidden /><span>{t("손자리가 쉴 때만 읽습니다. 일을 시키면 바로 멈춥니다.")}</span></li>
      </ul>

      {enabledRow && <ul className="settings-rows">{control(enabledRow)}</ul>}

      {error && <p className="settings-error" role="alert">{t("서기 상태를 읽지 못했습니다")} ({error})</p>}
      {!status && !error && <p className="settings-note"><Loader2 size={14} className="spin" /> {t("이 PC 의 클로드 코드 대화를 찾는 중입니다")}</p>}

      {status && enabled && (
        <dl className="scribe-ledger" aria-label={t("서기 상태")}>
          <div><dt>{t("쌓인 카드")}</dt><dd>{status.cards}</dd></div>
          <div><dt>{t("끝나서 닫은 것")}</dt><dd>{status.closed}</dd></div>
          <div><dt>{t("주제")}</dt><dd>{status.topics}</dd></div>
          <div><dt>{t("마지막으로 읽음")}</dt><dd>{status.last_read_at ? scribeAgo(status.last_read_at, now) : t("아직")}</dd></div>
          <div><dt>{t("클로드 코드 훅")}</dt><dd className={status.hooks.installed ? "is-ok" : "is-warn"}>{status.hooks.installed ? t("들어감") : t("없음")}</dd></div>
          <button type="button" className="scribe-refresh" onClick={load} aria-label={t("서기 상태 새로 읽기")}><RotateCw size={13} /></button>
        </dl>
      )}
      {warning && <p className="scribe-warn" role="status"><TriangleAlert size={14} aria-hidden /> {warning}</p>}

      {status && (
        <section className="scribe-projects" aria-labelledby="scribe-projects-title">
          <h3 id="scribe-projects-title">{t("읽을 프로젝트")}</h3>
          <p className="settings-note">{t("이 PC 에서 클로드 코드로 대화한 작업 폴더입니다. 최근에 대화한 것이 위에 있습니다. 서기는 고른 곳의 최근 이틀 대화만 읽습니다.")}</p>
          {projects.length === 0 ? (
            <p className="settings-note">{t("이 PC 에서 클로드 코드 대화 기록을 찾지 못했습니다. 클로드 코드로 한 번 대화하면 여기에 나타납니다.")}</p>
          ) : (
            <ul className="scribe-project-list">{main.map(project)}</ul>
          )}
          {temp.length > 0 && (
            <details className="scribe-temp">
              <summary>{t("임시 폴더에서 연 대화 {0}개", temp.length)}</summary>
              <ul className="scribe-project-list">{temp.map(project)}</ul>
            </details>
          )}
          {foldersRow && (
            <details className="settings-advanced">
              <summary>{t("폴더를 직접 적기 (고급)")}</summary>
              <ul className="settings-rows">{control(foldersRow)}</ul>
            </details>
          )}
          <p className="settings-note">{t("쌓인 카드는 손자리와 이어진 클로드에게 「서기 카드 보여 줘」라고 하면 꺼내 봅니다.")}</p>
        </section>
      )}
    </div>
  );
}
