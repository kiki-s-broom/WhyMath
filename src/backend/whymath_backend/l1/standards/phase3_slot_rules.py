"""기존 문항의 6슬롯 배정 규칙 — 로더·판정기 (P3-05 3단계).

규칙이 필요한 이유
------------------
핵심 개념 3개(02-01·02-02·02-07)의 기존 승인 문항 413건에는 슬롯 태그가 한 건도 없다.
신규 504건은 개념별 생성기의 틀이 슬롯을 정했지만 기존 문항에는 틀이 없다.
이 모듈은 "어느 문항이 어느 슬롯인가"의 기준을
코드가 아니라 **데이터**(`data/corpus/phase3_scope_v1/slot_assignment_rules.yaml`)로 읽어 판정한다.

이 모듈은 판정만 한다
---------------------
코퍼스를 쓰지 않는다. 쓰기는 `harness/problem_slot_backfill`이 이 판정을 받아 한다(정본화 ≠ 집행).
문항 자체 오개념 연결 여부는 계측기의 판정(`phase3_coverage`)과 **같은 기준이어야** 하므로 이 모듈이
직접 계산하지 않고 호출자가 함수로 넘긴다(`reaches`) — 계측기가 "오개념 유발"로 세는
문항과 이 규칙이
"오개념 유발"로 배정하는 문항이 어긋나면 칸이 채워졌다고 믿는 순간에 안 채워져 있다.

판정 규칙 (위에서 아래로, 처음 맞는 규칙이 이긴다)
-----------------------------------------------
  · 어떤 규칙에도 안 맞으면 배정하지 않는다(억지로 채우지 않는다).
  · `slot: null` 규칙에 맞으면 "보류"다 — 태그를 달지 않고 이유를 남긴다.
  · 이미 슬롯 태그가 있는 문항은 규칙을 적용하지 않는다(덮어쓰지 않는다).
  · 규칙의 범위(`banks` 코퍼스 · `scope_concepts` 개념) 밖 문항은 읽지도 않는다.
  · 모르는 것으로 합치지 않는다: 문면을 읽지 못한 문항은 `folded_stem_contains` 조건에 맞지 않는다.

침묵 실패 금지
--------------
알 수 없는 조건 키·슬롯 id·중복 규칙 id·빈 규칙 목록은 `SlotRulesError`로 즉시 실패한다.
오타 난 조건 키가
조용히 무시되면 그 규칙은 "조건 없음"이 되어 범위 안 모든 문항에 맞아 버린다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

from whymath_backend.l1.standards.phase3_coverage import ProblemRef
from whymath_backend.l1.standards.phase3_stem_fold import fold_stem
from whymath_backend.schema.problem_metadata import ProblemSlot, parse_slot_tags

RULES_VERSION: Final = 1
_REPO_ROOT: Final = Path(__file__).resolve().parents[5]
_DEFAULT_RULES: Final = Path("data/corpus/phase3_scope_v1/slot_assignment_rules.yaml")

_WHEN_KEYS: Final = frozenset({"concept", "folded_stem_contains", "has_own_misconception"})
_RULE_KEYS: Final = frozenset({"id", "when", "slot", "reason"})
_TOP_KEYS: Final = frozenset({"version", "banks", "scope_concepts", "rules"})


class SlotRulesError(RuntimeError):
    """규칙 파일이 구조를 어겼다(예외 타입명을 메시지에 싣는 관례를 따른다)."""


@dataclass(frozen=True)
class SlotRule:
    """규칙 1건 — `when`의 조건이 모두 맞으면 `slot`(None=보류)을 배정한다."""

    rule_id: str
    slot: ProblemSlot | None
    concept: str | None
    folded_stem_contains: str | None
    has_own_misconception: bool | None
    reason: str | None


@dataclass(frozen=True)
class SlotRules:
    """규칙 파일 전체 — 범위 개념과 순서 있는 규칙."""

    banks: tuple[str, ...]
    scope_concepts: frozenset[str]
    rules: tuple[SlotRule, ...]


@dataclass(frozen=True)
class SlotDecision:
    """문항 1건의 판정. `slot`이 None이면 태그를 달지 않는다.

    `rule_id`가 None이면 어떤 규칙에도 안 맞은 것이고, 있으면서 `slot`이 None이면 보류다.
    `skipped`는 규칙을 적용하지 않은 이유(범위 밖·이미 슬롯 있음·승인 아님)다.
    판정이 있을 때는 None이다.
    """

    slot: ProblemSlot | None
    rule_id: str | None = None
    reason: str | None = None
    skipped: str | None = None

    @property
    def held(self) -> bool:
        return self.rule_id is not None and self.slot is None


def default_rules_path() -> Path:
    return _REPO_ROOT / _DEFAULT_RULES


def _fail(where: str, message: str) -> SlotRulesError:
    return SlotRulesError(f"{where}: {message}")


def _parse_rule(raw: Any, index: int, scope: frozenset[str]) -> SlotRule:
    where = f"rules[{index}]"
    if not isinstance(raw, Mapping):
        raise _fail(where, f"규칙은 매핑이어야 한다(실제 {type(raw).__name__})")
    unknown = set(raw) - _RULE_KEYS
    if unknown:
        raise _fail(where, f"알 수 없는 키 {sorted(unknown)} — 허용 {sorted(_RULE_KEYS)}")
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise _fail(where, "id 가 비어 있다")
    where = f"rules[{index}]({rule_id})"

    when = raw.get("when")
    if not isinstance(when, Mapping) or not when:
        raise _fail(
            where, "when 은 비어 있지 않은 매핑이어야 한다(조건 없는 규칙은 범위 전체에 맞는다)"
        )
    bad_keys = set(when) - _WHEN_KEYS
    if bad_keys:
        raise _fail(where, f"알 수 없는 조건 키 {sorted(bad_keys)} — 허용 {sorted(_WHEN_KEYS)}")

    concept = when.get("concept")
    if concept is not None:
        if not isinstance(concept, str) or concept not in scope:
            raise _fail(where, f"concept {concept!r} 가 scope_concepts 에 없다")
    contains = when.get("folded_stem_contains")
    if contains is not None and (not isinstance(contains, str) or not contains.strip()):
        raise _fail(where, "folded_stem_contains 는 비어 있지 않은 문자열이어야 한다")
    own = when.get("has_own_misconception")
    if own is not None and not isinstance(own, bool):
        raise _fail(where, f"has_own_misconception 은 true/false 여야 한다(실제 {own!r})")

    if "slot" not in raw:
        raise _fail(where, "slot 키가 없다(보류는 slot: null 로 명시한다)")
    raw_slot = raw["slot"]
    slot: ProblemSlot | None
    if raw_slot is None:
        slot = None
    else:
        valid = {s.value: s for s in ProblemSlot}
        if not isinstance(raw_slot, str) or raw_slot not in valid:
            raise _fail(
                where, f"slot {raw_slot!r} 는 6개 슬롯 id {sorted(valid)} 또는 null 이어야 한다"
            )
        slot = valid[raw_slot]

    reason = raw.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise _fail(where, "reason 은 문자열이어야 한다")
    if slot is None and not (isinstance(reason, str) and reason.strip()):
        raise _fail(
            where,
            "보류(slot: null) 규칙은 reason 이 필수다 — 이유 없는 보류는 누락과 구별되지 않는다",
        )

    return SlotRule(
        rule_id=rule_id,
        slot=slot,
        concept=concept,
        folded_stem_contains=contains,
        has_own_misconception=own,
        reason=reason,
    )


def parse_slot_rules(doc: Any, source: str = "<memory>") -> SlotRules:
    """규칙 문서(이미 파싱된 YAML)를 검증해 `SlotRules`로 만든다."""
    if not isinstance(doc, Mapping):
        raise _fail(source, f"최상위는 매핑이어야 한다(실제 {type(doc).__name__})")
    unknown = set(doc) - _TOP_KEYS
    if unknown:
        raise _fail(source, f"알 수 없는 최상위 키 {sorted(unknown)} — 허용 {sorted(_TOP_KEYS)}")
    if doc.get("version") != RULES_VERSION:
        raise _fail(source, f"version 은 {RULES_VERSION} 이어야 한다(실제 {doc.get('version')!r})")

    raw_banks = doc.get("banks")
    if not isinstance(raw_banks, list) or not raw_banks:
        raise _fail(
            source, "banks 는 비어 있지 않은 목록이어야 한다(규칙이 읽는 코퍼스를 명시한다)"
        )
    if not all(isinstance(b, str) and b.strip() for b in raw_banks):
        raise _fail(source, "banks 의 모든 항목은 비어 있지 않은 문자열이어야 한다")
    if len(set(raw_banks)) != len(raw_banks):
        raise _fail(source, "banks 에 중복이 있다")

    raw_scope = doc.get("scope_concepts")
    if not isinstance(raw_scope, list) or not raw_scope:
        raise _fail(source, "scope_concepts 는 비어 있지 않은 목록이어야 한다")
    if not all(isinstance(c, str) and c.strip() for c in raw_scope):
        raise _fail(source, "scope_concepts 의 모든 항목은 비어 있지 않은 문자열이어야 한다")
    if len(set(raw_scope)) != len(raw_scope):
        raise _fail(source, "scope_concepts 에 중복이 있다")
    scope = frozenset(raw_scope)

    raw_rules = doc.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise _fail(source, "rules 는 비어 있지 않은 목록이어야 한다")
    rules = tuple(_parse_rule(r, i, scope) for i, r in enumerate(raw_rules))
    ids = [r.rule_id for r in rules]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise _fail(source, f"규칙 id 가 중복된다: {dup}")
    return SlotRules(banks=tuple(raw_banks), scope_concepts=scope, rules=rules)


def load_slot_rules(path: Path | None = None) -> SlotRules:
    """규칙 파일을 읽는다. 부재·파싱 실패는 예외 타입명과 함께 명시 실패한다."""
    target = path or default_rules_path()
    try:
        doc = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SlotRulesError(
            f"{target}: 규칙 파일을 읽지 못했다 — {type(exc).__name__}: {exc}"
        ) from exc
    return parse_slot_rules(doc, str(target))


def _matches(
    rule: SlotRule, problem: ProblemRef, folded: str | None, reaches: Callable[[ProblemRef], bool]
) -> bool:
    if rule.concept is not None and rule.concept not in problem.primary_src_ids:
        return False
    if rule.folded_stem_contains is not None:
        # 문면을 못 읽었으면 포함 여부를 알 수 없다 — 모르면 맞지 않는다(보류로 위장하지 않는다).
        if folded is None or rule.folded_stem_contains not in folded:
            return False
    if rule.has_own_misconception is not None and reaches(problem) != rule.has_own_misconception:
        return False
    return True


def decide_slot(
    rules: SlotRules,
    problem: ProblemRef,
    reaches: Callable[[ProblemRef], bool],
    *,
    eligible_status: str,
) -> SlotDecision:
    """문항 1건에 규칙을 적용한다. 규칙을 적용하지 않는 경우는 `skipped`에 이유를 남긴다."""
    if problem.review_status != eligible_status:
        return SlotDecision(slot=None, skipped="not-approved")
    if not (problem.primary_src_ids & rules.scope_concepts):
        return SlotDecision(slot=None, skipped="out-of-scope")
    if parse_slot_tags(problem.tags).slots:
        return SlotDecision(slot=None, skipped="already-slotted")
    folded = fold_stem(problem.question_text)
    for rule in rules.rules:
        if _matches(rule, problem, folded, reaches):
            return SlotDecision(slot=rule.slot, rule_id=rule.rule_id, reason=rule.reason)
    return SlotDecision(slot=None)
