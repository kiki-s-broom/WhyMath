"""미분 단원 오답 서명 독법(P3-06) — 잡는가, 안 잡아야 할 것을 안 잡는가, 그리고 그 보호가 진짜인가.

이 파일의 원칙은 CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"다. 정상 입력에서
초록인 것은 증거가 아니므로 각 보호를 **깨뜨려 RED를 확인**한다:

  ① 규칙 하나를 지우면 그 규칙의 오답이 더는 안 잡힌다          (규칙이 실제로 일하고 있다)
  ② 변환이 낸 오답 값을 어긋나게 하면 안 잡힌다                  (변환 값과 학생 답의 대조가 실제로 돈다)
  ③ 대조를 항상 참/거짓으로 만들면 픽스처가 깨진다               (대조가 무력화되면 픽스처가 알아챈다)
  ④ 오답을 정답으로 바꾸면 안 잡힌다                            (정답 가드)
  ⑤ 신뢰도를 게이트 하한 아래로 내리면 후보가 사라진다            (새 독법도 같은 게이트를 지난다)
  ⑥ 규칙표 적재가 실패하면 기존 채널은 살고, 실패는 숨지 않는다   (격리 + 침묵 실패 금지)

모든 주입은 `mutated != original`(주입이 실제로 적용됐는지)과 원복을 함께 단언한다 — 미적용 주입이
"검출"처럼 보이는 위장을 막는다(2026-09-06 규칙).

픽스처의 오답 값은 두 출처 중 하나다: 문항은행 `distractor_map`(별도 생성기가 만든 **독립 오라클**) 또는
엔진과 무관한 단순 계산. 정답은 문항은행의 기계 검증 정답을 쓴다 — 이 파일이 손으로 다시 적지 않는다.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

import pytest
import sympy

from whymath_backend.harness.wrong_answer_remediation_report import (
    BankProblem,
    iter_approved_problems,
)
from whymath_backend.l1.misconception import wrong_answer_tables as tables
from whymath_backend.l4.misconception import derivative_signature as ds
from whymath_backend.l4.misconception.answer_signature import scan_attempt_answer
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.schema.assessment_evidence import MisconceptionScan
from whymath_backend.schema.wrong_answer_remediation import SignatureRule, SignatureSpec

_OUR_KEBABS = frozenset(
    {
        "power-rule-step-omitted",
        "product-rule-naive",
        "critical-point-implies-extremum",
        "continuity-implies-differentiability",
        "extremum-max-min-confused",
        "extremum-value-vs-point-confused",
    }
)


@pytest.fixture(scope="module")
def problems() -> list[BankProblem]:
    rows = list(iter_approved_problems())
    assert len(rows) > 3000, f"승인 문항 {len(rows)}건 — 코퍼스를 못 읽었다(공허한 통과 방지)"
    return rows


@pytest.fixture(scope="module")
def by_id(problems: list[BankProblem]) -> dict[str, BankProblem]:
    return {p.problem_id: p for p in problems}


def _kebabs(question: str, answer: str) -> set[str]:
    return {m.misconception.id for m in ds.detect_derivative_signature(question, answer).matches}


@pytest.fixture(autouse=True)
def _fresh_rule_caches() -> Iterator[None]:
    """주입 테스트가 규칙표 캐시를 어지럽히지 않게 앞뒤로 비운다."""
    ds.compile_rules.cache_clear()
    yield
    ds.compile_rules.cache_clear()


# ── ① 규칙표 ↔ 엔진 레지스트리 ─────────────────────────────────────────────────────────────


class TestRuleTable:
    def test_every_rule_compiles_and_resolves_to_a_catalog_kebab(self) -> None:
        compiled = ds.compile_rules()
        assert len(compiled) == len(tables.load_signature_spec().rules) >= 10
        for item in compiled:
            assert item.kebab_id in CATALOG_BY_ID
            assert item.kebab_id in _OUR_KEBABS

    def test_registry_has_no_dead_entries(self) -> None:
        """규칙이 쓰지 않는 질문 추출기·변환은 죽은 코드다 — 레지스트리와 데이터가 함께 움직이게 한다."""
        rules = tables.load_signature_spec().rules
        assert {r.ask for r in rules} == set(ds.ASK_EXTRACTORS)
        assert {r.wrong_transform for r in rules} == set(ds.WRONG_TRANSFORMS)

    def test_every_transform_declares_only_registered_asks(self) -> None:
        for name, (supported, _) in ds.WRONG_TRANSFORMS.items():
            assert supported <= set(ds.ASK_EXTRACTORS), name

    @staticmethod
    def _spec_with(**override: Any) -> SignatureSpec:
        base: dict[str, Any] = {
            "rule_id": "sig.injected",
            "mis_ids": ["M0671"],
            "ask": "derivative_at",
            "wrong_transform": "power_rule_step_omitted",
            "confidence": 0.9,
            "evidence": "direct",
            "note": "주입",
            "fixtures": {"wrong": [{"problem_id": "x", "answer": "1", "note": "n"}]},
        }
        base.update(override)
        return SignatureSpec.model_validate(
            {
                "schema_version": "1.0.0",
                "spec_id": "wrong_answer_signatures_v1",
                "rules": [base],
            }
        )

    @pytest.mark.parametrize(
        ("override", "why"),
        [
            ({"ask": "no_such_ask"}, "모르는 ask"),
            ({"wrong_transform": "no_such_transform"}, "모르는 wrong_transform"),
            ({"ask": "extremum_count"}, "변환이 지원하지 않는 ask"),
            ({"mis_ids": ["M0673"]}, "kebab 좌석이 없는 M-id"),
            ({"mis_ids": ["M0671", "M0864"]}, "서로 다른 kebab에 걸린 M-id들"),
        ],
    )
    def test_inconsistent_rule_is_refused_at_load(
        self, monkeypatch: pytest.MonkeyPatch, override: dict[str, Any], why: str
    ) -> None:
        """데이터가 레지스트리·크로스워크와 어긋나면 조용히 건너뛰지 않고 적재를 거부한다."""
        monkeypatch.setattr(ds, "load_signature_spec", lambda: self._spec_with(**override))
        ds.compile_rules.cache_clear()
        with pytest.raises(ds.DerivativeSignatureError):
            ds.compile_rules()


# ── ② 규칙 픽스처 전건 ────────────────────────────────────────────────────────────────────


def _fixture_params() -> list[Any]:
    out: list[Any] = []
    for rule in tables.load_signature_spec().rules:
        for kind in ("wrong", "not_wrong"):
            for i, fx in enumerate(getattr(rule.fixtures, kind)):
                out.append(pytest.param(rule, kind, fx, id=f"{rule.rule_id}:{kind}{i}"))
    return out


class TestFixtures:
    @pytest.mark.parametrize(("rule", "kind", "fx"), _fixture_params())
    def test_fixture_behaves_as_declared(
        self, by_id: dict[str, BankProblem], rule: SignatureRule, kind: str, fx: Any
    ) -> None:
        problem = by_id[fx.problem_id]  # 키 오류 = 코퍼스에 없는 문항 — 실패가 맞다
        compiled = {c.rule.rule_id: c for c in ds.compile_rules()}[rule.rule_id]
        result = ds.detect_derivative_signature(problem.question_text, fx.answer)
        kebabs = {m.misconception.id for m in result.matches}
        if kind == "wrong":
            assert fx.answer != problem.answer, "오답 픽스처가 문항은행의 기계 검증 정답과 같다"
            assert compiled.kebab_id in kebabs, f"{rule.rule_id}: 오답이 안 잡힌다"
            hit = next(m for m in result.matches if m.misconception.id == compiled.kebab_id)
            assert hit.confidence == rule.confidence
            assert hit.matched_signals == (rule.rule_id,)
        else:
            assert (
                compiled.kebab_id not in kebabs
            ), f"{rule.rule_id}: 잡으면 안 되는 답이 잡혔다(오탐)"
            # 공허한 통과 방지: 이 규칙이 질문을 **실제로 읽었어야** '안 잡혔다'가 의미를 가진다.
            assert ds.ASK_EXTRACTORS[rule.ask](problem.question_text) is not None
            assert (
                result.applicable
            ), f"{rule.rule_id}: 규칙이 질문을 읽지 못했다 — 오탐 픽스처가 공허하다"

    def test_every_rule_has_a_clean_fixture(self) -> None:
        """오탐을 재는 픽스처가 없는 규칙은 '정답을 오개념으로 잡지 않는다'를 주장할 근거가 없다."""
        missing = [
            r.rule_id for r in tables.load_signature_spec().rules if not r.fixtures.not_wrong
        ]
        assert not missing, missing


# ── ③ 변별력 주입: 보호가 진짜인가 ─────────────────────────────────────────────────────────


def _wrong_fixture_cases(by_id: dict[str, BankProblem]) -> list[tuple[SignatureRule, str, str]]:
    return [
        (rule, by_id[fx.problem_id].question_text, fx.answer)
        for rule in tables.load_signature_spec().rules
        for fx in rule.fixtures.wrong
    ]


class TestInjectionRed:
    def test_removing_a_rule_silences_exactly_its_wrong_fixtures(
        self, monkeypatch: pytest.MonkeyPatch, by_id: dict[str, BankProblem]
    ) -> None:
        """① 규칙 하나를 지우면 그 규칙의 오답이 안 잡힌다 — 규칙이 실제로 일하고 있다는 증거."""
        original = ds.compile_rules()
        for target in original:
            mutated = tuple(c for c in original if c.rule.rule_id != target.rule.rule_id)
            assert len(mutated) == len(original) - 1, "주입 미적용 — 테스트 무효"
            with monkeypatch.context() as patch:  # 반복마다 확실히 원복된다
                patch.setattr(ds, "compile_rules", lambda m=mutated: m)
                for fx in target.rule.fixtures.wrong:
                    question = by_id[fx.problem_id].question_text
                    assert target.kebab_id not in _kebabs(
                        question, fx.answer
                    ), f"{target.rule.rule_id}: 규칙을 지웠는데도 잡힌다 — 다른 경로가 새고 있다"
            # 원복 확인 — 컨텍스트를 나오면 원래 규칙 수로 돌아온다.
            assert len(ds.compile_rules()) == len(original)

    def test_corrupting_each_transform_makes_its_fixtures_undetected(
        self, monkeypatch: pytest.MonkeyPatch, by_id: dict[str, BankProblem]
    ) -> None:
        """② 변환이 낸 오답 값을 어긋나게 하면 안 잡힌다 — 변환 값과 학생 답의 대조가 실제로 돈다."""
        kebab_of = {c.rule.rule_id: c.kebab_id for c in ds.compile_rules()}
        for name, (supported, fn) in list(ds.WRONG_TRANSFORMS.items()):
            calls: list[int] = []

            def corrupted(
                frame: Any, ask: Any, _fn: Callable[..., Any] = fn, _c: list[int] = calls
            ) -> Any:
                values = _fn(frame, ask)
                if values is None:
                    return None
                _c.append(1)
                return replace(values, wrongs=tuple(w + 10_007 for w in values.wrongs))

            with monkeypatch.context() as patch:
                patch.setitem(ds.WRONG_TRANSFORMS, name, (supported, corrupted))
                for rule, question, answer in _wrong_fixture_cases(by_id):
                    if rule.wrong_transform != name:
                        continue
                    assert kebab_of[rule.rule_id] not in _kebabs(
                        question, answer
                    ), f"{name}: 변환을 오염시켰는데 잡힌다"
            assert calls, f"{name}: 오염된 변환이 한 번도 불리지 않았다 — 주입 미적용, 테스트 무효"
            assert ds.WRONG_TRANSFORMS[name][1] is fn, "원복 실패 — 후속 테스트가 오염된다"

    def test_disabling_the_value_comparison_is_noticed_by_the_fixtures(
        self, monkeypatch: pytest.MonkeyPatch, by_id: dict[str, BankProblem]
    ) -> None:
        """③ 대조를 항상 거짓으로 만들면 오답 픽스처가, 항상 참으로 만들면 정상 픽스처가 알아챈다."""
        cases = _wrong_fixture_cases(by_id)
        monkeypatch.setattr(ds, "_same_value", lambda *_a, **_k: False)
        silent = sum(
            1
            for rule, q, a in cases
            if {c.rule.rule_id: c.kebab_id for c in ds.compile_rules()}[rule.rule_id]
            not in _kebabs(q, a)
        )
        assert silent == len(cases), "대조를 껐는데도 잡힌 오답이 있다"

        monkeypatch.setattr(ds, "_same_value", lambda *_a, **_k: True)
        for rule in tables.load_signature_spec().rules:
            kebab = {c.rule.rule_id: c.kebab_id for c in ds.compile_rules()}[rule.rule_id]
            flagged = [
                fx
                for fx in rule.fixtures.not_wrong
                if kebab in _kebabs(by_id[fx.problem_id].question_text, fx.answer)
            ]
            # 정상 답이 하나도 안 걸리는 규칙은 오탐 픽스처가 대조 단계에 닿지도 않는 것이다.
            assert (
                flagged
            ), f"{rule.rule_id}: 대조를 항상 참으로 만들어도 오탐 픽스처가 반응하지 않는다"

    def test_replacing_wrong_answers_with_the_correct_one_removes_detection(
        self, by_id: dict[str, BankProblem]
    ) -> None:
        """④ 오답을 정답으로 바꾸면 안 잡힌다 — 정답을 오개념으로 잡는 오탐의 직접 반증."""
        kebab_of = {c.rule.rule_id: c.kebab_id for c in ds.compile_rules()}
        for rule in tables.load_signature_spec().rules:
            for fx in rule.fixtures.wrong:
                problem = by_id[fx.problem_id]
                assert problem.answer != fx.answer, "주입 미적용 — 정답과 오답이 같다"
                assert kebab_of[rule.rule_id] in _kebabs(problem.question_text, fx.answer)
                assert kebab_of[rule.rule_id] not in _kebabs(problem.question_text, problem.answer)

    def test_changing_the_question_removes_detection(self, by_id: dict[str, BankProblem]) -> None:
        """문항의 함수식·점을 바꾸면 같은 답이 더는 그 규칙의 오답 값이 아니다 — 답이 문항에 묶여 있다."""
        cases = [
            # (문항 일부, 오답, 바꾼 질문 조각)
            ("y = x^8의 도함수 y'에 대하여 x = 4일 때", "16384", ("x = 4일 때", "x = 5일 때")),
            ("f(x) = -2x^3(x - 4)가 극값을 갖는", "0", ("-2x^3(x - 4)", "-2x^3(x - 4) + x")),
            ("f(x) = x^3 - 3x^2 - 105x 의 극솟값으로", "325", ("105x", "106x")),
            ("f(x) = |x - 2| 가 실수 전체에서", "1", ("|x - 2|", "(x - 2)^2")),
        ]
        for needle, wrong, (old, new) in cases:
            problem = next(p for p in by_id.values() if needle in p.question_text)
            before = _kebabs(problem.question_text, wrong) & _OUR_KEBABS
            mutated_q = problem.question_text.replace(old, new, 1)
            assert mutated_q != problem.question_text, "주입 미적용 — 테스트 무효"
            assert before, f"{needle}: 원문에서 먼저 잡혀야 변별을 잴 수 있다"
            assert not (
                _kebabs(mutated_q, wrong) & before
            ), f"{needle}: 질문을 바꿨는데도 같은 후보"


# ── ④ 전수 점검: 코퍼스 전체에서 오탐 0 · 오귀속 0 · 재현율 래칫 ───────────────────────────────


#: 문항은행이 오개념으로 표시한 오답 보기를 이 독법이 **서명만으로**(선지 인덱스 없이) 재현하는 수의
#: 하한 래칫. 2026-10-16 실측값이다. 내려가면 읽던 질문 형식을 잃은 것이고, 올라가면 이 표를 올려라.
#: 분모는 문항은행이 해당 kebab으로 표시한 보기 전체 — 읽지 못한 질문 형식(역문제·접선 y절편·속도 등)이
#: 분모에 그대로 남아 있으므로 비율이 100%가 아닌 것은 정직한 사정거리다.
_ORACLE_RECALL_FLOOR: dict[str, tuple[int, int]] = {
    "power-rule-step-omitted": (24, 66),
    "product-rule-naive": (30, 36),
    "critical-point-implies-extremum": (36, 36),
    "continuity-implies-differentiability": (24, 24),
    "extremum-max-min-confused": (56, 56),
    "extremum-value-vs-point-confused": (112, 124),
}


class TestCorpusSweeps:
    def test_no_correct_answer_is_ever_read_as_a_misconception(
        self, problems: list[BankProblem]
    ) -> None:
        """승인 문항 전체의 정답을 학생 답으로 훑어 후보가 나오는 수 = 0 (오탐 전수 점검)."""
        positives: list[str] = []
        readable = 0
        for p in problems:
            result = ds.detect_derivative_signature(p.question_text, p.answer)
            readable += result.applicable
            if result.matches:
                positives.append(p.problem_id)
        assert not positives, f"정답을 오개념으로 읽은 문항 {len(positives)}건: {positives[:3]}"
        # 공허한 통과 방지 — 질문을 거의 못 읽는 상태에서 오탐 0은 의미가 없다.
        assert readable >= 350, f"읽은 문항이 {readable}건뿐이다 — 질문 추출기가 퇴행했다"

    def test_engine_computed_correct_value_equals_the_banks_machine_verified_answer(
        self, problems: list[BankProblem]
    ) -> None:
        """질문을 잘못 읽었는지의 가장 직접적인 신호 — 엔진이 질문에서 계산한 정답이 문항은행의 정답과 같은가.

        '정답을 오답으로 읽지 않는다'만 보면 질문을 엉뚱하게 읽어도 우연히 초록일 수 있다(2026-10-16
        뮤테이션 M05 생존으로 발각: f'(a) 얽힘 가드를 지워도 통과했다). 이 검사는 읽은 질문마다 엔진의
        정답을 문항은행의 기계 검증 정답과 직접 대조해, 읽은 것이 실제로 그 문항이 묻는 양인지 잰다.
        """
        from whymath_backend.l3.symbolic_equivalence import (
            IdentityVerdict,
            identity_status,
            to_sympy_source,
        )

        compiled = ds.compile_rules()
        checked = 0
        mismatches: list[tuple[str, str]] = []
        for p in problems:
            for item in compiled:
                ask = ds.ASK_EXTRACTORS[item.rule.ask](p.question_text)
                if ask is None:
                    continue
                frame = ds._read_frame(p.question_text, allow_abs=ask.kind in ds._ASKS_NEEDING_ABS)
                if frame is None:
                    continue
                values = ds.WRONG_TRANSFORMS[item.rule.wrong_transform][1](frame, ask)
                if values is None or values.correct is sympy.nan:
                    continue  # 단일 정답이 없는 질문(극값을 갖는 x 전부)은 대조 대상이 아니다
                checked += 1
                verdict = identity_status(to_sympy_source(p.answer), str(values.correct))
                if verdict is not IdentityVerdict.identity:
                    mismatches.append((item.rule.rule_id, p.problem_id))
        assert (
            not mismatches
        ), f"엔진 정답이 은행 정답과 다른 읽기 {len(mismatches)}건: {mismatches[:3]}"
        # 공허한 통과 방지 — 측정값 493건(2026-10-16). 크게 줄면 질문 추출기가 퇴행한 것이다.
        assert checked >= 480, f"대조한 읽기가 {checked}건뿐이다"

    def test_wrong_distractors_are_never_attributed_to_a_different_misconception(
        self, problems: list[BankProblem]
    ) -> None:
        """문항은행이 다른 오개념(또는 미지정)으로 둔 보기에 우리 kebab을 붙이지 않는다 — 오귀속 0."""
        misattributed: list[tuple[str, int, str]] = []
        for p in problems:
            tagged = {int(d["choice_index"]): d["misconception_id"] for d in p.distractor_map}
            for i, choice in enumerate(p.choices):
                if choice == p.answer:
                    continue
                for kebab in _kebabs(p.question_text, choice):
                    if tagged.get(i) != kebab:
                        misattributed.append((p.problem_id, i, kebab))
        assert not misattributed, f"오귀속 {len(misattributed)}건: {misattributed[:3]}"

    def test_signature_reproduces_the_independent_oracle_at_least_as_well_as_the_floor(
        self, problems: list[BankProblem]
    ) -> None:
        hits: Counter[str] = Counter()
        total: Counter[str] = Counter()
        for p in problems:
            for d in p.distractor_map:
                kebab = d["misconception_id"]
                if kebab not in _OUR_KEBABS:
                    continue
                total[kebab] += 1
                if kebab in _kebabs(p.question_text, p.choices[int(d["choice_index"])]):
                    hits[kebab] += 1
        assert set(total) == set(_ORACLE_RECALL_FLOOR), "오라클 분모가 래칫 표와 다르다"
        for kebab, (floor_hits, floor_total) in _ORACLE_RECALL_FLOOR.items():
            assert (
                total[kebab] == floor_total
            ), f"{kebab}: 분모가 {floor_total}에서 {total[kebab]}로 바뀌었다"
            assert (
                hits[kebab] >= floor_hits
            ), f"{kebab}: 재현율 {hits[kebab]}/{total[kebab]} < 하한 {floor_hits}"


# ── ⑤ 질문 읽기의 경계: 읽을 것과 읽지 않을 것 ────────────────────────────────────────────


class TestReadBoundaries:
    @pytest.mark.parametrize(
        ("question", "wrong", "kebab"),
        [
            # 지수 규칙: f'(3) = 8·3^7 = 17496. 내리기만 52488, 1 줄이기만 2187.
            ("함수 f(x) = x^8에 대하여 f'(3)의 값은?", "52488", "power-rule-step-omitted"),
            ("함수 f(x) = x^8에 대하여 f'(3)의 값은?", "2187", "power-rule-step-omitted"),
            # 곱의 미분: (3x-6)(-2x²-5x-3), f'(-2) = -39. f'g' = 3·3 = 9.
            (
                "함수 f(x) = (3x - 6)(-2x^2 - 5x - 3)에 대하여 f'(-2)의 값은?",
                "9",
                "product-rule-naive",
            ),
            # 극값: f=x³-3x는 x=-1 극대(값 2), x=1 극소(값 -2).
            (
                "삼차함수 f(x) = x^3 - 3x가 극대가 되는 x의 값을 구하시오.",
                "1",
                "extremum-max-min-confused",
            ),
            ("삼차함수 f(x) = x^3 - 3x의 극댓값을 구하시오.", "-2", "extremum-max-min-confused"),
            (
                "삼차함수 f(x) = x^3 - 3x의 극댓값을 구하시오.",
                "-1",
                "extremum-value-vs-point-confused",
            ),
            # 부호가 안 바뀌는 임계점: f=x³+3x²+3x=(x+1)³-1은 f'(-1)=0이지만 극값이 하나도 없다.
            (
                "함수 f(x) = x^3 + 3x^2 + 3x가 극값을 갖는 x좌표는?",
                "-1",
                "critical-point-implies-extremum",
            ),
        ],
    )
    def test_independently_derived_wrong_values_are_caught(
        self, question: str, wrong: str, kebab: str
    ) -> None:
        assert kebab in _kebabs(question, wrong)

    @pytest.mark.parametrize(
        ("question", "correct"),
        [
            ("함수 f(x) = x^8에 대하여 f'(3)의 값은?", "17496"),
            ("함수 f(x) = (3x - 6)(-2x^2 - 5x - 3)에 대하여 f'(-2)의 값은?", "-39"),
            ("삼차함수 f(x) = x^3 - 3x가 극대가 되는 x의 값을 구하시오.", "-1"),
            ("삼차함수 f(x) = x^3 - 3x의 극댓값을 구하시오.", "2"),
        ],
    )
    def test_independently_derived_correct_values_are_not_caught(
        self, question: str, correct: str
    ) -> None:
        assert not (_kebabs(question, correct) & _OUR_KEBABS)

    @pytest.mark.parametrize(
        "question",
        [
            "두 함수 f(x) = x^2, g(x) = x^3 에 대하여 f(x) + g(x) 의 x = 2 에서의 미분계수를 구하시오.",
            "함수 f(x) = x^3에 대하여 f'(a)의 값이 f'(1)의 값보다 45만큼 클 때, 양수 a의 값을 구하시오.",
            "곡선 y = x^3 - 3x^2 + 3x - 5 위의 x좌표가 2인 점에서의 접선의 기울기에서 "
            "x좌표가 -2인 점에서의 접선의 기울기를 뺀 값을 구하시오.",
            "함수 f(x) = x^4에 대하여 f'(2)의 값은 f(2)의 값의 몇 배인지 구하시오.",
            "함수 f(x) = x^3 + ax에 대하여 f'(2)의 값은?",
            "함수 f(x) = sin x에 대하여 f'(0)의 값은?",
            "삼차함수 f(x) = x^3 - 3x의 구간 [0, 2]에서 극댓값을 구하시오.",
            "삼차함수 f(x) = x^3 - 3x가 극댓값 M을 가질 때, 상수 M의 값을 구하시오.",
            "방정식 x^3 - 3x = 0의 서로 다른 실근의 개수를 구하시오.",
        ],
    )
    def test_questions_outside_the_readable_range_are_reported_unreadable_not_clean(
        self, question: str
    ) -> None:
        """읽지 못한 질문은 '후보 없음'이 아니라 '볼 수 없음'(applicable=False)으로 드러난다."""
        result = ds.detect_derivative_signature(question, "7")
        assert result.applicable is False
        assert result.matches == ()

    def test_composite_function_is_not_read_as_a_power_rule_error(self) -> None:
        """합성함수 (2x+3)³의 전개식에 지수 규칙 변환이 우연히 걸려도 증거가 아니다(2026-10-16 실측 2건)."""
        question = "함수 f(x) = (2x + 3)^3 의 x = 2 에서의 미분계수 f'(2) 의 값을 구하시오."
        assert "power-rule-step-omitted" not in _kebabs(question, "588")

    def test_gate_state_and_unclear_attribution_when_two_misconceptions_explain_one_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """같은 답이 서로 다른 오개념 둘의 값이면 둘 다 후보로 내되 확신 진단은 보류시킨다."""
        base = next(
            c
            for c in ds.compile_rules()
            if c.rule.rule_id.startswith("sig.power-rule.omit-step.derivative")
        )
        clone = replace(base, kebab_id="product-rule-naive")
        single = (base,)
        both = (base, clone)
        question = "함수 f(x) = x^8에 대하여 f'(3)의 값은?"

        monkeypatch.setattr(ds, "compile_rules", lambda: single)
        one = ds.detect_derivative_signature(question, "52488").matches
        assert [m.attribution_unclear for m in one] == [False]

        monkeypatch.setattr(ds, "compile_rules", lambda: both)
        two = ds.detect_derivative_signature(question, "52488").matches
        assert len(two) == 2, "주입 미적용 — 두 번째 규칙이 후보를 내지 않았다"
        assert all(m.attribution_unclear for m in two)


# ── ⑥ 악성·퇴화 입력 ───────────────────────────────────────────────────────────────────────


class TestHostileInput:
    @pytest.mark.parametrize(
        "answer",
        [
            "__import__('os').system('echo x')",
            "exec(chr(111)+chr(112))",
            "9^9^9",
            "9**9**9",
            "(x+y+z+w+v)^60",
            "x" * 5000,
            "",
            "   ",
            "∞",
            "1/0",
        ],
    )
    def test_hostile_answers_neither_crash_hang_nor_match(self, answer: str) -> None:
        """R22-03: 학생 답은 안전 진입점을 거쳐 거부된다 — 예외를 올리거나 오래 걸리면 안 된다."""
        started = time.perf_counter()
        result = ds.detect_derivative_signature("함수 f(x) = x^8에 대하여 f'(3)의 값은?", answer)
        assert time.perf_counter() - started < 3.0
        assert result.matches == ()

    def test_hostile_question_text_is_unreadable_not_executed(self) -> None:
        result = ds.detect_derivative_signature(
            "함수 f(x) = __import__('os')에 대하여 f'(3)의 값은?", "7"
        )
        assert result.applicable is False


# ── ⑦ 기존 단일 진입점에 합쳐진 모습 ───────────────────────────────────────────────────────


def _scan(question: str, answer: str | None) -> Any:
    return scan_attempt_answer(question_text=question, student_answer=answer)


class TestScanIntegration:
    Q = "함수 f(x) = x^8에 대하여 f'(3)의 값은?"

    def test_wrong_answer_yields_gated_candidate_with_rules_scanned_disclosed(self) -> None:
        result = _scan(self.Q, "52488")
        assert result.scan is MisconceptionScan.RAN_WITH_CANDIDATES
        assert [c.misconception_id for c in result.candidates] == ["power-rule-step-omitted"]
        assert result.candidates[0].gate_passed is True
        assert result.signature_rules_scanned == len(tables.load_signature_spec().rules)

    def test_correct_answer_is_ran_no_candidate_not_not_run(self) -> None:
        result = _scan(self.Q, "17496")
        assert result.scan is MisconceptionScan.RAN_NO_CANDIDATE
        assert result.candidates == ()
        assert result.signature_rules_scanned > 0

    def test_question_the_old_channel_cannot_read_is_still_read_by_the_new_one(self) -> None:
        """연산자 없는 식(`f(x) = 3x`)은 기존 거짓 항등식 채널이 서명을 못 뽑는다 — 새 독법만 읽는 경로.

        뮤테이션 M08 생존으로 발각: 이 경로를 NOT_RUN으로 접어도 테스트가 몰랐다.
        """
        from whymath_backend.l4.misconception.answer_signature import extract_error_signature

        question = "함수 f(x) = 3x에 대하여 f'(3)의 값은?"
        assert (
            extract_error_signature(question, "9") is None
        ), "전제 깨짐 — 기존 채널이 이 질문을 읽는다"
        wrong = _scan(question, "9")  # 3x를 3x로 둔 채(1을 줄이는 것만 빠뜨리지 않고) 곱만 한 값
        assert wrong.scan is MisconceptionScan.RAN_WITH_CANDIDATES
        assert [c.misconception_id for c in wrong.candidates] == ["power-rule-step-omitted"]
        correct = _scan(question, "3")
        assert (
            correct.scan is MisconceptionScan.RAN_NO_CANDIDATE
        ), "읽은 질문의 정답은 NOT_RUN이 아니다"

    def test_unreadable_question_stays_not_run(self) -> None:
        """두 독법 모두 재료를 못 읽으면 종전대로 NOT_RUN — 0건을 '오개념 없음'으로 읽히게 하지 않는다."""
        assert _scan("x를 구하라.", "3").scan is MisconceptionScan.NOT_RUN

    @pytest.mark.parametrize("answer", [None, "", "   "])
    def test_missing_or_blank_answer_is_not_run(self, answer: str | None) -> None:
        assert _scan(self.Q, answer).scan is MisconceptionScan.NOT_RUN

    def test_candidate_below_gate_floor_is_dropped_by_the_same_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """⑤ 새 독법도 기존 품질 게이트를 지난다 — 신뢰도를 floor(0.65) 아래로 내리면 후보가 사라진다."""
        real = ds.compile_rules()
        low = tuple(
            replace(c, rule=c.rule.model_construct(**{**c.rule.__dict__, "confidence": 0.3}))
            for c in real
        )
        assert low[0].rule.confidence != real[0].rule.confidence, "주입 미적용 — 테스트 무효"
        assert _scan(self.Q, "52488").scan is MisconceptionScan.RAN_WITH_CANDIDATES
        monkeypatch.setattr(ds, "compile_rules", lambda: low)
        result = _scan(self.Q, "52488")
        assert result.scan is MisconceptionScan.RAN_NO_CANDIDATE
        assert result.candidates == ()

    def test_rule_table_load_failure_keeps_the_old_channel_alive_and_is_not_silent(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """⑥ 규칙표가 깨져도 거짓 항등식 채널은 산다. 실패는 예외 타입명과 함께 로그에 남고 응답이 드러낸다."""

        def broken() -> Any:
            raise FileNotFoundError("rules.yaml")

        monkeypatch.setattr(ds, "load_signature_spec", broken)
        ds.compile_rules.cache_clear()
        with caplog.at_level(logging.ERROR, logger="whymath.l4.misconception.answer_signature"):
            old = _scan("(x+2)²을 전개하시오.", "x²+4")
            new = _scan(self.Q, "52488")
        assert [c.misconception_id for c in old.candidates] == ["distribution-over-power"]
        assert new.candidates == ()
        assert old.signature_rules_scanned == 0, "독법을 못 돌렸다는 사실이 응답에 드러나야 한다"
        assert (
            "FileNotFoundError" in caplog.text
        ), "침묵 실패 금지 — 예외 타입명이 로그에 있어야 한다"

    def test_matched_signals_carry_no_student_text(self) -> None:
        match = ds.detect_derivative_signature(self.Q, "52488").matches[0]
        assert match.matched_signals == ("sig.power-rule.omit-step.derivative-at",)
        assert "52488" not in repr(match)

    def test_detection_is_deterministic(self) -> None:
        first = ds.detect_derivative_signature(self.Q, "52488")
        assert all(ds.detect_derivative_signature(self.Q, "52488") == first for _ in range(3))


def test_sympy_is_the_only_cas_used_and_no_direct_parser_calls() -> None:
    """R22-03: 이 모듈은 sympify/parse_expr를 직접 부르지 않는다(안전 진입점 경유)."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ds))
    called = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert not ({"sympify", "parse_expr", "parse_latex"} & called)
    assert sympy.Symbol("x") == ds._X
