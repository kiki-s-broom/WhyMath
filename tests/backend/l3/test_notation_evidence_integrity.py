"""표기 지원집합 정본의 **참조 무결성** — 근거로 지목한 파일이 실재하는가 (MATH-02 ③).

이 축을 보는 검사는 저장소에 0건이었다. 기존 `test_unproven_symbols_not_included`는
allowlist가 *넓어지는 것*만 막고, 이미 등재된 항목의 **근거가 실재하는지**는 보지 않는다.
그 사각 때문에 `NS-02`가 미병합 브랜치에 고립돼 실증 파일이 전부 사라진 뒤에도 `NS-03` 게이트는
계속 green이었다 — 선례(`OPS-03`·`VIZ-01`·`NLP-01`)가 "만들었는데 안 돈다"(증상=부재)였다면
이건 **"도는데 근거가 없다"(증상=green)**라 더 조용했다.

검사 축 2개 — 성격이 다르므로 분리한다:
  ① **회계 정합**(상시 green이어야 함) — `unproven` 격리가 *제대로 작동하는가*. 근거가 부재한
     매크로는 지원집합에 들어오지 않고, 실재하는 것만 들어온다. 유령이 몇 개든 이 검사는 통과한다.
  ② **근거 실재**(현재 red가 정상) — 정본이 주장하는 근거가 실제로 있는가. 지금은 5종 전부
     부재라 **red가 나야 맞다**. 이걸 green으로 만들려면 `NS-02`를 착륙시켜야 하는데 그건 이
     태스크 범위 밖(⑥ 포기 판정)이므로, red를 숨기지 않으면서 CI를 빨갛게 만들지 않기 위해
     **`xfail(strict=True)`**로 동결한다 — 근거가 생기면 `XPASS`로 *실패*해서 이 표식을 지우라고
     알려준다(공백을 숨기지 않으면서 해소를 놓치지도 않는 유일한 형태).

`xfail(strict=True)`를 고른 이유: `skip`은 "검사가 없는 것"과 구별되지 않고(침묵 실패),
그냥 `fail`은 알려진 공백으로 CI를 상시 red로 만들어 경고를 습관화시킨다(CLAUDE.md
"상시 실패하는 fail-open 보호를 '보호 있음'으로 신뢰 금지"의 대칭 문제).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.l3.notation_coverage import (
    _PROVEN_MACRO_EVIDENCE,
    KATEX_PROVEN_MACROS,
    load_support_set,
    proven_macros,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = _REPO_ROOT / "data" / "notation_support_manifest.json"


def _manifest_claims() -> list[dict[str, str]]:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    provenance = payload["provenance"]
    claims: list[dict[str, str]] = provenance["claims"]
    return claims


# ──────────────────────────────────────────────────────────────────────────
# 축 ① 회계 정합 — 격리 기계가 제대로 도는가 (상시 green)
# ──────────────────────────────────────────────────────────────────────────


def test_allowlist_is_derived_from_evidence_mapping_not_duplicated() -> None:
    """`KATEX_PROVEN_MACROS`는 근거 매핑에서 *파생*된다 — 이중 정의 금지."""
    assert KATEX_PROVEN_MACROS == frozenset(_PROVEN_MACRO_EVIDENCE)


def test_proven_and_unproven_partition_the_allowlist() -> None:
    """`proven` ⊎ `unproven` = allowlist 전체 — 어느 매크로도 회계에서 새지 않는다."""
    proven, unproven = proven_macros(_REPO_ROOT)
    assert proven | unproven == KATEX_PROVEN_MACROS
    assert not (proven & unproven)


def test_unproven_macros_are_excluded_from_support_set() -> None:
    """근거 부재 매크로는 **지원집합에 들어오지 않는다** — 유령 근거가 커버리지를 넓히지 못한다.

    단, manifest `cases`/`accent_macros`가 같은 매크로를 독립적으로 지원할 수 있다(그건 정당한
    다른 출처다). 따라서 "allowlist 경유로는 들어오지 않는다"를 검사한다 — allowlist를 비운
    지원집합과 실제 지원집합의 차집합이 곧 allowlist 기여분이고, 거기에 unproven이 없어야 한다.
    """
    proven, unproven = proven_macros(_REPO_ROOT)
    support = load_support_set(_MANIFEST, repo_root=_REPO_ROOT)
    manifest_only = load_support_set(_MANIFEST, repo_root=_REPO_ROOT / "__absent__")
    allowlist_contribution = support.macros - manifest_only.macros

    assert not (
        allowlist_contribution & unproven
    ), "근거 부재 매크로가 allowlist 경유로 지원집합에 유입됐다 — 유령 근거가 게이트를 넓힌다"
    assert allowlist_contribution <= proven


def test_every_evidence_path_is_repo_relative_and_nonempty() -> None:
    """근거 경로는 저장소 상대 경로 문자열이어야 한다(절대경로·빈 문자열 금지)."""
    for macro, evidence in _PROVEN_MACRO_EVIDENCE.items():
        assert evidence, f"{macro}: 근거 경로가 비었다"
        assert not Path(evidence).is_absolute(), f"{macro}: 절대경로 금지 — {evidence}"


def test_manifest_provenance_claims_are_well_formed() -> None:
    """`provenance.claims` 각 항목이 `{claim, evidence_path, status}` 구조를 지킨다."""
    claims = _manifest_claims()
    assert claims, "provenance.claims 가 비었다"
    for entry in claims:
        assert set(entry) == {"claim", "evidence_path", "status"}, entry
        assert entry["claim"] and entry["evidence_path"]
        assert entry["status"] in {"proven", "unproven"}, entry


def test_manifest_claim_status_matches_filesystem() -> None:
    """선언한 `status`가 **실제 파일 존재와 일치**한다 — 상태를 손으로 틀리게 적을 수 없다.

    이 검사가 ⑤의 변별력 좌석이다: `evidence_path`를 실재 파일로 바꾸면 `status`도 `proven`으로
    바꿔야 통과하고, 부재로 되돌리면 `unproven`이어야 통과한다. 즉 경로와 상태 중 하나만 고치면
    반드시 red가 난다.
    """
    for entry in _manifest_claims():
        exists = (_REPO_ROOT / entry["evidence_path"]).exists()
        expected = "proven" if exists else "unproven"
        assert entry["status"] == expected, (
            f"{entry['evidence_path']}: 파일 실재={exists} 인데 status={entry['status']!r} "
            f"(기대 {expected!r}) — 근거 상태를 실제와 다르게 선언했다"
        )


def test_macro_evidence_paths_are_declared_in_manifest_provenance() -> None:
    """코드 매핑이 쓰는 근거 파일이 manifest `provenance`에도 등재돼 있다 — 두 정본의 동기화."""
    declared = {entry["evidence_path"] for entry in _manifest_claims()}
    used = set(_PROVEN_MACRO_EVIDENCE.values())
    assert used <= declared, f"manifest provenance에 없는 근거 경로: {sorted(used - declared)}"


# ──────────────────────────────────────────────────────────────────────────
# 축 ② 근거 실재 — 현재 red가 정상 (NS-02 포기로 해소 미정)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "잔여 근거 1건 부재 — docs/architecture/notation_semantics_layer.md(표기 의미 계층 "
        "설계 정본)는 한 번도 작성된 적이 없다(원 NS-02 브랜치에도 부재·2026-09-21 실측). "
        "Dart 실증 4건은 S3-24 버킷B 회수로 착지해 proven이 됐다 — 종전 사유 '전량 부재(5/5)'는 "
        "그 시점 사실이었고 지금은 1/5만 남았다. 마지막 1건이 작성되면 이 xfail이 XPASS로 "
        "실패해 표식 제거를 알린다(설계 불변)."
    ),
)
def test_all_declared_evidence_files_exist() -> None:
    """정본이 주장하는 **모든** 근거 파일이 실재한다.

    이 태스크가 만든 검사의 본체다. 지금은 실패하는 것이 정직하다 — 통과시키려고 근거 주장을
    지우면 공백 자체가 사라져 보인다(그래서 ④는 삭제가 아니라 격리를 택했다).
    """
    missing = [
        entry["evidence_path"]
        for entry in _manifest_claims()
        if not (_REPO_ROOT / entry["evidence_path"]).exists()
    ]
    assert not missing, f"근거 파일 부재 {len(missing)}건: {missing}"
