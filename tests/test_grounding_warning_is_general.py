from alture_jarvis.agent import BrowserAgent


def test_model_recommendation_warning_describes_missing_evidence_without_job_fields():
    answer = '| 모델 | 용도 |\n|---|---|\n| **추천모델알파** | 대화 |\n| **추천모델베타** | 코드 |'
    warning = BrowserAgent._listed_entity_grounding_check(
        answer, [{'role': 'tool', 'content': '직접 읽은 모델은 기준모델감마뿐입니다.'}])
    assert '추천모델알파' in warning and '추천모델베타' in warning
    assert '고용형태' not in warning and '경력' not in warning and '마감' not in warning
    assert '확인' in warning
