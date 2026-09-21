"""L6 응용 모드 6종 학생 도달 관측 카운터 — app.state 인프로세스 상태 (PB-04).

`problem_bank_gap_review_r2.md` §0-②-나·§3 R5: L6 응용 모드는 `api/gating.py`에 6개
엔드포인트(`/v1/gating/retake`·`/suneung`·`/school-progress`·`/thinking`·`/metacognition`·
`/gifted`)로 이미 구현돼 있지만, `src/mobile`·`src/web` 전수 grep에서 이 6개 경로를 호출하는
코드가 0건이다 — 학생 앱은 `GET /v1/me/next-problem`만 부르고 그마저도 `mode` 파라미터를
전송하지 않는다(`problems_api.dart`). 즉 6개 모드 전부 *학생 도달 0회*다. 이 카운터는 그 주장을
계속 검증 가능하게 만든다 — 지금은 6개 다 0이지만, 향후 클라가 실제로 특정 모드를 호출하기
시작하면 그 모드의 값만 그대로 올라간다(정적 감사 하나로 끝내지 않고 라이브 신호로도 이중 회계).

`api/_growth_evidence_state.py`(PED-06/PED-08)와 **병렬 구축**이지 재사용이 아니다 — 어휘도
의미도 다르다:
  - growth_evidence는 "요청 총량 1개"(어느 엔드포인트에 도달했는지는 슬롯 분리로만 구분)를 센다.
  - 이 모듈은 "6개 모드 중 *어느 모드*가 호출됐는가"를 모드별로 나눠 센다 — 단일 스칼라가 아니라
    모드 이름을 키로 하는 카운터 묶음이다. 기존 `GrowthEvidenceReachCounters`를 확장·재사용하면
    "요청 1건이 growth_evidence 도달인지 l6_mode_reach 도달인지"가 같은 카운터에 섞여, PED-06
    3상태 도달 리포트가 의존하는 "슬롯별 독립 관측" 전제를 깬다(그 모듈 docstring과 동일 원칙).

**의도적으로 하지 않는 것 — 사용자별 카운트**: 요청자 `user_id`를 메모리에 누적하지 않는다.
gating 6개 엔드포인트는 애초에 인증 게이트가 없어(`Depends(get_session)` 기반 candidates dep만
주입) 요청자 식별자 자체가 핸들러 안에 없다. "모드별 도달 건수"는 요청 수로 근사한다 — 설령
식별자가 있었더라도 distinct user set을 메모리에 두는 것은 ①(가치가 낮음 — 지금은 0 대 0-아님만
증명하면 충분) ②(불필요한 식별자 누적, CLAUDE.md 미성년자 PII 최소화와 마찰) 양쪽 다 비용이
이득보다 크다(`_growth_evidence_state.py` 모듈 docstring과 동일 판단).
"""

from __future__ import annotations

from dataclasses import dataclass

# app.state 속성 키 — create_app이 앱 수명 동안 1개를 심고, api/gating.py·app.py(/health/ready)가
# 공유 조회한다(단일 출처). growth_evidence 키와 이름공간이 겹치지 않도록 접두어를 분리한다.
L6_MODE_REACH_COUNTERS_KEY = "l6_mode_reach_counters"

# L6 응용 모드 6종 — api/gating.py의 6개 엔드포인트와 1:1 대응(순서는 그 라우터 파일의
# 등장 순서를 따른다). 값 공간을 여기 한 곳에 고정해 두 모듈(카운터·라우터 배선)이
# 오타로 어긋나지 않게 한다.
RETAKE = "retake"
SUNEUNG = "suneung"
SCHOOL_PROGRESS = "school_progress"
THINKING = "thinking"
METACOGNITION = "metacognition"
GIFTED = "gifted"

_MODES: tuple[str, ...] = (
    RETAKE,
    SUNEUNG,
    SCHOOL_PROGRESS,
    THINKING,
    METACOGNITION,
    GIFTED,
)


@dataclass(frozen=True, slots=True)
class L6ModeReachSnapshot:
    """L6 응용 모드 6종 도달 관측의 불변 스냅샷 — `/health/ready` 노출 원천."""

    retake: int
    suneung: int
    school_progress: int
    thinking: int
    metacognition: int
    gifted: int


class L6ModeReachCounters:
    """L6 응용 모드 6종 도달 카운터 — 모드별 요청 1건당 1 증가(성공/실패 무관).

    `record(mode)`는 6개 모드 이름 중 하나만 받는다. 이 클래스의 유일한 호출부는
    `api/gating.py`의 6개 핸들러(고정 문자열 리터럴로 호출)이므로, 잘못된 mode 이름은
    *방어적으로 무시하지 않고* `KeyError`로 즉시 터뜨린다 — 오타가 있으면 그 핸들러를
    구현한 시점에 바로 드러나야지, 조용히 카운트가 안 되는 채로 넘어가면 "도달 0회"라는
    관측 자체가 거짓이 된다(CLAUDE.md 침묵 실패 금지).
    """

    __slots__ = ("_counts",)

    def __init__(self) -> None:
        self._counts: dict[str, int] = dict.fromkeys(_MODES, 0)

    def record(self, mode: str) -> None:
        """모드 1건이 해당 gating 엔드포인트 핸들러에 도달했다(응답 이전 — 성공 가정 무관).

        `mode`가 6개 값공간 밖이면 `KeyError`를 던진다(방어적 무시 금지 — 내부 호출부만
        쓰므로 오타는 개발 시점에 바로 터져야 한다).
        """
        if mode not in self._counts:
            raise KeyError(
                f"알 수 없는 L6 모드 '{mode}' — 값공간은 {sorted(_MODES)}뿐이다 "
                "(api/gating.py 핸들러의 record() 호출 인자를 확인하라)."
            )
        self._counts[mode] += 1

    def snapshot(self) -> L6ModeReachSnapshot:
        """현재 카운터의 불변 스냅샷 — `/health/ready` 렌더용."""
        return L6ModeReachSnapshot(
            retake=self._counts[RETAKE],
            suneung=self._counts[SUNEUNG],
            school_progress=self._counts[SCHOOL_PROGRESS],
            thinking=self._counts[THINKING],
            metacognition=self._counts[METACOGNITION],
            gifted=self._counts[GIFTED],
        )


def set_l6_mode_reach_counters(
    app_state_holder: object,
    counters: L6ModeReachCounters,
    *,
    key: str = L6_MODE_REACH_COUNTERS_KEY,
) -> None:
    """app(또는 app.state 보유 객체)에 카운터를 저장 — create_app이 부팅 시 호출."""
    app_state_holder.state.__setattr__(key, counters)  # type: ignore[attr-defined]


def get_l6_mode_reach_counters(
    app_state_holder: object, *, key: str = L6_MODE_REACH_COUNTERS_KEY
) -> L6ModeReachCounters:
    """app.state에서 카운터를 꺼낸다 — create_app 경유 앱이면 항상 존재(미설정은 버그)."""
    counters: L6ModeReachCounters = getattr(app_state_holder.state, key)  # type: ignore[attr-defined]
    return counters
