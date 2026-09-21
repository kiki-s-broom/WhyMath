"""오답 선지 오개념 신호 사장 규모 관측 리포트 테스트 — ASM-09 acceptance①~⑤ 대응.

구성:
  - 현행 실측 동결(acceptance①) — 실물 `AttemptSubmitRequest`에 선택 인덱스 슬롯이 없고
    `extra='forbid'`임을 런타임 프로브로 동결 + 코퍼스 정적 재실측 각주를 실물 코퍼스
    JSONL 재파싱으로 대조(수치 드리프트 시 이 테스트가 재실측 갱신을 강제한다).
  - 프로브 변별력(양방향·hermetic) — 합성 pydantic 모델로 슬롯 유/무가 *다른* 판정을
    내는지(같은 값을 내면 프로브의 존재 이유가 무너진다).
  - `build_report` 분류 변별력(acceptance④·hermetic 픽스처) — distractor_map 보유 문항의
    합성 시도 추가 → 분모 상승 → 제거 → 복원 / 비보유 문항·조인 불가 시도의 분모 제외.
  - 정직 표기(acceptance②) — 역추적 건수는 0이 아니라 None + 명시 상태 문자열. "아무도 안
    풀었다"(분모 0)와 "신호를 못 읽었다"(원천 불가)가 서로 다른 값.
  - 교수학 어휘 제약(acceptance③) — '오개념 검출' 미사용·학생 단위 산출물 0(구조 검사).
  - CLI — DB 오류 exit 2 + 예외 타입명 stderr(침묵 실패 금지)·`--help` 스모크·성공 경로.
  - 통합(실 PostgreSQL·기본 skip) — 라이브 DB에서 합성 시도 주입→분모 상승→제거→복원 실측
    (`test_attempt_grading_shadow_report.py`의 단일 이벤트 루프·델타 전용 관례 답습).
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from whymath_backend.harness import distractor_signal_dormancy_report as dsdr

# tests/backend/harness/ → tests/backend → tests → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO_ROOT / "src" / "backend"
_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"


# ──────────────────────────────────────────────────────────────────────────
# 헬퍼 — 합성 픽스처(레코드·프로브·카운트)
# ──────────────────────────────────────────────────────────────────────────
def _record(*, dmap_entries: int, joined: bool = True) -> dsdr.AttemptSeatRecord:
    """시도 레코드 합성 — joined=False면 조인 실패(고아 FK·NULL problem_id) 시뮬레이션."""
    return dsdr.AttemptSeatRecord(
        attempt_id=uuid.uuid4(),
        joined_problem_id=uuid.uuid4() if joined else None,
        distractor_entry_count=dmap_entries if joined else 0,
    )


def _counts(*, total: int = 10, with_map: int = 4) -> dsdr.ProblemSeatCounts:
    return dsdr.ProblemSeatCounts(total_problem_count=total, distractor_map_problem_count=with_map)


class _SlotlessSynthetic(BaseModel):
    """선택 인덱스 슬롯이 없는 합성 요청 모델(현행 AttemptSubmitRequest 축약형)."""

    model_config = ConfigDict(extra="forbid")

    problem_id: uuid.UUID
    student_answer: str | None = None


class _CanonicalSlotSynthetic(BaseModel):
    """정본명 `selected_choice_index` 슬롯을 가진 합성 모델(ASM-06 착지 형태)."""

    model_config = ConfigDict(extra="forbid")

    problem_id: uuid.UUID
    selected_choice_index: int | None = None


class _MarkerSlotSynthetic(BaseModel):
    """정본명이 아니어도 표지('chosen')에 걸리는 변형 이름 슬롯 + extra 미봉인 모델."""

    model_config = ConfigDict(extra="ignore")

    chosen_option_position: int | None = None


def _probe_absent() -> dsdr.CaptureSlotProbe:
    return dsdr.probe_capture_slot(_SlotlessSynthetic)


def _probe_present() -> dsdr.CaptureSlotProbe:
    return dsdr.probe_capture_slot(_CanonicalSlotSynthetic)


# ──────────────────────────────────────────────────────────────────────────
# 1. acceptance① — 실물 AttemptSubmitRequest 현행 실측 동결(슬롯 부재·extra=forbid)
# ──────────────────────────────────────────────────────────────────────────
class TestCurrentRealityFrozen:
    def test_real_attempt_submit_request_has_capture_slot(self) -> None:
        """실물 요청 계약에 선택 인덱스 슬롯이 **있다**(ASM-06 착지·2026-09-21 재작성).

        [진실 갱신] 종전 판(`..._has_no_capture_slot`)은 슬롯 *부재*를 동결했고, 그 docstring이
        "ASM-06이 `selected_choice_index`를 신설하면 이 테스트가 깨진다 — 그것이 의도다"라고
        예고해 두었다. 예고대로 깨졌으므로 ASM-05 선례에 따라 **새 진실로 재작성**한다(테스트를
        지우거나 skip하지 않는다 — 그러면 리포트의 상태 전이가 다시 무보호가 된다).

        변별력은 합성 픽스처가 보존한다 — 슬롯이 *없는* 모델(`_SlotlessSynthetic`)에 대해
        프로브가 여전히 False를 내는지는 `TestCaptureSlotProbe`가 양방향으로 확인하므로, 이
        테스트가 True로 뒤집혔다고 해서 "프로브가 항상 True를 낸다"는 위장이 성립하지 않는다.
        """
        from whymath_backend.api.me import AttemptSubmitRequest

        probe = dsdr.probe_capture_slot()  # 기본 인자 = 실물 모델 lazy 조사
        assert probe.probed_model == "AttemptSubmitRequest"
        assert probe.slot_present is True
        assert dsdr._CANONICAL_SLOT_FIELD in probe.matched_field_names
        assert dsdr._CANONICAL_SLOT_FIELD in AttemptSubmitRequest.model_fields

    def test_report_backtrace_state_flipped_to_slot_present(self) -> None:
        """리포트 상태가 `capture_slot_present_backtrace_unmeasured`로 실제 뒤집혔는가.

        종전 판 docstring이 요구한 "리포트 상태도 함께 갱신됐는지 확인하라"의 집행이다 —
        프로브만 보고 넘어가면 프로브와 리포트 사이 배선이 끊겨도 아무도 모른다.

        **미측정은 여전히 미측정이다**: ASM-06이 슬롯을 열고 역추적을 배선했지만, *이 리포트
        판*은 attempt↔distractor_map 조인을 세지 않는다(ASM-09 선언 범위 밖). 그래서 상태는
        `..._backtrace_unmeasured`로 남는 것이 정직하다 — 건수를 0으로도, 측정된 값으로도
        위장하지 않는다.
        """
        report = dsdr.build_report(_counts(), [_record(dmap_entries=2)], _probe_present())
        assert report.backtrace_state == dsdr._BACKTRACE_SLOT_PRESENT_UNMEASURED
        assert report.backtrace_state != dsdr._BACKTRACE_UNREACHABLE

    def test_real_attempt_submit_request_forbids_extra_fields(self) -> None:
        """`extra='forbid'` — 클라가 임의 필드로 인덱스를 실어 보낼 수도 없다(acceptance①)."""
        probe = dsdr.probe_capture_slot()
        assert probe.extra_forbid is True

    def test_corpus_remeasurement_note_matches_live_corpus_files(self) -> None:
        """정적 각주의 수치(2,638·1,612·동일 집합)를 실물 코퍼스 JSONL 재파싱으로 대조.

        코퍼스가 바뀌면(은퇴·증설) 여기가 깨져 `_CORPUS_REMEASUREMENT_2026_08_11`의 재실측
        갱신을 강제한다 — 문자열 동결이 아니라 기계 대조다(하드코딩 수치의 드리프트 방지).
        """
        files = sorted(_CORPUS_ROOT.glob("problem_bank*/problems.jsonl"))
        assert len(files) == 37  # r2 부록 A 7파일 + PB-13 회수 30종 — 증분이 회수 코퍼스 수와 일치
        total = with_choices = with_dmap = both = 0
        for path in files:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    total += 1
                    has_c = bool(rec.get("choices"))
                    has_d = bool(rec.get("distractor_map"))
                    with_choices += has_c
                    with_dmap += has_d
                    both += has_c and has_d
        assert (
            total == 14034
        )  # 2,638 + PB-13 회수 11,446 (r2의 2,647 대비 -9 = QUAL-02(#777) 은퇴 9건)
        assert with_choices == 1612  # r2의 1,616 대비 -4 = 은퇴 9건 중 객관식 4건
        assert with_dmap == 1612
        assert both == 1612  # choices↔distractor_map 동일 집합(불일치 0건)
        note = dsdr._CORPUS_REMEASUREMENT_2026_08_11
        assert "2,638" in note
        assert "1,612" in note
        assert "QUAL-02" in note
        # 각주는 렌더에도 실린다(acceptance① "리포트·docstring에 1줄 기록").
        report = dsdr.build_report(_counts(), [], _probe_absent())
        assert note in dsdr.render_report(report)


# ──────────────────────────────────────────────────────────────────────────
# 2. 프로브 변별력 — 슬롯 유/무·extra 봉인 유/무가 다른 판정을 낸다(양방향·hermetic)
# ──────────────────────────────────────────────────────────────────────────
class TestCaptureSlotProbeDiscrimination:
    def test_slotless_model_probes_absent(self) -> None:
        probe = _probe_absent()
        assert probe.slot_present is False
        assert probe.matched_field_names == ()
        assert probe.extra_forbid is True

    def test_canonical_slot_model_probes_present(self) -> None:
        """정본명 슬롯을 넣으면 판정이 실제로 뒤집힌다 — 같은 값이면 프로브가 무효다."""
        probe = _probe_present()
        assert probe.slot_present is True
        assert dsdr._CANONICAL_SLOT_FIELD in probe.matched_field_names
        assert probe.slot_present != _probe_absent().slot_present

    def test_marker_named_slot_still_detected(self) -> None:
        """정본명이 아니어도('chosen_option_position') 표지 그물에 걸린다 — 보수적 탐지."""
        probe = dsdr.probe_capture_slot(_MarkerSlotSynthetic)
        assert probe.slot_present is True
        assert "chosen_option_position" in probe.matched_field_names

    def test_extra_not_forbid_reported_honestly(self) -> None:
        """`extra='ignore'` 모델은 extra_forbid=False — 봉인 여부 축도 변별된다."""
        probe = dsdr.probe_capture_slot(_MarkerSlotSynthetic)
        assert probe.extra_forbid is False


# ──────────────────────────────────────────────────────────────────────────
# 3. acceptance④ — build_report 분류 변별력(양방향·hermetic 픽스처)
# ──────────────────────────────────────────────────────────────────────────
class TestDenominatorDiscrimination:
    def test_synthetic_attempt_on_distractor_problem_raises_then_restores_denominator(
        self,
    ) -> None:
        """분모(=distractor_map 보유 문항 시도)가 합성 시도 추가로 오르고 제거로 복원된다."""
        base = [_record(dmap_entries=2), _record(dmap_entries=0)]
        before = dsdr.build_report(_counts(), base, _probe_absent())
        assert before.attempts_on_distractor_map_problems == 1

        injected = [*base, _record(dmap_entries=3)]
        after = dsdr.build_report(_counts(), injected, _probe_absent())
        assert after.attempts_on_distractor_map_problems == (
            before.attempts_on_distractor_map_problems + 1
        ), "합성 시도가 분모에 반영되지 않음(변별력 없음)"
        assert after.total_attempt_count == before.total_attempt_count + 1

        restored = dsdr.build_report(_counts(), base, _probe_absent())
        assert (
            restored.attempts_on_distractor_map_problems
            == before.attempts_on_distractor_map_problems
        )
        assert restored.total_attempt_count == before.total_attempt_count

    def test_attempt_on_problem_without_distractor_map_excluded_from_denominator(self) -> None:
        """distractor_map 없는 문항의 시도는 분모에 들어가지 않고 제외 버킷에 명시된다."""
        base = [_record(dmap_entries=1)]
        before = dsdr.build_report(_counts(), base, _probe_absent())

        injected = [*base, _record(dmap_entries=0)]
        after = dsdr.build_report(_counts(), injected, _probe_absent())
        assert (
            after.attempts_on_distractor_map_problems == before.attempts_on_distractor_map_problems
        ), "비보유 문항 시도가 분모를 올렸다(분류 오류)"
        assert after.attempts_on_problems_without_distractor_map == (
            before.attempts_on_problems_without_distractor_map + 1
        )

    def test_unjoinable_attempt_is_neither_denominator_nor_excluded_bucket(self) -> None:
        """조인 실패(고아 FK·NULL) 시도는 별도 버킷 — 분모·비보유 어느 쪽도 오염하지 않는다."""
        base = [_record(dmap_entries=1), _record(dmap_entries=0)]
        before = dsdr.build_report(_counts(), base, _probe_absent())

        injected = [*base, _record(dmap_entries=0, joined=False)]
        after = dsdr.build_report(_counts(), injected, _probe_absent())
        assert (
            after.attempts_on_distractor_map_problems == before.attempts_on_distractor_map_problems
        )
        assert (
            after.attempts_on_problems_without_distractor_map
            == before.attempts_on_problems_without_distractor_map
        )
        assert after.attempts_unjoinable == before.attempts_unjoinable + 1

    def test_three_buckets_partition_total_attempts(self) -> None:
        """3버킷 합 == 총 시도(상호 배타 분할 불변식) — 어느 시도도 사라지거나 중복되지 않는다."""
        records = [
            _record(dmap_entries=2),
            _record(dmap_entries=1),
            _record(dmap_entries=0),
            _record(dmap_entries=0, joined=False),
        ]
        report = dsdr.build_report(_counts(), records, _probe_absent())
        assert report.total_attempt_count == 4
        assert (
            report.attempts_on_distractor_map_problems
            + report.attempts_on_problems_without_distractor_map
            + report.attempts_unjoinable
        ) == report.total_attempt_count

    def test_problem_seat_counts_pass_through_exactly(self) -> None:
        report = dsdr.build_report(_counts(total=2638, with_map=1612), [], _probe_absent())
        assert report.total_problem_count == 2638
        assert report.distractor_map_problem_count == 1612
        assert report.distractor_map_problem_ratio == pytest.approx(1612 / 2638)

    def test_zero_problem_denominator_ratio_is_none_not_zero(self) -> None:
        """문항 0건이면 비율은 None — 분모 없는 0%로 위장하지 않는다(시리즈 정직 회계)."""
        report = dsdr.build_report(_counts(total=0, with_map=0), [], _probe_absent())
        assert report.distractor_map_problem_ratio is None
        assert "데이터없음" in dsdr.render_report(report)


# ──────────────────────────────────────────────────────────────────────────
# 4. acceptance② — 역추적 정직 표기(0이 아니라 명시 상태·두 상태의 변별력)
# ──────────────────────────────────────────────────────────────────────────
class TestBacktraceHonestState:
    def test_slot_absent_reports_unreachable_state_with_none_count(self) -> None:
        report = dsdr.build_report(_counts(), [_record(dmap_entries=1)], _probe_absent())
        assert report.backtrace_state == dsdr._BACKTRACE_UNREACHABLE
        assert report.backtraceable_count is None  # 0이 아니다 — 원천 불가의 명시 표기

    def test_slot_present_reports_unmeasured_state_not_zero(self) -> None:
        """슬롯이 생겨도(합성) 건수를 0으로 위장하지 않는다 — 미측정 상태로 뒤집힌다."""
        report = dsdr.build_report(_counts(), [_record(dmap_entries=1)], _probe_present())
        assert report.backtrace_state == dsdr._BACKTRACE_SLOT_PRESENT_UNMEASURED
        assert report.backtraceable_count is None

    def test_two_states_render_different_wording(self) -> None:
        """같은 입력에서 프로브만 바꿔도 렌더 문구가 달라야 한다(같은 값이면 변별력 0)."""
        records = [_record(dmap_entries=1)]
        absent = dsdr.render_report(dsdr.build_report(_counts(), records, _probe_absent()))
        present = dsdr.render_report(dsdr.build_report(_counts(), records, _probe_present()))
        assert absent != present
        assert "원천 불가" in absent
        assert dsdr._BACKTRACE_UNREACHABLE in absent
        assert dsdr._BACKTRACE_SLOT_PRESENT_UNMEASURED in present
        assert "미측정" in present

    def test_nobody_attempted_vs_signal_unread_are_different_values(self) -> None:
        """'아무도 안 풀었다'(분모 0)와 '풀었지만 못 읽었다'(원천 불가)는 다른 값이다.

        분모는 정수 0, 역추적은 None+상태 문자열 — JSON에서도 0과 null로 갈린다(둘을 한
        값으로 뭉개면 이 리포트의 존재 이유가 무너진다 — acceptance② 핵심).
        """
        nobody = dsdr.build_report(_counts(), [], _probe_absent())
        assert nobody.attempts_on_distractor_map_problems == 0
        assert nobody.backtraceable_count is None
        payload = dsdr.report_to_json(nobody)
        assert payload["attempts_on_distractor_map_problems"] == 0
        assert payload["backtraceable_count"] is None
        assert payload["backtrace_state"] == dsdr._BACKTRACE_UNREACHABLE
        rendered = dsdr.render_report(nobody)
        assert "서로 다른 값" in rendered


# ──────────────────────────────────────────────────────────────────────────
# 5. acceptance③ — 교수학 어휘·산출물 제약(단정 금지·학생 단위 0)
# ──────────────────────────────────────────────────────────────────────────
class TestPedagogicalConstraints:
    def test_report_vocabulary_is_hypothesis_not_detection(self) -> None:
        """'오개념 검출'이 아니라 '오개념 가설 역추적 가능성' — 단정 어휘 금지."""
        report = dsdr.build_report(_counts(), [_record(dmap_entries=1)], _probe_absent())
        rendered = dsdr.render_report(report)
        assert "오개념 검출" not in rendered
        assert "가설 역추적" in rendered
        assert "단정하지 않는다" in rendered

    def test_no_per_student_or_correctness_outputs(self) -> None:
        """학생 단위 분해·정오답 통계가 산출물에 없다(구조 검사 — 서열·게임화 금기 승계).

        JSON 전체 직렬화에 사용자 키·정오답 키가 등장하지 않아야 한다. `collect_attempt_
        seat_records`도 사용자 필터 인자를 두지 않는다(시그니처 검사).
        """
        import inspect

        report = dsdr.build_report(_counts(), [_record(dmap_entries=1)], _probe_absent())
        dumped = json.dumps(dsdr.report_to_json(report), ensure_ascii=False).lower()
        assert "user" not in dumped
        assert "is_correct" not in dumped
        assert "정답률" not in dumped
        assert "오답률" not in dumped
        params = inspect.signature(dsdr.collect_attempt_seat_records).parameters
        assert "user_id" not in params


# ──────────────────────────────────────────────────────────────────────────
# 6. JSON 직렬화·렌더 결정론
# ──────────────────────────────────────────────────────────────────────────
class TestSerializationAndDeterminism:
    def test_report_to_json_roundtrips_through_json_dumps_loads(self) -> None:
        report = dsdr.build_report(
            _counts(total=5, with_map=3),
            [_record(dmap_entries=2), _record(dmap_entries=0)],
            _probe_absent(),
        )
        payload = dsdr.report_to_json(report)
        roundtripped = json.loads(json.dumps(payload, ensure_ascii=False))
        assert roundtripped == payload
        assert roundtripped["attempts_on_distractor_map_problems"] == 1
        assert roundtripped["capture_slot"]["slot_present"] is False

    def test_dump_json_produces_valid_sorted_json(self) -> None:
        report = dsdr.build_report(_counts(), [_record(dmap_entries=1)], _probe_absent())
        parsed = json.loads(dsdr.dump_json(report))
        assert parsed["backtraceable_count"] is None
        keys = list(parsed)
        assert keys == sorted(keys)  # sort_keys 고정(acceptance② 정렬 고정)

    def test_render_report_is_deterministic_across_repeated_calls(self) -> None:
        records = [_record(dmap_entries=1), _record(dmap_entries=0, joined=False)]
        r1 = dsdr.render_report(dsdr.build_report(_counts(), records, _probe_absent()))
        r2 = dsdr.render_report(dsdr.build_report(_counts(), records, _probe_absent()))
        assert r1 == r2


# ──────────────────────────────────────────────────────────────────────────
# 7. CLI — exit 0/2·침묵 실패 금지·--help 스모크
# ──────────────────────────────────────────────────────────────────────────
class TestCli:
    def test_main_returns_exit_2_and_logs_exception_type_on_db_failure(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(dsdr, "_run", new=AsyncMock(side_effect=RuntimeError("접속 실패"))):
            exit_code = dsdr.main([])
        assert exit_code == dsdr._EXIT_INPUT_ERROR
        captured = capsys.readouterr()
        assert "RuntimeError" in captured.err  # 무타입 경고 금지 — 예외 타입명 필수

    def test_main_success_path_renders_and_writes_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = dsdr.build_report(_counts(), [_record(dmap_entries=1)], _probe_absent())
        json_path = tmp_path / "dormancy.json"
        with patch.object(dsdr, "_run", new=AsyncMock(return_value=report)):
            exit_code = dsdr.main(["--json", str(json_path)])
        assert exit_code == dsdr._EXIT_OK
        assert "사장 규모 관측 리포트" in capsys.readouterr().out
        parsed = json.loads(json_path.read_text(encoding="utf-8"))
        assert parsed["backtrace_state"] == dsdr._BACKTRACE_UNREACHABLE

    def test_main_cli_smoke_help_exits_zero_without_db(self) -> None:
        """`--help`는 DB 접속 없이 exit 0이어야 한다(argparse 표준 동작 회귀 감시)."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "whymath_backend.harness.distractor_signal_dormancy_report",
                "--help",
            ],
            cwd=_BACKEND_DIR,
            capture_output=True,
            text=True,
            # [OPS-44 사고 경위] 자식 --help 출력의 UTF-8 한국어를 부모가 로케일(cp949)로 디코드해
            # reader thread가 UnicodeDecodeError로 죽고 stdout=None이 됐다 — UTF-8 명시로 고정.
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0
        assert "distractor" in result.stdout.lower() or "사장" in result.stdout


# ──────────────────────────────────────────────────────────────────────────
# 8. 통합(실 PostgreSQL·기본 skip) — 라이브 DB 양방향 변별력 실측(델타 전용)
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
class TestLiveDbDiscrimination:
    """acceptance④의 라이브 축 — 합성 시도 주입→분모 실측 상승→제거→복원(절대값 단언 없음).

    단일 이벤트 루프에서 전 과정을 `await`한다(`test_attempt_grading_shadow_report.py`의
    경고 관례 — 헬퍼별 `asyncio.run()` 반복은 죽은 루프에 바인딩된 커넥션 풀로 깨진다).
    다른 데이터와의 간섭을 피하려 절대값이 아니라 인접 측정 간 **델타만** 비교한다
    (`test_assessment_seat_reach_report_integration.py` 동일 원칙).
    """

    async def test_live_denominator_rises_with_injected_attempt_and_restores(self) -> None:
        from pydantic import SecretStr
        from sqlalchemy import text

        from whymath_backend.config import Settings
        from whymath_backend.db.models.activity import ProblemAttempt as ProblemAttemptORM
        from whymath_backend.db.models.problem import Problem as ProblemORM
        from whymath_backend.db.models.user import UserProfile as UserProfileORM
        from whymath_backend.schema.enums import Curriculum, Persona, SourceType, Subject
        from whymath_backend.schema.problem import DistractorEntry, Problem
        from whymath_backend.schema.user import UserProfile as UserProfileSchema

        settings = Settings(jwt_secret_key=SecretStr("integration-jwt-secret-0123456789abcdef"))
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            except Exception:
                pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

            uid = uuid.uuid4()
            pid_with_map = uuid.uuid4()
            pid_without_map = uuid.uuid4()
            aid_on_map = uuid.uuid4()
            aid_off_map = uuid.uuid4()

            def _problem(pid: uuid.UUID, *, with_map: bool) -> Problem:
                return Problem(
                    problem_id=pid,
                    source_type=SourceType.자체생성,
                    curriculum_version=Curriculum.REVISION_2022,
                    valid_from_year=2022,
                    subject=Subject.공통,
                    unit_codes=[f"U-{pid.hex[:8]}"],
                    choices=["1", "2", "3"] if with_map else None,
                    distractor_map=(
                        [DistractorEntry(choice_index=1, misconception_id="m-asm09-live-test")]
                        if with_map
                        else None
                    ),
                )

            sm = async_sessionmaker(engine, expire_on_commit=False)

            async def _report() -> dsdr.DormancyReport:
                async with sm() as session:
                    problem_counts = await dsdr.collect_problem_seat_counts(session)
                    records = await dsdr.collect_attempt_seat_records(session)
                return dsdr.build_report(problem_counts, records, _probe_absent())

            async def _cleanup() -> None:
                # FK 순서(자식→부모): problem_attempt → problem → user_profile. 전부 ORM delete.
                async with engine.begin() as conn:
                    await conn.execute(
                        delete(ProblemAttemptORM).where(ProblemAttemptORM.user_id == uid)
                    )
                    await conn.execute(
                        delete(ProblemORM).where(
                            ProblemORM.problem_id.in_([pid_with_map, pid_without_map])
                        )
                    )
                    await conn.execute(delete(UserProfileORM).where(UserProfileORM.user_id == uid))

            try:
                base = await _report()

                # 1. 문항 시딩 — dmap 보유 1건은 보유 카운트를 올리고, 비보유 1건은 못 올린다.
                async with sm() as session:
                    session.add_all(
                        [
                            UserProfileORM.from_schema(
                                UserProfileSchema(user_id=uid, persona_primary=Persona.A_일반고고3)
                            ),
                            ProblemORM.from_schema(_problem(pid_with_map, with_map=True)),
                            ProblemORM.from_schema(_problem(pid_without_map, with_map=False)),
                        ]
                    )
                    await session.commit()
                seeded = await _report()
                assert seeded.total_problem_count == base.total_problem_count + 2
                assert (
                    seeded.distractor_map_problem_count == base.distractor_map_problem_count + 1
                ), "distractor_map 보유 문항 시딩이 보유 카운트에 반영되지 않음(변별력 없음)"

                # 2. dmap 보유 문항에 합성 시도 주입 → 분모 실측 상승.
                async with sm() as session:
                    session.add(
                        ProblemAttemptORM(
                            attempt_id=aid_on_map, user_id=uid, problem_id=pid_with_map
                        )
                    )
                    await session.commit()
                injected = await _report()
                assert injected.attempts_on_distractor_map_problems == (
                    seeded.attempts_on_distractor_map_problems + 1
                ), "합성 시도가 분모에 반영되지 않음(변별력 없음)"

                # 3. dmap 비보유 문항의 시도는 분모를 올리지 못하고 제외 버킷만 올린다.
                async with sm() as session:
                    session.add(
                        ProblemAttemptORM(
                            attempt_id=aid_off_map, user_id=uid, problem_id=pid_without_map
                        )
                    )
                    await session.commit()
                off_map = await _report()
                assert (
                    off_map.attempts_on_distractor_map_problems
                    == injected.attempts_on_distractor_map_problems
                ), "비보유 문항 시도가 분모를 올렸다(분류 오류)"
                assert off_map.attempts_on_problems_without_distractor_map == (
                    injected.attempts_on_problems_without_distractor_map + 1
                )

                # 4. 주입 시도 제거 → 분모 복원 실측.
                async with engine.begin() as conn:
                    await conn.execute(
                        delete(ProblemAttemptORM).where(
                            ProblemAttemptORM.attempt_id.in_([aid_on_map, aid_off_map])
                        )
                    )
                restored = await _report()
                assert (
                    restored.attempts_on_distractor_map_problems
                    == seeded.attempts_on_distractor_map_problems
                )
                assert (
                    restored.attempts_on_problems_without_distractor_map
                    == seeded.attempts_on_problems_without_distractor_map
                )
            finally:
                await _cleanup()
        finally:
            await engine.dispose()
