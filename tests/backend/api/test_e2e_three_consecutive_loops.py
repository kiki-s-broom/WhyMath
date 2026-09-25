"""계획서 300 §18 **무개입 연속 3루프** 상시 하네스 — `PED-36` ⑫.

    운영자가 DB를 직접 수정하지 않고 3회 이상 연속 Learning Loop가 가능해야 한다.
    Loop 1: 진단 → 문제 → 오답 → **보정**
    Loop 2: 보정 → 문제 → 정답 → mastery 상승
    Loop 3: **다음 concept** → 문제 → 평가 → 추천

이 조건을 재는 상시 장치는 2026-09-19 Gate 2 판정(`EOS-22` · `docs/reviews/
eos_phase2_gate2_judgment_2026-09-19.md` §3-1) 시점에 main에 없었고, 판정은 커밋되지 않은
일회성 프로브로 이뤄졌다(§8-2). 이 파일이 그 프로브의 상시판이다 — 재판정(`EOS-130`)은
이 하네스의 출력(`THREE_LOOP_VERDICT` 줄)과 exit code를 근거로 쓴다.

**학습자는 시스템의 추천을 그대로 따른다(폐쇄 루프).** 이 하네스의 학습자가 하는 선택은
*정오답* 하나뿐이다 — 첫 진단 문항만 틀리고 그 뒤로는 추천받은 문항을 전부 맞힌다. 어느
문항을 풀지는 매번 `GET /v1/me/next-problem`이 정한다. 판정문 §3-3의 요지("3루프는 루프가
닫혀서 도는 것이 아니라 학습자가 올바른 경로를 미리 알고 있어서 돈다")를 재려면 학습자가
경로를 고르면 안 된다 — 고르는 순간 재는 것이 시스템이 아니라 스크립트가 된다.

────────────────────────────────────────────────────────────────────────────
루프 경계와 마디 판정 (판정 규칙의 정본은 이 절이다)
────────────────────────────────────────────────────────────────────────────
§18은 마디의 *이름*만 준다. 이름을 관측 가능한 조건으로 옮긴 것이 아래이며, 세 루프에
**같은 규칙 하나**를 적용한다 — *추천이 말하는 개념(정책 축: action·target_concept)과
추천이 실제로 준 문항의 개념(선택 축: problem_id)이 같은 곳을 가리킬 것.* 한 축만 보면
EOS-124의 두 방향 불일치(말만 전진 / 문항만 복귀)가 그대로 통과한다.

- **Loop 1** — 첫 추천(진단)을 틀리고 그 **직후 첫 추천**을 본다. `보정` 마디는
  ⓐ `action` ∈ {practice_prerequisite, practice_current} ⓑ `target_concept`이 틀린
  개념 또는 그 선수 개념 ⓒ 준 문항이 그 `target_concept` 소속 — 셋 다일 때만 선다.
  `diagnose`는 보정이 아니다: 측정이 없다는 뜻이고, 방금 오답이라는 측정이 생겼다.
- **Loop 2** — Loop 1 끝의 추천부터 따라 풀며(전부 정답) 틀린 개념의 숙달이 **오답 직후
  값보다 오르는가**(§18 문면)를 본다. 루프의 *출구*는 그 숙달이 추천 정책 자신의 전진
  임계(`WEAK_CONCEPT_MASTERY_CEILING` — 소스에서 읽는다)를 넘는 시점이다. 출구를 임의
  횟수가 아니라 정책의 임계로 둔 이유: "다음 concept로 갈 준비가 됐다"를 이 하네스가
  정하면 판정이 하네스의 취향이 된다. 예산은 틀린 개념의 문항 수 — 그 안에 못 넘으면
  숙달 상승이 선택이 아니라 후보 소진의 부산물이 된다.
- **Loop 3** — 임계를 넘긴 **직후 첫 추천**을 본다. `다음concept` 마디는 준 문항과
  `target_concept`이 **둘 다** 틀린 개념의 후행 개념일 때만 선다. 이때 틀린 개념에는
  미시도 문항이 반드시 남아 있어야 한다(아래 변별력 장치) — 남아 있는데 후행으로 가면
  그것은 소진이 아니라 선택이다. `평가`는 그 문항의 시도가 숙달 갱신을 낳는가, `추천`은
  그 뒤 추천이 근거와 함께 나오는가(`no_candidate` 아님)다.

**변별력 장치** — 개념 3종(선수·현재·후행)을 `prerequisite`로 잇고 문항 난이도 대역을
겹치지 않게 둔다(1.0~2.0 / 2.5~3.5 / 4.2~4.8 — 판정문 §8-2와 같은 배치). 틀린 개념의 문항은
6개를 심고, Loop 3 관측 시점에 **미시도 문항이 남아 있음을 단언**한다. 남은 것이 없으면
후행 개념 도달이 선택인지 소진인지 구별되지 않으므로 판정 불가로 **실패**시킨다(통과가 아니다).

────────────────────────────────────────────────────────────────────────────
"운영자 DB 개입 0"을 선언이 아니라 관측으로
────────────────────────────────────────────────────────────────────────────
1. **봉인** — 로그인 이후 이 하네스가 쓰는 저작 콘텐츠 시딩 함수(`_add_all`)를 예외를
   던지는 대역으로 바꾼다. 학습 도중 누군가 "루프를 통과시키려고" 행을 심는 편집을 하면
   그 줄에서 터진다.
2. **역추적** — 끝에 ⓐ `/v1/me/learning-trace`의 시도 이벤트 `attempt_id` 집합이 이
   하네스가 HTTP로 제출한 집합과 **같고** ⓑ `concept_mastery_history`의 이 학습자 행이 전부
   그 집합 안의 `attempt_id`를 가짐을 단언한다. 학습자 축의 모든 변화가 HTTP 제출 하나하나로
   거슬러 올라간다. ⓑ는 읽기 전용 SELECT다 — 시간선의 숙달 이벤트는 `attempt_id`를 싣지
   않고(`project_mastery_rows` — 2026-09-25 실측), 읽기는 "DB 직접 수정"이 아니다(페르소나
   하네스 `_provisioned_by`와 같은 규약).
3. **동일 학습자** — 시작과 끝의 `user_id`(반출권 표면)가 같다. 루프 사이에 학습자를
   지우거나 새로 만들지 않는다(연속성).

────────────────────────────────────────────────────────────────────────────
판정과 동결 — 이 파일이 초록인 것은 §18 충족이 **아니다**
────────────────────────────────────────────────────────────────────────────
2026-09-25 실측(main `bbd7c382`)으로 §18은 **미충족**이다(Loop 1 `보정` · Loop 3
`다음concept`). 이후 `EOS-124`(PR #1317 — 추천 설명을 전달 문항에 정렬)가 Loop 3
`다음concept`를 해소해 동결값을 승격했다. 남은 공백은 Loop 1 `보정`(`EOS-24`)이다. 그래서
테스트를 셋으로 나눈다.

- `test_three_loops_are_operator_free_and_continuous` — 무개입·연속성 불변식. 판정과
  무관하게 항상 초록이어야 한다.
- `test_three_loop_verdict_matches_frozen_gap` — 마디별 판정을 **현재 값으로 동결**한다
  (정직한 공백 동결 — `test_e2e_persona_journeys.py`와 같은 관례). 한 마디라도 바뀌면
  실패하고, 메시지가 *개선*(False→True — 동결을 승격하라)인지 *회귀*(True→False — 이
  변경이 루프를 끊었다)인지를 가른다.
- `test_plan300_s18_three_consecutive_loops_hold` — §18 문면 그대로의 계약(3루프 전건
  성립). `xfail(strict=True)`라 CI 요약에 **XFAIL**로 보인다 — "passed"와 같은 화면에서
  읽히지 않게 하려는 것이다. 해소되면 XPASS가 strict 실패로 바뀌어 동결 해제를 강제한다.

**판정 밖** — 교정 발화·추천 설명의 교수학적 적절성, 추천 품질(θ 근방이 최선인가)은
보지 않는다. 보는 것은 루프가 **닫히는가**(연결과 방향)뿐이다. 시나리오 뱅크(`PED-36` ①)가
이 반복을 표현할 수 있는가의 판정은 `docs/reviews/ped36_q12_three_consecutive_loops_2026-09-25.md`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

import pytest

from whymath_backend.l2.recommendation_contract import (
    WEAK_CONCEPT_MASTERY_CEILING as _ADVANCE_THRESHOLD,
)

pytestmark = pytest.mark.integration


# ── 페르소나 하네스의 검증된 조립기 재사용 (재구현 0) ───────────────────────────
# 경로 로딩인 이유는 그쪽 docstring과 같다(`--import-mode=importlib` — 형제 테스트 모듈이
# 이름으로 임포트되지 않는다). 페르소나 하네스는 다시 Week 2 하네스의 조립기를 빌린다.
_PERSONA_PATH = pathlib.Path(__file__).with_name("test_e2e_persona_journeys.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 이름을 지목하며 실패한다.
_PERSONA_HELPERS = (
    "_W2",
    "_UNMATCHED_WRONG_ANSWER",
    "_WRONG_ANSWER",
    "_add_all",
    "_attempt",
    "_begin",
    "_client",
    "_erase_learner",
    "_get",
    "_login",
    "_mastery_of",
    "_next_problem",
    "_prereq_edge",
    "_seed_concept",
    "_seed_problems",
    "_settings",
    "_state_of",
)


def _load_persona_harness() -> ModuleType:
    """페르소나 하네스를 파일 경로로 적재하고 헬퍼 계약을 검사한다."""
    if not _PERSONA_PATH.exists():
        raise RuntimeError(
            f"페르소나 여정 하네스가 없다: {_PERSONA_PATH}. 이 하네스는 그 조립기를 재사용한다 — "
            "파일이 옮겨졌으면 이 경로를 함께 고친다."
        )
    spec = importlib.util.spec_from_file_location("_three_loop_persona_harness", _PERSONA_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"페르소나 하네스 스펙 생성 실패: {_PERSONA_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _PERSONA_HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            f"페르소나 하네스의 헬퍼가 사라졌다: {missing}. 이 하네스가 그 조립기를 재사용하므로 "
            "이름이 바뀌면 여기도 함께 고쳐야 한다."
        )
    return module


_P = _load_persona_harness()

#: 보정으로 인정하는 추천 행위 — 측정을 근거로 약점에 개입하는 두 행위.
#: `diagnose`(측정 없음)·`advance_next`(전진)·`none`(후보 없음)은 보정이 아니다.
_REMEDIATION_ACTIONS = frozenset({"practice_prerequisite", "practice_current"})

#: 개념 3종의 문항 난이도 대역 — 서로 겹치지 않는다(판정문 §8-2와 같은 배치).
#: 난이도는 1~5 범위 강제다(범위 밖이면 `ProblemSchema`가 거부).
_DIFFICULTY_BANDS: dict[str, list[float]] = {
    "pre": [1.0, 1.2, 1.4, 1.6, 1.8, 2.0],
    "cur": [2.5, 2.7, 2.9, 3.1, 3.3, 3.5],
    "next": [4.2, 4.5, 4.8],
}
#: 후행 관계(개념 그래프의 prerequisite 엣지와 같은 방향). Loop 3의 "다음 concept"는
#: *틀린 개념*의 후행이다 — 진단이 어느 개념에서 시작하든 규칙이 같다.
_SUCCESSOR: dict[str, str | None] = {"pre": "cur", "cur": "next", "next": None}
_PREDECESSOR: dict[str, str | None] = {"pre": None, "cur": "pre", "next": "cur"}

#: 오답 두 종 — 같은 루프가 오답의 *종류*에 따라 갈리는지 본다.
#: `misconception`은 오개념 카탈로그의 거짓형을 인스턴스화해 상태 머신을 `REMEDIATING`으로
#: 보내고(2026-09-25 실측), `general`은 어떤 거짓형에도 걸리지 않는다(대조군).
_WRONG_ANSWERS: dict[str, str] = {
    "misconception": _P._WRONG_ANSWER,
    "general": _P._UNMATCHED_WRONG_ANSWER,
}


# ── 판정 구조 ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Node:
    """루프의 마디 1개 — 판정(ok)과 그 근거(evidence)를 함께 든다."""

    name: str
    ok: bool
    evidence: str


@dataclass
class _Loop:
    number: int
    nodes: list[_Node] = field(default_factory=list)

    def add(self, name: str, ok: bool, evidence: str) -> None:
        self.nodes.append(_Node(name, ok, evidence))

    @property
    def holds(self) -> bool:
        return bool(self.nodes) and all(n.ok for n in self.nodes)

    def as_map(self) -> dict[str, bool]:
        return {n.name: n.ok for n in self.nodes}


@dataclass
class _Journey:
    """3루프 1회 관통의 산출물 — 판정·불변식 근거·단계 기록."""

    variant: str
    loops: list[_Loop]
    #: 이 하네스가 HTTP로 제출한 시도 id(제출 순서).
    submitted_attempts: list[str]
    #: `/v1/me/learning-trace` 전문의 시도 이벤트 attempt_id.
    trace_attempt_ids: list[str]
    trace_truncated: bool
    #: `concept_mastery_history`의 이 학습자 행 attempt_id(없으면 None) — 읽기 전용 SELECT.
    mastery_row_attempt_ids: list[str | None]
    learner_before: str
    learner_after: str
    #: 봉인이 실제로 막은 호출 수 — 0이어야 한다(>0이면 누군가 학습 중 행을 심으려 했다).
    sealed_calls: int
    steps: list[str]

    def verdict_line(self) -> str:
        parts = [f"LOOP{lp.number}={'PASS' if lp.holds else 'FAIL'}" for lp in self.loops]
        overall = "PASS" if all(lp.holds for lp in self.loops) else "FAIL"
        return f"THREE_LOOP_VERDICT[{self.variant}] :: {' '.join(parts)} · §18={overall}"

    def as_map(self) -> dict[int, dict[str, bool]]:
        return {lp.number: lp.as_map() for lp in self.loops}


# ── 무개입 봉인 ─────────────────────────────────────────────────────────────────


class _Seal:
    """로그인 이후 저작 콘텐츠 시딩(`_add_all`)을 막는다 — 막힌 호출 수를 센다.

    페르소나 모듈과 그 아래 Week 2 모듈 **양쪽의** 이름을 바꾼다. 조립기는 Week 2의 함수를
    페르소나 모듈 전역으로 옮겨 쓰므로 한쪽만 바꾸면 다른 쪽 경로로 우회된다.
    """

    def __init__(self) -> None:
        self.blocked = 0
        self._originals: list[tuple[ModuleType, Any]] = []

    def _raiser(self, *_: Any, **__: Any) -> None:
        self.blocked += 1
        raise AssertionError(
            "학습 도중 DB 직접 쓰기 시도 — §18 '운영자 DB 개입 0' 위반. 3루프는 HTTP 부수효과만으로 "
            "성립해야 한다(시딩은 로그인 *전*에 끝낸다)."
        )

    def __enter__(self) -> _Seal:
        for module in (_P, _P._W2):
            self._originals.append((module, module._add_all))
            module._add_all = self._raiser
        return self

    def __exit__(self, *_: object) -> None:
        for module, original in self._originals:
            module._add_all = original


# ── 마디 판정 규칙 (순수 — 정책 축과 선택 축이 같은 개념을 가리키는가) ─────────────


def _remediation_fires(
    rec: dict[str, Any], *, member: dict[str, str], cname: dict[str, str], wrong_tag: str
) -> bool:
    """Loop 1 `보정`: ⓐ 보정 행위 ⓑ 대상이 틀린 개념 또는 그 선수 ⓒ 준 문항이 그 대상 소속."""
    target = cname.get(str(rec["target_concept"]))
    remedial_targets = {wrong_tag, _PREDECESSOR[wrong_tag]} - {None}
    return (
        rec["action"] in _REMEDIATION_ACTIONS
        and target in remedial_targets
        and member.get(str(rec["problem_id"])) == target
    )


def _advance_fires(
    rec: dict[str, Any], *, member: dict[str, str], cname: dict[str, str], succ_tag: str
) -> bool:
    """Loop 3 `다음concept`: 준 문항과 `target_concept`이 **둘 다** 후행 개념.

    `action`은 보지 않는다 — §18이 요구하는 것은 *다음 concept로 간다*이지 *특정 행위
    이름*이 아니다. (`EOS-124`가 고른 해소 방향에서는 정렬 재선택이 서면 `advance_next`가
    나가지만, 후행 개념 문항이 1차 선택으로 바로 나오면 미측정이라 `diagnose`다 — 둘 다
    다음 concept로 간 것이므로 행위 이름으로 가르지 않는다.)
    """
    return (
        member.get(str(rec["problem_id"])) == succ_tag
        and cname.get(str(rec["target_concept"])) == succ_tag
    )


# ── 관측 헬퍼 ───────────────────────────────────────────────────────────────────


def _user_id(client: Any, auth: dict[str, str]) -> str:
    """본인 user_id — 공개 표면 중 이 값을 내는 것은 반출권 export뿐이다."""
    return str(_P._get(client, auth, "/v1/me/export")["user_id"])


def _trace(client: Any, auth: dict[str, str]) -> dict[str, Any]:
    body: dict[str, Any] = _P._get(client, auth, "/v1/me/learning-trace?limit=1000")
    return body


def _mastery_row_attempt_ids(user_id: str) -> list[str | None]:
    """이 학습자의 숙달 이력 행이 가리키는 attempt_id — 읽기 전용(쓰기 0)."""

    async def _read() -> list[str | None]:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_P._settings().database_url)
        try:
            async with engine.begin() as conn:
                rows = (
                    await conn.execute(
                        text("SELECT attempt_id FROM concept_mastery_history WHERE user_id = :uid"),
                        {"uid": user_id},
                    )
                ).all()
            return [None if r[0] is None else str(r[0]) for r in rows]
        finally:
            await engine.dispose()

    return asyncio.run(_read())


def _describe(rec: dict[str, Any], member: dict[str, str], cname: dict[str, str]) -> str:
    return (
        f"문항소속={member.get(str(rec['problem_id']), '없음')} · action={rec['action']} · "
        f"reason={rec['reason']['type']} · target={cname.get(str(rec['target_concept']), '없음')}"
    )


# ── 3루프 관통 ──────────────────────────────────────────────────────────────────


def _run_journey(variant: str) -> _Journey:
    """학습자 1명이 추천을 따라 3루프를 도는 1회 관통 — 판정은 호출측이 한다."""
    content, _journal = _P._begin(f"L3-{variant}")
    try:
        # ① 저작 콘텐츠 시딩 — 로그인 *전*에 끝낸다(그 뒤로는 봉인).
        cids: dict[str, uuid.UUID] = {}
        for tag, name in (
            ("pre", "일차식의 계산"),
            ("cur", "일차방정식"),
            ("next", "연립일차방정식"),
        ):
            cids[tag], _ = _P._seed_concept(content, f"l3-{tag}", name)
        asyncio.run(_P._add_all(_P._prereq_edge(cids["pre"], cids["cur"])))
        asyncio.run(_P._add_all(_P._prereq_edge(cids["cur"], cids["next"])))
        member: dict[str, str] = {}
        for tag, bands in _DIFFICULTY_BANDS.items():
            for pid in _P._seed_problems(content, cids[tag], f"l3{tag[0]}", bands):
                member[str(pid)] = tag
        cname = {str(cid): tag for tag, cid in cids.items()}

        steps: list[str] = []
        submitted: list[str] = []
        attempted: set[str] = set()

        def mastery(tag: str) -> float | None:
            return _P._mastery_of(client, auth, cids[tag])

        def solve(rec: dict[str, Any], *, correct: bool, answer: str) -> dict[str, Any]:
            pid = str(rec["problem_id"])
            body = _P._attempt(client, auth, uuid.UUID(pid), correct=correct, answer=answer)
            submitted.append(str(body["attempt_id"]))
            attempted.add(pid)
            steps.append(
                f"{len(submitted):>2}. {_describe(rec, member, cname)} → "
                f"{'정답' if correct else '오답'} · 상태={_P._state_of(body)} · "
                f"숙달(pre/cur/next)={mastery('pre')}/{mastery('cur')}/{mastery('next')}"
            )
            return body

        with _P._client() as client:
            _P._erase_learner(client)  # 기준선 = 신규 학습자(지난 회차 잔여 제거)
            auth = _P._login(client)
            learner_before = _user_id(client, auth)

            with _Seal() as seal:
                # ── Loop 1: 진단 → 문제 → 오답 → 보정 ───────────────────────────────
                loop1 = _Loop(1)
                r0 = _P._next_problem(client, auth)
                assert r0["problem_id"] is not None, "진단 문항이 없다 — 루프가 시작되지 않는다."
                wrong_tag = member.get(str(r0["problem_id"]))
                assert wrong_tag is not None, "진단 문항이 이 회차가 심은 문항이 아니다(격리 실패)."
                succ_tag = _SUCCESSOR[wrong_tag]
                assert succ_tag is not None, (
                    f"진단이 후행 없는 개념({wrong_tag})에서 시작했다 — Loop 3 '다음 concept'를 판정할 "
                    "수 없다. 픽스처의 난이도 대역을 점검하라(판정 불가이지 통과가 아니다)."
                )
                loop1.add("진단", True, _describe(r0, member, cname))
                wrong_body = solve(r0, correct=False, answer=_WRONG_ANSWERS[variant])
                loop1.add("문제", True, f"진단 문항 제출 · 개념={wrong_tag}")
                after_wrong = mastery(wrong_tag)
                loop1.add(
                    "오답",
                    wrong_body["is_correct"] is False and after_wrong is not None,
                    f"오답 직후 {wrong_tag} 숙달={after_wrong} · 상태={_P._state_of(wrong_body)}",
                )
                r1 = _P._next_problem(client, auth)
                loop1.add(
                    "보정",
                    _remediation_fires(r1, member=member, cname=cname, wrong_tag=wrong_tag),
                    _describe(r1, member, cname),
                )

                # ── Loop 2: 보정 → 문제 → 정답 → mastery 상승 (출구 = 정책 전진 임계) ──
                loop2 = _Loop(2)
                loop2.add("보정진입", r1["problem_id"] is not None, _describe(r1, member, cname))
                budget = len(_DIFFICULTY_BANDS[wrong_tag])
                rec = r1
                crossed = False
                all_correct = True
                used = 0
                while used < budget and rec["problem_id"] is not None:
                    body = solve(rec, correct=True, answer="정답")
                    all_correct = all_correct and body["is_correct"] is True
                    used += 1
                    now = mastery(wrong_tag)
                    if now is not None and now > _ADVANCE_THRESHOLD:
                        crossed = True
                        break
                    rec = _P._next_problem(client, auth)
                final_wrong = mastery(wrong_tag)
                loop2.add("문제·정답", used > 0 and all_correct, f"추천을 따라 {used}회 정답")
                loop2.add(
                    "mastery상승",
                    after_wrong is not None
                    and final_wrong is not None
                    and final_wrong > after_wrong,
                    f"{wrong_tag} 숙달 {after_wrong} → {final_wrong}",
                )
                loop2.add(
                    "전진임계통과",
                    crossed,
                    f"{wrong_tag} 숙달 {final_wrong} > {_ADVANCE_THRESHOLD}? (예산 {budget}회 중 {used}회)",
                )

                # ── Loop 3: 다음 concept → 문제 → 평가 → 추천 ───────────────────────
                loop3 = _Loop(3)
                if not crossed:
                    for name in ("다음concept", "문제", "평가", "추천"):
                        loop3.add(name, False, "미진입 — Loop 2가 전진 임계에 닿지 못했다")
                else:
                    r3 = _P._next_problem(client, auth)
                    wrong_pids = {p for p, t in member.items() if t == wrong_tag}
                    remaining = wrong_pids - attempted
                    # 변별력 장치 — 남은 문항이 없으면 도달이 선택인지 소진인지 모른다.
                    assert remaining, (
                        f"Loop 3 관측 시점에 {wrong_tag} 미시도 문항이 0개다 — 후행 개념 도달이 선택인지 "
                        "소진인지 구별할 수 없다. 픽스처 문항 수를 늘려라(판정 불가이지 통과가 아니다)."
                    )
                    r3_problem = member.get(str(r3["problem_id"]))
                    loop3.add(
                        "다음concept",
                        _advance_fires(r3, member=member, cname=cname, succ_tag=succ_tag),
                        f"{_describe(r3, member, cname)} · 기대={succ_tag} · "
                        f"{wrong_tag} 미시도 {len(remaining)}개 남김",
                    )
                    if r3["problem_id"] is None:
                        for name in ("문제", "평가", "추천"):
                            loop3.add(name, False, "추천 문항 없음")
                    else:
                        body3 = solve(r3, correct=True, answer="정답")
                        loop3.add("문제", True, f"제출 · 개념={r3_problem}")
                        loop3.add(
                            "평가",
                            bool(body3.get("mastery_updates")),
                            f"숙달 갱신 {len(body3.get('mastery_updates') or [])}건",
                        )
                        r4 = _P._next_problem(client, auth)
                        loop3.add(
                            "추천",
                            r4["problem_id"] is not None and r4["reason"]["type"] != "no_candidate",
                            _describe(r4, member, cname),
                        )

            trace = _trace(client, auth)
            learner_after = _user_id(client, auth)
            mastery_rows = _mastery_row_attempt_ids(learner_after)

        entries = trace.get("entries") or []
        return _Journey(
            variant=variant,
            loops=[loop1, loop2, loop3],
            submitted_attempts=submitted,
            trace_attempt_ids=[
                str(e["attempt_id"])
                for e in entries
                if e["event_type"] == "problem_attempted" and e.get("attempt_id")
            ],
            trace_truncated=bool(trace.get("truncated")),
            mastery_row_attempt_ids=mastery_rows,
            learner_before=learner_before,
            learner_after=learner_after,
            sealed_calls=seal.blocked,
            steps=steps,
        )
    finally:
        content.teardown()


def _dump(journey: _Journey) -> None:
    """판정 근거 표 — 판정은 exit code가, *왜*는 이 표가 말한다."""
    print(f"\n=== 연속 3루프 [{journey.variant}] — 단계 기록 ===")
    for line in journey.steps:
        print(line)
    for lp in journey.loops:
        for node in lp.nodes:
            mark = "✓" if node.ok else "✗"
            print(f"LOOP{lp.number} {mark} {node.name:<10} | {node.evidence}")
    print(journey.verdict_line())


@pytest.fixture(scope="module", params=sorted(_WRONG_ANSWERS))
def journey(request: pytest.FixtureRequest) -> Iterator[_Journey]:
    """오답 종류별 3루프 관통 1회 — 세 테스트가 같은 관통을 본다(재실행 0)."""
    result = _run_journey(request.param)
    _dump(result)
    yield result


# ── 판정 규칙의 절별 변별력 — 관통 데이터가 밟지 않는 절을 여기서 밟는다 ─────────

#: 합성 추천의 개념 표 — 관통과 같은 태그 체계(pre·cur·next).
_SYN_MEMBER = {"p-pre": "pre", "p-cur": "cur", "p-next": "next"}
_SYN_CNAME = {"c-pre": "pre", "c-cur": "cur", "c-next": "next"}


def _syn(action: str, target: str, problem: str) -> dict[str, Any]:
    return {"action": action, "target_concept": f"c-{target}", "problem_id": f"p-{problem}"}


@pytest.mark.parametrize(
    ("rec", "fires", "why"),
    [
        (_syn("practice_prerequisite", "pre", "pre"), True, "선언·대상·문항이 모두 선수"),
        (_syn("practice_current", "cur", "cur"), True, "선언·대상·문항이 모두 틀린 개념"),
        (_syn("diagnose", "pre", "pre"), False, "ⓐ 행위 — diagnose는 보정이 아니다(현행 관측)"),
        (_syn("practice_current", "next", "next"), False, "ⓑ 대상 — 후행 개념은 보정 대상 밖"),
        (_syn("practice_prerequisite", "pre", "cur"), False, "ⓒ 문항 — EOS-124 형태(말만 선수)"),
    ],
)
def test_remediation_rule_requires_every_clause(rec: dict[str, Any], fires: bool, why: str) -> None:
    """Loop 1 `보정` 규칙의 절마다 그 절이 없으면 통과해 버리는 반례를 둔다.

    관통 데이터는 ⓐ에서 먼저 끊겨 ⓑ·ⓒ를 한 번도 밟지 않는다(2026-09-25 실측 — 행위가
    `diagnose`). 해소 PR이 ⓐ만 고치고 ⓒ(EOS-124)를 남기면 관통만으로는 그 차이가 안 보인다.
    """
    got = _remediation_fires(rec, member=_SYN_MEMBER, cname=_SYN_CNAME, wrong_tag="cur")
    assert got is fires, why


@pytest.mark.parametrize(
    ("rec", "fires", "why"),
    [
        (_syn("advance_next", "next", "next"), True, "문항·대상이 모두 후행"),
        (_syn("diagnose", "next", "next"), True, "행위 이름은 보지 않는다(EOS-124 ③ 미선점)"),
        (_syn("advance_next", "cur", "cur"), False, "문항·대상 모두 현재 — 현행 관측(EOS-124 ①가)"),
        (
            _syn("advance_next", "cur", "next"),
            False,
            "대상 축만 낡음 — 문항은 후행인데 설명이 현재",
        ),
        (_syn("advance_next", "next", "cur"), False, "선택 축만 낡음 — 말만 전진"),
    ],
)
def test_advance_rule_requires_both_axes(rec: dict[str, Any], fires: bool, why: str) -> None:
    """Loop 3 `다음concept` 규칙 — 두 축 중 하나만 맞으면 서지 않는다."""
    got = _advance_fires(rec, member=_SYN_MEMBER, cname=_SYN_CNAME, succ_tag="next")
    assert got is fires, why


# ── 불변식 — 판정과 무관하게 항상 초록 ──────────────────────────────────────────


def test_three_loops_are_operator_free_and_continuous(journey: _Journey) -> None:
    """무개입·연속성: 학습자 축의 모든 변화가 이 하네스의 HTTP 제출로 거슬러 올라간다."""
    assert journey.sealed_calls == 0, "학습 도중 DB 직접 쓰기가 시도됐다(봉인 발동)."
    assert (
        journey.learner_before == journey.learner_after
    ), "루프 도중 학습자가 바뀌었다 — '연속' 3루프가 아니다."
    assert not journey.trace_truncated, "학습 시간선이 잘렸다 — 역추적 근거가 전체가 아니다."
    assert sorted(journey.trace_attempt_ids) == sorted(journey.submitted_attempts), (
        "시간선의 시도 이벤트가 HTTP 제출과 다르다 — 이 하네스 밖에서 시도가 생겼거나 사라졌다: "
        f"제출 {len(journey.submitted_attempts)}건 · 시간선 {len(journey.trace_attempt_ids)}건"
    )
    # 0건이면 아래 부분집합 검사가 공허하게 통과한다(스캔 0건은 실패).
    assert journey.mastery_row_attempt_ids, "숙달 이력 행이 0건이다 — 역추적할 대상이 없다."
    submitted = set(journey.submitted_attempts)
    outsiders = [a for a in journey.mastery_row_attempt_ids if a is None or a not in submitted]
    assert (
        not outsiders
    ), f"HTTP 제출로 거슬러 올라가지 않는 숙달 이력 행이 있다(None=attempt 없는 행): {outsiders}"
    # Loop 2의 §18 문면(정답 → mastery 상승)은 동결 대상이 아니라 불변식이다 — 지금 성립하고,
    # 깨지면 그것은 공백이 아니라 회귀다.
    assert journey.loops[1].holds, f"Loop 2가 끊겼다(회귀): {journey.loops[1].as_map()}"


# ── 정직한 공백 동결 — 마디별 현재 판정 ────────────────────────────────────────

#: 2026-09-25 main `bbd7c382` 실측. 두 오답 종류 모두 같은 마디에서 끊긴다 — 오개념 오답은
#: 상태 머신을 `REMEDIATING`으로 보내지만 추천은 그 상태를 읽지 않는다(판정문 §3-3 ①과 같은
#: 형태가 오답 종류와 무관하게 재현된다).
_FROZEN: dict[int, dict[str, bool]] = {
    1: {"진단": True, "문제": True, "오답": True, "보정": False},
    2: {"보정진입": True, "문제·정답": True, "mastery상승": True, "전진임계통과": True},
    # EOS-124(PR #1317) 해소 — 임계 통과 직후 추천이 현재 개념에 미시도 문항이 남아 있어도
    # 후행 개념 문항·target을 낸다(정렬 재선택). False→True 승격.
    3: {"다음concept": True, "문제": True, "평가": True, "추천": True},
}

#: 동결된 공백의 소유자 — 해소 신호가 났을 때 메시지가 가리킬 곳.
_GAP_OWNERS: dict[tuple[int, str], str] = {
    (1, "보정"): (
        "`EOS-24-recommendation-reads-learning-state`(추천 정책이 학습 상태 머신을 읽지 않음 — "
        "2026-09-24 재판정이 #1295로 등재)"
    ),
    # (3, "다음concept")은 EOS-124로 해소돼 표에서 뺐다 — 남은 공백만 소유자를 가진다.
}


def test_three_loop_verdict_matches_frozen_gap(journey: _Journey) -> None:
    """마디별 판정이 동결값과 같은가 — 달라지면 개선인지 회귀인지 갈라서 말한다."""
    observed = journey.as_map()
    improved: list[str] = []
    regressed: list[str] = []
    for number, frozen_nodes in _FROZEN.items():
        assert observed.get(number, {}).keys() == frozen_nodes.keys(), (
            f"Loop {number}의 마디 구성이 바뀌었다: {sorted(observed.get(number, {}))} vs "
            f"{sorted(frozen_nodes)} — 판정 규칙을 바꿨다면 동결표를 함께 고친다."
        )
        for name, was in frozen_nodes.items():
            now = observed[number][name]
            if now and not was:
                owner = _GAP_OWNERS.get((number, name), "소유자 미상")
                improved.append(f"Loop {number} '{name}' False→True (소유자: {owner})")
            elif was and not now:
                regressed.append(f"Loop {number} '{name}' True→False")
    assert not regressed, (
        "회귀 — 성립하던 마디가 끊겼다. 이 변경이 연속 3루프를 깼다: "
        + " · ".join(regressed)
        + f"\n{journey.verdict_line()}"
    )
    assert not improved, (
        "해소 신호 — 동결된 공백이 메워졌다. `_FROZEN`을 새 값으로 올리고, 전 마디가 True면 "
        "`test_plan300_s18_three_consecutive_loops_hold`의 xfail을 제거하라: "
        + " · ".join(improved)
        + f"\n{journey.verdict_line()}"
    )


# ── §18 계약 — 지금은 미충족(XFAIL로 보인다) ───────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "계획서 300 §18 무개입 연속 3루프 미충족 — Loop 1 '보정'(오답 직후 추천이 diagnose · "
        "EOS-24). Loop 3 '다음concept'은 EOS-124(PR #1317)로 해소됐다. 해소 시 XPASS가 strict "
        "실패로 바뀐다 — 이 표식과 _FROZEN을 함께 올린다."
    ),
)
def test_plan300_s18_three_consecutive_loops_hold(journey: _Journey) -> None:
    """§18 문면 그대로: 세 루프의 전 마디가 성립한다."""
    broken = [
        f"Loop {lp.number} '{n.name}' ({n.evidence})"
        for lp in journey.loops
        for n in lp.nodes
        if not n.ok
    ]
    assert not broken, "끊긴 마디: " + " · ".join(broken)
