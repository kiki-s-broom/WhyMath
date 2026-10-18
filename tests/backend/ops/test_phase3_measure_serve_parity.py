"""P3-57 오답 보기 "계측기가 닿았다고 세는 것" ↔ "서빙이 후보를 내는 것" 동치 래칫.

이 파일이 지키는 것
-------------------
오답 보기(`distractor_map`)의 오개념 id 를 두 곳이 **따로** 해석한다.

  * 계측기 — `l1.standards.phase3_coverage.reached_misconception_ids`: kebab 은 크로스링크로, `M0674`
    같은 M-id 는 **형태(정규식)만 보고** "닿음"으로 센다. 문항 7필드·슬롯 지표가 이 판정에 기댄다.
  * 서빙 — `l4.misconception.distractor_link.distractor_link_matches`: `CATALOG_BY_ID`(kebab 키)에
    있는 id 만 후보를 낸다. M-id 는 어디에도 없으므로 **조용히 버려진다**.

두 판정이 갈라지면 "측정은 연결됐다고 말하는데 학생 경로는 아무것도 안 하는" 구간이 생긴다. 계측기(L1)는
서빙(L4)을 import 할 수 없으므로(7계층 단방향) 코드 공유로 한 판정을 만들 수 없고, 두 곳을 **함께 보는 이
자리**(ops 는 횡단 도구라 둘 다 부를 수 있다)가 유일한 대조 지점이다.

현재 어긋남은 `M0674` 12건이다(승인 문항 12건 · 보기 378건 중). 처분은 Kiki 결정 게이트
`G-p357-raw-mid-distractor-disposition` 소관이라 이 파일은 어긋남을 **고치지 않고 고정**한다:

  1. 형태별 표 — 보기 id 의 형태 5종에서 두 판정이 어떻게 반응하는지 한 줄씩 못 박는다. 일치하는 형태와
     갈라지는 형태가 **둘 다** 있어야 이 표가 공허하지 않다(전부 같거나 전부 다르면 검사 자체를 의심한다).
  2. 실 코퍼스 래칫 — 갈라지는 보기의 id 별 건수가 `KNOWN_DIVERGENCE` 와 정확히 같아야 한다. 늘어도(새
     어긋남) 줄어도(처분이 들어왔는데 목록이 안 갱신됨) RED 다. 정당한 진척이 RED 가 되는 것은 의도다 —
     목록이 거짓이 되는 순간을 막는다.
  3. 만료 — 목록에 남은 항목은 담당 태스크가 끝나기(done) 전까지만 유효하다. 담당 태스크를 done 으로
     바꾸는 커밋이 어긋남을 그대로 둔 채 들어오면 RED 다(P3-61 이 "kebab 신설"만으로 done 되고 12건은 계속
     죽어 있는 상태를 막는다 — 신설한 kebab 은 raw `M0674` 라벨을 해소하지 못한다).
"""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from whymath_backend.l1.standards import phase3_coverage as p3c
from whymath_backend.l4.misconception.distractor_link import distractor_link_matches
from whymath_backend.ops import phase3_remediation as pr

_REPO = Path(__file__).resolve().parents[3]

#: 갈라지는 보기의 id → 건수. 처분(게이트 `G-p357-raw-mid-distractor-disposition`)이 집행되면 비워진다.
KNOWN_DIVERGENCE: Final[dict[str, int]] = {"M0674": 12}

#: `KNOWN_DIVERGENCE` 의 담당 태스크 — 이 태스크가 done 이 되는 시점에 목록은 비어 있어야 한다.
#: 처분 결과가 다른 태스크로 집행되면 이 값을 그 태스크 id 로 바꾼다(바뀐 diff 가 곧 재확인 지점이다).
DIVERGENCE_OWNER_TASK: Final = "P3-61-choice-trace-only-kebabs"

#: 서빙에 좌석이 있는 kebab 과 그 kebab 의 M-id(크로스링크). 대조군 = 두 판정이 일치해야 한다.
_SEATED_KEBAB: Final = "power-rule-step-omitted"
_SEATED_MID: Final = "M0671"


@pytest.fixture(scope="module")
def base() -> pr.Inputs:
    return pr.load_inputs()


# ──────────────────────────────────────────────────────────────────────────
# 두 판정 — 보기 id 한 개를 각자의 방식으로 해석한다
# ──────────────────────────────────────────────────────────────────────────
def _instrument_reaches(ident: str, corpus: p3c.CoverageCorpus) -> bool:
    """계측기가 이 보기 id 를 오개념에 "닿음"으로 세는가(공개 창구 — 계측기 내부 계산과 같다)."""
    ref = p3c.ProblemRef(
        problem_id="probe",
        primary_src_ids=frozenset(),
        review_status=None,
        has_explanation=False,
        has_steps=False,
        problem_type_codes=(),
        distractor_ids=(ident,),
    )
    return bool(p3c.reached_misconception_ids(ref, corpus))


def _serves(ident: str) -> bool:
    """서빙이 이 보기 id 로 후보를 내는가(그 보기를 골랐을 때)."""
    return bool(distractor_link_matches([{"choice_index": 1, "misconception_id": ident}], 1))


def divergence_tally(
    rows: Mapping[str, Mapping[str, Any]], corpus: p3c.CoverageCorpus
) -> tuple[Counter[str], int]:
    """(두 판정이 갈라지는 보기의 id 별 건수, 훑은 보기 수) — 리포트와 같은 입력 행을 쓴다."""
    tally: Counter[str] = Counter()
    picks = 0
    for row in rows.values():
        dmap = row["distractor_map"]
        for entry in dmap:
            ident = entry.get("misconception_id")
            if not isinstance(ident, str) or not isinstance(entry.get("choice_index"), int):
                continue
            picks += 1
            served = bool(distractor_link_matches(dmap, entry["choice_index"]))
            if _instrument_reaches(ident, corpus) != served:
                tally[ident] += 1
    return tally, picks


# ──────────────────────────────────────────────────────────────────────────
# 1. 형태별 표 — 주입 + 대조군
# ──────────────────────────────────────────────────────────────────────────
#: (라벨, 보기 id, 계측기 닿음, 서빙 후보). 갈라지는 행이 현재 상태의 정직한 기술이다.
_SHAPES: Final[tuple[tuple[str, str, bool, bool], ...]] = (
    ("kebab · 좌석 있음(대조군)", _SEATED_KEBAB, True, True),
    ("kebab · 오타(미등록)", "power-rule-step-omited", False, False),
    # 아래 셋이 갈라지는 형태다 — 계측기는 M-id 모양이면 세고, 서빙은 M-id 를 모른다.
    ("raw M-id · 좌석 있음", _SEATED_MID, True, False),
    ("raw M-id · 좌석 없음", "M0674", True, False),
    ("raw M-id · 코퍼스에 없음", "M9999", True, False),
)


class TestShapeTable:
    @pytest.mark.parametrize(("label", "ident", "instrument", "served"), _SHAPES)
    def test_each_shape_reacts_as_recorded(
        self, base: pr.Inputs, label: str, ident: str, instrument: bool, served: bool
    ) -> None:
        assert _instrument_reaches(ident, base.corpus) is instrument, label
        assert _serves(ident) is served, label

    def test_table_has_both_agreeing_and_diverging_shapes(self, base: pr.Inputs) -> None:
        """표가 공허하지 않다 — 일치하는 형태와 갈라지는 형태가 모두 실제로 관측된다."""
        agree = [s for s in _SHAPES if _instrument_reaches(s[1], base.corpus) == _serves(s[1])]
        diverge = [s for s in _SHAPES if _instrument_reaches(s[1], base.corpus) != _serves(s[1])]
        assert agree and diverge, "한쪽이 비면 이 표는 아무것도 변별하지 못한다"

    def test_a_seated_misconception_written_raw_is_dropped_by_serving(self) -> None:
        """좌석이 있는 오개념도 M-id 로 적으면 서빙이 버린다 — 같은 개념이 kebab 으로는 후보를 낸다."""
        assert _serves(_SEATED_KEBAB) and not _serves(_SEATED_MID)


# ──────────────────────────────────────────────────────────────────────────
# 2. 실 코퍼스 래칫
# ──────────────────────────────────────────────────────────────────────────
class TestRealCorpusRatchet:
    def test_divergence_is_exactly_the_registered_set(self, base: pr.Inputs) -> None:
        tally, picks = divergence_tally(base.rows, base.corpus)
        assert picks > 0, "훑은 보기가 0건이면 이 래칫은 공허하게 통과한다"
        assert dict(tally) == KNOWN_DIVERGENCE, (
            f"계측기 닿음 ≠ 서빙 후보인 보기 {dict(tally)} 가 등록된 {KNOWN_DIVERGENCE} 와 다르다. "
            "늘었다면 새 raw id 보기다(kebab 으로 적거나 처분 게이트에 올릴 것). 줄었다면 처분이 "
            "집행된 것이다 — KNOWN_DIVERGENCE 를 갱신하라. 근거: docs/reviews/p3_57_*"
        )

    def test_scan_population_is_the_report_population(self, base: pr.Inputs) -> None:
        """같은 보기를 센다 — 리포트의 '오답 보기 선택 N건'과 이 스캔의 분모가 같다."""
        _, picks = divergence_tally(base.rows, base.corpus)
        assert picks == pr.evaluate(base).working.wrong_picks

    def test_report_drop_count_matches_divergence_for_unknown_ids(self, base: pr.Inputs) -> None:
        """서빙 쪽 증거(리포트의 '카탈로그에 없어 버려진 N건')와 이 래칫이 같은 사건을 센다."""
        tally, _ = divergence_tally(base.rows, base.corpus)
        assert dict(tally) == dict(pr.evaluate(base).working.dropped_unknown)

    def test_injecting_a_raw_id_into_an_agreeing_pick_is_detected(self, base: pr.Inputs) -> None:
        """주입 — 일치하던 보기 하나를 raw M-id 로 바꾸면 래칫이 반응한다(스캔이 공허하지 않다)."""
        rows = copy.deepcopy(dict(base.rows))
        before, _ = divergence_tally(rows, base.corpus)
        target = next(
            (pid, e)
            for pid, row in rows.items()
            for e in row["distractor_map"]
            if e["misconception_id"] == _SEATED_KEBAB
        )
        target[1]["misconception_id"] = _SEATED_MID  # 좌석 있는 오개념을 raw 로 적는 실수
        after, _ = divergence_tally(rows, base.corpus)
        assert before != after, "주입이 적용되지 않았다 — 이 테스트의 RED 는 신뢰할 수 없다"
        assert after[_SEATED_MID] == 1 and dict(after) != KNOWN_DIVERGENCE

    def test_control_world_without_raw_ids_has_no_divergence(self, base: pr.Inputs) -> None:
        """성공 방향 대조군 — raw M-id 보기를 전부 kebab 으로 바꾼 세계에서는 어긋남이 0이다."""
        rows = copy.deepcopy(dict(base.rows))
        swapped = 0
        for row in rows.values():
            for e in row["distractor_map"]:
                if e["misconception_id"] in KNOWN_DIVERGENCE:
                    e["misconception_id"] = _SEATED_KEBAB
                    swapped += 1
        assert swapped == sum(KNOWN_DIVERGENCE.values()), "치환 대상이 등록 건수와 다르다"
        tally, _ = divergence_tally(rows, base.corpus)
        assert dict(tally) == {}


# ──────────────────────────────────────────────────────────────────────────
# 3. 만료 — 예외 목록은 담당 태스크가 끝나기 전까지만 유효하다
# ──────────────────────────────────────────────────────────────────────────
class TestRegistrationExpiry:
    def test_owner_task_exists_and_is_not_done_while_divergence_is_registered(self) -> None:
        path = _REPO / "backlog" / "tasks" / f"{DIVERGENCE_OWNER_TASK}.yaml"
        assert (
            path.is_file()
        ), f"담당 태스크 {DIVERGENCE_OWNER_TASK} 가 대장에 없다 — 만료 지점이 사라졌다"
        status = yaml.safe_load(path.read_text(encoding="utf-8")).get("status")
        if KNOWN_DIVERGENCE:
            assert status != "done", (
                f"{DIVERGENCE_OWNER_TASK} 가 done 인데 계측기-서빙 어긋남 {KNOWN_DIVERGENCE} 가 남아 있다. "
                "신설한 kebab 은 문항에 적힌 raw M-id 를 해소하지 않는다 — 처분(별칭 해소·계측기 정렬·"
                "보강 은행)을 집행하고 KNOWN_DIVERGENCE 를 비우거나, 담당 태스크를 바꿔라."
            )
