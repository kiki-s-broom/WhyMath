"""교육과정 표기 범위 게이트(MATH-04) — 생성물이 대상 학년에 *도입되지 않은 표기*를 쓰는지 회계한다.

정본: `docs/architecture/math_engine_gap_review.md` §3 D4. 기능 30의 4단계 검증 중
'교육과정 범위'만 축 자체가 없었다 — 중3 문항에 `∫`가 들어가도 어떤 게이트도 반응하지 않았다.

⚠ 이 모듈은 **생성물(문항·풀이) 회계 전용**이다. 학생 입력에 대한 교육과정 범위 거부는
영구 미채택이다(gap_review §2-⑤) — "고2 방법은 쓰지 마세요"는 부정적 피드백의 정서적 강화이자
앞서 배운 방법으로 푸는 학생을 처벌하는 교수학 금기다. 그래서 이 게이트의 판정은 *개입이 아니라
회계*다: 초과 표기를 발견해도 콘텐츠를 삭제·수정하지 않고 래칫에 계상하며 사람이 판단한다.
학생 경로(`api/`·`l4/polya/`·`l4/socratic/`)가 이 모듈을 import하지 않음은 소스 스캔 거버넌스
테스트(`test_curriculum_notation_gate_student_path_governance.py`)가 동결한다.

재료 3개를 잇는다(새 어휘를 만들지 않는다 — 어휘 이원화는 truth source 이중화다):
  ① 학년밴드 × 도입 구조: `l4/speech/profiles.py`의 `introduced_constructs`(14종).
     **L3는 L4를 import할 수 없으므로**(7계층 계약) 이 모듈은 `constructs_by_band`를 인자로
     주입받고, 주입하는 CLI는 `harness/curriculum_notation_gate_cli.py`다
     (`l3/pedagogy/explanation_checker` ↔ `harness/explanation_f7_eval` 선례).
  ② 표기 토큰 전수 추출: `l3/notation_coverage`의 `extract_macros`·`extract_math_glyphs` +
     이 모듈의 ASCII 함수 단어 축. 코퍼스 문항 14,034건에 LaTeX 매크로가 0건이고 표기가
     평문이라, 매크로·글리프만으로는 "초과 0건"이 실제 부재인지 측정기의 맹점인지 구분되지 않는다.
  ③ 토큰 → 구조 키 폐쇄 표: `data/curriculum_notation_ranges.json`(이 태스크가 신설).
     같은 매핑이 `l3/speech.py`의 `_gate()` 호출 12곳에 AST 노드 키로 암묵 존재하므로,
     매크로 항목은 드리프트 테스트가 음성화 엔진과 대조해 두 번째 정본이 되지 않게 묶는다.

문항에는 학년 필드가 없다 — 학년밴드는 `achievement_standard_codes` →
`standards_v1/standards.json`의 `school_type`으로 파생하고, 복수 코드면 **최고 밴드**를 쓴다
(허용 범위를 넓히는 방향 = 오탐을 줄이는 보수). 정본에 없는 코드의 문항(대학 CALC1 등)은
*미분류*로 판정에서 제외하되 건수를 노출한다(침묵 통과 금지).

판정 단위는 (밴드, 구조, 토큰) 3-튜플이다. 베이스라인
(`data/curriculum_notation_range_baseline.json`) 밖의 신규 3-튜플이 나오면 게이트 위반이다.
베이스라인 갱신은 의식적 수동 편집만 한다(자동 갱신은 래칫 무력화).

MATH-06 확장(2026-10-08): ①ASCII 구조 표기 축(`structure`)을 더해 초등 밴드의 미관측을 해소했다 —
초등 표기는 `m^2`·`3/5`뿐이라 매크로·글리프·함수 단어 축으로는 한 번도 보이지 않았다.
②문항 코퍼스 밖의 보조 코퍼스 5종(이론·대학 이론·수식 그래프·시각 양식·시각화 가능성)을 판정 범위에
편입했다(밴드 파생 규칙은 코퍼스마다 다르므로 `AuxSource`가 규칙과 함께 보유하고 리포트가 전재한다).
③역삼각·편미분·프라임을 음성화 엔진(`l3/speech.py`)의 학년 게이트에 올린 뒤 표에 편입했다.

표현≠의미: 토큰 *멤버십*만 본다 — 수식의 의미·동치는 SymPy 단일 권위(`l3/verify_step.py`)의 몫.
침묵 실패 금지: 표·베이스라인·정본·코퍼스의 부재/구조 위반은 예외 타입명과 함께 명시 실패한다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l3.notation_coverage import extract_macros, extract_math_glyphs, is_math_glyph
from whymath_backend.schema.speech import SpeechGradeBand

# ──────────────────────────────────────────────────────────────────────────
# 밴드 어휘 — standards_v1의 school_type → SpeechGradeBand (새 학년 어휘를 만들지 않는다)
# ──────────────────────────────────────────────────────────────────────────
SCHOOL_TYPE_TO_BAND: Final[Mapping[str, SpeechGradeBand]] = MappingProxyType(
    {
        "초등학교": SpeechGradeBand.초등,
        "중학교": SpeechGradeBand.중등,
        "고등학교": SpeechGradeBand.고등,
    }
)

# 복수 성취기준 코드의 밴드 결합 규칙('최고 밴드')에 쓰는 순서.
_BAND_RANK: Final[Mapping[SpeechGradeBand, int]] = MappingProxyType(
    {
        SpeechGradeBand.초등: 0,
        SpeechGradeBand.중등: 1,
        SpeechGradeBand.고등: 2,
        SpeechGradeBand.대학: 3,
    }
)

KINDS: Final[frozenset[str]] = frozenset({"macro", "glyph", "word", "structure"})
_MACRO_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^\\[a-zA-Z]+$")
_WORD_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z]+$")
# ASCII 함수 단어 — 영문자 연속 *전체*가 표의 단어와 같을 때만 센다. 앞이 `\`이면 매크로 축이 이미
# 세므로 제외(이중 계상 방지), 양옆이 영문자면 다른 단어의 일부(using·cosine·dx)라 제외한다.
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"(?<![A-Za-z\\])[A-Za-z]+(?![A-Za-z])")

# ASCII 구조 표기 — 닫힌 정규식 패턴 7종(MATH-06). 표의 `structure` 항목 토큰은 이 이름 중 하나다.
# 매크로·글리프·함수 단어로는 안 보이는 구조(`m^2`·`a_n`·`|x|`·`5!`·`17C3`·`3/5`·`f'(x)`)를 본다.
# 패턴은 **보수적 하위집합**이다 — 오탐(학년 초과 오보)을 줄이는 쪽으로 좁게 잡았고, 놓치는 쪽은
# KNOWN_BLIND_SPOTS가 전재한다.
STRUCTURE_PATTERNS: Final[Mapping[str, re.Pattern[str]]] = MappingProxyType(
    {
        # 거듭제곱 `x^2`·`m^2`. 단위 지수(m^2)와 식의 거듭제곱을 구분하지 않는다(둘 다 power).
        "caret": re.compile(r"\^"),
        # 첨자 `a_n`·`x_1`. 앞이 영숫자·닫는 괄호이고 뒤가 영숫자·여는 괄호인 `_`만 센다 —
        # 빈칸 표시 `____`·`_` 단독은 세지 않는다.
        "underscore": re.compile(r"(?<=[A-Za-z0-9)\]}])_(?=[A-Za-z0-9{(\\])"),
        # 절댓값 `|x|`. 막대 하나하나를 센다(짝 맞춤 없음 — 집합 조건제시 `{x | x>0}`도 센다).
        "pipe-abs": re.compile(r"\|"),
        # 팩토리얼 `5!`·`n!`. 문장부호 느낌표(`!` 앞이 한글)와 `!=`는 세지 않는다.
        "bang": re.compile(r"(?<=[0-9A-Za-z)])!(?!=)"),
        # 조합 `17C3`·`nCr`·`C(n, r)`. 순열 `nPr`은 대응하는 구조 키가 없어 세지 않는다.
        "ncr": re.compile(
            r"(?<![A-Za-z0-9])(?:\d{1,3}|n)C(?:\d{1,3}|r)(?![A-Za-z0-9])"
            r"|(?<![A-Za-z])C\(\s*[0-9a-z]+\s*,\s*[0-9a-z]+\s*\)"
        ),
        # 슬래시 분수 `3/5`·`42/100`. 날짜(`2024/10/05`)·URL 조각은 앞뒤 `/`·숫자로 걸러낸다.
        "slash-frac": re.compile(r"(?<![\d./])\d+(?:\.\d+)?\s?/\s?\d+(?![\d/])"),
        # 미분 호출형 `f'(x)`·`g″(x)`·`f\prime(x)`. **소문자 한 글자 + 프라임 + `(`**만 센다.
        # 대문자 밑(A′·B″)은 도형의 점 이름이고, `x′`·`y′ =`처럼 괄호가 없으면 좌표 변환일 수 있어
        # 판정 밖이다. 같은 구분 규칙을 음성화 엔진(`speech.py::_read_deriv`)이 따른다
        # (표↔엔진 드리프트 테스트로 묶임).
        "prime-call": re.compile(
            r"(?<![A-Za-z0-9])[a-z](?:[\u2032\u2033\u2034']{1,3}|\\prime)(?=\()"
        ),
    }
)

# 게이트가 *보지 못하는* 것 — 침묵하지 않고 리포트가 전재한다(notation_coverage.KNOWN_GAPS 동형).
KNOWN_BLIND_SPOTS: Final[tuple[str, ...]] = (
    "ASCII 구조 표기는 닫힌 패턴 7종(^ _ |x| ! nCr a/b f'())만 본다 — 순열 nPr·괄호 짝·"
    "단위 지수와 거듭제곱의 구분은 보지 않는다. 프라임은 소문자 밑 + '(' 호출형만 미분으로 세고, "
    "무괄호 y'=…·대문자 점 이름(A′)은 판정 밖이다.",
    "범위는 문항 코퍼스 + 보조 코퍼스 5종(이론·대학 이론·수식 그래프·시각 양식·시각화 가능성)이다"
    " — "
    "개념·원자 그래프 노드 본문과 문항 레코드 안의 렌더 명세(figure/scene)는 아직 범위 밖이다.",
    "학년밴드는 레코드의 성취기준 코드 중 최고 학교급이다 — 레코드가 겨냥한 실제 학년이 아니라 "
    "허용 범위의 상한이다(오탐을 줄이는 방향의 보수 선택). 코드를 파생할 수 없으면 미분류다.",
    "역삼각(arc*)은 삼각(trig) 구조로 묶었다 — 삼각이 도입된 중등에서 arcsin을 써도 잡지 않는다.",
)


# ──────────────────────────────────────────────────────────────────────────
# 폐쇄 표 — 토큰 → 구조 키
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class RangeEntry:
    """표 1행 — 표기 토큰이 어느 도입 구조의 표기인가."""

    token: str
    kind: str  # "macro" | "glyph" | "word"
    construct: str


@dataclass(frozen=True, slots=True)
class RangeTable:
    """토큰 → 구조 키 폐쇄 표(불변). `lookup[kind][token] = construct`."""

    entries: tuple[RangeEntry, ...]
    lookup: Mapping[str, Mapping[str, str]]
    deliberately_unmapped: Mapping[str, str]

    @property
    def word_tokens(self) -> frozenset[str]:
        """ASCII 단어 축의 어휘 — 추출 시 이 집합에 속한 단어만 센다."""
        return frozenset(self.lookup["word"])


def load_range_table(path: Path, *, vocabulary: frozenset[str]) -> RangeTable:
    """`curriculum_notation_ranges.json` → 검증된 `RangeTable`. 구조 위반은 전부 명시 실패.

    `vocabulary`는 호출자가 `PROFILES`에서 조립해 주입한 구조 키 어휘다. 표의 construct가
    어휘 밖이면 거부한다 — 표가 새 어휘를 만들면 학년 구조 어휘가 이원화된다(truth source 이중화).

    Raises:
        FileNotFoundError: 표 부재.
        ValueError: JSON 파싱 실패·구조 위반·어휘 밖 construct·토큰 중복·추출 불가 토큰
            (예외 타입명 병기).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"범위 표 부재: {path} ({type(exc).__name__}) — 표 없이는 게이트가 공허하게 통과한다"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"{path}: 최상위 dict + schema_version=1 필수")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError(f"{path}: entries 비어 있음/구조 위반 — 빈 표는 공허한 게이트다")

    entries: list[RangeEntry] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_entries):
        where = f"{path}: entries[{index}]"
        if not isinstance(raw, dict) or set(raw) != {"token", "kind", "construct"}:
            raise ValueError(f"{where}: {{token, kind, construct}} 3필드 dict 필수 — {raw!r}")
        token, kind, construct = raw["token"], raw["kind"], raw["construct"]
        if not all(isinstance(v, str) and v for v in (token, kind, construct)):
            raise ValueError(f"{where}: 세 필드는 비어 있지 않은 문자열이어야 한다 — {raw!r}")
        if kind not in KINDS:
            raise ValueError(f"{where}: 알 수 없는 kind {kind!r} (허용: {sorted(KINDS)})")
        if construct not in vocabulary:
            raise ValueError(
                f"{where}: construct {construct!r}이 주입된 구조 키 어휘 밖이다 "
                f"(어휘: {sorted(vocabulary)}) — 어휘는 profiles.py가 정본이며 "
                "표는 새로 만들지 않는다"
            )
        if token in seen:
            raise ValueError(f"{where}: 토큰 중복 {token!r} — 한 토큰은 한 구조에만 속한다")
        _require_extractable(token, kind, where)
        seen.add(token)
        entries.append(RangeEntry(token=token, kind=kind, construct=construct))

    unmapped = payload.get("deliberately_unmapped", {})
    if not isinstance(unmapped, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v for k, v in unmapped.items()
    ):
        raise ValueError(
            f"{path}: deliberately_unmapped는 {{토큰: 사유(비어 있지 않음)}} dict여야 한다"
        )
    overlap = sorted(seen & set(unmapped))
    if overlap:
        raise ValueError(f"{path}: 매핑과 의도적 미매핑이 겹친다 — {overlap}")

    lookup: dict[str, dict[str, str]] = {kind: {} for kind in sorted(KINDS)}
    for entry in entries:
        lookup[entry.kind][entry.token] = entry.construct
    return RangeTable(
        entries=tuple(entries),
        lookup=MappingProxyType({k: MappingProxyType(v) for k, v in lookup.items()}),
        deliberately_unmapped=MappingProxyType(dict(unmapped)),
    )


def _require_extractable(token: str, kind: str, where: str) -> None:
    """표 항목이 실제 추출기에 *잡히는 형태*인지 확인한다 — 잡히지 않는 항목은 죽은 항목이다."""
    if kind == "macro" and not _MACRO_TOKEN_RE.match(token):
        raise ValueError(f"{where}: macro 토큰은 `\\영문` 형태여야 한다 — {token!r}")
    if kind == "glyph" and not (len(token) == 1 and is_math_glyph(token)):
        raise ValueError(
            f"{where}: glyph 토큰은 is_math_glyph가 추출하는 단일 문자여야 한다 — {token!r}"
        )
    if kind == "word" and not _WORD_TOKEN_RE.match(token):
        raise ValueError(f"{where}: word 토큰은 소문자 영문 연속이어야 한다 — {token!r}")
    if kind == "structure" and token not in STRUCTURE_PATTERNS:
        raise ValueError(
            f"{where}: structure 토큰은 STRUCTURE_PATTERNS의 이름이어야 한다 — {token!r} "
            f"(허용: {sorted(STRUCTURE_PATTERNS)})"
        )


# ──────────────────────────────────────────────────────────────────────────
# 토큰 추출 (순수·결정론)
# ──────────────────────────────────────────────────────────────────────────
def extract_words(text: str, *, vocabulary: frozenset[str]) -> Counter[str]:
    """텍스트에서 표의 ASCII 함수 단어를 전수 추출한다(순수) — 영문자 연속 전체가 일치할 때만."""
    return Counter(w for w in _WORD_RE.findall(text) if w in vocabulary)


def extract_structures(text: str) -> Counter[str]:
    """텍스트에서 ASCII 구조 표기 패턴(STRUCTURE_PATTERNS)의 등장 횟수를 전수 추출한다(순수)."""
    found: Counter[str] = Counter()
    for name, pattern in STRUCTURE_PATTERNS.items():
        count = sum(1 for _ in pattern.finditer(text))
        if count:
            found[name] = count
    return found


def extract_range_tokens(text: str, *, words: frozenset[str]) -> Counter[tuple[str, str]]:
    """텍스트 → {(kind, token): 등장 횟수}. 매크로·글리프는 notation_coverage 추출기를 재사용."""
    found: Counter[tuple[str, str]] = Counter()
    for token, count in extract_macros(text).items():
        found[("macro", token)] += count
    for token, count in extract_math_glyphs(text).items():
        found[("glyph", token)] += count
    for token, count in extract_words(text, vocabulary=words).items():
        found[("word", token)] += count
    for token, count in extract_structures(text).items():
        found[("structure", token)] += count
    return found


# ──────────────────────────────────────────────────────────────────────────
# 학년밴드 파생 — 문항 → 성취기준 코드 → school_type → 밴드
# ──────────────────────────────────────────────────────────────────────────
def load_standard_bands(standards_path: Path) -> dict[str, SpeechGradeBand]:
    """`standards_v1/standards.json` → {성취기준 코드: 밴드}. 정본이 모호하면 명시 실패한다.

    Raises:
        FileNotFoundError: 정본 부재.
        ValueError: 파싱 실패·구조 위반·알 수 없는 school_type·같은 코드의 서로 다른 학교급.
    """
    try:
        raw = standards_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"성취기준 정본 부재: {standards_path} ({type(exc).__name__}) — 밴드 파생 불가"
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{standards_path}: {type(exc).__name__}: {exc}") from exc
    standards = payload.get("standards") if isinstance(payload, dict) else None
    if not isinstance(standards, list) or not standards:
        raise ValueError(f"{standards_path}: standards 배열 부재/비어 있음")

    bands: dict[str, SpeechGradeBand] = {}
    for index, row in enumerate(standards):
        if not isinstance(row, dict) or not isinstance(row.get("code"), str):
            raise ValueError(f"{standards_path}: standards[{index}] code 부재/구조 위반")
        school_type = row.get("school_type")
        band = SCHOOL_TYPE_TO_BAND.get(school_type) if isinstance(school_type, str) else None
        if band is None:
            raise ValueError(
                f"{standards_path}: standards[{index}] 알 수 없는 school_type {school_type!r} "
                f"(허용: {sorted(SCHOOL_TYPE_TO_BAND)}) — 밴드를 추측하지 않는다"
            )
        code = row["code"]
        if code in bands and bands[code] != band:
            raise ValueError(f"{standards_path}: 코드 {code!r}의 학교급이 충돌한다 — 밴드 모호")
        bands[code] = band
    return bands


def derive_band(
    codes: Sequence[str], code_bands: Mapping[str, SpeechGradeBand]
) -> SpeechGradeBand | None:
    """성취기준 코드들 → 문항의 밴드(정본에 있는 코드 중 최고 밴드). 하나도 없으면 None(미분류)."""
    known = [code_bands[c] for c in codes if c in code_bands]
    return max(known, key=lambda b: _BAND_RANK[b]) if known else None


# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 스캔 — 레코드 단위로 (밴드, 토큰) 원장을 보존한다
# (--force-grade-band 대조군이 재스캔 없이 재판정할 수 있도록)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class ScannedRecord:
    """문항 1건의 스캔 결과 — 밴드(None=미분류)와 토큰 원장."""

    bank: str
    slug: str
    band: SpeechGradeBand | None
    tokens: Counter[tuple[str, str]]


PROBLEM_BANK_SOURCE: Final[str] = "problem_bank_*"
PROBLEM_BANK_RULE: Final[str] = (
    "문항의 achievement_standard_codes → standards_v1의 school_type → 밴드(복수 코드면 최고 밴드)"
)


def source_of(bank: str) -> str:
    """레코드의 은행/코퍼스 이름 → 리포트의 코퍼스 키. 문항 은행은 하나, 보조 코퍼스는 각자다."""
    return PROBLEM_BANK_SOURCE if bank.startswith("problem_bank_") else bank


@dataclass(slots=True)
class RangeScan:
    """코퍼스 전수 스캔 결과 — 문항 은행 + (선택) 보조 코퍼스."""

    records: list[ScannedRecord] = field(default_factory=list)
    # 코퍼스 키 → 밴드 파생 규칙(문항과 달리 코퍼스마다 다르다 — 리포트가 전재한다).
    source_rules: dict[str, str] = field(default_factory=dict)


def _record_texts(
    question_text: str | None, explanation: str | None, choices: Sequence[str] | None
) -> list[str]:
    """문항 1건의 표기 필드(question_text·answer_explanation·choices) → 비어있지 않은 텍스트."""
    texts = [t for t in (question_text, explanation) if t]
    if choices:
        texts.extend(c for c in choices if c)
    return texts


def scan_problem_banks(
    problem_paths: Sequence[Path],
    code_bands: Mapping[str, SpeechGradeBand],
    *,
    words: frozenset[str],
) -> RangeScan:
    """문제 코퍼스 JSONL 전수 스캔(hermetic·DB 0). L1 정본 로더로 읽어 위생·스키마 검증을 거친다.

    Raises:
        FileNotFoundError: 코퍼스 0건·레코드 0건(전수 측정이 공허하게 통과하는 것 차단).
    """
    if not problem_paths:
        raise FileNotFoundError(
            "문항 코퍼스 0건 — problem_bank_*/problems.jsonl이 없다. "
            "공허 통과를 막기 위해 명시 실패"
        )
    scan = RangeScan(source_rules={PROBLEM_BANK_SOURCE: PROBLEM_BANK_RULE})
    for path in problem_paths:
        bank = path.parent.name
        for record in load_problem_bank_records(path):
            problem = record.problem
            tokens: Counter[tuple[str, str]] = Counter()
            for text in _record_texts(
                problem.question_text, problem.answer_explanation, problem.choices
            ):
                tokens.update(extract_range_tokens(text, words=words))
            scan.records.append(
                ScannedRecord(
                    bank=bank,
                    slug=record.slug,
                    band=derive_band(problem.achievement_standard_codes, code_bands),
                    tokens=tokens,
                )
            )
    if not scan.records:
        raise FileNotFoundError("문항 레코드 0건 — 공허 통과를 막기 위해 명시 실패")
    return scan


# ──────────────────────────────────────────────────────────────────────────
# 보조 코퍼스(MATH-06) — 이론·수식 그래프·시각 양식·시각화 가능성
#   문항과 달리 레코드 단위로 밴드를 파생할 재료(성취기준 코드)가 코퍼스마다 다르다. 그래서
#   코퍼스마다 *읽기 함수와 파생 규칙을 한 묶음(AuxSource)*으로 두고 규칙을 리포트에 전재하며,
#   파생하지 못한 레코드는 미분류로 건수를 노출한다(밴드를 추측하지 않는다).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class AuxRecord:
    """보조 코퍼스 레코드 1건 — 표기 필드 텍스트와 밴드 파생 재료."""

    slug: str
    texts: tuple[str, ...]
    # 코드 1개당 순서 있는 표기 후보(앞에서부터 정본에 있는 첫 후보를 쓴다) — 예: 대괄호 유무.
    code_alternatives: tuple[tuple[str, ...], ...] = ()
    fixed_band: SpeechGradeBand | None = None  # 코퍼스 수준 규칙으로 밴드가 정해지는 경우(대학)


@dataclass(frozen=True, slots=True)
class AuxSource:
    """보조 코퍼스 1종 — 상대 경로·밴드 파생 규칙(사람 가독)·읽기 함수."""

    name: str
    relative_path: str
    rule: str
    read: Callable[[Path], list[AuxRecord]]


def _bracket(code: str) -> str:
    """성취기준 정본의 코드 표기는 `[9수01-01]` — 대괄호 없는 표기를 맞춘다."""
    return code if code.startswith("[") else f"[{code}]"


def _strip_atom_suffix(code: str) -> str:
    """원자(세부개념) 코드 `10공수1-02-05-1` → 소속 성취기준 `10공수1-02-05`(끝 `-숫자` 제거)."""
    return re.sub(r"-\d+$", "", code)


def _texts(*values: Any) -> tuple[str, ...]:
    """문자열이고 비어 있지 않은 값만 모은다(None·숫자·빈 문자열은 표기 필드가 아니다)."""
    return tuple(v for v in values if isinstance(v, str) and v.strip())


def _load_aux_payload(path: Path) -> dict[str, Any]:
    """보조 코퍼스 JSON 최상위 dict. 부재·파싱 실패는 명시 실패(침묵 skip 금지)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"보조 코퍼스 부재: {path} ({type(exc).__name__}) — 범위 확장 코퍼스가 침묵으로 "
            "빠지면 안 된다"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: 최상위가 dict가 아니다")
    return payload


def _load_aux_json(path: Path, key: str) -> list[dict[str, Any]]:
    """보조 코퍼스 JSON → `payload[key]` 레코드 리스트. 구조 위반은 명시 실패."""
    rows = _load_aux_payload(path).get(key)
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError(f"{path}: {key!r} 레코드 리스트 부재/구조 위반")
    return rows


def _content_texts(row: Mapping[str, Any]) -> tuple[str, ...]:
    """개념 교수학 콘텐츠 1건의 표기 필드 — 은유·오개념·정식정의·허용표현·설명 + 암기카드 앞뒤."""
    texts = list(
        _texts(
            row.get("metaphor"),
            row.get("misconception"),
            row.get("formal_definition_internal"),
            row.get("accepted_expressions"),
            row.get("explanation"),
        )
    )
    for card in row.get("flashcards") or []:
        if isinstance(card, dict):
            texts.extend(_texts(card.get("front"), card.get("back"), card.get("mnemonic")))
    return tuple(texts)


def _read_concept_content(path: Path) -> list[AuxRecord]:
    return [
        AuxRecord(
            slug=str(row.get("code")),
            texts=_content_texts(row),
            code_alternatives=tuple((str(c),) for c in row.get("standard_codes") or []),
        )
        for row in _load_aux_json(path, "content")
    ]


def _read_concept_content_university(path: Path) -> list[AuxRecord]:
    scope = _load_aux_payload(path).get("scope")
    if scope != "대학":
        # 파일 수준 규칙(전부 대학)의 근거가 깨졌다 — 밴드를 추측하지 않고 멈춘다.
        raise ValueError(f"{path}: scope={scope!r} — 대학 이론 코퍼스의 전제(scope=대학)가 깨졌다")
    return [
        AuxRecord(
            slug=str(row.get("code")),
            texts=_content_texts(row),
            fixed_band=SpeechGradeBand.대학,
        )
        for row in _load_aux_json(path, "content")
    ]


def _read_formula_graph(path: Path) -> list[AuxRecord]:
    return [
        AuxRecord(
            slug=str(row.get("formula_id")),
            texts=_texts(
                row.get("latex"), row.get("name_ko"), row.get("mnemonic"), row.get("notes")
            ),
            code_alternatives=tuple(
                (_bracket(str(c)), str(c)) for c in row.get("standard_codes") or []
            ),
        )
        for row in _load_aux_json(path, "formulas")
    ]


def _read_atom_coded_entries(path: Path) -> list[AuxRecord]:
    """시각 양식·시각화 가능성 — 원자 코드(`10공수1-02-05-1`)로 소속 성취기준을 찾는다."""
    return [
        AuxRecord(
            slug=str(row.get("code")),
            texts=_texts(row.get("name_ko"), row.get("rationale")),
            code_alternatives=(
                (
                    _bracket(str(row.get("code"))),
                    _bracket(_strip_atom_suffix(str(row.get("code")))),
                ),
            ),
        )
        for row in _load_aux_json(path, "entries")
    ]


DEFAULT_AUX_SOURCES: Final[tuple[AuxSource, ...]] = (
    AuxSource(
        name="concept_content_v1",
        relative_path="concept_content_v1/content.json",
        rule="레코드의 standard_codes(대괄호 표기) → standards_v1 school_type → 최고 밴드",
        read=_read_concept_content,
    ),
    AuxSource(
        name="concept_content_university_v1",
        relative_path="concept_content_university_v1/content.json",
        rule="파일 scope=대학 → 전 레코드 대학 밴드(성취기준 코드 없음 · scope가 깨지면 명시 실패)",
        read=_read_concept_content_university,
    ),
    AuxSource(
        name="formula_graph_v1",
        relative_path="formula_graph_v1/graph.json",
        rule="레코드의 standard_codes(대괄호 없는 표기 → 대괄호 보정) → standards_v1 → 최고 밴드",
        read=_read_formula_graph,
    ),
    AuxSource(
        name="concept_visual_style_v1",
        relative_path="concept_visual_style_v1/concept_visual_style.json",
        rule="원자 코드 → 대괄호 보정 → 끝의 `-숫자`를 떼어 소속 성취기준 → standards_v1 → 밴드",
        read=_read_atom_coded_entries,
    ),
    AuxSource(
        name="concept_visualization_v1",
        relative_path="concept_visualization_v1/visualizability.json",
        rule="원자 코드 → 대괄호 보정 → 끝의 `-숫자`를 떼어 소속 성취기준 → standards_v1 → 밴드",
        read=_read_atom_coded_entries,
    ),
)


def _resolve_aux_band(
    record: AuxRecord, code_bands: Mapping[str, SpeechGradeBand]
) -> SpeechGradeBand | None:
    """보조 레코드 → 밴드. 코퍼스 수준 고정이 있으면 그것, 아니면 코드별 첫 정본 후보의 최고."""
    if record.fixed_band is not None:
        return record.fixed_band
    resolved = [
        next(alt for alt in alternatives if alt in code_bands)
        for alternatives in record.code_alternatives
        if any(alt in code_bands for alt in alternatives)
    ]
    return derive_band(resolved, code_bands)


def scan_aux_sources(
    corpus_root: Path,
    sources: Sequence[AuxSource],
    code_bands: Mapping[str, SpeechGradeBand],
    *,
    words: frozenset[str],
    scan: RangeScan,
) -> RangeScan:
    """보조 코퍼스를 읽어 같은 원장(`scan`)에 더한다. 코퍼스 부재·레코드 0건은 명시 실패.

    Raises:
        FileNotFoundError: 코퍼스 파일 부재 또는 레코드 0건(공허 통과 차단).
    """
    for source in sources:
        records = source.read(corpus_root / source.relative_path)
        if not records:
            raise FileNotFoundError(
                f"보조 코퍼스 {source.name} 레코드 0건 — 공허 통과를 막기 위해 명시 실패"
            )
        scan.source_rules[source.name] = source.rule
        for record in records:
            tokens: Counter[tuple[str, str]] = Counter()
            for text in record.texts:
                tokens.update(extract_range_tokens(text, words=words))
            scan.records.append(
                ScannedRecord(
                    bank=source.name,
                    slug=record.slug,
                    band=_resolve_aux_band(record, code_bands),
                    tokens=tokens,
                )
            )
    return scan


# ──────────────────────────────────────────────────────────────────────────
# 베이스라인 (래칫 정본) — 로드만 한다. 갱신은 의식적 수동 편집(자동 갱신 금지).
# ──────────────────────────────────────────────────────────────────────────
ViolationKey = tuple[str, str, str]  # (밴드, 구조, 토큰)


def load_range_baseline(path: Path) -> frozenset[ViolationKey]:
    """베이스라인 JSON → {(밴드, 구조, 토큰)}. 부재·구조 위반은 명시 실패(첫 생성도 수동 커밋).

    Raises:
        FileNotFoundError: 베이스라인 부재.
        ValueError: JSON 파싱 실패·구조 위반·알 수 없는 밴드.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"베이스라인 부재: {path} ({type(exc).__name__}) — 첫 실측 산출을 수동 커밋해야 "
            "게이트가 가동된다(자동 생성 경로 없음·래칫 보호)"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {type(exc).__name__}: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("violations"), list)
    ):
        raise ValueError(
            f"{path}: 베이스라인 구조 위반 — dict + schema_version=1 + violations 리스트"
        )
    valid_bands = {b.value for b in SpeechGradeBand}
    out: set[ViolationKey] = set()
    for entry in payload["violations"]:
        if not isinstance(entry, dict) or set(entry) < {"band", "construct", "token"}:
            raise ValueError(f"{path}: violations 항목 구조 위반: {entry!r}")
        band = str(entry["band"])
        if band not in valid_bands:
            raise ValueError(f"{path}: 알 수 없는 band {band!r} (허용: {sorted(valid_bands)})")
        out.add((band, str(entry["construct"]), str(entry["token"])))
    return frozenset(out)


# ──────────────────────────────────────────────────────────────────────────
# 판정 (순수) — 초과 표기 회계
# ──────────────────────────────────────────────────────────────────────────
_EXAMPLE_LIMIT: Final[int] = 3


@dataclass(frozen=True, slots=True)
class Violation:
    """학년 초과 표기 1건(3-튜플 단위) — 어느 밴드의 문항이 미도입 구조의 표기를 썼는가."""

    band: str
    construct: str
    kind: str
    token: str
    occurrences: int
    records: int
    examples: tuple[str, ...]  # 근거 문항 slug(최대 3건·사람이 판단할 때 열어 볼 자리)

    @property
    def key(self) -> ViolationKey:
        return (self.band, self.construct, self.token)


@dataclass(frozen=True, slots=True)
class UnmappedToken:
    """표에 없어 판정에서 제외된 매크로·글리프 — 건수를 노출한다(침묵 통과 금지)."""

    kind: str
    token: str
    occurrences: int


@dataclass(frozen=True, slots=True)
class RangeReport:
    """게이트 측정 결과(불변) — 전수 통계 + 초과 표기 + 베이스라인 대비 신규/해소."""

    forced_band: str | None
    records_scanned: int
    records_by_band: dict[str, int]
    records_unclassified: int
    unclassified_by_bank: dict[str, int]
    records_judged: int
    mapped_occurrences: int  # 표에 있는 토큰의 총 관측 — '측정기가 실제로 보고 있다'는 근거
    # 밴드별 관측 — 0인 밴드의 '초과 0건'은 증거가 아니라 미관측이다
    # (그 밴드에서 측정기는 눈이 없다).
    mapped_by_band: dict[str, int]
    in_range_occurrences: int
    out_of_range_occurrences: int
    violations: tuple[Violation, ...]
    new_violations: tuple[Violation, ...]  # 베이스라인 밖 — 게이트 위반(exit 1)
    baseline_resolved: tuple[str, ...]
    unmapped: tuple[UnmappedToken, ...]
    unmapped_occurrences: int
    # 코퍼스별 전수 통계(MATH-06) — {코퍼스 키: {records·judged·unclassified·mapped·out_of_range}}
    # 와 그 코퍼스의 밴드 파생 규칙. 코퍼스마다 파생 재료가 달라 한 숫자로 합치면 맹점이 숨는다.
    source_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    source_rules: dict[str, str] = field(default_factory=dict)

    @property
    def gate_ok(self) -> bool:
        """게이트 판정 — 신규 초과 표기 0이면 통과(베이스라인 내는 리포트만·래칫)."""
        return not self.new_violations

    @property
    def unobserved_bands(self) -> tuple[str, ...]:
        """판정 대상 문항은 있으나 표의 토큰이 한 번도 관측되지 않은 밴드 — 측정기가 눈먼 밴드."""
        judged = [b for b in self.records_by_band if self.mapped_by_band.get(b, 0) == 0]
        if self.forced_band is not None and self.mapped_by_band.get(self.forced_band, 0) == 0:
            judged.append(self.forced_band)
        return tuple(sorted(set(judged)))


def evaluate(
    scan: RangeScan,
    table: RangeTable,
    constructs_by_band: Mapping[SpeechGradeBand, frozenset[str]],
    baseline: frozenset[ViolationKey],
    *,
    force_band: SpeechGradeBand | None = None,
) -> RangeReport:
    """스캔 원장 × 표 × 밴드별 도입 구조 × 베이스라인 → 초과 표기 회계(순수·IO 0).

    `force_band`는 변별력 대조군이다 — 모든 문항(미분류 포함)을 그 밴드로 판정한다. 고등이면 exit 0,
    초등이면 exit 1이 나와야 측정기가 학년 축을 실제로 보고 있다는 뜻이다.

    Raises:
        ValueError: 판정에 필요한 밴드의 도입 구조 집합이 주입되지 않음.
    """
    by_band: Counter[str] = Counter()
    mapped_by_band: Counter[str] = Counter()
    unclassified_by_bank: Counter[str] = Counter()
    unmapped_counter: Counter[tuple[str, str]] = Counter()
    agg: dict[ViolationKey, list[Any]] = {}  # key -> [kind, occurrences, records, examples]
    source_stats: dict[str, dict[str, int]] = {}
    mapped = in_range = out_of_range = judged = 0

    for rec in scan.records:
        stats = source_stats.setdefault(
            source_of(rec.bank),
            {"records": 0, "judged": 0, "unclassified": 0, "mapped": 0, "out_of_range": 0},
        )
        stats["records"] += 1
        if rec.band is None:
            stats["unclassified"] += 1
            unclassified_by_bank[rec.bank] += 1
        else:
            by_band[rec.band.value] += 1
        band = force_band if force_band is not None else rec.band
        for (kind, token), count in rec.tokens.items():
            # 단어는 표 어휘만 추출되므로 항상 매핑돼 있다 — 미매핑은 매크로·글리프에서만 생긴다.
            if token not in table.lookup[kind]:
                unmapped_counter[(kind, token)] += count
        if band is None:
            continue
        if band not in constructs_by_band:
            raise ValueError(f"밴드 {band.value!r}의 도입 구조 집합이 주입되지 않았다")
        judged += 1
        stats["judged"] += 1
        allowed = constructs_by_band[band]
        for (kind, token), count in rec.tokens.items():
            construct = table.lookup[kind].get(token)
            if construct is None:
                continue
            mapped += count
            stats["mapped"] += count
            mapped_by_band[band.value] += count
            if construct in allowed:
                in_range += count
                continue
            out_of_range += count
            stats["out_of_range"] += count
            slot = agg.setdefault((band.value, construct, token), [kind, 0, 0, []])
            slot[1] += count
            slot[2] += 1
            if len(slot[3]) < _EXAMPLE_LIMIT:
                slot[3].append(f"{rec.bank}/{rec.slug}")

    violations = tuple(
        sorted(
            (
                Violation(
                    band=key[0],
                    construct=key[1],
                    kind=slot[0],
                    token=key[2],
                    occurrences=slot[1],
                    records=slot[2],
                    examples=tuple(slot[3]),
                )
                for key, slot in agg.items()
            ),
            key=lambda v: (v.band, v.construct, -v.occurrences, v.token),
        )
    )
    new_violations = tuple(v for v in violations if v.key not in baseline)
    observed = {v.key for v in violations}
    resolved = tuple(sorted("/".join(k) for k in baseline if k not in observed))
    unmapped = tuple(
        UnmappedToken(kind=k, token=t, occurrences=n)
        for (k, t), n in sorted(unmapped_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return RangeReport(
        forced_band=force_band.value if force_band is not None else None,
        records_scanned=len(scan.records),
        records_by_band=dict(sorted(by_band.items())),
        records_unclassified=sum(unclassified_by_bank.values()),
        unclassified_by_bank=dict(sorted(unclassified_by_bank.items())),
        records_judged=judged,
        mapped_occurrences=mapped,
        mapped_by_band=dict(sorted(mapped_by_band.items())),
        in_range_occurrences=in_range,
        out_of_range_occurrences=out_of_range,
        violations=violations,
        new_violations=new_violations,
        baseline_resolved=resolved,
        unmapped=unmapped,
        unmapped_occurrences=sum(n for n in unmapped_counter.values()),
        source_stats=dict(sorted(source_stats.items())),
        source_rules=dict(sorted(scan.source_rules.items())),
    )


# ──────────────────────────────────────────────────────────────────────────
# 실행 (IO 오케스트레이션) — CLI(harness)가 구조 키 집합을 주입해 호출한다
# ──────────────────────────────────────────────────────────────────────────
def run_gate(
    *,
    corpus_root: Path,
    table_path: Path,
    baseline_path: Path,
    standards_path: Path,
    constructs_by_band: Mapping[SpeechGradeBand, frozenset[str]],
    force_band: SpeechGradeBand | None = None,
    aux_sources: Sequence[AuxSource] = (),
) -> RangeReport:
    """표·정본·베이스라인·코퍼스를 읽어 게이트를 한 번 돈다(hermetic·LLM 0·DB 0·결정론).

    `aux_sources`는 문항 코퍼스 밖의 보조 코퍼스다 — 기본은 비어 있고(합성 코퍼스 테스트가 보조
    코퍼스 없이 돌 수 있게), CLI가 `DEFAULT_AUX_SOURCES`를 넘긴다.
    """
    vocabulary = frozenset().union(*constructs_by_band.values())
    table = load_range_table(table_path, vocabulary=vocabulary)
    code_bands = load_standard_bands(standards_path)
    baseline = load_range_baseline(baseline_path)
    problem_paths = sorted(corpus_root.glob("problem_bank_*/problems.jsonl"))
    scan = scan_problem_banks(problem_paths, code_bands, words=table.word_tokens)
    scan_aux_sources(corpus_root, aux_sources, code_bands, words=table.word_tokens, scan=scan)
    return evaluate(scan, table, constructs_by_band, baseline, force_band=force_band)


# ──────────────────────────────────────────────────────────────────────────
# 리포트 렌더
# ──────────────────────────────────────────────────────────────────────────
def render_report(report: RangeReport) -> str:
    """사람 가독 요약 — 전수 통계·초과 표기·미매핑 건수·게이트 판정."""
    lines = [
        "=" * 64,
        "교육과정 표기 범위 게이트 (MATH-04) — 생성물 회계 전용(학생 입력 거부 아님)",
        "=" * 64,
        f"문항 {report.records_scanned}건 스캔 · 판정 {report.records_judged}건 · "
        f"미분류 {report.records_unclassified}건(판정 제외)",
        f"밴드 분포: {report.records_by_band}",
    ]
    if report.unclassified_by_bank:
        lines.append(f"미분류 은행: {report.unclassified_by_bank}")
    if report.forced_band is not None:
        lines.append(
            f"[변별력 대조군] 모든 문항을 '{report.forced_band}' 밴드로 강제 판정 "
            "— 고등이면 exit 0, 초등이면 exit 1이어야 측정기 정상."
        )
    lines.append(
        f"관측: 표에 있는 토큰 {report.mapped_occurrences}회"
        f"(도입 구조 안 {report.in_range_occurrences} · 초과 {report.out_of_range_occurrences}) · "
        f"표에 없어 판정 제외된 매크로·글리프 {report.unmapped_occurrences}회"
    )
    lines.append(f"밴드별 관측(표에 있는 토큰): {report.mapped_by_band}")
    lines.append("[코퍼스별 — 밴드 파생 규칙 · 레코드/판정/미분류 · 관측/초과]")
    for name, stats in report.source_stats.items():
        lines.append(
            f"  {name}: {stats['records']}/{stats['judged']}/{stats['unclassified']} · "
            f"{stats['mapped']}/{stats['out_of_range']}"
        )
        lines.append(f"    규칙: {report.source_rules.get(name, '(규칙 미기재)')}")
    if report.unobserved_bands:
        lines.append(
            f"[미관측 밴드: {', '.join(report.unobserved_bands)}] "
            "표의 토큰이 한 번도 관측되지 않았다 — 그 밴드의 '초과 0건'은 위반이 없다는 증거가 "
            "아니라 측정기가 보지 못했다는 뜻이다."
        )
    known = [v for v in report.violations if v not in report.new_violations]
    if known:
        lines.append(f"[초과 표기 — 베이스라인 내 {len(known)}건(리포트만·래칫)]")
        lines.extend(_violation_line(v) for v in known)
    if report.new_violations:
        lines.append(f"[신규 초과 표기 — 게이트 위반 {len(report.new_violations)}건]")
        lines.extend(_violation_line(v) for v in report.new_violations)
        lines.append(
            "  → 조치(콘텐츠는 삭제·수정하지 않는다): ①해당 문항의 밴드 판단을 사람이 검토 "
            "②의식적 수동 편집으로 베이스라인 등재(공백 인정)."
        )
    if not report.violations and report.forced_band is None:
        lines.append(
            "[정직 보고] 학년 초과 표기 0건 — 현 코퍼스에서 이 축은 위반을 잡지 않았다. "
            "증거 범위는 관측이 있는 밴드"
            f"({', '.join(report.mapped_by_band) or '없음'})에 한정된다. "
            "트립와이어로 유지한다(생성물이 상위 학년 표기를 들여오는 순간 작동)."
        )
    if report.baseline_resolved:
        lines.append(
            f"[베이스라인 해소 {len(report.baseline_resolved)}건 — 수동 편집으로 제거 검토]"
        )
        lines.extend(f"  {key}" for key in report.baseline_resolved)
    if report.unmapped:
        top = ", ".join(f"{u.token}×{u.occurrences}" for u in report.unmapped[:12])
        lines.append(f"[미매핑 토큰 {len(report.unmapped)}종 — 판정 제외·상위: {top}]")
    lines.append("[게이트 밖 기록 — 측정하지 못하는 것]")
    lines.extend(f"  - {spot}" for spot in KNOWN_BLIND_SPOTS)
    lines.append(f"게이트 판정(신규 초과 표기 0): {'PASS' if report.gate_ok else 'FAIL'}")
    lines.append("=" * 64)
    return "\n".join(lines)


def _violation_line(v: Violation) -> str:
    return (
        f"  [{v.band}] {v.token} → {v.construct} ({v.kind}) ×{v.occurrences}"
        f"/문항 {v.records}건 · 예: {', '.join(v.examples)}"
    )


def build_json_payload(report: RangeReport) -> dict[str, Any]:
    """JSON 리포트 페이로드 — 전 통계·초과 표기·미매핑·게이트 밖 기록."""
    return {
        "forced_band": report.forced_band,
        "gate_ok": report.gate_ok,
        "records_scanned": report.records_scanned,
        "records_judged": report.records_judged,
        "records_by_band": report.records_by_band,
        "records_unclassified": report.records_unclassified,
        "unclassified_by_bank": report.unclassified_by_bank,
        "mapped_occurrences": report.mapped_occurrences,
        "mapped_by_band": report.mapped_by_band,
        "unobserved_bands": list(report.unobserved_bands),
        "in_range_occurrences": report.in_range_occurrences,
        "out_of_range_occurrences": report.out_of_range_occurrences,
        "violations": [_violation_dict(v) for v in report.violations],
        "new_violations": [_violation_dict(v) for v in report.new_violations],
        "baseline_resolved": list(report.baseline_resolved),
        "unmapped": [
            {"kind": u.kind, "token": u.token, "occurrences": u.occurrences}
            for u in report.unmapped
        ],
        "unmapped_occurrences": report.unmapped_occurrences,
        "source_stats": report.source_stats,
        "source_rules": report.source_rules,
        "known_blind_spots": list(KNOWN_BLIND_SPOTS),
    }


def _violation_dict(v: Violation) -> dict[str, Any]:
    return {
        "band": v.band,
        "construct": v.construct,
        "kind": v.kind,
        "token": v.token,
        "occurrences": v.occurrences,
        "records": v.records,
        "examples": list(v.examples),
    }
