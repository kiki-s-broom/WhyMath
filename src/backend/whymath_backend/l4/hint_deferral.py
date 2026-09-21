"""답 미루기 4단계 graded hint — 스펙 §"답 미루기 4단계"(L31-61) 정본.

`docs/architecture/04_pedagogy_engine.md` 참조. 스펙 L31-40 표 정본:
    1. 방향(가장 자주) — 어디로 가야 할지만
    2. 의사코드(좌절 시) — 단계의 흐름
    3. 부분 풀이(5회+ 막힘) — 일부 단계 시연
    4. 전체 풀이(마지막 수단) — 매우 드물게

규칙(스펙 L39): *가능한 가장 빠른 단계에서 멈춤*.

PRD `Hint` 정렬(스펙 L41-61): WhyMath 1~3단계 ↔ PRD 1~3, WhyMath 4단계는 PRD 척도 밖 안전망.
`reveals` 라벨은 *노출량* 추적(KPI: 세션당 평균).

후속 슬라이스(범위 밖): `prev_hint_level` 영속(L2 세션 모델)·LLM-judged 좌절 감지·학습자
정서 신호(`affect=frustrated`) 통합·답 미루기 KPI 집계.

**PED-35 정직한 공백**(acceptance②) — `STUCK_TURN_THRESHOLD=5`는 이번 태스크에서
*튜닝하지 않았다*(스펙 L37 값을 그대로 유지). 이 세션은 라이브 `wh1_evaluation`
세션 지표(도움 감소 곡선·이탈률)에 접근할 수 없어, 임계값 변경의 실측 근거를
만들 수 없다 — LearnLM 2407.12687 §5.5(과잉 유도 완화 근거)는 방향성 참고일 뿐
이 임계값에 대한 직접 측정이 아니다. 규칙 6은 *기존* 임계값의 보장을 복원할
뿐, 임계값 자체의 재보정은 라이브 세션 데이터가 있는 후속(SSM 파일럿 또는
전용 실측 태스크)으로 미룬다.

**PED-31과의 관계**(acceptance④) — `docs/architecture/04f_pedagogy_module_boundaries.md`
§102가 이미 명문화했듯, `decide_hint_level`의 단계 결정은 hint_deferral *고유
책임*이며 PED-31이 설계하는 전략 라이브러리(`PedagogyPack.fading_schedule` 등
strategy 단위 성공/실패 스트릭 기반 페이딩·해당 문서 갭 ⑩)와는 다른 층위다.
PED-31 문서가 그 갭의 후속으로 제안한 번호(문서 표의 "PED-36")는 실제
`backlog.py add`로 등재된 적이 없다(2026-09-11 실측 — `backlog/tasks/`에 해당
ID 파일 없음) — 이 태스크(PED-35)가 그 자리를 선점하거나 중복 설계하는 것이
아니라, 이미 존재하던 hint_deferral 내부 버그를 고친 것뿐이다.
"""

from __future__ import annotations

from typing import Literal, cast

from whymath_backend.l4.lthc.models import MasteryLevel

HintLevel = Literal[1, 2, 3, 4]
"""답 미루기 단계 — 스펙 L31-37. 4는 PRD 척도 밖 WhyMath 고유 안전망(L52)."""


# 단계별 `reveals` 라벨 — 스펙 L41-49 PRD 정렬표 + L50 ("`reveals`를 함께 기록").
# 라벨 자체는 *불투명 식별자*(텔레메트리·KPI 집계용); UI 표시는 후속(L5).
REVEALS: dict[HintLevel, str] = {
    1: "next_concept_to_focus",  # "다음에 *주목할 대상*만 가리킴 (개념·도구 이름)" — L47
    2: "step_flow",  # "풀이의 *단계 흐름*을 노출, 계산은 미노출" — L48
    3: "partial_steps_demo",  # "일부 단계를 *실제로 시연*" — L49
    4: "full_solution",  # "마지막 수단 — PRD 척도 밖, 학습 곡선 분석과 함께만" — L52
}


# 좌절 신호 — `docs/prompts/socratic_template.md` 시나리오 4(`affect=frustrated`).
# 학생이 *명시적*으로 막힘을 표현하는 토큰. 모호한 침묵·짧은 응답은 신호 아님(보수적).
FRUSTRATION_TOKENS: frozenset[str] = frozenset(
    {
        "모르겠",
        "막혔",
        # "어려"는 활용형(어렵·어려운·어려워) 공통 스템을 잡되, "어려서"(드뭄·수학 코칭 맥락 외)는
        # false-positive로 허용 — 토큰 경계 검사는 v2(LLM-judged 좌절 감지로 대체 예정).
        "어려",
        "막막",
        "헷갈",
        "잘 안",
        "도무지",
    }
)


# 답 요구 신호 — `docs/prompts/socratic_template.md` 시나리오 3("그냥 답 알려주세요").
# 답을 *직접* 요구하는 토큰. 응답은 답 미루기 발동 + 점진 hint_level 상승.
DEMAND_ANSWER_TOKENS: frozenset[str] = frozenset(
    {
        "답 알려",
        "답 좀",
        "그냥 답",
        "답이 뭐",
        "정답 알려",
        "정답이 뭐",
        "풀이 좀",
        "풀어줘",
    }
)


# 5회+ 막힘 임계값 — 스펙 L37 "3. 부분 풀이(5회+ 막힘)" 정본.
STUCK_TURN_THRESHOLD = 5


def has_any_token(text: str, tokens: frozenset[str]) -> bool:
    """`text`에 토큰이 하나라도 포함되는가(부분 문자열·순수).

    PED-04: `l4/turn_meta.classify_student_intent`가 *같은* 토큰셋으로 학생 의도를 분류하므로
    토큰셋 3종과 이 술어를 공개했다 — 좌절·답요구 신호의 진실원천을 둘로 쪼개지 않기 위함.
    """
    return any(t in text for t in tokens)


def decide_hint_level(
    *,
    student_input: str,
    turn_count: int,
    prev_hint_level: int | None,
    mastery_level: MasteryLevel | None = None,
) -> HintLevel:
    """다음 응답의 hint_level을 결정한다 — 스펙 L31-40 표 + L39 "가장 빠른 단계에서 멈춤".

    우선순위(보수적 — 모호 시 *낮은* 단계):
    1. `5회+ 막힘`(turn_count ≥ 5) → 최소 3(부분 풀이). prev 우선 유지(max).
    2. 답 요구 신호 → min(4, prev+1) — 점진 상승, 즉시 답 차단.
    3. 좌절 신호 → min(4, prev+1) — 점진 상승(socratic_template 시나리오 4).
    4. 그 외 → 1(방향, 가장 빠른 단계).
    5. `mastery_level`로 양방향 조정(slice 69 숙달·slice 77 초보·L2→L4·ZPD): '숙달'→max(1,
       base-1)(생산적 고투), '초보'→min(4, base+1)(능력 낮음→세분화). 발전중/None은 불변.
    6. **상한 도달 보장**(PED-35) — 규칙 1(5회+ 막힘)이 정한 최소 레벨 3을 규칙 5의 '숙달'
       완화가 다시 깎지 못하게 한다. 즉답(레벨4) 허용이 아니라 스펙 L37 "3. 부분 풀이(5회+
       막힘)" 종착 보장이다 — 규칙 5가 매 턴 재적용되고 그 결과가 다음 턴 `prev`로 그대로
       피드백되면서, '숙달' 학생은 5턴 이상 막혀도 레벨이 최대 2에서 고착됐다(실측 갭 —
       `docs/reviews/learnlm_pedagogy_prompting_review_2026-08.md` §4-2 인용). 규칙 6은
       규칙 1의 조건(turn_count ≥ 5)을 그대로 재사용해 그 보장만 복원한다 — 짧은 horizon의
       점진 상승(규칙 2·3)은 '생산적 고투' 취지대로 여전히 완화된다.

    `prev_hint_level=None`(새 세션·첫 결정) → 1 시작. 후퇴는 자동 없음(prev 이하로 안 내림은
    1·2 규칙에서 보장; 4의 기본 1 복귀는 의도된 디폴트 — 막힘 신호 사라지면 다시 은근하게).
    """
    prev = prev_hint_level if prev_hint_level is not None else 1
    text = student_input.strip()

    # 1. 5회+ 막힘 — 임계 우선(스펙 L37). prev∈[1,4] → max(prev,3)∈{3,4}.
    if turn_count >= STUCK_TURN_THRESHOLD:
        base: int = max(prev, 3)
    # 2·3. 답 요구(시나리오 3) 또는 좌절(시나리오 4) — 점진 상승, prev∈[1,4] → min(4,prev+1)∈[2,4].
    elif has_any_token(text, DEMAND_ANSWER_TOKENS) or has_any_token(text, FRUSTRATION_TOKENS):
        base = min(4, prev + 1)
    # 4. 기본 — 1(방향). 신호 사라지면 가장 은근한 단계로 복귀(생산적 막힘 우선).
    else:
        base = 1

    # 5. 능력 라벨 양방향 조정(slice 69 숙달·slice 77 초보·L2→L4·ZPD). 숙달→완화(생산적 고투)·
    #    초보→강화(세분화). [1,4] 클램프로 방향 힌트(1)·전체 풀이(4) 경계 유지. 발전중/None 불변.
    if mastery_level == "숙달":
        base = max(1, base - 1)
    elif mastery_level == "초보":
        base = min(4, base + 1)

    # 6. 상한 도달 보장(PED-35) — 규칙 1과 *같은 조건*을 재사용해, 규칙 5의 '숙달' 완화가
    # 그 최소 레벨(3)까지 깎지 못하게 한다. prev가 매 턴 이 함수의 반환값으로 피드백되므로
    # 완화 없이는 이 보장이 없다 — 실측 갭: turn_count≥5가 유지돼도 '숙달' 학생은 최대
    # 레벨 2에서 고착됐다(레벨 3 "부분 풀이"에 구조적으로 도달 불가).
    if turn_count >= STUCK_TURN_THRESHOLD:
        base = max(base, 3)

    return cast(HintLevel, base)


def is_answer_demand(student_input: str) -> bool:
    """학생 발화가 답 요구 토큰(`DEMAND_ANSWER_TOKENS`)을 포함하는가 — 힌트요청(demand) 트리거.

    `decide_hint_level`의 2번 규칙(답 요구→hint_level 상승)과 *같은 판정*을 재사용만 한다(재계산
    아님·상수 단일 출처). 좌절 신호(`FRUSTRATION_TOKENS`)는 포함하지 않는다 — "답을 달라"는
    명시적 요구만 demand로 집계한다(좌절은 별도 신호로 후속 고려·이번 태스크 범위 밖).
    """
    return has_any_token(student_input.strip(), DEMAND_ANSWER_TOKENS)


def is_stuck_turn_count(turn_count: int) -> bool:
    """5회+ 막힘 임계(`STUCK_TURN_THRESHOLD`) 도달 여부 — 막힘 이벤트 트리거.

    `decide_hint_level`의 1번 규칙(5회+ 막힘→hint_level 최소 3)과 *같은 임계*를 재사용한다.
    """
    return turn_count >= STUCK_TURN_THRESHOLD


def is_ceiling_reached(hint_level: int, turn_count: int) -> bool:
    """PED-35 acceptance③("작동한 비율") — 5회+ 막힘 상황에서 규칙 6의 상한(레벨 3)이
    실제로 *달성*됐는가.

    `decide_hint_level`이 반환한 `hint_level`을 그대로 넘겨 판정한다(재계산 아님) — 상한
    보장이 무작동 상태로 정상 응답에 섞여 위장되지 않도록(CLAUDE.md "작동한 비율" 원칙),
    호출측(리포트·텔레메트리 계층)이 세션 로그에서 `상한 도달률 = Σis_ceiling_reached /
    Σis_stuck_turn_count`를 집계할 수 있는 순수 훅만 제공한다. **정직한 공백**: 이 훅을
    실제 리포트에 배선하는 것은 이 태스크의 `paths`(hint_deferral.py + 테스트) 밖이라
    범위 밖으로 남긴다 — 정본화(이 함수)와 집행 지점(리포트 배선)을 혼동하지 않는다.
    """
    return is_stuck_turn_count(turn_count) and hint_level >= 3
