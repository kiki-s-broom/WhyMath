"""Phase 1 구조 지표 5종 단일 화면 리포터 — 계획서 200 §36 (EOS-08).

⚠️ **이것은 판정기가 아니다** (acceptance ②)
--------------------------------------------
12/31 판정의 유일한 재료는 `ops/validation_scorecard.py`다(선언이 동결한 Hard Gate F-Ⅰ~Ⅴ +
KPI 12종). 이 모듈은 그것을 **대체하지도 보완하지도 않는다** — 축이 다르다. 스코어카드는
*AI 콘텐츠 생산 가능성*을 재고, 여기 5종은 *구조 계약이 얼마나 섰는가*를 잰다.

두 도구가 서로 다른 합격을 말하면 "무엇을 통과했는가"가 결정 불가가 된다. 그래서 이 모듈은
**exit code로 합격을 선언하지 않는다** — 산출에 성공하면 0, 산출 자체가 실패하면 1이다.
지표 값이 나쁘다고 1을 내지 않는다(그 판정은 사람과 스코어카드의 몫이다).

미측정 ≠ 0 (acceptance ③)
-------------------------
산출할 수 없는 지표는 **0이 아니라 `measured=False`**로 낸다(`weekly_metrics_report.KpiValue`
선례 그대로). 0%는 "그 축이 전혀 안 됐다"로 읽히고, 미측정은 "재는 방법이 없다"는 뜻이다 —
둘을 뭉개면 인프라가 죽었을 때 "0건 통과"로 위장된다.

정의를 먼저 적고 센다 (acceptance ⑤)
------------------------------------
비율 2종은 저장소에 정의가 없었다. **분모를 계획서에 고정**해 자의적 확대를 막는다:

  ① Contract coverage
     분모 = 계획서 200 §27이 **명시적으로 열거한 계약 검사 6종**(고정 — 늘리려면 계획서가
            바뀌어야 한다).
     분자 = 그중 **기계 집행 지점이 실재하는** 검사 수. "실재"는 파일이 있고 그 안에 지목한
            심볼·문자열이 있는 것으로 판정한다(존재 주장은 경로를 댄다).
     이 비율이 말하지 **않는** 것: 그 검사가 *옳은지*, *충분한지*. 집행 지점의 유무만이다.

  ② Vertical Slice pass %
     분모 = 계획서 200 §39가 열거한 **관통 단계 12종**(고정).
     분자 = E2E 통합테스트가 **단언으로 덮는** 단계 수. 근거는 테스트 파일의 실제 내용이며,
            단계마다 "어느 파일의 무엇이 그 단계를 단언하는가"를 함께 낸다.
     이 비율이 말하지 **않는** 것: 그 테스트가 지금 *통과하는지*. 그것은 CI 잡의 판정이고,
            여기서는 **덮는 범위**만 잰다(이름이 'pass %'인 계획서 어휘를 유지하되 정의를
            이렇게 좁힌다 — 실행 결과를 재는 것처럼 보이게 두면 그것이 위장이다).

산출식을 재발명하지 않는다 (acceptance ④)
-----------------------------------------
Data integrity는 `ops/integrity_violations_gate`를, 의존 선언은 `scripts/harness/
dep_declaration`을, 기능 장부는 `backlog/inventory/feature_inventory.yaml`을 그대로 읽는다.
같은 숫자를 두 곳에서 다르게 계산하면 어느 쪽이 맞는지 아무도 모른다.

7계층: INFRA(운영 관측). 서빙 경로가 아니며 학생 데이터를 읽지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CONTRACT_CHECKS",
    "Metric",
    "Phase1Report",
    "SLICE_STAGES",
    "build_report",
    "main",
]

_REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True, slots=True)
class Metric:
    """지표 1건 — `measured=False`면 `value`는 **반드시** None(0으로 위장 금지)."""

    name: str
    measured: bool
    value: float | int | None
    unit: str
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "measured": self.measured,
            "value": self.value,
            "unit": self.unit,
            "detail": self.detail,
        }


# ──────────────────────────────────────────────────────────────────────
# ① Contract coverage — 분모는 계획서 200 §27의 6종(고정)
#
# 각 항목: (계획서 문면, 집행 지점 경로, 그 파일 안에 있어야 하는 심볼/문자열)
# 집행 지점이 옮겨지면 이 표를 함께 고쳐야 한다 — 그러라고 경로를 박아 둔다.
# ──────────────────────────────────────────────────────────────────────
CONTRACT_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "모든 Problem은 최소 1개 Skill과 연결되는가",
        "src/backend/whymath_backend/ops/integrity_violations_gate.py",
        "def skill_coverage",  # 지표로 분리(EOS-07) — 차단 kind가 아니다
    ),
    (
        "모든 Skill의 Concept ID가 존재하는가",
        "src/backend/whymath_backend/ops/integrity_violations_gate.py",
        "KIND_ORPHAN_SKILL",
    ),
    (
        "모든 Misconception의 target Skill이 존재하는가",
        "tests/backend/l1/test_misconception_enrichment_governance.py",
        "def test_behavior_skills_reference_existing_skills",
    ),
    (
        "모든 Curriculum mapping target이 존재하는가",
        "src/backend/whymath_backend/ops/integrity_violations_gate.py",
        "KIND_DANGLING_CURRICULUM_REF",
    ),
    (
        "모든 published entity의 version이 존재하는가",
        "src/backend/whymath_backend/ops/integrity_violations_gate.py",
        "KIND_PUBLISHED_VERSION_INVALID",
    ),
    (
        "Math Adapter가 Subject Contract를 준수하는가",
        "tests/backend/schema/test_subject_adapter.py",
        "def test_math_adapter_satisfies_protocol_at_runtime",
    ),
)

# ──────────────────────────────────────────────────────────────────────
# ② Vertical Slice — 분모는 계획서 200 §39의 관통 단계 12종(고정)
#
# 각 항목: (단계, 단언 근거 파일, 그 파일 안에 있어야 하는 문자열). 근거가 **없는** 단계는
# 빈 문자열로 두고 그 사실을 그대로 낸다 — "아직 안 덮는다"를 숨기지 않는다.
# ──────────────────────────────────────────────────────────────────────
_E2E = "tests/backend/api/test_e2e_vertical_slice_integration.py"
SLICE_STAGES: tuple[tuple[str, str, str], ...] = (
    ("교육과정 선택", "", ""),
    ("Objective 조회", "", ""),
    ("Concept 조회", _E2E, "/v1/me/diagnosis/concepts"),
    ("Skill 조회", _E2E, "_skill_node"),
    ("문제 추천", _E2E, "/v1/me/next-problem"),
    ("학생 답 제출", _E2E, "/v1/coach/sessions"),
    ("Math Adapter 판정", _E2E, "/v1/verify-solution"),
    ("오개념 판정", "", ""),
    ("Assessment Evidence 생성", _E2E, "skill_ids"),
    ("Skill Mastery 변경", _E2E, "SkillMasteryHistory"),
    ("다음 Concept/Problem 추천", _E2E, "after_rec"),
    ("모든 Event 저장", _E2E, "_fetch_completion_events"),
)


@dataclass(frozen=True, slots=True)
class Phase1Report:
    metrics: tuple[Metric, ...]

    def to_json(self) -> dict[str, Any]:
        return {"metrics": [m.to_json() for m in self.metrics]}


def _evidence_exists(rel_path: str, needle: str) -> bool:
    """근거 파일이 있고 그 안에 지목한 문자열이 있는가 — 존재 주장은 경로를 댄다."""
    if not rel_path or not needle:
        return False
    path = _REPO_ROOT / rel_path
    if not path.is_file():
        return False
    return needle in path.read_text(encoding="utf-8", errors="replace")


def _contract_coverage() -> Metric:
    covered = [c for c in CONTRACT_CHECKS if _evidence_exists(c[1], c[2])]
    missing = [c[0] for c in CONTRACT_CHECKS if c not in covered]
    total = len(CONTRACT_CHECKS)
    return Metric(
        name="Contract coverage",
        measured=True,
        value=round(len(covered) / total * 100, 1),
        unit="%",
        detail=(
            f"계획서 200 §27의 계약 검사 {total}종 중 집행 지점 실재 {len(covered)}종"
            + (f" · 미실재: {', '.join(missing)}" if missing else " · 전건 실재")
        ),
    )


def _vertical_slice_coverage() -> Metric:
    covered = [s for s in SLICE_STAGES if _evidence_exists(s[1], s[2])]
    missing = [s[0] for s in SLICE_STAGES if s not in covered]
    total = len(SLICE_STAGES)
    return Metric(
        name="Vertical Slice pass %",
        measured=True,
        value=round(len(covered) / total * 100, 1),
        unit="%",
        detail=(
            f"계획서 200 §39의 관통 단계 {total}종 중 E2E가 단언으로 덮는 것 {len(covered)}종"
            + (f" · 미커버: {', '.join(missing)}" if missing else " · 전건 커버")
            + " ※ '덮는 범위'이지 '실행 통과'가 아니다(통과 판정은 CI 잡의 몫)"
        ),
    )


def _eos_migration_percent() -> Metric:
    """이관 완료율 — **측정 불가**다. 0%로 내면 정반대로 읽힌다.

    `feature_inventory.yaml`의 `migration_action`(KEEP/REFACTOR/HEAVY_REFACTOR/
    REPLACE_CANDIDATE)은 *무엇을 할 계획인가*이지 *얼마나 했는가*가 아니다. 진척을 담는 필드가
    장부에 없으므로 분자가 성립하지 않는다 — 있는 척하지 않는다.
    """
    inventory = _REPO_ROOT / "backlog" / "inventory" / "feature_inventory.yaml"
    if not inventory.is_file():
        reason = f"기능 장부 부재: {inventory.relative_to(_REPO_ROOT)}"
    else:
        reason = (
            "장부의 migration_action은 *계획*이지 진척이 아니다 — 이관 '완료' 상태를 담는 필드가 "
            "없어 분자가 성립하지 않는다. 진척 축이 생기기 전까지 이 지표는 낼 수 없다"
        )
    return Metric(name="EOS migration %", measured=False, value=None, unit="%", detail=reason)


def _broken_dependency_count() -> Metric:
    """의존 위반 — 대장 선언↔집행 축만 센다. 축이 다른 것을 합치지 않는다.

    이 저장소에는 "의존"이 세 축으로 갈려 있다: (a) 백로그 선언↔`depends_on` 집행
    (b) 아키텍처 import 방향(import-linter) (c) git 흐름 drift. 셋을 더하면 단위가 다른 것을
    합친 수가 되므로, 여기서는 **(a)만** 세고 (b)는 CI 계약이 pass/fail로 따로 판정한다는
    사실을 detail에 적는다.
    """
    harness_dir = str(_REPO_ROOT / "scripts" / "harness")
    if harness_dir not in sys.path:
        sys.path.insert(0, harness_dir)
    try:
        import dep_declaration  # noqa: PLC0415  (경로 주입 후 지연 import)
        from store import load_backlog  # noqa: PLC0415  (대장 로더 정본 — 재발명 0)
    except Exception as exc:  # 측정 실패를 0으로 위장하지 않는다
        return Metric(
            name="Broken dependency count",
            measured=False,
            value=None,
            unit="건",
            detail=f"의존 감사 모듈 적재 실패({type(exc).__name__}) — 0이 아니라 미측정이다",
        )
    try:
        backlog, _errors = load_backlog(_REPO_ROOT / "backlog")
        violations = dep_declaration.find_soft_declaration_violations(backlog.tasks)
    except Exception as exc:
        return Metric(
            name="Broken dependency count",
            measured=False,
            value=None,
            unit="건",
            detail=f"감사 실행 실패({type(exc).__name__}) — 0이 아니라 미측정이다",
        )
    return Metric(
        name="Broken dependency count",
        measured=True,
        value=len(violations),
        unit="건",
        detail=(
            "백로그 선언↔depends_on 집행 불일치 건수(dep_declaration). "
            "아키텍처 import 방향은 축이 달라 합치지 않는다 — lint-imports가 pass/fail로 별도 판정"
        ),
    )


async def _data_integrity_violations(database_url: str | None) -> Metric:
    """무결성 위반 — 기존 게이트를 그대로 호출한다(산출식 재발명 0)."""
    from whymath_backend.db.session import dispose_engine, get_sessionmaker  # noqa: PLC0415
    from whymath_backend.ops import integrity_violations_gate as igate  # noqa: PLC0415

    if database_url is None:
        return Metric(
            name="Data integrity violations",
            measured=False,
            value=None,
            unit="건",
            detail="DB URL 미설정 — 0이 아니라 미측정이다(WHYMATH_DATABASE_URL 확인)",
        )
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            report = await igate.scan_integrity(session)
    except Exception as exc:
        return Metric(
            name="Data integrity violations",
            measured=False,
            value=None,
            unit="건",
            detail=f"DB 도달 실패({type(exc).__name__}) — 0이 아니라 미측정이다",
        )
    finally:
        await dispose_engine()
    scanned = sum(report.scanned.values())
    return Metric(
        name="Data integrity violations",
        measured=True,
        value=len(report.violations),
        unit="건",
        detail=(
            f"integrity_violations_gate {len(igate.ALL_KINDS)}종 · 스캔 대상 {scanned}건. "
            "스캔 대상이 0이면 위반 0은 '깨끗하다'가 아니라 '볼 것이 없었다'이다"
        ),
    )


def build_report(*, database_url: str | None = None) -> Phase1Report:
    return Phase1Report(
        metrics=(
            _contract_coverage(),
            _eos_migration_percent(),
            _broken_dependency_count(),
            asyncio.run(_data_integrity_violations(database_url)),
            _vertical_slice_coverage(),
        )
    )


def render(report: Phase1Report) -> str:
    lines = [
        "=" * 68,
        "Phase 1 구조 지표 5종 (계획서 200 §36) — **판정기가 아니다**",
        "  12/31 판정의 재료는 ops/validation_scorecard.py다(축이 다름·모듈 docstring).",
        "=" * 68,
    ]
    for m in report.metrics:
        if m.measured:
            lines.append(f"[{m.name}] {m.value}{m.unit}")
        else:
            lines.append(f"[{m.name}] **미측정** (0이 아니다)")
        lines.append(f"    {m.detail}")
    lines += [
        "-" * 68,
        "exit 0 = 산출 성공(지표 값의 좋고 나쁨과 무관) · exit 1 = 산출 자체 실패",
        "=" * 68,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.phase1_structure_report",
        description="Phase 1 구조 지표 5종 리포터(계획서 200 §36) — 판정기가 아니다.",
    )
    parser.add_argument("--json", dest="json_path", default=None, help="JSON 저장 경로(선택).")
    args = parser.parse_args(argv)

    from whymath_backend.config import Settings  # noqa: PLC0415

    try:
        database_url: str | None = Settings().database_url
    except Exception:
        database_url = None

    report = build_report(database_url=database_url)
    print(render(report))
    if args.json_path is not None:
        Path(args.json_path).write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON 저장: {args.json_path}")
    # 산출 자체가 실패한 경우만 1 — 지표 값으로 합격을 선언하지 않는다(모듈 docstring).
    return 0 if report.metrics else 1


if __name__ == "__main__":
    sys.exit(main())
