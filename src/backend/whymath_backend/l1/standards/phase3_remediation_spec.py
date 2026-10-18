"""Phase 3 오답 → 교정 전략 슬라이스 데이터 로더 (P3-06) — 오류 서명 픽스처의 스키마 검증.

`data/corpus/phase3_remediation_v1/remediation.yaml` 은 kebab(런타임 오개념 id) 단위로 "이 보기를
고르면 이 오개념 후보가 나와야 한다(오답 픽스처) / 정답 보기를 고르면 나오면 안 된다(정답 픽스처)"를
선언한다. 이 모듈은 **구조만** 검증한다 — 문항·보기·오개념이 코퍼스에 실재하는지, 체인이 실제로 그
후보를 내는지는 `ops/phase3_remediation.py` 가 판정한다(L1 은 L4 를 알지 못한다).

일부러 담지 않는 것(복제하면 두 번째 진실 원천이 된다):
  · 핵심 오개념 12개 — P3-01 범위 명세(`phase3_scope`)가 소유한다.
  · kebab↔M-id — 승인 크로스워크가 소유한다(사람 서명 게이트).

종료 의미: 실패는 전부 `RemediationSpecError` — 빈 목록을 "픽스처 0건 통과"로 읽지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

__all__ = [
    "KNOWN_CHANNELS",
    "FixtureRef",
    "RemediationSpec",
    "RemediationSpecError",
    "SignatureFixtures",
    "default_spec_path",
    "load_remediation_spec",
    "parse_remediation_spec",
]

_REPO_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_SPEC = Path("data/corpus/phase3_remediation_v1/remediation.yaml")

#: 이 슬라이스가 다루는 채널 — 폐쇄 어휘. 오타·미지원 채널(단답형 등)을 조용히 통과시키지 않는다.
KNOWN_CHANNELS: Final[frozenset[str]] = frozenset({"choice"})


class RemediationSpecError(RuntimeError):
    """교정 전략 슬라이스 데이터 적재·구조 검증 실패 — 조용한 0건 대신 던진다."""


@dataclass(frozen=True)
class FixtureRef:
    """픽스처 1건 — 문항과 그 문항의 보기 인덱스(0-기반)."""

    problem_id: str
    choice_index: int


@dataclass(frozen=True)
class SignatureFixtures:
    """kebab 하나의 서명 픽스처 — 오답(후보가 나와야 함)과 정답(후보가 나오면 안 됨)."""

    kebab_id: str
    channel: str
    wrong: tuple[FixtureRef, ...]
    correct: tuple[FixtureRef, ...]


@dataclass(frozen=True)
class RemediationSpec:
    spec_id: str
    scope_spec_id: str
    unseated_gate: str
    signatures: tuple[SignatureFixtures, ...]

    def by_kebab(self) -> dict[str, SignatureFixtures]:
        return {s.kebab_id: s for s in self.signatures}


def default_spec_path() -> Path:
    """저장소 정본 데이터 경로."""
    return _REPO_ROOT / _DEFAULT_SPEC


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise RemediationSpecError(f"{where}: 매핑이 아니다 (실제 {type(value).__name__})")
    return value


def _text(raw: Mapping[str, Any], key: str, where: str) -> str:
    if key not in raw:
        raise RemediationSpecError(f"{where}: 필수 필드 {key!r} 결손")
    value = raw[key]
    if not isinstance(value, str) or not value.strip():
        raise RemediationSpecError(f"{where}: {key!r}가 빈 문자열이거나 문자열이 아니다")
    return value


def _fixtures(raw: Any, where: str) -> tuple[FixtureRef, ...]:
    if not isinstance(raw, list) or not raw:
        raise RemediationSpecError(
            f"{where}: 비어 있거나 리스트가 아니다 — 픽스처 0건은 통과가 아니다"
        )
    parsed: list[FixtureRef] = []
    for number, item in enumerate(raw, start=1):
        here = f"{where}[{number}]"
        row = _mapping(item, here)
        index = row.get("choice_index")
        # bool 은 int 의 서브클래스다 — True 가 1번 보기로 조용히 읽히지 않게 거부한다.
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise RemediationSpecError(
                f"{here}: choice_index 는 0 이상의 정수여야 한다 ({index!r})"
            )
        parsed.append(FixtureRef(problem_id=_text(row, "problem_id", here), choice_index=index))
    pairs = [(f.problem_id, f.choice_index) for f in parsed]
    if len(set(pairs)) != len(pairs):
        raise RemediationSpecError(f"{where}: 같은 (문항, 보기)가 중복이다")
    return tuple(parsed)


def _parse_signature(raw: Any, where: str) -> SignatureFixtures:
    row = _mapping(raw, where)
    kebab = _text(row, "kebab_id", where)
    channel = _text(row, "channel", where)
    if channel not in KNOWN_CHANNELS:
        raise RemediationSpecError(
            f"{where}: 지원하지 않는 채널 {channel!r} (허용 {sorted(KNOWN_CHANNELS)})"
        )
    fixtures = _mapping(row.get("fixtures"), f"{where}.fixtures")
    wrong = _fixtures(fixtures.get("wrong"), f"{where}.fixtures.wrong")
    correct = _fixtures(fixtures.get("correct"), f"{where}.fixtures.correct")
    # 같은 문항의 같은 보기가 "오답이면서 정답"인 자기모순은 검사 이전에 거부한다.
    clash = {(f.problem_id, f.choice_index) for f in wrong} & {
        (f.problem_id, f.choice_index) for f in correct
    }
    if clash:
        raise RemediationSpecError(
            f"{where}: 오답과 정답 픽스처가 같은 보기를 가리킨다 — {sorted(clash)}"
        )
    return SignatureFixtures(kebab_id=kebab, channel=channel, wrong=wrong, correct=correct)


def parse_remediation_spec(doc: Any) -> RemediationSpec:
    """파싱된 YAML → `RemediationSpec`. 구조 위반은 `RemediationSpecError`."""
    root = _mapping(doc, "최상위")
    if root.get("spec_version") != 1:
        raise RemediationSpecError(f"지원하지 않는 spec_version: {root.get('spec_version')!r}")
    unseated = _mapping(root.get("unseated_decision"), "unseated_decision")
    raw_signatures = root.get("signatures")
    if not isinstance(raw_signatures, list) or not raw_signatures:
        raise RemediationSpecError("signatures: 비어 있거나 리스트가 아니다 — 0건은 통과가 아니다")
    signatures = tuple(
        _parse_signature(item, f"signatures[{number}]")
        for number, item in enumerate(raw_signatures, start=1)
    )
    kebabs = [s.kebab_id for s in signatures]
    if len(set(kebabs)) != len(kebabs):
        dup = sorted({k for k in kebabs if kebabs.count(k) > 1})
        raise RemediationSpecError(f"signatures: kebab_id 중복 — {dup}")
    return RemediationSpec(
        spec_id=_text(root, "spec_id", "최상위"),
        scope_spec_id=_text(root, "scope_spec_id", "최상위"),
        unseated_gate=_text(unseated, "gate", "unseated_decision"),
        signatures=signatures,
    )


def load_remediation_spec(path: Path | None = None) -> RemediationSpec:
    """데이터 YAML → `RemediationSpec`. 실패는 전부 `RemediationSpecError`(침묵 0건 금지)."""
    source = path or default_spec_path()
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise RemediationSpecError(
            f"교정 전략 데이터를 읽지 못했다 ({source}): {type(exc).__name__}: {exc}"
        ) from exc
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RemediationSpecError(
            f"교정 전략 데이터 YAML 파싱 실패 ({source}): {type(exc).__name__}: {exc}"
        ) from exc
    return parse_remediation_spec(doc)
