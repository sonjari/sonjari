"""모델 없는 루틴 — 사람인 목록을 레시피 주소로 받아 칸만 읽는다 (2026-10-23 · 전략안 §55-39 · §55-40 첫 칸).

표본(`tests/fixtures/routine_lists/saramin_*.html` — 폴더 이름이 `saramin…` 이면 루트 .gitignore 의 `Saramin*/` 에 걸려 커밋에서 빠진다)은 10-23 이 PC 에서 레시피 주소를 브라우저 없이 받아 잘라 낸 것이다(추적 값은 x · 개인 정보 없음).
- busan: 「연구비 관리」 · 부산(106000) → 총 10건.
- zero: 없는 검색어 → 「검색결과가 없습니다」 + 밑에 **인기 공고**(진짜 화면은 20개 · 표본은 3개). 공고 칸만 세면 0건이 20건이 된다.
- 두 표본 모두 맨 위에 자동완성 상자의 「검색결과가 없습니다」 글자와, 칸 모양을 품은 `<script>` 를 넣었다 — 글자로 0건을 가르면 걸리는 함정.

**이 시험은 진짜 네트워크에 나가지 않는다** — `urlopen` 을 막고(나가면 실패), 받기는 표본을 돌려주는 가짜로 바꿔 끼운다.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from alture_jarvis import routine
from alture_jarvis.events import EventBus
from alture_jarvis.scheduler import TaskScheduler

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "routine_lists"
RECIPES = HERE.parent / "recipes"  # 손자리에 든(저장소의) 레시피 — 사람 문서 폴더가 아니다
BUSAN = (FIXTURES / "saramin_busan_2026-10-23.html").read_text(encoding="utf-8")
ZERO = (FIXTURES / "saramin_zero_2026-10-23.html").read_text(encoding="utf-8")
SPEC = {"recipe": "saramin", "query": "연구비 관리", "region": "부산"}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a, **_k):  # noqa: ANN002, ANN003
        raise AssertionError("시험이 진짜 네트워크에 나가려 했다")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


class _Fake:
    """받기 가짜 — 불린 주소를 적어 둔다(지어낸 주소가 나가는지 볼 수 있게)."""

    def __init__(self, html: str, final: str | None = None) -> None:
        self.html, self.final, self.urls = html, final, []

    def __call__(self, url: str) -> tuple[str, str]:
        self.urls.append(url)
        return self.html, self.final or url


def _run(spec: dict, html: str = BUSAN, out: Path | None = None, final: str | None = None) -> tuple[dict, _Fake]:
    fake = _Fake(html, final)
    return routine.run_routine(spec, out, fetch=fake, recipe_dir=RECIPES), fake


# ── 칸 읽기 ──────────────────────────────────────────────────────────────────

def test_reads_every_row_with_its_columns_and_evidence(tmp_path: Path) -> None:
    out = tmp_path / "jobs.json"
    result, fake = _run(SPEC, out=out)

    assert result["status"] == "ok", result["problems"]
    assert result["count"] == 10 and result["total_on_site"] == 10, "표본 머리말 「총 10건」 · 줄 10개(직접 셈)"
    # 주소는 레시피 틀 + 레시피 표의 번호(부산=106000)에서만 나왔다.
    assert fake.urls == ["https://www.saramin.co.kr/zf_user/search/recruit?searchword=%EC%97%B0%EA%B5%AC%EB%B9%84%20%EA%B4%80%EB%A6%AC&loc_mcd=106000"]
    by_id = {job["rec_idx"]: job for job in result["jobs"]}
    assert len(by_id) == 10, "rec_idx 가 겹치지 않는다"
    job = by_id["55364189"]
    assert job["title"] == "[삼우이머션] 정부R&D연구과제사업비,행정관리 (육아휴직대체)"
    assert job["company"] == "(주)삼우이머션"
    assert job["location"] == "부산 동구"
    assert (job["career"], job["education"], job["employment_type"]) == ("경력1년↑", "초대졸↑", "기간제·계약직")
    assert job["deadline"] == "~ 12/21(월)"
    assert job["url"] == "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=55364189", "공고 주소도 레시피 job 틀에서"
    # 연봉 칸은 있는 공고에서만(표본 10번째) — 순서가 아니라 낱말로 갈랐다.
    assert [j["salary"] for j in result["jobs"] if j["salary"]] == ["7,000 만원"]
    for row in result["jobs"]:
        assert row["source_url"] == fake.urls[0] and row["fetched_at"] and row["evidence"]
        assert row["region_match"] == "yes", row["location"]
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["count"] == 10 and saved["model_used"] is False


def test_zero_is_zero_not_the_popular_jobs_underneath(tmp_path: Path) -> None:
    out = tmp_path / "jobs.json"
    result, _ = _run(SPEC, html=ZERO, out=out)

    assert result["status"] == "empty"
    assert result["count"] == 0 and result["jobs"] == [], "밑에 붙은 인기 공고(표본 3개)를 세면 안 된다"
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "empty", "0건은 0건이라고 적는다"


def test_the_no_result_text_alone_does_not_mean_zero() -> None:
    """「검색결과가 없습니다」 글자는 모든 화면의 자동완성 상자에 있다 — busan 표본에도 있다. 그래도 10건이다."""
    assert "검색결과가 없습니다" in BUSAN
    assert routine.parse_saramin_list(BUSAN)["status"] == "ok"


# ── 깨짐: 조용히 넘기지 않는다 ───────────────────────────────────────────────

@pytest.mark.parametrize(
    ("label", "old", "new", "says"),
    [
        ("조건 칸 이름이 바뀜", 'class="job_condition"', 'class="job_cond_v2"', "칸 모양이 바뀐 것 같다"),
        ("머리말이 사라짐", 'class="cnt_result"', 'class="cnt_v2"', "총 N건"),
        ("목록 자리가 사라짐", 'id="recruit_info_list"', 'id="recruit_list_v2"', "목록 자리"),
        ("회사 칸이 사라짐", 'class="corp_name"', 'class="corp_v2"', "company"),
    ],
)
def test_shape_change_is_broken_and_keeps_the_last_good_file(tmp_path: Path, label: str, old: str, new: str, says: str) -> None:
    out = tmp_path / "jobs.json"
    out.write_text('{"status": "ok", "count": 7}', encoding="utf-8")
    assert old in BUSAN, f"표본에 {old} 가 없다 — 이 시험이 낡았다"
    result, _ = _run(SPEC, html=BUSAN.replace(old, new), out=out)

    assert result["status"] == "broken", label
    assert any(says in problem for problem in result["problems"]), result["problems"]
    assert json.loads(out.read_text(encoding="utf-8")) == {"status": "ok", "count": 7}, "깨진 회차는 지난 좋은 결과를 덮지 않는다"
    assert routine.EXIT["broken"] != routine.EXIT["ok"]


def test_wrong_region_list_is_broken_not_an_answer() -> None:
    """10-04 사고 모양: 틀린 번호는 오류 대신 엉뚱한 지역 목록을 준다. 서울을 걸었는데 부산 목록이 오면 깨짐이다."""
    result, _ = _run({**SPEC, "region": "서울"})
    assert result["params"]["region_code"] == "101000"
    assert result["status"] == "broken"
    assert any("지역이 안 걸린 것 같다" in problem for problem in result["problems"])


def test_redirect_to_another_page_is_broken() -> None:
    result, _ = _run(SPEC, final="https://www.saramin.co.kr/zf_user/")
    assert result["status"] == "broken" and result["count"] == 0


def test_network_failure_is_failed_not_broken() -> None:
    def down(_url: str) -> tuple[str, str]:
        raise TimeoutError("timed out")

    result = routine.run_routine(SPEC, fetch=down, recipe_dir=RECIPES)
    assert result["status"] == "failed" and "TimeoutError" in result["problems"][0]


# ── 모르는 지역 · 지어낸 주소는 받기 전에 막힌다 ─────────────────────────────

@pytest.mark.parametrize("region", ["부산시청앞", "3", "41,42,44"])
def test_unknown_or_guessed_region_is_refused_before_fetching(region: str) -> None:
    """이름 → 번호는 레시피 표만. 10-23 손자리가 지어낸 「loc_mcd=3」 · 10-04 의 짐작 번호(41·42·44)도 여기서 멈춘다."""
    result, fake = _run({**SPEC, "region": region})
    assert result["status"] == "refused"
    assert "쓸 수 있는 이름" in result["problems"][0]
    assert fake.urls == [], "모르는 지역으로는 아무 데도 나가지 않는다"


def test_a_url_in_the_spec_is_refused() -> None:
    made_up = "https://www.saramin.co.kr/zf_user/search?searchword=연구비&loc_mcd=3"
    result, fake = _run({**SPEC, "url": made_up})
    assert result["status"] == "refused" and "레시피에서만" in result["problems"][0]
    assert fake.urls == []


def test_recipe_url_outside_its_own_hosts_is_refused(tmp_path: Path) -> None:
    data = json.loads((RECIPES / "saramin.json").read_text(encoding="utf-8"))
    data["urls"]["search_region"] = "https://evil.example/search?q={query}&r={region}"
    (tmp_path / "saramin.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    fake = _Fake(BUSAN)
    result = routine.run_routine(SPEC, fetch=fake, recipe_dir=tmp_path)
    assert result["status"] == "refused" and "hosts 밖" in result["problems"][0]
    assert fake.urls == []


def test_site_without_a_recipe_is_refused() -> None:
    result, fake = _run({**SPEC, "recipe": "jobkorea"})
    assert result["status"] == "refused" and fake.urls == []


# ── 명령 한 줄 (스토어 판은 실행 별칭) ──────────────────────────────────────

def test_command_line_runs_without_a_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    fake = _Fake(BUSAN)
    monkeypatch.setattr(routine, "http_fetch", fake)
    out = tmp_path / "jobs.json"
    code = routine.main(["run", "--recipe", "saramin", "--query", "연구비 관리", "--region", "부산",
                         "--out", str(out), "--recipe-dir", str(RECIPES)])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0 and printed["count"] == 10 and printed["model_used"] is False
    assert len(json.loads(out.read_text(encoding="utf-8"))["jobs"]) == 10


def test_command_line_has_no_door_for_a_url(capsys: pytest.CaptureFixture) -> None:
    code = routine.main(["run", "--recipe", "saramin", "--query", "x", "--url", "https://www.saramin.co.kr/zf_user/search?loc_mcd=3"])
    assert code == routine.EXIT["refused"]
    assert "--url" in capsys.readouterr().out


def test_store_build_calls_through_the_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis import mcp_connect, msix

    monkeypatch.setattr(msix, "is_packaged", lambda: True)
    monkeypatch.setattr(mcp_connect, "msix_alias_path", lambda: Path("C:/Users/x/AppData/Local/Microsoft/WindowsApps/sonjari.exe"))
    line = routine.command_line(SPEC, "C:/out/jobs.json")
    assert line.startswith('"C:/Users/x/AppData/Local/Microsoft/WindowsApps/sonjari.exe" -m alture_jarvis.routine run')
    assert '--region "부산"' in line


# ── 예약 「루틴」 종류 ───────────────────────────────────────────────────────

def _scheduler(tmp_path: Path, html: str = BUSAN, enqueued: list | None = None) -> tuple[TaskScheduler, EventBus, _Fake]:
    events = EventBus()
    fake = _Fake(html)
    config = SimpleNamespace(scheduler_enabled=True, site_recipe_dir=RECIPES, data_dir=tmp_path / "data",
                             scheduled_mail_recipients="")

    def enqueue(*args):  # noqa: ANN002
        (enqueued if enqueued is not None else []).append(args)
        return {"id": "job-should-not-exist"}

    scheduler = TaskScheduler(tmp_path / "jarvis.db", events, enqueue, config=config,
                              routine_runner=lambda spec, out: routine.run_routine(spec, out, fetch=fake, recipe_dir=RECIPES))
    return scheduler, events, fake


def _run_due(scheduler: TaskScheduler) -> None:
    time.sleep(0.15)
    row = scheduler._claim_due()
    assert row is not None, "때가 된 예약을 못 잡았다"
    scheduler._dispatch(row)


def test_routine_schedule_runs_without_a_model_and_leaves_its_result(tmp_path: Path) -> None:
    enqueued: list = []
    scheduler, events, fake = _scheduler(tmp_path, enqueued=enqueued)
    row = scheduler.create({"title": "채용 공고 모으기", "routine": SPEC, "delay_minutes": 0.001})
    assert row["kind"] == "routine" and json.loads(row["routine"]) == SPEC
    assert row["prompt"].startswith("루틴(모델 없이)")

    _run_due(scheduler)
    after = scheduler.get(row["id"])
    assert enqueued == [], "루틴은 모델 판(잡)을 만들지 않는다"
    assert after["status"] == "ran" and after["last_job_id"] == ""
    last = json.loads(after["last_result"])
    assert (last["status"], last["count"], last["model_used"]) == ("ok", 10, False)
    assert "-m alture_jarvis.routine run" in last["command"]
    folder = tmp_path / "data" / "routines" / row["id"]
    assert json.loads((folder / "latest.json").read_text(encoding="utf-8"))["count"] == 10
    runs = (folder / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(runs) == 1 and json.loads(runs[0])["status"] == "ok", "회차 기록 — 사흘 9회를 셀 재료"
    assert any(record.event == "routine_ran" for record in events.get_since(0))
    listed = scheduler.list({"limit": 10})["schedules"][0]
    assert listed["kind"] == "routine" and json.loads(listed["last_result"])["count"] == 10, "앱 화면 목록이 읽는 그대로"


def test_repeating_routine_comes_back_and_a_broken_run_is_marked(tmp_path: Path) -> None:
    scheduler, events, _ = _scheduler(tmp_path, html=BUSAN.replace('class="job_condition"', 'class="job_cond_v2"'))
    row = scheduler.create({"routine": SPEC, "delay_minutes": 0.001, "repeat_every": "daily"})
    _run_due(scheduler)
    after = scheduler.get(row["id"])
    assert after["status"] == "pending" and after["run_at"] > time.time(), "깨진 회차도 다음 날은 다시 잡힌다"
    assert json.loads(after["last_result"])["status"] == "broken"
    broken = [record.payload for record in events.get_since(0) if record.event == "routine_broken"]
    assert broken and broken[0]["repair"] == "not_connected", "손자리 고침 자리는 있고, 아직 연결 안 됐다고 말한다"
    assert not (tmp_path / "data" / "routines" / row["id"] / "latest.json").exists(), "깨진 결과는 파일로 내보내지 않는다"


@pytest.mark.parametrize(
    "routine_spec",
    [
        {**SPEC, "region": "부산시청앞"},
        {**SPEC, "url": "https://www.saramin.co.kr/zf_user/search?loc_mcd=3"},
        {**SPEC, "recipe": "jobkorea"},
        {"recipe": "saramin", "query": ""},
    ],
)
def test_bad_routine_is_refused_when_created_not_at_7am(tmp_path: Path, routine_spec: dict) -> None:
    scheduler, _, fake = _scheduler(tmp_path)
    with pytest.raises(ValueError, match="routine_refused"):
        scheduler.create({"routine": routine_spec, "delay_minutes": 5})
    assert scheduler.list()["count"] == 0 and fake.urls == []


def test_prompt_schedules_are_untouched(tmp_path: Path) -> None:
    enqueued: list = []
    scheduler, _, fake = _scheduler(tmp_path, enqueued=enqueued)
    row = scheduler.create({"prompt": "상태 점검", "delay_minutes": 0.001})
    assert row["kind"] == "prompt" and row["routine"] == ""
    _run_due(scheduler)
    assert len(enqueued) == 1 and enqueued[0][0] == "chat"
    assert scheduler.get(row["id"])["status"] == "dispatched" and fake.urls == []
