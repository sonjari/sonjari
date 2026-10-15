/**
 * 브라우저 무대 — 화면 밖 크롬을 **온텔릭 창 안에서** 보고, 누르면 그대로 넘겨받는다 (2026-09-24 부산).
 *
 * 크롬 창을 사람 화면에 띄우는 길은 전부 번쩍임·앞창 뺏기로 끝났다. 그래서 창을 띄우지 않는다:
 * 크롬은 늘 화면 밖에 있고, 이 칸이 크롬이 그리는 화면을 스트림으로 받아 보여 준다(`/v1/browser/live`).
 * 사람이 화면을 누르는 순간 그 입력이 곧 넘겨받기다 — 온텔릭은 브라우저 도구를 멈추고 기다린다(`live_view.py`).
 *
 * 지키는 것
 * - **누르기 전에는 아무것도 보내지 않는다.** 마우스를 올리기만 해서는 넘겨받지 않는다 — 온텔릭 일을 우연히 멈추면 안 된다.
 * - 한글은 조합이 끝난 글자만 보낸다(`compositionend`). 조합 중 Enter 는 글자를 넣은 **뒤에** 보낸다.
 * - 오른쪽 클릭은 안 보낸다: 크롬이 띄우는 메뉴는 화면 밖 창에 떠서 보이지 않고, 입력을 막는다. 고르기 상자·파일 창도 같다 —
 *   그럴 때를 위해 「진짜 크롬으로 보기」가 있다.
 * - 스트림이 안 오면(뒤쪽 탭·옛 크롬) 예전 스크린샷 화면(`fallback`)으로 돌아간다. 빈 화면을 두지 않는다.
 *
 * 3차(2026-09-26) — 평소 쓰던 브라우저처럼: 탭 줄 · 뒤로/앞으로/새로고침 · 주소창 · 로딩 막대.
 * 크롬이 페이지 밖에 띄우는 것(고르기 상자 목록 · 확인/취소 알림창 · 파일 고르기)은 무대가 대신 그린다.
 * 규칙은 하나 — 사람이 무대 안의 무엇이든(화면·주소창·버튼·탭) 누르면 그 순간 넘겨받기.
 */
import { t } from "../i18n";
import { invoke } from "@tauri-apps/api/core";
import { AppWindow, ArrowLeft, ArrowRight, FileUp, Hand, Lock, Plus, RotateCw, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { isTauri, type JarvisClient } from "../backend";
import type { LiveInputEvent, LiveSelect, LiveState } from "../types";
import { shortUrl } from "./screen";

const SPECIAL_KEYS = new Set([
  "Enter", "Backspace", "Delete", "Tab", "Escape",
  "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown",
]);
/** 마지막 장이 이보다 오래되면 스트림이 끊긴 것으로 본다(정적인 페이지는 그리지 않으므로 넉넉히). */
const STALE_MS = 20_000;
/** 페이지를 옮기는 사이(`no_page`)는 잠깐이다 — 이만큼은 마지막 장을 그대로 둔다(2026-09-30: 옮길 때마다 「준비 중」으로 깜빡였다). */
const PAGE_GAP_MS = 6_000;
const MOVE_EVERY_MS = 40;

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export function LiveStage(props: {
  client: JarvisClient | null;
  /** 칸이 열려 있나 — 닫혀 있으면 스트림을 안 당긴다. */
  active: boolean;
  /** 크게 보는 중(무대 모드)인가 — 이때만 크롬 창 크기를 무대 비율에 맞춘다. */
  stage: boolean;
  /** 지금 온텔릭이 하는 일 한 줄. */
  caption: string;
  where: string;
  /** 본문이 아래에 있어 그림이 자리를 양보할 때. */
  compact?: boolean;
  /** 스트림이 안 될 때 보여 줄 예전 스크린샷 화면. */
  fallback: ReactNode;
  /** 스트림이 멈춰도 **받은 마지막 장**을 그대로 둔다(작은 창). 대신 볼 스크린샷 화면이 없는 자리에서 글 한 줄로 바뀌지 않게. */
  holdLastFrame?: boolean;
  onStreamingChange?: (streaming: boolean) => void;
  onControlChange?: (active: boolean) => void;
}) {
  const { client, active, stage } = props;
  const [imageUrl, setImageUrl] = useState("");
  const imageUrlRef = useRef("");
  const [streaming, setStreaming] = useState(false);
  const [control, setControl] = useState(false);
  const [releaseIn, setReleaseIn] = useState(0);
  const [hover, setHover] = useState(false);
  const [pageUrl, setPageUrl] = useState("");
  const boxRef = useRef<HTMLDivElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const keysRef = useRef<HTMLTextAreaElement | null>(null);
  const pressedRef = useRef<"left" | "middle" | "none">("none");
  const lastMoveRef = useRef(0);
  const pendingEnterRef = useRef(false);
  const controlRef = useRef(false);
  /** 사람이 막 누른 시각. 누르기 전에 떠난 화면 요청이 「넘겨받지 않음」을 들고 늦게 돌아와도 덮어쓰지 않게 한다. */
  const tookAtRef = useRef(0);
  /** 지금 화면에 걸린 그림의 크롬 CSS 크기 — 입력 좌표를 이 크기로 재라고 같이 보낸다(창 크기가 바뀌는 사이의 어긋남 방지). */
  const frameDimsRef = useRef<{ fw: number; fh: number }>({ fw: 0, fh: 0 });
  // ── 3차: 브라우저 틀 ──
  const [nav, setNav] = useState<LiveState | null>(null);
  const [selectMenu, setSelectMenu] = useState<LiveSelect | null>(null);
  const [address, setAddress] = useState("");
  const [editingAddress, setEditingAddress] = useState(false);
  const [promptText, setPromptText] = useState("");
  /** 이미 답한 알림창·파일 고르기의 시각. 답하기 전에 떠난 상태 요청이 옛 창을 들고 돌아오면 다시 그려서 다음 클릭을 삼켰다(E2E). */
  const answeredRef = useRef<Set<number>>(new Set());

  const { onStreamingChange, onControlChange } = props;
  useEffect(() => { onStreamingChange?.(streaming); }, [streaming, onStreamingChange]);
  useEffect(() => {
    controlRef.current = control;
    onControlChange?.(control);
    if (!control) keysRef.current?.blur();
  }, [control, onControlChange]);

  useEffect(() => () => {
    if (imageUrlRef.current) URL.revokeObjectURL(imageUrlRef.current);
  }, []);

  // ── 화면 받기(롱 폴) ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!client || !active) return;
    let alive = true;
    let seq = 0;
    let lastFrameAt = 0;
    const loop = async () => {
      while (alive) {
        if (document.hidden) { await sleep(600); continue; }
        const started = performance.now();
        const frame = await client.getLiveFrame(seq, 1);
        if (!alive) break;
        if (frame.control || Date.now() - tookAtRef.current > 2_500) setControl(frame.control);
        setReleaseIn(frame.releaseIn);
        if (frame.blob) {
          seq = frame.seq;
          lastFrameAt = Date.now();
          const url = URL.createObjectURL(frame.blob);
          const previous = imageUrlRef.current;
          imageUrlRef.current = url;
          setImageUrl(url);
          if (frame.url) setPageUrl(frame.url);
          if (frame.width > 0 && frame.height > 0) frameDimsRef.current = { fw: frame.width, fh: frame.height };
          if (previous) window.setTimeout(() => URL.revokeObjectURL(previous), 1_000);
        }
        // ★ 가만히 있는 페이지는 크롬이 새 장을 안 보낸다 — 「마지막 장이 오래됐다」로 끊김을 재면 멀쩡한 스트림을 버린다
        //   (비평 2회차: 20초 뒤 예전 스크린샷으로 돌아갔다). 백엔드가 스트림 중이라고 하는 동안은 마지막 장을 그대로 믿는다.
        //   서버에 아예 못 닿는 경우만 시간으로 끊는다.
        const reachable = frame.status !== "" && frame.status !== "backend_unreachable" && frame.status !== "no_token";
        const fresh = lastFrameAt > 0 && (frame.status === "streaming" || frame.control
          || (frame.status === "no_page" && Date.now() - lastFrameAt < PAGE_GAP_MS)
          || (!reachable && Date.now() - lastFrameAt < STALE_MS));
        setStreaming(fresh);
        // 새 장 없이 곧바로 돌아왔으면(서버가 없거나 스트림이 없다) 잠깐 쉰다. 있으면 초당 20장 안쪽으로.
        const spent = performance.now() - started;
        await sleep(frame.blob ? 45 : spent < 150 ? 700 : 0);
      }
    };
    void loop();
    return () => { alive = false; };
  }, [client, active]);

  // ── 브라우저 틀 상태(주소·탭·알림창) ─────────────────────────────────────
  useEffect(() => {
    if (!client || !active || !streaming) return;
    let alive = true;
    const pull = async () => {
      try {
        const next = await client.getLiveState();
        if (alive) setNav(next);
      } catch {
        // 옛 백엔드(3차 전)면 틀 없이 화면만 보여 준다.
      }
    };
    void pull();
    const timer = window.setInterval(() => void pull(), 700);
    return () => { alive = false; window.clearInterval(timer); };
  }, [client, active, streaming]);

  useEffect(() => { if (nav?.dialog?.type === "prompt") setPromptText(nav.dialog.default ?? ""); }, [nav?.dialog?.type, nav?.dialog?.default]);

  // ── 무대 크기에 크롬 맞추기 ──────────────────────────────────────────────
  useEffect(() => {
    const box = boxRef.current;
    if (!client || !active || !stage || !box) return;
    let timer = 0;
    let lastSent = "";
    const observer = new ResizeObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const width = Math.round(box.clientWidth);
        const height = Math.round(box.clientHeight);
        const key = `${Math.round(width / 40)}:${Math.round(height / 40)}`;
        if (width < 200 || height < 150 || key === lastSent) return;
        lastSent = key;
        void client.liveFit(width, height).catch(() => null);
      }, 500);
    });
    observer.observe(box);
    return () => { observer.disconnect(); window.clearTimeout(timer); };
  }, [client, active, stage, streaming]);

  // ── 입력 ───────────────────────────────────────────────────────────────
  // ★ 입력은 **한 줄로 줄 세워 순서대로** 보낸다(2026-09-26 E2E 에서 잡힘). 누르기·떼기를 따로 보내면 서버에 도착하는 순서가
  //   뒤바뀔 수 있다 — 누르기는 「고르기 상자인가」를 먼저 물어 몇 ms 늦는데, 그 사이 떼기가 먼저 들어가면 단추가 눌린 채 남고
  //   클릭이 사라졌다(확인창·파일 고르기가 가끔 안 열렸다). 보내는 중에 쌓인 것은 다음 한 번에 몰아 보내고, 이동은 마지막 것만 남긴다.
  const queueRef = useRef<LiveInputEvent[]>([]);
  const sendingRef = useRef(false);
  const flush = useCallback(async () => {
    if (!client || sendingRef.current) return;
    sendingRef.current = true;
    try {
      while (queueRef.current.length) {
        const batch = queueRef.current.splice(0, queueRef.current.length);
        const result = await client.sendLiveInput(batch).catch(() => null);
        if (result?.select) {
          pressedRef.current = "none";
          setSelectMenu(result.select);
        }
      }
    } finally {
      sendingRef.current = false;
    }
  }, [client]);
  const send = useCallback((events: LiveInputEvent[]) => {
    if (!client || !events.length) return;
    for (const raw of events) {
      const event = raw.kind === "mouse" || raw.kind === "wheel" ? { ...raw, ...frameDimsRef.current } : raw;
      const last = queueRef.current[queueRef.current.length - 1];
      if (event.kind === "mouse" && event.type === "move" && last?.kind === "mouse" && last.type === "move") {
        queueRef.current[queueRef.current.length - 1] = event;
      } else {
        queueRef.current.push(event);
      }
    }
    void flush();
  }, [client, flush]);

  /** 화면 좌표 → 크롬 화면 기준 0..1. 그림 밖(여백)이면 null. */
  const toPage = useCallback((clientX: number, clientY: number): { x: number; y: number } | null => {
    const img = imgRef.current;
    if (!img || !img.naturalWidth || !img.naturalHeight) return null;
    const rect = img.getBoundingClientRect();
    const scale = Math.min(rect.width / img.naturalWidth, rect.height / img.naturalHeight);
    const width = img.naturalWidth * scale;
    const height = img.naturalHeight * scale;
    const left = rect.left + (rect.width - width) / 2;
    // 그림은 **위쪽 가운데**에 그린다(`object-position: top center`, `pageToBox` 도 같다). 세로 가운데로 셈하면 비율이 칸과
    // 어긋날 때(창 맞춤이 안 먹은 탭 등) 위쪽 누르기가 「그림 밖」이 되어 조용히 버려졌다(2026-09-26 E2E).
    const top = rect.top;
    const x = (clientX - left) / width;
    const y = (clientY - top) / height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return null;
    return { x, y };
  }, []);

  const mods = (event: { ctrlKey: boolean; shiftKey: boolean; altKey: boolean; metaKey: boolean }) => ({
    ctrl: event.ctrlKey, shift: event.shiftKey, alt: event.altKey, meta: event.metaKey,
  });

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button === 2) return;
    const point = toPage(event.clientX, event.clientY);
    if (!point) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const button = event.button === 1 ? "middle" : "left";
    pressedRef.current = button;
    tookAtRef.current = Date.now();
    setControl(true);
    keysRef.current?.focus({ preventScroll: true });
    setSelectMenu(null);
    // 누른 곳이 고르기 상자면 백엔드가 누르지 않고 목록을 돌려준다(`flush` 가 받는다) — 크롬의 목록 창은 화면 밖에 떠서 안 보인다.
    send([
      { kind: "mouse", type: "move", ...point, button: "none", ...mods(event) },
      { kind: "mouse", type: "down", ...point, button, clickCount: Math.max(1, event.detail || 1), ...mods(event) },
    ]);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!controlRef.current && pressedRef.current === "none") return;
    const now = performance.now();
    if (now - lastMoveRef.current < MOVE_EVERY_MS) return;
    const point = toPage(event.clientX, event.clientY);
    if (!point) return;
    lastMoveRef.current = now;
    send([{ kind: "mouse", type: "move", ...point, button: pressedRef.current, ...mods(event) }]);
  };

  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    const button = pressedRef.current;
    if (button === "none") return;
    pressedRef.current = "none";
    const point = toPage(event.clientX, event.clientY) ?? { x: -1, y: -1 };
    if (point.x < 0) return;
    send([{ kind: "mouse", type: "up", ...point, button, clickCount: Math.max(1, event.detail || 1), ...mods(event) }]);
  };

  // 휠은 넘겨받은 뒤에만 — 지켜보는 중에 굴린 휠이 온텔릭 화면을 움직이면 안 된다. passive:false 로 온텔릭 화면 스크롤도 막는다.
  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const onWheel = (event: WheelEvent) => {
      if (!controlRef.current) return;
      const point = toPage(event.clientX, event.clientY);
      if (!point) return;
      event.preventDefault();
      const unit = event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? 400 : 1;
      send([{ kind: "wheel", ...point, dx: event.deltaX * unit, dy: event.deltaY * unit, ctrl: event.ctrlKey, shift: event.shiftKey }]);
    };
    box.addEventListener("wheel", onWheel, { passive: false });
    return () => box.removeEventListener("wheel", onWheel);
  }, [send, toPage, imageUrl]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing || event.key === "Process") {
      if (event.key === "Enter") pendingEnterRef.current = true;
      return;
    }
    const combo = (event.ctrlKey || event.metaKey) && event.key.length === 1;
    if (!SPECIAL_KEYS.has(event.key) && !combo) return;
    if (combo && event.key.toLowerCase() === "v") return; // 붙여넣기는 onPaste 가 글자로 보낸다
    event.preventDefault();
    send([{ kind: "key", type: "down", key: event.key, code: event.code, keyCode: event.keyCode, ...mods(event) }]);
  };

  const onKeyUp = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const combo = (event.ctrlKey || event.metaKey) && event.key.length === 1;
    if (!SPECIAL_KEYS.has(event.key) && !combo) return;
    if (combo && event.key.toLowerCase() === "v") return;
    send([{ kind: "key", type: "up", key: event.key, code: event.code, keyCode: event.keyCode, ...mods(event) }]);
  };

  const flushText = (area: HTMLTextAreaElement) => {
    const text = area.value;
    area.value = "";
    if (text) send([{ kind: "text", text }]);
  };

  const onInput = (event: React.FormEvent<HTMLTextAreaElement>) => {
    if ((event.nativeEvent as InputEvent).isComposing) return;
    flushText(event.currentTarget);
  };

  const onCompositionEnd = (event: React.CompositionEvent<HTMLTextAreaElement>) => {
    flushText(event.currentTarget);
    if (pendingEnterRef.current) {
      pendingEnterRef.current = false;
      send([
        { kind: "key", type: "down", key: "Enter", code: "Enter", keyCode: 13 },
        { kind: "key", type: "up", key: "Enter", code: "Enter", keyCode: 13 },
      ]);
    }
  };

  const onPaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    event.preventDefault();
    const text = event.clipboardData.getData("text");
    if (text) send([{ kind: "text", text }]);
  };

  /** 크롬 화면(0..1) 좌표 → 무대 안 픽셀. 그림은 비율을 지키며 들어가서 위아래·양옆에 여백이 있다. */
  const pageToBox = (x: number, y: number): { left: number; top: number; scale: number } | null => {
    const img = imgRef.current;
    const box = boxRef.current;
    if (!img || !box || !img.naturalWidth) return null;
    const scale = Math.min(box.clientWidth / img.naturalWidth, box.clientHeight / img.naturalHeight);
    const width = img.naturalWidth * scale;
    const offsetX = (box.clientWidth - width) / 2;
    return { left: offsetX + x * width, top: y * img.naturalHeight * scale, scale };
  };

  const pickOption = (index: number) => {
    setSelectMenu(null);
    send([{ kind: "select", index }]);
  };

  const go = (action: "back" | "forward" | "reload" | "stop") => {
    tookAtRef.current = Date.now();
    setControl(true);
    void client?.liveNav(action).catch(() => null);
  };

  const submitAddress = () => {
    const value = address.trim();
    setEditingAddress(false);
    keysRef.current?.focus({ preventScroll: true });
    if (!value) return;
    tookAtRef.current = Date.now();
    setControl(true);
    void client?.liveNav("go", value).catch(() => null);
  };

  const switchTab = (id: string) => {
    tookAtRef.current = Date.now();
    setControl(true);
    void client?.liveTab("switch", id).catch(() => null);
  };

  const newTab = () => {
    tookAtRef.current = Date.now();
    setControl(true);
    void client?.liveTab("new").catch(() => null);
  };

  const answerDialog = (accept: boolean) => {
    if (nav?.dialog?.at) answeredRef.current.add(nav.dialog.at);
    void client?.liveDialog(accept, promptText).catch(() => null);
    setNav((current) => (current ? { ...current, dialog: null } : current));
  };

  const chooseFiles = async () => {
    if (nav?.file_chooser?.at) answeredRef.current.add(nav.file_chooser.at);
    const multiple = nav?.file_chooser?.mode === "selectMultiple";
    const paths = isTauri() ? await invoke<string[]>("pick_upload_files", { multiple }).catch(() => [] as string[]) : [];
    await client?.liveFiles(paths).catch(() => null);
    setNav((current) => (current ? { ...current, file_chooser: null } : current));
  };

  const handBack = () => {
    tookAtRef.current = 0;
    setControl(false);
    void client?.liveControl("release", "button").catch(() => null);
  };

  const showRealChrome = () => {
    void client?.showBrowser().catch(() => null);
  };

  if (!streaming && imageUrl && props.holdLastFrame) {
    // ★ 2026-09-30 대표 스크린샷: 작은 창이 「화면을 준비하는 중입니다」 한 줄로만 남았다. 페이지가 뒤쪽 탭으로 가거나(no_frames)
    //   판이 끝나 스트림이 멈추면 큰 화면은 예전 스크린샷으로 돌아가지만, 작은 창에는 돌아갈 화면이 없다. 받은 마지막 장을 둔다.
    return (
      <div className={`live-stage held${props.compact ? " strip" : ""}${stage ? " big" : ""}`}>
        <div className="live-stage-screen">
          <img src={imageUrl} alt={t("Sonjari 브라우저의 마지막 화면")} />
          <p className="live-stage-caption live-stage-held">{t("잠시 멈춤 · 마지막으로 받은 화면")}</p>
        </div>
      </div>
    );
  }
  if (!streaming || !imageUrl) return <>{props.fallback}</>;

  const shownUrl = nav?.url || pageUrl;
  const tabs = nav?.tabs ?? [];
  const menuAt = selectMenu ? pageToBox(selectMenu.rect.x, selectMenu.rect.y + selectMenu.rect.h) : null;
  const fresh = <T extends { at?: number }>(item: T | null | undefined): T | null =>
    item && !(item.at && answeredRef.current.has(item.at)) ? item : null;
  const dialog = control ? fresh(nav?.dialog) : null;
  const chooser = control ? fresh(nav?.file_chooser) : null;

  return (
    <div className={`live-stage${control ? " controlling" : ""}${props.compact ? " strip" : ""}${stage ? " big" : ""}`}>
      {/* 키보드 받는 칸은 무대 **맨 위**에 둔다 — 글자를 칠 때 브라우저가 이 칸을 보이게 스크롤하는데, 화면 아래에 두었더니
          표시줄(「직접 조작 중」)이 위로 밀려 사라졌다(이 PC 실측). */}
      <textarea
        ref={keysRef}
        className="live-stage-keys"
        aria-label={t("크롬에 입력")}
        autoComplete="off"
        spellCheck={false}
        onKeyDown={onKeyDown}
        onKeyUp={onKeyUp}
        onInput={onInput}
        onCompositionEnd={onCompositionEnd}
        onPaste={onPaste}
      />
      <div className="live-browser">
        {tabs.length > 0 && (
          <div className="live-tabs" role="tablist" aria-label={t("Sonjari 크롬 탭")}>
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={tab.id === nav?.viewing}
                className={`live-tab${tab.id === nav?.viewing ? " on" : ""}`}
                title={tab.url}
                onClick={() => { if (tab.id !== nav?.viewing) switchTab(tab.id); }}
              >
                {tab.agent && <span className="live-tab-agent" aria-label={t("Sonjari가 일하는 탭")} />}
                <span className="live-tab-title">{tab.title || shortUrl(tab.url) || t("새 탭")}</span>
              </button>
            ))}
            <button type="button" className="live-tab-new" onClick={newTab} aria-label={t("새 탭")} title={t("새 탭")}><Plus size={13} /></button>
          </div>
        )}
        <div className="live-toolbar">
          <button type="button" className="live-nav" onClick={() => go("back")} disabled={!nav?.can_back} aria-label={t("뒤로")} title={t("뒤로")}><ArrowLeft size={15} /></button>
          <button type="button" className="live-nav" onClick={() => go("forward")} disabled={!nav?.can_forward} aria-label={t("앞으로")} title={t("앞으로")}><ArrowRight size={15} /></button>
          <button type="button" className="live-nav" onClick={() => go(nav?.loading ? "stop" : "reload")} aria-label={nav?.loading ? t("멈추기") : t("새로고침")} title={nav?.loading ? t("멈추기") : t("새로고침")}>
            {nav?.loading ? <X size={15} /> : <RotateCw size={14} />}
          </button>
          <form className="live-address" onSubmit={(event) => { event.preventDefault(); submitAddress(); }}>
            {shownUrl.startsWith("https://") && !editingAddress && <Lock size={11} aria-hidden />}
            <input
              aria-label={t("주소")}
              value={editingAddress ? address : shownUrl}
              placeholder={t("주소나 검색어를 입력하세요")}
              spellCheck={false}
              onFocus={(event) => {
                setAddress(shownUrl);
                setEditingAddress(true);
                tookAtRef.current = Date.now();
                setControl(true);
                void client?.liveControl("take").catch(() => null);
                window.requestAnimationFrame(() => event.target.select());
              }}
              onChange={(event) => setAddress(event.target.value)}
              onBlur={() => setEditingAddress(false)}
              onKeyDown={(event) => { if (event.key === "Escape") { setEditingAddress(false); event.currentTarget.blur(); } }}
            />
          </form>
          <button type="button" className="live-nav" onClick={showRealChrome} aria-label={t("진짜 크롬으로 보기")} title={t("이 화면으로 안 되는 일은 진짜 크롬 창에서 하세요")}>
            <AppWindow size={15} />
          </button>
        </div>
        <div className={`live-progress${nav?.loading ? " on" : ""}`} aria-hidden />
      </div>
      {control && (
        <div className="live-stage-bar">
          <span className="live-stage-state"><Hand size={13} /> {t("직접 조작 중 · Sonjari는 기다립니다")}</span>
          {releaseIn > 0 && releaseIn < 60 && <em>{Math.round(releaseIn)}{t("초 뒤 Sonjari에게 돌려줍니다")}</em>}
          <button type="button" className="live-stage-primary" onClick={handBack}><Undo2 size={13} /> {t("Sonjari에게 돌려주기")}</button>
        </div>
      )}
      <div
        ref={boxRef}
        className="live-stage-screen"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerEnter={() => setHover(true)}
        onPointerLeave={() => setHover(false)}
        onContextMenu={(event) => event.preventDefault()}
      >
        <img ref={imgRef} src={imageUrl} alt={shownUrl ? t("{0} 화면", shortUrl(shownUrl)) : t("Sonjari가 보고 있는 화면")} draggable={false} />
        {!control && hover && <span className="live-stage-hint"><Hand size={12} /> {t("눌러서 직접 조작")}</span>}
        {!control && props.caption && <p className="live-stage-caption">{props.caption}</p>}
        {selectMenu && menuAt && (
          <div
            className="live-select"
            role="listbox"
            style={{ left: menuAt.left, top: menuAt.top + 2, minWidth: Math.max(140, selectMenu.rect.w * (imgRef.current?.naturalWidth ?? 0) * menuAt.scale) }}
            onPointerDown={(event) => event.stopPropagation()}
          >
            {selectMenu.options.map((option, index) => (
              <button
                key={`${index}:${option.text}`}
                type="button"
                role="option"
                aria-selected={index === selectMenu.selected}
                disabled={option.disabled}
                className={index === selectMenu.selected ? "on" : ""}
                onClick={() => pickOption(index)}
              >
                {option.text || "\u00a0"}
              </button>
            ))}
          </div>
        )}
        {(dialog || chooser) && (
          <div className="live-modal" onPointerDown={(event) => event.stopPropagation()}>
            {dialog ? (
              <div className="live-modal-card" role="alertdialog" aria-label={t("페이지 알림")}>
                <small>{shortUrl(shownUrl) || t("이 페이지")} {t("의 알림")}</small>
                <p>{dialog.message}</p>
                {dialog.type === "prompt" && (
                  <input value={promptText} onChange={(event) => setPromptText(event.target.value)} autoFocus />
                )}
                <div className="live-modal-actions">
                  {dialog.type !== "alert" && <button type="button" onClick={() => answerDialog(false)}>{t("취소")}</button>}
                  <button type="button" className="live-stage-primary" onClick={() => answerDialog(true)}>{t("확인")}</button>
                </div>
              </div>
            ) : chooser ? (
              <div className="live-modal-card" role="dialog" aria-label={t("파일 올리기")}>
                <small>{shortUrl(shownUrl) || t("이 페이지")}</small>
                <p>{t("이 페이지가 파일을 달라고 합니다.")}</p>
                <div className="live-modal-actions">
                  <button type="button" onClick={() => {
                    if (chooser.at) answeredRef.current.add(chooser.at);
                    void client?.liveFiles([]).then(() => setNav((c) => (c ? { ...c, file_chooser: null } : c)));
                  }}>{t("취소")}</button>
                  <button type="button" className="live-stage-primary" onClick={() => void chooseFiles()}><FileUp size={13} /> {t("파일 고르기")}</button>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

export default LiveStage;
