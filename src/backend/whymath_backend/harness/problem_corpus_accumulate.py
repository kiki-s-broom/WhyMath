"""LLM 동등문제 코퍼스 *축적* 배치 CLI — 회차 간 dedup·증분 append(라이브 ops).

새 Phaiakes9 라이브 스모크(2026-07-07 실측·MEMORY)에서 확인된 갭을 상환한다: 스모크 스크립트는
실행마다 ① dedup index를 새로 만들고(회차 *간* 판박이 미차단) ② 산출 JSONL을 전면 교체했다
(축적 불가). 이 CLI는 **기존 코퍼스들의 canonical signature를 로드해 `run_batch`에 주입**하고,
수용분을 산출 파일에 **증분 append**한다 — 회차를 거듭할수록 코퍼스가 중복 없이 자란다.

동작:
  1. `--seed`(복수 가능) + `--out`(존재 시)의 전 레코드에서 signature·slug 집합을 로드.
  2. 생성기(run 함수는 좌석 무관 — LLM·스켈레톤 동일 계약)를 `run_batch`에 태움. 공유
     signature_index 덕에 기존 코퍼스와 구조가 같은 후보는 `rejected_duplicate`로 차단.
  3. 수용분 중 slug가 기존과 겹치는 건 스킵·리포트(멱등 upsert 키 충돌 방어 — 정상 경로에선
     signature dedup이 먼저 잡으므로 드묾), 나머지를 `--out`에 append.

main()은 라이브 전용(LLM 필요): `LLMEquivalentProblemGenerator`(provider=None→표준
CompositeProvider·Ollama)를 조립한다 — 이 환경(CI·LLM 0)에서 호출하면 provider 예외를
생성기가 안전 폴백(None)해 전건 `generation_failed`·exit 1로 정직 실패한다. hermetic 테스트는
`run_corpus_accumulate`에 결정론 스켈레톤 생성기를 주입해 축적·dedup 로직만 검증한다.

조성 루트 소관(주입 원칙): L4 정본(`CATALOG_BY_ID`)을 읽어 생성기에 오개념 라벨을 주입한다 —
L3 코드에는 L4 import 0(계층 규칙). harness는 import-linter 계약 밖(`problem_corpus_batch` 선례).

산출물은 v0(사람 검수 전) — 게이트 통과 ≠ 학생 노출(§03 정본). exit 코드: 신규 수용 ≥1이면 0,
아니면 1(코퍼스 무진전 신호 — 사유는 리포트의 outcome 집계로 관측·조용한 실패 금지).

생성 로그(EOS-55 집행 별항): 이 경로는 **기본으로** LLM 호출별 `GenerationLog`(모델·재현
좌석·입력 스냅샷 해시+참조)를 `<out>.genlog.jsonl`에 즉시 flush로 적재한다 —
`--generation-log`로 경로만 바꿀 수 있다(끄는 옵션 없음 — 적재가 기본이어야 "경로가
적재한다"가 참·정본화≠집행). `ops/hit_cu_metrics --generation-log`가 이 JSONL을 소비한다.

검수 큐(EOS-58 앵커 관통 + codex 리뷰 상환 — 2층 구조·genlog 동형): 비수용 outcome
(needs_review·rejected_*·generation_failed)은 종전엔 사유 문자열 샘플만 남고 휘발했다 — 사람
검수 큐(§03 "needs_review는 사람 검수로")의 입력이 라이브 LLM 경로에서 끊겨 있던 공백이다.
  1. **내구 큐** `<out>.review.jsonl` — 비수용 outcome 1건당 1행을 **발생 즉시 append+flush**
     한다(P2 — 장기 라이브 배치가 도중에 죽어도 그때까지의 기록이 남는다·genlog와 같은 규약).
     행에는 **후보 payload 전문**(코퍼스 레코드와 동일 직렬화 — 검수 승격 가능 형태)이 실려
     검수자가 문항·정답·해설을 행만으로 본다(P1-1 — 종전 워크리스트는 slug·점수·사유뿐이라
     실검수 불가였다). 후보가 없는 실패(generation_failed)는 사유만 정직 기록(본문 날조 금지).
  2. **워크리스트 뷰** `<out>.worklist.md` — 회차 메모리가 아니라 **내구 큐 전체**를 렌더한다
     (P1-2 — 같은 --out 반복 실행에서 이전 미해결 needs_review가 덮어쓰기로 소실되지 않고,
     전건 수용 회차도 기존 큐를 비우지 않는다). 같은 후보 재출현은 payload sha로 묶어 출현
     횟수를 표기한다. `--worklist-out`으로 뷰 경로만 바꿀 수 있다(끄기 없음 — 기본 기록이라야
     검수 큐 공급이 참·비수용 0건이어도 "관측했고 0건"을 기록). 무진전(exit 1) 회차에도
     기록한다(실패 증거 보존·2026-08-22 규칙).
범위 밖 별항(정본화≠집행): 해결(체크 완료) 추적·review_status 각인은 OPS-24 백필 소관이고,
**골든 승격 집행**은 `harness/golden_promotion_gate`(EOS-64 ③)가 경로를 강제한다 — 이 CLI의
계약은 "큐가 소실되지 않고 본문이 실린다"까지다.

회차 계측(EOS-64 ②④ — `harness/anchor_round_ledger`가 정본):
  - **작동한 비율** — 리포트 JSON에 `operating_rates`(outcome 6종 분포 + 방향별 Wilson 단측
    경계)를 싣는다. exit 0/1은 "이번에 붙었나"만 말하고 *어느 단계가 일했는지*는 말하지 않는다
    — 전건 generation_failed 회차와 "생성은 됐는데 게이트가 다 잡은" 회차는 exit 1로 같은 색인데
    조치가 정반대다. 분포가 그 둘을 가른다(CLAUDE.md "작동 신호 없는 알고리즘 부착 금지").
  - **회차 대장** — 회차 1건을 `<out>.rounds.jsonl` 사이드카에 즉시 append한다(genlog·검수 큐와
    같은 규약·끄기 없음). 이 대장이 없으면 연속 무진전이 영원히 "측정 불가"가 된다.
  - **회차 매니페스트**(MP-04) — 대장 행에 그 회차의 *구성*(프롬프트 버전·모델 핀 ID·카나리
    임계 3종·중단 감시 2종·시드 파일 sha256·CLI argv)과 *관측 판정*(카나리 통과·점추정·Wilson
    하한·차단/권고·중단 여부와 사유)을 함께 싣는다. 없으면 "지난주보다 수용률이 낮다"가 모델
    교체 때문인지 임계 변경 때문인지 대장만으로 갈리지 않는다(genlog 조인이 있어야 모델을 겨우
    안다). 두 묶음을 분리해 싣는 이유는 `anchor_round_ledger.RoundRecord` docstring 참조.
  - **연속 무진전 알람** — 최신 회차부터 연속으로 신규 행 0인 회차가 `--stagnation-window`
    (기본 3) 이상이면 알람이다. exit 2 + stderr 경고 + 리포트 `stagnation` 필드 3중으로 낸다 —
    stderr 한 줄만이면 습관화돼 소음이 되고(fail-open 상시 실패를 "보호 있음"으로 신뢰 금지),
    exit 코드라야 스케줄러·런북이 기계로 잡는다.

좌석별 생성 다양성 측정 계측(EOS-121 선결조건 B·C)
— 근거 문서 `docs/ops/eos121_seat_generation_diversity_precheck.md`:
  - **중복의 출처 구분**(B) — `rejected_duplicate` 한 이름에 원인도 처방도 다른 두 사건이 섞여
    있었다: *회차 내 중복*(이번 배치가 방금 만든 것과 겹침 = 생성 다양성 문제)과 *코퍼스 중복*
    (기존 자산과 겹침 = dedup 정상 동작). 상태 이름은 하위 호환으로 그대로 두고, 회차마다 새
    `RoundDedupScope`를 orchestrator에 주입해 **검출기(구조 signature/임베딩 과유사) × 출처
    (회차/코퍼스/혼재)** 2축을 기록한다. 집계는 리포트·대장의 `duplicate_sources`이고 개별 행은
    검수 큐가 싣는다. 이 구분은 **회차가 끝나면 복원할 수 없다** — signature 인덱스가 기존분과
    회차분이 섞인 한 덩어리가 되기 때문에, 회차 중에 기록하지 않으면 영영 없다.
  - **spec 순환**(C) — `--spec-file`(JSONL)을 주면 한 회차가 시도마다 spec을 번갈아 쓴다.
    결과는 `spec_outcome_counts`로 갈려 좌석 × spec 교차 집계가 선다. 미지정이면 종전대로
    단일 spec 1종(하위 호환).
  - **`--top-p`**(A의 CLI 배선) — 미지정이면 미전송(종전 동작 동일). **anthropic 좌석에서는
    지정할 수 없다**: Anthropic API가 temperature와 top_p의 동시 지정을 400으로 거부하는데
    저작 경로는 temperature(0.9)를 항상 싣는다. 그 조합이면 **호출 0건에서** exit 2로 거부한다
    (2026-09-19 라이브 회차에서 90호출 전건 400으로 죽은 뒤의 정정 — A의 원래 처방 "양 좌석에
    동일 명시 전송"은 API 제약상 불가능하다). openrouter·로컬 좌석은 둘을 함께 받는다.

exit 코드 3값: 0=신규 수용 ≥1 · 1=이번 회차 무진전 · 2=**셋 중 하나**(stderr가 어느 쪽인지 말한다)
  ⑴ 연속 무진전 알람 — 1보다 강한 신호(이번 회차만의 운이 아니라 구조적으로 막혀 있다)
  ⑵ spec 계획 파일 오류 — 회차가 시작조차 못 했다. 1로 내지 않는 이유: 1은 "돌았는데
     무진전"의 어휘라, 설정 오류를 거기 섞으면 "무엇을 고쳐야 하는가"가 사라진다.
  ⑶ `--top-p` × anthropic 좌석 충돌 — 호출 0건에서 거부한다(위 `--top-p` 항).
     좌석을 판독조차 못 한 경우도 여기 포함된다(모른다를 통과로 접지 않는다).

사용법(Phaiakes9·라이브):
    python -m whymath_backend.harness.problem_corpus_accumulate \\
        --seed <기존.jsonl> [--seed <추가.jsonl> ...] --out <축적.jsonl> --n 20 \\
        [--topic-hint "..."] [--standard-code "[10공수1-02-02]"] [--difficulty 2.5] \\
        [--spec-file <계획.jsonl>] [--top-p 0.95 — anthropic 좌석 제외] \\
        [--authoring-tier mid|quality] [--avoid-recent 10] [--canary-basis judged] \\
        [--generation-log <경로.jsonl>] [--worklist-out <경로.md>] [--stagnation-window 3]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from whymath_backend.config import get_settings
from whymath_backend.harness.anchor_round_ledger import (
    DEFAULT_STAGNATION_WINDOW,
    PromptCacheTally,
    RoundRecord,
    SeatTally,
    append_round_ledger,
    default_round_ledger_path,
    duplicate_source_rates,
    judge_stagnation,
    load_round_ledger,
    operating_rates,
    prompt_cache_rates,
    seat_operating_rates,
)
from whymath_backend.harness.batch_safety import (
    DEFAULT_ABORT_THRESHOLD,
    DEFAULT_ABORT_WINDOW,
    DEFAULT_CANARY_CONFIDENCE,
    DEFAULT_CANARY_SIZE,
    DEFAULT_CANARY_THRESHOLD,
    CanaryVerdict,
    RollingFailureWindow,
    evaluate_canary,
    is_accepted_status,
    is_neutral_status,
)
from whymath_backend.harness.needs_review_worklist import (
    ReviewQueueEntry,
    append_review_queue_jsonl,
    entry_from_outcome,
    load_review_queue_jsonl,
    render_review_queue_markdown,
)
from whymath_backend.harness.problem_corpus_batch import JsonlCorpusSink, _record_to_json
from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.generator import EquivalentProblemGenerator
from whymath_backend.l3.equivalent.orchestrator import (
    GenerationOutcome,
    RoundDedupScope,
    run_equivalent_generation,
)
from whymath_backend.l3.equivalent.orchestrator import (
    _to_record as _candidate_to_record,
)
from whymath_backend.l3.escalation_defaults import default_student_escalation_signals
from whymath_backend.l3.models import CostTier, RoutingRequest
from whymath_backend.l3.pregenerate.provenance_bridge import append_generation_log_jsonl
from whymath_backend.l3.providers.factory import cloud_model_pins, cloud_provider_name
from whymath_backend.l3.router import business_cost_tier
from whymath_backend.schema.provenance import GenerationLog

__all__ = [
    "AccumulateReport",
    "SpecSeat",
    "authoring_can_reach_cloud",
    "compute_dedup_input_digests",
    "default_generation_log_path",
    "default_round_ledger_path",
    "default_review_queue_path",
    "default_worklist_path",
    "load_corpus_index",
    "load_spec_plan_file",
    "main",
    "run_corpus_accumulate",
    "top_p_seat_precheck",
]

_LOGGER = logging.getLogger(__name__)

# 기본 topic 힌트 — 라이브 스모크(2026-07-07) 검증 문구. --topic-hint로 교체 가능.
_DEFAULT_TOPIC_HINT = "이차방정식 — 두 근 중 큰 근을 구하는 형태(답 하나)"
_DEFAULT_STANDARD_CODE = "[10공수1-02-02]"
_DEFAULT_DIFFICULTY = 2.5

#: 단일 spec 회차의 spec_id — spec 파일을 안 준 **하위 호환 경로**가 쓴다. 고정 문자열인 이유:
#: 값에서 파생하면(`--standard-code`+난이도 해시 등) 인자를 바꿀 때마다 대장의 집계 키가 갈려
#: 회차 간 비교가 끊긴다. 갈라야 할 때는 spec 파일로 명시 id를 주는 것이 계약이다.
_DEFAULT_SPEC_ID = "default"


@dataclass(frozen=True, slots=True)
class SpecSeat:
    """회차가 **순환시킬 spec 1종**과 그 spec을 태울 생성기(EOS-121 선결조건 C).

    왜 생성기가 spec과 **짝으로** 묶이는가 — `topic_hint` 때문이다. 이 값은 `EquivalenceSpec`
    필드가 아니라 `LLMEquivalentProblemGenerator` **생성자 인자**라(프롬프트 조립 시점에 박힌다)
    회차 루프 안에서 바꿀 자리가 없었다. 선택지는 둘이었다:

      ⓐ `topic_hint`를 `generate()` 호출 인자로 내린다 — `EquivalentProblemGenerator` 프로토콜
        (`generate(spec)`)을 바꿔야 하고, 그 프로토콜은 **스켈레톤 생성기 60여 종**이 구현한다.
        저작 주제 힌트는 LLM 생성기에만 의미가 있는데 전 구현체에 인자를 강요하게 된다.
      ⓑ **spec마다 생성기를 하나씩 둔다**(채택) — 프로토콜 무변경. 생성기는 provider를 지연
        구성하므로(`_build_live_generator`가 `None`을 넘긴다) 여러 개를 만들어도 실제 연결은
        쓰는 만큼만 생긴다. 같은 `topic_hint`면 **같은 인스턴스를 공유**하므로(main의 캐시)
        생성기가 들고 있는 지속 이벤트 루프(배치 격회 실패 방어)도 그대로 유지된다.

    ⓑ의 비용은 정직히 적는다: `topic_hint`가 서로 다른 spec은 각각 자기 이벤트 루프·자기
    provider 커넥션을 갖는다(spec 3종이면 최대 3벌). 180호출 규모에서 이 비용은 무시할 만하고,
    ⓐ가 요구하는 프로토콜 변경의 파급(60여 구현체)보다 훨씬 싸다.

    `spec_id`는 집계·조인 키다 — 회차 대장(`spec_outcome_counts`)·검수 큐 행(`spec_id`)이 이
    값으로 갈린다. 회차 안에서 **유일해야** 한다(중복이면 집계가 조용히 합산된다).
    """

    spec_id: str
    """집계·조인 키(회차 안 유일). 좌석 × spec 교차표의 spec 축."""

    spec: EquivalenceSpec
    """이 좌석이 요구하는 대응 명세(성취기준·난이도·답형태)."""

    generator: EquivalentProblemGenerator
    """이 spec을 태울 생성기. 같은 `topic_hint`를 쓰는 좌석끼리는 같은 인스턴스일 수 있다."""

    topic_hint: str | None = None
    """이 좌석의 저작 주제 힌트 — **기록용**이다(생성기에는 이미 박혀 있다).

    대장 행이 자족하려면 "이 spec이 어떤 힌트로 돌았나"가 남아야 한다. 생성기 내부 상태를
    꺼내 읽지 않고 좌석이 스스로 들고 있게 두는 쪽을 택했다(생성기 좌석 무관 유지).
    """


@dataclass(frozen=True, slots=True)
class AccumulateReport:
    """축적 배치 리포트 — 시도/수용/중복/검수/실패 + 파일 상태(조용한 실패 금지).

    `review_outcomes`(EOS-58)는 이 회차 비수용 GenerationOutcome 원본(후보+게이트 판정+사유)
    — 프로그램 소비용(batch `CorpusBatchReport.review_outcomes` 미러). 내구 영속은 리포트가
    아니라 `review_sink`(발생 즉시 append)가 소유한다 — 리포트는 회차 요약일 뿐이다.
    `run_id`는 이 회차 식별자 — 검수 큐 행(`ReviewQueueEntry.run_id`)과 조인하는 키.
    `to_json`엔 outcome 카운트만 싣는다(객체는 직렬화하지 않음).

    `to_json`의 `operating_rates`(EOS-64 ②)는 **작동한 비율** — outcome 6종 분포와 방향별
    Wilson 단측 경계다. 정상 응답·exit 0은 파이프라인이 일했다는 증거가 아니므로(CLAUDE.md
    "작동 신호 없는 알고리즘 부착 금지") 분포를 회차 리포트의 기본 필드로 싣는다. 계산은
    `anchor_round_ledger.operating_rates` 단일 원천(비율 산술을 여기서 재구현하지 않는다).
    """

    attempted: int
    accepted: int
    appended: int
    slug_conflicts: int
    outcome_counts: dict[str, int]
    seed_records: int
    existing_out_records: int
    out_path: str
    run_id: str
    reason_sample: list[str] = field(default_factory=list)
    review_outcomes: list[GenerationOutcome] = field(default_factory=list)
    #: 롤링 불량률 초과로 회차가 조기 중단됐는가(EOS-95 ③). 중단돼도 그 시점까지의
    #: 수용분은 append되고 비수용분은 검수 큐에 남는다 — 중단은 폐기가 아니다.
    aborted: bool = False
    #: 중단 사유(관측 불량률·창 크기·임계 포함). 중단이 없으면 None — 조용한 중단 금지.
    abort_reason: str | None = None
    #: 롤링 창의 최종 상태(관측 수·누적 불량·현재 비율). 감시가 돌았다는 *작동 신호*이며,
    #: 중단이 없어도 실린다 — "정상 응답 = 알고리즘이 일했다"가 아니기 때문이다.
    #: 이름이 인자 `abort_window`(창 *크기*)와 다른 이유: 이쪽은 창의 *상태*다.
    rolling_window: dict[str, Any] | None = None
    #: 카나리 판정(EOS-95 ①②) — 통과·미달 양쪽 다 실린다. 판정이 아예 없었으면 None
    #: (카나리 비활성 또는 n이 카나리 크기 이하라 막을 본배치가 없는 경우).
    canary: dict[str, Any] | None = None
    #: 카나리 미달로 본배치가 **시작되지 않았는가**. aborted(롤링 중단)와 구별한다 —
    #: 전자는 시작 전 차단, 후자는 진행 중 정지다.
    canary_blocked: bool = False
    #: 카나리 판정이 **권고**였는가(n <= canary_size라 막을 본배치가 없던 경우). 판정은
    #: 냈지만 차단력이 없었다는 뜻 — 이걸 안 적으면 운영자가 "게이트가 봐 줬다"고 오독한다.
    canary_advisory: bool = False
    #: 카나리 표본 기준(MP-02 재회차) — "attempts"(기본·종전)=앞머리 *시도* canary_size건,
    #: "judged"=중복을 뺀 *판정 대상*이 canary_size건 모일 때까지. 값이 달라지면 같은 카나리
    #: 수치의 뜻이 달라지므로 리포트에 함께 싣는다.
    canary_basis: str = "attempts"
    #: 카나리 판정이 내려진 시점까지 소비한 **시도 수**. attempts 기준이면 canary_size와 같고,
    #: judged 기준이면 중복만큼 더 크다 — 검수 구간(canary_slice)을 자를 때 이 값을 봐야 한다.
    canary_attempts: int | None = None
    #: 중복 출처 교차표 + **구분 장치가 실제로 작동한 비율**(EOS-121 선결조건 B·
    #: `anchor_round_ledger.duplicate_source_rates` 산출물 그대로 — 두 벌 산식 금지).
    #: `outcome_counts`와 **같은 층위**에 실린다: 저쪽이 "몇 건이 중복이었나"를 말하면
    #: 이쪽이 "그 중복이 무엇과 겹쳤나"를 말한다. 회차가 끝나면 복원 불가라 여기서 확정한다.
    duplicate_sources: dict[str, Any] = field(default_factory=dict)
    #: spec_id → outcome 상태별 건수(EOS-121 선결조건 C). 좌석 × spec 교차 집계의 spec 축 —
    #: 이것이 없으면 spec을 3종 돌려도 합산으로 뭉개져 "spec을 갈랐을 때 차이가 사라지는가"를
    #: 물을 수 없다(사전 실측 문서 §3의 대안 설명이 정확히 그 질문이다).
    spec_outcome_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    #: 이 회차가 순환시킨 spec 목록(`{spec_id, topic_hint, spec}` 전문) — 대장 행 자족용.
    spec_plan: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "accepted": self.accepted,
            "appended": self.appended,
            "slug_conflicts": self.slug_conflicts,
            "outcome_counts": self.outcome_counts,
            # 중복 출처(EOS-121 B)·spec 교차(C)는 outcome_counts 바로 옆에 둔다 — 세 값이
            # 같은 질문("이 회차가 무엇을 냈나")의 세 단면이라 떨어져 있으면 같이 안 읽힌다.
            "duplicate_sources": self.duplicate_sources,
            "spec_outcome_counts": self.spec_outcome_counts,
            "spec_plan": self.spec_plan,
            "seed_records": self.seed_records,
            "existing_out_records": self.existing_out_records,
            "out_path": self.out_path,
            "run_id": self.run_id,
            "reason_sample": self.reason_sample,
            "review_outcomes_count": len(self.review_outcomes),
            "operating_rates": operating_rates(self.outcome_counts, attempted=self.attempted),
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "rolling_window": self.rolling_window,
            "canary": self.canary,
            "canary_blocked": self.canary_blocked,
            "canary_advisory": self.canary_advisory,
            "canary_basis": self.canary_basis,
            "canary_attempts": self.canary_attempts,
        }


def load_corpus_index(paths: Sequence[Path]) -> tuple[set[str], set[str], int]:
    """기존 코퍼스들에서 (signature 집합, slug 집합, 총 레코드 수)를 로드.

    signature는 verify 메타(conditions·answer_selection)의 canonical 정규형 — 생성 배치의
    dedup 축과 동일 키라 주입 즉시 회차 간 중복이 차단된다. 정규화 불가(비다항)면 None이라
    집합에 안 실린다(그 문제군은 slug·임베딩 dedup에 위임 — 오케스트레이터 규약 동일).
    부재 경로는 건너뛴다(첫 축적 회차의 빈 out 허용).
    """
    signatures: set[str] = set()
    slugs: set[str] = set()
    total = 0
    for path in paths:
        if not path.exists():
            continue
        for record in load_problem_bank_records(path):
            total += 1
            slugs.add(record.slug)
            signature = canonical_signature(
                record.verify.conditions, record.verify.answer_selection
            )
            if signature is not None:
                signatures.add(signature)
    return signatures, slugs, total


def _append_records(path: Path, lines: list[str]) -> None:
    """JSONL append — 기존 내용 보존·신규 행만 덧붙임(전면 교체 아님·축적의 핵심)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")


def _queue_entry(
    outcome: GenerationOutcome, run_id: str, spec_id: str | None = None
) -> ReviewQueueEntry:
    """비수용 outcome → 내구 큐 행 조립(조성 루트) — payload = 코퍼스 레코드 동일 직렬화.

    후보가 있으면 저장 경로와 같은 변환(`_to_record`→`_record_to_json`)으로 전문을 싣는다 —
    검수 수용 시 그대로 코퍼스 행이 될 수 있는 승격 가능 형태(이중 직렬화 구현 금지). 후보
    없는 outcome(생성 실패)은 payload=None — `reasons`가 실패 사유를 말한다(본문 날조 금지).
    """
    payload: dict[str, Any] | None = None
    if outcome.candidate is not None:
        payload = _record_to_json(_candidate_to_record(outcome.candidate))
    return entry_from_outcome(outcome, run_id=run_id, candidate_payload=payload, spec_id=spec_id)


def _spec_plan_entry(seat: SpecSeat) -> dict[str, Any]:
    """좌석 1건 → 대장·리포트에 실을 spec 기록(해석된 값 전문·결정론 정렬).

    `model_dump(mode="json")`을 그대로 쓰는 이유: 여기서 필드를 손으로 베끼면
    `EquivalenceSpec`이 자랄 때 대장이 조용히 새 필드를 빠뜨린다(그리고 아무도 모른다).
    frozenset 필드는 직렬화 순서가 비결정이라 정렬한다 — 대장 행은 회차 간 *대조* 대상이고,
    같은 spec이 회차마다 다른 순서로 찍히면 눈으로도 기계로도 같은지 알 수 없다.
    """
    dumped = seat.spec.model_dump(mode="json")
    normalized = {
        key: (sorted(value) if isinstance(value, list) else value) for key, value in dumped.items()
    }
    return {"spec_id": seat.spec_id, "topic_hint": seat.topic_hint, "spec": normalized}


def _resolve_spec_seats(
    *,
    generator: EquivalentProblemGenerator | None,
    spec: EquivalenceSpec | None,
    spec_seats: Sequence[SpecSeat] | None,
) -> list[SpecSeat]:
    """호출 형태 2종을 좌석 목록 하나로 정규화(하위 호환 경로 보존·모호한 호출은 fail-loud).

    - **단일 spec**(종전 호출부 전부) — `generator`+`spec`을 주면 좌석 1건(`_DEFAULT_SPEC_ID`).
    - **spec 순환**(EOS-121 C) — `spec_seats`에 2종 이상을 준다.

    둘을 **함께** 주면 거부한다: 무엇이 돌았는지가 호출 형태만으로 결정되지 않고(순환에 끼나?
    무시되나?), 그 모호함은 회차 기록을 그대로 거짓으로 만든다. 빈 목록·중복 `spec_id`도
    거부한다 — 전자는 시도 0회로 조용히 끝나고, 후자는 집계 키가 겹쳐 두 spec의 결과가 한 칸에
    **합산**된다(구분하려고 만든 축이 스스로 뭉개지는 자리라 침묵으로 통과시키면 안 된다).
    """
    if spec_seats is not None:
        if generator is not None or spec is not None:
            raise ValueError(
                "spec_seats와 generator/spec을 함께 줄 수 없습니다 — 어느 쪽이 돌았는지가 "
                "호출 형태만으로 정해지지 않아 회차 기록이 거짓이 됩니다(둘 중 하나만)."
            )
        seats = list(spec_seats)
        if not seats:
            raise ValueError(
                "spec_seats가 비었습니다 — 돌릴 spec이 없습니다(시도 0회 무언 종료 금지)."
            )
        seen: set[str] = set()
        for seat in seats:
            if seat.spec_id in seen:
                raise ValueError(
                    f"spec_id가 중복입니다: {seat.spec_id!r} — 집계 키가 겹쳐 두 spec의 결과가 "
                    "한 칸에 합산됩니다(spec을 가른 의미가 사라집니다)."
                )
            seen.add(seat.spec_id)
        return seats
    if generator is None or spec is None:
        raise ValueError(
            "generator와 spec을 둘 다 주거나 spec_seats를 주어야 합니다 "
            f"(generator={generator is not None}, spec={spec is not None})."
        )
    return [SpecSeat(spec_id=_DEFAULT_SPEC_ID, spec=spec, generator=generator)]


def run_corpus_accumulate(
    *,
    out_path: Path,
    seed_paths: Sequence[Path],
    generator: EquivalentProblemGenerator | None = None,
    spec: EquivalenceSpec | None = None,
    spec_seats: Sequence[SpecSeat] | None = None,
    n: int,
    write: bool = True,
    review_sink: Callable[[ReviewQueueEntry], None] | None = None,
    run_id: str | None = None,
    abort_window: int | None = DEFAULT_ABORT_WINDOW,
    abort_threshold: float = DEFAULT_ABORT_THRESHOLD,
    canary_size: int | None = DEFAULT_CANARY_SIZE,
    canary_threshold: float = DEFAULT_CANARY_THRESHOLD,
    canary_confidence: float = DEFAULT_CANARY_CONFIDENCE,
    canary_basis: str = "attempts",
) -> AccumulateReport:
    """축적 1회차 — 기존 signature 주입 dedup + 수용분 증분 append(생성기 좌석 무관).

    `generator`는 좌석 계약만 요구한다(LLM·스켈레톤 동일) — 라이브 배선은 main() 소관이고,
    hermetic 테스트는 결정론 생성기를 주입해 축적 로직을 LLM 0으로 검증한다.

    `spec_seats`(EOS-121 선결조건 C): **한 회차 안에서 spec 여러 종을 순환**시킨다. 좌석 목록을
    주면 시도 i가 `spec_seats[i % len(spec_seats)]`를 쓴다 — 블록으로 몰아 돌리지 않고 **번갈아**
    가는 이유는 회차가 중간에 끊겼을 때(카나리 차단·롤링 중단) 표본이 한 spec에만 쏠리지 않게
    하기 위해서다. 좌석 개념·생성기 짝짓기 근거는 `SpecSeat` docstring 참조. `generator`+`spec`
    단일 호출(종전 전 호출부)은 그대로 동작한다 — 내부에서 좌석 1건으로 정규화된다.

    **출처 구분**(EOS-121 선결조건 B): 회차마다 `RoundDedupScope`를 **새로** 만들어
    orchestrator에 주입한다. 그래야 "이번 회차가 방금 만든 것과 겹침"(생성 다양성)과 "기존
    코퍼스와 겹침"(dedup 정상 동작)이 갈린다 — 둘은 원인도 처방도 다른데 종전에는 같은
    `rejected_duplicate`였다. 집계는 리포트 `duplicate_sources`가 싣는다.

    `review_sink`(EOS-58 codex P2 상환 — EOS-55 `generation_log_sink` 심 동형): 비수용 outcome
    1건마다 내구 큐 행(`ReviewQueueEntry`·후보 payload 전문 동반)을 **발생 즉시** 흘린다 —
    회차 루프 안에서 호출되므로 배치가 도중에 죽어도 그때까지의 검수 큐는 싱크가 영속한 만큼
    남는다(종료 일괄 기록 금지). 싱크 예외는 배치를 깨지 않되 **타입명**을 로그에 남긴다
    (never-break·침묵 실패 금지). None(기본)이면 종전 동작 그대로(기존 호출부 무영향).
    `run_id`는 회차 식별자(미지정 시 uuid4 hex) — 리포트·큐 행 양쪽에 실려 조인 축이 된다.

    `abort_window`·`abort_threshold`(EOS-95 ③): 최근 `abort_window`건의 불량률이
    `abort_threshold`를 **초과**하면 루프를 즉시 중단한다 — 결함이 대량 복제된 뒤에
    사후 게이트가 발견하는 것을 막는 비상정지다. 중단해도 **그 시점까지의 수용분은
    그대로 append되고 비수용분은 검수 큐에 남는다**(중단 ≠ 폐기 — 원인 분석 재료를
    버리지 않는다). `abort_window=None`이면 감시를 끈다(종전 동작).

    창이 다 차기 전에는 판정하지 않으므로 **`abort_window`보다 짧은 회차는 이 장치가
    한 번도 판정하지 않는다** — 그 구간의 보호는 아래 카나리 관문이 맡는다.

    `canary_size`·`canary_threshold`·`canary_confidence`(EOS-95 ①②): 회차 앞머리
    `canary_size`건을 카나리로 삼아, 그 지점에서 **Wilson 단측 하한 ≥ 임계**를 1회 판정한다.
    미달이면 남은 회차를 **시작하지 않고** 중단한다(`canary_blocked=True`). 카나리는 버리는
    표본이 아니라 이 회차의 앞부분이므로, 통과분은 그대로 코퍼스에 append된다.

    `n <= canary_size`면 막을 본배치가 없으므로 **차단하지는 않되 판정은 낸다**
    (`canary_advisory=True`) — 차단력 없는 권고다. 판정 자체를 생략하면 기본 경로
    (`--n 20` · 카나리 30)에서 아무 신호도 남지 않는다(2026-09-06 실측 사고).
    `canary_size=None`이면 관문을 완전히 끈다.

    `canary_basis`(MP-02 재회차): 카나리 표본을 무엇으로 세는가. "attempts"(기본·종전)는 앞머리
    *시도* `canary_size`건이다. 그런데 중복은 판정 분모에서 빠지므로
    (`batch_safety.NEUTRAL_STATUSES`) 중복이 많은 회차에서는 판정 대상이 크게 줄어,
    **품질과 무관하게 임계를 넘을 수 없게** 된다
    (2026-09-21 1차 회차: 30건 중 중복 20 → 분모 10 → 만점이어도 Wilson 하한 0.7871 < 0.90).
    "judged"는 **중복이 아닌 판정 대상이 `canary_size`건 모일 때까지** 카나리를 이어 가 표본 크기를
    보장한다. 임계·신뢰수준·중복 제외 규칙은 그대로이며 바뀌는 것은 *언제 판정하는가*뿐이다.
    전체 시도 상한은 여전히 `n`이라, 판정 대상이 모이기 전에 `n`이 소진되면 종전처럼 권고 판정만
    남는다(차단력 없음).
    """
    if canary_basis not in ("attempts", "judged"):
        raise ValueError(f"canary_basis는 attempts|judged여야 한다(받은 값 {canary_basis!r})")
    seats = _resolve_spec_seats(generator=generator, spec=spec, spec_seats=spec_seats)

    seed_signatures, seed_slugs, seed_total = load_corpus_index(list(seed_paths))
    out_signatures, out_slugs, out_total = load_corpus_index([out_path])

    # 공유 index — 기존(시드+축적분) 구조가 전부 실려 회차 간 판박이가 생성 단계에서 차단된다.
    signature_index: set[str] = seed_signatures | out_signatures
    known_slugs: set[str] = seed_slugs | out_slugs
    # 회차 장부(EOS-121 B) — **여기서 새로 만든다**. 이 인스턴스의 수명이 곧 "회차"의 정의라
    # (RoundDedupScope docstring) 호출자에게 받지 않는다: 받으면 호출자가 재사용했을 때 이전
    # 회차의 추가분이 조용히 `round`로 계상되고, 그 거짓은 아무 증상도 내지 않는다.
    #
    # **경계**: 위 `signature_index`는 이미 기존 코퍼스로 채워져 있고 이 장부는 비어 있다.
    # 즉 구분 기준은 "회차 시작 뒤 orchestrator가 추가한 것"이지 "코퍼스 파일에 있던 것"이
    # 아니다 — 후자는 orchestrator가 알 수 없다(호출자가 미리 채운 집합을 넘겨받을 뿐이다).
    round_scope = RoundDedupScope()

    resolved_run_id = run_id if run_id is not None else uuid.uuid4().hex
    sink = JsonlCorpusSink()
    # 종전 orchestrator.run_batch(n회 일괄) 대신 단건 조합을 회차 루프로 돈다 — 계약 동일
    # (같은 signature_index·store 공유)하되, 비수용 outcome을 **발생 즉시** 싱크로 흘릴 수
    # 있는 지점이 생긴다(P2 — outcome 리스트 완성 후 일괄 처리로는 중단 시 전부 잃는다).
    outcomes: list[GenerationOutcome] = []
    # 롤링 불량률 감시(EOS-95 ③) — None이면 감시 없음(종전 동작).
    watchdog = (
        RollingFailureWindow(window=abort_window, threshold=abort_threshold)
        if abort_window is not None
        else None
    )
    aborted = False
    abort_reason: str | None = None
    # 카나리 관문(EOS-95 ①) — 앞머리 canary_size건 시점에 1회만 판정한다. 막을 본배치가
    # 있을 때(n > canary_size)만 의미가 있고, 그 조건을 여기서 한 번에 좁혀 둔다(관문이
    # 없으면 None) — 루프 안에서 int|None 비교를 하지 않게 되고 조건이 한 곳에만 남는다.
    canary_gate_at: int | None = (
        canary_size if canary_size is not None and canary_size > 0 and n > canary_size else None
    )
    canary_verdict: CanaryVerdict | None = None
    canary_blocked = False
    canary_attempts: int | None = None
    # judged 기준의 진행 카운터 — 중립(중복) status를 뺀 판정 대상 수.
    judged_count = 0
    # 시도 순번 → spec_id(EOS-121 C) — 같은 인덱스로 outcomes와 짝지어 spec별 집계를 낸다.
    # 리스트로 쌓는 이유: 중단(카나리·롤링)으로 회차가 짧아져도 **실제로 돈 만큼만** 남아
    # 집계 분모가 부풀지 않는다(`attempted=len(outcomes)`와 같은 정직 집계 축).
    attempt_spec_ids: list[str] = []
    for index in range(n):
        # 순환(round-robin) — 좌석 1건이면 항상 같은 좌석이라 종전 동작과 동일하다.
        seat = seats[index % len(seats)]
        attempt_spec_ids.append(seat.spec_id)
        outcome = run_equivalent_generation(
            seat.spec,
            seat.generator,
            signature_index=signature_index,
            round_scope=round_scope,
            store=sink,
        )
        outcomes.append(outcome)
        if review_sink is not None and not is_accepted_status(outcome.status):
            try:
                review_sink(_queue_entry(outcome, resolved_run_id, seat.spec_id))
            except Exception as exc:  # noqa: BLE001 — 큐 적재 장애는 배치 비차단(타입명 로그)
                _LOGGER.warning("검수 큐 행 적재 실패(%s) — 배치 계속", type(exc).__name__)
        if watchdog is not None:
            watchdog.observe_status(outcome.status)
        if not is_neutral_status(outcome.status):
            judged_count += 1
        canary_progress = judged_count if canary_basis == "judged" else len(outcomes)
        if (
            canary_gate_at is not None
            and canary_verdict is None
            and canary_progress >= canary_gate_at
        ):
            canary_attempts = len(outcomes)
            canary_verdict = evaluate_canary(
                [item.status for item in outcomes],
                threshold=canary_threshold,
                confidence=canary_confidence,
            )
            if not canary_verdict.passed:
                # 본배치 미시작 — 여기서 끊으면 남은 n-canary_size건은 생성되지 않는다.
                canary_blocked = True
                _LOGGER.warning("%s — 본배치 미시작", canary_verdict.reason)
                break
        if watchdog is not None:
            if watchdog.should_abort():
                # 즉시 중단 — 아래 append·리포트 조립은 그대로 수행된다(수용분 보존).
                aborted = True
                abort_reason = watchdog.abort_reason()
                _LOGGER.warning("%s", abort_reason)
                break

    # 카나리가 *막을* 수 없는 크기(n <= canary_size)였어도 판정 자체는 낸다 — 차단력은
    # 없지만 "몇 건 중 몇 건이었는지"가 리포트에 남아야 운영자가 상태를 안다. 이것이 없으면
    # 기본 경로(--n 20 · 카나리 30)에서 canary=None만 보이고 아무 신호가 없다(2026-09-06 사고).
    canary_advisory = False
    if canary_verdict is None and canary_size is not None and canary_size > 0 and outcomes:
        canary_verdict = evaluate_canary(
            [item.status for item in outcomes],
            threshold=canary_threshold,
            confidence=canary_confidence,
        )
        canary_advisory = True
        canary_attempts = len(outcomes)
        if not canary_verdict.passed:
            _LOGGER.warning("[카나리 권고·차단력 없음] %s", canary_verdict.reason)

    counts: dict[str, int] = {}
    reasons: list[str] = []
    # 비수용 outcome 원본 보존(EOS-58) — 이 회차 요약(리포트)용. 내구 영속은 위 review_sink가
    # 이미 발생 즉시 수행했다(batch의 review_outcomes 포착 필터와 동일 기준).
    review_outcomes: list[GenerationOutcome] = []
    # spec × outcome 교차(EOS-121 C) — 좌석 전건을 **0으로 미리 깔아 둔다**. 한 번도 안 돈
    # spec(중단으로 순번이 안 왔거나 n < 좌석 수)이 키 자체로 사라지면 "돌았는데 전건 실패"와
    # "아예 안 돌았다"가 같은 화면이 된다(미측정 ≠ 0).
    spec_outcome_counts: dict[str, dict[str, int]] = {seat.spec_id: {} for seat in seats}
    # 중복 출처(EOS-121 B) — rejected_duplicate 전건의 (검출기, 출처)만 모은다.
    duplicate_pairs: list[tuple[str | None, str | None]] = []
    for attempt_index, outcome in enumerate(outcomes):
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        spec_bucket = spec_outcome_counts[attempt_spec_ids[attempt_index]]
        spec_bucket[outcome.status] = spec_bucket.get(outcome.status, 0) + 1
        if outcome.status == "rejected_duplicate":
            duplicate_pairs.append((outcome.duplicate_detector, outcome.duplicate_origin))
        if outcome.status not in ("accepted_stored", "accepted"):
            review_outcomes.append(outcome)
        if outcome.status != "accepted_stored" and outcome.reasons and len(reasons) < 10:
            reasons.append(outcome.reasons[0][:80])

    fresh_lines: list[str] = []
    slug_conflicts = 0
    for record in sink.records:
        if record.slug in known_slugs:
            slug_conflicts += 1  # 멱등 키 충돌 — append하면 중복 행이라 스킵(정직 집계).
            continue
        known_slugs.add(record.slug)
        fresh_lines.append(json.dumps(_record_to_json(record), ensure_ascii=False))

    if write and fresh_lines:
        _append_records(out_path, fresh_lines)

    return AccumulateReport(
        # 중단되면 실제 시도 수는 n보다 적다 — n을 그대로 쓰면 통과율 분모가 부풀어
        # "불량이 희석돼 보이는" 리포트가 된다(정직 집계).
        attempted=len(outcomes),
        accepted=counts.get("accepted_stored", 0),
        appended=len(fresh_lines) if write else 0,
        slug_conflicts=slug_conflicts,
        outcome_counts=counts,
        seed_records=seed_total,
        existing_out_records=out_total,
        out_path=str(out_path),
        run_id=resolved_run_id,
        reason_sample=reasons,
        review_outcomes=review_outcomes,
        aborted=aborted,
        abort_reason=abort_reason,
        rolling_window=watchdog.to_json() if watchdog is not None else None,
        canary=canary_verdict.to_json() if canary_verdict is not None else None,
        canary_blocked=canary_blocked,
        canary_advisory=canary_advisory,
        canary_basis=canary_basis,
        canary_attempts=canary_attempts,
        duplicate_sources=duplicate_source_rates(duplicate_pairs),
        spec_outcome_counts=spec_outcome_counts,
        spec_plan=[_spec_plan_entry(seat) for seat in seats],
    )


def compute_dedup_input_digests(paths: Sequence[Path]) -> dict[str, str | None]:
    """dedup 입력 경로 → 내용 sha256(hex) 매핑 — 회차 재현 계약의 *입력 지문*(MP-04 ①).

    **호출자가 dedup 입력 전부를 넘겨야 한다** — `--seeds`뿐 아니라 기존 `--out` 코퍼스까지다
    (`run_corpus_accumulate`가 `seed_signatures | out_signatures`로 인덱스를 만든다). 이 함수는
    받은 경로만 뜨므로, 무엇을 넘길지가 계약의 절반이다(PR #1013 Codex P1 — 초판이 seeds만
    넘겨 수용 판정에 쓰인 입력 하나가 대장에서 빠져 있었다).

    호출 **시점**도 계약이다: 배치가 out에 append하기 **전에** 떠야 한다. 뒤에 뜨면 이 회차의
    산출물이 섞여 "소비한 입력"이 아니라 "산출 후 상태"를 기록하게 된다.

    같은 CLI 인자로 다시 돌려도 입력 파일이 그 사이 자랐으면 dedup 인덱스가 달라져 결과가
    달라진다 — 그래서 재현 재료에는 경로 문자열이 아니라 **내용의 지문**이 필요하다.

    읽지 못한 경로(부재·권한·디렉터리)는 **키를 남기고 값만 None**으로 둔다: "그 경로를 dedup
    입력으로 주었는데 읽지 못했다"는 것도 관측이고(첫 회차의 아직 없는 out이 그 경우다), 키를
    지우면 인자에 있었다는 사실 자체가 사라진다 (날조 금지·미측정≠0). 실패는 삼키지 않고
    **예외 타입명**을 로그에 남긴다(침묵 실패 금지 — 파일 *내용*·경로 외 정보는 남기지 않는다).
    회차를 깨지 않는 관측 경로이므로 예외를 위로 올리지 않는다(대장 적재 실패와 같은 등급).
    """
    digests: dict[str, str | None] = {}
    for path in paths:
        key = str(path)
        try:
            hasher = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    hasher.update(chunk)
        except Exception as exc:  # noqa: BLE001 — 지문 계산 실패는 회차 비차단(타입명 로그)
            digests[key] = None
            _LOGGER.warning(
                "dedup 입력 지문 계산 실패(%s) — 경로 %s는 None=미기록으로 대장에 남는다",
                type(exc).__name__,
                key,
            )
        else:
            digests[key] = hasher.hexdigest()
    return digests


def _snapshot_observed_value(values: set[str]) -> str | None:
    """회차 전체에서 관측된 값 집합 → 대장 1칸(MP-04 ① `model_name`·`prompt_version`).

    0건이면 None=미기록(생성 호출이 없었던 회차 — 0이나 빈 문자열로 채우지 않는다). 1건이면
    그 값. **2건 이상이면 정렬 후 ','로 합친다** — 하나만 골라 적으면 그 행은 "회차가 단일
    모델로 돌았다"고 거짓말하게 되고, 회차 간 비교가 그 거짓 위에서 이뤄진다.
    """
    if not values:
        return None
    if len(values) == 1:
        return next(iter(values))
    return ",".join(sorted(values))


def default_generation_log_path(out_path: Path) -> Path:
    """생성 로그 기본 경로 — 축적 산출물 곁 사이드카 `<out>.genlog.jsonl`(항상 적재)."""
    return out_path.with_suffix(".genlog.jsonl")


def default_review_queue_path(out_path: Path) -> Path:
    """내구 검수 큐 기본 경로 — 축적 산출물 곁 사이드카 `<out>.review.jsonl`(append-only).

    genlog와 같은 규약(EOS-58 codex 상환) — 비수용 outcome이 발생 즉시 여기 영속돼야 라이브
    회차의 needs_review 후보가 소실되지 않는다. 워크리스트 md는 이 파일의 렌더 뷰다(정본은
    JSONL 행 — 뷰 경로는 `--worklist-out`으로 바꿔도 큐 저장소는 항상 이 사이드카다).
    """
    return out_path.with_suffix(".review.jsonl")


def default_worklist_path(out_path: Path) -> Path:
    """검수 워크리스트 기본 경로 — 축적 산출물 곁 사이드카 `<out>.worklist.md`(항상 기록).

    genlog 사이드카와 같은 규약(EOS-58) — 기본 기록이라야 라이브 회차의 needs_review 후보가
    사람 검수 큐로 반드시 흐른다(플래그를 잊으면 큐가 조용히 유실되는 설계 금지).
    """
    return out_path.with_suffix(".worklist.md")


def load_spec_plan_file(
    path: Path,
    *,
    default_standard_code: str,
    default_difficulty: float,
    default_topic_hint: str,
) -> list[tuple[str, EquivalenceSpec, str]]:
    """spec 순환 계획 파일(JSONL) → `[(spec_id, spec, topic_hint), ...]`(EOS-121 선결조건 C).

    형식 — **한 줄 1 spec**(JSON 객체). 빈 줄은 건너뛴다:

        {"spec_id": "quad-largest", "standard_code": "[10공수1-02-02]",
         "difficulty": 2.5, "topic_hint": "이차방정식 — 두 근 중 큰 근(답 하나)"}

    `spec_id`만 필수고 나머지는 CLI 단일 인자(`--standard-code`·`--difficulty`·`--topic-hint`)로
    폴백한다 — 힌트만 바꿔 3종을 돌리는 것이 가장 흔한 형태이기 때문이다.

    왜 **인자 반복**(`--standard-code A --standard-code B ...`)이 아니라 파일인가:
      ⑴ 축이 3개(코드·난이도·힌트)라 인자를 각각 반복시키면 **길이가 어긋날 때 조합이 모호**해
         진다(코드 3 × 난이도 2 = 곱인가 zip인가?). 파일은 한 줄이 곧 한 조합이라 모호함이 없다.
      ⑵ `spec_id`를 사람이 붙일 자리가 생긴다 — 집계·조인 키를 기계가 지어내면 회차 간 비교가
         인자 표기 변화에 깨진다.
      ⑶ 계획 전문이 회차 대장에 그대로 실려(`spec_plan`) 나중에 파일이 바뀌어도 행이 자족한다.

    **실패는 전부 fail-loud**(`ValueError`)다 — 이것은 측정 회차의 *설정*이고, 한 줄을 조용히
    건너뛰면 "spec 3종을 돌렸다"는 주장이 거짓이 된 채로 180호출이 나간다. 사유에는 줄 번호와
    예외 타입·필드명만 싣는다(원문 줄은 싣지 않는다 — 로더 관례 동형).
    """
    entries: list[tuple[str, EquivalenceSpec, str]] = []
    seen_ids: set[str] = set()
    # 인코딩은 `utf-8-sig`다 — 이 파일은 **사람이 손으로 만드는 유일한 입력**이고, Windows
    # PowerShell 5.1의 `Set-Content -Encoding utf8`이 UTF-8 **BOM을 붙인다**. `utf-8`로 읽으면
    # 첫 줄이 `\ufeff{...`가 되어 `JSONDecodeError: Unexpected UTF-8 BOM`으로 죽는다(2026-09-19
    # Phaiakes9 실측 — 파일럿 회차가 LLM 호출 0건에서 exit 2). `utf-8-sig`는 BOM이 없으면
    # `utf-8`과 동일하게 동작하므로 기존 파일에 회귀가 없다.
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"spec 계획 파일 {path} line {line_no}: JSONDecodeError — "
                    "한 줄 1 JSON 객체여야 합니다."
                ) from exc
            if not isinstance(raw, dict):
                raise ValueError(
                    f"spec 계획 파일 {path} line {line_no}: 객체가 아닙니다"
                    f"(받은 타입 {type(raw).__name__})."
                )
            unknown = set(raw) - {"spec_id", "standard_code", "difficulty", "topic_hint"}
            if unknown:
                # 오타 키를 조용히 무시하면 "난이도를 갈랐다"고 믿는 회차가 실제로는 한 난이도로
                # 돈다 — 설정 파일에서 가장 비싼 침묵이라 여기서 막는다.
                raise ValueError(
                    f"spec 계획 파일 {path} line {line_no}: 알 수 없는 키 {sorted(unknown)} — "
                    "허용 키는 spec_id·standard_code·difficulty·topic_hint입니다."
                )
            spec_id = raw.get("spec_id")
            if not isinstance(spec_id, str) or not spec_id.strip():
                raise ValueError(
                    f"spec 계획 파일 {path} line {line_no}: spec_id가 비었거나 문자열이 아닙니다 — "
                    "집계·조인 키라 기계가 지어낼 수 없습니다."
                )
            spec_id = spec_id.strip()
            if spec_id in seen_ids:
                raise ValueError(
                    f"spec 계획 파일 {path} line {line_no}: spec_id {spec_id!r}가 중복입니다 — "
                    "집계 키가 겹쳐 두 spec의 결과가 한 칸에 합산됩니다."
                )
            seen_ids.add(spec_id)
            standard_code = raw.get("standard_code", default_standard_code)
            difficulty = raw.get("difficulty", default_difficulty)
            topic_hint = raw.get("topic_hint", default_topic_hint)
            try:
                spec = EquivalenceSpec(
                    achievement_standard_codes=frozenset({str(standard_code)}),
                    target_misconception_ids=frozenset(),
                    difficulty_overall=float(difficulty),
                    answer_format=None,
                )
            except (ValidationError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"spec 계획 파일 {path} line {line_no}: spec 조립 실패"
                    f"({type(exc).__name__}) — difficulty는 1.0~5.0 실수여야 합니다."
                ) from exc
            entries.append((spec_id, spec, str(topic_hint)))
    if not entries:
        raise ValueError(
            f"spec 계획 파일 {path}에 유효한 줄이 0건입니다 — 돌릴 spec이 없습니다"
            "(빈 계획으로 조용히 단일 spec 회차가 되지 않게 fail-loud)."
        )
    return entries


# ──────────────────────────────────────────────────────────────────────────
# `--top-p` × 좌석 사전 거부 (EOS-121 라이브 정정 — 회차 시작 *전에* 막는다)
# ──────────────────────────────────────────────────────────────────────────
# 실측(2026-09-19): `--top-p 0.95`로 돈 anthropic 좌석 90호출이 **전건 400**으로 죽었다
# (`outcome_counts: {generation_failed: 90}`·`accepted: 0`·과금 0). 원인은 Anthropic Messages
# API가 `temperature`와 `top_p`의 **동시 지정**을 거부하는 것이고, 저작 경로는 temperature를
# 항상 싣는다(`llm_generator` 기본 0.9). 즉 이 조합은 시도 100%가 실패한다.
#
# 프로바이더에도 런타임 가드를 뒀지만(`providers/anthropic.py`) 그것만으로는 **90번 실패한다**
# — 실패가 싸려면 **호출 0건에서** 걸려야 한다. 그래서 이 CLI가 인자 검증 단계에서 막는다.
_ANTHROPIC_SEAT = "anthropic"
# 라우터가 쓰는 난이도 라벨 전집합 — spec의 difficulty(1~5)가 어느 라벨로 떨어지든 덮는다
# (`llm_generator._difficulty_label`). 한 라벨만 보면 안 된다: 예산이 CLOUD_HIGH 최소비용에
# 못 미치는 구성에서 "killer"는 LOCAL로 강등되지만 "hard"는 CLOUD_MID로 승급한다.
_ROUTING_DIFFICULTY_LABELS = ("easy", "medium", "hard", "killer")


def authoring_can_reach_cloud(subscription: str | None, budget_krw: float | None) -> bool:
    """이 회차의 라우팅 신호로 **클라우드 좌석에 닿을 수 있는가** — 라우터에게 직접 묻는다.

    `--subscription`·`--budget-krw` 미지정이면 생성기 기본값(free·0.0)이 쓰이고, 그 조합은
    라우터 규칙 1·2가 LOCAL로 강제한다 — 즉 anthropic 좌석은 아예 호출되지 않는다
    (`_build_live_generator` docstring: "클라우드 경로를 태우려면 **둘 다** 필요하다").
    그런 회차의 `--top-p`는 Ollama로 가므로 막으면 **과잉 차단**이다(로컬·openrouter 좌석은
    둘의 동시 지정이 가능하다 — 이 제약은 Anthropic 한정).

    판정을 여기서 다시 쓰지 않고 `l3.router.business_cost_tier`를 부르는 이유: 규칙을 사본으로
    베끼면 라우터가 바뀔 때 조용히 갈라진다(`ops.cost_probe`가 겪은 수동 미러 문제 — 그 함수의
    docstring이 이 목적으로 공개돼 있다). 법적 등급 게이트는 보지 않는데, 그 게이트는 **강등만**
    하므로 게이트 전 값을 쓰는 쪽이 보수적(= 더 잘 막는 방향)이다.

    난이도 라벨 4종을 **전부** 훑어 하나라도 클라우드면 True다 — spec 계획의 난이도가 어느
    라벨로 떨어질지 여기서는 모르고, 놓치는 쪽(= 90호출 태우는 쪽)이 훨씬 비싸다.
    """
    defaults = default_student_escalation_signals()
    resolved_subscription = (
        subscription if subscription is not None else defaults.student_subscription
    )
    resolved_budget = budget_krw if budget_krw is not None else defaults.budget_krw
    for difficulty in _ROUTING_DIFFICULTY_LABELS:
        request = RoutingRequest(
            # 저작 호출의 신호를 그대로 복제한다(`llm_generator._routing_request`).
            task_type="generate",
            difficulty=difficulty,
            requires_reasoning=True,
            student_subscription=resolved_subscription,
            budget_krw=resolved_budget,
            sync=True,
            # 등급 축도 저작 호출과 같게 둔다. `business_cost_tier`는 이 값을 보지 않지만
            # (등급 게이트는 그 뒤 단계다), 호출부가 등급을 선언하는 것이 이 저장소의 계약이고
            # `scripts/ops/check_routing_data_grade.py`가 전수로 강제한다 — 프로브라고
            # 비워 두면 "이 호출은 등급을 모른다"가 되어 계약이 조용히 갈린다.
            data_licenses=SELF_AUTHORED_CORPUS,
        )
        if business_cost_tier(request) is not CostTier.LOCAL:
            return True
    return False


def top_p_seat_precheck(
    *,
    top_p: float | None,
    seat: str,
    subscription: str | None,
    budget_krw: float | None,
) -> str | None:
    """`--top-p` × 좌석 조합이 **구조적으로 실패하는가** — 거부 사유 문자열 또는 None.

    None이면 통과다. 문자열이면 그 텍스트를 그대로 stderr에 내고 exit 2로 끝내면 된다
    (설정 오류는 0/1의 어휘가 아니다 — 0/1은 "회차가 돌았고 붙었나"를 말한다).

    거부 조건은 **세 개의 논리곱**이며 하나라도 빠지면 과잉 차단이다:
      ⓐ `--top-p`가 지정됐다 — 미지정이면 전송 자체가 없어 충돌할 것이 없다.
      ⓑ 좌석이 anthropic이다 — openrouter·로컬(ollama)은 둘의 동시 지정을 받는다.
      ⓒ 이 회차가 실제로 클라우드에 닿는다 — LOCAL 강제 회차의 top_p는 Ollama로 간다.

    ⓑ만 보고 막으면 **기본 좌석이 anthropic이라 로컬 회차 전부가 막힌다**(`config.py`의
    `cloud_provider` 기본값). 그래서 ⓒ가 대조군 축으로 반드시 함께 있어야 한다.
    """
    if top_p is None or seat != _ANTHROPIC_SEAT:
        return None
    if not authoring_can_reach_cloud(subscription, budget_krw):
        return None
    return (
        f"[좌석·인자 충돌] anthropic 좌석에서는 --top-p(받은 값 {top_p})를 쓸 수 없습니다 — "
        "Anthropic Messages API가 temperature와 top_p의 **동시 지정**을 400으로 거부하고"
        "(`temperature` and `top_p` cannot both be specified for this model), 동등문제 저작 "
        "경로는 temperature를 항상 싣습니다(기본 0.9). 즉 이 조합은 시도 100%가 실패합니다 "
        "— 2026-09-19 라이브 회차에서 90호출 전건 generation_failed로 실측됐습니다.\n"
        "처방 ①(권장) 이 좌석에서는 **--top-p를 빼고** 실행하세요. 각 공급사 기본값이 쓰이며, "
        "그것이 EOS-118 회차와 같은 조건입니다(좌석 간 대칭이되 통제되지는 않는 상태 — "
        "docs/ops/eos121_seat_generation_diversity_precheck.md §1).\n"
        "처방 ② top_p를 꼭 통제해야 한다면 좌석을 바꾸세요"
        "(WHYMATH_CLOUD_PROVIDER=openrouter) — openrouter는 두 인자를 함께 받습니다."
    )


def _build_live_generator(
    topic_hint: str,
    *,
    generation_log_sink: Callable[[GenerationLog], None] | None = None,
    subscription: str | None = None,
    budget_krw: float | None = None,
    top_p: float | None = None,
    authoring_tier: str = "mid",
    avoid_recent: int = 0,
) -> EquivalentProblemGenerator:
    """라이브 LLM 생성기 조립(조성 루트) — L4 카탈로그 라벨 주입·표준 CompositeProvider.

    이 함수만 LLM 경로를 안다 — 여기 격리해 run_corpus_accumulate는 좌석 무관을 유지한다.
    `generation_log_sink`(EOS-55): 호출별 GenerationLog(재현 좌석·입력 스냅샷)를 흘릴 싱크
    — main()이 JSONL appender를 배선한다(적재가 기본·정본화≠집행).

    `subscription`·`budget_krw`(EOS-99 PR #1023 codex P1): **둘 다 None이면 생성기 기본값**
    (단일 좌석 free/0.0)이라 종전 동작과 바이트 단위로 같다. 명시하면 그 값이 라우팅 신호로
    나간다 — 클라우드 경로를 태우려면 **둘 다** 필요하다(`business_cost_tier` 규칙1이 예산을,
    규칙2가 구독을 각각 LOCAL로 강제하고 `guard_cloud`가 한 번 더 본다). 하나만 열면 여전히
    LOCAL이고, 그러면 프롬프트 캐시 계측은 영영 `not_applicable`만 낸다.

    `top_p`(EOS-121 선결조건 A의 CLI 배선): **기본 None = 미전송**이라 지정하지 않으면 호출
    형태가 종전과 바이트 단위로 같다(각 공급사 기본값이 그대로 쓰인다). 값을 주면 생성기가
    `provider.generate(top_p=)`로 실어 **양 좌석에 같은 값**이 나간다 — 좌석별 생성 다양성을
    잴 때 이 축이 통제되지 않으면 어떤 숫자가 나와도 "설정 차이 아님"을 말할 수 없다
    (`docs/ops/eos121_seat_generation_diversity_precheck.md` §1의 3상태 분류: 같음/다름/
    **통제되지 않음**).
    """
    from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator
    from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
    from whymath_backend.schema.enums import Subject

    # None은 "지정 안 함"이라 **키 자체를 싣지 않는다** — 생성자 기본값(단일 좌석)이 그대로
    # 살아 있어야 회귀가 0이다. None을 그대로 넘기면 타입도 깨지고 좌석도 덮인다.
    routing_overrides: dict[str, Any] = {}
    if subscription is not None:
        routing_overrides["subscription"] = subscription
    if budget_krw is not None:
        routing_overrides["budget_krw"] = budget_krw
    # top_p도 같은 규약 — None이면 **키 자체를 싣지 않는다**. 생성자 기본값이 이미 None이라
    # 결과는 같지만, 키를 빼 두면 "미지정"이 호출 형태에서도 0바이트 차이가 되어 회귀 여부를
    # 눈으로도 판정할 수 있다(subscription·budget_krw와 같은 이유).
    if top_p is not None:
        routing_overrides["top_p"] = top_p
    # 저작 티어(MP-02 재회차) — "mid"(기본)는 키를 싣지 않아 종전과 바이트 동일하다. "quality"는
    # 라우팅 신호를 비동기로 바꿔 라우터 규칙 2가 로컬 QUALITY 티어를 고르게 한다(모델 ID를
    # 여기 박지 않는다 — 선택은 라우터 몫이고 실제 모델은 genlog → 회차 매니페스트에 남는다).
    if authoring_tier == "quality":
        routing_overrides["routing_sync"] = False
    elif authoring_tier != "mid":
        raise ValueError(f"authoring_tier는 mid|quality여야 한다(받은 값 {authoring_tier!r})")
    # 회피 목록(MP-02 재회차) — 0(기본)이면 키를 싣지 않아 종전 프롬프트와 바이트 동일하다.
    if avoid_recent:
        routing_overrides["avoid_recent"] = avoid_recent

    return LLMEquivalentProblemGenerator(
        # 표준 CompositeProvider 지연 구성 — 라이브 환경 전제. 클라우드 좌석은
        # `settings.cloud_provider` 셀렉터가 정한다(ARCH-57) — 이 배치는 그 선택을
        # llm_generator의 지연 조립에서 **상속**하므로 여기 제공자 이름이 박히지 않는다.
        None,
        misconception_catalog={mid: m.name_kr for mid, m in CATALOG_BY_ID.items()},
        topic_hint=topic_hint,
        subject=Subject.공통,
        slug_prefix="wm-gen-quad",
        generation_log_sink=generation_log_sink,
        **routing_overrides,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리(라이브 전용) — 리포트 JSON을 stdout에 내고, 신규 수용 0이면 exit 1."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_corpus_accumulate",
        description=(
            "LLM 동등문제 코퍼스 축적 배치 — 기존 코퍼스 signature를 주입해 회차 간 중복을 "
            "차단하고 수용분을 증분 append한다(라이브 LLM 필요)."
        ),
    )
    parser.add_argument(
        "--seed", dest="seeds", type=Path, action="append", default=[], help="기존 코퍼스 JSONL."
    )
    parser.add_argument("--out", type=Path, required=True, help="축적 산출 JSONL(append).")
    parser.add_argument("--n", type=int, default=20, help="생성 시도 횟수.")
    parser.add_argument("--topic-hint", default=_DEFAULT_TOPIC_HINT, help="저작 주제 힌트.")
    # ── 클라우드 라우팅 옵트인(EOS-99 PR #1023 codex P1) ──────────────────────────
    # 기본 None = 미지정 = 생성기 단일 좌석(free/0.0) 그대로 → **회귀 0**. 켜려면 둘 다 준다.
    parser.add_argument(
        "--subscription",
        default=None,
        choices=["free", "basic", "premium", "gifted"],
        help=(
            "라우팅 구독 신호(미지정=단일 좌석 free). 클라우드 경로를 태우려면 "
            "--budget-krw와 **함께** 지정한다 — 하나만으로는 라우터가 LOCAL로 강제한다."
        ),
    )
    parser.add_argument(
        "--budget-krw",
        type=float,
        default=None,
        help=(
            "라우팅 클라우드 잔여 예산(원·미지정=단일 좌석 0.0=LOCAL 강제). "
            "프롬프트 캐시 적중 계측(EOS-02)처럼 클라우드 호출이 필요한 회차에서만 지정한다."
        ),
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=None,
        help=(
            "누적확률 절단(nucleus sampling·EOS-121 선결조건 A). **미지정=미전송**이라 지정하지 "
            "않으면 호출 형태가 종전과 같고 각 공급사 기본값이 쓰인다. "
            "⚠️ **anthropic 좌석에서는 쓸 수 없다** — Anthropic API가 temperature와 top_p의 "
            "동시 지정을 400으로 거부하는데 저작 경로는 temperature(0.9)를 항상 싣기 때문이다. "
            "그 조합이면 이 CLI가 **호출 0건에서** exit 2로 거부한다(2026-09-19 라이브 90호출 "
            "전건 실패 실측). openrouter·로컬 좌석에서는 종전대로 쓸 수 있다."
        ),
    )
    parser.add_argument(
        "--authoring-tier",
        choices=["mid", "quality"],
        default="mid",
        help=(
            "로컬 저작 티어(MP-02 재회차). mid(기본)=종전 그대로 동기 라우팅 → 로컬 MID "
            "(qwen2.5:7b). quality=비동기 라우팅 → 라우터 규칙 2가 로컬 QUALITY 티어 "
            "(router.QUALITY_MODEL_ID·현 qwen3:30b-a3b)를 고른다. 오프라인 배치라 학생 대기가 "
            "없으므로 동기일 필요가 없다. 실제로 쓰인 모델은 genlog·회차 대장 manifest에 남는다."
        ),
    )
    parser.add_argument(
        "--avoid-recent",
        type=int,
        default=0,
        help=(
            "회차 내 중복 회피 목록 크기(MP-02 재회차·0~20·기본 0=끔). 주면 생성기가 이번 회차에 "
            "자신이 이미 만든 조건식 최근 N개를 다음 프롬프트에 '다시 쓰지 말 것'으로 싣는다. "
            "같은 spec 좌석(topic_hint)끼리만 공유한다. 상한 20은 Minimal context 규율"
            "(프롬프트에 넣을수록 모델이 흐려진다) 때문이다."
        ),
    )
    parser.add_argument(
        "--canary-basis",
        choices=["attempts", "judged"],
        default="attempts",
        help=(
            "카나리 표본 기준(MP-02 재회차). attempts(기본·종전)=앞머리 시도 --canary건. "
            "judged=중복을 뺀 판정 대상이 --canary건 모일 때까지 — 중복이 많아도 표본 크기가 "
            "줄지 않는다. 임계·신뢰수준·중복 제외 규칙은 동일하다."
        ),
    )
    parser.add_argument(
        "--standard-code", default=_DEFAULT_STANDARD_CODE, help="스펙 성취기준 코드."
    )
    parser.add_argument(
        "--difficulty", type=float, default=_DEFAULT_DIFFICULTY, help="스펙 난이도(1~5)."
    )
    parser.add_argument(
        "--spec-file",
        type=Path,
        default=None,
        help=(
            "spec 순환 계획 JSONL(EOS-121 선결조건 C). 한 줄 1 spec — "
            '{"spec_id": "...", "standard_code": "...", "difficulty": 2.5, "topic_hint": "..."} '
            "— 이며 spec_id만 필수고 나머지는 --standard-code·--difficulty·--topic-hint로 "
            "폴백한다. 주면 회차가 시도마다 spec을 **번갈아** 쓰고(라운드로빈) 결과가 spec별로 "
            "갈려 집계된다(리포트 spec_outcome_counts·대장 spec_plan·검수 큐 spec_id). "
            "미지정이면 종전대로 단일 spec 1종으로 돈다. 파일의 오류는 전부 fail-loud(exit 2) — "
            "조용히 건너뛰면 'spec 3종을 돌렸다'가 거짓인 채로 회차가 나간다."
        ),
    )
    parser.add_argument(
        "--generation-log",
        type=Path,
        default=None,
        help=(
            "GenerationLog JSONL 경로(EOS-55). 미지정 시 <out>.genlog.jsonl 사이드카에 "
            "항상 적재한다(끄기 없음 — 적재가 기본·정본화≠집행)."
        ),
    )
    parser.add_argument(
        "--worklist-out",
        type=Path,
        default=None,
        help=(
            "검수 워크리스트(내구 큐 <out>.review.jsonl 전체의 누적 렌더 뷰) 마크다운 경로"
            "(EOS-58). 미지정 시 <out>.worklist.md 사이드카에 항상 기록한다(끄기 없음 — 사람 "
            "검수 큐 공급이 기본·뷰 경로를 바꿔도 큐 저장소는 <out>.review.jsonl 고정)."
        ),
    )
    parser.add_argument(
        "--stagnation-window",
        type=int,
        default=DEFAULT_STAGNATION_WINDOW,
        help=(
            "연속 무진전 알람 임계 회차 수(EOS-64 ④·기본 "
            f"{DEFAULT_STAGNATION_WINDOW}). 최신 회차부터 코퍼스 신규 행 0인 회차가 이 수 "
            "이상 연속되면 exit 2 + stderr 알람. 회차 이력은 <out>.rounds.jsonl 대장에 "
            "항상 적재한다(끄기 없음 — 대장이 없으면 알람이 영원히 '측정 불가'다)."
        ),
    )
    parser.add_argument(
        "--canary",
        type=int,
        default=DEFAULT_CANARY_SIZE,
        help=(
            f"카나리 표본 수(EOS-95 ①·기본 {DEFAULT_CANARY_SIZE}). 회차 앞머리 이 건수를 "
            "생성한 시점에 Wilson 단측 하한으로 1회 판정하고, 미달이면 남은 회차를 "
            "시작하지 않는다(exit 1). 0이면 관문을 끈다. --n이 이 값 이하면 막을 본배치가 "
            "없으므로 판정하지 않는다."
        ),
    )
    parser.add_argument(
        "--canary-threshold",
        type=float,
        default=DEFAULT_CANARY_THRESHOLD,
        help=(
            f"카나리 통과에 요구하는 Wilson 하한(기본 {DEFAULT_CANARY_THRESHOLD}). "
            "주의: n=30에서 0.95는 만점 30/30(하한 91.7%%)에도 통과 불가능하다 — 근거는 "
            "batch_safety 모듈 docstring의 실측 표."
        ),
    )
    parser.add_argument(
        "--canary-confidence",
        type=float,
        default=DEFAULT_CANARY_CONFIDENCE,
        help=f"카나리 Wilson 단측 신뢰수준(기본 {DEFAULT_CANARY_CONFIDENCE}).",
    )
    parser.add_argument(
        "--abort-window",
        type=int,
        default=DEFAULT_ABORT_WINDOW,
        help=(
            f"롤링 불량률 감시 창 크기(EOS-95 ③·기본 {DEFAULT_ABORT_WINDOW}). 0이면 감시를 "
            "끈다. 창이 다 차기 전에는 판정하지 않으므로 이 값보다 짧은 회차는 롤링 감시가 "
            "한 번도 판정하지 않는다(그 구간의 보호는 카나리 관문)."
        ),
    )
    parser.add_argument(
        "--abort-threshold",
        type=float,
        default=DEFAULT_ABORT_THRESHOLD,
        help=(
            f"롤링 창 불량률이 이 값을 **초과**하면 즉시 중단(기본 {DEFAULT_ABORT_THRESHOLD}). "
            "중단해도 그때까지의 수용분은 append되고 비수용분은 검수 큐에 남는다."
        ),
    )
    # 회차 매니페스트(MP-04 ①)에 실을 **실행 인자 원문**을 여기서 확정한다 — argv=None(실제
    # CLI 실행)이면 `sys.argv[1:]`가 원문이고, 테스트·호출자가 리스트를 주면 그것이 원문이다.
    # parse_args에도 이 확정값을 넘겨 "기록한 인자"와 "해석한 인자"가 갈라지지 않게 한다.
    effective_argv: list[str] = list(argv) if argv is not None else list(sys.argv[1:])
    args = parser.parse_args(effective_argv)
    if not 0 <= args.avoid_recent <= 20:
        parser.error(f"--avoid-recent는 0~20이어야 한다(받은 값 {args.avoid_recent}).")
    if args.canary < 0:
        parser.error(f"--canary는 0 이상이어야 한다(받은 값 {args.canary}).")
    if not 0.0 <= args.canary_threshold <= 1.0:
        parser.error(f"--canary-threshold는 [0,1] 범위여야 한다(받은 값 {args.canary_threshold}).")
    if not 0.0 < args.canary_confidence < 1.0:
        # 0·1은 Wilson z가 발산해 게이트가 상시 통과/상시 차단이 된다(변별력 0).
        parser.error(
            f"--canary-confidence는 (0,1) 범위여야 한다(받은 값 {args.canary_confidence})."
        )
    if args.abort_window < 0:
        parser.error(f"--abort-window는 0 이상이어야 한다(받은 값 {args.abort_window}).")
    if not 0.0 <= args.abort_threshold <= 1.0:
        parser.error(f"--abort-threshold는 [0,1] 범위여야 한다(받은 값 {args.abort_threshold}).")
    if args.stagnation_window <= 0:
        # 창 0·음수는 알람을 상시 참으로 만들어 판정을 무의미하게 만든다(변별력 없는 게이트).
        parser.error(f"--stagnation-window는 1 이상이어야 한다(받은 값 {args.stagnation_window}).")
    if args.top_p is not None and not 0.0 < args.top_p <= 1.0:
        # 누적확률이므로 (0,1] 밖은 의미가 없다. 공급사가 400으로 거부하는 값을 180호출
        # **한복판에서** 만나면 회차가 통째로 날아가므로 인자 단계에서 막는다.
        parser.error(f"--top-p는 (0,1] 범위여야 한다(받은 값 {args.top_p}).")

    # ── `--top-p` × 좌석 사전 거부(EOS-121 라이브 정정) ─────────────────────
    # **호출 0건에서** 막는 것이 요점이다 — 프로바이더 가드만 있으면 90번 시도해 90번 실패한다.
    # `--top-p` 미지정이면 설정을 읽지도 않는다(종전 경로와 바이트 단위로 같게 둔다).
    if args.top_p is not None:
        try:
            seat_for_precheck = cloud_provider_name(get_settings())
        except Exception as exc:  # noqa: BLE001 — 판독 실패를 통과로 접지 않는다(타입명 남김)
            # 좌석을 모르면 거부 판정을 할 수 없다. 여기서 통과시키면 "모른다"가 "문제없다"로
            # 위장되고, 그 대가는 90호출이다(모른다 ≠ 아니다).
            sys.stderr.write(
                f"[좌석 판독 실패] {type(exc).__name__}: {exc} — --top-p를 지정한 회차는 "
                "좌석을 알아야 사전 거부 판정을 할 수 있습니다. 설정을 고치거나 --top-p를 "
                "빼고 실행하세요.\n"
            )
            return 2
        seat_refusal = top_p_seat_precheck(
            top_p=args.top_p,
            seat=seat_for_precheck,
            subscription=args.subscription,
            budget_krw=args.budget_krw,
        )
        if seat_refusal is not None:
            sys.stderr.write(f"{seat_refusal}\n")
            return 2

    # ── spec 순환 계획(EOS-121 선결조건 C) ──────────────────────────────────
    # 미지정이면 좌석 1건(`_DEFAULT_SPEC_ID`)으로 종전과 동일하게 돈다. 파일 오류는
    # fail-loud로 **exit 2**를 낸다 — 0/1은 "회차가 돌았고 붙었나/아니었나"의 어휘라, 설정
    # 오류를 1로 내면 "돌았는데 무진전"과 구분되지 않는다(2는 이미 '강한 구조 신호' 자리다).
    plan_entries: list[tuple[str, EquivalenceSpec, str]]
    if args.spec_file is not None:
        try:
            plan_entries = load_spec_plan_file(
                args.spec_file,
                default_standard_code=args.standard_code,
                default_difficulty=args.difficulty,
                default_topic_hint=args.topic_hint,
            )
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"[spec 계획 오류] {type(exc).__name__}: {exc}\n")
            return 2
    else:
        plan_entries = [
            (
                _DEFAULT_SPEC_ID,
                EquivalenceSpec(
                    achievement_standard_codes=frozenset({args.standard_code}),
                    target_misconception_ids=frozenset(),
                    difficulty_overall=args.difficulty,
                    answer_format=None,
                ),
                args.topic_hint,
            )
        ]
    # 생성 Run 재현 로그(EOS-55) — 호출별 즉시 flush 사이드카(2026-08-22 규칙 ①: 배치가
    # 도중에 죽어도 그때까지의 호출 이력·비용은 파일에 남는다).
    genlog_path: Path = (
        args.generation_log
        if args.generation_log is not None
        else default_generation_log_path(args.out)
    )

    # 회차 식별자를 **여기서** 정한다(EOS-97 리콜 조인 축). 종전에는 run_corpus_accumulate
    # 안에서 생성돼 생성 로그 싱크가 그 값을 볼 수 없었고, 그래서 GenerationLog와
    # AccumulateReport·검수 큐가 서로 다른 축을 갖는 상태였다 — "이 회차로 만든 산출물"을
    # 기계가 특정할 수 없던 이유다. 한 곳에서 뽑아 세 곳(생성 로그·리포트·검수 큐)에 같은
    # 값을 흘린다.
    run_id = uuid.uuid4().hex

    # 회차 매니페스트(MP-04 ①)의 모델·프롬프트 좌석 — genlog에 **실제로 적재된 행**에서만
    # 모은다(적재 전에 모으면 파일에 없는 값을 대장이 주장하게 된다 — 재현 계약 ④의 대조가
    # 그 순간 거짓이 된다). 회차 중 라우팅이 갈려 값이 여러 개면 전부 모아 둔다.
    observed_models: set[str] = set()
    observed_prompt_versions: set[str] = set()
    # 프롬프트 캐시 원장(EOS-99) — 모델·프롬프트 좌석과 **같은 자리**에서 모은다: 셋 다
    # "이 회차가 실제로 무엇으로 돌았는가"이고, 셋 다 genlog에 *적재된 행*에서만 나와야
    # 대장이 파일에 없는 값을 주장하지 않는다.
    cache_tally = PromptCacheTally()
    # 좌석 원장(EOS-111) — 캐시 원장과 **같은 자리**에서 모은다. 셋 다 "이 회차가 실제로
    # 무엇으로 돌았는가"이고, genlog에 *적재된 행*에서만 나와야 대장이 파일에 없는 값을
    # 주장하지 않는다.
    seat_tally = SeatTally()

    def _genlog_sink(log: GenerationLog) -> None:
        nonlocal cache_tally, seat_tally
        stamped = append_generation_log_jsonl(genlog_path, log, run_id=run_id)
        if stamped.model_name:
            observed_models.add(stamped.model_name)
        if stamped.prompt_version:
            observed_prompt_versions.add(stamped.prompt_version)
        cache_tally = cache_tally.observe(
            input_tokens=stamped.input_tokens,
            cache_read_input_tokens=stamped.cache_read_input_tokens,
            cache_creation_input_tokens=stamped.cache_creation_input_tokens,
        )
        seat_tally = seat_tally.observe(
            model_name=stamped.model_name,
            success=stamped.success,
            cost_usd=stamped.cost_usd,
            # 관측 축(EOS-112) — 선언값과 **같은 행**에서 같이 읽는다. 따로 순회하면 두
            # 집계가 다른 행 집합을 보게 되어 대조 자체가 거짓이 된다.
            served_model=stamped.served_model,
            retries=stamped.retries,
        )

    # 내구 검수 큐(EOS-58 codex P1-1/P2) — 비수용 outcome 발생 즉시 행 append+flush. 경로는
    # 항상 <out>.review.jsonl 사이드카(뷰와 달리 저장소는 옮기지 않는다 — 누적의 단일 원천).
    review_queue_path: Path = default_review_queue_path(args.out)

    def _review_sink(entry: ReviewQueueEntry) -> None:
        append_review_queue_jsonl(review_queue_path, entry)

    # 생성기는 **topic_hint별로 하나**씩 만들어 재사용한다(EOS-121 C·`SpecSeat` docstring ⓑ).
    # 같은 힌트를 쓰는 좌석이 같은 인스턴스를 공유해야 생성기가 들고 있는 지속 이벤트 루프
    # (배치 격회 실패 방어)와 provider 커넥션 풀이 회차 내내 살아 있다 — 좌석마다 새로 만들면
    # 그 방어가 spec 수만큼 쪼개진다. 단일 spec 회차에서는 정확히 1개라 종전과 같다.
    generators_by_hint: dict[str, EquivalentProblemGenerator] = {}
    for _, _, hint in plan_entries:
        if hint not in generators_by_hint:
            generators_by_hint[hint] = _build_live_generator(
                hint,
                generation_log_sink=_genlog_sink,
                subscription=args.subscription,
                budget_krw=args.budget_krw,
                top_p=args.top_p,
                authoring_tier=args.authoring_tier,
                avoid_recent=args.avoid_recent,
            )
    spec_seats = [
        SpecSeat(
            spec_id=spec_id, spec=plan_spec, generator=generators_by_hint[hint], topic_hint=hint
        )
        for spec_id, plan_spec, hint in plan_entries
    ]

    # 회차 매니페스트(MP-04 ①)의 입력 지문 — **배치 호출 앞에서** 뜬다(PR #1013 Codex P1).
    # 이유 둘: ⓐ dedup 인덱스는 `--seeds`뿐 아니라 **기존 `--out` 코퍼스**로도 만들어진다
    # (run_corpus_accumulate의 `load_corpus_index([out_path])` → `seed_signatures | out_signatures`)
    # — out을 빼면 수용 판정에 실제로 쓰인 입력 하나가 대장에서 통째로 빠진다 ⓑ 배치 뒤에
    # 뜨면 이 회차가 out에 append한 바이트까지 섞여, "소비한 입력"이 아니라 "산출 후 상태"를
    # 기록하게 된다(재현하려는 사람이 그 해시를 맞출 방법이 없다).
    # 첫 회차처럼 out이 아직 없으면 값은 None이다 — "그 경로를 dedup 입력으로 썼으나 읽을
    # 것이 없었다"는 관측이며, 키는 남는다.
    dedup_digests = compute_dedup_input_digests([*args.seeds, args.out])

    report = run_corpus_accumulate(
        out_path=args.out,
        seed_paths=list(args.seeds),
        spec_seats=spec_seats,
        n=args.n,
        review_sink=_review_sink,
        run_id=run_id,
        abort_window=args.abort_window if args.abort_window > 0 else None,
        abort_threshold=args.abort_threshold,
        canary_size=args.canary if args.canary > 0 else None,
        canary_threshold=args.canary_threshold,
        canary_confidence=args.canary_confidence,
        canary_basis=args.canary_basis,
    )
    # 배치 종료 — 관측 전송 확정(2026-07-21 정합성 검토: 생성기 trace 배선). LangfuseSink는
    # 배치 버퍼 전송이라 짧은 CLI는 flush 없이 종료하면 이벤트가 유실된다(cost_probe 동형).
    # 좌석 계약(EquivalentProblemGenerator)엔 flush가 없으므로 duck-typing으로 있는 경우만.
    # **생성기 전건**을 flush한다(EOS-121 C) — topic_hint가 갈리면 인스턴스도 갈리므로
    # 하나만 flush하면 나머지 좌석의 trace가 통째로 유실된다(조용한 관측 손실).
    for _live_generator in generators_by_hint.values():
        flush_trace = getattr(_live_generator, "flush_trace", None)
        if callable(flush_trace):
            flush_trace()
    # 검수 워크리스트(EOS-58 codex P1-2) — 이 회차 메모리가 아니라 **내구 큐 전체**의 렌더
    # 뷰다: 회차 간 누적이 기본이라 이전 미해결 needs_review가 덮어쓰기로 소실되지 않고, 전건
    # 수용 회차도 기존 큐를 비우지 않는다. 무진전 회차(exit 1)에도 기록한다(실패 증거 보존·
    # 2026-08-22 규칙 ①) — 큐 파일 부재(비수용 기록 0)면 헤더가 "누적 행 0"을 말한다
    # (미기록과 구분·미측정≠0). 로드 실패 행은 뷰 헤더에 타입명+줄 번호로 노출된다.
    queue_entries: list[ReviewQueueEntry] = []
    queue_errors: list[str] = []
    if review_queue_path.exists():
        queue_entries, queue_errors = load_review_queue_jsonl(review_queue_path)
    worklist_path: Path = (
        args.worklist_out if args.worklist_out is not None else default_worklist_path(args.out)
    )
    worklist_md = render_review_queue_markdown(
        queue_entries,
        queue_display_path=str(review_queue_path),
        load_errors=queue_errors,
    )
    worklist_path.parent.mkdir(parents=True, exist_ok=True)
    worklist_path.write_text(worklist_md, encoding="utf-8")

    # ── 회차 대장 + 연속 무진전 알람(EOS-64 ④) ───────────────────────────────
    # 대장 append는 워크리스트 기록 *뒤*에 둔다 — 앞선 산출물이 다 남은 뒤에 회차를 "끝났다"고
    # 기록해야 대장 행과 디스크 상태가 어긋나지 않는다(중간에 죽으면 그 회차는 대장에 없고,
    # 그건 정직하다 — 완료되지 않은 회차다).
    payload = report.to_json()
    # 프롬프트 캐시 작동 신호(EOS-99) — 리포트와 대장에 **같은 dict**를 싣는다(두 벌 산식
    # 금지). 플래그 상태는 이 회차를 돌린 설정에서 읽는다: 설정을 못 읽으면 False로 접지
    # 않고 None(미상)으로 둔다 — 모르는 것을 '꺼짐'으로 적으면 적중 0%가 당연한 결과로
    # 읽혀 '켰지만 작동 안 함'이 영영 안 보인다(모른다 ≠ 아니다).
    caching_enabled: bool | None
    try:
        caching_enabled = bool(get_settings().anthropic_prompt_caching)
    except Exception as exc:  # noqa: BLE001 — 설정 판독 실패는 회차 비차단(타입명 남김)
        caching_enabled = None
        _LOGGER.warning(
            "프롬프트 캐시 플래그 판독 실패(%s) — 판정을 미상으로 둔다", type(exc).__name__
        )
    payload["prompt_cache"] = prompt_cache_rates(cache_tally, caching_enabled=caching_enabled)
    # 좌석 작동 신호(EOS-111) — "셀렉터가 지목한 좌석이 실제로 돌았는가". 셀렉터·핀은 이
    # 회차를 돌린 설정에서 읽으며, 판독 실패는 False로 접지 않고 **미상**으로 남긴다
    # (모르는 것을 '기본 좌석'으로 적으면 이 신호 자체가 거짓이 된다 — ARCH-58 형태).
    selected_seat: str
    seat_pins: tuple[str, ...]
    try:
        _seat_settings = get_settings()
        selected_seat = cloud_provider_name(_seat_settings)
        seat_pins = cloud_model_pins(_seat_settings)
    except Exception as exc:  # noqa: BLE001 — 설정 판독 실패는 회차 비차단(타입명 남김)
        selected_seat = "unknown"
        seat_pins = ()
        _LOGGER.warning(
            "클라우드 좌석 설정 판독 실패(%s) — 좌석 판정을 미상으로 둔다", type(exc).__name__
        )
    payload["cloud_seat"] = seat_operating_rates(
        seat_tally, selected_seat=selected_seat, seat_model_pins=seat_pins
    )
    ledger_path: Path = default_round_ledger_path(args.out)
    ledger_error: str | None = None
    # 회차 매니페스트(MP-04) — 카나리 관측 3종은 판정이 **있었을 때만** 값이 있다. 판정이
    # 없었던 회차(관문 꺼짐·시도 0건)를 False/0.0으로 채우면 "게이트가 막았다"·"성공률 0%"로
    # 위장되므로 전부 None으로 둔다(모른다 ≠ 아니다).
    canary_json: dict[str, Any] | None = report.canary
    try:
        append_round_ledger(
            ledger_path,
            RoundRecord(
                run_id=report.run_id,
                out_path=report.out_path,
                attempted=report.attempted,
                accepted=report.accepted,
                appended=report.appended,
                outcome_counts=dict(report.outcome_counts),
                # ① 구성 스냅샷 — 이 회차를 재현하는 데 필요한 입력.
                #    `--canary 0`·`--abort-window 0`(끔)은 0 그대로 기록한다(None=미기록과 구분).
                prompt_version=_snapshot_observed_value(observed_prompt_versions),
                model_name=_snapshot_observed_value(observed_models),
                canary_size=args.canary,
                canary_threshold=args.canary_threshold,
                canary_confidence=args.canary_confidence,
                abort_window=args.abort_window,
                abort_threshold=args.abort_threshold,
                dedup_input_digests=dedup_digests,
                # spec 순환 계획·spec별 결과(EOS-121 C) — **좌석 × spec 교차 집계의 spec 축**
                # 이다. 좌석 축은 아래 `cloud_seat`가 따로 싣는다(좌석이 회차 단위라는 것은
                # 맞지만, 그 값이 대장에 실리지 않으면 대장만으로는 어느 좌석의 회차인지 알 수
                # 없다 — 2026-09-19 파일럿에서 `cloud_seat: null`로 실측됐다. 두 필드가 함께
                # 있어야 교차 집계가 성립한다).
                spec_plan=report.spec_plan,
                spec_outcome_counts=report.spec_outcome_counts,
                cli_argv=effective_argv,
                # ② 관측 판정 — 게이트가 실제로 일했다는 신호.
                canary_passed=bool(canary_json["passed"]) if canary_json is not None else None,
                canary_rate=(
                    float(canary_json["point_estimate"]) if canary_json is not None else None
                ),
                canary_lower_bound=(
                    float(canary_json["wilson_lower"]) if canary_json is not None else None
                ),
                canary_blocked=report.canary_blocked,
                canary_advisory=report.canary_advisory,
                canary_basis=report.canary_basis,
                canary_attempts=report.canary_attempts,
                aborted=report.aborted,
                abort_reason=report.abort_reason,
                # 중복 출처(EOS-121 B) — **사후 복원 불가**라 회차 중에 대장으로 흘린다.
                # 회차가 끝나면 signature_index는 기존분과 회차분이 섞인 한 덩어리다.
                duplicate_sources=report.duplicate_sources,
                prompt_cache=payload["prompt_cache"],
                # 좌석 작동 신호(EOS-111/112) — 요약과 **같은 dict**를 싣는다(두 벌 산식 금지).
                # 대장에도 싣는 이유: stdout 요약은 파이프로 받지 않으면 사라지는데, 좌석 비교
                # 회차(EOS-121)의 판정은 "어느 좌석의 회차인가"에서 출발한다. 대장이 그것을
                # 모르면 그 회차는 다시 못 읽는다(파일럿 실측 `cloud_seat: null` — 2026-09-19).
                cloud_seat=payload["cloud_seat"],
            ),
        )
    except Exception as exc:  # noqa: BLE001 — 대장 적재 장애는 회차를 깨지 않되 타입명을 남긴다
        ledger_error = type(exc).__name__
        _LOGGER.warning("회차 대장 적재 실패(%s) — 무진전 판정은 이 회차를 못 본다", ledger_error)

    ledger_records: list[RoundRecord] = []
    ledger_load_errors: list[str] = []
    if ledger_path.exists():
        ledger_records, ledger_load_errors = load_round_ledger(ledger_path)
    stagnation = judge_stagnation(
        ledger_records, window=args.stagnation_window, load_errors=ledger_load_errors
    )
    payload["stagnation"] = {
        **stagnation.to_json(),
        "ledger_path": str(ledger_path),
        # 적재가 실패했으면 이번 회차가 대장에 없다 — 판정이 그 사실 위에서 내려졌음을 명기한다
        # (조용한 실패 금지: 알람이 안 뜬 이유가 "진전"인지 "기록 누락"인지 구분 가능해야 한다).
        "ledger_append_error": ledger_error,
        "ledger_load_errors": ledger_load_errors,
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    # ── 배치 안전장치 판정(EOS-95) ────────────────────────────────────────────
    # 무진전 알람보다 **먼저** 본다: 카나리 미달·롤링 중단은 "이번 회차가 성과가 없었다"가
    # 아니라 "파이프라인이 결함을 대량 복제하려 했다"는 더 급한 신호다. stdout JSON에만
    # 실으면 습관화돼 안 읽히므로 stderr에도 사유를 낸다(조용한 중단 금지).
    if report.canary_blocked:
        sys.stderr.write(f"[카나리 차단] {payload['canary']['reason']} — 본배치 미시작\n")
        return 1
    if report.aborted:
        sys.stderr.write(f"[배치 중단] {report.abort_reason}\n")
        return 1

    if stagnation.alarm:
        # stderr + exit 2 — stdout JSON 한 필드만이면 습관화돼 안 읽힌다(fail-open 상시 실패를
        # "보호 있음"으로 신뢰 금지). exit 2는 "이번 회차 무진전"(1)보다 강한 구조 신호다.
        sys.stderr.write(f"[연속 무진전 알람] {stagnation.message}\n")
        return 2
    return 0 if report.appended > 0 else 1


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
