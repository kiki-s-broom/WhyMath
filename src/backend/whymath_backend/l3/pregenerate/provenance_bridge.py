"""생성 결과 → `GenerationLog` 변환·적재 어댑터 (L3 → schema 연결).

설계 정본: `schemas/v1.0/schema_v1.0.md` §10.1 `generation_log`(슬라이스 2 모델) +
EOS-55 재현 좌석(prompt_version·seed·입력 스냅샷 해시+참조).

계층 규칙(7계층 아키텍처, 절대원칙):
  `schema/`(L1 데이터)는 `l3`(L3)를 *import 금지*(역방향 의존 금지). 반대로 `l3 →
  schema`는 허용된다. 따라서 사전생성(`PrewarmItemResult`) 결과를 `GenerationLog`로
  바꾸는 *연결* 코드는 반드시 L3쪽(이 파일)에 둔다. 이렇게 두면 schema 패키지는 l3를
  전혀 모른 채 순수하게 유지된다.

적재 매체 메모(EOS-55 — 집행 별항): 두 생성 경로(`l3/pregenerate` CLI·
  `harness/problem_corpus_accumulate`)는 오프라인 배치라 DB 세션이 없다 — 1차 매체는
  **JSONL 즉시 flush**(`append_generation_log_jsonl`·EOS-54 `harness/review_timer.py`
  동형)이고, DB 적재는 같은 schema 레코드를 `db.models.provenance.GenerationLog
  .from_schema`로 넘기면 된다(별도 코드 불요). `ops/hit_cu_metrics --generation-log`가
  이 JSONL을 CU당 비용 인프로세스 이중 회계로 소비한다(SaaS 비의존).

텔레메트리 메모 (S1 게이트 ② 배선): provider `generate`가 `GenerationResult(text,
  usage)`를 반환하게 되어(usage=실측 토큰·지연), `PrewarmItemResult.usage`가 그 실측을
  담는다. 이 어댑터는 usage가 *있을 때만* 토큰·지연을 채우고, 없으면(인제스트 모드·
  usage 미노출 provider) 종전대로 None을 둔다 — *지어내지 않는다*. 비용(cost_usd)은
  호출자가 `actual_cost_usd_or_none` 등으로 산정해 인자로 준다(이 어댑터는 티어·단가를
  모른 채 순수 변환만 한다).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from whymath_backend.config import Settings, get_settings
from whymath_backend.l3.models import CostTier, RoutingDecision, Usage
from whymath_backend.l3.pregenerate.models import PregenItem, PrewarmItemResult
from whymath_backend.l3.providers.factory import cloud_model_pins
from whymath_backend.l3.router import _as_cost_tier, actual_cost_usd, resolve_model
from whymath_backend.schema.provenance import GenerationLog, text_sha256

logger = logging.getLogger("whymath.l3.pregenerate.provenance_bridge")

# 사전적재 결과 status 중 *유효 시드 확보=성공*으로 간주하는 집합.
# - "written": 새로 검증·적재됨 → 시드 확보.
# - "skipped_exists": 이미 같은 키의 시드가 존재(overwrite=False) → 유효 시드 이미 확보.
# - "failed_validation"/"error": 시드 미확보 → 실패.
_SUCCESS_STATUSES: frozenset[str] = frozenset({"written", "skipped_exists"})


def model_name_for_decision(
    decision: RoutingDecision,
    *,
    settings: Settings | None = None,
) -> str:
    """라우터 결정 → 이 설정에서 *호출 대상이 되는* 모델 ID (GenerationLog.model_name 좌석용).

    LOCAL은 라우터 매트릭스 해석(`resolve_model` — 예 'qwen2.5:7b'). CLOUD_MID/HIGH는
    **클라우드 좌석 셀렉터(`settings.cloud_provider`)가 지목한 제공자의 모델 핀**을 읽는다 —
    그 제공자를 실제로 만드는 `l3/providers/factory.build_cloud_provider()`와 같은 설정을
    보므로 둘이 갈라지지 않는다.

    **선언값이지 관측값이 아니다**(ARCH-58): 이 함수는 설정을 읽어 "이 구성이면 무엇이
    불릴 것인가"를 답한다. 응답이 실제로 어느 모델에서 왔는지(provider가 돌려준 model id)를
    싣는 축은 `EOS-111`이 소유한다. 그래서 docstring이 "실제 호출된"이라고 단정하지 않는다 —
    설정과 실제가 어긋나는 경로(폴백·프록시 라우팅)를 이 함수는 볼 수 없다.

    **회귀 이력**: 종전 판은 CLOUD_*에서 `anthropic_model_mid/high`를 **무조건** 읽었다.
    클라우드 슬롯이 항상 Anthropic이던 시절에는 참이었으나 `ARCH-57`이 셀렉터를 도입하며
    그 전제가 깨졌고, 그 사이 OpenRouter 좌석으로 돈 회차의 genlog가 `claude-sonnet-4-6`을
    적었다(2026-09-18 실측 · Phaiakes9 라이브 1회차). 출처 로그가 조용히 틀린 값을 적는
    상태였고 — 없는 기록보다 나쁘다, 읽는 사람이 믿기 때문이다.
    """
    cost = _as_cost_tier(decision.cost_tier)
    if cost is CostTier.LOCAL:
        return resolve_model(decision.local_family, decision.local_model)
    resolved = settings if settings is not None else get_settings()
    # 좌석→핀 매핑은 `l3/providers/factory.cloud_model_pins()`가 단일 근거다(EOS-111).
    # 여기서 다시 분기하면 좌석 집계와 이 함수가 갈라질 수 있고, 갈라지는 순간 둘 중
    # 하나는 거짓이 된다 — ARCH-58이 상환한 사고의 형태가 정확히 그것이다.
    # 알 수 없는 좌석의 raise도 그 함수가 담당한다(기본 좌석으로 접지 않는다).
    mid, high = cloud_model_pins(resolved)
    return mid if cost is CostTier.CLOUD_MID else high


def actual_cost_usd_or_none(decision: RoutingDecision, usage: Usage | None) -> float | None:
    """실측 비용(USD) 또는 미상(None) — '0원 확정'과 '산정 불가'를 구분한다(날조 금지).

    - LOCAL → 0.0 (Phaiakes9 0원 확정 — usage 유무 무관).
    - CLOUD_*인데 usage가 없거나 토큰이 미상 → None (미상 — pipeline `_record_trace` 동형).
      호출 자체가 없었던 경로(스킵·사전 오류)도 클라우드 결정이면 보수적으로 None이다 —
      "호출 안 됨=0원"과 "호출 실패=토큰 미상"을 결과만으로 가릴 수 없어 지어내지 않는다.
    - CLOUD_* + 토큰 실측 → 단가표 산정(`actual_cost_usd`).
    """
    cost = _as_cost_tier(decision.cost_tier)
    if cost is CostTier.LOCAL:
        return 0.0
    if usage is None or usage.input_tokens is None or usage.output_tokens is None:
        return None
    return actual_cost_usd(decision, usage)


def input_snapshot_for_prewarm(item: PregenItem) -> dict[str, Any]:
    """사전적재 항목 → 입력 스냅샷(전문+해시) — 재현 계약의 pregenerate측 조립(EOS-55).

    담는 것(전부 JSON 원시형 — canonical 직렬화·JSONB 왕복 안정):
      - `kind`: 스냅샷 판별자(경로별 형태가 달라 소비측이 분기할 수 있게).
      - `prompt`/`system`: 실제 전송 텍스트 **전문(verbatim)** — 스냅샷 자기완결의 핵심
        (#912 P1-1: 해시만 남기면 원본 specs 파일이 바뀌거나 사라진 뒤 모델 입력을 재구성할
        수 없다. 자체 저작 스펙이라 저작권 무관·행당 수 KB 허용).
      - `prompt_sha256`/`system_sha256`: 전문의 sha256 병기 — 무결성 대조 축(바이트 동일 핀).
      - `request`: 라우팅 신호 원문(`RoutingRequest` JSON 덤프) — 레코드만으로 *그대로
        복원*되는 구조 입력. 런타임 키 정합의 재료 전부가 여기 있다(03a §F.1).
      - `precomputed_response`(+`_sha256`): 인제스트 모드일 때만 — 외부 시드 응답도 이
        항목의 *입력*이므로 같은 원칙(전문+핀)으로 담는다(생성 모드는 키 자체가 없음 —
        모드가 스냅샷 형태로 드러난다).
    라우터 결정(decision)은 담지 않는다 — request에서 결정론 유도되는 파생물이고, 실제
    실행 모델은 `model_name` 컬럼이 별도로 기록한다.
    """
    snapshot: dict[str, Any] = {
        "kind": "l3.pregenerate.prewarm",
        "prompt": item.prompt,
        "system": item.system,
        "prompt_sha256": text_sha256(item.prompt),
        "system_sha256": text_sha256(item.system),
        "request": item.request.model_dump(mode="json"),
    }
    if item.precomputed_response is not None:
        snapshot["precomputed_response"] = item.precomputed_response
        snapshot["precomputed_response_sha256"] = text_sha256(item.precomputed_response)
    return snapshot


def generation_log_from_result(
    result: PrewarmItemResult,
    *,
    problem_id: uuid.UUID | None,
    model_name: str,
    provenance_id: uuid.UUID | None = None,
    prompt_template_id: uuid.UUID | None = None,
    cost_usd: float | None = None,
    prompt_version: str | None = None,
    seed: int | None = None,
    input_snapshot: Mapping[str, Any] | None = None,
    cu_slug: str | None = None,
) -> GenerationLog:
    """사전적재 항목 결과(`PrewarmItemResult`)를 `GenerationLog`로 변환한다(순수 함수).

    매핑:
      - `success`: `result.status ∈ {"written","skipped_exists"}` → True.
        (written/skipped_exists=유효 시드 확보=성공, failed_validation/error=실패)
      - `error_detail`: `result.error`(status별 의미는 `PrewarmItemResult` docstring).
      - `problem_id`/`model_name`/`provenance_id`/`prompt_template_id`: 인자에서 그대로.
        `problem_id`는 nullable이 됐다(EOS-55) — 사전적재 시드는 problem 레코드가 없어
        None이 정직하다(캐시 키 단위 자산). 다만 기본값은 두지 않는다 — 호출자가 "문제
        연결이 있는가"를 반드시 자문하게 한다(review_timer `elapsed_ms` 키워드 필수 동형).
      - `input_tokens`/`output_tokens`/`latency_ms`: `result.usage`(provider 실측)에서.
        usage가 None(인제스트 모드·usage 미노출)이면 종전대로 None — 지어내지 않는다.
        latency는 float(ms) 실측을 스키마 계약(int)에 맞춰 반올림한다.
      - `cache_read_input_tokens`/`cache_creation_input_tokens`(EOS-99): 같은 usage에서
        그대로. 캐시 개념이 없는 로컬 Ollama 경로는 provider가 채우지 않아 None이고, 그것이
        "해당 없음"의 정직한 표기다(0으로 접으면 '적중 0%'로 위장된다).
      - `cost_usd`: 인자에서 그대로(호출자가 `actual_cost_usd_or_none`으로 산정 — 로컬
        사전생성=0.0, 미상=None). 이 어댑터는 단가를 모른다(순수 변환).
      - `prompt_version`/`seed`: 재현 좌석(EOS-55) — *실제 쓰인 값만* 인자로 받는다.
        사전적재 경로는 프롬프트 템플릿 체계가 없어 `prompt_version`은 기본 None=미기록이다
        (번호를 발명하지 않는다). `seed`는 EOS-73부터 호출부가 `result.seed`(= provider에
        실제로 실려 나간 시드)를 넘긴다 — 이 어댑터는 여전히 *뽑지 않는다*(순수 변환). 호출이
        없었던 항목(인제스트·스킵)과 시드를 실을 수 없는 클라우드 결정은 None=미기록(날조 금지).
      - `input_snapshot`: 입력 스냅샷(전문+해시 — 자기완결) — 주어지면 `input_sha256`은
        schema validator가 canonical 해시로 자동 보충·봉인한다(해시 계산 정본은 schema 하나).
      - `cu_slug`: 생산 CU 조인 정체성(#912 P1-2) — 경로가 *실제 가진* 정체성만 기록한다.
        사전적재 캐시 시드는 CU 정체성이 없어 기본 None=미기록(코퍼스 slug를 아는 호출자는
        전달 — hit_cu_metrics CU 조인 축).
    """
    usage = result.usage
    latency_ms: int | None = None
    if usage is not None and usage.latency_ms is not None:
        # 실측은 float(ms), 스키마는 int(ms) — 반올림(음수 방어는 스키마 ge=0이 담당).
        latency_ms = int(round(usage.latency_ms))
    return GenerationLog(
        problem_id=problem_id,
        provenance_id=provenance_id,
        model_name=model_name,
        prompt_template_id=prompt_template_id,
        input_tokens=usage.input_tokens if usage is not None else None,
        output_tokens=usage.output_tokens if usage is not None else None,
        cache_read_input_tokens=(usage.cache_read_input_tokens if usage is not None else None),
        cache_creation_input_tokens=(
            usage.cache_creation_input_tokens if usage is not None else None
        ),
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        success=result.status in _SUCCESS_STATUSES,
        error_detail=result.error,
        prompt_version=prompt_version,
        seed=seed,
        input_snapshot=dict(input_snapshot) if input_snapshot is not None else None,
        cu_slug=cu_slug,
    )


def append_generation_log_jsonl(
    path: Path, log: GenerationLog, *, run_id: str | None = None
) -> GenerationLog:
    """GenerationLog 1건을 JSONL에 **즉시** append한다(호출마다 open→기록→flush→close).

    `generated_at`이 비어 있으면 append 시각(UTC)으로 스탬프한다 — JSONL 매체에서는
    append가 곧 생성 기록 시점이다(DB 경로의 `server_default now()`와 같은 역할·
    `harness/review_timer.append_event_jsonl` 동형). 스탬프된 레코드를 반환하므로
    호출자는 기록된 그대로의 사본을 갖는다(원본 불변 — model_copy).

    `run_id`(EOS-97 리콜 조인 축): 주어지고 레코드에 아직 없으면 함께 스탬프한다.
    `generated_at`과 같은 자리에서 찍는 이유는 같은 성질이기 때문이다 — **회차 정체성은
    개별 생성 호출이 아니라 그 호출을 감싼 회차가 안다**. 생성기는 자기가 몇 번째 회차에
    속하는지 모르고 알 필요도 없다(순수 변환 유지).

    이미 값이 있으면 **덮어쓰지 않는다** — 호출자가 명시로 실은 회차를 append 지점이
    바꾸면 그 레코드는 어느 회차 것인지 거짓말하게 된다.

    실패 경로(2026-08-22 규칙 ① "실패해도 증거가 남는가"): 마지막 일괄 저장이 아니라
    **레코드마다 flush**라, 배치 도중 프로세스가 죽어도 그때까지의 호출 이력은 파일에
    남는다.
    """
    updates: dict[str, Any] = {}
    if log.generated_at is None:
        updates["generated_at"] = datetime.now(UTC)
    if run_id is not None and log.run_id is None:
        updates["run_id"] = run_id
    stamped = log.model_copy(update=updates) if updates else log
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(stamped.model_dump_json() + "\n")
        fh.flush()
    return stamped


def load_generation_logs_jsonl(path: Path) -> tuple[list[GenerationLog], list[str]]:
    """JSONL에서 GenerationLog를 읽는다 — (유효 레코드, 실패 사유[타입명+줄 번호]) 튜플.

    파싱·검증 실패 줄은 삼키지 않고 사유로 수집한다(침묵 실패 금지 — **예외 타입명** +
    줄 번호 + 실패 필드 위치만 담는다. 필드 *값*·원문 줄은 넣지 않는다 — ValidationError
    문자열화는 input_value를 포함하므로 loc만 추출·`review_timer.load_events_jsonl` 동형).
    model_validate가 스냅샷↔해시 정합 validator를 다시 지나므로, 변조/파손된 스냅샷
    행은 여기서 실패 사유로 드러난다(재현 계약의 읽기측 봉인). 파일 부재는
    FileNotFoundError 전파 — "파일 없음"과 "레코드 0건"은 다른 실패다(미측정≠0).
    """
    logs: list[GenerationLog] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                logs.append(GenerationLog.model_validate(json.loads(text)))
            except ValidationError as exc:
                locs = ",".join(
                    "/".join(str(part) for part in err.get("loc", ())) or "(root)"
                    for err in exc.errors()
                )
                errors.append(f"line {line_no}: ValidationError: fields=[{locs}]")
            except Exception as exc:  # noqa: BLE001 — 사유 수집(타입명 보존)이 목적
                errors.append(f"line {line_no}: {type(exc).__name__}")
    return logs, errors
