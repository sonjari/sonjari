import { t } from "../i18n";
/**
 * 작업 화면에서 「지금 부탁해도 되는가」 (F2, 2026-09-15 제품 흐름 지도 G2).
 *
 * 첫 실행에서 모델을 「나중에 고르기」로 넘기거나, 그래픽카드가 없거나, Ollama 가 꺼져 있으면
 * 첫 부탁이 한참 돌다 오류로 끝났다 — 화면은 아무것도 말하지 않았다. `/health` 가 이미 아는 것을
 * 부탁하기 **전에** 말한다. 판정은 백엔드 값만 읽는다(화면이 추측하지 않는다).
 *
 * ★ 2026-09-20 노트북: 앱을 켜면 Ollama 가 뜨기까지 14초가 걸렸고, 그 사이 「닿지 않습니다」가 떴다.
 *   백엔드가 이제 꺼진 Ollama 를 알아서 켜고 `starting` 을 알려 준다 — 켜는 중은 고장이 아니다.
 */
export interface HealthOllama {
  ok: boolean;
  model?: string;
  model_available?: boolean;
  error?: string;
  /** 백엔드가 지금 Ollama 를 켜는 중(`OllamaKeeper`). */
  starting?: boolean;
  /** 켜기가 연달아 실패했을 때의 이유. */
  autostart_error?: string;
  /** **능력 실측** — 메모리 실측과 다른 칸이다(2026-09-20). 백엔드 `model_catalog.agent_grade`. */
  agent_grade?: AgentGrade;
  /** 지금 이 모델이 **실제로 올라가 있나**. */
  resident?: boolean;
  /** ★ Ollama `/api/ps` 가 말한 **실제로 올라간 컨텍스트**(2026-09-21).
   *  설정값이 아니라 이것이 진실이다 — 설정을 고쳐도 러너가 옛 값으로 떠 있으면
   *  화면이 거짓말한다. 머리의 「128K」는 이 값에서 온다. */
  context_length?: number;
}

export interface AgentGrade {
  model: string;
  /** 사슬 벤치를 돌렸고 합격선을 넘었는가. 안 잰 모델은 `false` — 「나쁘다」가 아니라 **모른다**. */
  measured: boolean;
  chain?: { ok: number; total: number; ctx?: number | null } | null;
  label: string;
  detail: string;
}

/**
 * 「권한을 여는 자리」에서 띄울 한 줄. 잰 모델이면 null(조용히 지나간다).
 *
 * 사장님 지시(2026-09-20): "벤치에서 검증된 애들만 권한을 틀어 주는 게 어떤가. 4B 로 그렇게 해
 * 버리면 진짜 큰일난다." 막는 것은 **쓰기 확장 하나**이고(백엔드), 나머지는 여기서 경고로 말한다.
 */
export function modelCaution(grade: AgentGrade | null | undefined): string | null {
  if (!grade || grade.measured) return null;
  return t("지금 모델({0})은 Sonjari가 능력을 잰 적이 없습니다 — {1}", grade.model, grade.detail);
}

export interface ReadinessProblem {
  kind: "ollama_down" | "ollama_starting" | "model_missing";
  title: string;
  detail: string;
  /** 없으면 누를 것이 없다(저절로 풀린다). */
  action?: string;
}

export function readinessProblem(ollama: HealthOllama | null | undefined): ReadinessProblem | null {
  if (!ollama) return null;
  if (!ollama.ok && ollama.starting) {
    return {
      kind: "ollama_starting",
      title: t("로컬 AI 엔진을 켜는 중입니다"),
      detail: t("켜지면 이 안내는 저절로 사라집니다."),
    };
  }
  if (!ollama.ok) {
    return {
      kind: "ollama_down",
      title: t("로컬 AI 엔진(Ollama)을 켜지 못했습니다"),
      detail: ollama.autostart_error
        ? t("여러 번 켜 보았지만 켜지지 않았습니다. 첫 실행 화면에서 엔진을 고치거나 다시 설치할 수 있습니다.")
        : t("엔진이 켜져 있지 않고, Sonjari가 직접 켤 수 있는 엔진도 이 PC 에 없습니다. 첫 실행 화면에서 설치할 수 있습니다."),
      action: t("엔진 확인하기"),
    };
  }
  if (ollama.model_available === false) {
    return {
      kind: "model_missing",
      title: t("대화 모델이 이 PC 에 없습니다"),
      detail: t("설정된 모델({0})을 아직 받지 않았습니다. 이 PC 에 맞는 모델을 고르면 받아서 확인한 뒤 적용합니다.", ollama.model ?? t("알 수 없음")),
      action: t("모델 고르기"),
    };
  }
  return null;
}
