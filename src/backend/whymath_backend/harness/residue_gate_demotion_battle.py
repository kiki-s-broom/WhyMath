"""잔여 축 교차검증 게이트 강등전 — 실 결함 주입 검출률 측정 (S4-16 · S4-13 게이트 승격 조건).

정본: `docs/architecture/problem_bank_gap_review.md` §3 D7 ⑵(잔여 축은 K≥3 독립 다관점
LLM 교차검증) + `docs/standards/superhuman_verification_standard.md` §3.1-3.2(강등전
방법론 — 결함을 우리가 의도로 주입해 정답지를 100% 확보한 뒤, 그 시험지를 검출기에 태워
검출률·오검출률을 *측정*으로 낸다). `l3/equivalent/defect_seeder.py` +
`harness/defect_detection_eval.py`가 SymPy 결정론 검증기 도메인의 선례라면, 이 모듈은
**검출기 자체가 LLM**(결정론 대체 불가)인 D7 도메인의 판이다.

이 모듈이 재사용하는 것(재구현하지 않는다 — 단일 진실 원천 유지):
  - `residue_cross_verify_eval.py::PilotRecord`/`load_pilot_records`/`select_sample`
    — 코퍼스 로딩·결정론 표본 추출.
  - `l3.finite_probability::parse_finite_model`/`enumerate_model`/`describe_model_ko`
    — 기계 모델 조립(발문은 변조해도 조건식·정답은 원본 그대로 유지 — 결함은 "발문이 더 이상
    기계 모델을 정확히 지시하지 못한다"는 것이지 기계 모델 자체를 건드리는 게 아니다).
  - `l3.cross_verify::CrossVerifier`/`ResidueSubject`/`CrossVerificationResult`
    — K=3 교차검증기와 그 자체 집계 규칙(`aggregate` 필드 — 여기서 재구현하지 않는다).
  - `harness.wilson::wilson_lower_bound`/`wilson_upper_bound` — Wilson 단측 신뢰경계.

이 모듈이 새로 만드는 것: 결함 4종의 **결정론 발문 변조기**(정답지는 변조 함수 자체가 곧
증거 — 인간 라벨 0건) + 결함 주입 셋/무결함 대조군 배터리 조립 + K=3 검증기 배선(주입 가능) +
결함류별·전체 검출률 Wilson 하한 + 대조군 오검출 Wilson 상한 집계 + 리포트/게이트 CLI.

**정직한 불균등 커버리지**(설계 명시 — 균일 N을 위해 억지 변조를 만들지 않는다):
  - `missing_condition`(조건 결측·"서로 구별되는 " 제거) — A·C·D만 적용(코인 그룹 B의 문장은
    애초 구별성 어구를 담지 않는다 — **실측 재검증 결과 25/34**, 최초 설계 메모의 "전 34건"
    주장은 코퍼스 실측과 불일치해 이 구현이 실측값으로 정정한다).
  - `unstated_equiprobability`(등확률 미명시) — A·B만 20/34(C·D는 애초 이 어구를 서술하지
    않음).
  - `ambiguous_wording`(중의성) — A·B·C만 26/34(D는 "이상" 어구 제거가 중의성이 아니라 문제
    자체를 바꿔버리므로 깨끗한 단어 단위 변조가 없어 제외).
  - `multiple_valid_answers`(복수 정답) — C만 6/34("동시에" 제거가 표본공간 모델을 실제로
    바꾸는 것은 공 추출뿐 — 주사위 동시/순차 던지기는 같은 36경우 모델이라 변조가 무의미).
  - `contradictory_condition`(모순 조건 삽입·**홀드아웃**) — A·B·D만 **28/34**(실측:
    주사위 확률 11 + 주사위 경우의 수 8 + 동전 9. 공 추출 C는 코퍼스에 흰 공이 없어 전건
    비적용 0/6 — 존재하지 않는 물체를 가리키는 조건은 변조가 아니라 파손이다).

**홀드아웃 설계**(1차 기록 §후속방향 1 — S3-15 "패턴 패치 축적 단독 재시도 금지"):
v4 관점 프롬프트가 위 4종을 *직접 조준*하므로 그 4종만으로 낸 점수는 승격 근거가 될 수
없다(teaching-to-the-test). 그래서 프롬프트가 조준하지 않은 **⑤ 모순 조건 삽입**을 함께
싣는다 — 튜닝 4종이 전부 *제거·치환*형인 것과 달리 이것은 표본공간을 줄이는 절을 *추가*하는
형태라, "무엇이 빠졌는가"를 묻는 v4 절차와 구조적으로 직교한다. 집계는 `overall_*`(튜닝
4종)과 `holdout_*`를 **분리**한다 — 합치면 홀드아웃 점수가 평균에 묻혀 읽히지 않는다.

**재강등전을 위해 이 판이 추가로 제공하는 것**(1차 미충족 사유의 직접 대응):
  - `--repeat-runs` — 같은 배터리·같은 시드를 반복 실행해 회차 간 **표준편차**를 낸다.
    1차 기록 §부록이 "검출이 결함 유형의 함수라기보다 문항별 우연에 가깝다 — 반복 시행으로
    검출의 일관성 자체를 측정할 가치가 있다"고 요구한 항목.
  - `--clean-n` — 대조군 표본 수를 결함류 표본 수와 **독립**으로 정한다. 1차는 `--sample-n`
    하나가 양쪽을 묶어 대조군 n=2에 그쳤고, 그래서 `--max-defect-upper` 실측 보정이
    수행 불가였다(§해석 3).
  - `--cloud` — `settings.cloud_provider` 좌석(ARCH-55/ARCH-57 팩토리)으로 측정한다.
    §후속방향 2의 "상위 모델 검증기 별도 강등전" 경로. 측정 구성(로컬 모델 id 또는 클라우드
    제공자·모델 핀)은 리포트·JSON·감사 JSONL에 **항상** 기록된다 — 구성이 남지 않은 측정치는
    재현 불가이고, 재현 불가한 측정치는 승격·기각의 근거가 되지 못한다.

사용(라이브 LLM 필요 — hermetic 배선 검증은 fake verifier로 테스트에서 수행):
    python -m whymath_backend.harness.residue_gate_demotion_battle \\
        data/corpus/problem_bank_probability_finite_v0/problems.jsonl \\
        --sample-n 5 --audit-out battle_audit.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from whymath_backend.harness.residue_cross_verify_eval import (
    PilotRecord,
    load_pilot_records,
    select_sample,
)
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l3.cross_verify import (
    MISSING_CONDITION_PERSPECTIVES,
    MULTIPLE_VALID_ANSWERS_PERSPECTIVES,
    PROBABILITY_PERSPECTIVES,
    CrossVerificationResult,
    CrossVerifier,
    Perspective,
    PerspectiveVerdict,
    ResidueSubject,
    _aggregate,
)
from whymath_backend.l3.finite_probability import (
    FiniteProbabilityError,
    describe_model_ko,
    enumerate_model,
    parse_finite_model,
)
from whymath_backend.l3.providers.factory import (
    build_cloud_provider,
    cloud_model_pins,
    cloud_provider_name,
)
from whymath_backend.l3.providers.ollama import FixedModelOllamaProvider

__all__ = [
    "RESIDUE_DEFECT_CLASSES",
    "RESIDUE_HOLDOUT_DEFECT_CLASSES",
    "RESIDUE_TUNED_DEFECT_CLASSES",
    "ResidueDefectClass",
    "MeasurementConfig",
    "SeededResidueItem",
    "ResidueBattery",
    "ClassDetection",
    "ResidueBattleReport",
    "RepeatedResidueBattleReport",
    "build_cloud_measurement_config",
    "build_residue_seeded_set",
    "run_residue_demotion_battle",
    "run_repeated_residue_demotion_battle",
    "render_report",
    "render_repeated_report",
    "report_to_json",
    "repeated_report_to_json",
    "write_audit_jsonl",
    "write_repeated_audit_jsonl",
]

_EXIT_OK = 0
_EXIT_GATE_FAIL = 1

# 결함류 Literal — 튜닝 4종(D7 명세: 발문 조건 결측·등확률 미명시·중의성·복수 정답)에
# **홀드아웃 1종**(`contradictory_condition`)이 더해진다.
ResidueDefectClass = Literal[
    "missing_condition",
    "unstated_equiprobability",
    "ambiguous_wording",
    "multiple_valid_answers",
    "contradictory_condition",
]

# 튜닝 4종 — v4 관점 프롬프트가 *직접 조준*하는 결함류. 이 4종만으로 낸 점수는 승격 근거가
# 될 수 없다(1차 기록 §후속방향 1: "이번 결함 4종에 맞춘 프롬프트 튜닝은 teaching-to-the-test
# 이므로, 재강등전에는 신규 결함류 홀드아웃을 동반해야 한다" — S3-15 교훈).
RESIDUE_TUNED_DEFECT_CLASSES: tuple[ResidueDefectClass, ...] = (
    "missing_condition",
    "unstated_equiprobability",
    "ambiguous_wording",
    "multiple_valid_answers",
)

# 홀드아웃 — 프롬프트가 조준하지 않은 **신규** 결함류. 튜닝 4종과 **절대 합산하지 않는다**
# (합산하면 홀드아웃 점수가 튜닝 점수에 희석돼 teaching-to-the-test를 가려 준다).
RESIDUE_HOLDOUT_DEFECT_CLASSES: tuple[ResidueDefectClass, ...] = ("contradictory_condition",)

RESIDUE_DEFECT_CLASSES: tuple[ResidueDefectClass, ...] = (
    *RESIDUE_TUNED_DEFECT_CLASSES,
    *RESIDUE_HOLDOUT_DEFECT_CLASSES,
)


# ──────────────────────────────────────────────────────────────────────────
# 결정론 발문 변조기 — 각 (원본 텍스트) → (변조 텍스트, 변조 기록) | None(비적용).
# 적용 여부는 *부분 문자열 실재*로 판정한다(그룹 색인 하드코딩 금지 — 코퍼스가 같은 문체로
# 재생성돼 건수가 바뀌어도 이 판정은 그대로 성립한다). 실재하지 않으면 정직하게 None —
# 억지 변조로 정답지를 오염시키지 않는다.
# ──────────────────────────────────────────────────────────────────────────

_MISSING_CONDITION_TARGET = "서로 구별되는 "


def _mutate_missing_condition(text: str) -> tuple[str, str] | None:
    """① 조건 결측 — 구별성 어구 제거. 이 어구가 없는 문장(코인 그룹)은 비적용."""
    if _MISSING_CONDITION_TARGET not in text:
        return None
    mutated = text.replace(_MISSING_CONDITION_TARGET, "", 1)
    return mutated, f"조건 결측: {_MISSING_CONDITION_TARGET!r} 제거(구별 가능 전제 소실)"


_EQUIPROB_DICE = "각 주사위의 여섯 눈이 나올 가능성이 모두 같을 때, "
_EQUIPROB_COIN = "매번 앞면과 뒷면이 나올 가능성이 같을 때, "


def _mutate_unstated_equiprobability(text: str) -> tuple[str, str] | None:
    """② 등확률 미명시 — 명시적 등확률 절 제거. A(주사위)·B(동전)만 이 절을 서술한다."""
    for target in (_EQUIPROB_DICE, _EQUIPROB_COIN):
        if target in text:
            mutated = text.replace(target, "", 1)
            return mutated, f"등확률 미명시: {target!r} 제거(균등분포 가정 미서술)"
    return None


_AMBIG_SUM_RE = re.compile(r"두 눈의 수의 합이 (\d+)일")
_AMBIG_EXACT_COUNT = "앞면이 정확히 "
_AMBIG_ALL_RED = "꺼낸 공이 모두 빨간 공일"


def _mutate_ambiguous_wording(text: str) -> tuple[str, str] | None:
    """③ 중의성 — 그룹별 참조 범위 축소 단어 제거(그룹 D는 깨끗한 변조 없어 의도적 제외).

    - A: "…의 합이 N일" → "…가 N일"("합" 소실 — 두 눈의 합인지 한 눈의 수인지 모호해짐).
    - B: "정확히 " 제거("정확히 M번"→"M번" — 정확히 M번인지 M번 이상인지 모호해짐).
    - C: "모두 " 제거("모두 빨간 공"→"빨간 공" — 전부 빨간지 일부인지 모호해짐).
    - D: 비적용(설계 명시 — "이상" 제거는 중의성이 아니라 문제 자체의 변경).
    """
    match = _AMBIG_SUM_RE.search(text)
    if match is not None:
        mutated = _AMBIG_SUM_RE.sub(r"두 눈의 수가 \1일", text, count=1)
        return mutated, "중의성: '의 합' 소실(두 눈의 수의 합이 N일 → 두 눈의 수가 N일)"
    if _AMBIG_EXACT_COUNT in text:
        mutated = text.replace(_AMBIG_EXACT_COUNT, "앞면이 ", 1)
        return mutated, f"중의성: {_AMBIG_EXACT_COUNT!r} 제거(정확히 M번 vs M번 이상 모호)"
    if _AMBIG_ALL_RED in text:
        mutated = text.replace(_AMBIG_ALL_RED, "꺼낸 공이 빨간 공일", 1)
        return mutated, "중의성: '모두' 제거(전부 빨간지 일부인지 모호)"
    return None


_MULTI_ANSWER_TARGET = "동시에 꺼낼 때"


def _mutate_multiple_valid_answers(text: str) -> tuple[str, str] | None:
    """④ 복수 정답 — 공 추출 그룹(C)에서만 "동시에" 제거가 모델을 실제로 바꾼다.

    주사위(A·D)는 "동시에"를 지워도 두 주사위 36경우 모델이 그대로다(무의미 변조 — 정답지
    오염 방지를 위해 의도적으로 배제). 공 추출은 "동시에"가 "비복원·무순서 추출" 모델을
    지시하는 유일한 단서라, 제거하면 순차/복원 추출이라는 방어 가능한 대안 해석이 생겨
    수치적으로 다른 확률이 나온다 — 진짜 복수 정답 결함.
    """
    if _MULTI_ANSWER_TARGET in text:
        mutated = text.replace(_MULTI_ANSWER_TARGET, "꺼낼 때", 1)
        return mutated, "복수 정답: '동시에' 제거(비복원·무순서 추출 가정 소실 → 대안 해석 발생)"
    return None


# ── 홀드아웃 결함류(⑤ contradictory_condition) ────────────────────────────
# 튜닝 4종이 전부 **제거·치환**형 변조(무엇인가가 발문에서 사라진다)인 것과 달리, 홀드아웃은
# **모순 조건을 덧붙이는** 형태다 — 표본공간을 줄이는 절을 *추가*해 발문이 더 이상 원본 기계
# 모델·정답을 지시하지 못하게 만든다. v4 관점 프롬프트가 전부 "무엇이 빠졌는가"를 묻는 절차라
# 구조적으로 직교하며, 그래서 이 결함류의 점수는 teaching-to-the-test로 설명되지 않는다.
#
# 삽입 위치는 코퍼스 실측 문장 구조를 읽고 정했다 — 세 그룹 모두 **첫 문장이 시행 상황을
# 서술하고 둘째 문장이 답을 묻는다**. 그래서 첫 문장 직후(=답을 묻는 문장 앞)에 한 문장으로
# 끼워 넣으면 어느 그룹에서도 문장이 깨지지 않는다(변조이지 파손이 아니다).
_HOLDOUT_DICE_ANCHOR = "주사위를 동시에 던진다. "
_HOLDOUT_DICE_CLAUSE = "단, 두 눈의 수는 서로 다르다. "
_HOLDOUT_COIN_ANCHOR = "번 던진다. "
_HOLDOUT_COIN_CLAUSE = "단, 첫 번째 시행은 반드시 앞면이다. "
_HOLDOUT_BALL_ANCHOR = "들어 있다. "
_HOLDOUT_BALL_CLAUSE = "단, 꺼낸 공 중 적어도 하나는 흰 공이다. "
_HOLDOUT_BALL_REQUIRED_OBJECT = "흰 공"


def _insert_after(text: str, anchor: str, clause: str) -> str:
    """`anchor` 첫 출현 **직후**에 `clause`를 끼워 넣는다(앵커 실재는 호출자가 이미 확인)."""
    cut = text.index(anchor) + len(anchor)
    return text[:cut] + clause + text[cut:]


def _mutate_contradictory_condition(text: str) -> tuple[str, str] | None:
    """⑤ 모순 조건 삽입(홀드아웃) — 표본공간을 줄이는 절을 추가해 원본 정답을 무효화한다.

    - 주사위(A 확률·D 경우의 수): "두 눈의 수는 서로 다르다" — 대각 6경우(1,1)~(6,6)가
      빠져 36경우 모델이 30경우가 된다. 합이 2·12인 문항은 아예 불가능해지고, 나머지도
      분모·분자가 모두 바뀐다. D(경우의 수)도 같은 이유로 세는 값이 달라지므로 적용한다
      — 확률이냐 경우의 수냐가 아니라 *표본공간이 실제로 바뀌는가*가 판정 기준이다.
    - 동전(B): "첫 번째 시행은 반드시 앞면이다" — 2^n이 2^(n-1)로 줄고 조건부 분포가
      바뀐다("앞면이 정확히 0번" 문항은 불가능해진다).
    - 공 추출(C): **전건 비적용**. 이 코퍼스의 주머니에는 빨간 공·파란 공만 있고 흰 공이
      없어서, "적어도 하나는 흰 공"은 표본공간을 줄이는 조건이 아니라 *문제에 존재하지도
      않는 물체를 가리키는 헛소리*다 — 그런 변조는 결함이 아니라 파손이라 정답지를
      오염시킨다. 주사위 '동시에' 제거를 무의미 변조로 배제한 1차 설계와 같은 원칙이며,
      흰 공을 담은 문항이 코퍼스에 생기면 이 분기가 저절로 살아난다(색인 하드코딩 0).

    실측 커버리지(코퍼스 34건): 주사위 19건(A 11 + D 8) + 동전 9건 + 공 추출 0건 = **28/34**.
    """
    if _HOLDOUT_DICE_ANCHOR in text:
        mutated = _insert_after(text, _HOLDOUT_DICE_ANCHOR, _HOLDOUT_DICE_CLAUSE)
        return mutated, (
            f"모순 조건 삽입(홀드아웃): {_HOLDOUT_DICE_CLAUSE!r} 추가"
            "(대각 6경우 소실 → 36경우 모델이 원본 정답을 더 이상 지시하지 못함)"
        )
    if _HOLDOUT_COIN_ANCHOR in text:
        mutated = _insert_after(text, _HOLDOUT_COIN_ANCHOR, _HOLDOUT_COIN_CLAUSE)
        return mutated, (
            f"모순 조건 삽입(홀드아웃): {_HOLDOUT_COIN_CLAUSE!r} 추가"
            "(첫 시행 고정 → 2^n이 2^(n-1)로 축소, 원본 정답 무효)"
        )
    if _HOLDOUT_BALL_ANCHOR in text and _HOLDOUT_BALL_REQUIRED_OBJECT in text:
        mutated = _insert_after(text, _HOLDOUT_BALL_ANCHOR, _HOLDOUT_BALL_CLAUSE)
        return mutated, (
            f"모순 조건 삽입(홀드아웃): {_HOLDOUT_BALL_CLAUSE!r} 추가"
            "(흰 공 포함 강제 → 표본공간 축소)"
        )
    return None


_MUTATORS: dict[ResidueDefectClass, Callable[[str], tuple[str, str] | None]] = {
    "missing_condition": _mutate_missing_condition,
    "unstated_equiprobability": _mutate_unstated_equiprobability,
    "ambiguous_wording": _mutate_ambiguous_wording,
    "multiple_valid_answers": _mutate_multiple_valid_answers,
    "contradictory_condition": _mutate_contradictory_condition,
}


# ──────────────────────────────────────────────────────────────────────────
# 측정 구성 기록 — *어느 검증기 좌석에서 난 수치인가*.
# CLAUDE.md 「작동 신호 없는 알고리즘 부착 금지」: 구성이 기록되지 않은 측정치는 재현 불가이고,
# 재현 불가한 측정치는 승격·기각 판정의 근거가 될 수 없다(1차 기록이 모델·타임아웃·콜수를
# "실행 조건" 표로 남긴 것과 같은 이유 — 그때는 사람이 손으로 적었다).
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MeasurementConfig:
    """강등전 1회의 검증기 구성 — 리포트·JSON·감사 JSONL에 그대로 실린다."""

    kind: Literal["router_default", "local_fixed", "cloud_seat"]
    local_model: str | None = None
    cloud_provider: str | None = None
    cloud_model_mid: str | None = None
    cloud_model_high: str | None = None

    def describe(self) -> str:
        """사람 가독 1줄 — 리포트 헤더용."""
        if self.kind == "local_fixed":
            return f"로컬 고정 모델 {self.local_model}"
        if self.kind == "cloud_seat":
            return (
                f"클라우드 좌석 {self.cloud_provider} "
                f"(MID={self.cloud_model_mid} · HIGH={self.cloud_model_high})"
            )
        return "라우터 기본 구성(CompositeProvider — 로컬/클라우드 혼합, 모델은 라우터가 선택)"

    def to_json(self) -> dict[str, str | None]:
        return {
            "kind": self.kind,
            "local_model": self.local_model,
            "cloud_provider": self.cloud_provider,
            "cloud_model_mid": self.cloud_model_mid,
            "cloud_model_high": self.cloud_model_high,
        }


def build_cloud_measurement_config() -> MeasurementConfig:
    """현재 `settings.cloud_provider` 좌석의 이름·모델 핀을 읽어 측정 구성을 만든다.

    좌석→핀 매핑을 여기서 다시 적지 않는다 — `factory.cloud_model_pins()`가 단일 근거이고,
    두 곳이 각자 들면 반드시 갈라진다(ARCH-58이 상환한 사고 형태).
    """
    mid, high = cloud_model_pins()
    return MeasurementConfig(
        kind="cloud_seat",
        cloud_provider=cloud_provider_name(),
        cloud_model_mid=mid,
        cloud_model_high=high,
    )


@dataclass(frozen=True, slots=True)
class SeededResidueItem:
    """결함 주입 시험지 1문 — 원본 레코드 + 결함류 + 변조된 발문 + 변조 기록(감사용)."""

    record: PilotRecord
    defect_class: ResidueDefectClass
    mutated_question_text: str
    mutation_note: str


@dataclass(frozen=True, slots=True)
class ResidueBattery:
    """강등전 시험지 배터리 — 결함 주입 셋(결함류 전 적용 가능 건) + 무결함 대조군.

    `coverage`는 *표본 추출 이전* 전체 코퍼스 기준 결함류별 적용 가능 건수 — 정직한 회계
    산출물이다(적용 불가 결함류는 0으로 명시, 침묵 생략이 아니다).
    """

    seeded: tuple[SeededResidueItem, ...]
    clean: tuple[PilotRecord, ...]
    coverage: dict[ResidueDefectClass, int]


def build_residue_seeded_set(records: Sequence[PilotRecord]) -> ResidueBattery:
    """로드된 파일럿 레코드 → 결함 주입 시험지 배터리(순수·결정론·LLM 0·발문만 변조).

    `answer`·`verify.conditions`는 절대 건드리지 않는다 — 기계가 검산한 "의도된" 정답은
    그대로 두고, 발문만 그 의도를 더 이상 정확히 지시하지 못하게 흐린다. 결함류마다 코퍼스
    전건을 스캔해 적용 가능한 레코드만 싣는다(부분 문자열 실재 판정 — 그룹 색인 하드코딩 0).
    """
    seeded: list[SeededResidueItem] = []
    coverage: dict[ResidueDefectClass, int] = {name: 0 for name in RESIDUE_DEFECT_CLASSES}
    for defect_class in RESIDUE_DEFECT_CLASSES:
        mutator = _MUTATORS[defect_class]
        for record in records:
            result = mutator(record.question_text)
            if result is None:
                continue
            mutated_text, note = result
            coverage[defect_class] += 1
            seeded.append(
                SeededResidueItem(
                    record=record,
                    defect_class=defect_class,
                    mutated_question_text=mutated_text,
                    mutation_note=note,
                )
            )
    return ResidueBattery(seeded=tuple(seeded), clean=tuple(records), coverage=coverage)


def _select_sample_items(
    items: Sequence[SeededResidueItem], *, sample_n: int, seed: str
) -> list[SeededResidueItem]:
    """결정론 표본 추출 — `residue_cross_verify_eval.select_sample`과 동형 해시 정렬 규칙.

    (defect_class, slug) 복합 키로 해시해, 같은 slug가 여러 결함류에 걸쳐 나와도 결함류별
    독립 표본이 된다.
    """
    if sample_n <= 0:
        return []
    ordered = sorted(
        items,
        key=lambda item: hashlib.sha256(
            f"{seed}:{item.defect_class}:{item.record.slug}".encode()
        ).hexdigest(),
    )
    return list(ordered[:sample_n])


def _build_subject(
    record: PilotRecord, *, question_text: str, authored_by: str
) -> ResidueSubject | str:
    """검증 대상 조립 — 기계 모델은 *원본* conditions에서(변조는 question_text에만 반영).

    모델 조립 실패는 사유 문자열(호출자가 측정 실패로 집계) — 파일럿 코퍼스는 이미 S4-13에서
    기계 축을 통과했으므로 실전에서는 발생하지 않을 것으로 예상되나, 방어적으로 처리한다.
    """
    try:
        model = parse_finite_model(record.conditions)
        result = enumerate_model(model)
    except FiniteProbabilityError as exc:
        return f"{record.slug}: 형식 모델 조립 실패({type(exc).__name__}) {exc}"
    return ResidueSubject(
        problem_id=record.slug,
        question_text=question_text,
        answer=record.answer,
        answer_explanation=record.answer_explanation,
        machine_model_ko=describe_model_ko(model, result),
        machine_total=result.total,
        machine_favorable=result.favorable,
        authored_by=authored_by,
    )


@dataclass(frozen=True, slots=True)
class ClassDetection:
    """결함류 1개의 검출 집계 — 표본·판정·검출·판정불가 + Wilson 하한."""

    defect_class: ResidueDefectClass
    sampled: int
    resolved: int
    detected: int
    unresolved: int
    model_failures: tuple[str, ...] = ()

    def detection_lower_bound(self, confidence: float = 0.95) -> float | None:
        """검출률 Wilson 단측 하한 — 판정 가능 표본 0이면 None(NO_DATA, 0.0으로 위장 금지)."""
        if self.resolved == 0:
            return None
        return wilson_lower_bound(self.detected, self.resolved, confidence)


@dataclass(frozen=True, slots=True)
class _AuditRow:
    """감사 JSONL 1행 — 문항·역할(seeded/clean)·결함류·변조기록·검증 결과."""

    problem_id: str
    role: Literal["seeded", "clean"]
    defect_class: str | None
    mutation_note: str
    aggregate: str
    holdout: bool = False


@dataclass(frozen=True, slots=True)
class ResidueBattleReport:
    """강등전 결과 — 결함류별 검출 + 전체 검출 Wilson 하한 + 대조군 오검출 Wilson 상한.

    `coverage`(배터리에서 물려받음)는 표본 추출 *이전* 전체 코퍼스 기준 적용 가능 건수이고,
    `per_class`의 `sampled`는 실제로 검증기에 태운 건수(`--sample-n`으로 제한된 실측 표본)다
    — 이 둘을 섞지 않는다(적용 가능 모집단 vs 실측 표본은 다른 숫자).

    `overall_*`는 **튜닝 4종만** 집계하고 홀드아웃은 `holdout_*`로 분리한다. 합치면 홀드아웃
    점수가 튜닝 점수에 희석돼 teaching-to-the-test 여부를 읽을 수 없게 된다.
    """

    per_class: dict[ResidueDefectClass, ClassDetection]
    coverage: dict[ResidueDefectClass, int]
    overall_detected: int
    overall_resolved: int
    overall_unresolved: int
    clean_false_alarms: int
    clean_resolved: int
    clean_unresolved: int
    clean_sampled: int
    audit_rows: tuple[_AuditRow, ...] = field(default_factory=tuple)
    holdout_detected: int = 0
    holdout_resolved: int = 0
    holdout_unresolved: int = 0
    measurement_config: MeasurementConfig | None = None

    def overall_detection_lower_bound(self, confidence: float = 0.95) -> float | None:
        if self.overall_resolved == 0:
            return None
        return wilson_lower_bound(self.overall_detected, self.overall_resolved, confidence)

    def holdout_detection_lower_bound(self, confidence: float = 0.95) -> float | None:
        """홀드아웃 검출률 Wilson 단측 하한 — 판정 표본 0이면 None(0.0으로 위장 금지)."""
        if self.holdout_resolved == 0:
            return None
        return wilson_lower_bound(self.holdout_detected, self.holdout_resolved, confidence)

    def false_alarm_upper_bound(self, confidence: float = 0.95) -> float | None:
        if self.clean_resolved == 0:
            return None
        return wilson_upper_bound(self.clean_false_alarms, self.clean_resolved, confidence)


def _resolve_verifiers(
    verifier: CrossVerifier | Mapping[ResidueDefectClass, CrossVerifier],
    default_verifier: CrossVerifier | None,
) -> tuple[Mapping[ResidueDefectClass, CrossVerifier], CrossVerifier]:
    """(결함류별 검증기, 기본 검증기)로 정규화 — 매핑에 없는 결함류·대조군이 기본을 쓴다.

    매핑이 비어 있고 `default_verifier`도 없으면 **조용히 넘어가지 않고 raise**한다
    (CLAUDE.md 「침묵 실패 금지」 — 검증기 0개로 돈 강등전은 "검출 0건"이 아니라 측정 미실시다).
    """
    if not isinstance(verifier, Mapping):
        return {name: verifier for name in RESIDUE_DEFECT_CLASSES}, verifier
    fallback = default_verifier
    if fallback is None:
        for candidate in verifier.values():
            fallback = candidate
            break
    if fallback is None:
        raise ValueError(
            "verifier 매핑이 비었고 default_verifier도 없다 — 검증기 없이는 강등전을 "
            "실행할 수 없다(측정 미실시를 '검출 0건'으로 위장하지 않는다)."
        )
    return verifier, fallback


def run_residue_demotion_battle(
    battery: ResidueBattery,
    *,
    verifier: CrossVerifier | Mapping[ResidueDefectClass, CrossVerifier],
    default_verifier: CrossVerifier | None = None,
    sample_n: int = 5,
    clean_n: int | None = None,
    seed: str = "S4-16",
    authored_by: str | None = None,
    measurement_config: MeasurementConfig | None = None,
) -> ResidueBattleReport:
    """배터리를 K=3 검증기에 태워 결함류별·전체 검출 + 대조군 오검출을 집계(순수 조합).

    `verifier`가 Mapping이면 **결함류별로 서로 다른 검증기**(관점 세트)를 쓴다 — 매핑에 없는
    결함류와 무결함 대조군은 `default_verifier`(없으면 매핑의 첫 값)를 쓴다. 단일 검증기를
    주면 종전처럼 전 결함류·대조군이 그것을 쓴다(기존 호출부 회귀 0).

    `clean_n`은 **대조군 표본 수를 결함류 표본 수와 독립으로** 정한다(None이면 `sample_n`과
    같다 — 기존 동작 보존). 1차 강등전이 `--max-defect-upper` 실측 보정에 실패한 직접 원인이
    대조군 판정 표본 n=2였고, 그것을 n≥20으로 올리려면 종전 구조에서는 결함류 4종도 함께
    20건이 돼 비용이 4배 붙었다 — 이 인자가 그 결합을 끊는다.

    "검출"(seeded) = `verifier.verify(subject).aggregate == "defect"`.
    "오검출"(clean) = 무결함 대상인데도 `aggregate == "defect"`.
    "판정불가"(unresolved) = `aggregate == "unclear"` — 측정 실패로 분리 집계(0건 검출로
    위장하지 않는다). K=3 집계 규칙 자체는 `l3.cross_verify`가 이미 내린 결과를 그대로
    쓴다(여기서 재구현하지 않는다).
    """
    class_verifiers, fallback_verifier = _resolve_verifiers(verifier, default_verifier)
    resolved_clean_n = sample_n if clean_n is None else clean_n

    by_class: dict[ResidueDefectClass, list[SeededResidueItem]] = {
        name: [] for name in RESIDUE_DEFECT_CLASSES
    }
    for item in battery.seeded:
        by_class[item.defect_class].append(item)

    per_class: dict[ResidueDefectClass, ClassDetection] = {}
    audit_rows: list[_AuditRow] = []
    overall_detected = overall_resolved = overall_unresolved = 0
    holdout_detected = holdout_resolved = holdout_unresolved = 0

    for defect_class in RESIDUE_DEFECT_CLASSES:
        is_holdout = defect_class in RESIDUE_HOLDOUT_DEFECT_CLASSES
        sample = _select_sample_items(by_class[defect_class], sample_n=sample_n, seed=seed)
        class_verifier = class_verifiers.get(defect_class, fallback_verifier)
        detected = unresolved = 0
        model_failures: list[str] = []
        for item in sample:
            subject = _build_subject(
                item.record,
                question_text=item.mutated_question_text,
                authored_by=authored_by or item.record.authored_by,
            )
            if isinstance(subject, str):
                model_failures.append(subject)
                continue
            result = class_verifier.verify(subject)
            audit_rows.append(
                _AuditRow(
                    problem_id=item.record.slug,
                    role="seeded",
                    defect_class=defect_class,
                    mutation_note=item.mutation_note,
                    aggregate=result.aggregate,
                    holdout=is_holdout,
                )
            )
            if result.aggregate == "unclear":
                unresolved += 1
            elif result.aggregate == "defect":
                detected += 1
        resolved = len(sample) - unresolved - len(model_failures)
        per_class[defect_class] = ClassDetection(
            defect_class=defect_class,
            sampled=len(sample),
            resolved=resolved,
            detected=detected,
            unresolved=unresolved,
            model_failures=tuple(model_failures),
        )
        # 홀드아웃은 전체 집계에 **더하지 않는다** — 섞으면 teaching-to-the-test가 가려진다.
        if is_holdout:
            holdout_detected += detected
            holdout_resolved += resolved
            holdout_unresolved += unresolved
        else:
            overall_detected += detected
            overall_resolved += resolved
            overall_unresolved += unresolved

    clean_sample = select_sample(list(battery.clean), sample_n=resolved_clean_n, seed=seed)
    false_alarms = clean_unresolved = 0
    clean_model_failures: list[str] = []
    for record in clean_sample:
        subject = _build_subject(
            record,
            question_text=record.question_text,
            authored_by=authored_by or record.authored_by,
        )
        if isinstance(subject, str):
            clean_model_failures.append(subject)
            continue
        result = fallback_verifier.verify(subject)
        audit_rows.append(
            _AuditRow(
                problem_id=record.slug,
                role="clean",
                defect_class=None,
                mutation_note="",
                aggregate=result.aggregate,
            )
        )
        if result.aggregate == "unclear":
            clean_unresolved += 1
        elif result.aggregate == "defect":
            false_alarms += 1
    clean_resolved = len(clean_sample) - clean_unresolved - len(clean_model_failures)

    return ResidueBattleReport(
        per_class=per_class,
        coverage=dict(battery.coverage),
        overall_detected=overall_detected,
        overall_resolved=overall_resolved,
        overall_unresolved=overall_unresolved,
        clean_false_alarms=false_alarms,
        clean_resolved=clean_resolved,
        clean_unresolved=clean_unresolved,
        clean_sampled=len(clean_sample),
        audit_rows=tuple(audit_rows),
        holdout_detected=holdout_detected,
        holdout_resolved=holdout_resolved,
        holdout_unresolved=holdout_unresolved,
        measurement_config=measurement_config,
    )


@dataclass(frozen=True, slots=True)
class RepeatedResidueBattleReport:
    """반복 실행된 강등전 결과 — 평균/최악/표준편차/판정불가율을 함께 제공한다.

    **왜 반복하는가**: 1차 기록 §부록이 "같은 변조도 문항에 따라 잡히고 안 잡힌다 — 검출이
    결함 유형의 함수라기보다 문항별 우연에 가깝다"고 관측하고, "재강등전 설계 시 같은 변조의
    반복 시행으로 검출의 **일관성 자체**를 측정할 가치가 있다"고 요구했다. 단일 실행의
    점추정은 그 일관성을 말하지 못한다.
    """

    reports: tuple[ResidueBattleReport, ...]
    confidence: float
    corpus_size: int
    sample_n: int
    repeat_runs: int
    seed: str
    clean_n: int | None = None
    measurement_config: MeasurementConfig | None = None

    @property
    def per_class_reports(self) -> dict[ResidueDefectClass, tuple[ClassDetection, ...]]:
        """결함류별로 반복 실행의 ClassDetection을 모은다."""
        result: dict[ResidueDefectClass, list[ClassDetection]] = {
            name: [] for name in RESIDUE_DEFECT_CLASSES
        }
        for report in self.reports:
            for name in RESIDUE_DEFECT_CLASSES:
                detection = report.per_class.get(name)
                if detection is not None:
                    result[name].append(detection)
        return {name: tuple(items) for name, items in result.items()}


def run_repeated_residue_demotion_battle(
    battery: ResidueBattery,
    *,
    verifier: CrossVerifier | Mapping[ResidueDefectClass, CrossVerifier],
    default_verifier: CrossVerifier | None = None,
    sample_n: int = 5,
    clean_n: int | None = None,
    seed: str = "S4-16",
    authored_by: str | None = None,
    repeat_runs: int = 1,
    corpus_size: int = 0,
    confidence: float = 0.95,
    measurement_config: MeasurementConfig | None = None,
) -> RepeatedResidueBattleReport:
    """동일 배터리를 동일 조건으로 여러 번 실행해 평균/최악/변동성을 산출한다.

    표본 추출은 시드 고정이라 매 회차가 **같은 문항 집합**을 본다 — 그래서 회차 간 차이는
    표본 차이가 아니라 **검증기 자신의 비결정성**이다(그것이 측정하려는 것이다).
    """
    if repeat_runs < 1:
        raise ValueError(f"repeat_runs는 1 이상이어야 한다(받은 값={repeat_runs}).")
    reports = tuple(
        run_residue_demotion_battle(
            battery,
            verifier=verifier,
            default_verifier=default_verifier,
            sample_n=sample_n,
            clean_n=clean_n,
            seed=seed,
            authored_by=authored_by,
            measurement_config=measurement_config,
        )
        for _ in range(repeat_runs)
    )
    return RepeatedResidueBattleReport(
        reports=reports,
        confidence=confidence,
        corpus_size=corpus_size,
        sample_n=sample_n,
        repeat_runs=repeat_runs,
        seed=seed,
        clean_n=clean_n,
        measurement_config=measurement_config,
    )


def write_audit_jsonl(path: Path, report: ResidueBattleReport) -> int:
    """감사 JSONL — 문항별 판정 행 + as-found 병기 요약(§4.5 합격 로트 무결성 동형).

    PR #854 "측정 도구는 실패 경로부터 설계" — 상세 레코드와 요약 레코드는 다른
    스키마이므로 ``record_type`` 태그로 명시적으로 구분한다. 파서가 시간 필터 없이
    tail만 읽었을 때 as-found 라인을 오판정하지 않도록 한다.
    """
    lines: list[str] = []
    if report.audit_rows and report.measurement_config is not None:
        # 측정 구성 헤더 — 어느 좌석에서 난 판정인지 감사 원자료 자체에 박는다.
        lines.append(
            json.dumps(
                {"record_type": "measurement_config", **report.measurement_config.to_json()},
                ensure_ascii=False,
            )
        )
    lines.extend(_verdict_lines(report))
    if report.audit_rows:
        lines.append(json.dumps(_as_found_payload(report), ensure_ascii=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    return len(lines)


def _verdict_lines(report: ResidueBattleReport, *, run: int | None = None) -> list[str]:
    """판정 행 직렬화 — 홀드아웃 행은 `holdout: true`로 표시해 하류가 섞어 세지 못하게 한다."""
    lines: list[str] = []
    for row in report.audit_rows:
        payload: dict[str, object] = {"record_type": "verdict"}
        if run is not None:
            payload["run"] = run
        payload.update(
            {
                "problem_id": row.problem_id,
                "role": row.role,
                "defect_class": row.defect_class,
                "holdout": row.holdout,
                "mutation_note": row.mutation_note,
                "aggregate": row.aggregate,
            }
        )
        lines.append(json.dumps(payload, ensure_ascii=False))
    return lines


def _as_found_payload(report: ResidueBattleReport, *, run: int | None = None) -> dict[str, object]:
    """as-found 요약 — 튜닝 집계와 홀드아웃 집계를 **다른 필드**로 낸다(합산 금지)."""
    payload: dict[str, object] = {"record_type": "as_found_summary"}
    if run is not None:
        payload["run"] = run
    payload.update(
        {
            "as_found_overall_detected": report.overall_detected,
            "as_found_overall_resolved": report.overall_resolved,
            "as_found_holdout_detected": report.holdout_detected,
            "as_found_holdout_resolved": report.holdout_resolved,
            "as_found_clean_false_alarms": report.clean_false_alarms,
            "as_found_clean_resolved": report.clean_resolved,
        }
    )
    return payload


def write_repeated_audit_jsonl(path: Path, repeated: RepeatedResidueBattleReport) -> int:
    """반복 실행 감사 JSONL — run별 판정 행 + run별 as-found 요약(+ 측정 구성 헤더 1행)."""
    lines: list[str] = []
    has_rows = any(report.audit_rows for report in repeated.reports)
    if has_rows and repeated.measurement_config is not None:
        lines.append(
            json.dumps(
                {
                    "record_type": "measurement_config",
                    "repeat_runs": repeated.repeat_runs,
                    **repeated.measurement_config.to_json(),
                },
                ensure_ascii=False,
            )
        )
    for run_index, report in enumerate(repeated.reports, start=1):
        lines.extend(_verdict_lines(report, run=run_index))
        if report.audit_rows:
            lines.append(json.dumps(_as_found_payload(report, run=run_index), ensure_ascii=False))
    if not lines:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _mean(values: Sequence[float | int | None]) -> float | None:
    """None(측정 실패)을 제외한 값의 산술평균 — 값이 하나도 없으면 None."""
    nums = [float(v) for v in values if v is not None]
    return statistics.mean(nums) if nums else None


def _stdev(values: Sequence[float | int | None]) -> float | None:
    """None을 제외한 값의 표본표준편차 — 2개 미만이면 None(1회 실행에 변동성은 없다)."""
    nums = [float(v) for v in values if v is not None]
    return statistics.stdev(nums) if len(nums) >= 2 else None


def _min_value(values: Sequence[float | int | None]) -> float | None:
    """None을 제외한 값의 최솟값 — 검출 하한의 *최악 회차*를 읽는 데 쓴다."""
    nums = [float(v) for v in values if v is not None]
    return min(nums) if nums else None


def _max_value(values: Sequence[float | int | None]) -> float | None:
    """None을 제외한 값의 최댓값 — 오검출 상한의 *최악 회차*를 읽는 데 쓴다."""
    nums = [float(v) for v in values if v is not None]
    return max(nums) if nums else None


def _measurement_config_lines(config: MeasurementConfig | None) -> list[str]:
    """측정 구성 블록 — 구성이 없으면 *없다고 말한다*(침묵하면 기본 구성으로 오독된다)."""
    if config is None:
        return ["[측정 구성] 기록 없음 — 이 수치는 어느 좌석에서 났는지 알 수 없다(재현 불가)."]
    return [f"[측정 구성] {config.describe()}"]


def _class_detection_line(
    report: ResidueBattleReport, name: ResidueDefectClass, confidence: float
) -> str:
    """결함류 1행 렌더 — 튜닝 절과 홀드아웃 절이 같은 형식을 쓰되 *다른 블록*에 놓인다."""
    detection = report.per_class.get(name)
    if detection is None or detection.sampled == 0:
        return f"  {name:26s} 표본 없음(N=0)"
    lower = detection.detection_lower_bound(confidence)
    return (
        f"  {name:26s} 표본 {detection.sampled}건 판정 {detection.resolved}건 "
        f"검출 {detection.detected}건  하한 {_fmt(lower)}  판정불가 {detection.unresolved}건"
    )


def _holdout_lines(report: ResidueBattleReport, *, confidence: float, pct: int) -> list[str]:
    """홀드아웃 블록 — 튜닝 집계와 **한 줄에 섞지 않는다**.

    홀드아웃 점수가 튜닝 점수보다 현저히 낮으면 그 차이가 곧 teaching-to-the-test의 크기다.
    합산해 버리면 그 차이가 평균에 묻혀 읽히지 않는다(S3-15 교훈의 집행 지점).
    """
    lines = [
        "[홀드아웃 결함류 — 프롬프트가 조준하지 않은 신규 결함류(위 전체 집계에 미포함)]",
    ]
    for name in RESIDUE_HOLDOUT_DEFECT_CLASSES:
        lines.append(_class_detection_line(report, name, confidence))
    holdout_lower = report.holdout_detection_lower_bound(confidence)
    lines.append(
        f"  홀드아웃 검출률: {report.holdout_detected}/{report.holdout_resolved} "
        f"({pct}% 하한 {_fmt(holdout_lower)})  판정불가 {report.holdout_unresolved}건"
    )
    return lines


def render_report(
    report: ResidueBattleReport, *, confidence: float = 0.95, corpus_size: int
) -> str:
    """사람 가독 리포트 — 커버리지(모집단)·검출(표본)·전체·대조군·보정 제안을 분리해 보여준다."""
    pct = round(confidence * 100)
    lines = [
        "=" * 68,
        "잔여 축 교차검증 게이트 강등전 — 결함 주입 검출률 측정 (S4-16 · D7)",
        "=" * 68,
    ]
    lines.extend(_measurement_config_lines(report.measurement_config))
    lines.append(f"[커버리지 — 코퍼스 전체({corpus_size}건) 기준 결함류별 적용 가능 건수]")
    for name in RESIDUE_DEFECT_CLASSES:
        n = report.coverage.get(name, 0)
        tag = " (홀드아웃)" if name in RESIDUE_HOLDOUT_DEFECT_CLASSES else ""
        if n == 0:
            lines.append(f"  {name:26s} 표본 없음(N=0/{corpus_size}) — 이 결함류는 적용 불가{tag}")
        else:
            lines.append(f"  {name:26s} {n}/{corpus_size}건 적용 가능{tag}")
    lines.append(f"[튜닝 결함류별 검출 — 실 표본({pct}% Wilson 하한)]")
    for name in RESIDUE_TUNED_DEFECT_CLASSES:
        lines.append(_class_detection_line(report, name, confidence))
    overall = report.overall_detection_lower_bound(confidence)
    fau = report.false_alarm_upper_bound(confidence)
    lines.append("[전체 — 튜닝 4종만 합산(홀드아웃 제외)]")
    lines.append(
        f"  결함 검출률   : {report.overall_detected}/{report.overall_resolved} "
        f"({pct}% 하한 {_fmt(overall)})  판정불가 {report.overall_unresolved}건"
    )
    lines.append(
        f"  무결함 오검출 : {report.clean_false_alarms}/{report.clean_resolved} "
        f"(표본 {report.clean_sampled}건 · {pct}% 상한 {_fmt(fau)})  "
        f"판정불가 {report.clean_unresolved}건"
    )
    lines.extend(_holdout_lines(report, confidence=confidence, pct=pct))
    lines.append("[보정 제안 — residue_cross_verify_eval.py --max-defect-upper]")
    if fau is not None:
        lines.append(
            f"  측정된 오검출 Wilson 상한이 {fau:.4f}이므로 --max-defect-upper는 최소 "
            f"{fau:.4f} 이상이어야 노이즈와 실결함을 구분 가능(현재 기본값 0.05는 이 실측 "
            "이전의 근거 없는 초기값 — 실측치가 0.05를 넘으면 그 기본값 자체가 상시 FAIL을 "
            "낳는 잘못 캘리브레이션된 임계다)."
        )
    else:
        lines.append("  대조군 판정 표본이 없어(clean_resolved=0) 보정 제안 불가 — 측정 부족.")
    lines.append("=" * 68)
    return "\n".join(lines)


def report_to_json(report: ResidueBattleReport, *, confidence: float = 0.95) -> dict[str, object]:
    """리포트 → JSON 직렬화 가능 dict(CLI --audit-out과 별개로 리포트 자체를 기계 판독하려는
    소비처를 위한 산출 — 필드는 render_report와 1:1 대응)."""
    return {
        "measurement_config": (
            report.measurement_config.to_json() if report.measurement_config is not None else None
        ),
        "coverage": dict(report.coverage),
        "holdout_classes": list(RESIDUE_HOLDOUT_DEFECT_CLASSES),
        "per_class": {
            name: {
                "sampled": d.sampled,
                "resolved": d.resolved,
                "detected": d.detected,
                "unresolved": d.unresolved,
                "detection_lower_bound": d.detection_lower_bound(confidence),
                "holdout": name in RESIDUE_HOLDOUT_DEFECT_CLASSES,
            }
            for name, d in report.per_class.items()
        },
        "overall": {
            "detected": report.overall_detected,
            "resolved": report.overall_resolved,
            "unresolved": report.overall_unresolved,
            "detection_lower_bound": report.overall_detection_lower_bound(confidence),
        },
        # 홀드아웃은 `overall`과 **다른 키**로 낸다 — 소비처가 실수로 합산하려면 명시적으로
        # 두 키를 더해야 하고, 그 순간 자기가 무엇을 하는지 알게 된다.
        "holdout": {
            "detected": report.holdout_detected,
            "resolved": report.holdout_resolved,
            "unresolved": report.holdout_unresolved,
            "detection_lower_bound": report.holdout_detection_lower_bound(confidence),
        },
        "clean_control": {
            "sampled": report.clean_sampled,
            "resolved": report.clean_resolved,
            "false_alarms": report.clean_false_alarms,
            "unresolved": report.clean_unresolved,
            "false_alarm_upper_bound": report.false_alarm_upper_bound(confidence),
        },
    }


def _detection_rate(detected: int, resolved: int) -> float | None:
    """판정 표본 0이면 None — 0/0을 0.0으로 접으면 측정 실패가 '완전 실명'으로 위장된다."""
    return detected / resolved if resolved > 0 else None


def _repeated_series(
    repeated: RepeatedResidueBattleReport, confidence: float
) -> dict[str, list[float | None]]:
    """반복 회차별 원시 계열 — 렌더러와 직렬화기가 **같은 계열**을 읽게 한다(이중 정의 금지)."""
    reports = repeated.reports
    tuned_sampled = [
        sum(r.per_class[n].sampled for n in RESIDUE_TUNED_DEFECT_CLASSES if n in r.per_class)
        for r in reports
    ]
    holdout_sampled = [
        sum(r.per_class[n].sampled for n in RESIDUE_HOLDOUT_DEFECT_CLASSES if n in r.per_class)
        for r in reports
    ]
    return {
        "overall_rate": [_detection_rate(r.overall_detected, r.overall_resolved) for r in reports],
        "overall_lower": [r.overall_detection_lower_bound(confidence) for r in reports],
        "overall_abstention": [
            (r.overall_unresolved / n if n > 0 else None)
            for r, n in zip(reports, tuned_sampled, strict=True)
        ],
        "holdout_rate": [_detection_rate(r.holdout_detected, r.holdout_resolved) for r in reports],
        "holdout_lower": [r.holdout_detection_lower_bound(confidence) for r in reports],
        "holdout_abstention": [
            (r.holdout_unresolved / n if n > 0 else None)
            for r, n in zip(reports, holdout_sampled, strict=True)
        ],
        "false_alarm_rate": [
            _detection_rate(r.clean_false_alarms, r.clean_resolved) for r in reports
        ],
        "false_alarm_upper": [r.false_alarm_upper_bound(confidence) for r in reports],
        "clean_abstention": [
            (r.clean_unresolved / r.clean_sampled if r.clean_sampled > 0 else None) for r in reports
        ],
    }


def _repeated_class_series(
    detections: Sequence[ClassDetection], confidence: float
) -> dict[str, list[float | None]]:
    """결함류 1종의 회차별 계열(검출률·하한·판정불가율)."""
    return {
        "rate": [_detection_rate(d.detected, d.resolved) for d in detections],
        "lower": [d.detection_lower_bound(confidence) for d in detections],
        "abstention": [(d.unresolved / d.sampled if d.sampled > 0 else None) for d in detections],
    }


def _repeated_class_line(name: ResidueDefectClass, series: dict[str, list[float | None]]) -> str:
    return (
        f"  {name:26s} 검출률 평균 {_fmt(_mean(series['rate']))} "
        f"하한 평균 {_fmt(_mean(series['lower']))} "
        f"최악 {_fmt(_min_value(series['lower']))} "
        f"표준편차 {_fmt(_stdev(series['lower']))} "
        f"판정불가율 {_fmt(_mean(series['abstention']))}"
    )


def render_repeated_report(
    repeated: RepeatedResidueBattleReport, *, confidence: float | None = None
) -> str:
    """반복 실행 리포트 — 평균/최악/표준편차/판정불가율을 함께 보여준다.

    **표준편차가 이 리포트의 핵심 산출물**이다. 1차 기록이 관측한 "검출이 문항별 우연에
    가깝다"가 사실이라면 회차 간 편차가 크게 나타나고, 그 경우 평균 점추정만으로 승격을
    논하는 것은 성립하지 않는다.
    """
    confidence = repeated.confidence if confidence is None else confidence
    pct = round(confidence * 100)
    reports = repeated.reports
    per_class_reports = repeated.per_class_reports
    series = _repeated_series(repeated, confidence)
    clean_n = repeated.sample_n if repeated.clean_n is None else repeated.clean_n

    lines = [
        "=" * 68,
        "잔여 축 교차검증 게이트 강등전 — 결함 주입 검출률 측정 (S4-16 · D7 · 반복 실행)",
        "=" * 68,
    ]
    lines.extend(_measurement_config_lines(repeated.measurement_config))
    lines.append(
        f"[실행 조건] 결함류 표본 {repeated.sample_n}건 · 대조군 표본 {clean_n}건 · "
        f"반복 {repeated.repeat_runs}회 · 시드 {repeated.seed}"
    )
    lines.append(f"[커버리지 — 코퍼스 전체({repeated.corpus_size}건) 기준 결함류별 적용 가능 건수]")
    coverage = reports[0].coverage if reports else {}
    for name in RESIDUE_DEFECT_CLASSES:
        n = coverage.get(name, 0)
        tag = " (홀드아웃)" if name in RESIDUE_HOLDOUT_DEFECT_CLASSES else ""
        if n == 0:
            lines.append(
                f"  {name:26s} 표본 없음(N=0/{repeated.corpus_size}) — "
                f"이 결함류는 적용 불가{tag}"
            )
        else:
            lines.append(f"  {name:26s} {n}/{repeated.corpus_size}건 적용 가능{tag}")

    lines.append(f"[튜닝 결함류별 검출 — 반복 평균({pct}% Wilson 하한)]")
    for name in RESIDUE_TUNED_DEFECT_CLASSES:
        detections = per_class_reports.get(name, ())
        if not detections:
            lines.append(f"  {name:26s} 표본 없음(N=0)")
            continue
        lines.append(_repeated_class_line(name, _repeated_class_series(detections, confidence)))

    lines.append("[전체 — 튜닝 4종만 합산(홀드아웃 제외)]")
    lines.append(
        f"  결함 검출률   : 평균 {_fmt(_mean(series['overall_rate']))} "
        f"({pct}% 하한 평균 {_fmt(_mean(series['overall_lower']))} "
        f"최악 {_fmt(_min_value(series['overall_lower']))} "
        f"표준편차 {_fmt(_stdev(series['overall_lower']))}) "
        f"판정불가율 {_fmt(_mean(series['overall_abstention']))}"
    )
    lines.append(
        f"  무결함 오검출 : 평균 {_fmt(_mean(series['false_alarm_rate']))} "
        f"({pct}% 상한 평균 {_fmt(_mean(series['false_alarm_upper']))} "
        f"최악 {_fmt(_max_value(series['false_alarm_upper']))} "
        f"표준편차 {_fmt(_stdev(series['false_alarm_upper']))}) "
        f"판정불가율 {_fmt(_mean(series['clean_abstention']))}"
    )

    lines.append("[홀드아웃 결함류 — 프롬프트가 조준하지 않은 신규 결함류(위 집계에 미포함)]")
    for name in RESIDUE_HOLDOUT_DEFECT_CLASSES:
        detections = per_class_reports.get(name, ())
        if not detections:
            lines.append(f"  {name:26s} 표본 없음(N=0)")
            continue
        lines.append(_repeated_class_line(name, _repeated_class_series(detections, confidence)))
    lines.append(
        f"  홀드아웃 검출률: 평균 {_fmt(_mean(series['holdout_rate']))} "
        f"({pct}% 하한 평균 {_fmt(_mean(series['holdout_lower']))} "
        f"최악 {_fmt(_min_value(series['holdout_lower']))} "
        f"표준편차 {_fmt(_stdev(series['holdout_lower']))}) "
        f"판정불가율 {_fmt(_mean(series['holdout_abstention']))}"
    )

    lines.append("[보정 제안 — residue_cross_verify_eval.py --max-defect-upper]")
    worst_fau = _max_value(series["false_alarm_upper"])
    if worst_fau is not None:
        lines.append(
            f"  측정된 **최악 회차** 오검출 Wilson 상한이 {worst_fau:.4f}이므로 "
            f"--max-defect-upper는 최소 {worst_fau:.4f} 이상이어야 노이즈와 실결함을 "
            "구분 가능(평균이 아니라 최악을 쓰는 것은 임계가 상시 FAIL을 내지 않게 하려는 것)."
        )
    else:
        lines.append("  대조군 판정 표본이 없어(clean_resolved=0) 보정 제안 불가 — 측정 부족.")
    lines.append("=" * 68)
    return "\n".join(lines)


def repeated_report_to_json(
    repeated: RepeatedResidueBattleReport, *, confidence: float | None = None
) -> dict[str, Any]:
    """반복 리포트 → JSON — 평균/최악/표준편차/판정불가율을 기계 판독 가능하게 낸다."""
    confidence = repeated.confidence if confidence is None else confidence
    reports = repeated.reports
    per_class_reports = repeated.per_class_reports
    series = _repeated_series(repeated, confidence)

    per_class_stats: dict[str, object] = {}
    for name in RESIDUE_DEFECT_CLASSES:
        detections = per_class_reports.get(name, ())
        if not detections:
            continue
        class_series = _repeated_class_series(detections, confidence)
        per_class_stats[name] = {
            "runs": len(detections),
            "holdout": name in RESIDUE_HOLDOUT_DEFECT_CLASSES,
            "detection_rate_mean": _mean(class_series["rate"]),
            "detection_lower_bound_mean": _mean(class_series["lower"]),
            "detection_lower_bound_worst": _min_value(class_series["lower"]),
            "detection_lower_bound_stdev": _stdev(class_series["lower"]),
            "abstention_rate_mean": _mean(class_series["abstention"]),
        }

    return {
        "measurement_config": (
            repeated.measurement_config.to_json()
            if repeated.measurement_config is not None
            else None
        ),
        "repeat_runs": repeated.repeat_runs,
        "sample_n": repeated.sample_n,
        "clean_n": repeated.sample_n if repeated.clean_n is None else repeated.clean_n,
        "seed": repeated.seed,
        "confidence": confidence,
        "coverage": dict(reports[0].coverage) if reports else {},
        "holdout_classes": list(RESIDUE_HOLDOUT_DEFECT_CLASSES),
        "per_class": per_class_stats,
        "overall": {
            "detection_rate_mean": _mean(series["overall_rate"]),
            "detection_lower_bound_mean": _mean(series["overall_lower"]),
            "detection_lower_bound_worst": _min_value(series["overall_lower"]),
            "detection_lower_bound_stdev": _stdev(series["overall_lower"]),
            "abstention_rate_mean": _mean(series["overall_abstention"]),
        },
        "holdout": {
            "detection_rate_mean": _mean(series["holdout_rate"]),
            "detection_lower_bound_mean": _mean(series["holdout_lower"]),
            "detection_lower_bound_worst": _min_value(series["holdout_lower"]),
            "detection_lower_bound_stdev": _stdev(series["holdout_lower"]),
            "abstention_rate_mean": _mean(series["holdout_abstention"]),
        },
        "clean_control": {
            "false_alarm_rate_mean": _mean(series["false_alarm_rate"]),
            "false_alarm_upper_bound_mean": _mean(series["false_alarm_upper"]),
            "false_alarm_upper_bound_worst": _max_value(series["false_alarm_upper"]),
            "false_alarm_upper_bound_stdev": _stdev(series["false_alarm_upper"]),
            "abstention_rate_mean": _mean(series["clean_abstention"]),
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# v4 모드 — 오라클 vs 프로덕션
#
# v4는 *결함류별* 전용 관점이다. 강등전 하네스는 자기가 무엇을 주입했는지 알기 때문에
# 그 결함류에 맞는 세트만 골라 태울 수 있다(**오라클 모드**). 그러나 프로덕션에는 그
# 오라클이 없다 — 실 코퍼스에서는 어떤 결함이 있는지(있기는 한지) 모르므로 **모든 세트를
# 태우고 판정을 합집합**해야 한다(**프로덕션 모드**).
#
# 두 모드는 수치가 체계적으로 다르다. 오라클은 무결함 문항에도 세트가 하나만 걸리므로
# **오검출을 과소 추정**하고, 검출률은 정답을 알고 조준한 상한 추정이다. 그러므로
# **승격 판정은 프로덕션 모드 수치로만 한다** — 오라클은 결함류별 실명(失明) 지점을 찾는
# 진단 도구다(1차 강등전의 `missing_condition` 0/3 관찰이 그 용도였다).
#
# 정본: `docs/standards/residue_gate_demotion_battle_history.md` §4.6.
# ──────────────────────────────────────────────────────────────────────────

#: v4 프로덕션 모드가 태우는 관점 세트 — 일반 v2 + 결함류 전용 2종.
V4_PERSPECTIVE_SETS: tuple[tuple[Perspective, ...], ...] = (
    PROBABILITY_PERSPECTIVES,
    MISSING_CONDITION_PERSPECTIVES,
    MULTIPLE_VALID_ANSWERS_PERSPECTIVES,
)


class UnionCrossVerifier(CrossVerifier):
    """전 관점 세트를 모두 태우고 판정을 **합집합**하는 검증기 (v4 프로덕션 모드).

    집계 규칙을 여기서 다시 쓰지 않고 `cross_verify._aggregate`를 그대로 부른다 — 측정
    도구가 규칙을 복제하면 배포 규칙과 조용히 갈라지고, 그러면 측정한 것이 배포되는 것과
    달라진다(측정 구성 = 배포 구성). 마침 그 규칙 자체가 이미 합집합 의미론이다: 하나라도
    defect면 defect, 아니면 하나라도 unclear면 unclear, 전건 ok여야 ok.

    호출 비용은 세트 수 배다 — 세트 3종 x K=3 = 문항당 9콜.
    """

    def __init__(
        self,
        base: CrossVerifier,
        perspective_sets: Sequence[Sequence[Perspective]] = V4_PERSPECTIVE_SETS,
    ) -> None:
        if not perspective_sets:
            raise ValueError("관점 세트가 비었다 — 합집합할 대상이 없으면 검증이 아니다")
        # base의 provider·trace·좌석 설정을 그대로 물려받는다(좌석이 갈리면 측정이 갈린다).
        self._sets = tuple(tuple(s) for s in perspective_sets)
        super().__init__(
            provider=base._provider,
            perspectives=self._sets[0],
            trace=base._trace,
        )

    @property
    def perspective_sets(self) -> tuple[tuple[Perspective, ...], ...]:
        return self._sets

    def verify(
        self,
        subject: ResidueSubject,
        perspectives: Sequence[Perspective] | None = None,
    ) -> CrossVerificationResult:
        """세트마다 K=3을 돌리고 전 판정을 이어 붙여 한 번에 집계한다.

        `perspectives`가 명시되면 합집합을 하지 않고 그 세트만 쓴다 — 상위 코드가 특정
        세트를 지목했을 때 그 의도를 덮어쓰지 않기 위해서다.
        """
        if perspectives is not None:
            return super().verify(subject, perspectives)
        verdicts: list[PerspectiveVerdict] = []
        for perspective_set in self._sets:
            verdicts.extend(super().verify(subject, perspective_set).verdicts)
        return _aggregate(subject.problem_id, verdicts)


V4Mode = Literal["off", "oracle", "production"]


def build_v4_wiring(
    mode: V4Mode, base: CrossVerifier
) -> tuple[CrossVerifier | Mapping[ResidueDefectClass, CrossVerifier], CrossVerifier | None]:
    """v4 모드 -> (강등전 검증기, 대조군·미지정 결함류용 폴백 검증기).

    - `off`: 종전 동작 — 일반 v2 3관점 하나로 전부 본다.
    - `oracle`: 결함류별 전용 세트를 매핑으로 준다. **대조군은 폴백(일반 v2)** 이다 —
      대조군에까지 오라클을 주면 그 오검출 수치는 아무것도 대표하지 못한다(프로덕션에는
      "이 문항은 무결함이다"를 아는 경로가 없다).
    - `production`: 전 세트를 태우고 합집합하는 검증기 하나(`UnionCrossVerifier`).

    좌석(provider·trace)은 `base`에서 물려받는다 — 좌석이 갈리면 측정이 갈린다.
    """
    if mode == "production":
        return UnionCrossVerifier(base), None
    if mode == "oracle":
        mapping: dict[ResidueDefectClass, CrossVerifier] = {
            "missing_condition": CrossVerifier(
                provider=base._provider,
                perspectives=MISSING_CONDITION_PERSPECTIVES,
                trace=base._trace,
            ),
            "multiple_valid_answers": CrossVerifier(
                provider=base._provider,
                perspectives=MULTIPLE_VALID_ANSWERS_PERSPECTIVES,
                trace=base._trace,
            ),
        }
        return mapping, base
    return base, None


def main(argv: list[str] | None = None) -> int:
    """강등전 CLI — 실 코퍼스 로드 → 배터리 조립 → K=3 검증 → 리포트. 게이트는 opt-in."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.residue_gate_demotion_battle",
        description=(
            "잔여 축 교차검증 게이트 강등전 — 결함 주입 셋 + 무결함 대조군으로 검출률·"
            "오검출률을 실측하고 --max-defect-upper 보정 제안을 낸다."
        ),
    )
    parser.add_argument("corpus", type=Path, help="파일럿 코퍼스 JSONL 경로.")
    parser.add_argument(
        "--sample-n",
        type=int,
        default=5,
        help="결함류별·대조군 표본 수(기본 5 — 실 provider 비용 통제. 결함류 4종 + 대조군 "
        "1종 × K=3 관점이라 기본값도 최대 ~75회 LLM 호출).",
    )
    parser.add_argument(
        "--clean-n",
        type=int,
        default=None,
        help=(
            "무결함 대조군 표본 수(생략하면 --sample-n과 같다 — 기존 동작). 결함류 표본과 "
            "**독립**이라, 오검출 상한 보정에 필요한 대조군 n≥20을 결함류 4종까지 20건으로 "
            "늘리지 않고 확보할 수 있다(1차 강등전이 보정에 실패한 직접 원인이 대조군 n=2)."
        ),
    )
    parser.add_argument(
        "--repeat-runs",
        type=int,
        default=1,
        help=(
            "같은 배터리·같은 시드로 반복 실행할 횟수(기본 1). 2 이상이면 회차별 검출률의 "
            "평균·최악·표준편차를 함께 낸다 — 1차 기록이 요구한 '검출 일관성 자체의 측정'. "
            "호출 수가 그대로 배수로 늘어난다."
        ),
    )
    parser.add_argument("--seed", default="S4-16", help="결정론 표본 추출 시드.")
    parser.add_argument("--confidence", type=float, default=0.95, help="Wilson 신뢰수준.")
    parser.add_argument(
        "--min-detection-lower",
        type=float,
        default=0.0,
        help="전체 검출률 Wilson 하한 임계 — 미만이면 exit 1(기본 0=off).",
    )
    parser.add_argument(
        "--max-false-alarm-upper",
        type=float,
        default=1.0,
        help="대조군 오검출률 Wilson 상한 임계 — 초과면 exit 1(기본 1.0=off).",
    )
    parser.add_argument(
        "--v4",
        choices=("off", "oracle", "production"),
        default="off",
        help=(
            "결함류별 적대적 관점(v4) 사용 모드. off=일반 v2 3관점만(기본·종전 동작). "
            "oracle=주입한 결함류에 맞는 전용 세트를 골라 태운다(**진단 전용** — 오라클이 "
            "없는 프로덕션을 대표하지 않으며 오검출을 과소 추정한다). "
            "production=전 세트를 태우고 판정을 합집합한다(문항당 9콜 — **승격 판정은 이 "
            "모드로만 한다**). 정본 = residue_gate_demotion_battle_history.md §4.6."
        ),
    )
    parser.add_argument("--audit-out", type=Path, default=None, help="감사 JSONL 산출 경로.")
    parser.add_argument(
        "--authored-by",
        default=None,
        help="생성자 서명 override(검증자와 충돌 시 IndependenceError 회피용).",
    )
    # 좌석 선택은 **상호배타** — 로컬 고정과 클라우드 좌석을 동시에 지정하면 어느 쪽에서 난
    # 수치인지 말할 수 없다. argparse가 거부하게 해서 측정 시작 전에 멈춘다.
    seat = parser.add_mutually_exclusive_group()
    seat.add_argument(
        "--local-model",
        default=None,
        help=(
            "로컬 Ollama 모델 ID 오버라이드(예: qwen2.5:7b). 라우터가 고른 모델 대신 "
            "고정 모델로 강등전을 실측한다 — 운영 모델이 로컬에서 timeout으로 실행 불가일 "
            "때 측정 가능성을 확보하는 선택이며, 측정치는 하한 추정으로 해석한다."
        ),
    )
    seat.add_argument(
        "--cloud",
        action="store_true",
        help=(
            "클라우드 좌석으로 강등전을 실측한다 — 좌석은 `settings.cloud_provider`"
            "(anthropic|openrouter|deepseek)가 정하고, 이 플래그는 그 좌석을 *쓰겠다*는 "
            "선언일 뿐 좌석을 고르지 않는다(ARCH-55/ARCH-57 팩토리 경유). 1차 기록 "
            "§후속방향 2의 '상위 모델 검증기 별도 강등전' 경로 — 단 측정 구성=배포 구성 "
            "원칙상, 이 측정이 인증이 되려면 배포 라우팅도 같은 좌석이어야 한다."
        ),
    )
    args = parser.parse_args(argv)

    records = load_pilot_records(args.corpus)
    battery = build_residue_seeded_set(records)
    # 실 provider는 지연 연결(구성만으로 네트워크 0) — 실제 호출은 verify() 시점에 일어난다.
    # 이 모듈은 provider를 **조립만** 하고 `.generate()`를 직접 부르지 않는다(호출은
    # CrossVerifier가 라우터 경유로 한다) — ARCH-46 좌석 계약의 FACTORY 분류 유지.
    measurement_config: MeasurementConfig
    if args.cloud:
        verifier = CrossVerifier(provider=build_cloud_provider())
        measurement_config = build_cloud_measurement_config()
    elif args.local_model is not None:
        verifier = CrossVerifier(provider=FixedModelOllamaProvider(args.local_model))
        measurement_config = MeasurementConfig(kind="local_fixed", local_model=args.local_model)
    else:
        verifier = CrossVerifier()
        measurement_config = MeasurementConfig(kind="router_default")

    battle_verifier, default_verifier = build_v4_wiring(args.v4, verifier)

    if args.repeat_runs > 1:
        repeated = run_repeated_residue_demotion_battle(
            battery,
            verifier=battle_verifier,
            default_verifier=default_verifier,
            sample_n=args.sample_n,
            clean_n=args.clean_n,
            seed=args.seed,
            authored_by=args.authored_by,
            repeat_runs=args.repeat_runs,
            corpus_size=len(records),
            confidence=args.confidence,
            measurement_config=measurement_config,
        )
        verifier.flush_trace()
        if args.audit_out is not None:
            write_repeated_audit_jsonl(args.audit_out, repeated)
        print(render_repeated_report(repeated, confidence=args.confidence))
        # 게이트는 **최악 회차**로 판정한다 — 평균으로 통과시키면 절반의 회차가 임계 아래인
        # 검증기가 승격된다. 회차 중 하나라도 측정 실패(None)면 전체를 측정 실패로 본다.
        lowers = [r.overall_detection_lower_bound(args.confidence) for r in repeated.reports]
        dlb = None if any(v is None for v in lowers) else min(v for v in lowers if v is not None)
        uppers = [r.false_alarm_upper_bound(args.confidence) for r in repeated.reports]
        fau = None if any(v is None for v in uppers) else max(v for v in uppers if v is not None)
    else:
        report = run_residue_demotion_battle(
            battery,
            verifier=battle_verifier,
            default_verifier=default_verifier,
            sample_n=args.sample_n,
            clean_n=args.clean_n,
            seed=args.seed,
            authored_by=args.authored_by,
            measurement_config=measurement_config,
        )
        verifier.flush_trace()
        if args.audit_out is not None:
            write_audit_jsonl(args.audit_out, report)
        print(render_report(report, confidence=args.confidence, corpus_size=len(records)))
        dlb = report.overall_detection_lower_bound(args.confidence)
        fau = report.false_alarm_upper_bound(args.confidence)

    exit_code = _EXIT_OK
    if args.min_detection_lower > 0.0 and (dlb is None or dlb < args.min_detection_lower):
        exit_code = _EXIT_GATE_FAIL
    if args.max_false_alarm_upper < 1.0 and (fau is None or fau > args.max_false_alarm_upper):
        exit_code = _EXIT_GATE_FAIL
    return exit_code


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
