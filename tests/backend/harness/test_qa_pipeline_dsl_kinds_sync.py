"""S4-68 ② — 등식 DSL 폐쇄 검사 제외 목록 ↔ v2 레지스트리 동기.

`qa_pipeline._NON_EQUATION_DSL_ANSWER_KINDS`는 수동 목록이라 `l3/verifier._VERIFIERS_V2`에 kind가
추가돼도 갱신되지 않았다. S4-53이 `statistical_claim`을 등록하며 빠뜨려 잠복했다(코퍼스 0건이라
미발현). 목록은 레지스트리에서 파생할 수 없다 — 레지스트리는 "어떤 DSL을 쓰는가"를 모른다 — 그래서
**분류표를 이 테스트가 소유**하고, v2에 kind가 늘면 분류 없이는 RED가 되게 강제한다.

검증 축:
  ① `statistical_claim` 레코드가 등식 DSL 위반으로 세어지지 않는다(정정 전 RED·정정 후 GREEN).
  ② v2 레지스트리의 모든 kind가 (비등식 DSL | 등식 DSL) 둘 중 정확히 하나로 분류돼 있다.
  ③ 제외 목록에 죽은 항목(v2에 없는 kind)이 없다.
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.harness import qa_pipeline as qp
from whymath_backend.l3.equivalent.canonicalize import condition_dsl_violation
from whymath_backend.l3.verifier import _VERIFIERS_V2

# sympify로 파싱되는 등식/부등식 DSL을 쓰는 v2 kind — 폐쇄 검사 *대상*이다.
# 근거(실측 2026-10-09, data/corpus 14,034건 중 조건 보유 레코드): 이 11종은 kind당 24건씩
# 등식 DSL 위반이 **0건**이다. 반대로 제외 8종 중 코퍼스에 있는 6종은 전건 위반(130건)이다.
_EQUATION_DSL_KINDS = frozenset(
    {
        "real_root_count",
        "extremum_count",
        "is_one_to_one",
        "geometric_convergence",
        "limit_equals_value",
        "is_differentiable",
        "series_converges",
        "excluded_point_count",
        "root_loss_count",
        "congruent_by_ratio",
        "inequality_direction",
    }
)

_STATISTICAL_CONDITIONS = "data=[1,2,3,4,5]; stat=mean"


def _write_corpus(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    bank = tmp_path / "problem_bank_a"
    bank.mkdir()
    (bank / "problems.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_statistical_claim_record_is_not_counted_as_dsl_violation(tmp_path: Path) -> None:
    """① statistical_claim 1건을 임시 코퍼스에 넣어도 위반으로 세어지지 않는다."""
    # 전제(픽스처가 그 절을 밟는다): 이 조건 문자열은 *제외되지 않았다면* 위반으로 센다.
    assert condition_dsl_violation(_STATISTICAL_CONDITIONS) is not None

    root = _write_corpus(
        tmp_path,
        [
            {
                "slug": "stat-1",
                "verify": {
                    "answer_kind": "statistical_claim",
                    "conditions": _STATISTICAL_CONDITIONS,
                },
            }
        ],
    )
    result = qp._axis_equivalence_canonicalize(root)
    assert result.status == "ok"
    assert result.detail == {"total_conditions_checked": 0, "violations": 0}


def test_every_v2_kind_is_classified_exactly_once() -> None:
    """② v2 kind가 늘면 분류 없이는 RED — 새 kind의 DSL 종류를 사람이 한 번 판정하게 강제한다."""
    non_equation = set(qp._NON_EQUATION_DSL_ANSWER_KINDS)
    registry = set(_VERIFIERS_V2)

    assert not non_equation & _EQUATION_DSL_KINDS, "한 kind가 두 분류에 동시에 있다"
    unclassified = registry - non_equation - _EQUATION_DSL_KINDS
    assert unclassified == set(), (
        f"v2 레지스트리에 분류되지 않은 kind: {sorted(unclassified)} — "
        "qa_pipeline._NON_EQUATION_DSL_ANSWER_KINDS 또는 이 테스트의 _EQUATION_DSL_KINDS에 "
        "등식 DSL 여부를 판정해 등록한다"
    )


def test_exclusion_list_has_no_dead_entries() -> None:
    """③ 제외 목록의 모든 kind는 v2 레지스트리에 있다(삭제·오타 잔재를 막는다)."""
    dead = set(qp._NON_EQUATION_DSL_ANSWER_KINDS) - set(_VERIFIERS_V2)
    assert dead == set(), f"v2에 없는 제외 항목: {sorted(dead)}"
    assert set(_EQUATION_DSL_KINDS) <= set(_VERIFIERS_V2)
