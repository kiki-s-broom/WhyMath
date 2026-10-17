"""발문 의미 어휘 트리거 거버넌스(QUAL-12) — QUAL-11 사고 부류의 신규 유입 차단.

배경: 초등 어림 코퍼스는 발문 "X의 자리에서"와 정답 "X의 자리까지" 해석이 어긋나 600문 중 537문이
교과 관례와 달랐고, 수용 게이트(SymPy 검증)는 생성기가 만든 조건식만 보므로 이를 통과시켰다.
QUAL-12 전수 감사(14,538행·38코퍼스)는 이 부류의 현존 불일치를 0건으로 확정했다. 그러나 그 0건은
"발문 의미 어휘가 있는 코퍼스가 3개뿐"이라는 데이터 사실에 기댄다 — 새 템플릿이 자리·방향·경계
어휘를 들여오는 순간 같은 사각이 열린다.

이 테스트가 막는 것: 어휘 계열(자리 지시·올림/버림·경계 방향·한정·부정)이 발문에 나타나는
(코퍼스, 계열) 쌍은 전부 **독립 계산 동결 테스트에 등록**돼야 한다. 등록 없이 어휘가 들어오면 RED,
어휘가 사라졌는데 등록이 남아 있어도 RED(낡은 등록은 "보호 있음"의 위장이다).

범위 밖(명시): "큰 근/작은 근/~보다 큰/에서 뺀" 같은 순서 방향어 계열은 이 트리거에 넣지 않았다 —
감사에서 불일치 0건이었으나 이 계열을 동결하는 테스트는 아직 없다(후속 태스크로 분리).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS_ROOT = _ROOT / "data" / "corpus"
_TESTS_DIR = Path(__file__).resolve().parent

# 어휘 계열 — QUAL-11형(경계·자리·방향이 정답 해석을 바꾸는 어휘)만 둔다.
HOOK_FAMILIES: dict[str, re.Pattern[str]] = {
    "자리지시": re.compile(r"의 자리"),
    "올림버림": re.compile(r"올림|버림|반올림"),
    "경계방향": re.compile(r"이상|이하|초과|미만"),
    "한정": re.compile(r"적어도|많아야|정확히|반드시|항상"),
    "부정": re.compile(r"옳지 않|아닌 것|틀린 것"),
}

# (코퍼스 디렉터리, 어휘 계열) → 그 쌍을 독립 계산으로 동결하는 테스트 파일.
# 파일은 실재해야 하고, 코퍼스 디렉터리 이름을 본문에 포함해야 한다(이름만 걸어 두는 위장 차단).
REGISTRY: dict[tuple[str, str], str] = {
    (
        "problem_bank_elementary_rounding_v0",
        "자리지시",
    ): "test_elementary_rounding_corpus_convention.py",
    (
        "problem_bank_elementary_rounding_v0",
        "올림버림",
    ): "test_elementary_rounding_corpus_convention.py",
    ("problem_bank_probability_finite_v0", "경계방향"): "test_stem_hook_independent_answers.py",
    ("problem_bank_probability_finite_v0", "한정"): "test_stem_hook_independent_answers.py",
    ("problem_bank_p3_calculus1_diff_v0", "경계방향"): "test_stem_hook_independent_answers.py",
    ("problem_bank_p3_calculus1_diff_v0", "한정"): "test_stem_hook_independent_answers.py",
}

# 스캔 규모 하한 — 감사 시점 38개·14,538행. 부분 스캔·0건 스캔은 공허 통과다.
_MIN_CORPORA = 38
_MIN_ROWS = 14_000


def scan_hook_pairs(stems_by_corpus: dict[str, list[str]]) -> set[tuple[str, str]]:
    """코퍼스별 발문 목록에서 어휘 계열이 나타나는 (코퍼스, 계열) 쌍을 모은다 — 순수 함수."""
    pairs: set[tuple[str, str]] = set()
    for corpus, stems in stems_by_corpus.items():
        for stem in stems:
            for family, pattern in HOOK_FAMILIES.items():
                if pattern.search(stem):
                    pairs.add((corpus, family))
    return pairs


def coverage_problems(
    pairs: set[tuple[str, str]],
    registry: dict[tuple[str, str], str],
    tests_dir: Path,
) -> list[str]:
    """등록 누락·낡은 등록·부실 등록을 문자열 목록으로 낸다(비어 있으면 통과) — 순수 함수."""
    problems: list[str] = []
    for pair in sorted(pairs - registry.keys()):
        problems.append(
            f"미등록 어휘 유입: {pair} — 독립 계산 동결 테스트를 만들고 REGISTRY에 등록"
        )
    for pair in sorted(registry.keys() - pairs):
        problems.append(f"낡은 등록(어휘가 더는 없음): {pair} — 등록 제거 또는 사유 확인")
    for pair, test_file in sorted(registry.items()):
        path = tests_dir / test_file
        if not path.exists():
            problems.append(f"등록 테스트 파일 부재: {pair} → {test_file}")
        elif pair[0] not in path.read_text(encoding="utf-8"):
            problems.append(f"등록 테스트가 코퍼스를 다루지 않음: {pair} → {test_file}")
    return problems


def _load_stems() -> dict[str, list[str]]:
    stems: dict[str, list[str]] = {}
    for corpus_dir in sorted(_CORPUS_ROOT.glob("problem_bank_*")):
        path = corpus_dir / "problems.jsonl"
        assert path.exists(), f"코퍼스 파일 부재: {path}"
        stems[corpus_dir.name] = [
            json.loads(line)["question_text"]
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return stems


class TestRealCorpora:
    def test_scan_is_not_vacuous(self) -> None:
        stems = _load_stems()
        assert len(stems) >= _MIN_CORPORA, f"코퍼스 {len(stems)}개 — 부분 스캔"
        assert sum(len(v) for v in stems.values()) >= _MIN_ROWS

    def test_every_hook_pair_is_registered_and_registry_is_live(self) -> None:
        pairs = scan_hook_pairs(_load_stems())
        assert pairs, "어휘 쌍 0건 — 스캔이 아무것도 못 찾았다(공허 통과 금지)"
        problems = coverage_problems(pairs, REGISTRY, _TESTS_DIR)
        assert not problems, "\n".join(problems)


class TestGovernanceDiscriminates:
    """거버넌스 자신의 변별력 — 막으려는 상태를 주입해 RED가 나오는지 고정한다."""

    _BASE = {
        "problem_bank_elementary_rounding_v0": ["123을 올림하여 십의 자리까지 나타내면"],
        "problem_bank_probability_finite_v0": ["합이 4 이상이고 앞면이 정확히 1번"],
        "problem_bank_p3_calculus1_diff_v0": ["n은 2 이상의 자연수이고 항상 성립"],
    }

    def _problems(self, stems: dict[str, list[str]], registry: dict | None = None) -> list[str]:
        return coverage_problems(scan_hook_pairs(stems), registry or REGISTRY, _TESTS_DIR)

    def test_baseline_is_clean(self) -> None:
        assert self._problems(self._BASE) == []

    def test_new_hook_in_unregistered_corpus_is_red(self) -> None:
        stems = {**self._BASE, "problem_bank_new_v0": ["합이 5 초과인 경우의 수를 구하시오"]}
        assert any("미등록 어휘 유입" in p for p in self._problems(stems))

    def test_new_family_in_registered_corpus_is_red(self) -> None:
        stems = {**self._BASE}
        stems["problem_bank_elementary_rounding_v0"] = [
            *stems["problem_bank_elementary_rounding_v0"],
            "수가 7 미만이다",  # 경계방향 계열이 처음 등장 — 반올림 등록으로는 덮이지 않는다
        ]
        assert any("미등록 어휘 유입" in p for p in self._problems(stems))

    def test_stale_registration_is_red(self) -> None:
        stems = {**self._BASE, "problem_bank_p3_calculus1_diff_v0": ["어휘 없는 발문"]}
        assert any("낡은 등록" in p for p in self._problems(stems))

    def test_registration_pointing_at_missing_file_is_red(self) -> None:
        bad = {**REGISTRY, ("problem_bank_elementary_rounding_v0", "자리지시"): "no_such_test.py"}
        assert any("파일 부재" in p for p in self._problems(self._BASE, bad))

    def test_registration_that_ignores_the_corpus_is_red(self) -> None:
        # 실재하는 테스트 파일이지만 해당 코퍼스를 한 번도 언급하지 않는 파일에 건 위장 등록.
        corpus = "problem_bank_probability_finite_v0"
        other = next(
            p
            for p in sorted(_TESTS_DIR.glob("test_*.py"))
            if corpus not in p.read_text(encoding="utf-8")
        )
        bad = {**REGISTRY, (corpus, "한정"): other.name}
        assert any("코퍼스를 다루지 않음" in p for p in self._problems(self._BASE, bad))

    @pytest.mark.parametrize(
        "stem,family",
        [
            ("반올림하여 십의 자리까지", "자리지시"),
            ("버림하면", "올림버림"),
            ("합이 4 이상", "경계방향"),
            ("적어도 한 번", "한정"),
            ("옳지 않은 것을 고르시오", "부정"),
        ],
    )
    def test_each_family_is_detected(self, stem: str, family: str) -> None:
        pairs = scan_hook_pairs({"problem_bank_x_v0": [stem]})
        assert ("problem_bank_x_v0", family) in pairs

    def test_empty_scan_yields_no_pairs_so_real_test_cannot_pass_vacuously(self) -> None:
        assert scan_hook_pairs({}) == set()
