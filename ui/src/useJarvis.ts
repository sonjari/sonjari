import { t } from "./i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { isTauri, JarvisClient, loadBootstrap, setNativeHudMode } from "./backend";
import { applyStateSnapshot, initialHudModel, reduceJarvisEvent } from "./hudMachine";
import type { HudModel, JarvisEvent, JarvisState } from "./types";

// Approval `arguments` for these tools only ever carry {action_id} -- the
// human-readable preview must be fetched separately from
// /v1/external-actions/{action_id} once the approval_requested event lands.
const COMMIT_TOOL_NAMES = new Set([
  "google_gmail_send",
  "google_calendar_create",
  "google_drive_write",
  "google_calendar_update",
  "google_calendar_delete",
  "naver_blog_save_draft",
  "naver_blog_publish",
]);

function previewModel(): HudModel {
  const preview = new URLSearchParams(window.location.search).get("preview");
  if (preview === "panel") {
    return {
      ...initialHudModel,
      mode: "panel",
      state: "speaking",
      connected: true,
      presentation: {
        mode: "hybrid",
        spoken_text: t("핵심은 짧게 말씀드리고, 자세한 분석은 화면에 정리했어요."),
        display_title: t("사무실 Sonjari 1차 분석"),
        display_content: t("## 지금 확인한 내용\n\nPocket 3 영상은 **RTX 2070의 경량 YOLO**가 사람만 감지합니다. 대화와 도구 선택은 로컬 Gemma가 담당합니다.\n\n- 짧은 대답은 F1 음성으로 바로 전달\n- 긴 조사와 표는 이 패널에서 확인\n- 위험 작업은 화면에서만 승인\n- 카메라 영상은 사무실 PC 안에서 처리\n\n> 평소에는 작은 오브로 머물고, 필요할 때만 조용히 확장됩니다.\n\n| 상태 | 표현 |\n|---|---|\n| 듣기 | 인디고 수신 링 |\n| 생각 | 보라·핑크 오로라 |\n| 말하기 | 부드러운 음성 파형 |"),
        estimated_full_speech_sec: 31,
        reasons: ["long_list", "table"],
      },
      approval: null,
      error: "",
    };
  }
  if (preview === "approval") {
    return {
      ...initialHudModel,
      mode: "approval",
      state: "waiting_approval",
      connected: true,
      approval: {
        nonce: "preview",
        tool_name: "send_email",
        arguments: { to: t("담당자"), subject: t("조사 결과 공유") },
        expires_at: Date.now() / 1000 + 300,
      },
    };
  }
  return initialHudModel;
}

export function useJarvis() {
  const [model, setModel] = useState<HudModel>(previewModel);
  const [busy, setBusy] = useState(false);
  const clientRef = useRef<JarvisClient | null>(null);
  const collapseTimer = useRef<number>();

  useEffect(() => {
    if (new URLSearchParams(window.location.search).has("preview")) return;
    let active = true;
    loadBootstrap()
      .then(async (bootstrap) => {
        if (!active) return;
        const onEvent = (event: JarvisEvent) => {
          setModel((current) => reduceJarvisEvent(current, event));
          if (event.event !== "approval_requested") return;
          const requestPayload = event.payload ?? {};
          const toolName = String(requestPayload.tool_name ?? "");
          const args = (requestPayload.arguments ?? {}) as Record<string, unknown>;
          const actionId = String(args.action_id ?? "");
          if (!actionId || !COMMIT_TOOL_NAMES.has(toolName)) return;
          clientRef.current
            ?.getExternalAction(actionId)
            .then((preview) => {
              setModel((current) =>
                reduceJarvisEvent(current, {
                  event: "external_action_preview_loaded",
                  payload: preview as unknown as Record<string, unknown>,
                }),
              );
            })
            .catch(() => {
              // ApprovalPanel falls back to the raw arguments view when no
              // preview loads -- a failed fetch here must not block approval.
            });
        };
        const resyncState = () => {
          // State only ever arrives as an event, so any gap in the socket left
          // the orb showing a state the backend had long since left -- stuck on
          // "working", it stops accepting presses entirely.
          clientRef.current
            ?.getState()
            .then((snapshot) => {
              // 성공한 왕복이 지난 에러를 지운다 — `applyStateSnapshot` 참고.
              if (active) {
                setModel((current) =>
                  applyStateSnapshot(current, snapshot.state as JarvisState),
                );
              }
            })
            .catch(() => undefined);
        };
        const client = new JarvisClient(bootstrap, onEvent, (connected) => {
          setModel((current) => ({ ...current, connected }));
          if (connected) resyncState();
        });
        clientRef.current = client;
        try {
          const snapshot = await client.getState();
          if (active) {
            setModel((current) => ({ ...current, state: snapshot.state as JarvisState }));
          }
        } catch (error) {
          if (active) setModel((current) => ({ ...current, error: String(error) }));
        }
        client.connect();
      })
      .catch((error) => setModel((current) => ({ ...current, error: String(error) })));

    return () => {
      active = false;
      window.clearTimeout(collapseTimer.current);
      clientRef.current?.disconnect();
    };
  }, []);

  useEffect(() => {
    window.clearTimeout(collapseTimer.current);
    if (model.mode === "orb") {
      collapseTimer.current = window.setTimeout(() => void setNativeHudMode("orb"), 280);
    } else {
      void setNativeHudMode(model.mode);
    }
  }, [model.mode]);

  const togglePtt = useCallback(async () => {
    const client = clientRef.current;
    if (!client || busy) return;
    setBusy(true);
    try {
      await client.togglePtt();
    } catch (error) {
      // A press that the backend refused means the two disagree about the
      // state -- take the backend's answer rather than leaving a wrong one on
      // screen, since a wrong "working" makes the orb unpressable.
      setModel((current) => ({ ...current, state: "error", error: String(error) }));
      await client
        .getState()
        .then((snapshot) =>
          setModel((current) => applyStateSnapshot(current, snapshot.state as JarvisState)),
        )
        .catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }, [busy]);

  const sendChat = useCallback(async (prompt: string) => {
    if (!prompt.trim()) return;
    if (!clientRef.current) throw new Error(t("Sonjari 연결을 준비하고 있습니다. 잠시 후 다시 시도해주세요."));
    setBusy(true);
    try {
      const job = await clientRef.current.sendChat(prompt.trim());
      setModel((current) => ({
        ...current,
        mode: "panel",
        presentation: {
          mode: "screen",
          spoken_text: "",
          display_title: t("Sonjari 작업 중"),
          display_content: "",
        },
        activeJobId: job.id,
        continuation: null,
        streamingContent: "",
        thinking: false,
        progress: [{
          key: `${job.id}:queued`,
          jobId: job.id,
          phase: "queued",
          message: t("요청을 실행 대기열에 등록했습니다"),
          step: 0,
          tool: "",
          status: "running",
        }],
        state: "working",
        error: "",
      }));
    } catch (error) {
      setModel((current) => ({ ...current, state: "error", error: String(error) }));
      throw error;
    } finally {
      setBusy(false);
    }
  }, []);

  const cancelActiveJob = useCallback(async () => {
    const jobId = model.activeJobId;
    if (!clientRef.current || !jobId) return;
    setBusy(true);
    try {
      await clientRef.current.cancelJob(jobId);
      setModel((current) => ({
        ...current,
        activeJobId: "",
        state: "idle",
        progress: current.progress.map((item) =>
          item.status === "running" ? { ...item, status: "cancelled" } : item,
        ),
      }));
    } catch (error) {
      setModel((current) => ({ ...current, error: String(error) }));
    } finally {
      setBusy(false);
    }
  }, [model.activeJobId]);

  const continueAgent = useCallback(async (action: "extend_3m" | "continue_task" | "finish") => {
    const jobId = model.continuation?.job_id || model.activeJobId;
    if (!clientRef.current || !jobId) return;
    setBusy(true);
    try {
      await clientRef.current.continueAgent(jobId, action);
      setModel((current) => ({
        ...current,
        mode: "panel",
        state: "working",
        continuation: null,
        activeJobId: jobId,
        progress: [
          ...current.progress,
          {
            key: `${jobId}:continuation:${action}`,
            jobId,
            phase: "continuation",
            message: action === "finish" ? t("현재까지 확인한 내용으로 정리합니다") : t("저장한 지점부터 작업을 계속합니다"),
            step: 0,
            tool: "",
            status: "running" as const,
          },
        ].slice(-12),
        error: "",
      }));
    } catch (error) {
      setModel((current) => ({ ...current, error: String(error) }));
    } finally {
      setBusy(false);
    }
  }, [model.activeJobId, model.continuation?.job_id]);

  const decideApproval = useCallback(async (approve: boolean, answer?: string) => {
    const nonce = model.approval?.nonce;
    if (!clientRef.current || !nonce) return;
    setBusy(true);
    try {
      await clientRef.current.decideApproval(nonce, approve, answer);
      setModel((current) => ({ ...current, mode: "orb", approval: null, approvalPreview: null, state: "idle" }));
    } catch (error) {
      setModel((current) => ({ ...current, state: "error", error: String(error) }));
    } finally {
      setBusy(false);
    }
  }, [model.approval?.nonce]);

  const collapse = useCallback(() => {
    setModel((current) => ({ ...current, mode: "orb", presentation: null, error: "" }));
  }, []);

  // 확인 요청은 사람에게 알리기만 한다 — 백엔드에 되돌려 줄 결정이 없다. 작업은
  // 기다리지 않고 이어서 돌고 있고, 여기서 하는 일은 카드를 치우는 것뿐이다.
  const dismissAttention = useCallback(() => {
    setModel((current) => reduceJarvisEvent(current, { event: "attention_cleared" }));
  }, []);

  return { model, busy, togglePtt, sendChat, cancelActiveJob, continueAgent, decideApproval, collapse, dismissAttention };
}
