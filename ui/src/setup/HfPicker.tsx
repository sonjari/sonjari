/**
 * 허깅페이스에서 직접 고르기 (2026-10-01 밤 대표 결정 — 헤르메스식 커스터마이징).
 *
 * 추천은 그대로 두고, 그 옆에 **이 카드에 들어가는 GGUF 와 양자화를 사람이 고르는 길**을 연다.
 * 직접 고른 모델은 Sonjari가 잰 적이 없다 — 화면이 그렇게 말하고(호박색 = 아직 안 쟀다),
 * 받은 뒤 실제로 올려 보고 도구 호출까지 확인해야 적용한다(기존 `pullTag` → 적용 장치).
 *
 * 이 화면의 한 가지 인상은 **양자화 사다리**다 — 위의 메모리 자와 같은 눈금 위에 파일마다 핀을 꽂는다.
 * 쓸 수 있는 메모리 선 너머의 핀은 누를 수 없다. 사람은 비트·VRAM 을 몰라도 「어디까지 들어가나」를 한눈에 본다.
 */
import { t } from "../i18n";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { GpuCard, HfFile, HfFiles, HfModel, HfSearch, SetupApi } from "./setupApi";

type Sort = "downloads" | "trending";

export interface HfPick {
  repo: string;
  file: HfFile;
  /** 「글만 읽기」로 받는다 — 그림 부속을 뺀 채 올린다(받는 파일은 같다). 부속이 따로 오는 저장소에서만 고를 수 있다. */
  textOnly?: boolean;
}

export function HfPicker({
  api,
  card,
  busy,
  busyWhy = "",
  picked,
  onPick,
  onGet,
  ctx = 32768,
  activeTag = "",
  status = null,
}: {
  api: SetupApi;
  card: GpuCard | null;
  busy: boolean;
  /** 지금 받거나 돌려 보는 중인 모델(태그)과 그 진행 줄 — **누른 그 줄 안에** 보여 준다(2026-10-07: 진행이 목록 밖에만 있었다). */
  activeTag?: string;
  status?: ReactNode;
  /** 받기 버튼이 왜 꺼져 있는지 — 말 없이 꺼진 버튼은 고장으로 보인다(2026-10-05 AWS 첫 실행). */
  busyWhy?: string;
  picked: HfPick | null;
  onPick: (pick: HfPick | null) => void;
  onGet: (pick: HfPick) => void;
  /** 받은 뒤 적용할 대화 길이 — 「들어가나」를 이 길이의 여유로 판정한다(레딧 댓글, 2026-10-03). */
  ctx?: number;
}) {
  const usable = card?.usable_gb ?? 0;
  const [typed, setTyped] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("downloads");
  const [found, setFound] = useState<HfSearch | null>(null);
  const [open, setOpen] = useState<string>("");

  useEffect(() => {
    let alive = true;
    setFound(null);
    api
      .hfSearch(query, usable, sort)
      .then((result) => {
        if (!alive) return;
        setFound(result);
        // 이 PC 에서 잰 것, 없으면 기준을 통과한 첫 모델을 펼쳐 둔다 — 탭을 열면 바로 「무엇을 어느 양자화로」가 보이게.
        const first = result.models.find((m) => m.pc_measured) ?? result.models.find((m) => m.recommended);
        if (first) setOpen((now) => now || first.repo);
      })
      .catch((err) => alive && setFound({ ok: false, error: err instanceof Error ? err.message : String(err), models: [] }));
    return () => {
      alive = false;
    };
  }, [api, query, sort, usable]);

  return (
    <section className="hf-picker" aria-label={t("허깅페이스에서 직접 고르기")}>
      <h3 className="gallery-head is-external">
        {t("허깅페이스에서 직접 고르기")}
        <small>{t("모델과 양자화를 직접 고릅니다 · Sonjari 미검증 · 받은 뒤 실제로 올려 보고 도구 호출까지 확인해야 적용합니다")}</small>
      </h3>

      <form
        className="hf-search"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          setOpen("");
          setQuery(typed.trim());
        }}
      >
        <input
          aria-label={t("모델 이름으로 찾기")}
          value={typed}
          placeholder={t("모델 이름 — 예: Qwen3.8 27B · gemma")}
          spellCheck={false}
          onChange={(event) => setTyped(event.target.value)}
        />
        <button type="submit" className="setup-btn-quiet">{t("찾기")}</button>
        <div className="hf-sort" role="radiogroup" aria-label={t("정렬")}>
          {(["downloads", "trending"] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={sort === value}
              className={sort === value ? "is-on" : ""}
              onClick={() => setSort(value)}
            >
              {value === "downloads" ? t("많이 받은 순") : t("요즘 뜨는 순")}
            </button>
          ))}
        </div>
      </form>

      {found === null ? (
        <p className="setup-reason">{t("허깅페이스에서 이 카드에 들어가는 모델을 찾는 중…")}</p>
      ) : !found.ok ? (
        <p className="setup-warn" role="alert">
          {found.error === "hf_unreachable"
            ? t("허깅페이스에 닿지 못했습니다 — 회사망이 막았거나 인터넷이 끊겼을 수 있습니다. 「받아 둔 모델·이름 입력」에서 hf.co/작성자/모델:양자화 를 직접 넣어도 됩니다.")
            : t("목록을 받지 못했습니다: {0}", found.error)}
        </p>
      ) : found.models.length === 0 ? (
        <p className="setup-reason">
          {query ? t("「{0}」로 찾은 것 중 이 카드에 들어가고 도구 호출이 되는 모델이 없습니다. 이름을 짧게 줄여 보세요.", query) : t("이 카드에 들어가는 모델을 찾지 못했습니다.")}
        </p>
      ) : (
        <>
          {/* ★ 2026-10-03 (레딧 r/LocalLLM 댓글): 「추천」은 무엇을 확인했는지 말해 주지 않는다 —
              표시는 **확인한 것만** 하나씩 적는다. 템플릿은 도구 칸을 읽었을 뿐 돌려 본 것이 아니라 「시험함」이라고 쓰지 않는다. */}
          <div className="setup-note hf-rule">
            <p>{t("표시는 확인한 것만 적습니다.")}</p>
            <ul className="hf-legend">
              <li><span className="hf-badge is-measured">{t("✓ 이 PC 실측")}</span>{t("이 PC 에서 올려 보고 잰 기록이 있습니다")}</li>
              <li><span className="hf-badge is-fact">{t("✓ 공식")}</span>{t("모델 회사 계정이 올렸거나, 원본을 그대로 양자화하는 곳(unsloth·bartowski 등)이 공식 원본을 양자화해 올렸습니다 — 개조판 제외")}</li>
              <li><span className="hf-badge">{t("✓ 기준 통과")}</span>{t("믿을 만한 제작자 · 개조판 아님 · 이 카드에 3비트 이상 · 그중 많이 받은 순 — 규칙이지 잰 성적이 아닙니다")}</li>
            </ul>
            <p>{t("목록의 모델은 모두 채팅 템플릿에 도구 칸이 있습니다 — 템플릿을 읽은 것이지 실제 대화로 돌려 본 것은 아닙니다. 받은 뒤 적용할 때 도구 호출을 실제로 확인합니다.")}</p>
          </div>
          <ul className="hf-list">
            {found.models.map((model) => (
              <HfRow
                key={model.repo}
                api={api}
                card={card}
                model={model}
                open={open === model.repo}
                onToggle={() => setOpen(open === model.repo ? "" : model.repo)}
                picked={picked?.repo === model.repo ? picked.file : null}
                onPick={(file) => onPick(file ? { repo: model.repo, file } : null)}
                busy={busy}
                busyWhy={busyWhy}
                onGet={onGet}
                ctx={ctx}
                activeTag={activeTag}
                status={status}
              />
            ))}
          </ul>
          {found.hidden && (found.hidden.no_tools > 0 || found.hidden.too_big > 0) && (
            <p className="setup-note hf-hidden">
              {t("숨김: 도구 호출 형식이 없는 모델")} {found.hidden.no_tools}{t("개(Sonjari가 일을 시킬 수 없음) · 이 카드에 2비트로도 안 들어가는 모델")}{" "}
              {found.hidden.too_big}{t("개")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function HfRow({
  api,
  card,
  model,
  open,
  onToggle,
  picked,
  onPick,
  busy,
  busyWhy,
  onGet,
  ctx,
  activeTag,
  status,
}: {
  api: SetupApi;
  card: GpuCard | null;
  model: HfModel;
  activeTag: string;
  status: ReactNode;
  open: boolean;
  onToggle: () => void;
  picked: HfFile | null;
  onPick: (file: HfFile | null) => void;
  busy: boolean;
  busyWhy: string;
  onGet: (pick: HfPick) => void;
  ctx: number;
}) {
  const [files, setFiles] = useState<HfFiles | null>(null);
  // 그림 읽기 — 이 저장소의 양자화를 「글만 읽기」로 받을지. 양자화를 바꿔도 고른 것은 남는다(같은 모델의 같은 선택).
  const [textOnly, setTextOnly] = useState(false);
  const asked = useRef(false);
  useEffect(() => {
    if (!open || asked.current) return;
    asked.current = true;
    api
      .hfFiles(model.repo, card?.usable_gb ?? 0, ctx)
      .then(setFiles)
      .catch((err) => setFiles({ ok: false, error: err instanceof Error ? err.message : String(err), files: [] }));
  }, [api, card, ctx, model.repo, open]);

  const panel = `hf-${model.repo.replace(/[^A-Za-z0-9]/g, "-")}`;
  return (
    <li className={`hf-row${open ? " is-open" : ""}${picked ? " is-picked" : ""}`}>
      <button type="button" className="hf-row-head" aria-expanded={open} aria-controls={panel} onClick={onToggle}>
        <span className="hf-name">
          {model.pc_measured && (
            <span className="hf-badge is-measured" title={t("이 PC 에서 {0} 를 올려 보고 쟀습니다 — GPU 에 다 들어간 가장 큰 컨텍스트 {1}K{2}", model.pc_measured.quant, Math.round(model.pc_measured.ceiling / 1024), model.pc_measured.tokens_per_sec ? t(" · 초당 {0}토큰", model.pc_measured.tokens_per_sec) : "")}>
              {t("✓ 이 PC 실측")}
            </span>
          )}
          {model.checks?.includes("official") && <span className="hf-badge is-fact" title={t("모델 회사 공식 계정이 올린 저장소입니다")}>{t("✓ 공식")}</span>}
          {model.checks?.includes("official_base") && <span className="hf-badge is-fact" title={t("원본을 그대로 양자화하는 곳이 올렸고, 카드에 적힌 원본이 전부 모델 회사 공식 저장소입니다(개조판 아님)")}>{t("✓ 공식 원본")}</span>}
          {model.recommended && <span className="hf-badge" title={t("믿을 만한 제작자 · 개조판 아님 · 이 카드에 3비트 이상 · 그중 많이 받은 순 — 규칙이지 잰 성적이 아닙니다")}>{t("✓ 기준 통과")}</span>}
          {model.measured_family && <span className="hf-badge is-measured" title={t("이 제품에서 {0} 를 실제로 쟀습니다(양자화·제작자는 다를 수 있음)", model.measured_family)}>{t("Sonjari 실측 계열")}</span>}
          {model.modded && <span className="hf-badge is-modded" title={t("안전 장치를 걷어 냈거나 역할극용으로 바꾼 개조판입니다")}>{t("개조판")}</span>}
          <span className="hf-author">{model.author}/</span>
          <b>{model.name}</b>
        </span>
        <span className="hf-meta num">
          {model.params_b ? `${model.params_b}B` : t("크기 모름")}
          {model.architecture ? ` · ${model.architecture}` : ""}
          {model.vision ? t(" · 화면 읽기") : ""}
        </span>
        <span className="hf-fit">≈{model.best_bits}{t("비트까지")}</span>
        <span className="hf-pop num" title={t("내려받기 {0}회 · 좋아요 {1}", model.downloads.toLocaleString(), model.likes.toLocaleString())}>
          ↓{compact(model.downloads)}
        </span>
      </button>
      {open && (
        <div id={panel} className="hf-row-body">
          {files === null ? (
            <p className="setup-reason">{t("양자화 파일을 읽는 중…")}</p>
          ) : !files.ok ? (
            <p className="setup-warn">{t("파일 목록을 받지 못했습니다")}{files.error === "hf_unreachable" ? t(" — 허깅페이스에 닿지 못했습니다") : `: ${files.error}`}</p>
          ) : files.files.length === 0 ? (
            <p className="setup-reason">{t("Ollama 로 받을 수 있는 한 파일짜리 GGUF 가 없습니다(나눠 올린 파일만 있음).")}</p>
          ) : (
            <QuantLadder card={card} files={files.files} margin={files.margin_gb ?? 1.2} ctx={files.ctx ?? ctx} picked={picked} onPick={onPick} />
          )}
          {picked && (
            <div className="hf-get">
              {/* 그림 읽기 — 부속이 따로 오는 저장소에서만(2026-10-13). 6GB 카드에서 눈을 단 4B 는 다 못 올라가고,
                  눈을 빼니 창 48K 까지 올라갔다: Ollama 가 눈을 단 모델에는 카드 자리를 1GB 넘게 더 비워 둔다. */}
              {(picked.projector_gb ?? 0) > 0 && (
                <div className="model-eyes hf-eyes">
                  <span className="model-eyes-label">{t("그림 읽기")}</span>
                  <div className="model-eyes-chips" role="radiogroup" aria-label={t("{0} 그림 읽기", model.name)}>
                    <button type="button" role="radio" aria-checked={!textOnly} className={!textOnly ? "is-on" : ""} disabled={busy} onClick={() => setTextOnly(false)}>
                      {t("그림도 읽기")}
                    </button>
                    <button type="button" role="radio" aria-checked={textOnly} className={textOnly ? "is-on" : ""} disabled={busy} onClick={() => setTextOnly(true)}>
                      {t("글만 읽기")}
                      <span className="num">−{picked.projector_gb!.toFixed(1)}GB</span>
                    </button>
                  </div>
                  <p className="model-eyes-note">
                    {textOnly
                      ? t("붙인 사진과 페이지 속 그림은 읽지 못합니다. 그림 부속을 빼고 올려, 빠듯한 카드에서도 그래픽카드에 다 올라가기 쉽습니다. 받는 파일은 같아서 나중에 다시 켤 수 있습니다.")
                      : t("붙인 사진과 페이지 속 그림까지 읽습니다. 그래픽카드에 다 안 올라가면 글만 읽기로 다시 받아 보세요 — 새로 받는 것은 없습니다.")}
                  </p>
                </div>
              )}
              <button type="button" className="setup-btn-go" disabled={busy}
                onClick={() => onGet({ repo: model.repo, file: picked, ...(textOnly && (picked.projector_gb ?? 0) > 0 ? { textOnly: true } : {}) })}>
                {picked.quant} {t("받고 확인하기 ·")} <span className="num">{picked.gb.toFixed(1)}GB</span>
              </button>
              {status && activeTag === picked.tag
                ? <div className="hf-status" data-testid="hf-status">{status}</div>
                : busy && busyWhy && <p className="setup-reason" data-testid="hf-busy-why">{busyWhy}</p>}
              <p className="setup-note">
                {picked.bits > 0 && picked.bits < 2
                  ? t("1비트는 품질이 크게 떨어집니다. ")
                  : picked.fit === "tight"
                    ? t("빠듯합니다 — 올려 보고 그래픽카드에 다 안 들어가면 컨텍스트를 줄이거나 적용하지 않습니다. ")
                    : ""}
                {t("받은 뒤 실제로 올려 보고 도구 호출이 되는지 확인해야 적용합니다. 안 맞으면 지금 모델을 그대로 둡니다.")}
              </p>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/**
 * 양자화 사다리 — 메모리 자와 같은 눈금(카드 전체)에 파일마다 핀. 쓸 수 있는 메모리 너머의 핀은 고를 수 없다.
 * 핀 아래 칩은 비트별로 묶는다. 칩에 올리면 그 핀이 밝아진다.
 */
export function QuantLadder({
  card,
  files,
  margin,
  ctx = 32768,
  picked,
  onPick,
}: {
  card: GpuCard | null;
  files: HfFile[];
  margin: number;
  ctx?: number;
  picked: HfFile | null;
  onPick: (file: HfFile | null) => void;
}) {
  const [hover, setHover] = useState("");
  const total = card?.vram_total_gb || Math.max(...files.map((f) => f.gb), 1);
  const usable = card?.usable_gb ?? 0;
  const pct = (gb: number) => `${Math.min(100, (gb / total) * 100)}%`;
  const usableFiles = files.filter((f) => f.fit !== "over");
  const tooBig = files.filter((f) => f.fit === "over");
  const byBits = new Map<number, HfFile[]>();
  for (const file of usableFiles) {
    const key = Math.floor(file.bits) || 0;
    byBits.set(key, [...(byBits.get(key) ?? []), file]);
  }
  const groups = [...byBits.entries()].sort((a, b) => a[0] - b[0]);
  const lit = hover || picked?.quant || "";

  return (
    <figure className="quant-ladder" aria-label={t("양자화 {0}개 — 이 카드에 들어가는 것 {1}개(추정)", files.length, usableFiles.length)}>
      <div className="quant-track">
        {card && <span className="quant-usable" style={{ width: pct(usable) }} />}
        {card && <span className="quant-reserve" style={{ left: pct(usable), width: pct(card.reserve_gb) }} />}
        {files.filter((f) => f.gb <= total).map((file) => (
          <span
            key={file.quant}
            className={`quant-pin is-${file.fit}${lit === file.quant ? " is-lit" : ""}`}
            style={{ left: pct(file.gb) }}
            aria-hidden="true"
          >
            {lit === file.quant && <span className="quant-pin-label num">{file.quant} {file.gb.toFixed(1)}</span>}
          </span>
        ))}
      </div>
      <div className="quant-groups" role="radiogroup" aria-label={t("양자화 고르기")}>
        {groups.map(([bits, list]) => (
          <div key={bits} className="quant-group">
            <span className="quant-group-label">{bits >= 16 ? t("원본") : bits ? t("{0}비트", bits) : t("기타")}</span>
            {list.map((file) => (
              <button
                key={file.quant}
                type="button"
                role="radio"
                aria-checked={picked?.quant === file.quant}
                className={`quant-chip is-${file.fit}${picked?.quant === file.quant ? " is-on" : ""}`}
                onMouseEnter={() => setHover(file.quant)}
                onMouseLeave={() => setHover("")}
                onFocus={() => setHover(file.quant)}
                onBlur={() => setHover("")}
                onClick={() => onPick(picked?.quant === file.quant ? null : file)}
                title={chipTitle(file, margin)}
              >
                {file.quant}
                <span className="num">{file.gb.toFixed(1)}</span>
                {file.pc_measured && <span className="quant-pc">{t("✓ 이 PC")}</span>}
                {file.recommended && <span className="quant-rec">{t("여유 최대")}</span>}
              </button>
            ))}
          </div>
        ))}
      </div>
      <figcaption className="quant-caption">
        {usableFiles.length > 0 ? (
          <>
            {t("이 카드에 들어가는 것")} <b className="num">{usableFiles.length}</b>
            {t("개 — 대화 길이 {0}K 로 올릴 때(파일 크기 + 실행 여유 ≈{1}GB, 추정 · 받은 뒤 실제로 올려 봅니다)", Math.round(ctx / 1024), margin)}
          </>
        ) : (
          t("이 카드에 들어가는 양자화가 없습니다")
        )}
        {(files[0]?.projector_gb ?? 0) > 0 && (
          <span className="quant-proj">
            {" · "}{t("크기는 파일 목록에서 확인한 받기 크기 — 화면 읽기 부속")} <span className="num">{files[0].projector_gb!.toFixed(1)}GB</span>{t(" 포함")}
          </span>
        )}
        {tooBig.length > 0 && (
          <span className="quant-over">
            {" · "}{t("더 큰")} {tooBig.length}{t("개(")}<span className="num">{tooBig[0].gb.toFixed(1)}~{tooBig[tooBig.length - 1].gb.toFixed(1)}GB</span>{t(")는 안 들어갑니다")}
          </span>
        )}
      </figcaption>
    </figure>
  );
}

/** 칩에 올리면 보이는 말 — 크기는 무엇을 더한 것인지, 이 PC 에서 잰 적이 있는지까지. */
function chipTitle(file: HfFile, margin: number): string {
  const size = file.projector_gb
    ? t("모델 {0}GB + 화면 읽기 부속 {1}GB = 받기 {2}GB(파일 목록에서 확인)", (file.file_gb ?? file.gb - file.projector_gb).toFixed(2), file.projector_gb.toFixed(2), file.gb.toFixed(2))
    : t("받기 {0}GB(파일 목록에서 확인)", file.gb.toFixed(2));
  const measured = file.pc_measured
    ? t(" · 이 PC 실측: GPU 에 다 들어간 가장 큰 컨텍스트 {0}K", Math.round(file.pc_measured.ceiling / 1024))
    : "";
  return t("{0} · {1} · 올리면 ≈{2}GB(추정){3}{4}", file.file, size, (file.gb + margin).toFixed(1), file.fit === "tight" ? t(" — 빠듯함") : "", measured);
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}
