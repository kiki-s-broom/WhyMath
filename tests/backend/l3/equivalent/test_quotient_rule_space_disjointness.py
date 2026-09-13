"""몫의 미분법 두 생성기의 파라미터 공간 **서로소 분할** 동결 — QUAL-07(2026-09-12).

## 왜 이 파일이 있는가 (사고 경위)

`highschool_quotient_rule_skeleton_generator`(고교 미적분Ⅱ `[12미적Ⅱ-02-04]`)는
`calculus_chain_quotient_rule_skeleton_generator`의 몫의 미분법 설계를 "그대로 재적용"해
만들어졌고, 그 "그대로"에 **계수 범위와 난수 시드까지** 포함돼 있었다. 결과:

  · 대학 몫의 미분법 풀 260개가 고교 풀 300개의 **부분집합**(실측).
  · 두 코퍼스가 **조건식(수학 실체) 동일 138건**을 공유했고, 그중 발문까지 글자 그대로 같은
    것이 **71건**이었다(나머지 67건은 두 템플릿이 갈려 발문만 달랐다 — 즉 텍스트 기반 감사는
    실제 중복의 절반만 보고 있었다).

처분은 레코드 은퇴가 아니라 **공간 분할 + 전건 재생성**이다(판정 기록:
`docs/data/problem_duplicate_disposition_2026-09.md`). 은퇴는 발문 동일 71건만 지우고 조건식
동일 67건을 남기며, 생성기를 다시 돌리는 순간 전부 되살아났을 것이다.

## 동결하는 계약

  ① **전수 열거 분할** — 두 축의 합집합 공간(계수 4종 × 대입점 × 부호) 전건에 대해 각 키가
     고교 공간과 대학 공간 중 **정확히 한쪽**에만 속한다. 표본이 아니라 전수다.
  ② **풀 수준 서로소** — 실제로 만들어지는 두 풀의 키 교집합이 0이다(①이 참이면 따라오지만,
     풀 빌더가 범위 상수를 실제로 쓰는지까지 확인하는 축이라 따로 잰다).
  ③ **코퍼스 수준 서로소** — 커밋된 두 코퍼스가 발문도 `verify.conditions`도 공유하지 않는다.
     ②는 "다시 돌리면 안 겹친다"를, ③은 "지금 파일이 안 겹친다"를 말한다 — 생성기만 고치고
     코퍼스 재생성을 빠뜨리면 ②는 통과하고 ③이 깨진다.
     조건식을 중복 판정에 쓰는 것은 **이 두 코퍼스에 한정된 정당성**이다: 여기 조건식은 계수
     4종과 대입점을 전부 담아 발문과 일대일이다. 저장소 전체에서는 조건식이 축약된 계열이 많아
     같은 판정을 일반화하면 오탐이 압도한다(전수 스캔 결과 = 판정 기록 §7).
  ④ **교육적 요구 보존** — 좁힌 고교 공간이 성취기준 요구를 여전히 만족한다: 계수 부호 양쪽과
     0(해당 자리), 대입점 음수·0·양수가 전부 실제 코퍼스에 나타난다. 공간을 좁히는 처분이
     "겹치지만 않으면 된다"로 미끄러지는 것을 막는 축이다.

`corpus_authoring` 마커를 **붙이지 않는다** — 배치 실행(SymPy 검산 200×)이 없어 빠르고,
backend 잡의 PR 상시 경로에서 돌아야 생성기 변경이 아닌 경로(코퍼스 직접 편집 등)로도 계약이
깨지는 것을 잡는다.
"""

from __future__ import annotations

import json
import re
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l3.equivalent import (
    calculus_chain_quotient_rule_skeleton_generator as university,
)
from whymath_backend.l3.equivalent import (
    highschool_quotient_rule_skeleton_generator as highschool,
)

_CORPUS_ROOT = Path(__file__).resolve().parents[4] / "data" / "corpus"
_HS_CORPUS = _CORPUS_ROOT / "problem_bank_highschool_quotient_rule_v0" / "problems.jsonl"
_UNI_CORPUS = _CORPUS_ROOT / "problem_bank_university_calc1_chain_quotient_v0" / "problems.jsonl"

_HS_STANDARD = "[12미적Ⅱ-02-04]"
_UNI_QUOTIENT_STANDARD = "[CALC1-02-03]"
_UNI_CHAIN_STANDARD = "[CALC1-02-04]"

# 조건식에서 계수를 되읽는 정규식 — 생성기 `condition` 포맷과 1:1(포맷이 바뀌면 파싱 0건이
# 되어 아래 "스캔 0건은 실패" 단언이 터진다).
_CONDITION_RE = re.compile(
    r"^Derivative\(\((-?\d+)\*x\*\*2 \+ (-?\d+)\*x \+ (-?\d+)\) / "
    r"\((-?\d+)\*x \+ (-?\d+)\), x\)\.doit\(\)\.subs\(x, (-?\d+)\) = y$"
)


def _read(path: Path) -> list[dict[str, Any]]:
    assert path.exists(), f"코퍼스가 없다: {path}"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert records, f"코퍼스가 비었다: {path}"  # 스캔 0건은 실패(공허한 통과 금지).
    return records


def _hs_admits(a: int, b: int, c: int, d: int) -> bool:
    """고교 축이 받는 계수 조합인가 — 범위 상수에서 유도(테스트가 값을 따로 적지 않는다)."""
    return (
        a in highschool._A_RANGE
        and b in highschool._BC_RANGE
        and c in highschool._BC_RANGE
        and d in highschool._D_RANGE
    )


def _uni_admits(a: int, b: int, c: int, d: int) -> bool:
    """대학 축이 받는 계수 조합인가 — 범위 상수 + 밴드 술어."""
    return (
        a in university._QUOT_A_RANGE
        and b in university._QUOT_BC_RANGE
        and c in university._QUOT_BC_RANGE
        and d in university._QUOT_D_RANGE
        and university._quotient_band_admits(a, b, c, d)
    )


def _union_space() -> list[tuple[int, int, int, int]]:
    """두 축 범위의 합집합 — 전수 열거 대상(표본 아님)."""
    a_values = sorted(set(highschool._A_RANGE) | set(university._QUOT_A_RANGE))
    bc_values = sorted(set(highschool._BC_RANGE) | set(university._QUOT_BC_RANGE))
    d_values = sorted(set(highschool._D_RANGE) | set(university._QUOT_D_RANGE))
    return [tuple(t) for t in product(a_values, bc_values, bc_values, d_values)]  # type: ignore[misc]


class TestSpacePartition:
    """① 전수 열거 분할."""

    def test_every_coefficient_tuple_belongs_to_at_most_one_axis(self) -> None:
        space = _union_space()
        assert len(space) > 1000, f"열거 대상이 비정상적으로 작다: {len(space)}"  # 스캔 0건 방지.
        both = [t for t in space if _hs_admits(*t) and _uni_admits(*t)]
        assert both == [], f"두 축이 함께 받는 계수 조합 {len(both)}건: {both[:5]}"

    def test_partition_covers_the_union_space(self) -> None:
        """어느 쪽도 받지 않는 계수 조합은 없다 — 분할이지 '양쪽 다 좁히기'가 아니다.

        이 절이 없으면 "둘 다 |계수|≤2로 좁히기" 같은 과잉 수정도 ①을 통과한다(교집합 0).
        """
        neither = [t for t in _union_space() if not _hs_admits(*t) and not _uni_admits(*t)]
        assert neither == [], f"어느 축도 받지 않는 계수 조합 {len(neither)}건: {neither[:5]}"

    def test_both_axes_keep_a_substantial_space(self) -> None:
        """양쪽 모두 200문항 코퍼스를 충분히 덮는 공간을 유지한다(고갈·단조 방지)."""
        space = _union_space()
        hs = [t for t in space if _hs_admits(*t)]
        uni = [t for t in space if _uni_admits(*t)]
        # 대입점(7) × 분모부호(2) = 14배가 곱해지므로 계수 조합만으로도 넉넉해야 한다.
        assert len(hs) >= 500, len(hs)
        assert len(uni) >= 500, len(uni)


class TestPoolDisjointness:
    """② 풀 수준 서로소 — 범위 상수가 실제 풀 빌더에 쓰이는지까지 본다."""

    @staticmethod
    def _keys(pool: tuple[Any, ...]) -> set[tuple[int, int, int, int, int, int]]:
        return {(s.a, s.b, s.c, s.d, s.k, s.g_sign) for s in pool}

    def test_generated_pools_share_no_key(self) -> None:
        hs_keys = self._keys(highschool._build_pool())
        uni_keys = self._keys(university._build_quotient_pool())
        assert hs_keys, "고교 풀이 비었다"
        assert uni_keys, "대학 몫의 미분법 풀이 비었다"
        assert hs_keys & uni_keys == set(), sorted(hs_keys & uni_keys)[:5]

    def test_pools_still_reach_their_targets(self) -> None:
        """서로소 분리가 풀 고갈을 만들지 않았다(거부 샘플링이 목표치를 못 채우면 코퍼스가 준다)."""
        assert len(highschool._build_pool()) == highschool._POOL_TARGET
        assert len(university._build_quotient_pool()) == university._QUOT_POOL_TARGET


class TestCorpusDisjointness:
    """③ 코퍼스 수준 서로소 — 생성기만 고치고 재생성을 빠뜨리면 여기서 걸린다."""

    def test_committed_corpora_share_no_question_text(self) -> None:
        hs = {" ".join(r["question_text"].split()) for r in _read(_HS_CORPUS)}
        uni = {" ".join(r["question_text"].split()) for r in _read(_UNI_CORPUS)}
        assert len(hs) == 200 and len(uni) == 400, (len(hs), len(uni))
        assert hs & uni == set(), sorted(hs & uni)[:3]

    def test_committed_corpora_share_no_verify_condition(self) -> None:
        """발문이 아니라 **수학 실체**로 잰다 — 71쌍 밑에 깔려 있던 138건이 이 축이다.

        템플릿이 2종이라 같은 스켈레톤이 서로 다른 발문을 낼 수 있다. 발문만 비교하면 중복의
        절반이 보이지 않는다(QUAL-07 실측: 발문 71 vs 조건식 138).
        """
        hs = {r["verify"]["conditions"] for r in _read(_HS_CORPUS)}
        uni = {r["verify"]["conditions"] for r in _read(_UNI_CORPUS)}
        assert hs & uni == set(), sorted(hs & uni)[:3]

    def test_corpus_coefficients_obey_each_axis_predicate(self) -> None:
        """커밋된 레코드의 계수가 각 축의 술어를 실제로 만족한다(공간과 데이터의 정합)."""
        parsed = 0
        for record in _read(_HS_CORPUS):
            match = _CONDITION_RE.match(record["verify"]["conditions"])
            assert match, record["verify"]["conditions"]
            a, b, c, d, _e, _k = (int(g) for g in match.groups())
            assert _hs_admits(a, b, c, d), record["slug"]
            assert not _uni_admits(a, b, c, d), record["slug"]
            parsed += 1
        for record in _read(_UNI_CORPUS):
            if record["achievement_standard_codes"][0] != _UNI_QUOTIENT_STANDARD:
                continue  # 연쇄법칙 밴드는 (ax+b)ⁿ — 구조가 달라 애초에 겹치지 않는다.
            match = _CONDITION_RE.match(record["verify"]["conditions"])
            assert match, record["verify"]["conditions"]
            a, b, c, d, _e, _k = (int(g) for g in match.groups())
            assert _uni_admits(a, b, c, d), record["slug"]
            assert not _hs_admits(a, b, c, d), record["slug"]
            parsed += 1
        assert parsed == 400, f"조건식 파싱 대상이 400건이 아니다: {parsed}"  # 스캔 0건 방지.

    def test_chain_band_is_untouched_by_the_split(self) -> None:
        """연쇄법칙 밴드는 분할 대상이 아니다 — 200건이 그대로 있어야 한다(과잉 처분 방지)."""
        codes = [r["achievement_standard_codes"][0] for r in _read(_UNI_CORPUS)]
        assert codes.count(_UNI_CHAIN_STANDARD) == 200
        assert codes.count(_UNI_QUOTIENT_STANDARD) == 200


class TestPedagogicalRequirementsSurvive:
    """④ 좁힌 쪽이 성취기준 요구를 여전히 만족하는가 — '겹치지만 않으면 된다' 방지."""

    def test_highschool_corpus_keeps_sign_and_zero_variety(self) -> None:
        seen_a: set[int] = set()
        seen_b: set[int] = set()
        seen_d: set[int] = set()
        seen_k: set[int] = set()
        for record in _read(_HS_CORPUS):
            match = _CONDITION_RE.match(record["verify"]["conditions"])
            assert match, record["verify"]["conditions"]
            a, b, _c, d, _e, k = (int(g) for g in match.groups())
            seen_a.add(a)
            seen_b.add(b)
            seen_d.add(d)
            seen_k.add(k)
        # 분자·분모 최고차항: 양·음 양쪽(0은 정의상 제외).
        assert any(v > 0 for v in seen_a) and any(v < 0 for v in seen_a), sorted(seen_a)
        assert any(v > 0 for v in seen_d) and any(v < 0 for v in seen_d), sorted(seen_d)
        # 일차항: 양·음·0 셋 다 — 0항 생략 표기(`(2x^2 + 3)`)도 연습 대상이다.
        assert any(v > 0 for v in seen_b) and any(v < 0 for v in seen_b) and 0 in seen_b
        # 대입점: 음수·0·양수 — 음수 대입은 고교 축에서도 성취기준 요구다(공간을 좁힐 때
        # `k`를 건드리지 않은 이유).
        assert any(v < 0 for v in seen_k) and any(v > 0 for v in seen_k) and 0 in seen_k

    def test_highschool_corpus_stays_fully_distinct(self) -> None:
        records = _read(_HS_CORPUS)
        assert len({r["question_text"] for r in records}) == len(records)
        assert len({r["verify"]["conditions"] for r in records}) == len(records)
        assert {r["achievement_standard_codes"][0] for r in records} == {_HS_STANDARD}

    def test_university_quotient_band_is_structurally_heavier(self) -> None:
        """난이도 표기(대학 3.9 > 고교 3.7)에 구조적 실체를 준다 — 이전에는 **같은 문항**에
        다른 숫자를 붙인 것뿐이었다."""
        hs_max: list[int] = []
        uni_max: list[int] = []
        for path, bucket, only in (
            (_HS_CORPUS, hs_max, None),
            (_UNI_CORPUS, uni_max, _UNI_QUOTIENT_STANDARD),
        ):
            for record in _read(path):
                if only is not None and record["achievement_standard_codes"][0] != only:
                    continue
                match = _CONDITION_RE.match(record["verify"]["conditions"])
                assert match, record["verify"]["conditions"]
                a, b, c, d, _e, _k = (int(g) for g in match.groups())
                bucket.append(max(abs(a), abs(b), abs(c), abs(d)))
        assert hs_max and uni_max
        assert max(hs_max) < min(uni_max), (max(hs_max), min(uni_max))


def test_generators_do_not_share_a_coefficient_range_object() -> None:
    """두 축이 같은 범위 상수를 다시 공유하는 회귀를 잡는다(사고의 직접 원인).

    범위가 다시 같아지면 위 ①이 먼저 RED가 되지만, 이 단언은 **무엇이 같아졌는지**를 이름으로
    지목해 준다 — 진단 비용 축소용.
    """
    assert set(highschool._A_RANGE) != set(university._QUOT_A_RANGE)
    assert set(highschool._BC_RANGE) != set(university._QUOT_BC_RANGE)
    assert set(highschool._D_RANGE) != set(university._QUOT_D_RANGE)
    # 대입점은 의도적으로 같다 — 좁히면 음수 대입 연습이 사라진다.
    assert set(highschool._K_RANGE) == set(university._QUOT_K_RANGE)


@pytest.mark.parametrize(
    ("a", "b", "c", "d", "expected_axis"),
    [
        (1, 0, 0, 1, "hs"),  # 전 계수 최소 — 고교.
        (3, 3, 3, 3, "hs"),  # 고교 상한 경계(전부 3) — 한 칸만 커져도 대학으로 넘어간다.
        (4, 3, 3, 3, "uni"),  # a만 4 — 경계 바로 바깥.
        (3, 4, 3, 3, "uni"),  # b만 4.
        (3, 3, -5, 3, "uni"),  # c만 |5| — 음수 쪽 경계도 밟는다.
        (3, 3, 3, -4, "uni"),  # d만 |4| — 음수 쪽.
        (-4, -5, 5, 4, "uni"),  # 전 계수 최대.
    ],
)
def test_boundary_tuples_land_on_the_expected_axis(
    a: int, b: int, c: int, d: int, expected_axis: str
) -> None:
    """경계 케이스 개별 지목 — `>= 4` 절이 `> 4`·`>= 3`으로 밀리면 여기서 먼저 터진다.

    각 케이스는 "이 절이 없으면 무엇이 통과하는가"의 반례다: `(3,3,3,3)`은 대학 술어가
    `>= 3`이 되면 양쪽 모두 받게 되고, `(4,3,3,3)`은 `> 4`가 되면 어느 쪽도 받지 못한다.
    """
    hs_ok, uni_ok = _hs_admits(a, b, c, d), _uni_admits(a, b, c, d)
    assert (hs_ok, uni_ok) == ((expected_axis == "hs"), (expected_axis == "uni"))
