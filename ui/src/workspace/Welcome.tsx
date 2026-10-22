import { t } from "../i18n";
import { Bug, FolderCode, FolderOpen, Globe, ScanSearch, Table2 } from "lucide-react";
import type { WorkspaceMode } from "../types";
import type { ReactNode } from "react";

/**
 * 대화가 하나도 없을 때. 빈 화면은 무엇을 하라는 초대여야 한다.
 *
 * ## 왜 이 세 개인가 (2026-08-23)
 *
 * 그 전에는 "오늘 우선순위를 정리해줘" 같은 것이 있었다. **어느 AI 제품에나 있는
 * 그 카드**다 — 이 제품이 아니어도 되는 문장이라, 첫 화면이 무엇을 잘하는지
 * 아무것도 말하지 않았다.
 *
 * 이제 셋은 **이 제품만 정직하게 제안할 수 있는 것**이다. 셋 다 같은 날 실측으로
 * 확인한 일이다:
 *
 *     웹 조사    레시피가 없는 처음 보는 사이트에서도 정확했다(무신사·YES24 대조 완료)
 *     내 파일    상자에 넣어 계산하고 새 파일로 내보내는 길이 그날 뚫렸다
 *     우리 데이터 입시 DB 를 직접 조회한다 — 남이 못 따라오는 자리
 *
 * 세 갈래를 고른 것도 뜻이 있다. **밖 · 내 컴퓨터 · 우리 원천** — 자비스가 손을
 * 뻗는 곳이 셋뿐이고, 첫 화면이 그 지도를 그대로 보여 준다.
 */
const SUGGESTIONS = [
  {
    icon: Globe,
    label: t("웹에서 찾기"),
    text: t("다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘"),
  },
  {
    icon: Table2,
    label: t("내 파일 다루기"),
    text: t("이 엑셀 읽고 반별 평균을 내서 새 파일로 저장해줘"),
  },
  {
    // ★ 2026-09-17: 「우리 데이터 · 중앙대 경쟁률」은 만든 회사의 사내 데이터 예시라 설치한 사람에겐 뜻이 없다.
    icon: FolderOpen,
    label: t("문서로 만들기"),
    text: t("사람인에서 여수 회계 채용 공고 3개를 찾아 비교표 문서로 만들어줘"),
  },
];

const CODE_SUGGESTIONS = [
  { icon: FolderCode, label: t("화면 만들기"), text: t("이 프로젝트의 첫 화면을 살펴보고, 사용자가 바로 눌러 볼 수 있는 핵심 흐름을 만들어줘. 실행 방법도 알려줘") },
  { icon: Bug, label: t("써 보고 고치기"), text: t("현재 제품을 실행해 주요 버튼과 화면 흐름을 확인하고, 실제로 막히는 곳을 찾아 고쳐줘") },
  { icon: ScanSearch, label: t("기존 코드 이해"), text: t("프로젝트 구조와 핵심 진입점을 읽고, 지금 제품에서 가장 먼저 확인할 화면을 알려줘") },
];

/** 태그에 적힌 크기(B) — `qwen3.5:9b` → 9. 모르면 0(백엔드 `hf_catalog.params_in_tag` 와 같은 규칙). */
export function paramsInTag(tag: string): number {
  const found = [...String(tag || "").matchAll(/(\d+(?:\.\d+)?)\s*b(?![a-z])/gi)].map((m) => Number(m[1]));
  return found.length ? Math.max(...found) : 0;
}

export function Welcome({ onSuggestion, mode = "cowork", codeWorkspace = "", codeModel = "", quests, receipt }: {
  onSuggestion: (value: string) => void;
  /** 처음 쓰는 사람의 퀘스트 판(튜토리얼) — 제안 칸보다 먼저 보인다. */
  quests?: ReactNode;
  /** 「이번 주 영수증」(2026-10-21) — 퀘스트 판 다음, 제안 칸 앞. 셀 것이 없으면 카드가 스스로 숨는다. */
  receipt?: ReactNode;
  mode?: WorkspaceMode;
  codeWorkspace?: string;
  /** 코드 탭에서 쓰는 모델 — 작으면 시작 전에 무엇을 잘하고 무엇을 클로드에게 맡길지 한 줄 알린다(§55-13 기대 맞추기 2). */
  codeModel?: string;
}) {
  const code = mode === "code";
  const size = code ? paramsInTag(codeModel) : 0;
  const small = size > 0 && size < 20;
  const suggestions = code ? CODE_SUGGESTIONS : SUGGESTIONS;
  return (
    <div className={`workspace-welcome${code ? " code-welcome" : ""}`}>
      {/* ★ 2026-09-30: 여기 있던 구슬은 HUD 마이크를 빌려 온 것이라 **누르면 아무 일도 없는 마이크**였다(onPress 가 비어 있었다).
          장식이 기능처럼 생기면 거짓말이 된다 — 코드 모드의 폴더 표식과 함께 뺐다. 첫 화면은 질문으로 시작한다. */}
      <h1>{code ? t("만들고, 눌러 보고, 고칩니다") : t("무엇을 할까요?")}</h1>
      <p>{code
        ? codeWorkspace
          ? t("선택한 저장소를 읽고 화면을 만듭니다. 오른쪽에서 제품을 직접 써 보고, 이상한 점을 바로 수정 요청으로 보내세요. {0}", codeWorkspace)
          : t("위에서 프로젝트 폴더를 지정하세요. 코드를 고친 뒤 오른쪽에서 실행 화면을 직접 눌러 볼 수 있습니다.")
        : t("짧은 질문은 바로 답합니다. 조사·브라우저·문서 분석은 필요한 도구를 스스로 골라 진행하고, 새 대화에서도 최근 맥락을 이어갑니다.")}</p>
      {/* ★ 2026-10-01 베타 테스터: 9B 에게 3ds Max 앱 전체를 한 번에 시켰다가 코드가 망가졌다(정직하게 「확인 못 했다」고는 했다).
          사용자는 처음에 한 방에 크게 시킨다 — 한 방에 안 될 일은 **시작 전에** 알린다. 막지는 않는다. */}
      {small && (
        <p className="code-expect" role="note">
          {t("지금 코드 모델은")} <b>{codeModel}</b>({size}{t("B)입니다. 이 크기는 이미 있는 코드를 읽고 고치고 돌려서 확인하는 일에 맞습니다. 새 앱을 통째로 만드는 일은 클로드(Claude Code)가 더 잘합니다 — 클로드에게 짜게 하고 손자리를 같이 부르세요. 위 모델 이름을 누르면 이 PC 에 들어가는 더 큰 코드 모델을 고를 수 있습니다.")}
        </p>
      )}

      {quests}
      {receipt}
      <div className="suggestion-grid">
        {suggestions.map(({ icon: Icon, label, text }) => (
          <button key={text} onClick={() => onSuggestion(text)}>
            <span><Icon size={15} /></span>
            <u>{label}</u>
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}
