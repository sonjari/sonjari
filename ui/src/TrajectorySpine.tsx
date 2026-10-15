/**
 * 작업 궤적 노드 — 대화와 같은 축에 붙는다.
 *
 * 접혀 있을 때는 한 줄(`7걸음 · 42초 · 읽기만 함`), 펴면 걸음마다 무슨 도구로
 * 무엇을 했는지. 끝나도 사라지지 않는다 — 답 바로 위에 근거가 남아 있어야
 * "했다고 말했는데 안 했다"를 화면에서 잡을 수 있다.
 */
import { t } from "./i18n";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Circle, FileText, Image, Loader2,
  Route, Undo2, X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { parseSheetPreview } from "./workspace/sheetPreview";
import type { JobOutput, UndoOffer } from "./types";
import type { PlanItem, Trajectory } from "./trajectory";
import { evidenceLine, planProgress, summarize, toolLabel } from "./trajectory";

const ease = [0.22, 1, 0.36, 1] as const;

function StepIcon({ status }: { status: string }) {
  if (status === "running") return <Loader2 size={12} className="spin" />;
  if (status === "failed" || status === "cancelled") return <X size={12} />;
  if (status === "partial") return <AlertTriangle size={12} />;
  return <Check size={12} />;
}

/**
 * 시킨 것 대조 — 궤적 맨 위 (R3).
 *
 * 진행이 몇 분씩 걸릴 때 "무엇이 남았나"가 보이는 것과 안 보이는 것의 차이는 크다.
 * 백엔드는 이 대조를 처음부터 하고 있었지만 **모델에게만** 말했다.
 *
 * 도는 동안에는 펼치지 않아도 보인다. 끝난 뒤에는 접어 둔다 — 지난 대화를 훑을 때
 * 다 채운 체크리스트가 줄마다 펼쳐져 있으면 정작 답이 안 보인다.
 */
function PlanChecklist({ items }: { items: PlanItem[] }) {
  return (
    <ul className="trajectory-plan">
      {items.map((item) => (
        <li key={item.label} className={item.met ? "met" : ""}>
          <span className="plan-mark">{item.met ? <Check size={12} /> : <Circle size={12} />}</span>
          <span className="plan-label">{item.label}</span>
          {/* 지금까지 어땠는지를 같이 적는다. "안 됨"만 적으면 얼마나 왔는지 모른다. */}
          <span className="plan-saw">{item.saw}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * 브라우저가 **못 그리는** 형식. 이걸 받아서 창에 띄우면 다운로드가 될 뿐이다 —
 * 사용자가 본 「미리보기도 안되고 아무것도 안되는데」가 정확히 이것이었다.
 * 이 형식들은 바이트 대신 **글**을 받아 화면 안에서 편다.
 */
const READ_AS_TEXT = /\.(docx|xlsx|pptx|hwpx|csv|txt|md|json)$/i;

/** 만든 파일 한 줄. **없는 파일도 지우지 않는다** — 그 사실이 정보다. */
function OutputRow({
  output,
  onOpen,
  onPreview,
}: {
  output: JobOutput;
  onOpen: () => void;
  onPreview?: () => Promise<{ text: string; readable: boolean } | null>;
}) {
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const size = output.bytes >= 1024 * 1024
    ? `${(output.bytes / 1024 / 1024).toFixed(1)}MB`
    : `${Math.max(1, Math.round(output.bytes / 1024))}KB`;
  const canPreview = Boolean(onPreview) && output.exists && output.viewable && READ_AS_TEXT.test(output.name);

  const toggle = async () => {
    if (preview !== null) { setPreview(null); return; }
    setBusy(true);
    const got = await onPreview?.().catch(() => null);
    setBusy(false);
    // 못 읽었을 때 조용히 아무 일도 안 일어나면 "고장"으로 보인다. 말해 준다.
    if (!got) setPreview(t("미리보기를 가져오지 못했습니다."));
    else setPreview(got.readable ? got.text : t("이 파일은 글로 읽을 수 없습니다. 「열기」로 확인해 주세요."));
  };

  return (
    <li className={output.exists ? "" : "missing"}>
      <span className="output-mark">{output.kind === "image" ? <Image size={12} /> : <FileText size={12} />}</span>
      {output.viewable ? (
        <button type="button" className="output-name" onClick={onOpen} title={output.path}>{output.name}</button>
      ) : (
        <span className="output-name" title={output.path}>{output.name}</span>
      )}
      <span className="output-meta">{output.exists ? size : t("파일이 없습니다")}</span>
      {canPreview && (
        <button type="button" className="output-peek" onClick={() => void toggle()} disabled={busy}>
          {busy ? t("읽는 중") : preview !== null ? t("접기") : t("미리보기")}
        </button>
      )}
      {preview !== null && <OutputPreview text={preview} />}
    </li>
  );
}

/** 만든 문서의 속. 엑셀은 표로 그린다 — 글자 덩어리로는 어느 값이 어느 칸인지 읽을 수 없다(2026-10-13). */
function OutputPreview({ text }: { text: string }) {
  const parsed = parseSheetPreview(text);
  if (!parsed) return <pre className="output-preview">{text}</pre>;
  return (
    <div className="output-preview output-sheets">
      {parsed.sheets.map((sheet) => (
        <figure key={sheet.title} className="output-sheet">
          {parsed.sheets.length > 1 || sheet.title ? <figcaption>{sheet.title}</figcaption> : null}
          <table>
            <thead>
              <tr>{sheet.rows[0].map((cell, index) => <th key={index} scope="col">{cell}</th>)}</tr>
            </thead>
            <tbody>
              {sheet.rows.slice(1).map((row, rowIndex) => (
                <tr key={rowIndex}>{row.map((cell, index) => <td key={index}>{cell}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </figure>
      ))}
      {parsed.note ? <p className="output-sheet-note">{parsed.note}</p> : null}
    </div>
  );
}

export function TrajectoryNode({
  trajectory,
  defaultOpen = false,
  outputs,
  undo = [],
  onLoadOutputs,
  onOpenOutput,
  onPreviewOutput,
  onUndo,
}: {
  trajectory: Trajectory;
  defaultOpen?: boolean;
  /** `undefined` = 아직 안 물어봤다. 빈 배열 = 물어봤는데 만든 것이 없다. */
  outputs?: JobOutput[];
  undo?: UndoOffer[];
  onLoadOutputs?: (jobId: string) => void;
  onOpenOutput?: (jobId: string, output: JobOutput) => void;
  /** 문서의 **속**을 글로 가져온다. 브라우저가 못 그리는 형식을 화면 안에서 확인한다. */
  onPreviewOutput?: (jobId: string, output: JobOutput) => Promise<{ text: string; readable: boolean } | null>;
  onUndo?: (undoId: string) => void;
}) {
  const running = trajectory.status === "running";
  const [open, setOpen] = useState(defaultOpen || running);
  const [allUndo, setAllUndo] = useState(false);
  const summary = summarize(trajectory);
  const plan = planProgress(trajectory);
  const planVisible = Boolean(trajectory.plan?.length) && (running || open);

  // 펼쳤을 때만 물어본다. 대화를 열 때마다 모든 궤적의 산출물을 미리 긁어 오면
  // 그건 목록 API 가 455KB 였던 것과 같은 실수다(미리보기만, 본문은 고를 때).
  useEffect(() => {
    if (open && !running && outputs === undefined) onLoadOutputs?.(trajectory.jobId);
  }, [open, running, outputs, onLoadOutputs, trajectory.jobId]);

  return (
    <div className={`spine-node trajectory ${running ? "running" : ""} ${summary.failed ? "has-failure" : ""}`}>
      <span className="spine-dot"><Route size={13} /></span>
      <div className="spine-body">
        <button className="trajectory-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <strong>{running ? t("일하는 중") : t("작업 궤적")}</strong>
          {/* 다 못 채웠으면 접혀 있어도 그 사실이 보여야 한다. */}
          {plan && (
            <span className={`trajectory-plan-count ${plan.met === plan.total ? "met" : ""}`}>
              {t("시킨 것")} {plan.met}/{plan.total}
            </span>
          )}
          <span>{summary.label}</span>
          {/* ★ 서명을 밖으로 (2026-08-23).
              걸음 눈금자는 이 제품의 심장인데 **오른쪽 칸 안에만** 있었다.
              그 칸은 일이 도는 동안에만 열리므로, 끝난 답을 나중에 볼 때는
              "이 답이 몇 걸음을 밟았고 어디서 실패했는지"가 어디에도 없었다.

              여기 붙는 것은 **누를 수 없는 축소판**이다. 펼치지 않아도 모양이
              보이고, 자세히 보려면 펼친다 - 계기판의 작은 눈금과 같은 일이다.
              실패한 걸음은 짧고 붉다(눈금자와 같은 규칙). */}
          {trajectory.steps.length > 0 && (
            <span className="trajectory-mini" aria-hidden>
              {trajectory.steps.slice(-14).map((step) => (
                <i key={step.key} className={step.status} />
              ))}
            </span>
          )}
        </button>
        {planVisible && <PlanChecklist items={trajectory.plan ?? []} />}
        <AnimatePresence initial={false}>
          {open && (
            <motion.ol
              className="trajectory-steps"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.26, ease }}
            >
              {trajectory.steps.map((step, index) => (
                <motion.li
                  key={step.key}
                  className={step.status}
                  initial={{ y: -6, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  transition={{ duration: 0.18, ease, delay: Math.min(index, 5) * 0.04 }}
                >
                  <span className="step-mark"><StepIcon status={step.status} /></span>
                  <span className="step-tool">{toolLabel(step.tool)}</span>
                  <span className="step-message">{step.message}</span>
                  {/* 근거 — 어디서 무엇을 봤는가. 이게 없으면 걸음은 도구 이름일 뿐이고,
                      "했다고 말했는데 안 했다"를 화면에서 잡을 수가 없다. */}
                  {evidenceLine(step) && <span className="step-evidence">{evidenceLine(step)}</span>}
                </motion.li>
              ))}
              {trajectory.steps.length === 0 && <li className="step-empty">{t("아직 도구를 쓰지 않았습니다.")}</li>}
            </motion.ol>
          )}
        </AnimatePresence>

        {/* 만든 것 (R4). 물어보기 전에는 아무 말도 안 한다 — 빈 서랍과 "아직 모름"은 다르다. */}
        {open && outputs !== undefined && outputs.length > 0 && (
          <div className="trajectory-outputs">
            <p>{t("만든 것")} {outputs.length}{t("개")}</p>
            <ul>
              {outputs.map((output) => (
                <OutputRow
                  key={output.path}
                  output={output}
                  onOpen={() => onOpenOutput?.(trajectory.jobId, output)}
                  onPreview={onPreviewOutput ? () => onPreviewOutput(trajectory.jobId, output) : undefined}
                />
              ))}
            </ul>
          </div>
        )}

        {/* 되돌리기 (R4). 도구는 처음부터 있었고 **화면에 버튼이 없었을 뿐이다.**
            Sonjari가 못 되돌리는 것도 남긴다 — 그때는 사람이 할 일을 적어 준다. */}
        {/* ★ 고친 횟수만큼 카드가 쌓여 화면을 덮었다 (2026-10-04 대표 화면 — 같은 파일 되돌리기 카드 11장).
            가장 최근 둘만 펴 두고 나머지는 접는다. 지우지 않는다 — 한 번 누르면 전부 보인다. */}
        {open && undo.length > 0 && (
          <div className="trajectory-undo">
            {undo.length > UNDO_SHOWN && (
              <button type="button" className="undo-more" onClick={() => setAllUndo((value) => !value)}>
                {allUndo ? t("이전 되돌리기 접기") : t("이전 되돌리기 {0}개 더 보기", undo.length - UNDO_SHOWN)}
              </button>
            )}
            {(allUndo ? undo : undo.slice(-UNDO_SHOWN)).map((offer) => (
              <div className="undo-row" key={offer.undo_id}>
                <span>{offer.label || toolLabel(offer.tool)}</span>
                {offer.automatic ? (
                  <button type="button" onClick={() => onUndo?.(offer.undo_id)}>
                    <Undo2 size={12} /> {t("되돌리기")}
                  </button>
                ) : (
                  <small>{offer.manual_hint || t("Sonjari가 되돌릴 수 없습니다 — 직접 해주셔야 합니다")}</small>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** 되돌리기 카드를 접지 않고 보여 주는 수 — 가장 최근 것부터. */
const UNDO_SHOWN = 2;

export default TrajectoryNode;
