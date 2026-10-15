/**
 * 머리에 적힌 모델 이름 — **누르면 바꾸는 버튼** (2026-09-21 제품 요청).
 *
 * 예전 이 자리는 글씨였다. 모델을 바꾸려면 설정 › 모델까지 들어가야 했고, 거기 목록에는
 * 우리 카탈로그만 있었다. 사용자가 `ollama pull` 로 직접 받아 둔 모델은 아예 안 보여서
 * 「온텔릭에서는 못 쓰는구나」로 읽혔다 — 쓸 수 있다.
 *
 *   ✓ Qwen 3.6 35B-A3B    Alibaba    사슬 벤치 10/10 실측     23.0GB
 *     Qwen 3.5 9B         Alibaba    사슬 벤치 9/10 실측       6.1GB
 *     ─ 이 PC 에 직접 받아 두신 것 ─
 *     mistral-small3.2:24b           능력을 잰 적 없음         14.0GB
 *     translategemma:4b              도구를 부를 수 없어 …     (못 누름)
 *
 * ## 세 가지를 지킨다
 *
 * 1. **「검증됨」과 「능력을 쟀다」를 섞지 않는다.** 목록에 있다는 건 이 PC 메모리에
 *    들어간다는 뜻이지 일을 잘한다는 뜻이 아니다. 능력은 `grade` 가 따로 말한다.
 * 2. **못 고르는 것도 이유를 적어 보인다.** 그냥 빼면 사용자는 왜 안 보이는지 모른 채
 *    같은 벽에 계속 부딪친다.
 * 3. **역할마다 따로.** Code 탭에서 고른 것은 Code 탭 모델만 바꾼다.
 *
 * ## 왜 미리 읽어 두나
 *
 * 처음 부를 때 0.8초가 든다(PC 진단 + Ollama 묻기). 눌러 놓고 0.8초를 기다리면 「안
 * 눌렸나?」가 된다 — 화면이 뜰 때 한 번 미리 읽어 두고, 열면 바로 그린다.
 */
import { t } from "../i18n";
import { AlertTriangle, Check, ChevronDown, Loader2 } from "lucide-react";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import type { CodeUpgrade, ModelPickerView, ModelRole, PickerModel, SetupApi } from "../setup/setupApi";
import { ContextCeilingPanel } from "./ContextCeilingPanel";

function sizeLabel(gb: number): string {
  return gb > 0 ? `${gb.toFixed(1)}GB` : "";
}

/** 목록 안 → 목록 밖 → 못 고르는 것. 지금 쓰는 것은 맨 위. */
function order(row: PickerModel): number {
  if (row.current) return 0;
  if (row.blocked) return 4;
  if (row.listed && row.installed) return 1;
  if (row.listed) return 2;
  return 3;
}

export function LocalModelPicker({ api, role, label, context, onChanged }: {
  api: SetupApi | null;
  role: ModelRole;
  /** 칩에 적을 이름 — 이미 예쁘게 다듬은 것이 들어온다. */
  label: string;
  context: string;
  onChanged?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<ModelPickerView | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  // 30분 감시(백엔드)가 「잴 때와 카드 사정이 바뀌었다」고 하면 칩에 작은 점 — 깜빡이지 않는다(제품 결정).
  const [cardChanged, setCardChanged] = useState(false);
  const shell = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!api) return;
    try {
      setView(await api.modelPicker(role));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [api, role]);

  // 화면이 뜰 때 · 역할이 바뀔 때 미리 한 번. 누르는 순간의 0.8초를 없앤다.
  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!api || role !== "chat") return;
    const check = () => {
      void api.contextStatus().then((status) => setCardChanged(status.watch?.state === "changed")).catch(() => undefined);
    };
    check();
    window.addEventListener("ontelic:context-watch", check);
    return () => window.removeEventListener("ontelic:context-watch", check);
  }, [api, role]);

  useEffect(() => {
    if (!open) return;
    void load();
    const closeOutside = (event: PointerEvent) => {
      if (!shell.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", closeOutside);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOutside);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open, load]);

  const choose = async (row: PickerModel) => {
    if (!api || row.blocked || row.current) return;
    setBusy(row.tag);
    setError("");
    try {
      const done = await api.selectModel(row.tag, role, row.num_ctx ?? 0);
      if (!done.ok) throw new Error(reasonText(done.error, row));
      await load();
      onChanged?.();
      setOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  };

  // 위성은 본체의 모델을 빌려 쓴다 — 여기서 바꿀 수 있는 척하면 안 된다.
  if (!api || view?.satellite) {
    return <span className="model-chip" title={context}>{label || t("모델 확인 중")}</span>;
  }

  const rows = [...(view?.models ?? [])].sort((a, b) => order(a) - order(b));
  // ★ 2026-09-21 실물에서 잡음: 지금 쓰는 모델이 목록 밖 것이면 맨 윗줄이 되는데,
  //   머리말을 그 앞에 붙이면 **목록이 제목으로 시작하고** 쓰는 모델이 「직접 받아 두신
  //   모델」 아래로 들어간다. 쓰는 것은 어느 무리에도 속하지 않는다 — 맨 위 한 줄이다.
  const firstUnlisted = rows.findIndex((row) => !row.listed && !row.blocked && !row.current);
  const firstBlocked = rows.findIndex((row) => Boolean(row.blocked));

  return (
    <div className="pilot-model-picker local-model-picker" ref={shell}>
      <button
        type="button"
        className={`model-chip pilot-model-trigger ${open ? "open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="listbox"
        title={context}
      >
        <span>{label || t("모델 확인 중")}</span>
        {cardChanged && <i className="model-chip-dot" title={t("잰 뒤로 그래픽카드 사정이 바뀌었습니다 — 눌러서 다시 재 보세요")} />}
        <ChevronDown size={12} aria-hidden />
      </button>
      {open && (
        <div className="pilot-model-popover local-model-popover" role="listbox"
             aria-label={role === "code" ? t("코드 모델 선택") : t("대화 모델 선택")}>
          <div className="pilot-model-popover-head">
            <div>
              <strong>{role === "code" ? t("코드 작업 모델") : t("대화 모델")}</strong>
              <small>
                {role === "code"
                  ? t("Code 탭에서만 씁니다 — 대화 모델은 그대로입니다")
                  : t("대화와 일반 작업에 씁니다")}
              </small>
            </div>
            {view && view.budget_gb > 0 && <span>{view.budget_gb.toFixed(1)}{t("GB 가용")}</span>}
          </div>
          {role === "code" && view?.suggestion && (
            <CodeUpgradeOffer api={api} offer={view.suggestion} budget={view.budget_gb}
              pull={view.pulls[view.suggestion.tag]} onDone={async () => { await load(); onChanged?.(); }} onPoll={load} />
          )}
          {!view ? (
            <p className="local-model-loading"><Loader2 size={13} className="spin" /> {t("이 PC 의 모델을 읽는 중입니다")}</p>
          ) : (
            <div className="pilot-model-options local-model-options">
              {/* ★ 2026-09-21: 여기를 `<div>` 로 감쌌더니 줄이 가로로 겹쳐 쏟아졌다.
                  `.pilot-model-options > button` 규칙이 **직계 자식**만 보는데 버튼이
                  손자가 돼 버려 `display:flex; width:100%` 가 통째로 안 걸린 것이다.
                  `display:contents` 는 배치만 바꾸고 선택자 매칭은 못 바꾼다.
                  Fragment 는 DOM 을 안 만들어 버튼이 직계 자식으로 남는다. */}
              {rows.map((row, index) => (
                <Fragment key={row.tag}>
                  {index === firstUnlisted && firstUnlisted >= 0 && (
                    <p className="local-model-divider">{t("이 PC 에 직접 받아 두신 모델")}</p>
                  )}
                  {index === firstBlocked && firstBlocked >= 0 && (
                    <p className="local-model-divider">{t("지금은 고를 수 없는 모델")}</p>
                  )}
                  <button
                    type="button"
                    role="option"
                    aria-selected={row.current}
                    disabled={Boolean(row.blocked) || busy !== "" || row.current}
                    className={`${row.current ? "selected" : ""} ${row.blocked ? "unavailable" : ""}`}
                    onClick={() => void choose(row)}
                    title={row.blocked || row.grade.detail}
                  >
                    <span className="pilot-model-copy">
                      <strong>
                        {row.name}
                        {!row.listed && <em className="local-model-tag">{t("내 모델")}</em>}
                      </strong>
                      <small>
                        {row.blocked
                          ? row.blocked
                          : row.grade.measured
                            ? row.grade.label
                            : row.current
                              // 쓰는 중인 모델에게 「써 볼 수는 있습니다」는 말이 안 된다 — 이미 쓰고 있다.
                              ? t("{0} · 지금 쓰는 중", row.grade.label)
                              : t("{0} · 써 볼 수는 있습니다", row.grade.label)}
                      </small>
                    </span>
                    <span className="pilot-model-meta">
                      {busy === row.tag
                        ? <Loader2 size={14} className="spin" />
                        : <small>{row.installed ? sizeLabel(row.size_gb) : t("받기 {0}", sizeLabel(row.size_gb))}</small>}
                      {row.current && <Check size={15} aria-label={t("쓰는 중")} />}
                      {!row.blocked && !row.grade.measured && !row.current && (
                        <AlertTriangle size={13} className="local-model-untested" aria-label={t("능력 안 쟀음")} />
                      )}
                    </span>
                  </button>
                </Fragment>
              ))}
            </div>
          )}
          {error && <p className="local-model-error">{error}</p>}
          {/* 머리의 「· 128K」를 누른 자리에서 그 숫자를 잰다(2026-09-23). Code 탭은 같은 모델이면 대화와 같은
              컨텍스트를 쓴다(`num_ctx_for`) — 두 곳에서 따로 재면 러너가 둘이 된다.
              ★ 09-29: 대표가 연 것은 Code 탭 고르개였고 거기엔 칸이 없었다. 이제 양쪽에 보이되 **한 값**이다 —
              같은 모델이면 코드 쪽에서 골라도 대화와 같이 바뀌고(패널이 그렇게 적는다), 다른 모델이면 그렇다고만 적는다. */}
          {view && view.current && (
            <ContextCeilingPanel api={api} model={view.current} onApplied={onChanged} role={role} />
          )}
          <p>
            {t("바꾸면 실제로 한 번 돌려 보고, 그래픽카드에 다 올라갔을 때만 바꿉니다.")}
            {role === "code" && t(" 이어받기·폴더 쓰기 같은 센 권한은 능력을 잰 모델에만 열립니다.")}
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * 코드 일 추천 (2026-10-01 밤 대표 전략) — 대화·브라우저는 작은 모델 그대로, **코드 역할만** 큰 모델로.
 * 우리가 잰 것이 아니라 규칙이면 그렇다고 적는다(`basis`). 받기·적용은 사람이 누를 때만.
 */
function CodeUpgradeOffer({ api, offer, budget, pull, onDone, onPoll }: {
  api: SetupApi;
  offer: CodeUpgrade;
  budget: number;
  pull?: { status: string; completed?: number; total?: number; error?: string };
  onDone: () => Promise<void>;
  onPoll: () => Promise<void>;
}) {
  const [asked, setAsked] = useState(false);
  const [error, setError] = useState("");
  const pulling = pull?.status === "pulling";
  useEffect(() => {
    if (!pulling) return;
    const timer = window.setInterval(() => void onPoll(), 1500);
    return () => window.clearInterval(timer);
  }, [pulling, onPoll]);
  useEffect(() => {
    if (asked && pull && pull.status === "done") void onDone();
  }, [asked, pull?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const pct = pull?.total ? Math.round(((pull.completed ?? 0) / pull.total) * 100) : 0;
  const start = async () => {
    setAsked(true);
    setError("");
    try {
      const started = await api.pullTag(offer.tag, 65536, "code");
      if (!started.ok) throw new Error(started.error || t("받기를 시작하지 못했습니다"));
      await onPoll();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  return (
    <div className="code-upgrade" role="note">
      <p className="code-upgrade-head">
        <strong>{t("코드 일에 더 큰 모델을 써 볼 수 있습니다")}</strong>
        <small>{t("지금")} {offer.current_params_b}{t("B · 이 카드")} {budget.toFixed(1)}{t("GB 에")} {offer.name}({offer.size_gb.toFixed(1)}{t("GB)가 들어갑니다")}</small>
      </p>
      <p className="code-upgrade-basis">{offer.basis} {t("대화·브라우저 모델은 그대로 두고 코드 탭만 바꿉니다.")}</p>
      {pulling ? (
        <p className="code-upgrade-progress"><Loader2 size={13} className="spin" /> {t("받는 중")} {pct}{t("% — 다 받으면 실제로 한 번 돌려 보고 코드 모델로 바꿉니다")}</p>
      ) : (
        <button type="button" className="code-upgrade-go" onClick={() => void start()}>
          {offer.installed ? t("{0} 코드 모델로 쓰기", offer.name) : t("받고 코드 모델로 쓰기 · {0}GB", offer.size_gb.toFixed(1))}
        </button>
      )}
      {(error || pull?.error) && <p className="local-model-error">{error || pull?.error}</p>}
    </div>
  );
}

/** 백엔드가 준 까닭을 사람 말로. 모르는 값은 그대로 보여 준다 — 삼키면 진단이 사라진다. */
function reasonText(error: string | undefined, row: PickerModel): string {
  switch (error) {
    case "no_tool_calling":
      return t("{0} 은(는) 도구를 부를 수 없어 Sonjari가 일을 못 합니다", row.name);
    case "model_not_installed":
      return t("{0} 이(가) 이 PC 에 없습니다", row.name);
    case "model_not_fully_on_gpu":
      return t("{0} 이(가) 그래픽카드에 다 올라가지 않아 바꾸지 않았습니다", row.name);
    case "model_did_not_generate":
      return t("{0} 이(가) 글자를 만들지 못해 바꾸지 않았습니다", row.name);
    case "model_load_timeout":
      return t("{0} 을(를) 올리는 데 시간이 너무 오래 걸렸습니다", row.name);
    case "model_out_of_memory":
      return t("그래픽카드 메모리가 모자라 {0} 을(를) 올리지 못했습니다 — 그래픽카드를 쓰는 다른 프로그램을 닫고 다시 시도해 주세요", row.name);
    case "model_load_failed":
      return t("{0} 을(를) 올리다 Ollama 가 멈췄습니다", row.name);
    case "ollama_runner_missing":
      return t("Ollama 가 반쪽만 깔려 있습니다 — 설정 › 모델에서 고칠 수 있습니다");
    case "satellite_uses_brain_models":
      return t("이 PC 는 본체의 모델을 빌려 씁니다 — 본체에서 바꿔 주세요");
    default:
      return error || t("바꾸지 못했습니다");
  }
}
