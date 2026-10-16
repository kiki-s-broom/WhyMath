"""오개념 코퍼스 문장 무결성 — `canonical_statement` 절단 전수 검출 (QUAL-14 · 2026-10-12).

배경: 코퍼스(`data/corpus/misconceptions_v1/misconceptions.json`) 생성 단계의 문장 분리 결함으로
`canonical_statement` 76건(843건의 9.0%)이 문장 중간에서 잘려 있었다. 원인은 둘이다.

  ① **40자 절단**(71건): 문장이 40자에서 잘렸다. 대부분 조사·괄호가 열린 채 끝나지만, 우연히 `)`나
     `다`에서 끊겨 *완결형처럼 보이는* 3건(M0436·M0473·M0502)이 있다 — 종결 문자 검사만으로는 못 잡는다.
  ② **소수점 분할**(5건 · M0465~M0468·M0511): 문장 분리가 `0.3`의 소수점에서 끊어 `3/10을 0`처럼
     남겼다. 길이와 무관하므로 40자 기준으로는 잡히지 않는다.

가장 눈에 띈 것이 M0677('…교점으로 보는 관점을' — 서술어 없음)이다. 판정자 지적 12건이 여기서 나왔다.

**검출 원리 — 자기 증거**: 이 코퍼스는 `student_wrong_thinking`이 같은 문장을 서술어까지 담고 있다.
온전한 레코드 264건(swt가 canonical로 시작하고 canonical이 종결형)에서 `canonical == swt의 첫 문장`이
그대로 재현된다(정정 전 261/264, 불일치 3건이 위 숨은 절단). 그래서 "canonical이 swt 첫 문장의 *진부분*
이면 절단"이다 — 종결 문자·글자 수 같은 겉모양 추정이 아니라 레코드 자신의 증거다. swt가 없는 레코드
(109건)에는 증거가 없어 구조 신호(열린 괄호·매달린 조사)로만 본다.

**면제 — 단일 토큰 라벨**: `이항`·`공통인수`·`정사영`처럼 공백 없는 주제 라벨은 swt가 그 라벨로 시작해도
절단이 아니다(`이항` + `이항 시 부호 안 바꿈`). 절단 문장 76건은 전부 공백을 포함하고 라벨 3건은 전부
공백이 없다 — 길이 임계값보다 이 경계가 실측에 맞는다.

복원 규칙은 위 원리의 역이다(canonical := swt 첫 문장). 정정 근거·범위는 데이터 카드
`docs/data/misconception_catalog_v1.md`의 'QUAL-14' 절에 있다.

hermetic: DB 불요(코퍼스 JSON 스캔).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _REPO_ROOT / "data" / "corpus" / "misconceptions_v1" / "misconceptions.json"

#: swt가 canonical을 진부분으로 품는다 — 문장이 그 앞에서 잘렸다는 레코드 자신의 증거.
FRAGMENT = "fragment-of-wrong-thinking"
#: 여는 괄호가 닫히지 않았다(swt 없이도 보인다).
UNCLOSED = "unclosed-bracket"
#: 긴 서술이 목적격·연결 조사로 끝나 서술어가 없다(swt 없이도 보인다).
DANGLING = "dangling-particle"

#: 서술어 없이 끝나는 문장의 조사·어미. 명사 어미와 겹치는 것(이·가·의·에·로·도·만, 면·과·서)은 뺐다 —
#: '넓이'·'정의'·'단면'·'결과'로 끝나는 정상 명사구를 오탐하지 않으려는 것이다.
_DANGLING_ENDINGS = ("을", "를", "은", "는", "와", "으로", "에서", "고", "며")
#: 이 길이 미만은 서술 문장이 아니라 주제 라벨로 본다(조사 매달림 검사의 적용 하한).
_CLAUSE_MIN_LEN = 20


def first_sentence(text: str) -> str:
    """괄호 밖이고 소수점이 아닌 첫 마침표 앞까지(마침표 제외). 마침표가 없으면 전체."""
    depth = 0
    for index, char in enumerate(text):
        if char in "(（":
            depth += 1
        elif char in ")）":
            depth = max(0, depth - 1)
        elif char == "." and depth == 0:
            before = text[index - 1] if index > 0 else ""
            after = text[index + 1] if index + 1 < len(text) else ""
            if before.isdigit() and after.isdigit():  # 0.3 같은 소수점은 문장 끝이 아니다
                continue
            return text[:index]
    return text.rstrip(".")


def truncation_reasons(canonical: str, wrong_thinking: str | None) -> tuple[str, ...]:
    """canonical_statement가 잘렸다고 볼 근거들(없으면 빈 튜플)."""
    statement = canonical.strip()
    reasons: list[str] = []
    if wrong_thinking:
        sentence = first_sentence(wrong_thinking.strip())
        # 공백 없는 단일 토큰은 주제 라벨이다 — swt가 그 라벨로 시작해도 절단이 아니다
        if statement != sentence and " " in statement and statement in sentence:
            reasons.append(FRAGMENT)
    if statement.count("(") > statement.count(")"):
        reasons.append(UNCLOSED)
    if len(statement) >= _CLAUSE_MIN_LEN and statement.endswith(_DANGLING_ENDINGS):
        reasons.append(DANGLING)
    return tuple(reasons)


def _records() -> list[dict[str, object]]:
    document = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return list(document["misconceptions"])


def _by_id() -> dict[str, dict[str, object]]:
    return {str(r["mis_id"]): r for r in _records()}


# ── 코퍼스 전수 ────────────────────────────────────────────────────────────
def test_no_canonical_statement_is_truncated() -> None:
    """코퍼스의 `canonical_statement`가 하나도 잘려 있지 않다 — 새 레코드가 잘려 들어오면 red."""
    broken: list[str] = []
    for record in _records():
        reasons = truncation_reasons(
            str(record["canonical_statement"]), _optional_text(record["student_wrong_thinking"])
        )
        if reasons:
            tail = str(record["canonical_statement"])[-30:]
            broken.append(f"{record['mis_id']} {','.join(reasons)} …{tail}")
    assert not broken, (
        f"문장이 잘린 레코드 {len(broken)}건 — canonical_statement를 student_wrong_thinking의 "
        "첫 문장으로 복원한다(데이터 카드 QUAL-14 절):\n" + "\n".join(broken[:20])
    )


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def test_scan_is_not_vacuous() -> None:
    """전수 가드의 스캔 대상이 실재한다 — 0건을 훑고 통과하는 공허한 초록을 막는다.

    swt가 있는 레코드(검출의 증거가 되는 쪽)가 과반이어야 위 검출이 의미를 갖는다.
    """
    document = json.loads(_CORPUS.read_text(encoding="utf-8"))
    records = _records()
    assert len(records) == document["count"] >= 800
    with_evidence = [r for r in records if r["student_wrong_thinking"]]
    assert len(with_evidence) > len(records) // 2


def test_m0677_is_a_complete_sentence() -> None:
    """M0677 — 서술어('못 쓴다')까지 있고 swt의 첫 문장과 같다(판정자 지적 12건의 원인 해소)."""
    record = _by_id()["M0677"]
    statement = str(record["canonical_statement"])
    assert statement == "f(x)=k의 근의 개수를 그래프와 가로선 y=k의 교점으로 보는 관점을 못 쓴다"
    assert statement == first_sentence(str(record["student_wrong_thinking"]))


@pytest.mark.parametrize(
    ("mis_id", "starts_with"),
    [
        ("M0465", "0.1을"),
        ("M0466", "3/10을 0.3이"),
        ("M0467", "0.07을 0.7과"),
        ("M0468", "'자리 수가 많은 소수가 크다'고 여겨 0.45를"),
        ("M0511", "소수점 자리 수의 합을"),
    ],
)
def test_decimal_split_records_keep_their_decimal_point(mis_id: str, starts_with: str) -> None:
    """소수점에서 갈라졌던 5건 — 소수점 앞뒤 숫자가 한 토큰으로 되돌아와 있다(40자 기준으론 안 잡힌다)."""
    statement = str(_by_id()[mis_id]["canonical_statement"])
    assert statement.startswith(starts_with)
    assert re.search(r"\d\.\d", statement)


def test_hidden_cuts_that_look_complete_are_repaired() -> None:
    """40자에서 우연히 `)`·`다`로 끊겨 완결형처럼 보였던 3건 — 종결 문자 검사만으론 놓치는 쪽이다."""
    by_id = _by_id()
    assert str(by_id["M0436"]["canonical_statement"]).endswith("를 잘못 잡는다")
    assert str(by_id["M0473"]["canonical_statement"]).endswith("(양변이 같아야 함)")
    assert str(by_id["M0502"]["canonical_statement"]).endswith("같다고 본다")


# ── 검출기 단위(절마다 그 절의 반례) ───────────────────────────────────────
_M0677_CUT = "f(x)=k의 근의 개수를 그래프와 가로선 y=k의 교점으로 보는 관점을"
_M0677_SWT = _M0677_CUT + " 못 쓴다."


def test_first_sentence_does_not_split_on_decimal_points_or_inside_brackets() -> None:
    assert first_sentence("0.5를 1/2로 착각한다. 둘째 문장.") == "0.5를 1/2로 착각한다"
    assert first_sentence("몫을 구한다(예: 1.5로 나눔). 다음") == "몫을 구한다(예: 1.5로 나눔)"
    # 괄호 깊이 절의 반례 — 괄호 안 마침표가 숫자 사이가 아니라서 소수점 가드로는 걸러지지 않는다
    assert (
        first_sentence("몫을 구한다(예: 나눗셈. 단 0 제외). 다음")
        == "몫을 구한다(예: 나눗셈. 단 0 제외)"
    )
    assert first_sentence("마침표가 없는 문장") == "마침표가 없는 문장"
    assert first_sentence("끝에만 마침표가 있다.") == "끝에만 마침표가 있다"


def test_m0677_shape_fires_both_evidence_and_structure_clauses() -> None:
    """swt가 이어지는데 canonical이 조사에서 끊김 — 절단본은 두 신호가 함께 잡고 완결본은 안 잡는다(짝).

    `…관점을`은 swt 증거(FRAGMENT)로도, 서술어 없는 목적격 끝(DANGLING)으로도 잡힌다 — 한 신호가
    죽어도 다른 신호가 남는 이중 그물이다. 신호 하나씩의 단독 발동은 아래 절별 테스트가 따로 본다.
    """
    assert truncation_reasons(_M0677_CUT, _M0677_SWT) == (FRAGMENT, DANGLING)
    assert truncation_reasons(_M0677_SWT.rstrip("."), _M0677_SWT) == ()


def test_fragment_clause_detects_a_cut_that_looks_complete() -> None:
    """`다`로 끝나 종결형처럼 보여도 swt가 더 이어지면 절단이다(M0502 형태)."""
    cut = "한쪽에만 곱해 크기가 달라지는데도 같다"
    swt = cut + "고 본다."
    assert truncation_reasons(cut, swt) == (FRAGMENT,)
    assert truncation_reasons(cut + "고 본다", swt) == ()


def test_fragment_clause_detects_a_decimal_split_that_is_not_a_prefix() -> None:
    """소수점 분할로 앞 `0.`까지 잃어 swt의 접두조차 아닌 조각(M0467 형태) — 진부분 포함으로 잡는다."""
    swt = "0.07을 0.7과 같다고 보는 등 소수점 아래 자릿값을 무시한다."
    assert truncation_reasons("07을 0", swt) == (FRAGMENT,)
    assert truncation_reasons(first_sentence(swt), swt) == ()


def test_unclosed_bracket_clause_works_without_wrong_thinking() -> None:
    """swt가 없는 레코드도 열린 괄호는 보인다."""
    assert truncation_reasons("자릿값을 무시한다(실제로는 200+30+", None) == (UNCLOSED,)
    assert truncation_reasons("자릿값을 무시한다(실제로는 200+30+4)", None) == ()


def test_dangling_particle_clause_works_without_wrong_thinking() -> None:
    """swt가 없어도 긴 서술이 목적격으로 끝나면 서술어가 없다."""
    dangling = "그래프와 가로선의 교점으로 보는 관점을 이용해서 방정식의 근의 개수를"
    assert truncation_reasons(dangling, None) == (DANGLING,)
    assert truncation_reasons(dangling + " 센다", None) == ()
    # 적용 하한 — 짧은 라벨은 이 신호로 보지 않는다(증거가 부족하다)
    assert truncation_reasons("넓이를", None) == ()


def test_clean_controls_are_not_flagged() -> None:
    """정상 레코드 대조군 — 오탐 0. 라벨·다문장·소수·괄호·명사 어미가 전부 통과한다."""
    controls: list[tuple[str, str | None]] = [
        # 첫 문장 = canonical인 다문장 swt
        ("234를 그냥 읽어 자릿값을 무시한다", "234를 그냥 읽어 자릿값을 무시한다. 0을 빠뜨린다."),
        # 단일 토큰 라벨 — swt가 그 라벨로 시작해도 절단이 아니다
        ("이항", "이항 시 부호 안 바꿈"),
        ("공통인수", "공통인수 일부만 묶음"),
        # 소수점·닫힌 괄호를 품은 완결 문장
        ("0.5를 1/2로 착각한다(0.50은 같은 값)", "0.5를 1/2로 착각한다(0.50은 같은 값)."),
        # swt 없는 완결 문장·명사 어미 라벨(조사로 오인하기 쉬운 '식'·'락')
        ("log(a+b)를 log a+log b로 한다", None),
        ("약수·배수 혼동, 1과 자기자신 누락", None),
        ("절댓값 부등식 풀이에서 경우 나눔을 빠뜨리는 실수의 유형과 그 결과", None),
    ]
    for canonical, swt in controls:
        assert truncation_reasons(canonical, swt) == (), canonical
