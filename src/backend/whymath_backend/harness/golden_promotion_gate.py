"""골든 승격 **경로 게이트** — 경로 밖 승격을 exit 1로 막는다 (EOS-64 ③).

무엇을 막는가
------------
축적 CLI(`problem_corpus_accumulate`)가 내는 v0 코퍼스는 **사람 검수 전**이다(그 모듈 docstring:
"게이트 통과 ≠ 학생 노출"). 그런데 v0에서 노출 가능 상태로 가는 길에는 아무 잠금이 없었다 —
누군가 코퍼스 JSONL의 `review_status`를 손으로 `approved`로 고치면 `l6/_shared.is_review_cleared`
가 그대로 통과시키고 학생에게 노출된다. 즉 **승격의 경로가 규약(산문)으로만 존재**했다.

이 게이트는 승격 제안(promotion proposal)을 받아 정본 경로 4단을 전부 통과했는지 확인하고,
하나라도 빠지면 **exit 1**을 낸다. 정본 경로:

    ① 코퍼스 실재(축적 CLI가 수용·저장한 후보)  →  ② 사람 검수 판정(HIT 이벤트)  →
    ③ review_status 각인(각인 도구 감사로그 값 = 코퍼스 값 = approved)  →
    ④ Wilson 결함율 상한 게이트(검수 배치 전체 — 제안만이 아니다)

③단의 각인 도구는 코퍼스 부류마다 하나다(EOS-136 — 계약 정본
`docs/standards/review_status_stamping_contract.md`): 축적 CLI의 **회차 코퍼스**는 사람 판정을
slug별로 옮기는 `harness/review_status_verdict_bridge`, 고정 코퍼스 7종(`KNOWN_CORPORA`)은
감사 라벨 표본으로 코퍼스 전체를 판정하는 `harness/problem_corpus_review_status_backfill`이다.
이 게이트는 어느 도구의 감사로그든 같은 형식(`slug`·`review_status`)으로 읽는다.

경로 밖 승격의 구체형 9종을 각각 다른 사유로 거부한다(뭉뚱그린 "거부" 금지 — 조치가 다르다):
`not_in_corpus` · `no_human_verdict` · `human_verdict_rejected` ·
`human_verdict_needs_edit`(사람이 "손질하면 쓸 수 있다"로 판정 — 지금 내용은 승인되지 않았다) ·
`review_content_changed`(사람 판정 뒤 코퍼스 내용이 바뀌었다 — 검수 지문 ≠ 현재 지문, EOS-27) ·
`review_fingerprint_unverifiable`(판정 이벤트에 내용 지문이 없다 — 모름은 일치가 아니다, EOS-27) ·
`review_status_not_backfilled`(각인 감사로그에 각인 기록 없음 = 손각인 의심) ·
`review_status_audit_mismatch`(감사로그 각인값 ≠ 코퍼스 현재값 = 각인 후 손편집 의심) ·
`review_status_not_approved`(감사로그·코퍼스가 일치하되 값이 approved가 아님).

왜 `approved_with_edit`는 ②단을 통과하지 못하는가 (EOS-136)
----------------------------------------------------------
검수 CLI(`harness/review_session`)의 `e` 키는 "손질하면 쓸 수 있다"이고(MP-02 검수 런북 판정
키 표), 그 도구는 **손질 내용을 저장하지 않는다** — 판정만 이벤트로 남는다. 따라서 코퍼스에
있는 것은 여전히 *손질 전* 내용이며, 골든 계약도 그 내용을 as-found `defective`로 라벨링한다
(`docs/standards/golden_benchmark_contract.md` — `edit_aware_verdict`). 그 내용을 승격시키면
사람이 "이대로는 못 쓴다"고 본 문항이 학생에게 나간다. `schema/review_timer.
review_status_for_verdict`가 이 판정을 `approved`로 옮기는 것은 *손질이 반영된 내용*에 대한
노출 어휘 변환이고, 여기서 막는 것은 *손질이 반영되지 않은 내용*이다 — 두 축은 충돌하지 않는다.
승격 경로는 "손질 반영 → 재검수(`approved`)"다(재검수의 종결이 최신 판정이 된다).
판정 술어는 `certifies_current_content` 하나이며 각인 도구가 같은 술어를 import해 쓴다(게이트와
각인 도구가 한 판정을 다르게 읽지 않게).

왜 ②단이 "판정 실재"에서 멈추지 않고 내용 지문까지 보는가 (EOS-27)
-----------------------------------------------------------------
②단은 최신 사람 판정이 `approved`인지만 봤고, ③단은 `review_status` **값**(감사값 = 코퍼스값)만
대조했다. 둘 다 문항 *내용*은 보지 않는다 — 사람이 승인한 뒤 누군가 문항을 손으로 고치면(정답·해설·
조건) 승인·각인·감사로그가 전부 그대로여서 게이트가 통과시킨다. 검수 이벤트가 검수자가 본 레코드의
지문(`content_fingerprint`)을 싣게 되었으므로(`review_session`), 게이트는 승인 판정의 지문과 코퍼스
현재 레코드의 지문(`schema/review_timer.review_content_fingerprint`)을 대조한다:

  · 다르다            → `review_content_changed` (승인이 인증한 내용이 아니다 — 조치: 재검수)
  · 이벤트에 지문 없음 → `review_fingerprint_unverifiable` (옛 이벤트 · 모름 ≠ 일치 — 조치: 재검수)
  · 같다              → 통과 (③단 이하로 진행)

대조는 `evaluate_promotion(review_fingerprints=, corpus_fingerprints=)`를 **둘 다** 넘길 때 켜진다
(순수 함수라 파일을 못 읽는다). 생략하면 `fingerprint_checked=False`로 리포트에 *미수행*을 자백한다
— CLI는 항상 넘기며 인자로 끌 수 없다. 반려·손질 승인은 이미 ②단에서 막히므로 지문을 보지 않는다.

왜 ①단이 "검수 큐 등재"가 아니라 "코퍼스 실재"인가 (2026-09-01 codex P1 실측)
--------------------------------------------------------------------------
초판은 ①단을 **검수 큐 멤버십**(`<out>.review.jsonl`)으로 걸었다. 그 게이트는 실제 파이프라인
산출물을 **한 건도** 통과시킬 수 없다 — 구조적으로 0건이다:

  · `problem_corpus_accumulate.run_corpus_accumulate`는 `outcome.status not in ("accepted_stored",
    "accepted")`인 것**만** `review_sink`(검수 큐)로 흘리고, 코퍼스 JSONL에는 **수용된 것만**
    append한다. 즉 두 산출물의 slug 집합은 **정의상 서로소**다.
  · 그 서로소는 우연이 아니라 동결된 불변이다 — `tests/backend/harness/
    test_needs_review_worklist.py`가 "수용(accepted_stored·accepted)은 워크리스트/큐에서 제외"를
    핵심 계약으로 붙든다.

따라서 "코퍼스에 있다 AND 큐에 있다"는 **동시에 참일 수 없는** 조건이었고, 게이트는 아무것도
막지 못하는 대신 아무것도 통과시키지 못하는 상태(항상 exit 1)였다. 개념이 뒤집혀 있었다:
**검수 큐는 "고쳐야 할 것" 목록이지 "승인 대기" 목록이 아니다.** 승격 후보의 전제는 큐 등재가
아니라 **코퍼스 실재**이며, 워크리스트 검수를 대표하는 것은 큐 멤버십이 아니라 **사람 판정
기록의 실재**(`ReviewTimerEvent` — ②단)다. 그 단은 그대로 유지한다(오히려 그것만이 사람 검수를
대표한다).

큐 멤버십은 **버리지 않고 정보로 유지**한다(`SlugVerdict.in_review_queue` · 리포트 표시).
승격 후보가 *한때 반려 큐에 있었다*는 사실은 검수자에게 의미가 있다(재제출 이력) — 다만 그것은
차단 조건이 아니라 참고 정보다.

법정·검수 절차의 기계 대체 금지 (명기)
-------------------------------------
**이 게이트는 사람 검수를 대신하지 않는다.** 하는 일은 "사람이 실제로 판정한 기록이 있는가"를
*확인*하는 것뿐이고, 판정 자체를 만들어 내거나 추론하지 않는다. 구조적 표현 3가지:

  - **쓰기 경로가 없다.** 이 모듈은 `review_status`를 각인하지 않고 코퍼스·검수 큐·이벤트
    JSONL을 수정하지 않는다(`--json` 리포트 출력만 쓴다). 승격 *집행*은 사람이 각인 도구로
    한다(회차 코퍼스 = `review_status_verdict_bridge`) — 게이트는 그 뒤에 서서 "경로를
    거쳤는가"만 판정한다.
  - **사람 판정을 우회하는 플래그가 없다.** `--force`·`--skip-review` 류를 두지 않는다. 임계값
    (`--max-defect-rate`)은 완화할 수 있어도 ②단(사람 판정 실재)은 인자로 끌 수 없다.
  - **검수 부재는 통과가 아니라 거부다.** 사람 판정이 없는 후보는 "결함 미관측"이 아니라
    `no_human_verdict`(경로 밖)다 — 미측정을 정상으로 읽지 않는다(CLAUDE.md 미측정≠0).

CLAUDE.md 절대 금기 "*측정 없는* 기계 게이트를 인간 검수 대체로 선언 금지"·"법령 유래 절차의
기계 대체 금지"의 코드 착지다. 골든 벤치마크 계약(`docs/standards/golden_benchmark_contract.md`)
의 as-found fail-closed·재채점 금지와도 같은 방향이다 — 그쪽이 *판정기를 재는* 정답지의 무결성
을 지킨다면, 이 모듈은 *학생 노출로 가는 문*의 무결성을 지킨다(대상이 다르고 원칙이 같다).

④단 Wilson 게이트 — 분모는 제안이 아니라 **검수 배치 전체**다 (EOS-136 판정)
-------------------------------------------------------------------------
배치 결함율은 점추정으로 보지 않는다. **검수 배치**(= `--review-events`로 넘긴 검수 기록의 사람
종결 판정이 있는 slug **전건** — 제안 여부·코퍼스 수록 여부 무관)의 as-found 결함 비율의 **Wilson
단측 상한**(`harness/wilson.wilson_upper_bound` 재사용 — 재구현 0)이 `--max-defect-rate` 이하일
때만 통과한다. as-found 결함 = 종결 판정 **이력 중 한 번이라도** `rejected`·`approved_with_edit`
(손질 전 내용이 결함이었다 — 골든 계약의 as-found 라벨과 같은 어휘). 최신 판정이 아니라 이력인
이유: 손질 → 재검수(`approved`)는 승격의 정본 경로인데, 최신 판정만 세면 그 재승인이 원래의
결함을 **지워** 손질이 잦은 배치가 무결점 배치로 보인다. ②단·각인은 *지금 내용*의 판정이라
최신 판정을, ④단은 *생성 배치의 품질*이라 이력을 본다. "낮을수록 좋은" 지표라 상한이다(하한을
쓰면 0/5 관측이 0.0으로 통과해 나쁜 값이 그대로 지나간다).

초판은 분모를 **제안 slug**로 잡았다. 그런데 반려된 제안은 ②단에서 이미 경로 밖이므로 통과
가능한 모든 경우에 결함 수가 0이 되고, ④단은 "승인 제안 ≥ 133건"이라는 **표본 하한**으로
퇴화했다 — 결과로 걸러 낸 집합의 결함율을 재는 것이라(선택 편향) 결함율이 아니었다. 예: 300건을
검수해 30건(10%)을 반려한 배치에서 승인 270건만 제안하면 0/270 → 상한 0.0099로 **통과**했다.
배치 분모로는 30/300 → 상한 0.1322로 거부된다(수치는 이 저장소 `wilson_upper_bound` 실측).
사람 검수는 결함을 놓치는 검출기이고 그 놓침은 결함 유병률에 비례하므로, 배치 결함율이 낮음을
보인 배치의 승인분만 올린다 — 이것이 `problem_corpus_review_status_backfill`의 코퍼스 판정과
"같은 교리"(표본의 결함을 분모에 넣는 로트 판정)라는 선언의 실제 뜻이다.
판정 근거 전문: `docs/standards/review_status_stamping_contract.md` §5.

배치는 운영자가 넘긴 검수 기록이 정한다 — 여러 회차의 기록을 합치면 합친 배치로 잰다. 리포트가
배치 크기와 **제안 밖 판정 수**를 따로 싣는 이유다(무엇을 분모로 삼았는지 산출물이 자백한다).

기본 임계 0.02·신뢰 0.95는 `problem_corpus_review_status_backfill`의 코퍼스 판정 규칙과 **같은
값**이다(같은 교리를 두 곳이 다른 숫자로 말하지 않게). 그 귀결: 무결점 5건짜리 배치도 상한이
≈0.35라 **통과하지 못한다**. 이것은 버그가 아니라 설계다 — 작은 표본으로 "결함 없음"을 주장할
수 없다는 것이 Wilson 경계를 쓰는 이유 자체다(`harness/wilson` docstring). 통과하려면 표본을
키워야 한다(0결함 133건 · 결함 1건이면 222건).

측정 실패는 통과가 아니다
------------------------
검수 배치가 0건이면 결함율의 **분모가 없다** — 이때는 "결함 0%"가 아니라 측정 실패이므로
exit 1이다. 입력 파일 부재·**행 파싱 실패 1건 이상**처럼 판정 재료가 손상되면 판정이 아니라
**입력 오류(exit 2)** 로 구분한다(`ops/declared_unwired_audit`의 수집기 파손 exit 2 선례).

검수 도구의 판정 파일은 각인 감사로그가 아니다 (EOS-136)
------------------------------------------------------
`review_session --verdicts` 파일도 `{slug, review_status}`를 담는다. 그것을 `--backfill-audit`에
넣으면 ②단(사람 판정)과 ③단(각인)이 **같은 증거로 이중 계상**된다 — 각인이 실제로 일어났는지는
아무도 확인하지 않은 채 ③단이 통과한다. 그래서 감사 행에 판정 파일 고유 키(`verdict`)가 있으면
각인 기록으로 세지 않고 **입력 손상(exit 2)** 으로 신고한다. 각인 도구의 감사 행은 그 키를 쓰지
않는다(사람 판정 원값은 `human_verdict`에 싣는다).

손상된 입력에 exit 0을 주지 않는 이유 (2026-09-01 codex P1 실측): 초판은 `load_errors`를 모아
리포트에 **렌더만** 하고 반환값에는 반영하지 않았다. 그러면 이런 형태가 조용히 통과한다 —
검수 이벤트 JSONL의 **뒤쪽 반려 행이 잘려** 파싱 실패로 스킵되면, 같은 CU의 *이전 승인*이
여전히 최신 판정으로 남아 승격된다(`_human_verdicts`가 파일 순서상 마지막 종결을 채택하므로).
즉 손상은 "정보가 조금 빠진 상태"가 아니라 **판정을 뒤집을 수 있는 상태**다. 게이트에서
"읽다가 실패했지만 통과"는 존재할 수 없다.

exit 코드: 0=전건 경로 내 + Wilson 통과 · 1=경로 밖 1건 이상 또는 Wilson 미달/측정 불가 ·
2=입력 오류(파일 부재·제안 0건·**입력 행 파싱 실패 1건 이상** — 판정 불가).

사용법(운영자):
    python -m whymath_backend.harness.golden_promotion_gate \\
        --proposal <승격제안.txt> --review-queue <acc>.review.jsonl \\
        --review-events <review_timer.jsonl> --corpus <acc>.jsonl \\
        --backfill-audit <acc>.review_status_audit.jsonl \\
        [--max-defect-rate 0.02] [--confidence 0.95] [--json <리포트.json>]

    (`--backfill-audit`는 각인 도구의 감사로그 — 회차 코퍼스는 `review_status_verdict_bridge`가
    낸 `<acc>.review_status_audit.jsonl`, 고정 코퍼스는 `docs/data/review_status_backfill_audit/`)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.harness.needs_review_worklist import load_review_queue_jsonl
from whymath_backend.harness.review_timer import load_events_jsonl
from whymath_backend.harness.wilson import wilson_upper_bound
from whymath_backend.schema.enums import is_review_status_cleared
from whymath_backend.schema.review_timer import (
    VERDICT_APPROVED_WITH_EDIT,
    ReviewTimerEvent,
    review_content_fingerprint,
    review_fingerprint_state,
)

__all__ = [
    "AS_FOUND_DEFECT_VERDICTS",
    "HUMAN_REVIEW_NOTICE",
    "PROMOTION_PATH_STAGES",
    "HumanVerdictLedger",
    "PromotionGateReport",
    "SlugVerdict",
    "certifies_current_content",
    "evaluate_promotion",
    "latest_human_verdict_events",
    "main",
    "read_human_verdict_ledger",
    "render_gate_report",
]

# 리포트가 매번 싣는 고지 — 이 게이트의 성격을 사람이 읽는 산출물에 못 박는다. 문구를 지우면
# `tests/backend/harness/test_golden_promotion_gate.py`가 빨개진다(선언을 코드가 붙든다).
HUMAN_REVIEW_NOTICE = (
    "이 게이트는 사람 검수를 대체하지 않는다 — 사람 판정 기록의 *실재*를 확인할 뿐이고, "
    "판정을 만들거나 추론하지 않는다. 쓰기 경로 없음(review_status 각인은 각인 도구가 한다 — "
    "회차 코퍼스는 review_status_verdict_bridge)·사람 판정 우회 플래그 없음. "
    "법정·검수 절차의 기계 대체 금지(CLAUDE.md)."
)

# 정본 경로 4단 — 리포트 헤더에 그대로 렌더한다(경로가 무엇인지 산출물이 자백하게).
# ①단이 "검수 큐 등재"가 아닌 이유는 모듈 docstring 참조(큐와 코퍼스는 정의상 서로소라
# 큐 멤버십을 전제로 걸면 게이트가 구조적으로 아무것도 통과시키지 못한다 — 2026-09-01 P1).
# ④단의 "검수 배치 전체"는 EOS-136 판정(분모가 제안이면 통과 경로의 결함 수가 항상 0이다).
PROMOTION_PATH_STAGES = (
    "① 코퍼스 실재(축적 CLI가 수용·저장한 후보 — 검수 큐 등재가 아니다)",
    "② 사람 검수 판정(ReviewTimerEvent finished + verdict=approved — 손질 승인은 재검수 대상 · "
    "판정이 본 내용 지문 = 코퍼스 현재 내용 지문)",
    "③ review_status 각인(각인 도구 감사로그 각인값 = 코퍼스 값 = approved)",
    "④ Wilson 결함율 상한 게이트(검수 배치 전체 — 판정 이력의 반려·손질 승인 = as-found 결함)",
)

# 기본 임계 — `problem_corpus_review_status_backfill.verdict_from_audit_labels`와 같은 값
# (같은 교리를 두 곳이 다른 숫자로 말하지 않게). 완화는 인자로 가능하되 ②단은 못 끈다.
_DEFAULT_MAX_DEFECT_RATE = 0.02
_DEFAULT_CONFIDENCE = 0.95

# 사람 검수 종결 이벤트 — `ReviewTimerEventType.FINISHED` 값(use_enum_values=True라 문자열).
_FINISHED = "finished"

# `review_session.append_verdict_jsonl` 행의 고유 키 — 사람 판정 원값. 각인 감사 행은 이 이름을
# 쓰지 않는다(각인 도구는 `human_verdict`로 싣는다). 이 키가 곧 "판정 파일이 감사로그 자리에
# 들어왔다"의 식별자다(`_load_backfill_audit` docstring — EOS-136).
_REVIEW_VERDICT_ROW_KEY = "verdict"

# 지금 코퍼스에 있는 내용을 **그대로** 승인하는 유일한 판정(모듈 docstring "왜
# approved_with_edit는 ②단을 통과하지 못하는가"). 각인 도구(`review_status_verdict_bridge`)도
# 이 값만 approved로 각인한다.
_AS_IS_APPROVAL = "approved"

# 지문 대조를 건너뛴 리포트가 싣는 자백 문구 — 테스트가 '미수행' 포함 여부로 대조한다.
_FINGERPRINT_UNCHECKED_TEXT = "미수행 — 승인 뒤 내용 편집은 확인되지 않았다"

#: ④단 분자 — as-found 결함 판정. 반려는 정의상 결함이고, 손질 승인은 *손질 전* 내용이 결함이었다는
#: 뜻이다(골든 계약 `edit_aware_verdict` → defective와 같은 규칙 — 같은 사실을 두 곳이 다르게 세지
#: 않게). 이 집합을 줄이면 손질이 잦은 생성기의 배치가 결함 없는 배치로 보인다.
AS_FOUND_DEFECT_VERDICTS: frozenset[str] = frozenset({"rejected", VERDICT_APPROVED_WITH_EDIT})


def certifies_current_content(verdict: str | None) -> bool:
    """사람 판정이 **지금 코퍼스에 있는 내용 그대로**를 승인하는가 — `approved`만 참.

    `approved_with_edit`는 "손질하면 쓸 수 있다"라 손질 전 내용을 승인하지 않는다(검수 CLI는 손질
    내용을 저장하지 않는다). 게이트 ②단과 각인 도구의 approved 각인 조건이 이 술어 하나를 공유한다
    — 두 곳이 같은 판정을 다르게 읽으면 "게이트는 막는데 코퍼스는 노출 가능" 같은 갈라짐이 생긴다.
    """
    return verdict == _AS_IS_APPROVAL


@dataclass(frozen=True, slots=True)
class SlugVerdict:
    """제안 slug 1건의 경로 판정 — 통과/차단과 **어느 단에서** 막혔는지."""

    slug: str
    """승격 제안된 후보 slug."""

    in_review_queue: bool
    """**정보** — 검수 큐 JSONL에 이 slug 행이 있는가. 차단 조건이 **아니다**.

    수용 문항은 정의상 큐에 없으므로(모듈 docstring) 정상 승격 후보는 여기서 False가 기본이다.
    True는 "이 후보가 한때 반려/검수필요로 큐에 올랐다"는 이력 신호라 검수자에게 의미가 있어
    버리지 않고 싣는다 — 판정이 아니라 참고 정보다.
    """

    human_verdict: str | None
    """②단 — 사람 검수 최신 종결 판정(approved|approved_with_edit|rejected). 없으면 None(= 검수
    기록 없음). ②단 통과는 `approved`뿐이다(`certifies_current_content`)."""

    backfill_stamped: bool
    """③단 전반 — 각인 감사로그가 이 slug를 **approved로** 각인했다고 기록하는가.

    "각인 기록의 존재"가 아니라 "각인값이 approved"까지를 뜻한다 — 감사로그에 pending으로
    적힌 기록을 '각인됨'으로 세면, 그 뒤 코퍼스만 손으로 approved가 돼도 통과한다(P1 ②).
    """

    backfill_review_status: str | None
    """③단 — 백필 감사로그가 기록한 각인값 그 자체(각인 기록이 없으면 None).

    slug 집합으로 축약하지 않고 값을 보존하는 이유: 이 모듈의 존재 이유가 "백필 각인 vs
    손각인"의 구분인데, 감사=pending·코퍼스=approved 같은 **불일치**는 값을 버리는 순간
    보이지 않는다(2026-09-01 codex P1 ②).
    """

    corpus_review_status: str | None
    """③단 후반 — 코퍼스 레코드의 현재 `review_status`(레코드 부재면 None)."""

    in_corpus: bool
    """①단 — 코퍼스 JSONL에 이 slug 레코드가 실재하는가(승격 후보의 전제)."""

    blocked_reason: str | None
    """차단 사유(경로 밖 9종 중 하나). None이면 경로 내."""

    review_fingerprint: str | None = None
    """②단 — 최신 사람 판정이 본 내용의 지문(EOS-27). None = 이벤트에 지문 없음(모름)."""

    corpus_fingerprint: str | None = None
    """②단 — 코퍼스 현재 레코드의 지문(레코드 부재면 None)."""

    fingerprint_state: str = "not_checked"
    """`match`·`changed`·`unknown`(`review_fingerprint_state`) 또는 `not_checked`(대조 미수행 —
    `evaluate_promotion`에 지문 맵을 넘기지 않았다). 통과가 아니라 *미수행*임을 값으로 자백한다."""

    @property
    def on_path(self) -> bool:
        """경로 내 여부 — 차단 사유가 없을 때만 참."""
        return self.blocked_reason is None

    def to_json(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "in_review_queue": self.in_review_queue,
            "human_verdict": self.human_verdict,
            "backfill_stamped": self.backfill_stamped,
            "backfill_review_status": self.backfill_review_status,
            "in_corpus": self.in_corpus,
            "corpus_review_status": self.corpus_review_status,
            "review_fingerprint": self.review_fingerprint,
            "corpus_fingerprint": self.corpus_fingerprint,
            "fingerprint_state": self.fingerprint_state,
            "on_path": self.on_path,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True, slots=True)
class PromotionGateReport:
    """승격 게이트 판정 — slug별 경로 판정 + 배치 Wilson 게이트."""

    verdicts: list[SlugVerdict]
    """제안 slug 전건의 경로 판정(제안 순서 보존)."""

    max_defect_rate: float
    """④단 임계 — 결함율 Wilson 상한이 이 값 이하여야 통과."""

    confidence: float
    """Wilson 단측 신뢰수준."""

    load_errors: list[str] = field(default_factory=list)
    """입력 JSONL 로드 실패 사유(파일명+줄 번호+예외 타입명) — 판정 재료의 손상 목록.

    비어 있지 않으면 이 리포트는 **판정이 아니라 입력 오류**다(`input_damaged`) — 손상된
    입력으로는 승격 허용도 거부도 권위가 없다.
    """

    batch_verdicts: dict[str, str] = field(default_factory=dict)
    """④단 분모 — **검수 배치**: 넘긴 검수 기록의 사람 최신 종결 판정 전건 {slug: 판정}.

    제안 slug만이 아니라 제안 밖 판정(반려되어 제안에서 빠진 것·코퍼스에 없는 것)까지 담는다.
    제안만 세면 반려분이 ②단에서 먼저 빠져 통과 경로의 결함 수가 항상 0이 된다(EOS-136 판정 —
    모듈 docstring ④단 절).
    """

    fingerprint_checked: bool = False
    """②단 내용 지문 대조를 *수행했는가*(EOS-27). False면 이 리포트의 통과는 '승인 뒤 내용 편집'을
    보지 않은 통과다 — CLI는 항상 True로 호출한다."""

    batch_defective: frozenset[str] = frozenset()
    """④단 분자 — 검수 배치 중 종결 판정 **이력**에 as-found 결함(반려·손질 승인)이 있는 slug.

    최신 판정이 아니라 이력이다 — 손질 후 재승인이 원래의 결함을 지우지 않게(모듈 docstring).
    """

    @property
    def input_damaged(self) -> bool:
        """입력 재료가 손상됐는가 — 참이면 판정 자체가 성립하지 않는다(CLI exit 2).

        게이트의 통과/거부보다 **앞서는** 상태다: 잘려 스킵된 반려 행 하나가 이전 승인을
        최신 판정으로 만들 수 있으므로, 손상 위에서 계산된 `approved`는 신뢰할 수 없다.
        """
        return bool(self.load_errors)

    @property
    def previously_queued(self) -> list[SlugVerdict]:
        """**정보** — 한때 검수 큐(반려·검수필요)에 올랐던 제안. 차단하지 않고 표시만 한다."""
        return [v for v in self.verdicts if v.in_review_queue]

    @property
    def off_path(self) -> list[SlugVerdict]:
        """경로 밖 제안 — 1건이라도 있으면 게이트는 거부다."""
        return [v for v in self.verdicts if not v.on_path]

    @property
    def reviewed(self) -> int:
        """검수 배치 크기 — 결함율의 **분모**(0이면 측정 불가). 제안 수가 아니다(EOS-136)."""
        return len(self.batch_verdicts)

    def _defective_with_latest(self, latest: str) -> int:
        return sum(
            1
            for slug, verdict in self.batch_verdicts.items()
            if slug in self.batch_defective and verdict == latest
        )

    @property
    def batch_rejected(self) -> int:
        """as-found 결함 중 최신 판정이 `rejected`인 수."""
        return self._defective_with_latest("rejected")

    @property
    def batch_edited(self) -> int:
        """as-found 결함 중 최신 판정이 `approved_with_edit`(손질 대기)인 수."""
        return self._defective_with_latest(VERDICT_APPROVED_WITH_EDIT)

    @property
    def batch_reapproved(self) -> int:
        """as-found 결함 중 손질 후 재검수로 최신 판정이 `approved`가 된 수 — 결함으로 센다."""
        return self._defective_with_latest(_AS_IS_APPROVAL)

    @property
    def defects(self) -> int:
        """검수 배치의 as-found 결함 수(판정 이력 기준) — 결함율의 분자."""
        return sum(1 for slug in self.batch_verdicts if slug in self.batch_defective)

    @property
    def batch_outside_proposal(self) -> int:
        """**정보** — 검수 배치 중 제안에 없는 판정 수(무엇을 분모로 삼았는지의 자백)."""
        proposed = {v.slug for v in self.verdicts}
        return sum(1 for slug in self.batch_verdicts if slug not in proposed)

    @property
    def defect_rate_upper(self) -> float | None:
        """결함율 Wilson **상한**(낮을수록 좋은 지표). 분모 0이면 None(= 측정 불가)."""
        if self.reviewed <= 0:
            return None
        return wilson_upper_bound(self.defects, self.reviewed, self.confidence)

    @property
    def wilson_passed(self) -> bool:
        """④단 통과 여부 — 분모 0(측정 불가)은 통과가 아니다."""
        upper = self.defect_rate_upper
        return upper is not None and upper <= self.max_defect_rate

    @property
    def approved(self) -> bool:
        """게이트 최종 — 입력 무손상 **그리고** 경로 밖 0건 **그리고** Wilson 통과."""
        return not self.input_damaged and not self.off_path and self.wilson_passed

    def to_json(self) -> dict[str, Any]:
        return {
            "notice": HUMAN_REVIEW_NOTICE,
            "path_stages": list(PROMOTION_PATH_STAGES),
            "proposed": len(self.verdicts),
            "on_path": len(self.verdicts) - len(self.off_path),
            "off_path": len(self.off_path),
            "fingerprint_checked": self.fingerprint_checked,
            "previously_queued": len(self.previously_queued),
            "input_damaged": self.input_damaged,
            # ④단 분모·분자 — 검수 배치 기준(EOS-136). `defect_scope`가 그 사실을 산출물에 싣는다.
            "defect_scope": "review_batch",
            "reviewed": self.reviewed,
            "batch_outside_proposal": self.batch_outside_proposal,
            "defects": self.defects,
            "batch_rejected": self.batch_rejected,
            "batch_edited": self.batch_edited,
            "batch_reapproved": self.batch_reapproved,
            "defect_rate_upper": self.defect_rate_upper,
            "max_defect_rate": self.max_defect_rate,
            "confidence": self.confidence,
            "wilson_passed": self.wilson_passed,
            "approved": self.approved,
            "load_errors": self.load_errors,
            "verdicts": [v.to_json() for v in self.verdicts],
        }


def evaluate_promotion(
    proposed_slugs: Sequence[str],
    *,
    queue_slugs: set[str],
    human_verdicts: dict[str, str],
    backfilled_status: dict[str, str],
    corpus_review_status: dict[str, str | None],
    max_defect_rate: float = _DEFAULT_MAX_DEFECT_RATE,
    confidence: float = _DEFAULT_CONFIDENCE,
    load_errors: Sequence[str] = (),
    as_found_defective: Collection[str] | None = None,
    review_fingerprints: Mapping[str, str | None] | None = None,
    corpus_fingerprints: Mapping[str, str] | None = None,
) -> PromotionGateReport:
    """승격 제안을 정본 경로 4단에 대조한다(순수 — 파일 I/O 0·쓰기 0).

    입력은 전부 *이미 로드된* 사실 집합이라 이 함수는 파일을 열지 않는다 — 로딩(그리고 그
    실패 사유 수집)은 `main`이 하고, 판정 로직은 여기서 hermetic하게 테스트된다.

    `queue_slugs`는 **판정에 쓰지 않는다** — `SlugVerdict.in_review_queue`로 실려 리포트에만
    나타난다(왜: 모듈 docstring "왜 ①단이 검수 큐 등재가 아닌가"). 인자를 없애지 않는 이유는
    그 이력 정보를 계속 싣기 위해서다.

    `backfilled_status`는 slug 집합이 아니라 **{slug: 감사로그 각인값}** 맵이다 — 값을 버리면
    "감사=pending인데 코퍼스=approved"(각인 후 손편집)를 볼 수 없다.

    `human_verdicts`는 제안 slug의 ②단 판정원이면서 **④단의 분모(검수 배치)** 다 — 넘긴 검수
    기록의 최신 종결 판정 전건을 그대로 받는다(제안 밖 판정을 걸러 넣으면 반려분이 분모에서
    사라져 통과 경로의 결함 수가 항상 0이 된다 — EOS-136 판정).

    `as_found_defective`는 ④단 분자 — 판정 **이력**에 as-found 결함이 있는 slug 집합
    (`read_human_verdict_ledger`가 만든다). 생략하면 최신 판정값에서만 유도한다(이력을 모르는
    호출자용 — 그 경우 손질 후 재승인은 결함으로 세지 못하므로 CLI는 항상 이력을 넘긴다).

    `review_fingerprints`·`corpus_fingerprints`(EOS-27)는 **둘 다** 넘길 때만 ②단 내용 지문 대조가
    켜진다: {slug: 최신 사람 판정이 본 내용의 지문(None = 이벤트에 지문 없음)} ·
    {slug: 코퍼스 현재 레코드의 지문}. 하나만 넘기면 `ValueError`다(반쪽 대조는
    '대조했다'로 위장된다).
    둘 다 생략하면 대조를 건너뛰고 리포트가 `fingerprint_checked=False`로 그 사실을 싣는다.

    차단 사유는 **첫 번째로 막힌 단**을 낸다(뭉뚱그리지 않는다 — 조치가 단마다 다르다):
    코퍼스에 없다 → 사람 판정이 없다 → 사람이 반려했다 → 사람이 손질을 요구했다 →
    판정 뒤 내용이 바뀌었다 → 판정에 내용 지문이 없다 → 각인을 안 거쳤다 → 감사값과 코퍼스값이
    어긋난다 → 각인값이 approved가 아니다.
    """
    if (review_fingerprints is None) != (corpus_fingerprints is None):
        raise ValueError(
            "review_fingerprints와 corpus_fingerprints는 함께 넘겨야 한다 — 한쪽만 있으면 "
            "내용 지문 대조는 수행될 수 없는데 수행된 것처럼 보인다(EOS-27)"
        )
    fingerprint_checked = review_fingerprints is not None
    verdicts: list[SlugVerdict] = []
    for slug in proposed_slugs:
        in_queue = slug in queue_slugs  # 정보 전용(차단 조건 아님)
        verdict = human_verdicts.get(slug)
        audit_status = backfilled_status.get(slug)
        # "각인됨"의 정의 = 감사로그에 기록이 있고 **그 값이 approved**. 기록 존재만으로
        # 인정하면 pending 각인 뒤의 손편집 approved가 그대로 통과한다(P1 ②).
        stamped = audit_status is not None and is_review_status_cleared(audit_status)
        in_corpus = slug in corpus_review_status
        status = corpus_review_status.get(slug)
        review_fp = review_fingerprints.get(slug) if review_fingerprints is not None else None
        corpus_fp = corpus_fingerprints.get(slug) if corpus_fingerprints is not None else None
        fp_state = (
            review_fingerprint_state(review_fp, corpus_fp) if fingerprint_checked else "not_checked"
        )

        reason: str | None
        if not in_corpus:
            # ①단 — 승격 후보의 전제는 코퍼스 실재다(축적 CLI가 수용·저장한 것).
            reason = "not_in_corpus"
        elif verdict is None:
            reason = "no_human_verdict"
        elif verdict == "rejected":
            reason = "human_verdict_rejected"
        elif not certifies_current_content(verdict):
            # 손질 승인 — "손질하면 쓸 수 있다"는 지금 내용의 승인이 아니다(검수 CLI는 손질을
            # 저장하지 않는다). 조치: 손질을 코퍼스에 반영하고 재검수(approved)를 받는다.
            # 각인 도구도 같은 술어로 이 판정을 각인하지 않는다(모듈 docstring — EOS-136).
            reason = "human_verdict_needs_edit"
        elif fp_state == "changed":
            # EOS-27 — 사람은 이 내용을 승인한 적이 없다. 승인 뒤 누군가 문항을 고쳤다(정답·해설·
            # 조건). 값(review_status)·감사로그는 멀쩡하므로 아래 ③단은 이것을 못 본다.
            # 조치: 지금 내용을 재검수(approved)한다 — 그 종결이 새 지문을 싣는다.
            reason = "review_content_changed"
        elif fp_state == "unknown":
            # EOS-27 — 판정 이벤트에 지문이 없다(옛 이벤트·본문 미표시). 모름은 일치가 아니다.
            # 조치: 재검수. (코퍼스 레코드가 없으면 위 ①단이 이미 막았으므로 여기 오는 unknown은
            # 항상 '이벤트 쪽 지문 없음'이다.)
            reason = "review_fingerprint_unverifiable"
        elif audit_status is None:
            # 코퍼스 값은 approved인데 각인 감사로그에 기록이 없다 = 각인 도구를 안 거친
            # 각인(손편집 의심). 값만 보고 통과시키면 "경로 밖 승격"의 가장 쉬운 형태가 열린다.
            # 조치: 각인 도구를 돌려 각인을 정본 경로로 다시 만든다.
            reason = "review_status_not_backfilled"
        elif audit_status != status:
            # 각인은 거쳤는데 **지금 코퍼스 값이 그때 각인값과 다르다** = 각인 이후 누군가
            # 코퍼스를 고쳤다. "각인 안 됨"과 조치가 다르다(이쪽은 백필 재실행이 아니라 변경
            # 이력 조사 대상) — 그래서 사유를 분리한다(2026-09-01 codex P1 ②).
            reason = "review_status_audit_mismatch"
        elif not stamped:
            # 감사값 = 코퍼스값인데 그 값이 approved가 아니다(pending/rejected).
            # 판정 권위는 `is_review_status_cleared` 단일. 조치: 검수 판정 자체를 다시 받는다.
            reason = "review_status_not_approved"
        else:
            reason = None

        verdicts.append(
            SlugVerdict(
                slug=slug,
                in_review_queue=in_queue,
                human_verdict=verdict,
                backfill_stamped=stamped,
                backfill_review_status=audit_status,
                corpus_review_status=status,
                in_corpus=in_corpus,
                blocked_reason=reason,
                review_fingerprint=review_fp,
                corpus_fingerprint=corpus_fp,
                fingerprint_state=fp_state,
            )
        )
    defective = (
        frozenset(as_found_defective)
        if as_found_defective is not None
        else frozenset(
            slug for slug, verdict in human_verdicts.items() if verdict in AS_FOUND_DEFECT_VERDICTS
        )
    )
    return PromotionGateReport(
        verdicts=verdicts,
        max_defect_rate=max_defect_rate,
        confidence=confidence,
        load_errors=list(load_errors),
        batch_verdicts=dict(human_verdicts),
        batch_defective=defective,
        fingerprint_checked=fingerprint_checked,
    )


def render_gate_report(report: PromotionGateReport) -> str:
    """운영자용 판정 리포트(순수) — 경로 4단·차단 사유·Wilson 판정·고지문을 낸다."""
    lines: list[str] = [
        "# 골든 승격 경로 게이트 판정 (EOS-64 ③)",
        "",
        f"- 고지: {HUMAN_REVIEW_NOTICE}",
        "- 정본 경로:",
    ]
    lines.extend(f"  - {stage}" for stage in PROMOTION_PATH_STAGES)
    upper = report.defect_rate_upper
    upper_text = "측정 불가(분모 0 — 사람 검수 판정 0건)" if upper is None else f"{upper:.4f}"
    lines.extend(
        [
            "",
            f"- 제안 {len(report.verdicts)}건 · 경로 내 "
            f"{len(report.verdicts) - len(report.off_path)}건 · 경로 밖 {len(report.off_path)}건",
            # ④단 분모는 제안이 아니라 검수 배치다(EOS-136) — 제안 밖 판정 수를 함께 적어
            # 분모가 무엇이었는지 산출물이 자백하게 한다.
            f"- 검수 배치 {report.reviewed}건(제안 밖 {report.batch_outside_proposal}건 포함) · "
            f"as-found 결함 {report.defects}건(최신 반려 {report.batch_rejected} · "
            f"손질 대기 {report.batch_edited} · 손질 후 재승인 {report.batch_reapproved}) · "
            f"결함율 Wilson 상한(신뢰 {report.confidence}) {upper_text} "
            f"(임계 {report.max_defect_rate})",
            # 큐 이력은 **정보**로만 싣는다(차단 조건 아님) — 승격 후보가 한때 반려·검수필요
            # 큐에 올랐다는 사실은 검수자에게 의미가 있어 버리지 않는다.
            f"- 참고(차단 아님): 한때 검수 큐에 오른 제안 {len(report.previously_queued)}건",
            f"- 내용 지문 대조(EOS-27): "
            f"{'수행' if report.fingerprint_checked else _FINGERPRINT_UNCHECKED_TEXT}",
            f"- 판정: {'승격 허용' if report.approved else '승격 거부'}",
            "",
        ]
    )
    if report.load_errors:
        # 손상은 "정보 누락"이 아니라 판정 무효 사유다 — 어느 파일 몇 번째 줄이 왜 실패했는지
        # 전건을 남긴다(침묵 실패 금지). CLI는 이 상태에서 exit 2를 낸다.
        lines.append("## 입력 오류 — 판정 재료 손상(판정 무효·exit 2)")
        lines.extend(f"- ⚠ 입력 로드 실패 행: {error}" for error in report.load_errors)
        lines.append("")
    if report.previously_queued:
        lines.append("## 참고 — 검수 큐 이력이 있는 제안(차단 아님)")
        lines.extend(f"- `{verdict.slug}`" for verdict in report.previously_queued)
        lines.append("")
    if report.off_path:
        lines.append("## 경로 밖 제안(차단)")
        for verdict in report.off_path:
            lines.append(f"- `{verdict.slug}` — {verdict.blocked_reason}")
        lines.append("")
    return "\n".join(lines)


def _read_proposal(path: Path) -> list[str]:
    """승격 제안 파일 → slug 목록(한 줄 1 slug·`#` 주석·빈 줄 무시·중복 제거·순서 보존)."""
    slugs: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if not text or text in seen:
            continue
        seen.add(text)
        slugs.append(text)
    return slugs


def _load_backfill_audit(path: Path) -> tuple[dict[str, str], list[str]]:
    """각인 감사로그 JSONL → {slug: 각인된 review_status}. (맵, 실패 사유[타입명+줄 번호]).

    **slug 집합으로 축약하지 않는 이유**(2026-09-01 codex P1 ②): 감사 레코드는 각인 도구가 쓴
    `{slug, review_status, ...}`라 각인 *값*을 이미 갖고 있다(코퍼스 단위 백필의 `_backfill_line`·
    회차 각인 도구 `review_status_verdict_bridge` 공통). 그 값을 버리고 slug만 남기면 "이전 각인이
    pending이었는데 나중에 코퍼스를 손으로 approved로 고친" 경우가 그대로 통과한다 — 이 모듈의
    존재 이유(도구 각인 vs 손각인 구분)가 정확히 그 지점에서 무너진다.

    같은 slug가 여러 줄/여러 파일에 나오면 **마지막 기록이 이긴다**(각인 재실행이 이전 각인을
    갱신한다 — `latest_human_verdict_events`의 "마지막 종결이 현재 판정"과 같은 규칙). 파싱 실패
    줄은 삼키지 않고 파일명·줄 번호·예외 타입명을 남긴다(필드 *값*은 남기지 않는다 — 침묵 실패
    금지 규약의 로그 위생).

    **검수 도구의 판정 행은 각인 기록이 아니다**(EOS-136): `review_session --verdicts` 행도
    `{slug, review_status}`를 담지만 그것은 *사람 판정*이지 *각인 사실*이 아니다. 그 파일을 감사로그
    자리에 넣으면 ②단과 ③단이 같은 증거로 이중 계상된다. 판정 행의 고유 키 `verdict`가 있는 행은
    각인으로 세지 않고 손상으로 신고한다(게이트 exit 2). 각인 도구의 감사 행은 그 키를 쓰지 않는다.
    """
    statuses: dict[str, str] = {}
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except Exception as exc:  # noqa: BLE001 — 사유 수집(타입명 보존)이 목적
                errors.append(f"{path.name} line {line_no}: {type(exc).__name__}")
                continue
            if not isinstance(parsed, dict):
                continue
            slug = parsed.get("slug")
            if not (isinstance(slug, str) and slug):
                continue
            if _REVIEW_VERDICT_ROW_KEY in parsed:
                # 검수 도구 판정 파일의 행 — 각인 사실이 아니라 사람 판정이다(docstring). 각인으로
                # 세면 ③단이 각인 없이 통과한다. 조치: 각인 도구의 감사로그를 넘긴다.
                errors.append(f"{path.name} line {line_no}: ReviewVerdictRowNotStampAudit")
                continue
            raw = parsed.get("review_status")
            if not (isinstance(raw, str) and raw):
                # slug는 있는데 각인값이 없는 감사 행 = 재료 손상이다. 조용히 "각인 기록 있음"
                # 으로 세면 값 없는 행이 approved 각인처럼 행세한다 — 손상으로 신고한다.
                errors.append(f"{path.name} line {line_no}: MissingReviewStatusField")
                continue
            statuses[slug] = raw
    return statuses, errors


def _load_corpus_review_status(path: Path) -> tuple[dict[str, str | None], list[str]]:
    """코퍼스 JSONL → ({slug: review_status}, 실패 사유). `_load_corpus_records`의 상태 투영."""
    statuses, _fingerprints, errors = _load_corpus_records(path)
    return statuses, errors


def _load_corpus_records(
    path: Path,
) -> tuple[dict[str, str | None], dict[str, str], list[str]]:
    """코퍼스 JSONL → ({slug: review_status}, {slug: 내용 지문}, 실패 사유). 생 dict로 읽는다
    (Problem 검증 우회). 지문은 EOS-27 — `review_content_fingerprint` 단일 정본으로 만든다.

    `load_problem_bank_records`를 쓰지 않는 이유: 이 게이트가 봐야 하는 것은 두 키(`slug`·
    `review_status`)뿐인데, 전체 레코드 검증에 걸려 `ProblemCorpusError`가 나면 *게이트가
    판정할 기회조차 잃는다*. 값 판정은 단일 권위(`is_review_status_cleared`)가 하므로 여기서
    관대해져도 판정 기준은 느슨해지지 않는다.
    """
    statuses: dict[str, str | None] = {}
    fingerprints: dict[str, str] = {}
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except Exception as exc:  # noqa: BLE001 — 사유 수집(타입명 보존)이 목적
                errors.append(f"{path.name} line {line_no}: {type(exc).__name__}")
                continue
            if not isinstance(parsed, dict):
                continue
            slug = parsed.get("slug")
            if isinstance(slug, str) and slug:
                raw = parsed.get("review_status")
                statuses[slug] = raw if isinstance(raw, str) else None
                fingerprints[slug] = review_content_fingerprint(parsed)
    return statuses, fingerprints, errors


@dataclass(frozen=True, slots=True)
class HumanVerdictLedger:
    """검수 기록의 사람 종결 판정 — 최신 판정(②단·각인)과 as-found 결함 이력(④단 분자)."""

    latest: dict[str, ReviewTimerEvent]
    """{cu_slug: 최신 종결 이벤트} — 키 순서는 첫 등장 순서(재검수는 값만 갱신한다)."""

    as_found_defective: frozenset[str]
    """종결 판정 이력 중 한 번이라도 as-found 결함(반려·손질 승인)이었던 cu_slug."""


def read_human_verdict_ledger(paths: Iterable[Path]) -> tuple[HumanVerdictLedger, list[str]]:
    """검수 타이머 이벤트 → 판정 원장. `finished` + verdict만 센다(**사람 판정 해석의 단일 권위**).

    게이트 ②단·④단, 제안 파생(`golden_inputs` — `_human_verdicts` 경유), 각인 도구
    (`review_status_verdict_bridge` — `latest_human_verdict_events` 경유)가 전부 이 함수로 읽는다.
    각인 도구가 판정을 따로 읽으면 "게이트가 본 판정"과 "각인된 판정"이 갈라질 수 있다.

    같은 CU가 여러 세션으로 검수되면(시작→중단→재시작→종결) **파일 순서상 마지막 종결**이
    현재 판정이다 — 재검수가 이전 판정을 갱신한다. started/aborted는 판정이 아니므로 무시한다
    (그 상태를 approved로 읽으면 그것이 곧 "기계가 사람 판정을 대신하는" 형태다).

    as-found 결함은 **이력**으로 모은다 — 손질 → 재검수(approved)가 최신 판정을 바꿔도 원래의
    결함은 배치 품질(④단)에서 지워지지 않아야 한다(모듈 docstring ④단 절).
    """
    latest: dict[str, ReviewTimerEvent] = {}
    defective: set[str] = set()
    errors: list[str] = []
    for path in paths:
        events, load_errors = load_events_jsonl(path)
        errors.extend(f"{path.name} {err}" for err in load_errors)
        for event in events:
            if event.event_type != _FINISHED or event.verdict is None:
                continue
            latest[event.cu_slug] = event
            if str(event.verdict) in AS_FOUND_DEFECT_VERDICTS:
                defective.add(event.cu_slug)
    return HumanVerdictLedger(latest=latest, as_found_defective=frozenset(defective)), errors


def latest_human_verdict_events(
    paths: Iterable[Path],
) -> tuple[dict[str, ReviewTimerEvent], list[str]]:
    """검수 타이머 이벤트 → {cu_slug: 최신 종결 이벤트} — `read_human_verdict_ledger`의 최신판.

    이벤트 *전체*를 돌려주는 이유: 각인 도구의 감사로그가 근거 이벤트 id·검수자·검수 시각을
    싣는다(판정 값만 돌려주면 그 근거를 다시 찾는 두 번째 해석 경로가 생긴다).
    """
    ledger, errors = read_human_verdict_ledger(paths)
    return ledger.latest, errors


def _human_verdicts(paths: Iterable[Path]) -> tuple[dict[str, str], list[str]]:
    """검수 타이머 이벤트 → {cu_slug: 최신 종결 판정 값} — `latest_human_verdict_events` 투영."""
    latest, errors = latest_human_verdict_events(paths)
    return {slug: str(event.verdict) for slug, event in latest.items()}, errors


def _say(message: str) -> None:
    """운영자 메시지 — stdout(리포트와 같은 스트림·`--json`은 파일로 따로 쓴다)."""
    sys.stdout.write(message + "\n")


def main(argv: Sequence[str] | None = None) -> int:  # noqa: C901 — 입력 검증 분기가 본체다
    """CLI 엔트리 — 경로 밖 승격이면 exit 1, 입력이 없거나 **손상됐으면** exit 2."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.golden_promotion_gate",
        description=(
            "골든 승격 경로 게이트 — 코퍼스 실재→사람 판정→review_status 각인→검수 배치 Wilson "
            "게이트를 전부 거친 제안만 통과시킨다(경로 밖 승격은 exit 1). 사람 검수를 "
            "대체하지 않는다."
        ),
    )
    parser.add_argument("--proposal", type=Path, required=True, help="승격 제안 slug 목록(텍스트).")
    parser.add_argument(
        "--review-queue",
        type=Path,
        required=True,
        help=(
            "검수 큐 JSONL(<out>.review.jsonl) — **정보용**(차단 조건 아님). 수용 문항은 "
            "정의상 큐에 없으므로 큐 멤버십을 전제로 걸면 아무것도 통과하지 못한다."
        ),
    )
    parser.add_argument(
        "--review-events",
        dest="review_events",
        type=Path,
        action="append",
        required=True,
        help="검수 타이머 이벤트 JSONL(복수 지정 가능) — ②단 사람 판정의 근거.",
    )
    parser.add_argument("--corpus", type=Path, required=True, help="승격 대상 코퍼스 JSONL.")
    parser.add_argument(
        "--backfill-audit",
        dest="backfill_audits",
        type=Path,
        action="append",
        required=True,
        help=(
            "review_status 각인 감사로그 JSONL(복수 지정 가능) — ③단 각인이 각인 도구를 거쳤음의 "
            "근거(회차 코퍼스 = review_status_verdict_bridge의 "
            "<corpus>.review_status_audit.jsonl). "
            "필수인 이유: 코퍼스의 값만 보면 손편집 각인을 구분할 수 없다. 각인 *값*까지 읽어 "
            "코퍼스 현재값과 대조한다(불일치는 review_status_audit_mismatch). 검수 도구의 "
            "--verdicts 파일은 각인 기록이 아니다(넣으면 입력 손상 exit 2)."
        ),
    )
    parser.add_argument(
        "--max-defect-rate",
        type=float,
        default=_DEFAULT_MAX_DEFECT_RATE,
        help=(
            f"④단 결함율 Wilson 상한 임계(기본 {_DEFAULT_MAX_DEFECT_RATE} — 백필 CLI와 동일). "
            "분모는 검수 배치 전체(--review-events의 종결 판정 전건)다."
        ),
    )
    parser.add_argument(
        "--confidence", type=float, default=_DEFAULT_CONFIDENCE, help="Wilson 단측 신뢰수준."
    )
    parser.add_argument(
        "--json", dest="json_out", type=Path, default=None, help="리포트 JSON 경로."
    )
    args = parser.parse_args(argv)

    # ── 입력 오류(exit 2) — 판정이 아니라 잴 재료가 없는 상태 ──────────────────
    required: list[Path] = [args.proposal, args.review_queue, args.corpus]
    required.extend(args.review_events)
    required.extend(args.backfill_audits)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        _say(f"[입력 오류] 입력 파일 부재 — {', '.join(missing)} (판정 불가·exit 2).")
        return 2

    proposed = _read_proposal(args.proposal)
    if not proposed:
        _say("[입력 오류] 승격 제안 0건 — 판정할 대상이 없다(통과가 아니다·exit 2).")
        return 2

    load_errors: list[str] = []
    queue_entries, queue_errors = load_review_queue_jsonl(args.review_queue)
    load_errors.extend(f"{args.review_queue.name} {err}" for err in queue_errors)
    queue_slugs = {entry.slug for entry in queue_entries if entry.slug is not None}

    ledger, verdict_errors = read_human_verdict_ledger(args.review_events)
    verdict_map = {slug: str(event.verdict) for slug, event in ledger.latest.items()}
    load_errors.extend(verdict_errors)

    backfilled: dict[str, str] = {}
    for audit_path in args.backfill_audits:
        audit_status, audit_errors = _load_backfill_audit(audit_path)
        backfilled.update(audit_status)  # 마지막 감사 파일의 각인이 이긴다(재실행 갱신)
        load_errors.extend(audit_errors)

    corpus_status, corpus_fingerprints, corpus_errors = _load_corpus_records(args.corpus)
    load_errors.extend(corpus_errors)
    review_fingerprints = {slug: event.content_fingerprint for slug, event in ledger.latest.items()}

    report = evaluate_promotion(
        proposed,
        queue_slugs=queue_slugs,
        human_verdicts=verdict_map,
        backfilled_status=backfilled,
        corpus_review_status=corpus_status,
        max_defect_rate=args.max_defect_rate,
        confidence=args.confidence,
        load_errors=load_errors,
        as_found_defective=ledger.as_found_defective,
        review_fingerprints=review_fingerprints,
        corpus_fingerprints=corpus_fingerprints,
    )
    _say(render_gate_report(report))
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # ── 입력 손상(exit 2) — 판정보다 **앞선다** ──────────────────────────────
    # 리포트·JSON은 이미 위에서 냈다(증거는 남기고 판정만 무효화한다). 손상된 입력 위의
    # 통과/거부는 둘 다 권위가 없으므로 게이트 판정(0/1)이 아니라 입력 오류로 종료한다
    # (2026-09-01 codex P1 ③ — 초판은 load_errors를 렌더만 하고 exit 0을 낼 수 있었다).
    if report.input_damaged:
        _say(
            f"[입력 오류] 판정 재료 손상 {len(report.load_errors)}행 — "
            f"{'; '.join(report.load_errors[:5])}"
            f"{' …' if len(report.load_errors) > 5 else ''} (판정 무효·exit 2)."
        )
        return 2
    if report.off_path:
        reasons = ", ".join(sorted({v.blocked_reason or "?" for v in report.off_path}))
        _say(f"[승격 거부] 경로 밖 제안 {len(report.off_path)}건 — 사유: {reasons} (exit 1).")
        return 1
    if report.defect_rate_upper is None:
        _say("[측정 실패] 사람 검수 판정 0건 — 결함율의 분모가 없다(0%가 아니다·exit 1).")
        return 1
    if not report.wilson_passed:
        _say(
            f"[승격 거부] 결함율 Wilson 상한 {report.defect_rate_upper:.4f} > "
            f"임계 {report.max_defect_rate} — 검수 배치 {report.reviewed}건(as-found 결함 "
            f"{report.defects}건)으로는 결함 없음을 주장할 수 없다(exit 1)."
        )
        return 1
    _say(f"[승격 허용] 제안 {len(proposed)}건 전건이 정본 경로 4단을 통과했다(exit 0).")
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
