"""MP-05 — 회차 앞머리 카나리 구간을 **검수 큐 JSONL로 잘라내는** CLI.

왜 이 모듈이 있는가 (실측 공백)
------------------------------
`MP-02` acceptance ②는 "카나리 30건을 100% 검수"를 요구하는데, **그 30건을 지목할 수단이
저장소에 없었다.** 카나리는 버리는 표본이 아니라 회차의 앞부분이라 통과분이 아무 표식 없이
나머지와 같은 파일에 섞인다 — `problem_corpus_accumulate.py:305-306`::

    카나리는 버리는 표본이 아니라 이 회차의 앞부분이므로, 통과분은 그대로 코퍼스에 append된다.

2026-09-06 실측: 코퍼스 행(`<out>.jsonl`)에도 검수 큐 행(`<out>.review.jsonl`)에도 phase·
canary 표식 필드가 **0건**이다. 그래서 "이 30건이 카나리였다"를 기계가 특정할 수 없고, 검수자는
회차 60건을 전부 보거나 임의로 30건을 고르게 된다 — 어느 쪽이든 게이트
`G-eos-first-run-canary-review`의 증적이 "카나리 30건 검수"라는 주장을 뒷받침하지 못한다.

유일하게 남아 있는 근거는 **genlog(`<out>.genlog.jsonl`)의 적재 순서**다. 생성 호출 1건당
1행이 발생 즉시 append되므로, 같은 `run_id` 행을 파일 순서대로 읽은 앞머리 N건이 곧 그 회차의
카나리 구간이다. 이 CLI는 그 순서를 유일한 식별 근거로 삼는다.

식별 근거 — 순서는 재정렬하지 않는다
-----------------------------------
genlog 행은 **파일에 적힌 순서 그대로** 소비한다. 정렬(slug·시각 등)하는 순간 "앞머리 N건"이
카나리 구간이 아니라 "이름순 N건"이 되어 근거가 통째로 무효가 된다 — 이 도구가 붙드는 계약의
전부가 그 순서다.

`canary_size`는 **회차 대장(`<out>.rounds.jsonl`) 행에서 읽는다**(MP-04 산출 필드). 추론·기본값
금지: 회차마다 다를 수 있고, `0`(관문 끔)과 `None`(미기록)은 서로 다른 처분이다 — `None`은
"모른다"이므로 30을 채워 넣지 않고 exit 1로 정직하게 멈춘다(모른다 ≠ 아니다).

해결(resolve) — 수용분은 코퍼스에서, 비수용분은 검수 큐에서
---------------------------------------------------------
카나리 시도 1건(genlog 행)의 `cu_slug`를 두 곳에서 찾는다:

  1. 코퍼스 `<out>.jsonl` — 수용되어 append된 행(검수 큐에는 없다).
  2. 검수 큐 `<out>.review.jsonl` — 비수용 outcome 행(기계 사유·후보 전문 동반).

어느 쪽에서도 못 찾은 행은 **조용히 버리지 않는다**(침묵 실패 금지). 사유는 서로 구별되는
3종이며(`MissingCuSlug`·`SlugNotFound`·`GenlogShortfall`), 요약 JSON에 건별로 전부 실린다.

왜 `--limit` 같은 절단 옵션이 없는가
-----------------------------------
이 도구의 산출은 "100% 검수"의 분모다. 표시 상한이 검수 범위를 결정하면 잘린 쪽이 검수되지
않은 채 "카나리 전건 검수"로 보고된다 — `ops/generation_recall`이 `--limit`와 `--apply`의 동시
사용을 거부하는 것과 같은 이유다(표시 상한이 처분 범위를 결정하면 안 된다). 그래서 절단 옵션
자체를 두지 않는다.

7계층 — 하네스 도구
------------------
파일만 읽는다(LLM 0·DB 0·네트워크 0). L3 생성기·L4 교수학을 부르지 않으며, 사이드카 경로
규약과 스키마 로더만 재사용한다(경로 산식을 여기 다시 적으면 truth source가 둘이 된다).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.harness.anchor_round_ledger import (
    RoundRecord,
    default_round_ledger_path,
    load_round_ledger,
)
from whymath_backend.harness.needs_review_worklist import (
    ReviewQueueEntry,
    load_review_queue_jsonl,
)
from whymath_backend.harness.problem_corpus_accumulate import (
    default_generation_log_path,
    default_review_queue_path,
)
from whymath_backend.l3.pregenerate.provenance_bridge import load_generation_logs_jsonl

__all__ = [
    "REASON_GENLOG_SHORTFALL",
    "REASON_MISSING_CU_SLUG",
    "REASON_SLUG_NOT_FOUND",
    "STATUS_CORPUS_RESOLVED",
    "CanarySlice",
    "build_canary_slice",
    "load_corpus_rows",
    "main",
    "select_round_record",
]

# 코퍼스에서 해결된 행의 status — **오케스트레이터 outcome 어휘가 아니다**(그 값을 쓰면 우리가
# 읽지도 않은 outcome 상태를 주장하게 된다). "이 slug가 코퍼스 파일에 있다 = 수용·적재됐다"는
# 이 도구의 관측만을 말하는 자기서술 라벨이다. 검수 TUI는 `[status] slug` 형태로 그대로 보여
# 주므로, 검수자는 이 행이 큐에서 온 비수용 후보가 아님을 한눈에 구분한다.
STATUS_CORPUS_RESOLVED = "canary_accepted"

# 미해결 사유 3종 — 서로 다른 처분을 부르므로 한 글자로 뭉치지 않는다.
#   MissingCuSlug   : 생성이 후보 조립에 도달하지 못해 정체성 자체가 없다(검수할 CU가 없음).
#   SlugNotFound    : 정체성은 있는데 코퍼스·검수 큐 어디에도 없다(적재 누락 의심 — 조사 대상).
#   GenlogShortfall : genlog 행이 canary_size보다 적다(회차 중단 — 카나리 구간이 덜 생성됨).
REASON_MISSING_CU_SLUG = "MissingCuSlug"
REASON_SLUG_NOT_FOUND = "SlugNotFound"
REASON_GENLOG_SHORTFALL = "GenlogShortfall"


@dataclass(frozen=True, slots=True)
class CanarySlice:
    """카나리 구간 절단 결과 — 검수 큐 행과 **미해결 근거**를 함께 들고 다닌다.

    `rows`만 반환하면 못 찾은 시도가 조용히 사라진다. 미해결은 결과의 일부이지 부작용이
    아니므로 같은 값에 담아 호출자가 버릴 수 없게 한다(침묵 실패 금지).
    """

    run_id: str
    canary_size: int
    genlog_rows: int
    """이 회차(run_id)에 속한 genlog 행 수 — 절단 전 분모."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    """검수 큐 JSONL로 쓸 행(각 행이 `slug` 키를 갖는다 — review_session이 그대로 먹는다)."""

    unresolved: list[dict[str, Any]] = field(default_factory=list)
    """해결하지 못한 카나리 슬롯 — `reason`·`canary_index`·`detail` 동반."""

    @property
    def sliced(self) -> int:
        """실제로 잘라 본 카나리 슬롯 수 — `min(canary_size, genlog_rows)`."""
        return min(self.canary_size, self.genlog_rows)

    @property
    def missing_slots(self) -> int:
        """genlog 부족분(중단된 회차) — 0이면 회차가 카나리 구간을 다 돌았다는 뜻."""
        return max(0, self.canary_size - self.genlog_rows)

    def unresolved_counts(self) -> dict[str, int]:
        """사유별 미해결 집계 — 사유가 뭉개지면 조치가 갈리지 않는다."""
        counts: dict[str, int] = {}
        for item in self.unresolved:
            reason = str(item["reason"])
            counts[reason] = counts.get(reason, 0) + 1
        return counts


def select_round_record(
    records: list[RoundRecord], run_id: str | None
) -> tuple[RoundRecord | None, str, str]:
    """대장에서 대상 회차 1건을 고른다 — (레코드, 선택 방식, 사유) 튜플.

    `run_id`가 없으면 대장의 **마지막 행**(가장 최근 회차)을 쓴다. 어느 회차를 골랐는지는
    호출자가 반드시 출력한다 — 조용히 고르면 검수자가 어제 회차를 오늘 것으로 읽는다.

    같은 `run_id`가 여러 행이고 그 행들의 `canary_size`가 **서로 다르면** 고르지 않는다
    (None 반환) — 어느 값이 이 회차의 카나리 크기인지 모르는 상태에서 하나를 집으면 그 절단은
    근거 없는 숫자가 된다(모른다 ≠ 아니다).
    """
    if not records:
        return None, "none", "대장에 유효 회차 행이 0건이다."
    if run_id is None:
        return records[-1], "ledger_last", "대장 마지막 행(가장 최근 회차)을 골랐다."
    matched = [record for record in records if record.run_id == run_id]
    if not matched:
        return None, "explicit", f"대장에 run_id={run_id} 행이 없다."
    distinct = {record.canary_size for record in matched}
    if len(matched) > 1 and len(distinct) > 1:
        return (
            None,
            "explicit",
            (
                f"run_id={run_id} 행이 {len(matched)}건인데 canary_size가 서로 다르다"
                f"(관측 {sorted(str(size) for size in distinct)}) — 어느 값이 이 회차의 카나리"
                " 크기인지 결정할 수 없다."
            ),
        )
    return matched[-1], "explicit", f"run_id={run_id} 행을 골랐다."


def load_corpus_rows(path: Path) -> tuple[dict[str, tuple[int, dict[str, Any]]], list[str]]:
    """코퍼스 JSONL → `slug → (줄 번호, 행 dict)` 색인. (색인, 실패 사유) 튜플.

    `Problem.model_validate`를 하지 **않는다**(`ops/generation_recall.load_slug_index` 동형) —
    필요한 것은 `slug` 하나이고, 무관한 필드의 검증 실패로 해결 가능한 행까지 잃는 것이 더
    나쁘다. 파싱·키 부재는 사유로 수집한다(**예외 타입명** + 줄 번호만 — 필드 값은 싣지
    않는다). 같은 slug가 두 번 있으면 **먼저 읽은 쪽을 유지**하고 충돌을 사유로 남긴다.
    """
    index: dict[str, tuple[int, dict[str, Any]]] = {}
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row: Any = json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"{path.name} line {line_no}: {type(exc).__name__}")
                continue
            if not isinstance(row, dict):
                errors.append(f"{path.name} line {line_no}: TypeError(not an object)")
                continue
            slug = row.get("slug")
            if not isinstance(slug, str) or not slug:
                errors.append(f"{path.name} line {line_no}: KeyError(slug)")
                continue
            if slug in index:
                errors.append(f"{path.name} line {line_no}: DuplicateSlug(first kept)")
                continue
            index[slug] = (line_no, row)
    return index, errors


def _queue_index(
    entries: list[ReviewQueueEntry], run_id: str
) -> tuple[dict[str, ReviewQueueEntry], dict[str, ReviewQueueEntry], list[str]]:
    """검수 큐 행 → 색인 **두 벌**: (이 회차 전용, 전체) + 충돌 사유.

    왜 두 벌인가 (2026-09-07 · PR #1021 Codex P1)
    --------------------------------------------
    한 벌만 두면 *어느 회차의* 판정인지 구별할 수 없다. 그런데 카나리 후보가 기존 코퍼스
    문항과 구조가 같으면 오케스트레이터는 **이번 회차**의 시도를 `rejected_duplicate`로 큐에
    적고, 그 slug는 **옛 회차**에 적재된 코퍼스 행과도 일치한다. 회차 구분 없이 코퍼스를 먼저
    보면 이번 회차의 거부가 옛 회차의 수용으로 덮여 `canary_accepted`로 보고된다 —
    검수자는 실제 판정과 그 사유를 영영 못 본다.

    `ReviewQueueEntry.run_id`는 필수 필드라 이 구분은 데이터로 가능하다(추론이 아니다).

    같은 slug가 회차를 넘어 재출현하는 것은 큐의 정상 동작이므로(재시도) 실패가 아니라 사유
    수집 대상이다. slug 없는 행(생성 실패 후보)은 색인 키가 없어 애초에 조인 대상이 아니다.
    """
    scoped: dict[str, ReviewQueueEntry] = {}
    index: dict[str, ReviewQueueEntry] = {}
    errors: list[str] = []
    for entry in entries:
        if entry.slug is None:
            continue
        if entry.run_id == run_id and entry.slug not in scoped:
            scoped[entry.slug] = entry
        if entry.slug in index:
            errors.append(f"review queue line {entry.source_line}: DuplicateSlug(first kept)")
            continue
        index[entry.slug] = entry
    return scoped, index, errors


def build_canary_slice(
    *,
    run_id: str,
    canary_size: int,
    cu_slugs: list[str | None],
    corpus_index: dict[str, tuple[int, dict[str, Any]]],
    queue_index: dict[str, ReviewQueueEntry],
    corpus_name: str,
    queue_name: str,
    run_queue_index: dict[str, ReviewQueueEntry] | None = None,
) -> CanarySlice:
    """카나리 구간 절단(순수 — 파일 I/O 0).

    `cu_slugs`는 **해당 run_id의 genlog 행을 적재 순서 그대로** 늘어놓은 `cu_slug` 열이다
    (None = 그 시도가 후보 조립에 도달하지 못함). 이 함수는 그 순서를 건드리지 않는다 —
    앞에서 `canary_size`개를 자르는 것이 이 도구의 식별 근거 전부다.

    해결원 우선순위는 **이번 회차의 판정이 언제나 먼저**다:

      ① `run_queue_index` — 선택한 run_id가 이 slug에 대해 남긴 검수 큐 행. 이번 회차가 실제로
         내린 판정이므로 다른 무엇보다 우선한다.
      ② `corpus_index` — 코퍼스에 있다 = 수용·적재됐다(이 도구의 관측).
      ③ `queue_index` — 회차 무관 큐 행. ①이 없고 코퍼스에도 없을 때의 마지막 단서다.

    ②를 ① 앞에 두면 **이번 회차의 거부가 옛 회차의 수용으로 덮인다** — 후보가 기존 문항과
    구조가 같아 `rejected_duplicate`로 차단된 경우가 정확히 그 형태이고, 그때 코퍼스 행은
    *다른 회차가 적재한 다른 시도*다(2026-09-07 실측·PR #1021 Codex P1).

    반환 계약: `len(rows) + len(unresolved) == canary_size`. 카나리 슬롯은 하나도 사라지지
    않는다 — genlog가 부족해 시도 자체가 없던 슬롯도 `GenlogShortfall` 미해결로 남는다
    (부족을 조용히 넘기면 "카나리 12건 전건 검수"가 "30건 전건 검수"로 보고된다).
    """
    sliced = cu_slugs[:canary_size]
    rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for offset, cu_slug in enumerate(sliced):
        index = offset + 1  # 1-기반 — 검수자가 "카나리 3번째"로 부르는 그 번호
        marker = f"canary_slice: run {run_id} 카나리 {index}/{canary_size}"
        if cu_slug is None:
            unresolved.append(
                {
                    "canary_index": index,
                    "run_id": run_id,
                    "cu_slug": None,
                    "reason": REASON_MISSING_CU_SLUG,
                    "detail": (
                        "genlog 행의 cu_slug가 None — 생성이 후보 조립에 도달하지 못해 정체성이"
                        " 없다(검수할 CU 자체가 없으므로 큐에 넣지 않는다)."
                    ),
                }
            )
            continue
        # ① 이번 회차가 이 slug에 대해 내린 판정이 있으면 그것이 정답이다(회차 스코프 우선).
        scoped_hit = (run_queue_index or {}).get(cu_slug)
        if scoped_hit is not None:
            row = scoped_hit.model_dump(mode="json")
            row["reasons"] = [
                f"{marker} — 이번 회차 판정: 검수 큐 {queue_name} (run {run_id})",
                *scoped_hit.reasons,
            ]
            row["canary_index"] = index
            row["resolved_from"] = "review_queue_this_run"
            rows.append(row)
            continue
        corpus_hit = corpus_index.get(cu_slug)
        if corpus_hit is not None:
            corpus_line, corpus_row = corpus_hit
            rows.append(
                {
                    "slug": cu_slug,
                    "status": STATUS_CORPUS_RESOLVED,
                    "reasons": [f"{marker} — 수용분: 코퍼스 {corpus_name} line {corpus_line}"],
                    "canary_index": index,
                    "run_id": run_id,
                    "resolved_from": "corpus",
                    "source_line": corpus_line,
                    # 후보 전문 — 검수자가 행만으로 문항·정답·검산 조건을 본다(큐 행의
                    # candidate_payload와 같은 자리·같은 직렬화).
                    "candidate_payload": corpus_row,
                }
            )
            continue
        queue_hit = queue_index.get(cu_slug)
        if queue_hit is not None:
            row = queue_hit.model_dump(mode="json")
            # 기계 사유는 보존하고 카나리 표식을 **앞에** 덧붙인다 — 검수 TUI가 reasons를
            # 그대로 보여 주므로, 이 행이 회차의 몇 번째 카나리인지 검수자가 즉시 안다.
            row["reasons"] = [f"{marker} — 비수용분: 검수 큐 {queue_name}", *queue_hit.reasons]
            row["canary_index"] = index
            row["resolved_from"] = "review_queue"
            rows.append(row)
            continue
        unresolved.append(
            {
                "canary_index": index,
                "run_id": run_id,
                "cu_slug": cu_slug,
                "reason": REASON_SLUG_NOT_FOUND,
                "detail": (
                    f"cu_slug가 코퍼스({corpus_name})·검수 큐({queue_name}) 어디에도 없다 —"
                    " 적재 누락 의심(조사 대상). 이 시도는 검수 큐에 실을 근거가 없다."
                ),
            }
        )

    for offset in range(len(sliced), canary_size):
        index = offset + 1
        unresolved.append(
            {
                "canary_index": index,
                "run_id": run_id,
                "cu_slug": None,
                "reason": REASON_GENLOG_SHORTFALL,
                "detail": (
                    f"이 회차의 genlog 행이 {len(cu_slugs)}건뿐이라 카나리 {index}번째 시도가"
                    " 존재하지 않는다(회차 중단 — 카나리 구간이 끝까지 생성되지 않았다)."
                ),
            }
        )

    return CanarySlice(
        run_id=run_id,
        canary_size=canary_size,
        genlog_rows=len(cu_slugs),
        rows=rows,
        unresolved=unresolved,
    )


def _fail(message: str) -> int:
    """측정 실패·모름 — stderr에 사유를 남기고 exit 1. 산출 파일은 만들지 않는다."""
    sys.stderr.write(f"[측정 실패] {message}\n")
    return 1


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점 — exit 0=성공, 1=측정 실패·모름, 2=인자 오류(argparse 기본)."""
    parser = argparse.ArgumentParser(
        prog="canary_slice",
        description=(
            "회차 앞머리 카나리 구간을 검수 큐 JSONL로 잘라낸다(MP-05). 식별 근거는 genlog의 "
            "적재 순서이고, 크기는 회차 대장의 canary_size다."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help=(
            "축적 코퍼스 JSONL 경로 — problem_corpus_accumulate --out과 같은 값. 사이드카 3종"
            "(.rounds.jsonl 대장 / .genlog.jsonl 생성 로그 / .review.jsonl 검수 큐)을 여기서 "
            "파생한다."
        ),
    )
    parser.add_argument(
        "--queue-out",
        type=Path,
        required=True,
        help=(
            "카나리 검수 큐 산출 JSONL 경로(덮어쓰기). review_session --queue가 그대로 먹는 "
            "형식이다. append가 아닌 이유: 이 파일은 회차에서 파생되는 값이라 재실행하면 같은 "
            "행이 두 번 쌓여 분모가 부풀기 때문이다."
        ),
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "대상 회차 식별자(완전 일치). 생략하면 대장의 마지막 행(가장 최근 회차)을 쓰고, "
            "어느 회차를 골랐는지 요약에 명시한다."
        ),
    )
    args = parser.parse_args(argv)

    out_path: Path = args.out
    queue_out: Path = args.queue_out
    ledger_path = default_round_ledger_path(out_path)
    genlog_path = default_generation_log_path(out_path)
    review_path = default_review_queue_path(out_path)

    # 산출 경로가 입력 경로를 덮으면 회차 증거가 파괴된다 — 되돌릴 수 없으므로 인자 단계에서
    # 거부한다(exit 2).
    reserved = {
        out_path.resolve(): "코퍼스",
        ledger_path.resolve(): "회차 대장",
        genlog_path.resolve(): "생성 로그",
        review_path.resolve(): "검수 큐",
    }
    clash = reserved.get(queue_out.resolve())
    if clash is not None:
        parser.error(f"--queue-out이 {clash} 입력 경로와 같다 — 입력을 덮어쓸 수 없다.")

    if not ledger_path.exists():
        return _fail(
            f"회차 대장 없음: {ledger_path} — 대장이 없으면 canary_size를 알 수 없다"
            "(0건 성공이 아니다)."
        )
    records, ledger_errors = load_round_ledger(ledger_path)
    if ledger_errors and args.run_id is None:
        # 기본 선택은 "대장 마지막 행 = 가장 최근 회차"라고 **주장**한다. 그런데 물리적으로
        # 마지막인 행이 손상돼 건너뛰어졌다면 그 주장은 거짓이고, 도구는 *이전* 회차의 카나리를
        # 최신 회차인 양 검수 큐로 내보낸다(2026-09-07 실측·PR #1021 Codex P1 — 손상 행 1건에
        # exit 0 + "가장 최근 회차를 골랐다" note를 달고 R_OLD를 골랐다).
        #
        # 손상 행의 run_id는 **읽을 수 없으므로** 그것이 최신 회차인지 아닌지 판정할 방법이
        # 없다 — 모른다 ≠ 아니다. 그래서 자동 선택을 거부하고 사람에게 넘긴다. `--run-id`로
        # 회차를 명시하면 "가장 최근"이라는 주장 자체를 하지 않으므로 그때는 진행한다.
        return _fail(
            f"회차 대장에 손상된 행 {len(ledger_errors)}건이 있어 '가장 최근 회차'를 자동으로 "
            f"고를 수 없다 — 손상 행이 최신 회차인지 알 수 없기 때문이다. `--run-id <회차>`로 "
            f"명시하라. 손상 사유: {ledger_errors}"
        )
    record, selection, selection_note = select_round_record(records, args.run_id)
    if record is None:
        broken = f" (대장 로드 실패 {len(ledger_errors)}행)" if ledger_errors else ""
        return _fail(f"{selection_note}{broken}")

    canary_size = record.canary_size
    if canary_size is None:
        # 모른다 ≠ 아니다 — 30을 기본값으로 채우면 이 도구가 근거 없는 30건을 "카나리"로
        # 주장하게 된다. 구행(MP-04 이전 기록)이 정확히 이 경우다.
        return _fail(
            f"run_id={record.run_id} 회차의 canary_size가 미기록(None)이다 — 이 회차가 카나리 "
            "몇 건으로 돌았는지 알 수 없다. 기본값을 가정해 채우지 않는다(모른다 ≠ 아니다)."
        )
    if canary_size < 0:
        return _fail(
            f"run_id={record.run_id} 회차의 canary_size가 음수({canary_size})다 — 대장 행이 "
            "손상됐다."
        )

    if not genlog_path.exists():
        return _fail(
            f"생성 로그 없음: {genlog_path} — 카나리 구간의 유일한 식별 근거(적재 순서)가 "
            "없으므로 절단할 수 없다."
        )
    logs, genlog_errors = load_generation_logs_jsonl(genlog_path)
    if genlog_errors:
        # **적재 순서가 이 도구의 유일한 정체성 근거**다(모듈 docstring ①). 로더는 파싱 실패
        # 행을 목록에서 **빼 버리므로**, 앞쪽 한 줄이 깨지면 뒤 행이 통째로 한 칸씩 당겨진다 —
        # 시도 2·3·4번이 "카나리 1·2·3번"으로 출력되고 exit 0이 난다(2026-09-07 실측·PR #1021
        # Codex P1: 1행 파손으로 s2·s3·s4가 카나리 1~3번이 됐다).
        #
        # 자리표시자로 위치를 보존하는 대안은 성립하지 않는다: 깨진 행의 `run_id`를 읽을 수
        # 없어 **그 행이 이 회차 것인지조차 판정할 수 없기** 때문이다(모른다 ≠ 아니다).
        # 그래서 부분 산출을 제공하지 않고 측정 실패로 끝낸다 — 잘못된 30건을 "카나리 전건"으로
        # 검수하는 것보다 측정을 한 번 더 하는 편이 싸다.
        return _fail(
            f"생성 로그에 손상된 행 {len(genlog_errors)}건이 있다 — 적재 순서가 카나리 구간의 "
            f"유일한 식별 근거라, 행이 하나라도 빠지면 뒤 시도가 앞당겨져 **다른 구간**이 "
            f"카나리로 보고된다. 손상 행의 run_id를 읽을 수 없어 이 회차 것인지도 판정할 수 "
            f"없으므로 부분 산출도 내지 않는다. 손상 사유: {genlog_errors}"
        )
    # 순서 계약 — 파일 순서 그대로다. 정렬하면 "앞머리 N건"이 카나리 구간이 아니게 된다.
    cu_slugs: list[str | None] = [log.cu_slug for log in logs if log.run_id == record.run_id]

    corpus_present = out_path.exists()
    queue_present = review_path.exists()
    if canary_size > 0 and not corpus_present and not queue_present:
        return _fail(
            f"해결원이 둘 다 없다(코퍼스 {out_path} · 검수 큐 {review_path}) — 카나리 "
            f"{canary_size}건을 어디에서도 해결할 수 없다."
        )

    corpus_index: dict[str, tuple[int, dict[str, Any]]] = {}
    corpus_errors: list[str] = []
    if corpus_present:
        corpus_index, corpus_errors = load_corpus_rows(out_path)
    queue_index: dict[str, ReviewQueueEntry] = {}
    run_queue_index: dict[str, ReviewQueueEntry] = {}
    queue_load_errors: list[str] = []
    queue_dup_errors: list[str] = []
    if queue_present:
        queue_entries, queue_load_errors = load_review_queue_jsonl(review_path)
        run_queue_index, queue_index, queue_dup_errors = _queue_index(queue_entries, record.run_id)

    # 코퍼스·검수 큐의 손상도 **측정 실패**다 — 대장·genlog와 같은 뿌리이므로 같이 닫는다.
    #
    # 왜 원본별로 봐주지 않는가: 손상 행의 slug를 읽을 수 없으므로 그 행이 카나리 구간의
    # 어느 후보였는지 판정할 방법이 없다(모른다 ≠ 아니다). 코퍼스 행이 깨지면 그 후보는
    # `SlugNotFound`로 *보이거나* 더 나쁘게는 **옛 회차 큐 행**으로 해결돼 엉뚱한 판정이
    # 붙고, 큐 행이 깨지면 이번 회차의 거부가 사라져 코퍼스의 옛 수용분이 `canary_accepted`로
    # 보고된다 — 둘 다 exit 0으로 조용히 나간다.
    #
    # 이 네 파일은 같은 파이프라인이 append로 쓰는 기계 산출물이라 손상 자체가 이상 사건이다.
    # 산출물이 게이트 증적(`G-eos-first-run-canary-review`)이 되는 이상, "일부는 읽었다"로
    # 넘어가는 예외 경로를 두지 않는다 — 예외 경로가 곧 다음 구멍이 된다.
    source_errors = {
        "corpus": corpus_errors,
        "review_queue": [*queue_load_errors, *queue_dup_errors],
    }
    broken_sources = {name: errs for name, errs in source_errors.items() if errs}
    if broken_sources:
        return _fail(
            "해결원에 손상된 행이 있다 — 손상 행이 어느 후보였는지 읽을 수 없어 카나리 판정을 "
            f"신뢰할 수 없다(해당 줄을 고친 뒤 다시 돌려라). {broken_sources}"
        )

    result = build_canary_slice(
        run_id=record.run_id,
        canary_size=canary_size,
        cu_slugs=cu_slugs,
        corpus_index=corpus_index,
        queue_index=queue_index,
        corpus_name=out_path.name,
        queue_name=review_path.name,
        run_queue_index=run_queue_index,
    )

    slugs = [str(row["slug"]) for row in result.rows]
    distinct = len(set(slugs))
    summary: dict[str, Any] = {
        "run_id": record.run_id,
        "run_id_selection": selection,
        "run_id_selection_note": selection_note,
        "ledger_path": str(ledger_path),
        "genlog_path": str(genlog_path),
        "corpus_path": str(out_path),
        "review_queue_path": str(review_path),
        "queue_out": str(queue_out),
        "corpus_present": corpus_present,
        "review_queue_present": queue_present,
        "canary_size": canary_size,
        "genlog_rows_total": len(logs),
        "genlog_rows_for_run": result.genlog_rows,
        "sliced": result.sliced,
        "emitted": len(result.rows),
        "emitted_distinct_slugs": distinct,
        # 같은 slug가 두 번 실리면 review_session이 DuplicateSlug로 한 번만 검수한다 —
        # 그러면 실검수 건수가 산출 건수보다 적다. 그 차이를 요약이 먼저 말한다.
        "duplicate_slug_rows": len(slugs) - distinct,
        "resolved_from": {
            # 이번 회차 큐를 별도 칸으로 센다 — 코퍼스 수용분과 합치면 "이번 회차가 실제로
            # 거부한 건수"가 요약에서 사라진다.
            "review_queue_this_run": sum(
                1 for row in result.rows if row["resolved_from"] == "review_queue_this_run"
            ),
            "corpus": sum(1 for row in result.rows if row["resolved_from"] == "corpus"),
            "review_queue": sum(1 for row in result.rows if row["resolved_from"] == "review_queue"),
        },
        "unresolved_count": len(result.unresolved),
        "unresolved_counts": result.unresolved_counts(),
        # 미해결은 전건을 싣는다(절단 없음) — 여기서 자르면 그 행이 조용히 사라진다.
        "unresolved": result.unresolved,
        "shortfall": (
            None
            if result.missing_slots == 0
            else {
                "expected": canary_size,
                "observed": result.genlog_rows,
                "missing": result.missing_slots,
            }
        ),
        "load_errors": {
            "ledger": ledger_errors,
            "genlog": genlog_errors,
            "corpus": corpus_errors,
            "review_queue": [*queue_load_errors, *queue_dup_errors],
        },
    }

    if canary_size > 0 and not result.rows:
        # 산출 0건은 "검수할 것이 없다"가 아니라 **잘라내기 실패**다. 빈 큐를 남기면 검수자가
        # 0건을 검수하고 "카나리 전건 검수"로 보고하게 된다 — 파일을 만들지 않고 실패한다.
        summary["written"] = False
        summary["exit_code"] = 1
        json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return _fail(
            f"카나리 {canary_size}건 중 해결 0건 — 검수 큐를 만들지 않는다"
            f"(미해결 사유: {result.unresolved_counts()})."
        )

    queue_out.parent.mkdir(parents=True, exist_ok=True)
    with queue_out.open("w", encoding="utf-8") as handle:
        for row in result.rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()

    summary["written"] = True
    summary["exit_code"] = 0
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if result.missing_slots > 0:
        # 부분 산출 — 성공이지만 분모가 줄었다는 사실을 stderr에도 낸다(stdout이 파이프로
        # 빨려 들어가도 사람 눈에 남게).
        sys.stderr.write(
            f"[부분 산출] 카나리 {canary_size}건 중 genlog 행은 {result.genlog_rows}건뿐이다"
            f"(부족 {result.missing_slots}건 — 회차 중단). 검수 분모는 {len(result.rows)}건이다.\n"
        )
    if result.unresolved:
        sys.stderr.write(f"[미해결] {result.unresolved_counts()} — 요약 JSON에 건별 사유가 있다.\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
