"""PIPA 데이터 권한 매트릭스 계약 게이트 — COLLAB-01 D1.

공유 계약 `data/access_matrix.json`이 `docs/legal/pipa_data_matrix.md` §2.2(학생 본인/교사(B2B)/
부모 × 9개 데이터 항목의 ●/◐/✕ 표)와 동기화돼 있는지, `Role` enum(`schema/enums.py`)과 계약의
역할 축이 정합하는지 고정한다. `render_contract.json`↔`test_render_contract.py`·
`visual_style_contract.json`↔`test_visual_style_render_contract.py`와 동형 패턴 — 새 추상 없음.

**배경(실측, ①)**: 이 테스트를 만들기 전 `Role.` 사용처·`access_matrix`/`pipa_data_matrix`
문자열·`resolution`/`"full"`/`'summary'` 패턴을 `src/backend/whymath_backend` 전역에서 grep한
결과, 항목(정답률·오답 패턴 등) 단위로 역할별 응답을 필터링하는 코드는 0건이었다(`require_role`은
`Role.CONTENT_ADMIN` 게이팅 1건뿐이고 콘텐츠 CUD용이지 데이터 열람용이 아니다·`pipa_data_matrix`
문자열이 등장하는 유일한 코드는 §3 부모 동의 관련 config/consent 주석). `docs/architecture/
collaboration_module_gap_review.md` §3 D1의 "매트릭스는 선언은 정본, 집행은 0"이라는 진단과
일치 — 이 태스크는 새로 발견한 부분 구현을 대체하는 것이 아니라 진짜 공백을 처음 메운다.

**설계 — 왜 계약의 역할 축이 PIPA 3열보다 넓은가**: `Role` enum은 STUDENT와 콘텐츠 운영 역할
4종(CONTENT_ADMIN·P3-12의 편집·검수·배포)이고, pipa 매트릭스는 학생/교사/부모 3열이다. 두 축이
겹치지 않는다(콘텐츠 역할은 PIPA 데이터 뷰어가 아닌 저작·운영 역할, 교사·부모는 아직 Role enum에
없다). 계약은 이 둘의 합집합을 `roles`로 선언하고 각 role에 `status`(`active`=지금 Role enum이
실제로 발급 / `planned`=Phase 3+ 좌석 대기)를 매겨 두 축을 화해시킨다.
`TestRoleEnumSyncsWithContract`가 "활성 역할 집합 == 계약이 active로 선언한 역할 집합"을
양방향으로 검사하므로, 미래에 `Role`에 새 멤버가 추가되는데 계약이 그 role을 `active`로
승격하지 않으면 즉시 red다 — 이것이 이 계약의 존재 이유(Phase 3에 `PARENT`/`TEACHER`가
실제로 열릴 때 계약이 먼저 강제하고 있어야 한다).

**선형 서열 비전제(ⓒ) — `test_role_enum.py`와의 관계**: 그 파일은 `Role` *타입 자체*가 서열
비교 연산을 지원하지 않음을 동결한다(`<`가 `TypeError`). 이 파일은 그 결정의 *데이터 근거*를
추가로 실측한다 — 설령 누군가 `Role`에 서열 연산을 억지로 얹더라도(다른 enum·비교 유틸 경유),
pipa 매트릭스의 실제 값 자체가 student/teacher/parent 3역할 중 어느 순열로도 전 9항목에서
일관된 순서를 이루지 않는다는 것을 보여 "서열을 얹는 시도 자체가 데이터와 모순"임을 증명한다.
중복이 아니라 보완 — 저 파일이 타입을, 이 파일이 데이터를 막는다.
"""

from __future__ import annotations

import json
import re
from itertools import permutations
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.schema.enums import Role

# tests/backend/schema/ → parents[3] = 레포 루트(test_render_contract.py와 동일 기준).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE = _PROJECT_ROOT / "data" / "access_matrix.json"
_PIPA_DOC = _PROJECT_ROOT / "docs" / "legal" / "pipa_data_matrix.md"

_SYMBOL_TO_RESOLUTION = {"●": "full", "◐": "summary", "✕": "none"}
_RESOLUTION_RANK = {"full": 2, "summary": 1, "none": 0}
# pipa_data_matrix.md §2.2 표 열 순서(학생 본인/교사(B2B)/부모) == 계약 roles 중 PIPA 3역할.
_PIPA_ROLE_COLUMNS: tuple[str, str, str] = ("student", "teacher", "parent")
#: PIPA 데이터 뷰어가 아닌 콘텐츠 운영 역할 — 9항목 전부 none으로 명시한다(P3-12가 3종을 더했다).
_CONTENT_ROLES: tuple[str, ...] = (
    "content_admin",
    "content_editor",
    "content_reviewer",
    "content_publisher",
)


def _load_contract() -> dict[str, Any]:
    if not _FIXTURE.exists():  # pragma: no cover - fixture는 레포에 동봉
        pytest.skip(f"권한 매트릭스 계약 fixture 없음: {_FIXTURE}")
    loaded: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return loaded


_CONTRACT = _load_contract()
_ROLES: dict[str, Any] = _CONTRACT["roles"]
_ITEMS: dict[str, Any] = _CONTRACT["items"]

# `| # | **라벨**(선택적 부연) | 학생기호 | 교사기호 | 부모기호 | 설계메모 |` 형태의 표 행만
# 매치. 라벨은 **볼드** 구간만 취하고(항목 #6·#9처럼 볼드 뒤에 괄호 부연이 붙어도 무시), 부연
# 텍스트는 `.*?`로 건너뛴다 — 짧은 정규 라벨만 계약 label_ko와 대조한다.
_MD_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*\*\*(.+?)\*\*.*?\|\s*(\S)\s*\|\s*(\S)\s*\|\s*(\S)\s*\|"
)


def _parse_pipa_matrix_rows() -> list[dict[str, Any]]:
    """`pipa_data_matrix.md` §2.2 표를 원문에서 직접 파싱 — 계약에 값을 중복 하드코딩하지 않는다.

    파싱 실패(행 0건이나 9건 미만)를 조용히 넘기지 않는다 — 표 포맷이 바뀌면 이 파서도 함께
    깨져야 drift를 놓치지 않는다(`test_md_table_has_exactly_nine_rows`가 그 하한을 명시적으로 건다).
    """
    text = _PIPA_DOC.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = _MD_ROW_RE.match(line)
        if not m:
            continue
        num, label, student_sym, teacher_sym, parent_sym = m.groups()
        rows.append(
            {
                "num": int(num),
                "label_ko": label.strip(),
                "student": student_sym,
                "teacher": teacher_sym,
                "parent": parent_sym,
            }
        )
    return rows


_MD_ROWS = _parse_pipa_matrix_rows()


def _md_sync_violations(items: dict[str, Any], md_rows: list[dict[str, Any]]) -> list[str]:
    """계약 `items` ↔ md `md_rows` 불일치를 계산 — 순수 함수(전역/디스크 미접근, 인자만 본다).

    항목 개수·번호·라벨·(학생/교사/부모) 해상도 기호 매핑을 전부 대조한다. 훼손 실험
    (acceptance ④)이 이 함수를 직접 호출해 red/green을 실측한다.
    """
    violations: list[str] = []
    by_num = {item["num"]: (item_id, item) for item_id, item in items.items()}
    for row in md_rows:
        found = by_num.get(row["num"])
        if found is None:
            violations.append(f"#{row['num']} {row['label_ko']}: 계약에 해당 num 항목이 없음")
            continue
        item_id, item = found
        if item["label_ko"] != row["label_ko"]:
            violations.append(
                f"#{row['num']}: 라벨 불일치 "
                f"(doc={row['label_ko']!r} vs contract={item['label_ko']!r})"
            )
        for role in _PIPA_ROLE_COLUMNS:
            expected = _SYMBOL_TO_RESOLUTION.get(row[role])
            if expected is None:
                violations.append(f"#{row['num']} {role}: doc 기호 {row[role]!r}를 해석할 수 없음")
                continue
            actual = item["resolution"].get(role)
            if actual != expected:
                violations.append(
                    f"#{row['num']} {row['label_ko']} · role={role}: "
                    f"doc={row[role]!r}({expected}) vs contract={actual!r} (item_id={item_id})"
                )
    doc_nums = {row["num"] for row in md_rows}
    for item_id, item in items.items():
        if item["num"] not in doc_nums:
            violations.append(f"{item_id}(num={item['num']}): 계약에만 있고 doc에는 없는 항목")
    return violations


def _role_sync_violations(
    active_role_values: frozenset[str], contract_roles: dict[str, Any]
) -> list[str]:
    """`Role` enum 활성 값 집합 ↔ 계약 `roles`의 `status=="active"` 집합 불일치 — 순수 함수.

    양방향: (1) 활성 역할인데 계약에 `active`로 없음 (2) 계약이 `active`라는데 실제 활성
    역할에 없음. 둘 다 위반으로 잡아야 "Role에 멤버가 추가됐는데 계약이 모른다"·"계약이 아직
    없는 역할을 활성이라 우긴다" 양쪽 drift를 막는다.
    """
    violations: list[str] = []
    contract_active = {
        entry["role_enum_value"]
        for entry in contract_roles.values()
        if entry.get("status") == "active" and entry.get("role_enum_value") is not None
    }
    for value in sorted(active_role_values):
        if value not in contract_active:
            violations.append(
                f"활성 역할 '{value}'이 계약(roles)에 status=active로 선언돼 있지 않음"
            )
    for value in sorted(contract_active):
        if value not in active_role_values:
            violations.append(
                f"계약이 status=active로 선언한 역할 '{value}'이 실제 Role enum에 없음"
            )
    return violations


def _produced_by_violations(items: dict[str, Any]) -> list[str]:
    """`produced_by`(산출물 매핑) 미정의/공백 항목 검출 — 순수 함수."""
    violations: list[str] = []
    for item_id, item in items.items():
        produced_by = item.get("produced_by")
        if not isinstance(produced_by, list) or not produced_by:
            violations.append(f"{item_id}: produced_by가 비어있거나 리스트가 아님")
            continue
        for entry in produced_by:
            if not isinstance(entry, str) or not entry.strip():
                violations.append(f"{item_id}: produced_by에 빈 항목")
    return violations


def _rank(resolution: str) -> int:
    return _RESOLUTION_RANK[resolution]


# ──────────────────────────────────────────────────────────────────────────
# ⓐ 계약 ↔ pipa_data_matrix.md §2.2 표 동기
# ──────────────────────────────────────────────────────────────────────────
class TestContractSyncsWithPipaDoc:
    def test_md_table_has_exactly_nine_rows(self) -> None:
        assert (
            len(_MD_ROWS) == 9
        ), f"pipa_data_matrix.md §2.2 파싱 {len(_MD_ROWS)}행 — 표 포맷 변경 또는 파서 손상 의심"

    def test_contract_has_exactly_nine_items(self) -> None:
        assert len(_ITEMS) == 9

    def test_contract_item_nums_are_1_through_9_with_no_duplicates(self) -> None:
        nums = sorted(item["num"] for item in _ITEMS.values())
        assert nums == list(range(1, 10))

    def test_no_sync_violations_against_the_real_doc(self) -> None:
        violations = _md_sync_violations(_ITEMS, _MD_ROWS)
        assert violations == [], "\n".join(violations)

    @pytest.mark.parametrize("role", _PIPA_ROLE_COLUMNS)
    def test_all_resolution_values_are_known_symbols(self, role: str) -> None:
        for item_id, item in _ITEMS.items():
            assert (
                item["resolution"][role] in _RESOLUTION_RANK
            ), f"{item_id}.{role}: 알 수 없는 해상도 값 {item['resolution'][role]!r}"

    @pytest.mark.parametrize("role", _CONTENT_ROLES)
    def test_content_roles_have_no_pipa_data_visibility(self, role: str) -> None:
        """콘텐츠 역할 4종은 PIPA 뷰어 축이 아니다 — 9항목 전부 none이어야 '뷰어 아님'이 정직하다.

        P3-12가 CMS 역할 3종(편집·검수·배포)을 더했다. 명시하지 않으면 미래의 역할별 필드 필터링
        좌석이 `resolution[role]`을 못 찾아 '미명시'를 '허용'으로 읽을 수 있다 — 미명시 ≠ 미공개.
        """
        for item_id, item in _ITEMS.items():
            assert item["resolution"][role] == "none", (
                f"{item_id}: {role}이 none이 아님 — 콘텐츠 역할이 학생 데이터 열람권을 "
                "갖는 것은 설계 밖(계약 note 참조)"
            )

    def test_content_roles_are_exactly_the_active_non_student_roles(self) -> None:
        """분모 — 위 4종이 계약의 활성 역할 중 학생을 뺀 전부다(역할이 늘면 이 목록이 먼저 red)."""
        active = {
            e["role_enum_value"]
            for e in _ROLES.values()
            if e.get("status") == "active" and e.get("role_enum_value") is not None
        }
        assert set(_CONTENT_ROLES) == active - {"student"}


# ──────────────────────────────────────────────────────────────────────────
# 변별력(계약 축, acceptance ④) — "또래 비교 × 부모"를 none→full로 훼손 → red → 복원 → green
# ──────────────────────────────────────────────────────────────────────────
class TestMdSyncViolationDetectorIsDiscriminating:
    def test_baseline_contract_is_clean(self) -> None:
        assert _md_sync_violations(_ITEMS, _MD_ROWS) == []

    def test_corrupting_peer_comparison_parent_cell_is_detected(self) -> None:
        """원본 파일은 건드리지 않는다 — 로드된 dict의 깊은 복사본만 훼손한다."""
        corrupted = json.loads(json.dumps(_ITEMS))
        assert corrupted["peer_comparison"]["resolution"]["parent"] == "none"
        corrupted["peer_comparison"]["resolution"]["parent"] = "full"  # 훼손

        violations = _md_sync_violations(corrupted, _MD_ROWS)  # → red 실측
        assert any("또래 비교" in v and "parent" in v for v in violations), (
            "\n".join(violations) or "훼손이 red를 내지 못함"
        )

        corrupted["peer_comparison"]["resolution"]["parent"] = "none"  # 복원
        assert _md_sync_violations(corrupted, _MD_ROWS) == []  # → green 재확인


# ──────────────────────────────────────────────────────────────────────────
# ⓑ Role enum ↔ 계약 roles 축 정합 + 변별력(역할 축, acceptance ⑤)
# ──────────────────────────────────────────────────────────────────────────
class TestRoleEnumSyncsWithContract:
    def test_current_role_enum_has_no_sync_violations(self) -> None:
        active_values = frozenset(member.value for member in Role)
        violations = _role_sync_violations(active_values, _ROLES)
        assert violations == [], "\n".join(violations)

    def test_teacher_and_parent_are_declared_planned_not_active(self) -> None:
        for role_key in ("teacher", "parent"):
            entry = _ROLES[role_key]
            assert entry["status"] == "planned", f"roles.{role_key}.status는 아직 planned여야 함"
            assert entry["role_enum_value"] is None, f"roles.{role_key}.role_enum_value는 아직 None"


class TestRoleSyncViolationDetectorIsDiscriminating:
    """acceptance ⑤ — 실 `Role` enum 파일은 건드리지 않는다(CLAUDE.md 절대 금기 ⑦).

    검사 로직을 순수 함수(`_role_sync_violations`)로 분리했으므로, "PARENT가 Role enum에 추가된"
    상황을 *합성 역할 값 집합*으로만 시뮬레이션한다 — 프로세스 전역 상태(진짜 Role 클래스)는
    한 줄도 바뀌지 않는다(COLLAB-02가 실 `Base.metadata` 대신 합성 `MetaData`를 쓴 것과 동일 원칙).
    """

    def test_baseline_synthetic_set_matching_real_role_enum_is_clean(self) -> None:
        baseline = frozenset(member.value for member in Role)
        assert _role_sync_violations(baseline, _ROLES) == []

    def test_adding_parent_without_contract_promotion_is_red(self) -> None:
        synthetic = frozenset(member.value for member in Role) | {"parent"}
        violations = _role_sync_violations(synthetic, _ROLES)  # → red 실측
        assert any("parent" in v for v in violations), (
            "Role enum에 PARENT가 추가됐는데 계약(access_matrix.json roles.parent)이 여전히 "
            "status=planned면 이 검사가 red를 내야 한다 — Phase 3 역할 개방 전에 계약을 먼저 "
            "승격하라는 강제가 이 태스크의 존재 이유(collaboration_module_gap_review.md §3 D1)."
        )

    def test_promoting_contract_role_clears_the_violation(self) -> None:
        """원본 계약은 미변경 — roles 딕셔너리의 깊은 복사본만 승격해 red→green 왕복을 실측한다."""
        promoted_roles = json.loads(json.dumps(_ROLES))
        promoted_roles["parent"]["status"] = "active"
        promoted_roles["parent"]["role_enum_value"] = "parent"
        synthetic = frozenset(member.value for member in Role) | {"parent"}

        assert _role_sync_violations(synthetic, promoted_roles) == []  # → green 재확인
        # 원본 _ROLES는 이 테스트로 인해 바뀌지 않았음을 재확인(다음 테스트 오염 방지).
        assert _ROLES["parent"]["status"] == "planned"


# ──────────────────────────────────────────────────────────────────────────
# ⓒ 선형 서열 비전제 실측(test_role_enum.py 승계·보완 — 타입이 아니라 데이터)
# ──────────────────────────────────────────────────────────────────────────
class TestMatrixDataContradictsAnyLinearRoleOrdering:
    def test_item_3_wrong_answer_pattern_shows_parent_is_not_a_superset_of_student(self) -> None:
        """`schema/enums.py` Role docstring의 구체 근거 — #3 오답 패턴: 학생 full·부모 none.

        보호자가 피보호자보다 '상위' 역할이라는 흔한 직관(선형 서열의 전형적 동기)이 맞다면
        부모 해상도가 학생 이상이어야 하는데, 실측 값은 정반대(부모 < 학생)다.
        """
        item = _ITEMS["wrong_answer_pattern"]
        assert item["num"] == 3
        assert _rank(item["resolution"]["parent"]) < _rank(item["resolution"]["student"])

    def test_no_permutation_of_the_three_roles_is_a_consistent_total_order(self) -> None:
        """3역할(학생/교사/부모)의 6가지 순열 후보 전부를 9항목 실측치와 대조 — 전부 불일치.

        `student`는 모든 항목에서 다른 둘 이상으로 지배적이나(교사·부모 모두 `student` 이하),
        `teacher`·`parent`는 서로 지배 관계가 일관되지 않는다(#1 정답률: 교사 full > 부모 summary
        vs #4 이용 시간대: 교사 none < 부모 summary — 방향이 뒤집힌다). 따라서 어느 전역 순서
        가설을 세워도 9항목 전부를 만족시키는 순열이 존재하지 않는다 — Role이 `<`/`>`를 봉인한
        설계가 실제 데이터로도 정당화됨을 기계로 확인한다.
        """
        ranks = {
            item_id: {role: _rank(item["resolution"][role]) for role in _PIPA_ROLE_COLUMNS}
            for item_id, item in _ITEMS.items()
        }
        consistent_orders = [
            order
            for order in permutations(_PIPA_ROLE_COLUMNS)
            if all(ranks[i][order[0]] <= ranks[i][order[1]] <= ranks[i][order[2]] for i in ranks)
        ]
        assert consistent_orders == [], (
            f"9항목 전체와 일관된 순열이 존재함: {consistent_orders} — "
            "선형 서열이 실제로 가능하다는 뜻인데, 이는 '부모 가시성은 학생의 부분집합이지 "
            "상위집합이 아니다'라는 설계 전제와 모순"
        )

    def test_teacher_and_parent_flip_relative_order_between_item_1_and_item_4(self) -> None:
        """위 전수 검사의 구체 반례 하나 — 회귀 시 어느 두 항목이 깨졌는지 바로 가리킨다."""
        answer_rate = _ITEMS["answer_rate"]
        usage_time = _ITEMS["usage_time_of_day"]
        assert answer_rate["num"] == 1 and usage_time["num"] == 4
        rate_teacher = _rank(answer_rate["resolution"]["teacher"])
        rate_parent = _rank(answer_rate["resolution"]["parent"])
        usage_teacher = _rank(usage_time["resolution"]["teacher"])
        usage_parent = _rank(usage_time["resolution"]["parent"])
        assert rate_teacher > rate_parent
        assert usage_teacher < usage_parent


# ──────────────────────────────────────────────────────────────────────────
# ⓓ produced_by(산출물 매핑) 완전성 + 변별력
# ──────────────────────────────────────────────────────────────────────────
class TestProducedByMappingCompleteness:
    def test_no_produced_by_violations_in_real_contract(self) -> None:
        assert _produced_by_violations(_ITEMS) == []

    @pytest.mark.parametrize("item_id", sorted(_ITEMS))
    def test_item_has_nonempty_produced_by(self, item_id: str) -> None:
        produced_by = _ITEMS[item_id]["produced_by"]
        assert isinstance(produced_by, list) and produced_by

    def test_detector_flags_item_with_missing_produced_by(self) -> None:
        broken = json.loads(json.dumps(_ITEMS))
        broken["answer_rate"]["produced_by"] = []  # 훼손

        violations = _produced_by_violations(broken)  # → red 실측
        assert any("answer_rate" in v for v in violations), "\n".join(violations)

        broken["answer_rate"]["produced_by"] = _ITEMS["answer_rate"]["produced_by"]  # 복원
        assert _produced_by_violations(broken) == []  # → green 재확인
