"""WH-1 튜터링 두뇌 — 프로덕션 LLM 정책(`LLMTutorPolicy`·G1).

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md`(도구 8종·§3.4 불변식)·
`docs/architecture/s1_e2e_vertical_slice_design.md`(S1-a). `wh1_loop.py`의 `TutorPolicy`
Protocol을 *프로덕션*으로 구현한다 — 지금까지 두뇌는 `ScriptedTutorPolicy`(테스트용)뿐이었다.

**정책의 유일한 책임은 "다음 교수학적 도구 선택"이다.** 상태·검증·기록·불변식 강제는 전부
하네스(`run_tutoring_turn`)가 소유한다(WH-S `run_solver` 선례 동형). 본 정책은:
  ① `TurnState`를 *비민감* 요약으로 압축(학생 원문·정답 원문은 프롬프트에 절대 넣지 않는다 —
     오개념은 id/한국어 라벨만, history는 kind/ok만),
  ② 8개 도구 명세 + WH-1 불변식(verify 의무·정답 억제·Polya 우선)을 시스템 프롬프트로 주고,
  ③ **L3 파이프라인 좌석(`Wh1LlmSeam`)을 경유**해 구조화 도구 선택을 받고(직접 Anthropic/Ollama
     호출 금지·CLAUDE.md),
  ④ JSON(`{"kind": ..., ...}`)을 8개 `Action` 중 하나로 매핑한다(Pydantic 판별 유니온 재사용).

**민감 인자 격리(요구사항 ⑥의 핵심).** `match_misconception`의 학생 원문·`verify_step`의 풀이
단계는 *LLM 출력이 아니라 정책이 생성 시 주입받아 사적으로 보유한 값*으로 채운다. LLM은 "어떤
도구를 쓸지"(kind)와 개념 id·극성 같은 *비민감 스칼라*만 고른다. 따라서 학생 원문·정답은
프롬프트에도, LLM 출력 경로에도 실리지 않는다(L3 트레이스·캐시는 `Wh1LlmSeam`으로
결선돼 있다(OPS-36) — 프롬프트에 원문이 없으므로 트레이스·캐시 키에도 원문이 실릴 수 없다).

**불변식 이중 방어(프롬프트 + 코드).** 하네스가 불변식을 *최종* 강제하지만(정책이 어기면 거부),
정책도 선제적으로 존중한다:
  - **verify 의무**: `has_solution_steps and not verify_called`면 LLM이 end_turn을 내도 정책이
    `verify_step`으로 재지정(하네스의 end_turn 거부·루프 낭비 사전 차단).
  - **정답 억제(Polya 우선)**: `last_verdict`가 correct가 아니면(incorrect·unverifiable=오답·막힘)
    end_turn의 *명시 발화*를 제거하고 소크라테스 유도(질문/힌트/격려)로 강등 — 정답 노출
    발화를 막는다(CLAUDE.md "막혔을 때 바로 정답 금지"). 하네스의 개입 발화 결선이 대신 말한다.
    이는 하네스 `_end_turn_utterance`의 *최종* 정답 억제 백스톱(정책 무관)과 이중 방어를 이룬다 —
    정책이 선제 존중하되, 어떤 정책이 어겨도 하네스가 명시 발화를 버려 정답이 학생에게 닿지 않는다.

**안전 폴백(조용한 크래시 금지).** 파싱 실패·미지 kind·provider 오류는 크래시 대신 안전 액션으로
강등한다 — verify 의무가 걸려 있으면 `verify_step`, 아니면 `end_turn(격려)`. 학생 앞에서 루프가
죽지 않는다.

범위 밖(후속): S1-b(`/v1/coach` 엔드포인트를 하네스 경유로 전환하며 이 정책을 배선)·전략 계층
도구·fast path. 본 모듈은 *도구 선택 두뇌*만 둔다. `ScriptedTutorPolicy`는 존치(테스트용).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from pydantic import ValidationError

from whymath_backend.config import Settings
from whymath_backend.harness.wh1_llm_seam import Wh1Generation, Wh1LlmSeam
from whymath_backend.harness.wh1_loop import (
    _ANSWER_SUPPRESSED_VERDICTS,
    Action,
    CurateHypothesisAction,
    EndTurnAction,
    EndTurnType,
    LogEvidenceAction,
    MatchMisconceptionAction,
    QueryCurriculumAction,
    ReadStateAction,
    SelectProbeAction,
    TurnState,
    VerifyStepAction,
)
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.interfaces import CacheBackend, LLMProvider, TraceSink
from whymath_backend.l3.models import RoutingRequest
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.misconception.probe_selection import ProbeCandidate
from whymath_backend.l4.session_recall import SessionRecall

__all__ = ["LLMTutorPolicy"]

# ──────────────────────────────────────────────────────────────────────
# 시스템 프롬프트 — 도구 8종 명세 + WH-1 불변식 + 구조화 출력 계약.
# 학생 원문·정답은 여기에도, 사용자 프롬프트(상태 요약)에도 넣지 않는다(요구사항 ⑥).
# ──────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """당신은 WhyMath의 수학 튜터링 '두뇌'입니다. 당신의 유일한 역할은 이번 턴에
**다음 교수학적 도구 하나를 고르는 것**입니다. 학생에게 직접 말하거나 문제를 풀지 마세요 —
실행·검증·기록은 하네스가 합니다.

## 사용 가능한 도구 8종
1. read_student_state — 개념 노드 컨텍스트 조회. 필드: node_ids(개념 id 배열, 선택).
2. verify_step — 학생이 제출한 풀이 단계를 SymPy로 검증. 필드 없음(하네스가 단계를 보유).
3. match_misconception — 학생 풀이에서 오개념 후보를 탐지. 필드 없음(하네스가 원문을 보유).
4. curate_hypothesis — 활성 오개념 가설 세트를 감쇠·강화·정리. 필드: turns_elapsed(정수, 기본 1).
5. query_curriculum — 커리큘럼 관계 조회. 필드: node_id(문자열), relation(선수|후속|형제).
6. select_probe — 진단 문항 선택. 필드 없음(하네스가 후보 풀·θ를 보유).
7. log_evidence — 오개념 증거 적재. 필드: misconception_id(카탈로그 id), polarity(+1 지지/-1 반박),
   weight(실수, 선택).
8. end_turn — **유일하게 학생에게 말하는 도구**. 필드: action_type(질문|힌트|출제|격려),
   utterance(문자열, 선택 — 비우면 하네스의 소크라테스 개입 발화가 대신 말합니다).

## WH-1 불변식 (반드시 지킬 것)
- **verify 의무**: 학생이 풀이 단계를 제출한 턴(verify_obligation_pending=true)에는 end_turn 전에
  반드시 verify_step을 먼저 호출하세요. 검증 없이 턴을 끝내면 하네스가 거부합니다.
- **정답 억제·Polya 우선**: 학생이 막혔거나 검증이 unverifiable일 때 *정답을 바로 주지 마세요*.
  질문/힌트로 스스로 생각하게 유도하세요(소크라테스). end_turn의 utterance에 정답을 쓰지 마세요.
- **내부 도구는 침묵**: read/verify/match/curate/query/select/log는 학생에게 보이지 않는 내부
  동작입니다. 학생 발화는 오직 end_turn에서만 나옵니다.

## 출력 형식 (엄수)
JSON 객체 하나만 출력하세요. 다른 텍스트·설명·코드펜스 없이:
{"kind": "<도구명>", ...해당 필드}
예: {"kind": "verify_step"} · {"kind": "end_turn", "action_type": "질문"} ·
    {"kind": "curate_hypothesis", "turns_elapsed": 1}
"""

_ENCOURAGE_TYPE: EndTurnType = "격려"
_SOCRATIC_SAFE_TYPES: tuple[EndTurnType, ...] = ("질문", "힌트", "격려")

# ──────────────────────────────────────────────────────────────────────
# Minimal Reasoning Subgraph 예산(플레이북 Part 8·CLAUDE.md 하드 게이트·감사 Q2).
#
# "LLM에게 전체 그래프를 통째로 주지 마라 — 더 많이 넣을수록 더 멍청해진다"(Part 8). 이 정책의
# `_build_prompt`가 LLM에 컨텍스트를 실제로 주입하는 *첫 소비처*(S1-a)이므로, Part 8이 규정한
# 예산 상한(depth ≤ 2·max_nodes ≤ 12~20·max_tokens ≤ 3000)을 프롬프트 컨텍스트 크기에 코드로
# 박는다. depth는 현재 소비처가 그래프 traversal을 하지 않으므로(TurnState 요약만) 무관 —
# 아래 `_build_prompt` 주석의 traversal guard 유예 근거 참조.
# ──────────────────────────────────────────────────────────────────────
# 컨텍스트 노드 총합 상한(가설 + last_match). Part 8 max_nodes 상한(12~20)의 최댓값 20을 택함.
_MAX_CONTEXT_NODES = 20
# recent history 상한. Part 8 예산 안에서 최근 트레이스만 남기는 합리적 창(가설 5·노드 20보다
# 작게 잡아 어텐션 희석 방지). 인스턴스 `max_history`는 이 천장 안에서만 조절된다(min).
_MAX_HISTORY = 8
# 프롬프트 토큰 근사 상한. Part 8 max_tokens 상한을 그대로 채택. 외부 tokenizer 금지(경량 근사).
_MAX_PROMPT_TOKENS = 3000


class LLMTutorPolicy:
    """프로덕션 LLM 도구 선택 정책 — `TutorPolicy` Protocol 구현(G1).

    생성 시 이번 턴의 *민감 컨텍스트*(학생 원문·풀이 단계·진단 문항 후보)를 사적으로 주입받는다.
    `next_action`은 비민감 상태 요약으로 LLM을 호출해 도구를 고르고, 민감 인자는 LLM이 아니라
    보유한 컨텍스트로 채운다(원문 미노출). provider는 주입 가능(테스트=FakeProvider)하며 미주입
    시 표준 `CompositeProvider`(Ollama+Anthropic)를 구성한다(app.py 패턴 재사용).
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        cache: CacheBackend | None = None,
        trace: TraceSink | None = None,
        seam: Wh1Generation | None = None,
        settings: Settings | None = None,
        student_text: str = "",
        solution_steps: Sequence[str] = (),
        probe_candidates: Sequence[ProbeCandidate] = (),
        theta: float = 0.0,
        outside_mids: Sequence[str] = (),
        administered: Sequence[str] = (),
        subscription: str = "free",
        difficulty: str = "medium",
        max_history: int = 6,
        session_recall: SessionRecall | None = None,
    ) -> None:
        """정책 구성.

        Args:
            provider: L3 LLM provider(경유 필수). None이면 표준 CompositeProvider 구성.
            settings: 앱 설정(선택·후속 정책 튜닝 좌석). 지금은 보관만.
            student_text: 학생 풀이 원문 — **LLM 프롬프트에 넣지 않고** match_misconception 인자로만
                사적 사용(요구사항 ⑥).
            solution_steps: 학생 풀이 단계 — **프롬프트에 넣지 않고** verify_step 인자로만 사용.
            probe_candidates·theta·outside_mids·administered: select_probe용 진단 컨텍스트(비민감).
            subscription·difficulty: L3 라우팅 신호(도구 선택 호출의 비용·크기 결정용).
            max_history: 프롬프트에 요약할 최근 도구 트레이스 개수.
            session_recall: 직전 세션의 교수 이력(PED-04 D1 reader ②·**메타 한정**). 필드가
                전부 enum/정수라 학생 원문을 실을 자리가 타입상 없다. None(기본)이면 요약에
                키 자체가 없어 프롬프트가 기존과 바이트 동일.
        """
        # 좌석 조립(OPS-36) — 여기서부터 LLM 호출은 `l3.pipeline` 경유다(라우터·캐시·관측).
        # `seam`이 주어지면 그것을 쓴다(대체 가능성을 타입으로 — 테스트·미래 파이프라인 교체).
        self._seam: Wh1Generation = (
            seam if seam is not None else Wh1LlmSeam(provider=provider, cache=cache, trace=trace)
        )
        self._settings = settings
        self._student_text = student_text
        self._solution_steps = list(solution_steps)
        self._probe_candidates = list(probe_candidates)
        self._theta = theta
        self._outside_mids = list(outside_mids)
        self._administered = list(administered)
        self._subscription = subscription
        self._difficulty = difficulty
        self._max_history = max_history
        self._session_recall = session_recall

    # ── TutorPolicy Protocol ──────────────────────────────────────────
    async def next_action(self, state: TurnState) -> Action:
        """다음 도구를 고른다 — 상태 요약 → L3 provider → 파싱 → 불변식 이중 방어."""
        prompt = self._build_prompt(state)
        try:
            # 좌석 경유(OPS-36): 라우터 결정·캐시 조회/적재·Langfuse 기록이 전부 그 안에서
            # 일어난다. 도구 선택은 텍스트만 소비한다(usage는 좌석이 트레이스로 흘렸다).
            raw = await self._seam.generate(self._routing_request(), prompt, _SYSTEM_PROMPT)
        except Exception:  # noqa: BLE001 — provider 장애 시 학생 앞 크래시 금지·안전 강등.
            return self._safe_fallback(state)
        action = self._parse_action(raw, state)
        return self._enforce_invariants(action, state)

    # ── 상태 요약(비민감·Minimal Reasoning Subgraph 예산 적용) ──────────
    def _build_prompt(self, state: TurnState) -> str:
        """`TurnState`를 비민감 JSON 요약으로 압축 — 학생 원문·정답 원문 미포함(요구사항 ⑥).

        오개념은 id + 한국어 라벨(name_kr)만(원문 아님). history는 kind/ok만(detail 미포함 —
        detail에 문항 id 등 내부값이 있을 수 있어 요약에서 배제). last_matches도 id만.

        **Minimal Reasoning Subgraph 예산(Part 8·감사 Q2)을 여기서 강제한다.** 이 요약이 LLM에
        주입되는 *유일한* 컨텍스트이므로 팽창하면 어텐션이 희석돼 도구 선택이 나빠진다("더 많이
        넣을수록 더 멍청해진다"). 3중 상한을 적용한다:
          ① 컨텍스트 노드(가설+last_match) 총합 ≤ `_MAX_CONTEXT_NODES` — 초과 시 confidence
             내림차순 상위만 남기고 절단(가장 관련 높은 것 우선).
          ② recent history ≤ min(인스턴스 max_history, `_MAX_HISTORY`).
          ③ 프롬프트 토큰 근사 ≤ `_MAX_PROMPT_TOKENS` — 초과 시 추가 절단(history 먼저,
             그다음 저confidence 가설·마지막으로 match id).
        절단이 일어나면 **fail-closed 정직 신호**(`context_truncated`·`omitted_count`)를 요약에
        표기해 LLM이 "컨텍스트가 제한됐음"을 알게 한다(감사 §3·조용한 무동작 금지). 절단 순서는
        confidence·인덱스 등 결정론 기준만 사용(random/시각 금지).

        **traversal guard 유예 근거**: 현재 소비처는 `TurnState` 요약만 다루고 실제 그래프
        traversal을 하지 않는다(가설·매치·history는 이미 상위 계층이 채워 넣은 값). 따라서 visited
        set·timeout 같은 traversal guard는 *지금* 필요 없고, 없는 traversal에 가짜 guard를 만들지
        않는다. 향후 `query_curriculum`이 L1(개념 그래프)+L2 조인을 이 프롬프트로 실제 순회·주입하게
        배선될 때 visited set·timeout·token budget guard를 그 지점에 동반한다.
        """
        # ① 컨텍스트 노드 예산(가설+last_match 총합 상한, confidence 우선).
        hyp_summaries, match_ids, omitted = self._budget_context_nodes(state)
        # ② history 예산 — 인스턴스 조절값을 Part 8 천장 안으로 클램프.
        history_limit = min(self._max_history, _MAX_HISTORY)
        recent = [{"kind": r.kind, "ok": r.ok} for r in state.history[-history_limit:]]
        omitted += max(0, len(state.history) - history_limit)

        # ③ 토큰 근사 예산 — 초과 시 세션 회상부터, 그다음 history·저confidence 가설·match id를
        #    결정론 절단. 회상이 1순위인 이유: 세션 *간* 맥락은 이번 턴 결정에 가장 덜 급하다.
        recall = self._session_recall
        prompt = self._render_summary(state, hyp_summaries, match_ids, recent, omitted, recall)
        while self._approx_tokens(prompt) > _MAX_PROMPT_TOKENS:
            if recall is not None:
                recall = None
                omitted += 1
            elif recent:
                recent.pop(0)  # 가장 오래된 history 먼저
                omitted += 1
            elif hyp_summaries:
                # 저confidence 가설 절단(결정론: 최소 confidence, 동률이면 뒤쪽 인덱스).
                lo = min(
                    range(len(hyp_summaries)),
                    key=lambda i: (hyp_summaries[i]["confidence"], -i),
                )
                hyp_summaries.pop(lo)
                omitted += 1
            elif match_ids:
                match_ids.pop()  # 마지막 match id부터(결정론)
                omitted += 1
            else:
                break  # 고정 필드만 남아 더 줄일 수 없음(안전 탈출).
            prompt = self._render_summary(state, hyp_summaries, match_ids, recent, omitted, recall)
        return prompt

    def _budget_context_nodes(
        self, state: TurnState
    ) -> tuple[list[dict[str, object]], list[str], int]:
        """가설+last_match를 컨텍스트 노드로 보고 총합을 `_MAX_CONTEXT_NODES`로 제한.

        초과 시 confidence 내림차순 상위만 유지(가장 관련 높은 것 우선). 결정론 tiebreak은
        (kind_rank, 원본 인덱스) — random·시각 미사용. 생존자는 원본 순서로 렌더한다.
        반환: (가설 요약 리스트, match id 리스트, 절단된 노드 수).
        """
        # (confidence, kind_rank[0=가설,1=매치], 원본 인덱스) — 인덱스로 충돌·동률을 결정론 처리.
        scored: list[tuple[float, int, int]] = []
        for i, h in enumerate(state.hypotheses):
            scored.append((h.confidence, 0, i))
        for j, m in enumerate(state.last_matches):
            scored.append((m.confidence, 1, j))

        total = len(scored)
        if total <= _MAX_CONTEXT_NODES:
            keep_hyp = set(range(len(state.hypotheses)))
            keep_match = set(range(len(state.last_matches)))
            omitted = 0
        else:
            ranked = sorted(scored, key=lambda t: (-t[0], t[1], t[2]))[:_MAX_CONTEXT_NODES]
            keep_hyp = {t[2] for t in ranked if t[1] == 0}
            keep_match = {t[2] for t in ranked if t[1] == 1}
            omitted = total - _MAX_CONTEXT_NODES

        hyp_summaries = [
            self._hypothesis_summary(h) for i, h in enumerate(state.hypotheses) if i in keep_hyp
        ]
        match_ids = [
            m.misconception.id for j, m in enumerate(state.last_matches) if j in keep_match
        ]
        return hyp_summaries, match_ids, omitted

    @staticmethod
    def _hypothesis_summary(h: MisconceptionHypothesis) -> dict[str, object]:
        """가설 1건 → 비민감 요약(id + 한국어 라벨 + 반올림 confidence). 원문 미포함."""
        return {
            "id": h.misconception_id,
            "name": (
                CATALOG_BY_ID[h.misconception_id].name_kr
                if h.misconception_id in CATALOG_BY_ID
                else h.misconception_id
            ),
            "confidence": round(h.confidence, 3),
        }

    @staticmethod
    def _render_summary(
        state: TurnState,
        hyp_summaries: list[dict[str, object]],
        match_ids: list[str],
        recent: list[dict[str, object]],
        omitted: int,
        recall: SessionRecall | None = None,
    ) -> str:
        """예산 적용된 조각들로 최종 프롬프트 문자열을 조립(순수·결정론).

        `recall`(PED-04)은 **3축만** 싣는다 — 단계·전략·경과. `unresolved_hypothesis_ids`는
        의도적으로 제외한다: 활성 가설은 이미 `active_hypotheses`로 렌더 중이라 중복이고,
        오개념을 초기 context에 preload하지 않는다는 금기(CLAUDE.md)에도 걸린다. 그 필드의
        소비처는 warmstart `exclude_mids` 하나뿐이다.
        """
        summary: dict[str, object] = {
            "turn_index": state.turn_index,
            "has_solution_steps": state.has_solution_steps,
            "verify_called": state.verify_called,
            "last_verdict": state.last_verdict,
            "tool_calls": state.tool_calls,
            "active_hypotheses": hyp_summaries,
            "last_match_ids": match_ids,
            "recent_tools": recent,
            "verify_obligation_pending": state.has_solution_steps and not state.verify_called,
        }
        if recall is not None:
            summary["session_recall"] = {
                "last_polya_stage": (
                    recall.last_polya_stage.value if recall.last_polya_stage else None
                ),
                "last_strategies": [s.value for s in recall.last_socratic_strategies],
                "turns_since": recall.turns_since,
            }
        if omitted > 0:
            # fail-closed 정직 신호 — 예산으로 컨텍스트를 절단했음을 LLM에 명시(조용한 무동작 금지).
            summary["context_truncated"] = True
            summary["omitted_count"] = omitted
        state_json = json.dumps(summary, ensure_ascii=False, indent=2)
        return (
            "현재 튜터링 상태(요약·학생 원문/정답 미포함):\n"
            f"{state_json}\n\n"
            "위 상태에서 다음 도구 하나를 골라 JSON 하나로만 답하세요."
        )

    @staticmethod
    def _approx_tokens(text: str) -> int:
        """경량 토큰 근사 — 외부 tokenizer 금지(Part 8 예산은 정밀 회계가 아닌 상한 가드).

        문자수/4 근사. 한글은 문자당 토큰이 더 나올 수 있어 이 근사는 *과소 추정*일 수 있으나,
        1차 구조 가드는 노드·history 상한(①②)이 담당하고 토큰 가드는 팽창 방지용 보조 상한이다.
        """
        return len(text) // 4

    def _routing_request(self) -> RoutingRequest:
        """도구 선택 호출의 라우팅 신호 — 8개 중 택1은 *구조화 상태에 대한 분류 결정*이라
        task_type='classify'(→ GENERAL 패밀리·FAST 크기·LOCAL). 비용 0·저지연 즉답이 목표."""
        return RoutingRequest(
            task_type="classify",
            difficulty=self._difficulty,
            requires_reasoning=False,
            student_subscription=self._subscription,
            sync=True,
            # 등급: 이 프롬프트는 *구조화된 튜터링 상태 요약*이다 — `_build_state_prompt`가
            # "학생 원문/정답 미포함"을 계약으로 못박고 있어(같은 파일) 학생 저작물이 실리지
            # 않는다. 실리는 것은 우리 시스템이 만든 상태 JSON뿐 → 자체 저작(EOS-59).
            data_licenses=SELF_AUTHORED_CORPUS,
        )

    # ── 파싱·매핑 ──────────────────────────────────────────────────────
    def _parse_action(self, raw: str, state: TurnState) -> Action:
        """LLM 원시 출력 → Action. 파싱 실패·미지 kind·검증 실패는 안전 폴백(크래시 금지)."""
        data = self._extract_json(raw)
        if data is None:
            return self._safe_fallback(state)
        try:
            action = self._build_action(data)
        except (ValidationError, ValueError, KeyError, TypeError):
            return self._safe_fallback(state)
        if action is None:
            return self._safe_fallback(state)
        return action

    @staticmethod
    def _extract_json(raw: str) -> dict[str, object] | None:
        """원시 텍스트에서 JSON 객체를 관대하게 추출 — 코드펜스·주변 산문 허용."""
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        # 1차: 통째로 파싱
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        # 2차: 본문 속 첫 { … 마지막 } 구간만 파싱
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        return None

    def _build_action(self, data: dict[str, object]) -> Action | None:
        """파싱된 dict → 8개 Action 중 하나. 민감 인자(원문·단계·문항)는 정책 보유값으로 채운다.

        미지 kind면 None(→ 호출자가 안전 폴백). Pydantic 검증 실패는 예외로 전파돼 폴백된다.
        """
        kind = data.get("kind")

        if kind == "read_student_state":
            node_ids_raw = data.get("node_ids") or []
            node_ids = [str(n) for n in node_ids_raw] if isinstance(node_ids_raw, list) else []
            return ReadStateAction(node_ids=node_ids)

        if kind == "match_misconception":
            # 학생 원문은 LLM이 아니라 정책 보유값(프롬프트 미노출·요구사항 ⑥).
            return MatchMisconceptionAction(student_text=self._student_text)

        if kind == "curate_hypothesis":
            return CurateHypothesisAction(turns_elapsed=self._as_int(data.get("turns_elapsed", 1)))

        if kind == "verify_step":
            # 풀이 단계도 정책 보유값(프롬프트 미노출).
            return VerifyStepAction(steps=list(self._solution_steps))

        if kind == "query_curriculum":
            relation = data.get("relation", "선수")
            return QueryCurriculumAction(
                node_id=str(data["node_id"]),
                relation=relation,  # type: ignore[arg-type]  # 잘못된 값은 Pydantic이 거부→폴백
            )

        if kind == "select_probe":
            # 진단 문항 풀·θ는 정책 보유 컨텍스트(구조·비민감).
            return SelectProbeAction(
                candidates=list(self._probe_candidates),
                theta=self._theta,
                outside_mids=list(self._outside_mids),
                administered=list(self._administered),
            )

        if kind == "log_evidence":
            weight_raw = data.get("weight")
            weight = self._as_float(weight_raw) if weight_raw is not None else None
            return LogEvidenceAction(
                misconception_id=str(data["misconception_id"]),
                polarity=self._as_int(data["polarity"]),
                weight=weight,
            )

        if kind == "end_turn":
            return EndTurnAction(
                action_type=data["action_type"],  # type: ignore[arg-type]  # Literal 검증→폴백
                utterance=self._coerce_utterance(data.get("utterance")),
            )

        return None  # 미지 kind → 안전 폴백

    @staticmethod
    def _coerce_utterance(value: object) -> str | None:
        """utterance는 문자열 또는 None만 허용(그 외는 None으로 안전 강등)."""
        return value if isinstance(value, str) else None

    @staticmethod
    def _as_int(value: object) -> int:
        """JSON 값(object) → int. 변환 불가 타입은 ValueError로 폴백 유도."""
        if isinstance(value, (int, float, str)):
            return int(value)
        raise ValueError(f"정수로 변환 불가: {value!r}")

    @staticmethod
    def _as_float(value: object) -> float:
        """JSON 값(object) → float. 변환 불가 타입은 ValueError로 폴백 유도."""
        if isinstance(value, (int, float, str)):
            return float(value)
        raise ValueError(f"실수로 변환 불가: {value!r}")

    # ── 불변식 이중 방어(프롬프트에 이어 코드로도 강제) ──────────────────
    def _enforce_invariants(self, action: Action, state: TurnState) -> Action:
        """정책 레벨 방어 — 하네스 최종 강제에 앞서 선제 존중(루프 낭비·정답 노출 차단)."""
        # verify 의무: 풀이 제출 턴인데 미검증이면 end_turn을 verify_step으로 재지정.
        if (
            state.has_solution_steps
            and not state.verify_called
            and isinstance(action, EndTurnAction)
        ):
            return VerifyStepAction(steps=list(self._solution_steps))

        # 정답 억제(Polya 우선): correct가 아닌(incorrect·unverifiable=오답/막힘) end_turn은 명시
        # 발화를 제거하고 소크라테스로 강등. LLM이 utterance에 정답을 실었을 위험을 제거하고,
        # 하네스의 개입 발화 결선이 대신 말한다(하네스 백스톱과 이중 방어).
        if state.last_verdict in _ANSWER_SUPPRESSED_VERDICTS and isinstance(action, EndTurnAction):
            safe_type: EndTurnType = (
                action.action_type if action.action_type in _SOCRATIC_SAFE_TYPES else "질문"
            )
            return EndTurnAction(action_type=safe_type, utterance=None)

        return action

    def _safe_fallback(self, state: TurnState) -> Action:
        """안전 강등 — 조용한 크래시 금지. verify 의무가 걸리면 verify_step, 아니면 격려 종료."""
        if state.has_solution_steps and not state.verify_called:
            return VerifyStepAction(steps=list(self._solution_steps))
        return EndTurnAction(action_type=_ENCOURAGE_TYPE, utterance=None)
