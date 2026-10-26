/**
 * 원래 클라이언트(서버 · 리허설)에 **Claude 갈래**를 덧씌운다 (2026-10-26).
 *
 * 화면의 모든 자리(대화 칸 · 사이드바 · 컴퓨터 칸 · 눈금자 · 만든 것)는 클라이언트 메서드로만 읽는다. 그래서 메서드 몇 개만
 * 「클로드 판이면 갈래로」 갈라 주면, 화면은 한 줄도 갈래를 몰라도 같은 흐름을 그린다(ADR 고침 3 「앱 하나 · 흐름 하나」).
 *
 * - 보내기: 그 대화의 두뇌(`brain.ts`)가 Claude Agent 면 갈래로, 아니면 원래 길(지금 그대로).
 * - 대화 기록 · 목록 · 일감: 서버 것과 갈래 것을 시각 순으로 합친다(한 대화 안에서 두뇌를 바꿔도 한 줄로 이어진다).
 * - 판 번호가 `claude-` 로 시작하면 걸음 · 만든 것 · 멈춤을 갈래가 답한다.
 */
import { t } from "../i18n";
import type { JarvisClient } from "../backend";
import type { ConversationHistory, ConversationSummary, JobSummary } from "../types";
import { brainFor, isClaudeBrain } from "./brain";
import type { ClaudeLane } from "./lane";

export function withClaudeLane<T extends JarvisClient>(client: T, lane: ClaudeLane): T {
  const base = {
    sendChat: client.sendChat.bind(client),
    getConversations: client.getConversations.bind(client),
    getConversation: client.getConversation.bind(client),
    deleteConversation: client.deleteConversation.bind(client),
    listJobs: client.listJobs.bind(client),
    getJob: client.getJob.bind(client),
    listSteps: client.listSteps.bind(client),
    getStep: client.getStep.bind(client),
    cancelJob: client.cancelJob.bind(client),
    listOutputs: client.listOutputs.bind(client),
    fetchOutput: client.fetchOutput.bind(client),
    previewOutput: client.previewOutput.bind(client),
    steerJob: client.steerJob.bind(client),
    slidesAnswer: client.slidesAnswer?.bind(client),
    slidesPhoto: client.slidesPhoto?.bind(client),
  };
  // 대화의 첫 답이 끝나면 내 PC 모델에게 제목을 짓게 한다 — 본체가 손자리가 쉴 때 뒤에서 짓고 `conversation_titled` 로 알린다.
  if (!lane.onFirstAnswer) {
    lane.onFirstAnswer = (sessionId, prompt, answer) => {
      void client.nameConversation(sessionId, prompt, answer).catch(() => undefined);
    };
  }
  if (!lane.local) {
    lane.local = {
      listSteps: base.listSteps, getStep: base.getStep, listOutputs: base.listOutputs, cancelJob: base.cancelJob,
    };
  }

  const serverHistory = async (sessionId: string, limit?: number): Promise<ConversationHistory> => {
    try {
      return await base.getConversation(sessionId, limit);
    } catch {
      // 클로드와만 말한 대화는 서버에 없다 — 빈 기록에서 갈래 것을 얹는다.
      return { session_id: sessionId, summary: "", has_summary: false, messages: [] };
    }
  };

  const merged = async (sessionId: string, limit?: number): Promise<ConversationHistory> => {
    const server = await serverHistory(sessionId, limit);
    const extra = lane.messages(sessionId);
    if (!extra.length) return server;
    const messages = [...server.messages, ...extra].sort((a, b) => a.created_at - b.created_at || a.id - b.id);
    return { ...server, messages: limit ? messages.slice(-limit) : messages };
  };

  Object.assign(client, {
    async sendChat(...args: Parameters<JarvisClient["sendChat"]>) {
      const [prompt, sessionId = "", attachments = [], , , workspaceMode = "cowork", codeWorkspace = "", , , reasoning = ""] = args;
      const brain = brainFor(sessionId);
      if (!isClaudeBrain(brain)) return base.sendChat(...args);
      const history = await merged(sessionId);
      // 손자리 권한 메뉴 · 생각 깊이 칩을 그대로 Claude 에 넘긴다(2026-10-26 대표: 「클로드 앱 권한처럼」).
      const permissionMode = await client.permissionMode().then((modes) => String(modes?.mode ?? "")).catch(() => "");
      return lane.send({
        prompt, sessionId, attachments, workspaceMode, codeWorkspace, model: brain, history: history.messages,
        permissionMode, effort: String(reasoning ?? ""),
      });
    },
    async getConversations(limit = 50): Promise<ConversationSummary[]> {
      const [rows, titles] = await Promise.all([
        base.getConversations(limit).catch(() => [] as ConversationSummary[]),
        client.conversationTitles().then((value) => value.items ?? {}).catch(() => ({} as Record<string, { title: string; source: string }>)),
      ]);
      // ★ 앱 안 Claude 가 맡긴 손자리 판의 방은 따로 세우지 않는다 (2026-10-26 대표: 「Claude Code…」 주황 방이 목록에 늘어났다).
      //   그 판은 맡긴 Claude 대화의 맡김 카드 · 눈금자에서 보인다. 서버는 via=app 방을 빼고 주지만, 그 칸이 생기기 전 기록은
      //   갈래가 아는 「이 Claude 판이 맡긴 판 번호」로 알아본다.
      const visible = rows.filter((row) => row.via !== "app" && !(row.job_id && lane.claudeJobOf(row.job_id)));
      const byId = new Map(visible.map((row) => [row.session_id, { ...row }]));
      for (const listed of lane.sessions()) {
        // 내 PC 모델이 지은 제목(본체에 저장) — Claude 와만 말한 대화도 같은 제목을 받는다.
        const named = titles[listed.session_id];
        const extra = named?.title ? { ...listed, title: named.title, title_source: named.source } : listed;
        const found = byId.get(extra.session_id);
        if (!found) byId.set(extra.session_id, extra);
        else {
          found.message_count += extra.message_count;
          if (named?.title) Object.assign(found, { title: named.title, title_source: named.source });
          if (extra.updated_at > found.updated_at) Object.assign(found, { updated_at: extra.updated_at, preview: extra.preview });
        }
      }
      return [...byId.values()].sort((a, b) => b.updated_at - a.updated_at).slice(0, limit);
    },
    getConversation: merged,
    async deleteConversation(sessionId: string) {
      const had = lane.messages(sessionId).length > 0;
      lane.deleteSession(sessionId);
      try {
        return await base.deleteConversation(sessionId);
      } catch (reason) {
        if (had) return { ok: true };
        throw reason;
      }
    },
    async listJobs(limit = 40): Promise<JobSummary[]> {
      const rows = await base.listJobs(limit);
      return [...lane.jobs(), ...rows].sort((a, b) => b.created_at - a.created_at).slice(0, limit);
    },
    async getJob(jobId: string) {
      return lane.owns(jobId) ? lane.getJob(jobId) : base.getJob(jobId);
    },
    async listSteps(jobId: string) {
      return lane.owns(jobId) ? lane.listSteps(jobId) : base.listSteps(jobId);
    },
    async getStep(jobId: string, step: number) {
      return lane.owns(jobId) ? lane.getStep(jobId, step) : base.getStep(jobId, step);
    },
    async cancelJob(jobId: string) {
      return lane.owns(jobId) ? lane.cancel(jobId) : base.cancelJob(jobId);
    },
    async listOutputs(jobId: string) {
      return lane.owns(jobId) ? lane.listOutputs(jobId) : base.listOutputs(jobId);
    },
    async fetchOutput(jobId: string, path: string) {
      return base.fetchOutput(lane.owns(jobId) ? await lane.ownerOf(jobId, path) : jobId, path);
    },
    async previewOutput(jobId: string, path: string) {
      return base.previewOutput(lane.owns(jobId) ? await lane.ownerOf(jobId, path) : jobId, path);
    },
    // ★ 2026-10-26 첫 실제 판: 장표 사건은 클로드 판 번호로 옮겨 보이는데, 결을 누르면 그 클로드 번호로 답을 보내
    //   손자리 본체(자기 판 번호만 기다림)가 못 받았다 — 결을 못 골랐다. 장표를 그리는 손자리 판 번호로 되돌려 보낸다.
    async slidesAnswer(jobId: string, title: string, kind: string, value?: unknown) {
      return base.slidesAnswer!(lane.owns(jobId) ? lane.deckJobOf(jobId) || jobId : jobId, title, kind, value);
    },
    async slidesPhoto(jobId: string, title: string, index: number, slot: string, data: string) {
      return base.slidesPhoto!(lane.owns(jobId) ? lane.deckJobOf(jobId) || jobId : jobId, title, index, slot, data);
    },
    async steerJob(jobId: string, text: string) {
      // 클로드는 한 판을 받으면 끝까지 간다(입력을 닫고 띄운다) — 덧붙인 말은 다음 판으로 간다(화면이 그 길로 보낸다).
      if (lane.owns(jobId)) throw new Error(t("Claude Agent 가 일하는 중에는 말을 덧붙일 수 없습니다 — 다음 말로 보냅니다."));
      return base.steerJob(jobId, text);
    },
  });
  return client;
}
