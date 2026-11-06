/**
 * 설정 › MCP 서버 꽂기 (2026-11-04 · 설계 docs/설계_MCP서버꽂기_2026-11-04.ko.md).
 *
 * - 서버를 꽂고 빼는 곳은 여기뿐이다. 손자리 모델은 꽂지 못한다(stdio 서버는 명령 실행이다).
 * - 클로드 데스크톱 `mcpServers` 모양을 그대로 붙여 넣는다 — 사용자가 이미 아는 모양.
 * - 비밀 값(토큰 · 열쇠)은 백엔드가 보관함으로 옮긴다. 화면에는 돌아오지 않는다.
 * - 화면은 판정하지 않는다 — 도구의 위험 등급(L0 읽기 · L2 승인 · L3 지우기)은 백엔드가 서버 표시로 정한 것을 그린다.
 */
import { t } from "../i18n";
import { CheckCircle2, Download, Loader2, Plug, Plus, Power, Trash2, Wrench } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { JarvisClient } from "../backend";
import type { McpServerRow } from "../types";

type ToolRow = { name: string; description: string; risk: string };

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

const RISK_WORD: Record<string, string> = { L0: "읽기", L1: "읽기", L2: "승인 뒤", L3: "지우기 · 승인 뒤", L4: "승인 뒤" };

export function McpSection({ client }: { client: JarvisClient }) {
  const [servers, setServers] = useState<McpServerRow[] | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [tools, setTools] = useState<Record<string, ToolRow[]>>({});

  const load = useCallback(async () => {
    try {
      setServers((await client.listMcpServers()).servers);
    } catch (reason) {
      setError(message(reason));
    }
  }, [client]);

  useEffect(() => { void load(); }, [load]);

  const run = async (key: string, work: () => Promise<void>) => {
    setBusy(key);
    setError("");
    setNote("");
    try {
      await work();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy("");
    }
  };

  const add = () => run("add", async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(draft);
    } catch {
      throw new Error(t("JSON 모양이 아닙니다 — 클로드 데스크톱 설정의 \"mcpServers\" 칸을 그대로 붙여 넣어 주세요"));
    }
    const body = parsed && typeof parsed === "object" && "mcpServers" in (parsed as object) ? parsed : { mcpServers: parsed };
    const result = await client.addMcpServers(body);
    setServers(result.servers);
    setDraft("");
    setNote(skippedNote(result.added, result.skipped));
  });

  const importClaude = () => run("import", async () => {
    const result = await client.importMcpFromClaude();
    setServers(result.servers);
    setNote(result.added.length || result.skipped.length
      ? skippedNote(result.added, result.skipped)
      : t("클로드 설정(클로드 코드 · 데스크톱)에서 가져올 서버를 찾지 못했습니다"));
  });

  const test = (name: string) => run(`test:${name}`, async () => {
    const result = await client.testMcpServer(name);
    setTools((prev) => ({ ...prev, [name]: result.tools }));
    await load();
  });

  const toggle = (row: McpServerRow) => run(`toggle:${row.name}`, async () => {
    setServers((await client.setMcpServerEnabled(row.name, !row.enabled)).servers);
  });

  const remove = (name: string) => run(`remove:${name}`, async () => {
    setServers((await client.removeMcpServer(name)).servers);
  });

  return (
    <div className="settings-block mcp" data-testid="mcp-section">
      <p className="settings-note">
        {t("다른 프로그램의 MCP 서버(노션 · 깃허브 · 파일 · 사내 도구 등)를 꽂으면 Sonjari 가 일하다가 그 도구를 찾아 씁니다. 읽기 전용이라고 표시된 도구만 바로 쓰고, 나머지는 승인 카드를 거칩니다. 토큰 같은 비밀 값은 이 PC 의 비밀 보관함에만 저장됩니다.")}
      </p>
      <div className="pack-mine-actions">
        <button type="button" className="setup-btn-go" onClick={() => void importClaude()} disabled={busy === "import"}>
          {busy === "import" ? <Loader2 size={14} className="spin" /> : <Download size={14} aria-hidden="true" />} {t("클로드에서 가져오기")}
        </button>
      </div>
      <label className="mcp-draft">
        <span>{t("직접 붙여 넣기 — 클로드 데스크톱 설정의 \"mcpServers\" 모양")}</span>
        <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={5} spellCheck={false}
          placeholder={'{"mcpServers": {"files": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/work"]}}}'} />
      </label>
      <button type="button" className="setup-btn-quiet" onClick={() => void add()} disabled={!draft.trim() || busy === "add"}>
        {busy === "add" ? <Loader2 size={14} className="spin" /> : <Plus size={14} aria-hidden="true" />} {t("꽂기")}
      </button>
      {error && <p className="settings-error" role="alert">{error}</p>}
      {note && <p className="settings-note" role="status">{note}</p>}

      {servers && servers.length === 0 && <p className="settings-note">{t("아직 꽂힌 서버가 없습니다.")}</p>}
      <ul className="mcp-list">
        {(servers ?? []).map((row) => (
          <li key={row.name} className={`mcp-row${row.enabled ? " is-on" : ""}`} data-testid={`mcp-${row.name}`}>
            <div className="mcp-row-head">
              <Plug size={15} aria-hidden="true" />
              <b>{row.name}</b>
              <code>{row.transport === "http" ? row.url : row.command}</code>
              <span className="mcp-count">{row.listed_at ? t("도구 {0}개", row.tools) : t("목록 안 받음 — [시험]")}</span>
            </div>
            <div className="mcp-row-actions">
              <button type="button" className="setup-btn-quiet" onClick={() => void test(row.name)} disabled={busy === `test:${row.name}`}>
                {busy === `test:${row.name}` ? <Loader2 size={14} className="spin" /> : <Wrench size={14} aria-hidden="true" />} {t("시험")}
              </button>
              <button type="button" className="setup-btn-quiet" onClick={() => void toggle(row)} disabled={busy === `toggle:${row.name}`}>
                <Power size={14} aria-hidden="true" /> {row.enabled ? t("끄기") : t("켜기")}
              </button>
              <button type="button" className="setup-btn-quiet" onClick={() => void remove(row.name)} disabled={busy === `remove:${row.name}`}>
                <Trash2 size={14} aria-hidden="true" /> {t("빼기")}
              </button>
            </div>
            {tools[row.name] && (
              <ul className="mcp-tools">
                {tools[row.name].map((tool) => (
                  <li key={tool.name}>
                    <CheckCircle2 size={12} aria-hidden="true" /> <code>{tool.name}</code>
                    <span className={`mcp-risk risk-${tool.risk}`}>{t(RISK_WORD[tool.risk] ?? "승인 뒤")}</span>
                    <span className="mcp-desc">{tool.description}</span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function skippedNote(added: string[], skipped: { name: string; why: string }[]): string {
  const parts: string[] = [];
  if (added.length) parts.push(t("꽂음: {0}", added.join(", ")));
  if (skipped.length) parts.push(t("건너뜀: {0}", skipped.map((s) => `${s.name}(${s.why})`).join(" · ")));
  return parts.join(" — ");
}
