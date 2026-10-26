#!/usr/bin/env python3
"""S4-18 결정론 계보 동기화 — rephrase 변형에 identity_id/problem_relation을 부여한다.

**소급(S4-18 당시 429건) + 향후(재실행 가능)** 양쪽에 쓰는 같은 스크립트다 —
`problem_corpus_rephrase.py`는 의도적으로 slug/problem_id/identity_id를 건드리지 않는다(발문만
다양화하는 것이 그 함수의 계약이자, `--in` 소스 코퍼스는 이 파이프라인 전체에서 읽기 전용이라는 기존
관례 — S2-08 `reconcile_rephrased_corpus_s2_08.py`와 동형). 그래서 Phaiakes9에서 새 rephrase 배치를
돌린 뒤에는 매번 이 스크립트를 재실행해 계보를 동기화한다(멱등이라 몇 번을 돌려도 안전 — 이미 처리된
레코드는 스킵하고 신규 레코드만 처리).

배경: rephrase는 원본 Problem을 그대로 복사하며 question_text만 바꾸므로(`l3/equivalent/
rephrase.py` 계약), 당시 rephrased_v0 429건 중 392건(91%)이 원본과 *동일* slug·problem_id를
갖는다(실측 확인) — populate.py의 slug ON CONFLICT upsert가 이 둘을 *같은 DB 행*으로
병합해, problem_relation(2행 관계)을 맺을 대상 행 자체가 없다(schema._no_self_relation이
구조적으로 막음). 나머지 37건(8.6%)은 이미 별개 slug/problem_id를 갖지만 계보(relation)가
없다.

Kiki 결정(2026-07-29, identity_id/Canonical 분리): problem_id는 개체마다 절대 불변,
identity_id(신규 nullable UUID)로만 "같은 문제의 다른 표현" 계열을 묶고, problem_relation은
개별 변환 이력만 기록한다.

이 스크립트가 매 실행마다 미처리(identity_id 없는) 레코드 전부에 하는 일(최초 실행=429건):
  ① parent 판정 — slug가 원본(generated_v0)과 같으면 그 slug 자체가 parent. 다르면(재실행 시
     이미 재슬러그된 레코드 포함) 수정 불변 수학키(unit_codes·verify.conditions·
     answer_selection/aggregate/kind·answer)로 원본과 조인(`scripts/
     reconcile_rephrased_corpus_s2_08.py`와 동일 키·전건 유일성 실측 검증됨 — 620건 키 충돌 0).
  ② slug 충돌 해소(parent와 slug가 같은 경우만) — rephrase 레코드에 신규 slug
     (`f"{parent_slug}-rephrased"`)·신규 problem_id를 결정론 파생(uuid5)해 부여한다. 원본
     (parent) 행은 손대지 않는다(slug·problem_id 불변 — 재적재 시 기존 DB 행과 계속 일치·
     PK churn 0).
  ③ identity_id 부여 — parent_slug로부터 결정론 파생(uuid5)해 rephrase 레코드와 원본 레코드
     양쪽에 같은 값을 쓴다.
  ④ problem_relation 계보 — rephrase 레코드에 `relations=[{parent_slug, "변형",
     similarity_score=1.0}]` authoring 키를 추가한다(populate.py가 적재 시 upsert).
     similarity_score=1.0은 추정이 아니라 실측 사실이다 — rephrase는 conditions·answer를
     그대로 복사하므로(발문만 재작성) 수치 내용이 완전히 동일하다.

멱등: identity_id가 이미 있는 레코드는 재처리하지 않는다(재실행 안전 — slug 재채번된 뒤
재실행해도 수학키로 같은 parent를 다시 찾되 이미 분리된 slug라 재채번을 반복하지 않는다).
신규 slug 충돌(기존 코퍼스에 이미 그 slug가 있음)·수학키 조인 실패·수학키 충돌은 즉시
실패한다(조용한 누락 금지).

QUAL-04(2026-08-11) 설계 변경 — 무변화(no-op) 레코드는 계보를 부여하지 않고 건너뛴다:
QUAL-03이 rephrased_v0 429건 중 282건(65.7%)을 "원본과 정규화 텍스트가 완전 동일한 무변화
재서술"로 확정했다. 그 근본원인은 `problem_corpus_rephrase.run_corpus_rephrase`가 아니라
*이 스크립트*였다(오케스트레이터 코드 추적 재확인) — `run_corpus_rephrase`의 fail-closed(검증
실패 시 원문 유지)는 `tests/backend/harness/test_problem_corpus_rephrase.py`의
`test_failed_rephrase_keeps_original`·`test_main_without_live_provider_fails_closed`가 이미
명시적으로 고정한 의도된 안전 철학(레코드 드롭이 아니라 검증된 원본 유지)이라 거기서 손대지
않는다. 반면 이 스크립트는 무변화 레코드에도 예외 없이 slug 재채번·identity_id·relations를
부여해 왔으므로, `populate.py` 적재 시 부모와 내용이 같은 "가짜 중복" DB 행이 매번 생겼다.
그래서 `backfill()`의 루프는 parent 판정 직후 — slug 재채번·identity 부여·relation 추가
*전에* — `question_text`가 parent와 (정규화 후) 완전히 같은지 검사하고, 같으면 slug·
problem_id·identity_id·relations를 전부 미부여한 채 건너뛴다(`noop_skipped` 카운터).
colliding 레코드(parent와 slug가 같은 절대다수 케이스)는 원래 slug가 parent와 같은 채로
남으므로 `populate.py`의 slug ON CONFLICT upsert가 부모와 *같은* DB 행으로 자연 병합한다 —
이것이 "드롭"의 실질 효과다(JSONL에서 줄을 지우는 게 아니라 DB에서 별도 행이 되는 것을
막는다). 이미 별개 slug로 들어온 non-colliding 레코드도 텍스트가 진짜 무변화라면 "변형"이라는
거짓 계보(relation_type=변형·similarity_score=1.0)를 남기지 않도록 동일하게 건너뛴다.

신규 마이그레이션 0 — 코퍼스 JSONL에 필드를 추가하는 게 아니라 오히려 *안 붙이는* 쪽으로
결정했다. 대안 (b) "rephrase_status 필드 신설로 무변화 여부를 영속화하고 소비측(populate.py
등)이 필터링 중 판정"은 기각했다 — 이 저장소에는 "선언됐으나 소비자가 실제로는 안 지키는
필드"가 반복되는 결함 패턴이 있고(PED-06→PED-08 재설계·OPS-22 선언≠배선 감사기가 애초에
그 패턴을 잡으려고 생긴 장치다), 필드 신설은 소비측 규율(그 필드를 매 소비 지점에서 빠짐없이
확인하는 것)에 의존해 같은 패턴을 또 만들 위험이 있다. 소급 backfill 단계에서 애초에 별도
identity/slug를 부여하지 않는 쪽(식별 자체를 원천 차단)이 소비측 규율에 의존하지 않아
구조적으로 더 안전하다.

사용:  python3 scripts/backfill_rephrase_lineage_s4_18.py [--check]
  --check: 쓰지 않고 변경 요약만 출력(드라이런).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import uuid
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GENERATED = _REPO / "data" / "corpus" / "problem_bank_generated_v0" / "problems.jsonl"
_REPHRASED = _REPO / "data" / "corpus" / "problem_bank_rephrased_v0" / "problems.jsonl"

# uuid5 결정론 파생 namespace(고정 상수 — 한 번 생성해 고정, 재실행 시 항상 같은 값 보장).
_IDENTITY_NAMESPACE = uuid.UUID("83ed15d5-7ce4-469b-8166-1ac4e44a176f")
_VARIANT_PROBLEM_ID_NAMESPACE = uuid.UUID("caa1a2ae-7188-43fd-bd81-06d73f118879")

_RENAME_SUFFIX = "-rephrased"


# rephrase가 발문만 바꾸고 그대로 복사하는 필드(S2-08 정본 조인키와 동형) — 조사·난이도·
# op-code 수정에 불변이고 generated 전건에서 유일함을 실측 검증했다.
def _math_key(record: dict) -> tuple:
    verify = record.get("verify") or {}
    return (
        tuple(sorted(record.get("unit_codes") or [])),
        verify.get("conditions"),
        str(record.get("answer")),
        verify.get("answer_selection"),
        verify.get("answer_aggregate"),
        verify.get("answer_kind"),
    )


# 무변화(no-op) 판정용 비교 정규화 — QUAL-04(2026-08-11). NFC + 공백 연속 축약 + 양끝 trim.
_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize_for_comparison(text: object) -> str | None:
    """비교용 텍스트 정규화 — NFC + 공백 연속 축약 + 양끝 trim(비문자열·공백만이면 None).

    `harness.problem_duplication_audit.normalize_question_text`·`l3.equivalent.
    rephrase_hygiene._normalize_for_comparison`와 동등 기준의 로컬 재구현이다(QUAL-04 판단 —
    이 스크립트는 `src/backend/whymath_backend/` 밖의 독립 `scripts/` 파일로 whymath_backend를
    import하지 않는다는 것을 실측 확인했다: 기존 이 파일의 배선에 그 의존이 전혀 없었다).
    새 의존을 만드는 대신, `rephrase_hygiene._normalize_for_comparison`이 QUAL-03에서 이미
    확립한 "import 방향 때문에 공유 불가 → 로컬 재구현" 선례를 그대로 따른다. 두 함수(및
    `normalize_question_text`)가 항상 같은 출력을 내야 세 수치가 어긋나지 않는다(CLAUDE.md
    정직 회계). 정직한 한계: `rephrase_hygiene` 쪽은 둘 다 `whymath_backend` 안이라
    `tests/backend`에서 바이트 단위 교차검증 테스트를 둘 수 있지만, 이 스크립트는
    `tests/infra`에서 테스트되고 그 CI 잡은 최소 의존 원칙상 `whymath_backend`를 설치하지
    않아 같은 방식의 자동 교차검증이 구조적으로 불가하다 — `tests/infra/
    test_backfill_rephrase_lineage_s4_18.py`의 회귀 테스트는 이 구현 자체의 정규화 동작
    (NFC 정규화·공백축약이 실제로 근접 무변화를 잡는지)만 고정한다. 세 구현이 서로 갈리면
    (알고리즘이 바뀌는 드문 경우) 사람이 코드 diff로 잡아야 한다.
    """
    if not isinstance(text, str):
        return None
    collapsed = _WHITESPACE_RUN.sub(" ", unicodedata.normalize("NFC", text)).strip()
    return collapsed or None


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def backfill(*, check: bool) -> int:
    """전량 계보 백필(S4-18 당시 429건) — 미해석/충돌 잔여가 있으면 즉시 실패(fail-closed)."""
    generated = _load(_GENERATED)
    rephrased = _load(_REPHRASED)

    by_slug: dict[str, dict] = {g["slug"]: g for g in generated}
    by_key: dict[tuple, list[dict]] = {}
    for g in generated:
        by_key.setdefault(_math_key(g), []).append(g)
    ambiguous = {k: [g["slug"] for g in v] for k, v in by_key.items() if len(v) > 1}
    if ambiguous:
        print(
            f"치명: generated 수학키 충돌 {len(ambiguous)}건 — 조인 불가: "
            f"{list(ambiguous.items())[:3]}",
            file=sys.stderr,
        )
        return 1

    all_slugs = {r["slug"] for r in generated} | {r["slug"] for r in rephrased}

    unmatched: list[str] = []
    already_done = 0
    noop_skipped = 0
    renamed = 0
    identity_assigned = 0
    relations_added = 0

    for record in rephrased:
        if record.get("identity_id") is not None:
            already_done += 1
            continue

        parent = by_slug.get(record["slug"])
        if parent is None:
            candidates = by_key.get(_math_key(record), [])
            if len(candidates) != 1:
                unmatched.append(record["slug"])
                continue
            parent = candidates[0]

        parent_slug = parent["slug"]

        # QUAL-04(2026-08-11) — 무변화 판정. 정규화 후 question_text가 parent와 완전히 같으면
        # slug 재채번·identity_id·relations를 전부 미부여하고 건너뛴다(위 모듈 docstring
        # "QUAL-04 설계 변경" 문단 참고 — 근거·대안 기각 사유 전문). record_norm이 None(비문자열·
        # 공백만)이면 무변화로 취급하지 않는다 — 둘 다 빈 텍스트인 우연을 "동일"로 오판하지
        # 않기 위해서다(rephrase_hygiene.question_hygiene_violations의 동일 방어와 동형).
        record_norm = _normalize_for_comparison(record.get("question_text"))
        parent_norm = _normalize_for_comparison(parent.get("question_text"))
        if record_norm is not None and record_norm == parent_norm:
            noop_skipped += 1
            continue

        colliding = record["slug"] == parent_slug

        if colliding:
            new_slug = f"{parent_slug}{_RENAME_SUFFIX}"
            if new_slug in all_slugs:
                print(f"치명: 신규 slug 충돌: {new_slug}", file=sys.stderr)
                return 1
            all_slugs.add(new_slug)
            record["slug"] = new_slug
            record["problem_id"] = str(uuid.uuid5(_VARIANT_PROBLEM_ID_NAMESPACE, new_slug))
            renamed += 1

        identity = str(uuid.uuid5(_IDENTITY_NAMESPACE, parent_slug))
        record["identity_id"] = identity
        parent["identity_id"] = identity
        identity_assigned += 1

        record["relations"] = [
            {"parent_slug": parent_slug, "relation_type": "변형", "similarity_score": 1.0}
        ]
        relations_added += 1

    if unmatched:
        print(
            f"치명: rephrased {len(unmatched)}건 parent 미해석(조인 실패) — {unmatched[:5]}",
            file=sys.stderr,
        )
        return 1

    print(
        f"이미 처리됨(스킵) {already_done} · 무변화 스킵(noop) {noop_skipped} · "
        f"slug 재채번 {renamed} · identity_id 부여 {identity_assigned} · "
        f"relation 부여 {relations_added} (전체 {len(rephrased)}건)"
    )
    if check:
        print("[--check] 드라이런 — 파일 미수정")
        return 0

    _REPHRASED.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rephrased) + "\n",
        encoding="utf-8",
    )
    _GENERATED.write_text(
        "\n".join(json.dumps(g, ensure_ascii=False) for g in generated) + "\n",
        encoding="utf-8",
    )
    print(f"기록: {_REPHRASED}\n기록: {_GENERATED}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S4-18 rephrase 계보(identity_id·problem_relation) 소급 백필(결정론·멱등)."
    )
    parser.add_argument(
        "--check", action="store_true", help="쓰지 않고 변경 요약만 출력(드라이런)."
    )
    args = parser.parse_args(argv)
    return backfill(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
