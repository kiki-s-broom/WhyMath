"""회차 대장에서 **판정 재료를 뽑아 사람이 읽을 회신으로 쓰는** CLI (EOS-121 [F]).

왜 이 모듈이 있는가 — 셸이 바이트를 중계하면 한국어가 깨진다
----------------------------------------------------------
EOS-121 파일럿에서 런북 [F]는 이렇게 회신을 만들었다::

    Get-Content <대장> -Tail 1 | Out-File -FilePath reply.json -Encoding utf8

그 결과 한국어가 `?댁감諛⑹젙??`로 깨졌다. 원인은 파일이 아니다 — 같은 필드를 Python으로
읽으면 정상이다. 깨뜨린 것은 **경유 자체**다: Windows PowerShell 5.1은 파일·네이티브 명령의
바이트를 `[Console]::OutputEncoding`(한국어 Windows 기본 cp949)으로 **디코딩한 뒤 다시
인코딩**하고, cp949는 2바이트 조합이라 UTF-8 3바이트 문자(`—`·`·`·한글)에서 경계가 어긋난다.
`Out-File -Encoding utf8`은 **이미 깨진 문자열**을 성실히 UTF-8로 쓸 뿐이라 이 축을 막지
못한다(CLAUDE.md v0.2.24 「셸이 중계하는 제3 도구 출력은 셸을 통과시키지 않는다」).

그래서 이 도구는 **Python이 읽고 Python이 쓴다.** 셸은 프로세스를 띄울 뿐 바이트를 만지지
않는다. 화면 표시는 여전히 콘솔 디코딩을 타므로(그 축은 `[Console]::OutputEncoding` 설정이
맡는다) **정본은 파일**이고, 그 파일은 BOM 붙은 UTF-8(`utf-8-sig`)로 쓴다 — PowerShell
`Get-Content`와 메모장이 BOM을 보고 UTF-8로 디코딩하므로 회신자가 파일을 열어 복사하는
경로까지 닫힌다.

무엇을 뽑는가 (판정 재료)
------------------------
EOS-121의 판정은 좌석 비교다. 그래서 대장 마지막 행에서 아래를 뽑는다:

  · `cloud_seat` — **어느 좌석의 회차인가**(이 측정의 출발점)
  · `duplicate_sources` — 회차 내 중복 vs 코퍼스 중복(acceptance ③)
  · `spec_outcome_counts`·`spec_plan` — spec 3종 중 어디서 났는가(acceptance ②)
  · `outcome_counts`·`attempted/accepted/appended` — 작동한 비율
  · `model_name` — 실제로 호출된 모델 핀

미측정과 0을 섞지 않는다
-----------------------
대장의 이 필드들은 **3상태**다(CLAUDE.md 「모른다 ≠ 아니다」). 렌더는 셋을 각각 다른
문장으로 낸다 — 필드 `None`은 "미기록", 블록의 `measured=false`는 "잴 대상이 0건이라 비율이
정의되지 않음", 실측 0은 "0건". 하나로 접으면 회신을 읽는 사람이 '측정 실패'를 '0% 달성'으로
읽는다.

실패해도 증거가 남는다 (2026-08-22 규칙)
---------------------------------------
대장이 없거나 비었거나 로드 실패가 있어도 **보고서는 쓴다** — 그 사실 자체가 판정 재료이기
때문이다(회차가 대장을 못 썼다는 것은 회차가 중간에 죽었다는 뜻이다). 사유는 예외 타입명과
경로를 남기고 exit 1로 정직하게 실패를 알린다.

7계층 — 하네스 도구
------------------
파일만 읽는다(LLM 0·DB 0·네트워크 0). 대장 스키마 로더(`load_round_ledger`)만 재사용하며
경로 산식·집계 산식을 여기 다시 적지 않는다(truth source 이중화 금지).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from whymath_backend.harness.anchor_round_ledger import RoundRecord, load_round_ledger

__all__ = [
    "RoundReply",
    "extract_round_reply",
    "main",
    "render_reply_text",
]

#: 미기록(필드 자체가 None)을 말하는 단일 문구 — 화면에서 "0건"과 눈으로 갈리게 한다.
_UNRECORDED = "미기록(대장 행에 필드 없음 — 구판 행이거나 이 회차가 기록하지 않았다. 0이 아니다)"


class RoundReply:
    """회차 1건에서 뽑아낸 판정 재료 + 그 회차를 읽지 못한 사유.

    `record`가 None이면 **읽지 못한 회차**다(대장 부재·행 0건). 그 경우에도 인스턴스는
    만들어지며 `problems`가 이유를 말한다 — 실패를 빈 보고서로 위장하지 않는다.
    """

    __slots__ = ("label", "ledger_path", "record", "problems", "total_rows")

    def __init__(
        self,
        *,
        label: str,
        ledger_path: Path,
        record: RoundRecord | None,
        problems: list[str],
        total_rows: int,
    ) -> None:
        self.label = label
        self.ledger_path = ledger_path
        self.record = record
        self.problems = problems
        self.total_rows = total_rows

    @property
    def ok(self) -> bool:
        """판정 재료를 실제로 확보했는가 — 로드 실패가 있으면 행이 있어도 False다."""
        return self.record is not None and not self.problems

    def to_json(self) -> dict[str, Any]:
        """회신에 동봉할 기계 판독용 증거(사람 렌더와 **같은 원천**에서 나온다)."""
        payload: dict[str, Any] = {
            "label": self.label,
            "ledger_path": str(self.ledger_path),
            "ledger_rows": self.total_rows,
            "problems": list(self.problems),
        }
        record = self.record
        if record is None:
            payload["round"] = None
            return payload
        payload["round"] = {
            "run_id": record.run_id,
            "out_path": record.out_path,
            "recorded_at": record.recorded_at.isoformat() if record.recorded_at else None,
            "source_line": record.source_line,
            "attempted": record.attempted,
            "accepted": record.accepted,
            "appended": record.appended,
            "outcome_counts": dict(record.outcome_counts),
            "model_name": record.model_name,
            # 아래 넷은 **None을 그대로 싣는다** — 빈 dict로 채우면 미기록이 "0건 관측"이 된다.
            "cloud_seat": record.cloud_seat,
            "duplicate_sources": record.duplicate_sources,
            "spec_outcome_counts": record.spec_outcome_counts,
            "spec_plan": record.spec_plan,
        }
        return payload


def extract_round_reply(label: str, ledger_path: Path) -> RoundReply:
    """대장 1개에서 **마지막 회차**를 뽑는다(읽지 못하면 사유를 담아 돌려준다).

    마지막 행을 쓰는 이유: 좌석당 1회 실행이 이 런북의 절차이고, 재실행이 있었다면 판정
    대상은 가장 최근 회차다. 행 수(`total_rows`)를 함께 내어 "여러 번 돌았다"는 사실이
    회신에서 보이게 한다 — 그 사실을 감추면 읽는 사람이 앞 회차 결과를 이번 것으로 오독한다.
    """
    problems: list[str] = []
    if not ledger_path.exists():
        problems.append(
            f"회차 대장 없음: {ledger_path} — 그 좌석 회차가 대장을 쓰지 못했다"
            "(회차가 시작조차 못 했거나 중간에 죽었다). stdout 로그를 함께 보내야 원인을 읽는다."
        )
        return RoundReply(
            label=label, ledger_path=ledger_path, record=None, problems=problems, total_rows=0
        )

    try:
        records, load_errors = load_round_ledger(ledger_path)
    except Exception as exc:  # noqa: BLE001 — 사유 수집이 목적(예외 타입명 보존·침묵 실패 금지)
        problems.append(f"대장 로드 실패: {type(exc).__name__} ({ledger_path})")
        return RoundReply(
            label=label, ledger_path=ledger_path, record=None, problems=problems, total_rows=0
        )

    # 로드 실패 줄은 **삼키지 않는다** — 유효 행이 있어도 사유를 남긴다(부분 신뢰 금지).
    problems.extend(f"대장 로드 실패 줄: {reason}" for reason in load_errors)
    if not records:
        problems.append(
            f"대장에 유효 행 0건: {ledger_path} — 파일은 있으나 회차가 기록되지 않았다"
            "(0건 성공이 아니다)."
        )
        return RoundReply(
            label=label,
            ledger_path=ledger_path,
            record=None,
            problems=problems,
            total_rows=0,
        )
    return RoundReply(
        label=label,
        ledger_path=ledger_path,
        record=records[-1],
        problems=problems,
        total_rows=len(records),
    )


def _render_seat(seat: dict[str, Any] | None) -> list[str]:
    """좌석 블록 — 이 측정의 출발점('어느 좌석의 회차인가')."""
    if seat is None:
        return [f"  좌석: {_UNRECORDED}", "        ↳ 대장만으로는 어느 좌석의 회차인지 알 수 없다."]
    lines: list[str] = []
    selected = seat.get("selected_seat")
    state = seat.get("state")
    measured = seat.get("measured")
    lines.append(f"  좌석(선택): {selected}   판정 상태: {state}   측정됨: {measured}")
    if selected == "unknown" and not seat.get("seat_model_pins"):
        lines.append(
            "        ↳ 설정 판독 실패 회차다(좌석 미상). on/off 계수를 좌석 판정으로 읽지 말 것."
        )
    if not measured:
        lines.append(f"        ↳ {seat.get('unmeasured_reason')}")
    lines.append(
        f"  호출: 전체 {seat.get('calls_total')}건 · model_name 기록 "
        f"{seat.get('calls_with_model_name')}건 · 선택 좌석 {seat.get('calls_on_selected_seat')}건 "
        f"· 좌석 밖 {seat.get('calls_off_selected_seat')}건"
    )
    lines.append(f"  선언 모델(설정이 지목): {_counts_text(seat.get('observed_models'))}")
    observation = seat.get("observation") or {}
    lines.append(f"  관측 모델(응답이 온): {_counts_text(observation.get('observed_models'))}")
    compare = observation.get("declared_vs_served") or {}
    lines.append(
        f"  선언↔관측: 비교가능 {compare.get('comparable')} · 일치 {compare.get('matched')} · "
        f"어긋남 {compare.get('differs')}"
    )
    if compare.get("differing_pairs"):
        for pair in compare["differing_pairs"]:
            lines.append(
                f"        · 선언 {pair.get('declared')} → 관측 {pair.get('served')} "
                f"({pair.get('count')}건)"
            )
        lines.append("        ↳ 차이가 곧 이상은 아니다(별칭→버전 해소도 같은 모양이다).")
    retries = observation.get("retries") or {}
    if retries.get("calls_with_retries_measured"):
        lines.append(
            f"  재시도: 계측 {retries.get('calls_with_retries_measured')}행 · 합계 "
            f"{retries.get('retries_total')} · 1회 이상 {retries.get('calls_with_any_retry')}행"
        )
    else:
        lines.append("  재시도: 계측한 호출 0건 — '재시도 없었다'가 아니라 **미계측**이다.")
    lines.append(
        f"  성공/실패: {seat.get('succeeded')} / {seat.get('failed')}   비용(단가 곱셈·청구서 "
        f"미대조): {seat.get('cost_usd_total')} USD ({seat.get('calls_with_cost')}행)"
    )
    return lines


def _render_duplicate_sources(block: dict[str, Any] | None) -> list[str]:
    """중복 출처 블록 — acceptance ③('회차 내 중복'과 '코퍼스 중복'을 가른다)."""
    if block is None:
        return [f"  중복 출처: {_UNRECORDED}"]
    total = block.get("duplicates_total")
    if not block.get("measured"):
        return [
            f"  중복 출처: 총 {total}건 — 미측정",
            f"        ↳ {block.get('unmeasured_reason')}",
        ]
    lines = [
        f"  중복 출처: 총 {total}건 (측정됨) · 검출기 식별 {block.get('classified')}건 "
        f"({_ratio(block.get('classified_rate'))}) · 출처 해소 {block.get('origin_resolved')}건 "
        f"({_ratio(block.get('origin_resolved_rate'))})"
    ]
    counts: dict[str, int] = block.get("counts") or {}
    nonzero = {key: value for key, value in counts.items() if value}
    if nonzero:
        for key, value in sorted(nonzero.items()):
            lines.append(f"        · {key} = {value}건")
        lines.append("        ↳ 0건 조합은 화면에서만 생략했다(전건은 아래 JSON 증거에 있다).")
    else:
        lines.append("        · 교차표 전건 0 — 검출기/출처 조합 어디에도 계상되지 않았다.")
    lines.append(f"        by_origin: {_counts_text(block.get('by_origin'))}")
    lines.append(
        "        ↳ round = 이번 회차가 방금 만든 것끼리 겹침(**생성 다양성**) / "
        "corpus = 기존 코퍼스와 겹침(dedup 정상 동작)."
    )
    if block.get("unknown_detectors") or block.get("unknown_origins"):
        lines.append(
            f"        ⚠ 어휘 밖 값: detectors={block.get('unknown_detectors')} "
            f"origins={block.get('unknown_origins')}"
        )
    return lines


def _render_specs(
    spec_outcome_counts: dict[str, dict[str, int]] | None,
    spec_plan: list[dict[str, Any]] | None,
) -> list[str]:
    """spec 축 — acceptance ②('한 spec에만 쏠려 있으면 좌석 특성이 아니다')."""
    lines: list[str] = []
    if spec_plan is None:
        lines.append(f"  spec 계획: {_UNRECORDED}")
    elif not spec_plan:
        lines.append(
            "  spec 계획: 0건 기록 — 순환할 spec이 없었다(단일 spec 회차도 1건이어야 한다)."
        )
    else:
        ids = ", ".join(str(item.get("spec_id")) for item in spec_plan)
        lines.append(f"  spec 계획: {len(spec_plan)}종 — {ids}")
        for item in spec_plan:
            lines.append(f"        · {item.get('spec_id')}: {item.get('topic_hint')}")

    if spec_outcome_counts is None:
        lines.append(f"  spec별 outcome: {_UNRECORDED}")
    elif not spec_outcome_counts:
        lines.append("  spec별 outcome: 시도 0건(빈 기록 — 미기록이 아니다).")
    else:
        # 표제를 따로 둔다 — 위 spec 계획 목록과 들여쓰기·불릿이 같아서, 표제가 없으면 두
        # 목록이 한 덩어리로 읽힌다(회신을 읽는 사람이 topic_hint 줄과 건수 줄을 섞는다).
        lines.append(f"  spec별 outcome: {len(spec_outcome_counts)}종")
        for spec_id, counts in sorted(spec_outcome_counts.items()):
            lines.append(f"        · {spec_id}: {_counts_text(counts)}")
    return lines


def _counts_text(counts: Any) -> str:
    """`{키: 건수}`를 한 줄로 — 빈 dict와 None을 다른 문구로 낸다(미기록 ≠ 0건)."""
    if counts is None:
        return "미기록"
    if not counts:
        return "0건"
    return " · ".join(f"{key}×{value}" for key, value in sorted(dict(counts).items()))


def _ratio(value: float | None) -> str:
    """비율 표시 — None은 퍼센트로 위장하지 않는다."""
    return "미정의" if value is None else f"{value * 100:.1f}%"


def render_reply_text(replies: list[RoundReply]) -> str:
    """회신 본문 — 사람이 읽는 요약 + 기계 판독용 JSON 증거(같은 원천)."""
    lines: list[str] = [
        "# EOS-121 좌석별 생성 다양성 회차 — 회신",
        "",
        "이 파일은 회차 대장(`<out>.rounds.jsonl`)의 **마지막 행**을 Python이 읽고 Python이",
        "쓴 것이다(셸이 바이트를 중계하지 않는다 — cp949 왕복 손상 방지).",
        "",
    ]
    for reply in replies:
        lines.append(f"## 좌석 라벨: {reply.label}")
        lines.append(f"  대장: {reply.ledger_path}  (유효 행 {reply.total_rows}건)")
        for problem in reply.problems:
            lines.append(f"  ⚠ {problem}")
        record = reply.record
        if record is None:
            lines.append("  → 판정 재료 없음. 위 사유를 그대로 회신하면 원인을 읽을 수 있다.")
            lines.append("")
            continue
        if reply.total_rows > 1:
            lines.append(
                f"  ※ 대장에 {reply.total_rows}회차가 있다 — 아래는 **마지막 회차**"
                f"(줄 {record.source_line})뿐이다."
            )
        stamp = record.recorded_at.isoformat() if record.recorded_at else "미기록"
        lines.append(f"  회차: run_id={record.run_id} · 기록 {stamp}")
        lines.append(
            f"  시도/수용/적재: attempted={record.attempted} accepted={record.accepted} "
            f"appended={record.appended}"
        )
        lines.append(f"  outcome: {_counts_text(record.outcome_counts)}")
        lines.append(
            f"  모델 핀(genlog 관측): {record.model_name if record.model_name else _UNRECORDED}"
        )
        lines.extend(_render_seat(record.cloud_seat))
        lines.extend(_render_duplicate_sources(record.duplicate_sources))
        lines.extend(_render_specs(record.spec_outcome_counts, record.spec_plan))
        lines.append("")

    lines.append("## 기계 판독용 증거(JSON)")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps([reply.to_json() for reply in replies], ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점 — exit 0=전 좌석 재료 확보, 1=하나라도 읽지 못함, 2=인자 오류.

    실패해도 **보고서 파일은 쓴다**(2026-08-22 「실패해도 증거가 남는가」) — 무엇을 읽지
    못했는지가 그 자체로 판정 재료이기 때문이다.
    """
    parser = argparse.ArgumentParser(
        prog="problem_corpus_round_reply",
        description=(
            "회차 대장에서 좌석 비교 판정 재료를 뽑아 사람이 읽을 회신으로 쓴다(EOS-121 [F]). "
            "PowerShell이 바이트를 중계하지 않도록 Python이 읽고 Python이 쓴다."
        ),
    )
    parser.add_argument(
        "--round",
        dest="rounds",
        action="append",
        required=True,
        metavar="라벨=대장경로",
        help=(
            "좌석 라벨과 회차 대장 경로 (`openrouter=.eos121-out/openrouter.rounds.jsonl`). "
            "여러 번 줄 수 있고, 준 순서대로 보고서에 실린다."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help=(
            "회신 보고서 경로(덮어쓰기). **BOM 붙은 UTF-8**로 쓴다 — PowerShell "
            "`Get-Content`와 메모장이 BOM을 보고 UTF-8로 디코딩하므로, 파일을 열어 복사하는 "
            "경로에서도 한국어가 깨지지 않는다."
        ),
    )
    args = parser.parse_args(argv)

    replies: list[RoundReply] = []
    for entry in args.rounds:
        label, sep, raw_path = entry.partition("=")
        if not sep or not label.strip() or not raw_path.strip():
            parser.error(f"--round 형식 오류(라벨=경로 필요): {entry!r}")
        replies.append(extract_round_reply(label.strip(), Path(raw_path.strip())))

    text = render_reply_text(replies)
    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 파일이 정본이다 — 인코딩을 **명시**하고, 콘솔 디코딩과 무관하게 바이트를 확정한다.
    with out_path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        handle.write(text)
        handle.flush()

    # 화면 출력은 콘솔 디코딩을 타므로 파일보다 약한 증거다 — 그 사실을 화면이 스스로 말한다.
    sys.stdout.write(text)
    sys.stdout.write(f"\n[회신 파일] {out_path}\n")
    sys.stdout.write(
        "[안내] 화면 표시가 깨져 보이면 콘솔 디코딩 문제이고 파일은 정상이다 — "
        "위 회신 파일을 열어 그 내용을 보내면 된다.\n"
    )

    failed = [reply.label for reply in replies if not reply.ok]
    if failed:
        sys.stderr.write(
            f"[회신 불완전] 판정 재료를 확보하지 못한 좌석: {', '.join(failed)} — "
            "보고서에 사유가 적혀 있다(빈 결과가 아니라 측정 실패다).\n"
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
