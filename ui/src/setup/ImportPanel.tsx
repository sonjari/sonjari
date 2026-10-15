/**
 * 첫 실행 3단계 왼쪽(사람 쪽) — 무엇을 가져올지 고르고, 누른다 (전략안 §43, P4).
 *
 * 자동으로 넣지 않는다. 미리보기 → 「가져오기」를 사람이 눌러야 들어간다.
 * 지우기는 한 번 더 묻는다 — 원본 파일은 그대로지만 가져온 사본은 되돌릴 수 없다.
 */
import { t } from "../i18n";
import { useState } from "react";
import { pickNativeCodeWorkspace } from "../backend";
import type { ImportCandidate, ImportedItem, PasteTool } from "./setupApi";
import { candidateNote, importErrorText, secretSentence, shortPath, type ImportState } from "./useInstructionImport";

const PASTE_TOOLS: { key: PasteTool; label: string }[] = [
  { key: "claude_desktop", label: "Claude Desktop" },
  { key: "manus", label: "Manus" },
  { key: "windsurf", label: "Windsurf" },
  { key: "other", label: t("다른 도구") },
];

export function ImportPanel({ imp }: { imp: ImportState }) {
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState("");
  const [pasteOpen, setPasteOpen] = useState(false);

  const pickProject = async () => {
    const picked = await pickNativeCodeWorkspace(imp.project).catch(() => null);
    if (picked) {
      setTyping(false);
      await imp.chooseProject(picked);
      return;
    }
    // 앱 창 밖(브라우저 리허설)에는 폴더 고르기 창이 없다 — 경로를 직접 적는다.
    setTyping(true);
  };

  const globals = imp.candidates.filter((c) => c.scope === "global");
  const projects = imp.candidates.filter((c) => c.scope === "project");

  return (
    <section className="imp" aria-labelledby="imp-title">
      <header className="imp-head">
        <h2 id="imp-title">{t("다른 AI 에 적어 둔 지침 가져오기")}</h2>
        <p>{t("이 PC 안에서만 읽습니다. 넣기 전에 읽은 내용을 오른쪽에 보여 드리고, 키·비밀번호는 걷어 냅니다.")}</p>
      </header>

      <div className="imp-group">
        <h3>{t("이 PC 전체에 적용되는 지침")}</h3>
        {imp.scanned ? <CandidateList items={globals} imp={imp} /> : <p className="imp-hint">{t("찾는 중입니다…")}</p>}
      </div>

      <div className="imp-group">
        <div className="imp-group-head">
          <h3>{t("프로젝트 폴더의 지침")}</h3>
          <button type="button" className="imp-link" onClick={() => void pickProject()} disabled={imp.busy === "scan"}>
            {imp.project ? t("다른 폴더 고르기") : t("폴더 고르기")}
          </button>
        </div>
        {typing && (
          <form
            className="imp-path"
            onSubmit={(event) => {
              event.preventDefault();
              void imp.chooseProject(draft.trim());
            }}
          >
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="D:\work\my-site"
              aria-label={t("프로젝트 폴더 전체 경로")}
              spellCheck={false}
            />
            <button type="submit" className="setup-btn-quiet" disabled={!draft.trim()}>
              {t("이 폴더 보기")}
            </button>
          </form>
        )}
        {imp.projectError && (
          <p className="setup-warn" role="alert">
            {importErrorText(imp.projectError)}
          </p>
        )}
        {imp.project ? (
          <>
            <p className="imp-path-text">{shortPath(imp.project)}</p>
            <CandidateList items={projects} imp={imp} />
          </>
        ) : (
          <p className="imp-hint">
            {t("고른 폴더에서 CLAUDE.md · AGENTS.md · .cursorrules · .cursor/rules 만 봅니다. 하위 폴더로는 내려가지 않습니다.")}
          </p>
        )}
      </div>

      <div className="imp-group">
        <button type="button" className="imp-link" aria-expanded={pasteOpen} onClick={() => setPasteOpen(!pasteOpen)}>
          {pasteOpen ? t("붙여 넣기 닫기") : t("Claude Desktop·Manus·Windsurf 지침은 붙여 넣어 가져오기")}
        </button>
        {pasteOpen && (
          <div className="imp-paste">
            <div className="imp-tools" role="radiogroup" aria-label={t("어느 도구의 지침인가요")}>
              {PASTE_TOOLS.map((tool) => (
                <button
                  key={tool.key}
                  type="button"
                  role="radio"
                  aria-checked={imp.pasteTool === tool.key}
                  className={imp.pasteTool === tool.key ? "is-on" : ""}
                  onClick={() => imp.setPasteTool(tool.key)}
                >
                  {tool.label}
                </button>
              ))}
            </div>
            <textarea
              value={imp.pasteText}
              onChange={(event) => imp.setPasteText(event.target.value)}
              rows={5}
              placeholder={t("그 도구의 설정 화면에 적어 둔 지침을 복사해 붙여 넣으세요")}
              aria-label={t("붙여 넣을 지침")}
              spellCheck={false}
            />
          </div>
        )}
      </div>

      <label className="imp-check">
        <input
          type="checkbox"
          checked={imp.redactContacts}
          onChange={(event) => imp.setRedactContacts(event.target.checked)}
        />
        {t("이메일·전화번호도 걷어 내기")}
      </label>

      <Actions imp={imp} />
      {imp.error && (
        <p className="setup-error" role="alert">
          {imp.error}
        </p>
      )}
      <ImportedList imp={imp} />
    </section>
  );
}

function CandidateList({ items, imp }: { items: ImportCandidate[]; imp: ImportState }) {
  // 있는 것부터. 없는 자리도 남긴다 — 「어디를 봤는지」가 이 칸의 약속이다.
  const sorted = [...items].sort((a, b) => Number(b.exists) - Number(a.exists));
  return (
    <ul className="imp-list">
      {sorted.map((candidate) => {
        const usable = candidate.exists && candidate.readable && !candidate.too_large;
        const note = candidateNote(candidate);
        return (
          <li key={candidate.id} className={`imp-row${usable ? "" : " is-off"}`}>
            <label>
              <input
                type="checkbox"
                disabled={!usable}
                checked={imp.checked.has(candidate.id)}
                onChange={() => imp.toggle(candidate.id)}
              />
              <span className="imp-name">
                <b>{candidate.tool_name}</b>
                <span className="imp-path-text">{shortPath(candidate.path)}</span>
              </span>
            </label>
            <span className={`imp-note is-${note.tone}`}>{note.text}</span>
          </li>
        );
      })}
    </ul>
  );
}

function Actions({ imp }: { imp: ImportState }) {
  const chosen = imp.checked.size + (imp.pasteText.trim() ? 1 : 0);
  if (!imp.preview) {
    return (
      <div className="imp-actions">
        <button
          type="button"
          className="setup-btn-go"
          disabled={!chosen || imp.busy !== ""}
          onClick={() => void imp.runPreview()}
        >
          {imp.busy === "preview" ? t("읽고 걷어 내는 중…") : chosen ? t("고른 {0}개 미리보기", chosen) : t("가져올 지침을 고르세요")}
        </button>
        {imp.result && <CommitResult imp={imp} />}
      </div>
    );
  }
  const secrets = imp.ready.reduce((sum, item) => sum + (item.secret_total ?? 0), 0);
  const failed = imp.preview.filter((item) => item.error);
  return (
    <div className="imp-actions is-column">
      <p className={secrets ? "setup-warn" : "setup-done"}>
        {imp.ready.length}{t("개를 읽었습니다.")}{" "}
        {secrets ? t("비밀 {0}개를 걷어 낸 채로 넣습니다 — 오른쪽에서 확인해 주세요.", secrets) : t("걷어 낼 키·비밀번호는 없었습니다.")}
      </p>
      {failed.length > 0 && <p className="setup-note">{failed.length}{t("개는 읽지 못했습니다 — 오른쪽에 이유가 있습니다.")}</p>}
      <div className="imp-actions">
        <button
          type="button"
          className="setup-btn-go"
          disabled={!imp.ready.length || imp.busy !== ""}
          onClick={() => void imp.runCommit()}
        >
          {imp.busy === "commit" ? t("가져오는 중…") : t("가져오기 · {0}개", imp.ready.length)}
        </button>
        <button type="button" className="setup-btn-quiet" onClick={imp.clearPreview} disabled={imp.busy !== ""}>
          {t("다시 고르기")}
        </button>
      </div>
    </div>
  );
}

function CommitResult({ imp }: { imp: ImportState }) {
  const result = imp.result!;
  const secrets = result.saved.reduce((sum, item) => sum + item.secret_total, 0);
  return (
    <div className="imp-result" role="status">
      {result.saved.length > 0 && (
        <p className="setup-done">
          {result.saved.length}{t("개를 가져왔습니다")}{secrets ? t(" · 비밀 {0}개는 걷어 낸 채로", secrets) : ""}.
        </p>
      )}
      {result.refused.map((item) => (
        <p key={item.id} className="setup-warn">
          {item.id === "paste" ? t("붙여 넣은 지침") : item.id}: {importErrorText(item.error)}
        </p>
      ))}
    </div>
  );
}

function ImportedList({ imp }: { imp: ImportState }) {
  const [confirming, setConfirming] = useState<number | null>(null);
  if (!imp.imported.length) return null;
  return (
    <div className="imp-group">
      <h3>
        {t("가져온 지침")} <span className="num">{imp.imported.length}</span>
      </h3>
      <p className="imp-hint">{t("아직 대답에는 쓰지 않습니다. 넣어 두고, 보고, 지울 수 있습니다.")}</p>
      <ul className="imp-list">
        {imp.imported.map((item) => (
          <li key={item.import_id} className="imp-row">
            <span className="imp-name">
              <b>{item.tool_name}</b>
              <span className="imp-path-text">{item.scope === "paste" ? item.source_path : shortPath(item.source_path)}</span>
              <StatusLine item={item} />
            </span>
            {confirming === item.import_id ? (
              <span className="imp-confirm">
                {t("가져온 사본만 지웁니다. 원본 파일은 그대로입니다.")}
                <button type="button" className="imp-link is-stop" onClick={() => void imp.remove(item.import_id).then(() => setConfirming(null))}>
                  {t("지우기")}
                </button>
                <button type="button" className="imp-link is-quiet" onClick={() => setConfirming(null)}>
                  {t("그만두기")}
                </button>
              </span>
            ) : (
              <span className="imp-row-actions">
                <button
                  type="button"
                  className="imp-link"
                  aria-pressed={imp.view?.kind === "imported" && imp.view.importId === item.import_id}
                  onClick={() => imp.setView({ kind: "imported", importId: item.import_id })}
                >
                  {t("보기")}
                </button>
                <button type="button" className="imp-link is-stop" onClick={() => setConfirming(item.import_id)}>
                  {t("지우기")}
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatusLine({ item }: { item: ImportedItem }) {
  if (item.status === "changed") return <span className="imp-note is-signal">{t("원본이 바뀌었습니다 · 위에서 다시 고르면 새로 가져옵니다")}</span>;
  if (item.status === "missing") return <span className="imp-note is-signal">{t("원본 파일이 없어졌습니다 · 가져온 사본은 남아 있습니다")}</span>;
  if (item.status === "unreadable") return <span className="imp-note is-quiet">{t("원본을 확인하지 못했습니다")}</span>;
  return <span className="imp-note is-quiet">{secretSentence(item.secret_total, item.secrets)}</span>;
}
