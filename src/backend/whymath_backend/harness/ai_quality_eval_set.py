"""P3-10 AI 품질 평가셋 — 대표 과정(P3-01 미적분Ⅰ·미분)의 튜터 턴 사례: 스키마·결정론 생성·적재.

평가셋은 데이터 파일로 버전 관리한다(`data/corpus/ai_quality_eval_v1/eval_set.jsonl`). 이 모듈은
그 파일을 **코퍼스에서 결정론으로 다시 만드는 규칙**과 **읽는 규칙**을 함께 가진다 — 커밋된 파일이
규칙의 산출과 바이트 동일한지는 테스트가 동결한다(손 편집·코퍼스 표류가 조용히 지나가지 않게).

사례가 담는 것 / 담지 않는 것
-----------------------------
담는다: 사례 id · 종류 · 문항 id · 개념(성취기준 코드·canonical id) · 학생 밴드 · 이번 턴 검증
판정 · 학생이 이미 정답에 닿았는가 · (힌트) 목표 단계·학생 신호·사다리 위치 · (선택) 고른 보기·
**정답 라벨**(기대 오개념 kebab 또는 없음).
담지 않는다: 문항 본문·정답·풀이 단계·보기 본문. 적재 시 승인 문항 코퍼스(`problem_bank_*`)에서
id로 해석한다 — 같은 문항 재료를 두 곳에 두면 진실 원천이 둘이 된다. 문항은 전부 와이매스 자체 생성
코퍼스이며(교과서·평가원 본문 0), 학생 데이터는 0건이다(학생 신호 문장은 합성 고정문).

선정 규칙(결정론 — 사람이 고르지 않는다)
---------------------------------------
- **힌트 사례**: 명세 개념 10개마다, 그 개념을 PRIMARY로 갖는 승인 문항 중 `verify`에 조건·풀이
  단계(3단계 이상)가 있는 것을 `problem_id` 오름차순으로 `HINT_PROBLEMS_PER_CONCEPT`개
  고른다(조건 형태는 식 1개 또는 식 목록 · 정답 대입표는 요구하지 않는다 — 02-09 실근 개수형은
  대입표가 비어 있다). 문항마다 목표 단계 2(학생이 1단계를 적고 막힘)의 힌트 사다리 L1·L2·L3
  세 턴을 만든다.
  단계는 학생 신호로 정해지며(`l4.hint_deferral.decide_hint_level` — 생성 시 그 함수로 대조한다):
  L1 = 신호 없음, L2 = 좌절 신호("모르겠어요") + 직전 1, L3 = 5회 막힘 + 직전 2.
- **선택 사례**: 명세 개념마다, 보기·오답 매핑(`distractor_map`)이 있는 승인 객관식 문항 중
  런타임 카탈로그(`CATALOG_BY_ID`)에 있는 오개념을 가리키는 오답 보기가 1개 이상이고 정답 보기가
  정확히 1개인 것을 `problem_id` 오름차순으로 `CHOICE_PROBLEMS_PER_CONCEPT`개 고른다. 문항마다 오답
  보기(최대 `WRONG_CHOICES_PER_PROBLEM`개 · 보기 번호 오름차순 · 라벨 = 그 kebab)와 정답 보기
  1개(라벨 = 오개념 없음)를 사례로 만든다.

N의 근거
--------
축마다 판정 대상이 60건 이상이 되도록 정했다. 실패율 상한 0.05(Wilson 단측 95%)를 **실패 0건으로**
통과하려면 표본이 53건 이상이어야 한다(0/53 상한 = 0.0486). 60은 그 문턱 위이고, 대표 과정의 문항
수량 목표(핵심 개념 10 × 슬롯 6 = 60 · 명세 항 8)와 같은 크기다. 힌트 사례는 10개념 × 6문항 × 3턴 =
180건이고, 수학적 정확성 축의 분모는 그중 식을 싣는 L3 턴(60)이 주로 채운다. 오개념 축은 선택 문항이
있는 개념에서만 나온다(2026-10-21 실측: 9개 개념 64건 — 02-06은 카탈로그 kebab을 가리키는 오답 0) —
실제 건수는 리포트가 매번 출력한다.

라벨의 독립성(정직)
-------------------
오개념 라벨은 문항의 **승인된** `distractor_map`에서 온다. 결정론 진단기(`distractor_link`)도 같은
매핑을 읽으므로, 결정론 후보로 잰 이 축의 점수는 독립 정확도가 아니라 **회귀 감시**다. 독립 정확도
증거는 외부 응답(`--responses`)이나 골든(EOS-60 · MP-03)의 몫이다.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from whymath_backend.harness.ai_quality_registry import Registry, default_repo_root
from whymath_backend.l1.standards import phase3_coverage as p3c
from whymath_backend.l4.hint_deferral import decide_hint_level
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.schema.speech import SpeechGradeBand

__all__ = [
    "CASE_SCHEMA",
    "CHOICE_PROBLEMS_PER_CONCEPT",
    "DEFAULT_EVAL_SET",
    "HINT_LEVEL_SIGNALS",
    "HINT_PROBLEMS_PER_CONCEPT",
    "HINT_TARGET_STEP",
    "KIND_CHOICE",
    "KIND_HINT",
    "WRONG_CHOICES_PER_PROBLEM",
    "EvalCase",
    "EvalSet",
    "EvalSetError",
    "HintSignals",
    "ProblemMaterial",
    "build_cases",
    "dump_cases",
    "load_eval_set",
    "parse_cases",
]

CASE_SCHEMA: Final = "ai-quality-eval-case/v1"
KIND_HINT: Final = "hint"
KIND_CHOICE: Final = "choice"
_KINDS: Final = frozenset({KIND_HINT, KIND_CHOICE})
_VERDICTS: Final = frozenset({"correct", "incorrect", "unverifiable"})

DEFAULT_EVAL_SET: Final = Path("data/corpus/ai_quality_eval_v1/eval_set.jsonl")
_PROBLEM_GLOB: Final = "data/corpus/problem_bank_*/problems.jsonl"

HINT_PROBLEMS_PER_CONCEPT: Final = 6
HINT_TARGET_STEP: Final = 2
CHOICE_PROBLEMS_PER_CONCEPT: Final = 3
WRONG_CHOICES_PER_PROBLEM: Final = 2
_MIN_HINT_STEPS: Final = 3


class EvalSetError(RuntimeError):
    """평가셋 생성·적재 실패 — 측정 실패로 올린다(0건·참조 부재를 통과로 접지 않는다)."""


@dataclass(frozen=True)
class HintSignals:
    """힌트 단계를 정하는 학생 신호 — `decide_hint_level`의 입력 그대로."""

    student_input: str
    turn_count: int
    prev_hint_level: int | None


#: 사다리 위치(1~3) → 학생 신호. 합성 고정문이다(학생 데이터 아님).
HINT_LEVEL_SIGNALS: Final[Mapping[int, HintSignals]] = {
    1: HintSignals("어디서부터 손대야 할지 생각 중이에요", 1, None),
    2: HintSignals("잘 모르겠어요", 2, 1),
    3: HintSignals("모르겠어요", 5, 2),
}


@dataclass(frozen=True)
class EvalCase:
    """튜터 턴 1건의 평가 사례(입력 + 라벨). 문항 재료는 `ProblemMaterial`로 따로 해석한다."""

    case_id: str
    kind: str
    problem_id: str
    concept_code: str
    concept_id: str
    student_band: str
    verdict: str | None
    """이번 턴 검증 판정 — 힌트 사례는 새 단계가 없어 None, 선택 사례는 correct/incorrect."""
    answer_known_to_student: bool
    target_step: int | None = None
    signals: HintSignals | None = None
    ladder_id: str | None = None
    ladder_pos: int | None = None
    selected_choice_index: int | None = None
    misconception_labeled: bool = False
    expected_misconception_id: str | None = None


@dataclass(frozen=True)
class ProblemMaterial:
    """사례가 가리키는 문항 재료 — 승인 문항 코퍼스에서 해석(평가셋 파일에는 없다)."""

    problem_id: str
    problem_uuid: uuid.UUID
    answer: str
    conditions: tuple[str, ...]
    """`verify.conditions` — 식 1개면 길이 1, 식 목록이면 그대로(없으면 빈 튜플)."""
    solution_steps: tuple[str, ...]
    choices: tuple[str, ...]
    distractor_map: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class EvalSet:
    """적재된 평가셋 — 사례 + 문항 재료 + 파일 지문(이번 실행이 어느 평가셋인지)."""

    cases: tuple[EvalCase, ...]
    materials: Mapping[str, ProblemMaterial]
    source: str
    sha256: str


# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 스캔
# ──────────────────────────────────────────────────────────────────────────
def _scan_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    paths = sorted(root.glob(_PROBLEM_GLOB))
    if not paths:
        raise EvalSetError("문항 코퍼스 0개 — problem_bank_*/problems.jsonl 이 없다")
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise EvalSetError(f"{path}: 읽지 못했다 ({type(exc).__name__})") from exc
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalSetError(f"{path}:{number}: {type(exc).__name__}") from exc
            if isinstance(row, dict):
                rows.append(row)
    if not rows:
        raise EvalSetError("문항 레코드 0건")
    return rows


def _eligible_primary(row: Mapping[str, Any]) -> frozenset[str]:
    """승인 문항이면 PRIMARY 개념 src id 집합, 아니면 빈 집합(P3-06·P3-14와 같은 변환)."""
    ref = p3c.problem_ref_from_row(row)
    if ref is None or ref.review_status != p3c.PROBLEM_ELIGIBLE_STATUS:
        return frozenset()
    return ref.primary_src_ids


def _verify_of(row: Mapping[str, Any]) -> Mapping[str, Any]:
    verify = row.get("verify")
    return verify if isinstance(verify, dict) else {}


def _norm_choice(text: str) -> str:
    return "".join(text.split())


def _correct_index(row: Mapping[str, Any]) -> int | None:
    """정답 보기 인덱스 — 공백 제거 문자열 일치가 정확히 1개일 때만(모호하면 쓰지 않는다)."""
    choices = row.get("choices")
    answer = row.get("answer")
    if not isinstance(choices, list) or not isinstance(answer, str):
        return None
    hits = [
        i
        for i, c in enumerate(choices)
        if isinstance(c, str) and _norm_choice(c) == _norm_choice(answer)
    ]
    return hits[0] if len(hits) == 1 else None


def _conditions_of(verify: Mapping[str, Any]) -> tuple[str, ...]:
    """`verify.conditions` → 조건식 튜플(문자열 1개 또는 문자열 목록). 형태가 다르면 빈 튜플."""
    raw = verify.get("conditions")
    if isinstance(raw, str):
        return (raw,) if raw.strip() else ()
    if isinstance(raw, list) and raw and all(isinstance(c, str) and c.strip() for c in raw):
        return tuple(raw)
    return ()


def _hint_ready(row: Mapping[str, Any]) -> bool:
    verify = _verify_of(row)
    steps = verify.get("solution_steps")
    return (
        bool(_conditions_of(verify))
        and isinstance(steps, list)
        and len(steps) >= _MIN_HINT_STEPS
        and all(isinstance(s, str) and s.strip() for s in steps)
        and isinstance(row.get("answer"), str)
        and bool(str(row.get("answer")).strip())
    )


def _catalog_wrong_entries(row: Mapping[str, Any], correct: int) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    choices = row.get("choices")
    n = len(choices) if isinstance(choices, list) else 0
    for entry in row.get("distractor_map") or []:
        if not isinstance(entry, dict):
            continue
        index = entry.get("choice_index")
        kebab = entry.get("misconception_id")
        if (
            isinstance(index, int)
            and not isinstance(index, bool)
            and 0 <= index < n
            and index != correct
            and isinstance(kebab, str)
            and kebab in CATALOG_BY_ID
        ):
            entries.append((index, kebab))
    return sorted(set(entries))


# ──────────────────────────────────────────────────────────────────────────
# 생성(결정론)
# ──────────────────────────────────────────────────────────────────────────
def build_cases(registry: Registry, repo_root: Path | None = None) -> list[EvalCase]:
    """코퍼스 → 평가 사례(결정론). 같은 코퍼스·명세면 같은 목록이다."""
    rows = _scan_rows(repo_root or default_repo_root())
    band = SpeechGradeBand.고등.value  # 대표 과정 = 고2(명세 항 2 school_level 고등학교)
    if registry.scope.school_level != "고등학교":
        raise EvalSetError(f"명세 학교급이 고등학교가 아니다: {registry.scope.school_level!r}")
    by_src: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for src in _eligible_primary(row):
            by_src.setdefault(src, []).append(row)

    cases: list[EvalCase] = []
    for c_index, concept in enumerate(registry.scope.concepts, start=1):
        pool = sorted(by_src.get(concept.source_id, []), key=lambda r: str(r.get("problem_id")))
        hint_rows = [r for r in pool if _hint_ready(r)][:HINT_PROBLEMS_PER_CONCEPT]
        for p_index, row in enumerate(hint_rows, start=1):
            ladder = f"lad-{c_index:02d}-{p_index:02d}"
            for level, signals in HINT_LEVEL_SIGNALS.items():
                engine = decide_hint_level(
                    student_input=signals.student_input,
                    turn_count=signals.turn_count,
                    prev_hint_level=signals.prev_hint_level,
                )
                if engine != level:
                    raise EvalSetError(
                        f"사다리 신호가 엔진 단계와 어긋난다(위치 {level} → 엔진 {engine})"
                    )
                cases.append(
                    EvalCase(
                        case_id=f"aq-h-{c_index:02d}-{p_index:02d}-l{level}",
                        kind=KIND_HINT,
                        problem_id=str(row["problem_id"]),
                        concept_code=concept.code,
                        concept_id=concept.concept_id,
                        student_band=band,
                        verdict=None,
                        answer_known_to_student=False,
                        target_step=HINT_TARGET_STEP,
                        signals=signals,
                        ladder_id=ladder,
                        ladder_pos=level,
                    )
                )
        picked = 0
        for row in pool:
            if picked >= CHOICE_PROBLEMS_PER_CONCEPT:
                break
            correct = _correct_index(row)
            if correct is None or not row.get("distractor_map"):
                continue
            wrong = _catalog_wrong_entries(row, correct)[:WRONG_CHOICES_PER_PROBLEM]
            if not wrong:
                continue
            picked += 1
            base = f"aq-c-{c_index:02d}-{picked:02d}"
            for index, kebab in wrong:
                cases.append(
                    EvalCase(
                        case_id=f"{base}-w{index}",
                        kind=KIND_CHOICE,
                        problem_id=str(row["problem_id"]),
                        concept_code=concept.code,
                        concept_id=concept.concept_id,
                        student_band=band,
                        verdict="incorrect",
                        answer_known_to_student=False,
                        selected_choice_index=index,
                        misconception_labeled=True,
                        expected_misconception_id=kebab,
                    )
                )
            cases.append(
                EvalCase(
                    case_id=f"{base}-c{correct}",
                    kind=KIND_CHOICE,
                    problem_id=str(row["problem_id"]),
                    concept_code=concept.code,
                    concept_id=concept.concept_id,
                    student_band=band,
                    verdict="correct",
                    answer_known_to_student=True,
                    selected_choice_index=correct,
                    misconception_labeled=True,
                    expected_misconception_id=None,
                )
            )
    if not cases:
        raise EvalSetError("평가 사례 0건 — 선정 규칙이 아무것도 고르지 못했다")
    return cases


def _case_to_json(case: EvalCase) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema": CASE_SCHEMA,
        "case_id": case.case_id,
        "kind": case.kind,
        "problem_id": case.problem_id,
        "concept_code": case.concept_code,
        "concept_id": case.concept_id,
        "student_band": case.student_band,
        "verdict": case.verdict,
        "answer_known_to_student": case.answer_known_to_student,
    }
    if case.kind == KIND_HINT:
        assert case.signals is not None
        out["target_step"] = case.target_step
        out["ladder_id"] = case.ladder_id
        out["ladder_pos"] = case.ladder_pos
        out["signals"] = {
            "student_input": case.signals.student_input,
            "turn_count": case.signals.turn_count,
            "prev_hint_level": case.signals.prev_hint_level,
        }
    else:
        out["selected_choice_index"] = case.selected_choice_index
        out["expected_misconception_id"] = case.expected_misconception_id
    return out


def dump_cases(cases: Sequence[EvalCase]) -> str:
    """사례 → JSONL 텍스트(키 정렬·한글 그대로 — 바이트 결정론)."""
    return "".join(
        json.dumps(_case_to_json(c), ensure_ascii=False, sort_keys=True) + "\n" for c in cases
    )


# ──────────────────────────────────────────────────────────────────────────
# 적재(엄격)
# ──────────────────────────────────────────────────────────────────────────
def _req(row: Mapping[str, Any], key: str, kind: type | tuple[type, ...], where: str) -> Any:
    if key not in row:
        raise EvalSetError(f"{where}: 필드 {key!r} 결손")
    value = row[key]
    if isinstance(value, bool) and kind is not bool:
        raise EvalSetError(f"{where}: {key!r}가 bool이다")
    if not isinstance(value, kind):
        raise EvalSetError(f"{where}: {key!r} 타입 위반({type(value).__name__})")
    return value


def parse_cases(text: str, *, source: str = "<text>") -> tuple[EvalCase, ...]:
    """JSONL → 사례. 구조 위반·중복 id·사다리 결손은 `EvalSetError`."""
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{source}:{number}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalSetError(f"{where}: {type(exc).__name__}") from exc
        if not isinstance(row, dict) or row.get("schema") != CASE_SCHEMA:
            raise EvalSetError(f"{where}: schema 가 {CASE_SCHEMA!r} 가 아니다")
        kind = _req(row, "kind", str, where)
        if kind not in _KINDS:
            raise EvalSetError(f"{where}: 알 수 없는 kind {kind!r}")
        case_id = _req(row, "case_id", str, where)
        if case_id in seen:
            raise EvalSetError(f"{where}: 중복 case_id {case_id!r}")
        seen.add(case_id)
        verdict = row.get("verdict")
        if verdict is not None and verdict not in _VERDICTS:
            raise EvalSetError(f"{where}: 알 수 없는 verdict {verdict!r}")
        band = _req(row, "student_band", str, where)
        if band not in {b.value for b in SpeechGradeBand}:
            raise EvalSetError(f"{where}: 알 수 없는 student_band {band!r}")
        common: dict[str, Any] = {
            "case_id": case_id,
            "kind": kind,
            "problem_id": _req(row, "problem_id", str, where),
            "concept_code": _req(row, "concept_code", str, where),
            "concept_id": _req(row, "concept_id", str, where),
            "student_band": band,
            "verdict": verdict,
            "answer_known_to_student": _req(row, "answer_known_to_student", bool, where),
        }
        if kind == KIND_HINT:
            sig = _req(row, "signals", dict, where)
            prev = sig.get("prev_hint_level")
            if prev is not None and (isinstance(prev, bool) or not isinstance(prev, int)):
                raise EvalSetError(f"{where}: prev_hint_level 타입 위반")
            cases.append(
                EvalCase(
                    **common,
                    target_step=_req(row, "target_step", int, where),
                    signals=HintSignals(
                        student_input=_req(sig, "student_input", str, where),
                        turn_count=_req(sig, "turn_count", int, where),
                        prev_hint_level=prev,
                    ),
                    ladder_id=_req(row, "ladder_id", str, where),
                    ladder_pos=_req(row, "ladder_pos", int, where),
                )
            )
        else:
            if "expected_misconception_id" not in row:
                raise EvalSetError(f"{where}: 선택 사례에 라벨(expected_misconception_id)이 없다")
            expected = row["expected_misconception_id"]
            if expected is not None and not isinstance(expected, str):
                raise EvalSetError(f"{where}: expected_misconception_id 타입 위반")
            cases.append(
                EvalCase(
                    **common,
                    selected_choice_index=_req(row, "selected_choice_index", int, where),
                    misconception_labeled=True,
                    expected_misconception_id=expected,
                )
            )
    if not cases:
        raise EvalSetError(f"{source}: 사례 0건 — 빈 평가셋을 통과로 접지 않는다")
    ladders: dict[str, list[int]] = {}
    for case in cases:
        if case.ladder_id is not None and case.ladder_pos is not None:
            ladders.setdefault(case.ladder_id, []).append(case.ladder_pos)
    for ladder, positions in ladders.items():
        if sorted(positions) != list(range(1, len(positions) + 1)):
            raise EvalSetError(f"{source}: 사다리 {ladder} 위치가 1..n 연속이 아니다 {positions}")
    return tuple(cases)


def _material(row: Mapping[str, Any]) -> ProblemMaterial:
    verify = _verify_of(row)
    steps = verify.get("solution_steps")
    choices = row.get("choices")
    dmap = row.get("distractor_map")
    pid = str(row["problem_id"])
    try:
        puuid = uuid.UUID(pid)
    except ValueError as exc:
        raise EvalSetError(f"문항 id가 UUID가 아니다: {pid} ({type(exc).__name__})") from exc
    return ProblemMaterial(
        problem_id=pid,
        problem_uuid=puuid,
        answer=str(row.get("answer") or ""),
        conditions=_conditions_of(verify),
        solution_steps=tuple(str(s) for s in steps) if isinstance(steps, list) else (),
        choices=tuple(str(c) for c in choices) if isinstance(choices, list) else (),
        distractor_map=(
            tuple(d for d in dmap if isinstance(d, dict)) if isinstance(dmap, list) else ()
        ),
    )


def load_eval_set(
    registry: Registry, path: Path | None = None, *, repo_root: Path | None = None
) -> EvalSet:
    """평가셋 파일 + 승인 문항 코퍼스 → `EvalSet`. 참조 부재·미승인·범위 밖은 `EvalSetError`."""
    root = repo_root or default_repo_root()
    target = path or root / DEFAULT_EVAL_SET
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise EvalSetError(f"평가셋을 읽지 못했다 ({target}): {type(exc).__name__}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvalSetError(f"{target}: {type(exc).__name__}") from exc
    cases = parse_cases(text, source=str(target))
    wanted = {c.problem_id for c in cases}
    found: dict[str, ProblemMaterial] = {}
    srcs: dict[str, frozenset[str]] = {}
    for row in _scan_rows(root):
        pid = str(row.get("problem_id"))
        if pid in wanted and pid not in found:
            found[pid] = _material(row)
            srcs[pid] = _eligible_primary(row)
    problems: list[str] = []
    for case in cases:
        material = found.get(case.problem_id)
        if material is None:
            problems.append(f"{case.case_id}: 문항 {case.problem_id} 이 코퍼스에 없다")
            continue
        if case.concept_id not in registry.scope_concepts:
            problems.append(f"{case.case_id}: 개념 {case.concept_id} 이 대표 과정 밖이다")
        concept_src = (
            registry.concepts[case.concept_id].src_id
            if (case.concept_id in registry.concepts)
            else None
        )
        if concept_src is None or concept_src not in srcs[case.problem_id]:
            problems.append(f"{case.case_id}: 승인 문항이 아니거나 PRIMARY 개념이 다르다")
        if case.kind == KIND_HINT:
            steps = len(material.solution_steps)
            if case.target_step is None or not 1 <= case.target_step < steps:
                problems.append(f"{case.case_id}: 목표 단계가 풀이 단계 범위 밖이다")
        elif case.selected_choice_index is None or not (
            0 <= case.selected_choice_index < len(material.choices)
        ):
            problems.append(f"{case.case_id}: 고른 보기가 보기 범위 밖이다")
    if problems:
        head = "; ".join(problems[:5])
        raise EvalSetError(f"평가셋 참조 위반 {len(problems)}건: {head}")
    return EvalSet(
        cases=cases,
        materials=found,
        source=str(target),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
