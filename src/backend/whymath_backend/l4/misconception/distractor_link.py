"""L4 오답 선택 인덱스 → 오개념 역방향 조회 (ASM-06 — REC-02의 반대 방향).

학생이 실제로 고른 객관식 보기 인덱스(`selected_choice_index`)를 문제의 `distractor_map`
(오답 선지→오개념 매핑, P3b·`schema.problem.DistractorEntry`)에 대조해 어떤 오개념이 이
오답을 유발했는지 역추적한다.

**방향 대비**:
  - `l4.misconception.distractor`(P3b 스캐폴드) 모듈 docstring이 예고한 "② 학생이 고른
    오답 선지를 오개념으로 역추적"을 실제로 결선하는 조회 모듈이다.
  - `l1.problem_bank.probe_candidates`(REC-02)는 *반대 방향* — 오개념 가설 집합에서
    출발해 그 오개념을 겨냥한 진단 문항 *후보*를 찾는다(가설→프로브). 이 모듈은 학생이
    이미 낸 답(선택 인덱스) 하나에서 출발해 오개념을 찾는다(응답→오개념).

**선행 조사 결론(스코프 확정·2026-08-11 r2 §3 D4 재확인)**: `student_answer`는 시스템 전
구간(자유텍스트)에서 "몇 번 보기를 골랐는가" 자체를 담지 않는다 — NLP-02 shadow 채점
(`harness/attempt_grading_shadow_report.py`)은 수치/기호식 검산 오프라인 배치이지 선택
인덱스를 포착하지 않는다. 선택 인덱스는 **클라이언트만 아는 사실**이라 요청 슬롯이 없으면
서버는 영원히 알 수 없다. 그래서 `selected_choice_index`가 두 학생 표면(`api/me.py`
`AttemptSubmitRequest` · `api/coach.py` `CoachRequest`)에 신규 슬롯으로 열렸고, 이 모듈은
그 값을 받아 오개념으로 옮기는 순수 변환만 담당한다(DB·I/O 0).

**단일 진실원천(ASM-06 승계 제약)**: 이 모듈은 *후보를 만들 뿐* 판정하지 않는다. 산출물은
기존 오개념 좌석 — 채점 경로는 `_scan_attempt_misconceptions`의 후보 집합에 합류해
`collect_assessment_evidence`·`apply_candidates`로, 코치 경로는 `_compute_matches` 결과와
합류해 `curate_hypothesis`로 흐른다. **별도 판정 경로·별도 응답 필드를 신설하지 않는다**
(이중 진실원천 금지). 그래서 이 모듈에는 영속·노출 코드가 한 줄도 없다.

**reactive retrieval(CLAUDE.md 협상 불가)**: `selected_choice_index`가 없으면(자유응답형·
클라 미전송) 즉시 비어 있는 결과를 돌려주고 `distractor_map`을 들여다보지도 않는다. 오개념
카탈로그도 *역추적된 id 하나*를 확인할 때만 건드린다 — 카탈로그 전체를 컨텍스트에 미리
싣지 않는다.

**형태만 본다(참조 무결성 재검증 아님)**: `l1.problem_bank.probe_candidates._match_probe_rows`
선례와 동형 — `distractor_map`은 DB JSONB 원값(list[dict])을 그대로 받는다(Pydantic
`DistractorEntry`로 재검증하지 않음). 원소가 매핑이 아니거나 `choice_index`/
`misconception_id`가 없으면 조용히 건너뛴다 — 여긴 학생 제출을 처리하는 라이브 경로라
콘텐츠 결함(형태 불량 원소)으로 요청 자체가 크래시하면 안 된다(참조 무결성 위반은 콘텐츠
생성 시점 게이트 `l4.misconception.validate.raise_for_distractor_map`이 잡아야 할 문제).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.match_gate import apply_match_quality_gate
from whymath_backend.l4.misconception.models import MisconceptionMatch
from whymath_backend.schema.assessment_evidence import MisconceptionCandidate

__all__ = [
    "DISTRACTOR_LINK_CONFIDENCE",
    "distractor_link_candidates",
    "distractor_link_matches",
    "resolve_misconception_from_choice",
]


#: 오답 선지 역추적 1건에 주는 진단 신뢰도.
#:
#: **왜 1.0이 아닌가**: 학생이 그 보기를 골랐다는 *사실*은 확실하지만, 그 선택이 매핑된
#: 오개념에서 비롯됐다는 *귀속*은 확실하지 않다 — 찍었거나 잘못 눌렀을 수 있다. ASM-06이
#: 승계한 제약("오답을 오개념으로 단정 금지 — distractor_map은 가설의 *근거*이지 판정이
#: 아니다")이 여기에 수치로 집행된다.
#:
#: **왜 0.65(품질 게이트 floor)보다 높은가**: 이 신호는 자유 텍스트 substring 매칭과 달리
#: ①문항별로 사람·저작 파이프라인이 *직접 적은* 매핑이고 ②학생의 선택과 **정확히 구조로**
#: 일치한다(근사 매칭 0). 텍스트 채널의 top-1보다 약하게 둘 이유가 없다.
#:
#: `_REFUTE_WEIGHT`(api/coach.py) 선례와 동형으로 **KPI 튜닝 대상 상수**로 노출한다. 이
#: 값을 게이트 floor 미만으로 내리면 아래 두 함수가 후보를 통째로 비우므로(게이트 ①),
#: 채널이 조용히 죽지 않고 테스트가 즉시 그것을 드러낸다.
DISTRACTOR_LINK_CONFIDENCE: float = 0.8


def resolve_misconception_from_choice(
    distractor_map: Sequence[Mapping[str, Any]] | None,
    selected_choice_index: int | None,
) -> str | None:
    """학생이 고른 보기 인덱스 → 그 오답을 유발한 오개념 id(있으면). 순수 함수(DB·I/O 0).

    Args:
      distractor_map: 이 문제의 오답 선지→오개념 매핑(`Problem.distractor_map` 원값). 각
        원소는 최소 `choice_index`(int)·`misconception_id`(str)를 갖는 매핑을 기대한다
        (`schema.problem.DistractorEntry.model_dump()`와 동형이나 raw dict도 그대로 허용).
        `None`이거나 빈 시퀀스면 매핑 없음 취급.
      selected_choice_index: 학생이 실제로 고른 0-기반 보기 인덱스(`Problem.choices` 위치).
        `None`이면 학생이 인덱스를 보고하지 않음(자유응답형 등) — `distractor_map`을 보지
        않고 즉시 `None`(reactive — 불필요한 순회 생략).

    Returns:
      일치하는 엔트리의 `misconception_id`. 다음은 모두 `None`이다: `selected_choice_index`가
      `None`·`distractor_map`이 비었거나 없음·학생이 *정답* 선지를 골라 매핑에 없음·일치하는
      엔트리의 `misconception_id`가 빈 문자열이거나 누락.

    `bool`은 파이썬에서 `int`의 서브클래스라 `True`가 인덱스 1과 같아진다 — 잘못 실린 불린이
    조용히 2번 보기로 해석되지 않도록 인덱스 타입을 엄격히 본다(무증상 오귀속 차단).
    """
    if selected_choice_index is None or isinstance(selected_choice_index, bool):
        return None
    if not distractor_map:
        return None
    for entry in distractor_map:
        if not isinstance(entry, Mapping):
            continue  # 형태 불량 원소 — 조용히 제외(참조 무결성은 생성 시점 게이트 소관)
        raw_index = entry.get("choice_index")
        if isinstance(raw_index, bool) or raw_index != selected_choice_index:
            continue
        misconception_id = entry.get("misconception_id")
        if not isinstance(misconception_id, str) or not misconception_id:
            return None
        return misconception_id
    return None


def distractor_link_matches(
    distractor_map: Sequence[Mapping[str, Any]] | None,
    selected_choice_index: int | None,
) -> list[MisconceptionMatch]:
    """역추적 결과를 L4 리치 타입으로 — 카탈로그 확인 + §3.3 품질 게이트 통과분만.

    두 단계로 좁힌다:
      1. **카탈로그 실재**: 역추적된 id가 `CATALOG_BY_ID`에 없으면 빈 목록. 하류
         (`apply_candidates`·`curate_hypothesis`)가 미등록 id를 *조용히 버리기* 때문에,
         여기서 걸러 두지 않으면 "후보 1건 산출"과 "가설 0건 반영"이 어긋난 채로 남는다.
      2. **품질 게이트**: `apply_match_quality_gate`를 *이 채널만의 단일 원소 목록*에
         적용한다. 텍스트 채널과 **같은 게이트 호출에 섞지 않는 것**이 핵심이다 — 섞으면
         이 채널의 높은 신뢰도가 top-1이 되어, 원래 floor에서 걸러졌어야 할 약한 텍스트
         후보까지 함께 통과시킨다(게이트 ①은 top-1 하나로 목록 전체를 판정한다). 채널마다
         따로 통과시킨 뒤 합치면 각 채널의 floor가 각자 정직하게 작동한다.

    게이트를 *재사용*하는 이유: `MisconceptionCandidate.gate_passed`는 "품질 게이트를
    통과했다"는 자기 기술이라, 통과 없이 True를 박으면 게이트가 우회 가능해진다(그 필드
    docstring의 계약). 신뢰도 상수가 floor 미만으로 바뀌면 여기서 빈 목록이 되어 채널이
    조용히 죽지 않는다.

    `ocr_confidence`는 넘기지 않는다 — 이 신호는 OCR 산출물이 아니라 UI 탭이라 게이트 ②
    (OCR low_quality)의 대상이 아니다(None=dormant가 사실이다).
    """
    misconception_id = resolve_misconception_from_choice(distractor_map, selected_choice_index)
    if misconception_id is None:
        return []
    misconception = CATALOG_BY_ID.get(misconception_id)
    if misconception is None:
        return []
    gated = apply_match_quality_gate(
        [MisconceptionMatch(misconception=misconception, confidence=DISTRACTOR_LINK_CONFIDENCE)]
    )
    return list(gated.matches)


def distractor_link_candidates(
    distractor_map: Sequence[Mapping[str, Any]] | None,
    selected_choice_index: int | None,
) -> tuple[MisconceptionCandidate, ...]:
    """역추적 결과를 채점 경로 계약 DTO로 — `distractor_link_matches`의 얇은 투영.

    채점 경로(Core)가 다루는 것은 L4 리치 타입이 아니라 계약 DTO(`MisconceptionCandidate`)
    이므로 여기서 한 번만 변환한다(게이트 재호출 0 — 위 함수가 이미 통과시킨 것만 온다).

    `low_quality`·`attribution_unclear`는 **False**다. 둘 다 *텍스트 입력*의 결함 축이라
    (OCR 인식 품질 · 풀이 산문 속 정정 어구의 귀속 불명) 선지 탭에는 대응물이 없다 —
    없는 결함을 있다고 표시하지 않는다.
    """
    return tuple(
        MisconceptionCandidate(
            misconception_id=match.misconception.id,
            confidence=match.confidence,
            gate_passed=True,
        )
        for match in distractor_link_matches(distractor_map, selected_choice_index)
    )
