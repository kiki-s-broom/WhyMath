"""교육과정 표기 범위 게이트(MATH-04) hermetic 상시 회귀 — LLM 0·DB 0.

게이트는 *생성물 회계 전용*이다(학생 입력 거부 아님). 여기서는 다음을 동결한다:
  ① 폐쇄 표 로더 — 어휘 밖 construct·중복·추출 불가 토큰·빈 표를 명시 실패로 거부(공허한 게이트 차단).
  ② 표 ↔ 구조 키 어휘 — 표가 `PROFILES`의 14종 중 ASCII 전용인 abs·factorial을 뺀 12종을 정확히 덮는다.
  ③ 표 ↔ 음성화 엔진 드리프트 — 같은 매핑이 `l3/speech.py::_gate()`에 AST 키로 암묵 존재하므로, 매크로
     항목이 엔진의 학년별 실제 반응과 어긋나면 실패한다(두 번째 정본 방지).
  ④ 추출 — ASCII 함수 단어는 영문자 연속 *전체*가 일치할 때만 센다(using·cosine·dx 오탐 0)·`\\sin`은
     매크로 축에서만 센다(이중 계상 0).
  ⑤ 판정 — 학년 초과 표기만 계상·미분류/미매핑은 건수 노출·베이스라인 래칫.
  ⑥ 변별력 대조군 — 같은 코퍼스를 고등으로 판정하면 exit 0, 초등으로 판정하면 exit 1.
  ⑦ 실코퍼스 — 커밋 베이스라인과 일치(CI 상시 회귀)·측정기가 실제로 토큰을 관측함.
  ⑧ (MATH-06) ASCII 구조 축 — 초등 밴드의 미관측 해소·결함 주입 RED·프라임 구분 규칙(점 이름 vs 미분).
  ⑨ (MATH-06) 보조 코퍼스 편입 — 코퍼스별 밴드 파생 규칙·미분류 노출·결함 주입·부재 시 명시 실패.
  ⑩ (MATH-06) 엔진 게이트 확장 표 편입 — 역삼각·편미분이 표↔엔진 드리프트 검사에 묶임.

학생 경로 import 금지(④)는 `test_curriculum_notation_gate_student_path_governance.py`가 따로 동결한다.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness.curriculum_notation_gate_cli import constructs_by_band, main
from whymath_backend.l3.curriculum_notation_gate import (
    DEFAULT_AUX_SOURCES,
    KNOWN_BLIND_SPOTS,
    STRUCTURE_PATTERNS,
    AuxRecord,
    AuxSource,
    RangeScan,
    ScannedRecord,
    build_json_payload,
    derive_band,
    evaluate,
    extract_range_tokens,
    extract_structures,
    extract_words,
    load_range_baseline,
    load_range_table,
    load_standard_bands,
    render_report,
    run_gate,
    scan_aux_sources,
    scan_problem_banks,
    source_of,
)
from whymath_backend.l4.speech import PROFILES, speak_latex
from whymath_backend.schema.speech import SpeechGradeBand

# tests/backend/l3/ → parents[3] = 레포 루트.
_ROOT = Path(__file__).resolve().parents[3]
_TABLE = _ROOT / "data" / "curriculum_notation_ranges.json"
_BASELINE = _ROOT / "data" / "curriculum_notation_range_baseline.json"
_CORPUS = _ROOT / "data" / "corpus"
_STANDARDS = _CORPUS / "standards_v1" / "standards.json"

_CB = constructs_by_band()
_VOCAB = frozenset().union(*_CB.values())
_CI_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yml"


# ──────────────────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────────────────
def _entry(token: str, kind: str, construct: str) -> dict[str, str]:
    return {"token": token, "kind": kind, "construct": construct}


def _write_table(
    tmp_path: Path, entries: list[Any], *, extra: dict[str, Any] | None = None
) -> Path:
    payload: dict[str, Any] = {"schema_version": 1, "entries": entries}
    payload.update(extra or {})
    path = tmp_path / "table.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _mini_table(tmp_path: Path) -> Any:
    """합성 판정용 최소 표 — 적분(고등)·제곱근(중등)·분수(초등) 한 항목씩."""
    path = _write_table(
        tmp_path,
        [
            _entry("∫", "glyph", "integral"),
            _entry("\\int", "macro", "integral"),
            _entry("√", "glyph", "root"),
            _entry("½", "glyph", "fraction"),
            _entry("sin", "word", "trig"),
        ],
    )
    return load_range_table(path, vocabulary=_VOCAB)


def _record(
    slug: str, band: SpeechGradeBand | None, tokens: dict[tuple[str, str], int], bank: str = "b"
) -> ScannedRecord:
    return ScannedRecord(bank=bank, slug=slug, band=band, tokens=Counter(tokens))


# ──────────────────────────────────────────────────────────────────────────
# ① 폐쇄 표 로더
# ──────────────────────────────────────────────────────────────────────────
class TestRangeTableLoader:
    def test_real_table_loads_and_is_non_trivial(self) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        assert len(table.entries) >= 50
        assert {e.kind for e in table.entries} == {"macro", "glyph", "word", "structure"}
        assert table.word_tokens >= {"sin", "cos", "tan", "log", "ln", "lim", "sqrt"}

    def test_missing_table_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="FileNotFoundError"):
            load_range_table(tmp_path / "nope.json", vocabulary=_VOCAB)

    def test_bad_json_names_exception_type(self, tmp_path: Path) -> None:
        path = tmp_path / "t.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="JSONDecodeError"):
            load_range_table(path, vocabulary=_VOCAB)

    @pytest.mark.parametrize(
        ("entries", "needle"),
        [
            ([], "비어 있음"),  # 빈 표는 공허한 게이트
            ([_entry("∫", "glyph", "calculus")], "어휘 밖"),  # 새 어휘 생성 금지
            ([_entry("∫", "glyph", "integral"), _entry("∫", "glyph", "sum")], "토큰 중복"),
            ([_entry("∫", "stroke", "integral")], "알 수 없는 kind"),
            ([_entry("a", "glyph", "integral")], "단일 문자"),  # ASCII는 is_math_glyph가 안 잡는다
            ([_entry("int", "macro", "integral")], "macro 토큰은"),
            ([_entry("Sin", "word", "trig")], "소문자"),
            ([{"token": "∫", "kind": "glyph"}], "3필드"),
            ([{"token": "∫", "kind": "glyph", "construct": "integral", "x": 1}], "3필드"),
            ([_entry("", "glyph", "integral")], "비어 있지 않은"),
        ],
    )
    def test_invalid_entries_are_rejected(
        self, tmp_path: Path, entries: list[Any], needle: str
    ) -> None:
        with pytest.raises(ValueError, match=needle):
            load_range_table(_write_table(tmp_path, entries), vocabulary=_VOCAB)

    def test_wrong_schema_version_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "t.json"
        path.write_text(json.dumps({"schema_version": 2, "entries": []}), encoding="utf-8")
        with pytest.raises(ValueError, match="schema_version=1"):
            load_range_table(path, vocabulary=_VOCAB)

    def test_overlap_between_mapping_and_deliberately_unmapped_rejected(
        self, tmp_path: Path
    ) -> None:
        path = _write_table(
            tmp_path,
            [_entry("∫", "glyph", "integral")],
            extra={"deliberately_unmapped": {"∫": "사유"}},
        )
        with pytest.raises(ValueError, match="겹친다"):
            load_range_table(path, vocabulary=_VOCAB)

    def test_deliberately_unmapped_requires_a_reason(self, tmp_path: Path) -> None:
        path = _write_table(
            tmp_path, [_entry("∫", "glyph", "integral")], extra={"deliberately_unmapped": {"′": ""}}
        )
        with pytest.raises(ValueError, match="사유"):
            load_range_table(path, vocabulary=_VOCAB)


# ──────────────────────────────────────────────────────────────────────────
# ② 표 ↔ 구조 키 어휘
# ──────────────────────────────────────────────────────────────────────────
class TestTableVocabulary:
    def test_vocabulary_is_the_14_constructs_of_profiles(self) -> None:
        # 태스크 문면의 '12종'은 오기였다 — 실측 14종(_ARITHMETIC 4 + 고등 10).
        assert len(_VOCAB) == 14
        assert _VOCAB == PROFILES[SpeechGradeBand.고등].introduced_constructs

    def test_table_covers_every_construct(self) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        covered = {e.construct for e in table.entries}
        # 같은 집합이어야 한다: 빠지면 그 구조는 판정 불가, 남으면 어휘 밖(로더가 이미 거부).
        # profiles.py에 구조가 추가되면 여기서 실패해 표 갱신을 강제한다.
        # MATH-06 이전에는 abs·factorial이 ASCII 전용이라 표 밖이었으나, structure 축이 덮는다.
        assert covered == _VOCAB

    def test_deliberately_unmapped_tokens_carry_reasons(self) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        assert {"′", "\\prime", "\\bigcup"} <= set(table.deliberately_unmapped)
        assert all(reason.strip() for reason in table.deliberately_unmapped.values())

    def test_math06_graduated_the_engine_gated_tokens_out_of_the_unmapped_list(self) -> None:
        """역삼각·편미분은 엔진 게이트를 확장한 뒤 표로 편입됐다 — 미매핑 목록에 남아 있으면 모순이다."""
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        for token in ("\\arcsin", "\\arccos", "\\arctan", "\\partial"):
            assert token in table.lookup["macro"], token
            assert token not in table.deliberately_unmapped, token
        # 프라임은 토큰 단독으로 구조를 단정할 수 없어 미매핑으로 남고, 문맥 패턴(prime-call)이 센다.
        for token in ("′", "″", "‴", "\\prime"):
            assert token in table.deliberately_unmapped, token
        assert table.lookup["structure"]["prime-call"] == "derivative"

    def test_structure_entries_are_exactly_the_closed_pattern_names(self) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        assert set(table.lookup["structure"]) == set(STRUCTURE_PATTERNS)
        assert len(STRUCTURE_PATTERNS) == 7


# ──────────────────────────────────────────────────────────────────────────
# ③ 표 ↔ 음성화 엔진 드리프트 — 같은 매핑의 두 번째 정본을 만들지 않는다
# ──────────────────────────────────────────────────────────────────────────
# 매크로 항목마다 그 토큰 하나만 담은 최소 수식. 엔진이 AST 노드로 읽는 형태여야 한다.
_MACRO_PROBES: dict[str, str] = {
    "\\frac": "\\frac{1}{2}",
    "\\dfrac": "\\dfrac{1}{2}",
    "\\tfrac": "\\tfrac{1}{2}",
    "\\sqrt": "\\sqrt{2}",
    "\\sin": "\\sin x",
    "\\cos": "\\cos x",
    "\\tan": "\\tan x",
    "\\cot": "\\cot x",
    "\\sec": "\\sec x",
    "\\csc": "\\csc x",
    "\\arcsin": "\\arcsin x",
    "\\arccos": "\\arccos x",
    "\\arctan": "\\arctan x",
    "\\partial": "\\frac{\\partial f}{\\partial x}",
    "\\log": "\\log x",
    "\\ln": "\\ln x",
    "\\lg": "\\lg x",
    "\\int": "\\int_0^1 x\\,dx",
    "\\iint": "\\iint f",
    "\\iiint": "\\iiint f",
    "\\oint": "\\oint f",
    "\\sum": "\\sum_{k=1}^{n} k",
    "\\prod": "\\prod_{k=1}^{n} k",
    "\\lim": "\\lim_{x\\to 0} x",
    "\\binom": "\\binom{5}{2}",
    "\\dbinom": "\\dbinom{5}{2}",
    "\\tbinom": "\\tbinom{5}{2}",
}


class TestTableEngineDrift:
    def test_every_macro_entry_has_a_probe_and_no_stray_probes(self) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        macros = set(table.lookup["macro"])
        assert macros == set(_MACRO_PROBES), (
            "표의 매크로 항목과 드리프트 프로브 목록이 어긋났다 — 매크로를 표에 더하면 "
            "프로브도 더해 음성화 엔진과 대조하라(프로브 없는 항목은 검증되지 않는 정본이다)"
        )

    @pytest.mark.parametrize("band", list(SpeechGradeBand))
    def test_macro_entries_agree_with_speech_engine_reaction(self, band: SpeechGradeBand) -> None:
        """엔진이 그 밴드에서 unresolved로 표시하는가 ⇔ 표의 구조가 그 밴드에 미도입인가."""
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        drifted: list[str] = []
        for token, construct in sorted(table.lookup["macro"].items()):
            engine_reacts = bool(speak_latex(_MACRO_PROBES[token], band).unresolved_symbols)
            table_says_out_of_range = construct not in PROFILES[band].introduced_constructs
            if engine_reacts != table_says_out_of_range:
                drifted.append(
                    f"{token}({construct}) @ {band.value}: 엔진 반응={engine_reacts} "
                    f"표 판정(미도입)={table_says_out_of_range}"
                )
        assert not drifted, "표와 음성화 엔진이 어긋났다:\n" + "\n".join(drifted)

    def test_drift_check_discriminates_a_wrong_mapping(self) -> None:
        """대조군 — 일부러 틀린 매핑(\\int를 fraction으로)이면 같은 판정식이 어긋남을 잡아야 한다."""
        wrong_construct = "fraction"  # 모든 밴드에 도입 → 표는 '초과 아님'이라 말한다
        engine_reacts = bool(
            speak_latex(_MACRO_PROBES["\\int"], SpeechGradeBand.초등).unresolved_symbols
        )
        table_says_out_of_range = (
            wrong_construct not in PROFILES[SpeechGradeBand.초등].introduced_constructs
        )
        assert engine_reacts is True
        assert engine_reacts != table_says_out_of_range  # 판정식이 틀린 매핑에서 어긋남을 낸다


# structure 항목: 엔진이 AST로 읽어 학년 게이트를 거는 것은 caret·underscore·prime-call뿐이다. 나머지는
# 엔진에 묶인 매크로 쌍둥이(ncr↔\binom·slash-frac↔\frac)와의 일치로, 또는 "모든 밴드에 도입된 구조"(abs·
# factorial — 위반을 낼 수 없는 구조)라는 사실로 고정한다. 셋 중 어디에도 없는 항목은 검증되지 않는 정본이다.
_STRUCTURE_ENGINE_PROBES: dict[str, str] = {
    "caret": "x^{2}",
    "underscore": "a_n",
    "prime-call": "f'(x)",
}
_STRUCTURE_MACRO_TWINS: dict[str, str] = {"ncr": "\\binom", "slash-frac": "\\frac"}
_STRUCTURE_EVERY_BAND: dict[str, str] = {"pipe-abs": "abs", "bang": "factorial"}


class TestStructureEngineDrift:
    def test_every_structure_entry_is_bound_one_way_or_another(self) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        bound = (
            set(_STRUCTURE_ENGINE_PROBES) | set(_STRUCTURE_MACRO_TWINS) | set(_STRUCTURE_EVERY_BAND)
        )
        assert set(table.lookup["structure"]) == bound, (
            "structure 항목과 드리프트 묶음이 어긋났다 — 항목을 더하면 엔진 프로브·매크로 쌍둥이·"
            "전 밴드 도입 중 하나로 묶어라"
        )

    @pytest.mark.parametrize("band", list(SpeechGradeBand))
    def test_engine_bound_structures_agree_with_speech_engine_reaction(
        self, band: SpeechGradeBand
    ) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        introduced = PROFILES[band].introduced_constructs
        drifted: list[str] = []
        for name, probe in sorted(_STRUCTURE_ENGINE_PROBES.items()):
            # 프로브가 추출기에도 실제로 그 구조로 잡히는지 — 표↔엔진만 맞고 추출기가 못 보면 죽은 항목이다.
            assert extract_structures(probe)[name] >= 1, (name, probe)
            engine_reacts = bool(speak_latex(probe, band).unresolved_symbols)
            table_says_out = table.lookup["structure"][name] not in introduced
            if engine_reacts != table_says_out:
                drifted.append(
                    f"{name} @ {band.value}: 엔진={engine_reacts} 표(미도입)={table_says_out}"
                )
        assert not drifted, "구조 표와 음성화 엔진이 어긋났다:\n" + "\n".join(drifted)

    def test_macro_twins_agree_with_the_engine_bound_macro_rows(self) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        for name, twin in _STRUCTURE_MACRO_TWINS.items():
            assert table.lookup["structure"][name] == table.lookup["macro"][twin], name

    def test_every_band_structures_can_never_be_a_violation(self) -> None:
        """abs·factorial이 어느 밴드에서 미도입이 되면 이 가정이 깨진다 — 그때 엔진 프로브로 승격하라."""
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        for name, construct in _STRUCTURE_EVERY_BAND.items():
            assert table.lookup["structure"][name] == construct
            assert all(construct in PROFILES[b].introduced_constructs for b in SpeechGradeBand)

    def test_drift_check_discriminates_a_wrong_structure_mapping(self) -> None:
        """대조군 — a_n을 power(전 밴드 도입)로 잘못 매핑하면 같은 판정식이 초등에서 어긋남을 잡는다."""
        engine_reacts = bool(speak_latex("a_n", SpeechGradeBand.초등).unresolved_symbols)
        wrong_says_out = "power" not in PROFILES[SpeechGradeBand.초등].introduced_constructs
        assert engine_reacts is True and engine_reacts != wrong_says_out

    def test_point_name_vs_derivative_rule_is_the_same_in_extractor_and_engine(self) -> None:
        """프라임 구분 규칙: 대문자 밑 = 점 이름(세지 않음·게이트 안 함) / 소문자 호출형 = 미분(셈·게이트)."""
        for point_name in ("A'", "A′", "B″", "A′B′C′"):
            assert extract_structures(point_name)["prime-call"] == 0, point_name
            assert not speak_latex(point_name, "중등").unresolved_symbols, point_name
        for derivative in ("f'(x)", "f′(x)", "g″(x)", "f\\prime(x)"):
            assert extract_structures(derivative)["prime-call"] == 1, derivative
            assert speak_latex(derivative, "중등").unresolved_symbols, derivative


# glyph·word 항목은 음성화 엔진이 직접 읽지 못한다(엔진은 LaTeX AST만 본다). 그래서 항목 하나가
# 엉뚱한 구조로 오매핑돼도 드리프트 검사는 못 잡는다. 두 번째 정답 사본을 만들지 않고, **엔진에 이미
# 묶인 매크로 쌍둥이**와의 일치(`sin`↔`\\sin`·`∫`↔`\\int`)와 **유니코드 블록 가족 규칙**으로 간접 고정한다.
_GLYPH_TWINS: dict[str, str] = {
    "∫": "\\int", "∬": "\\iint", "∭": "\\iiint", "∮": "\\oint",
    "√": "\\sqrt", "∑": "\\sum", "Σ": "\\sum", "∏": "\\prod", "Π": "\\prod",
}  # fmt: skip


class TestTableSemanticsBeyondTheEngine:
    def test_every_word_entry_matches_its_engine_bound_macro_twin(self) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        for word, construct in sorted(table.lookup["word"].items()):
            twin = "\\" + word
            assert (
                twin in table.lookup["macro"]
            ), f"{word}: 엔진에 묶인 매크로 쌍둥이 {twin}가 표에 없다"
            assert construct == table.lookup["macro"][twin], f"{word}→{construct}가 {twin}와 어긋남"

    def test_glyph_entries_with_a_macro_twin_agree_with_it(self) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        for glyph, twin in sorted(_GLYPH_TWINS.items()):
            assert table.lookup["glyph"][glyph] == table.lookup["macro"][twin], f"{glyph}≠{twin}"

    def test_unicode_block_families_map_to_one_construct(self) -> None:
        """첨자·분수꼴·루트 글리프는 유니코드 블록으로 구조가 정해진다 — 블록 안에서 섞이면 안 된다."""
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        expected: dict[str, str] = {}
        for glyph in table.lookup["glyph"]:
            code = ord(glyph)
            if 0x2080 <= code <= 0x209F:
                expected[glyph] = "subscript"
            elif 0x2070 <= code <= 0x207F or glyph in "¹²³":
                expected[glyph] = "power"
            elif 0x2150 <= code <= 0x215F or glyph in "¼½¾":
                expected[glyph] = "fraction"
            elif glyph in "√∛∜":
                expected[glyph] = "root"
            elif glyph == "∂":
                expected[glyph] = "derivative"
        assert len(expected) >= 45  # 가족 규칙이 실제로 항목 대부분을 덮는다(공허 방지)
        wrong = {
            g: (c, table.lookup["glyph"][g])
            for g, c in expected.items()
            if table.lookup["glyph"][g] != c
        }
        assert not wrong, f"유니코드 블록 가족과 표가 어긋났다 {{글리프: (기대, 표)}}: {wrong}"


# ──────────────────────────────────────────────────────────────────────────
# ④ 추출
# ──────────────────────────────────────────────────────────────────────────
class TestExtraction:
    _WORDS = frozenset({"sin", "cos", "tan", "log", "ln", "lim", "sqrt"})

    def test_whole_word_match_only(self) -> None:
        text = "using cosine and sinh then dx, tangent, login, slim, sqrtx"
        assert extract_words(text, vocabulary=self._WORDS) == Counter()

    def test_plain_function_words_are_counted(self) -> None:
        found = extract_words(
            "sin x + cos(y) - tan 30° , log_2 x, ln 3, lim x, sqrt(2)", vocabulary=self._WORDS
        )
        assert found == Counter(
            {"sin": 1, "cos": 1, "tan": 1, "log": 1, "ln": 1, "lim": 1, "sqrt": 1}
        )

    def test_digit_adjacent_plain_notation_is_counted(self) -> None:
        # 숫자는 단어 경계다 — 평문 코퍼스는 sin30°·log2·sqrt2처럼 붙여 쓴다.
        found = extract_words("sin30° + log2 8 + sqrt2", vocabulary=self._WORDS)
        assert found == Counter({"sin": 1, "log": 1, "sqrt": 1})

    def test_latex_macro_is_counted_once_not_twice(self) -> None:
        found = extract_range_tokens("\\sin x", words=self._WORDS)
        assert found == Counter({("macro", "\\sin"): 1})  # 단어 축은 백슬래시 뒤를 건너뛴다

    def test_tail_of_a_macro_name_is_not_a_word(self) -> None:
        # `\xsin`은 매크로 한 덩어리다 — 꼬리 `sin`을 따로 떼어 단어로 세면 이중 계상이 된다.
        # (영문자 lookbehind가 있어야 막힌다. 탐욕 매치라 끝쪽 lookahead는 이 입력으로는 갈리지 않는다.)
        assert extract_range_tokens("\\xsin y + \\mylog z", words=self._WORDS) == Counter(
            {("macro", "\\xsin"): 1, ("macro", "\\mylog"): 1}
        )

    def test_case_sensitive(self) -> None:
        assert extract_words("Sin X, LOG", vocabulary=self._WORDS) == Counter()

    def test_four_axes_together(self) -> None:
        found = extract_range_tokens("\\int_0^1 x²dx + √2 + sin x", words=self._WORDS)
        assert found == Counter(
            {
                ("macro", "\\int"): 1,
                ("glyph", "²"): 1,
                ("glyph", "√"): 1,
                ("word", "sin"): 1,
                ("structure", "underscore"): 1,  # \int_0
                ("structure", "caret"): 1,  # ^1
            }
        )

    def test_korean_prose_has_no_false_positives(self) -> None:
        assert (
            extract_range_tokens(
                "이차방정식의 두 근 중 큰 근을 구하시오. 항을 이항하면", words=self._WORDS
            )
            == Counter()
        )


class TestStructureExtraction:
    """ASCII 구조 표기 패턴 7종 — 각 패턴의 양성과 *그 절이 없으면 통과할 반례*를 함께 고정한다."""

    @pytest.mark.parametrize(
        ("name", "text", "expected"),
        [
            ("caret", "x^2 + m^2", 2),
            ("underscore", "a_n + x_{1} + (a)_2", 3),
            ("pipe-abs", "|x| + |-3|", 4),
            ("bang", "5! + n! + (n-1)!", 3),
            ("ncr", "17C3 + nCr + C(n, r) + 5C2", 4),
            ("slash-frac", "3/5 + 42/100 + 1 / 2 + 0.5/2", 4),
            ("prime-call", "f'(x) + f′(x) + g″(x) + h'''(x) + f\\prime(x)", 5),
        ],
    )
    def test_positive(self, name: str, text: str, expected: int) -> None:
        assert extract_structures(text)[name] == expected

    @pytest.mark.parametrize(
        ("name", "text"),
        [
            # `_`: 빈칸 표시·단독·끝 밑줄 — 앞뒤 영숫자 lookaround 절의 반례
            ("underscore", "답: ____ 이다. 빈칸 _ 에 3_ 를"),
            # `!`: 한글 뒤 문장부호·`!=` — 앞 문자 lookbehind·`(?!=)` 절의 반례
            ("bang", "맞아요! 정말요! a!=b"),
            # nCr: 섭씨·반 이름·단어 속 C — 앞뒤 영숫자 경계 절의 반례
            ("ncr", "25°C 에서 ABC3 와 A4C3 와 3C 반, C3 열, Cat"),
            # `/`: 날짜·단위·문자 분수 — 숫자 양쪽 + 앞뒤 `/`·숫자 lookaround 절의 반례
            ("slash-frac", "2024/10/05 와 km/h 와 a/b"),
            # 프라임: 점 이름(대문자)·괄호 없음·단어 속 아포스트로피·숫자 뒤 변수 — 각 절의 반례
            ("prime-call", "점 A′(1, 2) 와 A'B' 와 y' = 2 와 don't(x) 와 2x'(t)"),
        ],
    )
    def test_negative(self, name: str, text: str) -> None:
        assert extract_structures(text)[name] == 0, (name, text)

    def test_unknown_structure_token_is_rejected_by_the_loader(self, tmp_path: Path) -> None:
        path = _write_table(tmp_path, [_entry("tilde", "structure", "power")])
        with pytest.raises(ValueError, match="STRUCTURE_PATTERNS"):
            load_range_table(path, vocabulary=_VOCAB)

    def test_structure_axis_does_not_double_count_the_macro_axis(self) -> None:
        """\\frac{1}{2}는 매크로 축만 센다 — 슬래시 분수 패턴은 `\\frac`을 보지 않는다."""
        found = extract_range_tokens("\\frac{1}{2}", words=frozenset())
        assert found == Counter({("macro", "\\frac"): 1})


# ──────────────────────────────────────────────────────────────────────────
# 밴드 파생
# ──────────────────────────────────────────────────────────────────────────
class TestBandDerivation:
    def test_real_standards_map_school_types_to_bands(self) -> None:
        bands = load_standard_bands(_STANDARDS)
        assert bands["[2수01-01]"] is SpeechGradeBand.초등
        assert bands["[9수01-01]"] is SpeechGradeBand.중등
        assert bands["[10공수1-01-01]"] is SpeechGradeBand.고등

    def test_highest_band_wins(self) -> None:
        bands = {"a": SpeechGradeBand.초등, "b": SpeechGradeBand.중등, "c": SpeechGradeBand.고등}
        assert derive_band(["a", "b"], bands) is SpeechGradeBand.중등
        assert derive_band(["c", "a"], bands) is SpeechGradeBand.고등

    def test_unknown_codes_are_unclassified_not_guessed(self) -> None:
        assert derive_band(["[CALC1-02-03]"], {"a": SpeechGradeBand.초등}) is None
        assert derive_band([], {"a": SpeechGradeBand.초등}) is None
        # 정본에 있는 코드와 없는 코드가 섞이면 있는 코드만 쓴다.
        assert derive_band(["zzz", "a"], {"a": SpeechGradeBand.초등}) is SpeechGradeBand.초등

    def test_missing_standards_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="FileNotFoundError"):
            load_standard_bands(tmp_path / "none.json")

    def test_unknown_school_type_is_refused_not_guessed(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text(
            json.dumps({"standards": [{"code": "[x]", "school_type": "대학교"}]}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="알 수 없는 school_type"):
            load_standard_bands(path)

    def test_conflicting_school_type_for_same_code_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        rows = [
            {"code": "[x]", "school_type": "초등학교"},
            {"code": "[x]", "school_type": "중학교"},
        ]
        path.write_text(json.dumps({"standards": rows}), encoding="utf-8")
        with pytest.raises(ValueError, match="충돌"):
            load_standard_bands(path)


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 판정 (합성 원장 — 코퍼스 없이)
# ──────────────────────────────────────────────────────────────────────────
class TestEvaluateSynthetic:
    def test_same_token_is_out_of_range_in_middle_but_not_in_high(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = RangeScan(
            records=[
                _record("mid", SpeechGradeBand.중등, {("glyph", "∫"): 2}),
                _record("high", SpeechGradeBand.고등, {("glyph", "∫"): 5}),
            ]
        )
        report = evaluate(scan, table, _CB, frozenset())
        assert [(v.band, v.construct, v.token, v.occurrences) for v in report.violations] == [
            ("중등", "integral", "∫", 2)
        ]
        assert report.violations[0].examples == ("b/mid",)
        assert report.gate_ok is False
        assert report.in_range_occurrences == 5 and report.out_of_range_occurrences == 2

    def test_in_range_tokens_are_counted_but_not_violations(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = RangeScan(records=[_record("el", SpeechGradeBand.초등, {("glyph", "½"): 3})])
        report = evaluate(scan, table, _CB, frozenset())
        assert report.violations == () and report.gate_ok
        assert report.mapped_by_band == {"초등": 3}

    def test_baseline_suppresses_known_violation_and_reports_resolved(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = RangeScan(records=[_record("mid", SpeechGradeBand.중등, {("glyph", "∫"): 1})])
        baseline = frozenset({("중등", "integral", "∫"), ("초등", "root", "√")})
        report = evaluate(scan, table, _CB, baseline)
        assert len(report.violations) == 1  # 기존 공백은 리포트만
        assert report.new_violations == () and report.gate_ok
        assert report.baseline_resolved == (
            "초등/root/√",
        )  # 더는 관측되지 않는 항목 = 수동 정리 후보

    def test_new_violation_outside_baseline_fails(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = RangeScan(records=[_record("mid", SpeechGradeBand.중등, {("word", "sin"): 1})])
        # 중등은 trig 도입 → 위반 아님. 초등으로 내리면 위반.
        assert evaluate(scan, table, _CB, frozenset()).gate_ok is True
        forced = evaluate(scan, table, _CB, frozenset(), force_band=SpeechGradeBand.초등)
        assert forced.gate_ok is False

    def test_unclassified_records_are_excluded_but_counted(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = RangeScan(
            records=[
                _record("u1", None, {("glyph", "∫"): 9}, bank="university"),
                _record("el", SpeechGradeBand.초등, {}),
            ]
        )
        report = evaluate(scan, table, _CB, frozenset())
        assert report.records_unclassified == 1
        assert report.unclassified_by_bank == {"university": 1}
        assert report.records_judged == 1
        assert report.violations == ()  # 미분류의 ∫는 판정 제외 — 건수만 노출

    def test_force_band_judges_unclassified_too(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = RangeScan(records=[_record("u1", None, {("glyph", "∫"): 1}, bank="university")])
        report = evaluate(scan, table, _CB, frozenset(), force_band=SpeechGradeBand.초등)
        assert report.records_judged == 1 and not report.gate_ok

    def test_unmapped_tokens_are_counted_not_silently_dropped(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = RangeScan(
            records=[_record("h", SpeechGradeBand.고등, {("glyph", "π"): 4, ("macro", "\\pi"): 1})]
        )
        report = evaluate(scan, table, _CB, frozenset())
        assert report.unmapped_occurrences == 5
        assert {(u.kind, u.token, u.occurrences) for u in report.unmapped} == {
            ("glyph", "π", 4),
            ("macro", "\\pi", 1),
        }

    def test_unobserved_band_is_surfaced(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = RangeScan(
            records=[
                _record("el", SpeechGradeBand.초등, {}),  # 표의 토큰이 한 번도 안 보이는 밴드
                _record("hs", SpeechGradeBand.고등, {("glyph", "∫"): 1}),
            ]
        )
        report = evaluate(scan, table, _CB, frozenset())
        assert report.unobserved_bands == ("초등",)
        assert "미관측 밴드: 초등" in render_report(report)

    def test_missing_band_injection_fails_loudly(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = RangeScan(records=[_record("mid", SpeechGradeBand.중등, {})])
        partial = {SpeechGradeBand.초등: _CB[SpeechGradeBand.초등]}
        with pytest.raises(ValueError, match="주입되지 않았다"):
            evaluate(scan, table, partial, frozenset())

    def test_report_never_proposes_deleting_content(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = RangeScan(records=[_record("mid", SpeechGradeBand.중등, {("glyph", "∫"): 1})])
        text = render_report(evaluate(scan, table, _CB, frozenset()))
        assert "콘텐츠는 삭제·수정하지 않는다" in text  # 회계이지 개입이 아니다
        assert "학생 입력 거부 아님" in text

    def test_blind_spots_are_always_disclosed(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        text = render_report(
            evaluate(
                RangeScan(records=[_record("e", SpeechGradeBand.초등, {})]), table, _CB, frozenset()
            )
        )
        assert all(spot in text for spot in KNOWN_BLIND_SPOTS)


# ──────────────────────────────────────────────────────────────────────────
# 합성 코퍼스 end-to-end — 실제 로더(위생·스키마)·표·베이스라인·CLI를 끝까지 통과
# ──────────────────────────────────────────────────────────────────────────
def _synthetic_corpus(tmp_path: Path, *, question: str, code: str) -> Path:
    """실코퍼스 1레코드를 변형해 합성 은행을 만든다(스키마·저작권 위생 검증을 그대로 통과)."""
    first = (
        (_CORPUS / "problem_bank_v1" / "problems.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    record = json.loads(first)
    record["slug"] = "wm-synthetic-range-probe"
    record["question_text"] = question
    record["achievement_standard_codes"] = [code]
    bank = tmp_path / "corpus" / "problem_bank_synthetic_v0"
    bank.mkdir(parents=True)
    (bank / "problems.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return tmp_path / "corpus"


class TestEndToEndSynthetic:
    def test_middle_school_problem_with_integral_glyph_fails_then_baseline_passes(
        self, tmp_path: Path
    ) -> None:
        corpus = _synthetic_corpus(
            tmp_path, question="구간 [0, 1]에서 ∫ x dx 를 구하시오.", code="[9수01-01]"
        )
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"schema_version": 1, "violations": []}), encoding="utf-8")
        argv = [
            "--corpus-root", str(corpus), "--standards", str(_STANDARDS), "--problem-banks-only",
            "--table", str(_TABLE), "--baseline", str(baseline), "--json", str(tmp_path / "r.json"),
        ]  # fmt: skip
        assert main(argv) == 1  # 중등 문항의 ∫ — 학년 초과
        payload = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
        assert payload["gate_ok"] is False
        assert [(v["band"], v["construct"], v["token"]) for v in payload["new_violations"]] == [
            ("중등", "integral", "∫")
        ]

        # 의식적 수동 편집으로 베이스라인에 등재하면 래칫이 통과시킨다.
        baseline.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "violations": [{"band": "중등", "construct": "integral", "token": "∫"}],
                }
            ),
            encoding="utf-8",
        )
        assert main(argv) == 0

    def test_same_problem_under_a_high_school_code_passes(self, tmp_path: Path) -> None:
        corpus = _synthetic_corpus(
            tmp_path, question="구간 [0, 1]에서 ∫ x dx 를 구하시오.", code="[10공수1-01-01]"
        )
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"schema_version": 1, "violations": []}), encoding="utf-8")
        argv = [
            "--corpus-root",
            str(corpus),
            "--standards",
            str(_STANDARDS),
            "--problem-banks-only",
            "--baseline",
            str(baseline),
        ]
        assert main(argv) == 0  # 같은 표기·다른 학년 = 판정이 학년 축을 실제로 본다

    def test_plain_ascii_function_word_is_caught_in_a_middle_school_problem(
        self, tmp_path: Path
    ) -> None:
        corpus = _synthetic_corpus(
            tmp_path, question="sin 30° 의 값을 구하시오.", code="[2수01-01]"
        )
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"schema_version": 1, "violations": []}), encoding="utf-8")
        argv = [
            "--corpus-root",
            str(corpus),
            "--standards",
            str(_STANDARDS),
            "--problem-banks-only",
            "--baseline",
            str(baseline),
        ]
        assert main(argv) == 1  # 매크로·글리프만 봤다면 이 문항은 통과했을 것이다

    def test_missing_baseline_is_a_loud_failure_not_a_pass(self, tmp_path: Path) -> None:
        corpus = _synthetic_corpus(tmp_path, question="2 + 3 = ?", code="[2수01-01]")
        with pytest.raises(FileNotFoundError, match="FileNotFoundError"):
            main(
                [
                    "--corpus-root",
                    str(corpus),
                    "--standards",
                    str(_STANDARDS),
                    "--problem-banks-only",
                    "--baseline",
                    str(tmp_path / "x.json"),
                ]
            )

    def test_empty_corpus_is_a_loud_failure_not_a_vacuous_pass(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError, match="코퍼스 0건"):
            run_gate(
                corpus_root=empty, table_path=_TABLE, baseline_path=_BASELINE,
                standards_path=_STANDARDS, constructs_by_band=_CB,
            )  # fmt: skip

    def test_invalid_force_band_is_rejected_by_argparse(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--force-grade-band", "대학원"])
        assert exc.value.code == 2

    def test_scan_zero_records_is_refused(self, tmp_path: Path) -> None:
        bank = tmp_path / "problem_bank_blank_v0"
        bank.mkdir()
        (bank / "problems.jsonl").write_text("\n", encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="레코드 0건"):
            scan_problem_banks([bank / "problems.jsonl"], {}, words=frozenset())


# ──────────────────────────────────────────────────────────────────────────
# ⑧ ASCII 구조 축 — 초등 밴드 미관측 해소 (MATH-06 ①)
#    초등 문항에 *상위 구조를 주입*해 RED를 실측하고, 같은 문항의 초등 허용 구조는 GREEN임을 대조한다.
# ──────────────────────────────────────────────────────────────────────────
_ELEMENTARY_CODE = "[2수01-01]"


def _run_synthetic(tmp_path: Path, question: str, code: str) -> tuple[int, dict[str, Any]]:
    corpus = _synthetic_corpus(tmp_path, question=question, code=code)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"schema_version": 1, "violations": []}), encoding="utf-8")
    out = tmp_path / "r.json"
    code_ = main(
        [
            "--corpus-root", str(corpus), "--standards", str(_STANDARDS), "--problem-banks-only",
            "--baseline", str(baseline), "--json", str(out),
        ]  # fmt: skip
    )
    return code_, json.loads(out.read_text(encoding="utf-8"))


class TestElementaryBandIsObservable:
    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("수열 a_n 의 첫째 항을 구하시오.", ("초등", "subscript", "underscore")),
            ("서로 다른 17개에서 3개를 뽑는 17C3 을 구하시오.", ("초등", "binom", "ncr")),
            ("f'(x) 를 구하시오.", ("초등", "derivative", "prime-call")),
            ("arcsin 0 의 값을 구하시오.", ("초등", "trig", "arcsin")),
            ("편미분 \\partial x 를 구하시오.", ("초등", "derivative", "\\partial")),
        ],
    )
    def test_injecting_a_higher_structure_into_an_elementary_item_goes_red(
        self, tmp_path: Path, question: str, expected: tuple[str, str, str]
    ) -> None:
        code, payload = _run_synthetic(tmp_path, question, _ELEMENTARY_CODE)
        assert code == 1  # 결함 주입 → RED (구조 축이 없던 때는 \\partial 외에는 전부 GREEN이었다)
        assert [(v["band"], v["construct"], v["token"]) for v in payload["new_violations"]] == [
            expected
        ]

    def test_control_the_same_item_with_elementary_structures_is_green_and_observed(
        self, tmp_path: Path
    ) -> None:
        question = "16 m^2 를 cm^2 로 나타내고 3/5 와 5! 와 |-2| 의 값을 구하시오."
        code, payload = _run_synthetic(tmp_path, question, _ELEMENTARY_CODE)
        assert code == 0 and payload["new_violations"] == []
        # 관측이 0이 아니다 — '초과 0건'이 미관측이 아니라 증거가 된다.
        assert payload["mapped_by_band"]["초등"] == 6  # caret 2 + slash-frac 1 + bang 1 + pipe 2
        assert payload["unobserved_bands"] == []

    def test_math04_blind_spot_is_gone_elementary_structures_are_counted(self) -> None:
        """MATH-04 첫 실측: 초등 2,798문항에서 표의 토큰 관측이 0회였다 — 같은 입력이 이제 센다."""
        found = extract_range_tokens("9m^2 는 몇 cm^2 인지, 3/5 는 얼마인지", words=frozenset())
        assert found == Counter({("structure", "caret"): 2, ("structure", "slash-frac"): 1})


# ──────────────────────────────────────────────────────────────────────────
# ⑨ 보조 코퍼스 편입 (MATH-06 ②) — 코퍼스별 밴드 파생 규칙·미분류 노출·결함 주입·명시 실패
# ──────────────────────────────────────────────────────────────────────────
_CODE_BANDS = {
    "[9수02-08]": SpeechGradeBand.중등,
    "[10공수1-02-05]": SpeechGradeBand.고등,
    "[2수01-01]": SpeechGradeBand.초등,
}


def _aux_scan(tmp_path: Path, records: list[AuxRecord], name: str = "aux_v0") -> RangeScan:
    source = AuxSource(
        name=name,
        relative_path="aux.json",
        rule="테스트 합성 규칙",
        read=lambda _path: records,
    )
    return scan_aux_sources(
        tmp_path, [source], _CODE_BANDS, words=frozenset({"sin"}), scan=RangeScan()
    )


class TestAuxCorpora:
    def test_aux_record_band_follows_its_own_codes_and_unknown_is_unclassified(
        self, tmp_path: Path
    ) -> None:
        scan = _aux_scan(
            tmp_path,
            [
                AuxRecord("known", ("x",), (("[9수02-08]",),)),
                AuxRecord(
                    "alt", ("x",), (("9수02-08", "[9수02-08]"),)
                ),  # 두 번째 후보가 정본에 있다
                AuxRecord("multi", ("x",), (("[2수01-01]",), ("[10공수1-02-05]",))),
                AuxRecord("unknown", ("x",), (("[12미적I-01-01]",),)),  # 정본에 없다 → 추측 금지
                AuxRecord("nocode", ("x",), ()),
            ],
        )
        bands = {r.slug: r.band for r in scan.records}
        assert bands == {
            "known": SpeechGradeBand.중등,
            "alt": SpeechGradeBand.중등,
            "multi": SpeechGradeBand.고등,  # 복수 코드는 최고 밴드
            "unknown": None,
            "nocode": None,
        }

    def test_fixed_band_wins_over_codes(self, tmp_path: Path) -> None:
        scan = _aux_scan(
            tmp_path, [AuxRecord("u", ("x",), (("[2수01-01]",),), fixed_band=SpeechGradeBand.대학)]
        )
        assert scan.records[0].band is SpeechGradeBand.대학

    def test_aux_defect_injection_a_middle_school_formula_with_an_integral_goes_red(
        self, tmp_path: Path
    ) -> None:
        table = _mini_table(tmp_path)
        scan = _aux_scan(
            tmp_path,
            [
                AuxRecord("bad", ("\\int x dx",), (("[9수02-08]",),)),
                AuxRecord("ok", ("\\int x dx",), (("[10공수1-02-05]",),)),  # 같은 표기·고등 → 통과
            ],
            name="formula_graph_v1",
        )
        # _mini_table에는 \\int가 있다. 단어 축 어휘는 {sin}.
        report = evaluate(scan, table, _CB, frozenset())
        assert [(v.band, v.construct, v.token) for v in report.violations] == [
            ("중등", "integral", "\\int")
        ]
        assert report.violations[0].examples == ("formula_graph_v1/bad",)
        assert not report.gate_ok

    def test_per_source_stats_and_rules_are_reported(self, tmp_path: Path) -> None:
        table = _mini_table(tmp_path)
        scan = _aux_scan(
            tmp_path,
            [
                AuxRecord("a", ("\\int x",), (("[9수02-08]",),)),
                AuxRecord("b", ("\\int x",), (("[10공수1-02-05]",),)),
                AuxRecord("c", ("\\int x",), (("[없는코드]",),)),
            ],
            name="aux_v0",
        )
        report = evaluate(scan, table, _CB, frozenset())
        assert report.source_stats["aux_v0"] == {
            "records": 3, "judged": 2, "unclassified": 1, "mapped": 2, "out_of_range": 1,
        }  # fmt: skip
        assert report.source_rules == {"aux_v0": "테스트 합성 규칙"}
        text = render_report(report)
        assert "aux_v0: 3/2/1 · 2/1" in text and "규칙: 테스트 합성 규칙" in text
        payload = json.loads(json.dumps(build_json_payload(report), ensure_ascii=False))
        assert payload["source_stats"]["aux_v0"]["unclassified"] == 1
        assert payload["source_rules"]["aux_v0"] == "테스트 합성 규칙"

    def test_problem_banks_are_one_source_and_aux_sources_are_their_own(self) -> None:
        assert source_of("problem_bank_elementary_v0") == "problem_bank_*"
        assert source_of("problem_bank_v1") == "problem_bank_*"
        assert source_of("concept_content_v1") == "concept_content_v1"

    def test_missing_aux_corpus_fails_loudly_not_silently_skipped(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="보조 코퍼스 부재"):
            scan_aux_sources(
                tmp_path, DEFAULT_AUX_SOURCES, _CODE_BANDS, words=frozenset(), scan=RangeScan()
            )

    def test_empty_aux_corpus_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="레코드 0건"):
            _aux_scan(tmp_path, [])

    def test_university_content_requires_its_scope_premise(self, tmp_path: Path) -> None:
        """파일 수준 규칙(전부 대학)의 근거 scope가 깨지면 밴드를 추측하지 않고 멈춘다."""
        source = next(s for s in DEFAULT_AUX_SOURCES if s.name == "concept_content_university_v1")
        path = tmp_path / source.relative_path
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"scope": "K-12", "content": [{"code": "x"}]}), encoding="utf-8")
        with pytest.raises(ValueError, match="scope"):
            source.read(path)

    def test_default_sources_cover_the_five_aux_corpora_with_rules(self) -> None:
        names = {s.name for s in DEFAULT_AUX_SOURCES}
        assert names == {
            "concept_content_v1",
            "concept_content_university_v1",
            "formula_graph_v1",
            "concept_visual_style_v1",
            "concept_visualization_v1",
        }
        assert all(s.rule.strip() for s in DEFAULT_AUX_SOURCES)
        for source in DEFAULT_AUX_SOURCES:
            assert (_CORPUS / source.relative_path).is_file(), source.relative_path

    def test_ci_gate_step_includes_the_aux_corpora(self) -> None:
        """배선 동결 — CI 게이트 스텝이 `--problem-banks-only`로 보조 코퍼스를 빼면 범위 확장이 무효가 된다."""
        text = _CI_WORKFLOW.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if "curriculum_notation_gate_cli" in ln]
        assert lines, "CI에 교육과정 표기 범위 게이트 스텝이 없다"
        assert not any("--problem-banks-only" in ln for ln in lines), lines


# ──────────────────────────────────────────────────────────────────────────
# ⑥⑦ 실코퍼스 — 상시 회귀 + 변별력 대조군
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def real_scan() -> RangeScan:
    table = load_range_table(_TABLE, vocabulary=_VOCAB)
    codes = load_standard_bands(_STANDARDS)
    paths = sorted(_CORPUS.glob("problem_bank_*/problems.jsonl"))
    scan = scan_problem_banks(paths, codes, words=table.word_tokens)
    # CLI 기본 실행과 같은 범위 — 문항 은행 + 보조 코퍼스 5종.
    return scan_aux_sources(_CORPUS, DEFAULT_AUX_SOURCES, codes, words=table.word_tokens, scan=scan)


def _problem_banks_only(scan: RangeScan) -> RangeScan:
    """문항 은행 레코드만 — MATH-04 시절 범위. 매크로 0건 같은 문항 코퍼스 고유 사실을 단언할 때 쓴다."""
    return RangeScan(records=[r for r in scan.records if source_of(r.bank) == "problem_bank_*"])


class TestRealCorpus:
    def test_committed_baseline_matches_reality(self, real_scan: RangeScan) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        report = evaluate(real_scan, table, _CB, load_range_baseline(_BASELINE))
        assert report.gate_ok, render_report(report)
        assert report.baseline_resolved == ()  # 베이스라인이 낡았으면(해소 항목 존재) 수동 정리하라

    def test_scan_is_exhaustive_and_band_derivation_covers_the_corpus(
        self, real_scan: RangeScan
    ) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        report = evaluate(real_scan, table, _CB, frozenset())
        assert report.records_scanned >= 14000
        # 미분류는 대학 CALC1 은행 + 수식 그래프의 정본 밖 코드뿐이어야 한다 — 다른 코퍼스가 미분류로
        # 새면 밴드 파생이 깨진 것이다(보조 코퍼스 5종 중 수식 그래프만 코드가 정본에 없는 레코드를 가진다).
        assert set(report.unclassified_by_bank) <= {
            "problem_bank_university_calc1_v0",
            "problem_bank_university_calc1_chain_quotient_v0",
            "formula_graph_v1",
        }
        assert set(report.records_by_band) == {"초등", "중등", "고등", "대학"}

    def test_every_source_is_reported_with_its_derivation_rule_and_unclassified_count(
        self, real_scan: RangeScan
    ) -> None:
        """MATH-06 ② — 코퍼스별로 파생 규칙과 미분류 건수를 리포트한다(합산 숫자 하나로 숨기지 않는다)."""
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        report = evaluate(real_scan, table, _CB, frozenset())
        expected = {"problem_bank_*"} | {s.name for s in DEFAULT_AUX_SOURCES}
        assert set(report.source_stats) == expected
        assert set(report.source_rules) == expected
        for name, stats in report.source_stats.items():
            assert stats["records"] > 0, name
            assert stats["judged"] + stats["unclassified"] == stats["records"], name
        # 파생이 막힌 레코드는 formula_graph_v1에만 있고 건수가 노출된다(밴드를 추측하지 않았다).
        assert report.source_stats["formula_graph_v1"]["unclassified"] > 0
        for name in expected - {"formula_graph_v1", "problem_bank_*"}:
            assert report.source_stats[name]["unclassified"] == 0, name
        text = render_report(report)
        assert all(name in text for name in expected)

    def test_instrument_actually_observes_tokens(self, real_scan: RangeScan) -> None:
        """측정기가 눈먼 것이 아님 — 모든 밴드에서 표의 토큰이 실제로 읽힌다."""
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        report = evaluate(real_scan, table, _CB, frozenset())
        for band in ("초등", "중등", "고등", "대학"):
            assert report.mapped_by_band.get(band, 0) > 0, band
        # MATH-06 ① — 초등은 표기가 ×·÷·ASCII ^·분수뿐이라 구조 축 이전에는 관측이 0이었다(MATH-04 첫 실측).
        # 이제 어떤 밴드도 '미관측'이 아니다: 초등의 '초과 0건'은 증거가 된다.
        assert report.unobserved_bands == ()

    def test_elementary_observation_comes_from_the_structure_axis(
        self, real_scan: RangeScan
    ) -> None:
        """초등 관측의 출처 — 구조 축을 빼면 문항 코퍼스의 초등 관측이 다시 0이 된다(축의 기여를 분리)."""
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        elementary = [
            r for r in _problem_banks_only(real_scan).records if r.band is SpeechGradeBand.초등
        ]
        assert len(elementary) >= 2000  # MATH-04 첫 실측의 초등 문항 2,798건 규모
        mapped_by_kind: Counter[str] = Counter()
        for rec in elementary:
            for (kind, token), count in rec.tokens.items():
                if token in table.lookup[kind]:  # 표에 있는 토큰만 관측이다(×·÷·π는 표 밖)
                    mapped_by_kind[kind] += count
        # MATH-04 첫 실측: 매크로·글리프·단어 축으로는 표의 토큰이 0회였다 — 구조 축만이 초등을 본다.
        assert mapped_by_kind["macro"] == mapped_by_kind["glyph"] == mapped_by_kind["word"] == 0
        assert mapped_by_kind["structure"] > 0

    def test_control_high_school_passes_and_elementary_fails(self, real_scan: RangeScan) -> None:
        """⑤ 변별력 — 같은 코퍼스: 고등 프로파일 → 통과, 초등 프로파일 → 실패. 같으면 학년 축을 안 본다."""
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        high = evaluate(real_scan, table, _CB, frozenset(), force_band=SpeechGradeBand.고등)
        elem = evaluate(real_scan, table, _CB, frozenset(), force_band=SpeechGradeBand.초등)
        assert high.gate_ok and high.violations == ()
        assert not elem.gate_ok and len(elem.violations) >= 10
        assert elem.out_of_range_occurrences > 0 == high.out_of_range_occurrences

    def test_word_axis_is_what_sees_trig_log_limit_in_this_corpus(
        self, real_scan: RangeScan
    ) -> None:
        """코퍼스에 LaTeX 매크로가 0건이라 매크로·글리프만으로는 삼각·로그·극한이 통째로 안 보인다."""
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        banks = _problem_banks_only(
            real_scan
        )  # 문항 코퍼스 고유 사실 — 보조 코퍼스는 LaTeX를 쓸 수 있다
        elem = evaluate(banks, table, _CB, frozenset(), force_band=SpeechGradeBand.초등)
        by_construct: dict[str, set[str]] = {}
        for v in elem.violations:
            by_construct.setdefault(v.construct, set()).add(v.kind)
        for construct in ("trig", "log", "limit"):
            assert by_construct[construct] == {"word"}, construct  # 단어 축 없이는 0건이다
        assert not any(
            t.startswith("\\") for r in banks.records for (_k, t) in r.tokens
        )  # 매크로 0건

    def test_cli_end_to_end_on_the_real_corpus(self, tmp_path: Path) -> None:
        out = tmp_path / "r.json"
        assert main(["--json", str(out)]) == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["gate_ok"] is True and payload["forced_band"] is None
        assert payload["known_blind_spots"] and payload["unobserved_bands"] == []
        assert set(payload["source_stats"]) == {"problem_bank_*"} | {
            s.name for s in DEFAULT_AUX_SOURCES
        }
        assert main(["--force-grade-band", "고등"]) == 0
        assert main(["--force-grade-band", "초등"]) == 1

    def test_json_payload_is_serializable_and_complete(self, real_scan: RangeScan) -> None:
        table = load_range_table(_TABLE, vocabulary=_VOCAB)
        elem = evaluate(real_scan, table, _CB, frozenset(), force_band=SpeechGradeBand.초등)
        payload = json.loads(json.dumps(build_json_payload(elem), ensure_ascii=False))
        assert payload["forced_band"] == "초등" and payload["new_violations"]
        assert {"band", "construct", "kind", "token", "occurrences", "records", "examples"} <= set(
            payload["new_violations"][0]
        )
