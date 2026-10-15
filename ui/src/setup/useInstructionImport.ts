/**
 * 첫 실행 3단계 — 지침 가져오기 상태 (전략안 §43, P4).
 *
 *     찾기(있는지만) → 고르기 → 미리보기(읽고 걷음) → 가져오기(사람이 누름) → 목록·지우기
 *
 * ## 규율
 *
 * - 화면은 **걷어 내지 않는다.** 무엇이 비밀인지는 백엔드(`secret_scrub.py`) 한 곳이 정한다.
 *   화면이 따로 판단하면 두 벌이 되고, 두 벌은 반드시 갈린다.
 * - 고른 것·붙여 넣은 글·연락처 설정이 바뀌면 **미리보기를 버린다.** 사람이 본 것과
 *   넣는 것이 달라지면 안 된다(백엔드도 해시로 한 번 더 막는다).
 */
import { t } from "../i18n";
import { useCallback, useEffect, useState } from "react";
import type {
  ImportCandidate,
  ImportCommitResult,
  ImportedItem,
  ImportPreviewItem,
  ImportScan,
  PasteTool,
  SetupApi,
} from "./setupApi";

export type ImportView = { kind: "preview"; id: string } | { kind: "imported"; importId: number } | null;

/** 오류는 무엇이 잘못됐고 어떻게 하면 되는지까지. */
export function importErrorText(code: string | undefined): string {
  switch (code) {
    case "not_in_list":
      return t("Sonjari가 보는 자리 목록에 없는 파일이라 열지 않았습니다.");
    case "settings_file":
      return t("설정 파일은 키가 섞여 있을 수 있어 열지 않습니다. 지침만 따로 파일로 두면 가져올 수 있습니다.");
    case "sensitive_location":
      return t("보호된 폴더(.ssh·credentials 같은 곳) 안이거나 그쪽을 가리키는 파일이라 열지 않습니다.");
    case "missing":
      return t("파일이 없어졌습니다. 폴더를 다시 골라 목록을 새로 고쳐 주세요.");
    case "too_large":
      return t("256KB 가 넘어 가져오지 않습니다(자르면 뜻이 바뀝니다). 필요한 부분만 붙여 넣기로 가져오세요.");
    case "not_text":
      return t("글자로 읽을 수 없는 파일입니다. UTF-8 로 저장한 뒤 다시 골라 주세요.");
    case "unreadable":
      return t("파일을 열지 못했습니다. 다른 프로그램이 붙잡고 있는지 확인한 뒤 다시 눌러 주세요.");
    case "changed_since_preview":
      return t("미리보기를 한 뒤에 파일이 바뀌었습니다. 다시 미리보기를 눌러 바뀐 내용을 확인해 주세요.");
    case "empty":
      return t("붙여 넣은 글이 비어 있습니다.");
    case "unknown_tool":
      return t("어느 도구의 지침인지 골라 주세요.");
    case "project_not_found":
      return t("그 폴더를 찾지 못했습니다. 드라이브부터 시작하는 전체 경로(예: D:\\work\\site)를 넣어 주세요.");
    default:
      return code ? t("가져오지 못했습니다: {0}", code) : "";
  }
}

export type NoteTone = "quiet" | "ok" | "signal";

export function candidateNote(c: ImportCandidate): { tone: NoteTone; text: string } {
  if (!c.exists) return { tone: "quiet", text: t("없음") };
  if (c.skip_reason === "settings_file") return { tone: "quiet", text: t("설정 파일이라 열지 않습니다") };
  if (c.skip_reason === "sensitive_location") return { tone: "signal", text: t("보호된 폴더라 열지 않습니다") };
  if (c.too_large) return { tone: "signal", text: t("256KB 넘음 · 붙여 넣기로") };
  if (c.imported?.status === "changed") return { tone: "signal", text: t("가져온 뒤 바뀜 · 고르면 새로 가져옵니다") };
  if (c.imported) return { tone: "ok", text: t("가져옴") };
  return { tone: "quiet", text: sizeLabel(c.size) };
}

export function sizeLabel(bytes: number): string {
  return bytes < 1024 ? t("1KB 미만") : `${Math.round(bytes / 1024)}KB`;
}

/** `C:\Users\누구\.claude\CLAUDE.md` → `~\.claude\CLAUDE.md` */
export function shortPath(path: string): string {
  return path.replace(/^[A-Za-z]:\\Users\\[^\\]+/, "~");
}

export function secretSentence(total: number, secrets: Record<string, number>): string {
  if (!total) return t("걷어 낼 키·비밀번호가 없었습니다.");
  const parts = Object.entries(secrets).map(([label, n]) => `${label} ${n}`);
  return t("비밀 {0}개를 걷어 냈습니다 — {1}", total, parts.join(" · "));
}

export function useInstructionImport(api: SetupApi | null) {
  const [project, setProject] = useState("");
  const [scan, setScan] = useState<ImportScan | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [pasteTool, setPasteToolRaw] = useState<PasteTool>("manus");
  const [pasteText, setPasteTextRaw] = useState("");
  const [redactContacts, setRedactContactsRaw] = useState(false);
  const [preview, setPreview] = useState<ImportPreviewItem[] | null>(null);
  const [busy, setBusy] = useState<"" | "scan" | "preview" | "commit" | "remove">("");
  const [result, setResult] = useState<ImportCommitResult | null>(null);
  const [imported, setImported] = useState<ImportedItem[]>([]);
  const [view, setView] = useState<ImportView>(null);
  const [error, setError] = useState("");

  const fail = (err: unknown) => setError(err instanceof Error ? err.message : String(err));

  const refresh = useCallback(
    async (projectPath: string) => {
      if (!api) return null;
      const [next, list] = await Promise.all([api.importScan(projectPath), api.importList()]);
      setScan(next);
      setImported(list.items);
      return next;
    },
    [api],
  );

  useEffect(() => {
    if (!api) return;
    setBusy("scan");
    refresh(project)
      .catch(fail)
      .finally(() => setBusy(""));
  }, [api]); // eslint-disable-line react-hooks/exhaustive-deps

  // 고른 것이 바뀌면 본 것도 버린다.
  const invalidate = useCallback(() => {
    setPreview(null);
    setResult(null);
    setView((current) => (current?.kind === "preview" ? null : current));
  }, []);

  const toggle = (id: string) => {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    invalidate();
  };

  const chooseProject = async (path: string) => {
    if (!api || !path) return;
    setError("");
    setBusy("scan");
    invalidate();
    try {
      const next = await refresh(path);
      if (next?.project_error) return;
      setProject(next?.project || path);
      // 앞 폴더에서 고른 프로젝트 파일은 새 폴더와 상관없다.
      setChecked((current) => new Set([...current].filter((id) => next?.candidates.some((c) => c.id === id && c.scope === "global"))));
    } catch (err) {
      fail(err);
    } finally {
      setBusy("");
    }
  };

  const runPreview = async () => {
    if (!api) return;
    setError("");
    setBusy("preview");
    try {
      const paste = pasteText.trim() ? { tool: pasteTool, text: pasteText } : null;
      const res = await api.importPreview(project, [...checked], paste, redactContacts);
      setPreview(res.items);
      const first = res.items.find((item) => !item.error) ?? res.items[0];
      setView(first ? { kind: "preview", id: first.id } : null);
    } catch (err) {
      fail(err);
    } finally {
      setBusy("");
    }
  };

  const ready = (preview ?? []).filter((item) => !item.error && item.sha256);

  const runCommit = async () => {
    if (!api || !ready.length) return;
    setError("");
    setBusy("commit");
    try {
      const files = ready.filter((item) => item.id !== "paste").map((item) => ({ id: item.id, sha256: item.sha256! }));
      const pasteItem = ready.find((item) => item.id === "paste");
      const res = await api.importCommit(
        project,
        files,
        pasteItem ? { tool: pasteTool, text: pasteText, sha256: pasteItem.sha256 } : null,
        redactContacts,
      );
      setResult(res);
      setPreview(null);
      // 못 넣은 것만 골라 둔 채로 남긴다 — 다시 미리보기만 누르면 된다.
      setChecked(new Set(res.refused.map((item) => item.id).filter((id) => id !== "paste")));
      if (res.saved.some((item) => item.id === "paste")) setPasteTextRaw("");
      await refresh(project);
      setView(res.saved[0] ? { kind: "imported", importId: res.saved[0].import_id } : null);
    } catch (err) {
      fail(err);
    } finally {
      setBusy("");
    }
  };

  const remove = async (importId: number) => {
    if (!api) return;
    setError("");
    setBusy("remove");
    try {
      const res = await api.importRemove(importId);
      if (!res.ok) setError(res.error === "not_found" ? t("이미 지워진 지침입니다. 목록을 새로 고쳤습니다.") : String(res.error));
      setView((current) => (current?.kind === "imported" && current.importId === importId ? null : current));
      await refresh(project);
    } catch (err) {
      fail(err);
    } finally {
      setBusy("");
    }
  };

  return {
    project,
    projectError: scan?.project_error ?? "",
    candidates: scan?.candidates ?? [],
    scanned: scan !== null,
    checked,
    toggle,
    chooseProject,
    pasteTool,
    setPasteTool: (tool: PasteTool) => {
      setPasteToolRaw(tool);
      invalidate();
    },
    pasteText,
    setPasteText: (text: string) => {
      setPasteTextRaw(text);
      invalidate();
    },
    redactContacts,
    setRedactContacts: (on: boolean) => {
      setRedactContactsRaw(on);
      invalidate();
    },
    preview,
    ready,
    clearPreview: invalidate,
    runPreview,
    runCommit,
    result,
    imported,
    remove,
    view,
    setView,
    busy,
    error,
  };
}

export type ImportState = ReturnType<typeof useInstructionImport>;
