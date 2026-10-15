/**
 * 첫 실행 3단계 오른쪽(기계 쪽) — 자비스가 **어디를 여는지**, 그리고 **걷은 결과** (전략안 §43, P4).
 *
 * 걷어 낸 자리는 빗금 칸으로 긋는다. 메모리 자에서 「쓸 수 없는 칸」을 칠하지 않고 긋던
 * 것과 같은 문법이다 — 새 색이 아니라 이미 있는 뜻을 쓴다.
 *
 * ★ 원문 비밀은 이 화면에 오지 않는다. 빗금 칸에는 백엔드가 준 **라벨만** 있다.
 */
import { t } from "../i18n";
import type { ImportedItem, ImportPreviewItem, ImportSegment } from "./setupApi";
import { importErrorText, secretSentence, shortPath, type ImportState } from "./useInstructionImport";

const MARKER = /\[비밀 걷어 냄: ([^\]]+)\]/g;

export function ImportPreview({ imp }: { imp: ImportState }) {
  const view = imp.view;
  if (view?.kind === "imported") {
    const item = imp.imported.find((row) => row.import_id === view.importId);
    if (item) return <ImportedView imp={imp} item={item} />;
  }
  if (view?.kind === "preview" && imp.preview) {
    const item = imp.preview.find((row) => row.id === view.id);
    if (item) return <PreviewView imp={imp} item={item} />;
  }
  return <Manifest imp={imp} />;
}

function Manifest({ imp }: { imp: ImportState }) {
  return (
    <div className="imp-manifest">
      <h2>{t("Sonjari가 여는 자리는 이것뿐입니다")}</h2>
      <p>
        {t("디스크를 훑지 않습니다. 아래 자리에 파일이 있는지만 확인했고, 내용은 아직 열지 않았습니다. 왼쪽에서 고르고 미리보기를 누르면 그때 읽습니다.")}
      </p>
      <ul>
        {imp.candidates.map((candidate) => (
          <li key={candidate.id} className={candidate.exists ? "is-there" : ""}>
            <span className="imp-m-tool">{candidate.tool_name}</span>
            <code>{shortPath(candidate.path)}</code>
            <span className="imp-m-state">
              {!candidate.exists ? t("없음") : candidate.readable ? t("있음") : t("있음 · 열지 않음")}
            </span>
          </li>
        ))}
        {!imp.project && (
          <li>
            <span className="imp-m-tool">{t("프로젝트")}</span>
            <span className="imp-m-hint">{t("폴더를 고르면 그 안의 네 자리")}</span>
            <span className="imp-m-state">{t("고르기 전")}</span>
          </li>
        )}
      </ul>
    </div>
  );
}

function FileTabs({ imp }: { imp: ImportState }) {
  if (!imp.preview || imp.preview.length < 2) return null;
  return (
    <div className="imp-files" role="tablist" aria-label={t("미리보기 파일")}>
      {imp.preview.map((item) => {
        const selected = imp.view?.kind === "preview" && imp.view.id === item.id;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => imp.setView({ kind: "preview", id: item.id })}
          >
            {item.tool_name ?? item.id}
            <small>{item.id === "paste" ? t("붙여넣기") : fileName(item.path)}</small>
            {item.error ? (
              <em className="is-quiet">{t("못 읽음")}</em>
            ) : item.secret_total ? (
              <em className="is-signal" aria-label={t("비밀 {0}개 걷음", item.secret_total)}>
                {item.secret_total}
              </em>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function PreviewView({ imp, item }: { imp: ImportState; item: ImportPreviewItem }) {
  return (
    <div className="imp-view">
      <FileTabs imp={imp} />
      <header className="imp-doc-head">
        <b>{item.tool_name ?? item.id} {t("· 미리보기")}</b>
        <code>{item.id === "paste" ? t("붙여 넣은 글") : shortPath(item.path ?? "")}</code>
      </header>
      {item.error ? (
        <p className="imp-doc-error" role="alert">
          {importErrorText(item.error)}
        </p>
      ) : (
        <>
          <p className={`imp-sum ${item.secret_total ? "is-signal" : "is-ok"}`}>
            {secretSentence(item.secret_total ?? 0, item.secrets ?? {})}
          </p>
          {(item.contact_total ?? 0) > 0 && !imp.redactContacts && (
            <p className="imp-sum is-quiet">
              {Object.entries(item.contacts ?? {})
                .map(([label, n]) => t("{0} {1}개", label, n))
                .join(" · ")}
              {t("는 밑줄로 표시만 했고 그대로 들어갑니다. 빼려면 왼쪽 「이메일·전화번호도 걷어 내기」를 켜세요.")}
            </p>
          )}
          <Doc segments={item.segments ?? []} />
        </>
      )}
    </div>
  );
}

function ImportedView({ imp, item }: { imp: ImportState; item: ImportedItem }) {
  return (
    <div className="imp-view">
      <button type="button" className="imp-link imp-back" onClick={() => imp.setView(null)}>
        {t("← Sonjari가 여는 자리 보기")}
      </button>
      <header className="imp-doc-head">
        <b>{item.tool_name} {t("· 가져온 사본")}</b>
        <code>{item.scope === "paste" ? item.source_path : shortPath(item.source_path)}</code>
      </header>
      {item.status === "changed" && (
        <p className="imp-sum is-signal">{t("원본이 가져온 뒤에 바뀌었습니다. 자동으로 따라가지 않습니다 — 왼쪽에서 다시 고르면 새로 가져옵니다.")}</p>
      )}
      <p className={`imp-sum ${item.secret_total ? "is-signal" : "is-ok"}`}>{secretSentence(item.secret_total, item.secrets)}</p>
      <Doc segments={segmentsFromStored(item.text)} />
    </div>
  );
}

function Doc({ segments }: { segments: ImportSegment[] }) {
  return (
    <pre className="imp-doc" tabIndex={0} aria-label={t("걷어 낸 결과")}>
      {segments.map((segment, index) =>
        segment.t === "secret" ? (
          <mark key={index} className="imp-scrub" title={t("원문은 이 화면에 오지 않았습니다")}>
            {t("걷어 냄 ·")} {segment.label}
          </mark>
        ) : segment.t === "contact" ? (
          <span key={index} className="imp-contact" title={t("{0} — 그대로 들어갑니다", segment.label)}>
            {segment.v}
          </span>
        ) : (
          segment.v
        ),
      )}
    </pre>
  );
}

/** 저장된 글의 표시 글자를 다시 빗금 칸으로 — 판단이 아니라 백엔드가 남긴 표시를 읽을 뿐이다. */
function segmentsFromStored(text: string): ImportSegment[] {
  const out: ImportSegment[] = [];
  let cursor = 0;
  for (const match of text.matchAll(MARKER)) {
    const at = match.index ?? 0;
    if (at > cursor) out.push({ t: "text", v: text.slice(cursor, at) });
    out.push({ t: "secret", v: match[0], label: match[1] });
    cursor = at + match[0].length;
  }
  if (cursor < text.length) out.push({ t: "text", v: text.slice(cursor) });
  return out;
}

function fileName(path: string | undefined): string {
  return (path ?? "").split(/[\\/]/).pop() ?? "";
}
