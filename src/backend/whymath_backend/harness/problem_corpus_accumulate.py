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

exit 코드 3종: 0=신규 수용 ≥1 · 1=이번 회차 무진전 · **2=연속 무진전 알람**(1보다 강한 신호 —
이번 회차만의 운이 아니라 구조적으로 막혀 있다).

사용법(Phaiakes9·라이브):
    python -m whymath_backend.harness.problem_corpus_accumulate \\
        --seed <기존.jsonl> [--seed <추가.jsonl> ...] --out <축적.jsonl> --n 20 \\
        [--topic-hint "..."] [--standard-code "[10공수1-02-02]"] [--difficulty 2.5] \\
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

from whymath_backend.config import get_settings
from whymath_backend.harness.anchor_round_ledger import (
    DEFAULT_STAGNATION_WINDOW,
    PromptCacheTally,
    RoundRecord,
    append_round_ledger,
    default_round_ledger_path,
    judge_stagnation,
    load_round_ledger,
    operating_rates,
    prompt_cache_rates,
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
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.generator import EquivalentProblemGenerator
from whymath_backend.l3.equivalent.orchestrator import (
    GenerationOutcome,
    run_equivalent_generation,
)
from whymath_backend.l3.equivalent.orchestrator import (
    _to_record as _candidate_to_record,
)
from whymath_backend.l3.pregenerate.provenance_bridge import append_generation_log_jsonl
from whymath_backend.schema.provenance import GenerationLog

__all__ = [
    "AccumulateReport",
    "compute_dedup_input_digests",
    "default_generation_log_path",
    "default_round_ledger_path",
    "default_review_queue_path",
    "default_worklist_path",
    "load_corpus_index",
    "main",
    "run_corpus_accumulate",
]

_LOGGER = logging.getLogger(__name__)

# 기본 topic 힌트 — 라이브 스모크(2026-07-07) 검증 문구. --topic-hint로 교체 가능.
_DEFAULT_TOPIC_HINT = "이차방정식 — 두 근 중 큰 근을 구하는 형태(답 하나)"
_DEFAULT_STANDARD_CODE = "[10공수1-02-02]"
_DEFAULT_DIFFICULTY = 2.5


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

    def to_json(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "accepted": self.accepted,
            "appended": self.appended,
            "slug_conflicts": self.slug_conflicts,
            "outcome_counts": self.outcome_counts,
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


def _queue_entry(outcome: GenerationOutcome, run_id: str) -> ReviewQueueEntry:
    """비수용 outcome → 내구 큐 행 조립(조성 루트) — payload = 코퍼스 레코드 동일 직렬화.

    후보가 있으면 저장 경로와 같은 변환(`_to_record`→`_record_to_json`)으로 전문을 싣는다 —
    검수 수용 시 그대로 코퍼스 행이 될 수 있는 승격 가능 형태(이중 직렬화 구현 금지). 후보
    없는 outcome(생성 실패)은 payload=None — `reasons`가 실패 사유를 말한다(본문 날조 금지).
    """
    payload: dict[str, Any] | None = None
    if outcome.candidate is not None:
        payload = _record_to_json(_candidate_to_record(outcome.candidate))
    return entry_from_outcome(outcome, run_id=run_id, candidate_payload=payload)


def run_corpus_accumulate(
    *,
    out_path: Path,
    seed_paths: Sequence[Path],
    generator: EquivalentProblemGenerator,
    spec: EquivalenceSpec,
    n: int,
    write: bool = True,
    review_sink: Callable[[ReviewQueueEntry], None] | None = None,
    run_id: str | None = None,
    abort_window: int | None = DEFAULT_ABORT_WINDOW,
    abort_threshold: float = DEFAULT_ABORT_THRESHOLD,
    canary_size: int | None = DEFAULT_CANARY_SIZE,
    canary_threshold: float = DEFAULT_CANARY_THRESHOLD,
    canary_confidence: float = DEFAULT_CANARY_CONFIDENCE,
) -> AccumulateReport:
    """축적 1회차 — 기존 signature 주입 dedup + 수용분 증분 append(생성기 좌석 무관).

    `generator`는 좌석 계약만 요구한다(LLM·스켈레톤 동일) — 라이브 배선은 main() 소관이고,
    hermetic 테스트는 결정론 생성기를 주입해 축적 로직을 LLM 0으로 검증한다.

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
    """
    seed_signatures, seed_slugs, seed_total = load_corpus_index(list(seed_paths))
    out_signatures, out_slugs, out_total = load_corpus_index([out_path])

    # 공유 index — 기존(시드+축적분) 구조가 전부 실려 회차 간 판박이가 생성 단계에서 차단된다.
    signature_index: set[str] = seed_signatures | out_signatures
    known_slugs: set[str] = seed_slugs | out_slugs

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
    for _ in range(n):
        outcome = run_equivalent_generation(
            spec, generator, signature_index=signature_index, store=sink
        )
        outcomes.append(outcome)
        if review_sink is not None and not is_accepted_status(outcome.status):
            try:
                review_sink(_queue_entry(outcome, resolved_run_id))
            except Exception as exc:  # noqa: BLE001 — 큐 적재 장애는 배치 비차단(타입명 로그)
                _LOGGER.warning("검수 큐 행 적재 실패(%s) — 배치 계속", type(exc).__name__)
        if watchdog is not None:
            watchdog.observe_status(outcome.status)
        if (
            canary_gate_at is not None
            and canary_verdict is None
            and len(outcomes) >= canary_gate_at
        ):
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
        if not canary_verdict.passed:
            _LOGGER.warning("[카나리 권고·차단력 없음] %s", canary_verdict.reason)

    counts: dict[str, int] = {}
    reasons: list[str] = []
    # 비수용 outcome 원본 보존(EOS-58) — 이 회차 요약(리포트)용. 내구 영속은 위 review_sink가
    # 이미 발생 즉시 수행했다(batch의 review_outcomes 포착 필터와 동일 기준).
    review_outcomes: list[GenerationOutcome] = []
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
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


def _build_live_generator(
    topic_hint: str,
    *,
    generation_log_sink: Callable[[GenerationLog], None] | None = None,
    subscription: str | None = None,
    budget_krw: float | None = None,
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
        "--standard-code", default=_DEFAULT_STANDARD_CODE, help="스펙 성취기준 코드."
    )
    parser.add_argument(
        "--difficulty", type=float, default=_DEFAULT_DIFFICULTY, help="스펙 난이도(1~5)."
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

    spec = EquivalenceSpec(
        achievement_standard_codes=frozenset({args.standard_code}),
        target_misconception_ids=frozenset(),
        difficulty_overall=args.difficulty,
        answer_format=None,
    )
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

    def _genlog_sink(log: GenerationLog) -> None:
        nonlocal cache_tally
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

    # 내구 검수 큐(EOS-58 codex P1-1/P2) — 비수용 outcome 발생 즉시 행 append+flush. 경로는
    # 항상 <out>.review.jsonl 사이드카(뷰와 달리 저장소는 옮기지 않는다 — 누적의 단일 원천).
    review_queue_path: Path = default_review_queue_path(args.out)

    def _review_sink(entry: ReviewQueueEntry) -> None:
        append_review_queue_jsonl(review_queue_path, entry)

    generator = _build_live_generator(
        args.topic_hint,
        generation_log_sink=_genlog_sink,
        subscription=args.subscription,
        budget_krw=args.budget_krw,
    )

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
        generator=generator,
        spec=spec,
        n=args.n,
        review_sink=_review_sink,
        run_id=run_id,
        abort_window=args.abort_window if args.abort_window > 0 else None,
        abort_threshold=args.abort_threshold,
        canary_size=args.canary if args.canary > 0 else None,
        canary_threshold=args.canary_threshold,
        canary_confidence=args.canary_confidence,
    )
    # 배치 종료 — 관측 전송 확정(2026-07-21 정합성 검토: 생성기 trace 배선). LangfuseSink는
    # 배치 버퍼 전송이라 짧은 CLI는 flush 없이 종료하면 이벤트가 유실된다(cost_probe 동형).
    # 좌석 계약(EquivalentProblemGenerator)엔 flush가 없으므로 duck-typing으로 있는 경우만.
    flush_trace = getattr(generator, "flush_trace", None)
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
                aborted=report.aborted,
                abort_reason=report.abort_reason,
                prompt_cache=payload["prompt_cache"],
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
