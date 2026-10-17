"""발문 다양화 후처리 CLI — 스켈레톤 코퍼스의 question_text만 LLM으로 rephrase(S2-p 후속).

스켈레톤 배치(`problem_corpus_batch.run_corpus_batch`)는 LLM 0·바이트 동일 봉인이 존재 이유라,
비결정 LLM rephrase를 그 안에 넣지 않는다. 대신 이 CLI가 **배치 산출물(JSONL)을 입력으로 받아
발문만 다양화**하는 별도 opt-in 단계다(기본 경로 분리). 수치·정답·선지·distractor는 그대로 두고
`question_text`만 바뀌며, `rephrase.QuestionRephraser`의 결정론 검증 게이트(방정식 substring 봉인·
추가 등식 차단·위생)가 수학적 실체 오염을 원천 차단한다(fail-closed — 검증 실패 시 원문 유지).

hermetic 주의: 이 환경엔 LLM(Ollama·키)이 없어 provider 미주입 시 라이브 호출이 실패한다 — 실
다양화는 Phaiakes9에서 실 provider로 구동한다(llm_generator 라이브 핸드오프 동형). 테스트는
FakeProvider를 `run_corpus_rephrase(..., rephraser=...)`로 주입해 라이브 0으로 검증한다. 따라서
repo에 rephrase 코퍼스 산출물은 커밋하지 않는다(라이브 LLM 산출·Phaiakes9 소관).

**계보(S4-18) 후속 단계**: 이 함수는 의도적으로 slug·problem_id·identity_id를 건드리지 않는다
(`--in` 소스 코퍼스는 읽기 전용이라는 파이프라인 관례 — S2-08 재조정 스크립트와 동형 — 이
함수는 발문만 다양화). 그래서 원본과 slug가 충돌하는 산출물이 나온다 — populate.py의 slug
upsert가 원본과 *같은 DB 행*으로 병합해버리므로, 계보(problem_relation)를 걸려면 이 CLI
실행 *직후* 매번 `scripts/backfill_rephrase_lineage_s4_18.py`를 재실행해 신규 slug 채번·
identity_id·relation을 동기화해야 한다(멱등 — 여러 번 돌려도 안전).

사용법(Phaiakes9):
    python -m whymath_backend.harness.problem_corpus_rephrase --in <src.jsonl> --out <dst.jsonl>

산출: 입력과 같은 순서·같은 필드의 JSONL(발문만 변형분 반영) + 리포트를 JSON으로 stdout에 낸다
(total·rephrased·unchanged). rephrase는 fail-closed라 exit 0(부분 다양화도 정상) — 실패는 리포트의
unchanged 수·사유 표본으로 정직 관측한다(조용한 실패 금지).

harness는 import-linter 계약 밖(조성/ops 층·상위 호출 정상 — problem_corpus_batch 선례).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.l3.equivalent.rephrase import QuestionRephraser

__all__ = ["RephraseCorpusReport", "main", "run_corpus_rephrase"]

# 사유 표본 상한 — 리포트에 unchanged 사유를 몇 건만 실어 관측(로그 폭주 방지).
_REASON_SAMPLE_CAP = 10


@dataclass(frozen=True, slots=True)
class RephraseCorpusReport:
    """발문 다양화 리포트 — 처리·변형·유지 수 + 유지 사유 표본(조용한 실패 금지)."""

    total: int
    attempted: int
    rephrased: int
    unchanged: int
    written: int | None
    in_path: str
    out_path: str
    unchanged_reason_sample: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "attempted": self.attempted,
            "rephrased": self.rephrased,
            "unchanged": self.unchanged,
            "written": self.written,
            "in_path": self.in_path,
            "out_path": self.out_path,
            "unchanged_reason_sample": self.unchanged_reason_sample,
        }


def _read_records(path: Path) -> list[dict[str, Any]]:
    """입력 JSONL을 dict 목록으로 로드(순서 보존·빈 줄 무시). 원 필드 전부 유지."""
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _write_records(path: Path, records: list[dict[str, Any]]) -> int:
    """records를 JSONL로 기록(입력 형태·필드 순서 보존) — 기록 행 수 반환."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    return len(lines)


def run_corpus_rephrase(
    *,
    in_path: Path,
    out_path: Path,
    rephraser: QuestionRephraser,
    limit: int | None = None,
    write: bool = True,
) -> RephraseCorpusReport:
    """코퍼스 발문 다양화 — 각 레코드의 question_text만 rephrase(수치·정답·선지 불변).

    `rephraser`(주입 좌석)가 검증 게이트를 소유한다 — 검증 실패 시 원문 유지(fail-closed)라 이
    함수는 항상 유효한 코퍼스를 산출한다. question_text 외 필드는 전부 그대로 복사한다(얕은 복제
    후 한 키만 교체). `limit`(온도 스윕용)은 rephrase *시도* 수(=LLM 호출 수)의 상한이다 —
    앞에서부터 limit건만 rephrase에 태우고 나머지는 그대로 복사한다(전체 코퍼스 LLM 비용 없이
    고정 샘플로 온도별 rephrased 비율을 싸게 비교). None이면 전건.
    """
    records = _read_records(in_path)
    rephrased_count = 0
    attempted = 0
    reasons: list[str] = []
    out_records: list[dict[str, Any]] = []
    for record in records:
        question = record.get("question_text")
        if not isinstance(question, str) or not question:
            out_records.append(record)  # 발문 부재(메타 전용) — 그대로.
            continue
        if limit is not None and attempted >= limit:
            out_records.append(record)  # 샘플 상한 초과 — 그대로 복사(LLM 미호출).
            continue
        attempted += 1
        outcome = rephraser.rephrase(question)
        updated = dict(record)
        updated["question_text"] = outcome.text
        if outcome.rephrased:
            # PB-17 — LLM 이 발문을 다시 썼다. 소스의 결정론 서명(`deterministic:`)을 그대로 두면
            # LLM 저작분이 결정론으로 위장돼 생성자≠검증자 가드가 거짓 면제된다. 서명을 지워
            # '기록 없음'으로 되돌린다(저작 모델 id 를 모르므로 `llm:` 서명도 지어내지 않는다 →
            # 가드는 fail-closed 로 거부하고 사람이 `--authored-by llm:<모델>`로 선언해야 돈다).
            # 발문이 그대로인 레코드(rephrased=False)는 결정론 원문이므로 서명을 유지한다.
            updated.pop("authored_by", None)
        out_records.append(updated)
        if outcome.rephrased:
            rephrased_count += 1
        elif outcome.reason is not None and len(reasons) < _REASON_SAMPLE_CAP:
            reasons.append(f"{record.get('slug', '?')}: {outcome.reason}")

    written = _write_records(out_path, out_records) if write else None
    total = len(records)
    return RephraseCorpusReport(
        total=total,
        attempted=attempted,
        rephrased=rephrased_count,
        unchanged=total - rephrased_count,
        written=written,
        in_path=str(in_path),
        out_path=str(out_path),
        unchanged_reason_sample=reasons,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 발문 다양화 후 리포트를 JSON으로 stdout에 낸다(fail-closed·항상 exit 0).

    provider 미주입이라 이 CLI는 라이브 provider가 있는 환경(Phaiakes9)에서만 실효한다 — 이
    환경(LLM 0)에서 호출하면 전건 provider 예외로 unchanged(원문 유지)가 되고, 리포트가 그
    사실을 정직히 드러낸다(조용한 실패 금지).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_corpus_rephrase",
        description=(
            "발문 다양화 후처리(S2-p) — 스켈레톤 코퍼스의 question_text만 LLM으로 rephrase하고 "
            "수치 불변 검증 게이트로 봉인한다(수치·정답 불변·fail-closed)."
        ),
    )
    parser.add_argument("--in", dest="in_path", type=Path, required=True, help="입력 JSONL 경로.")
    parser.add_argument("--out", dest="out_path", type=Path, required=True, help="산출 JSONL 경로.")
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="rephrase 샘플링 온도(기본 0.7 — 라이브 스윕 실측 스윗스팟·2026-07-07).",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="rephrase 시도 상한(온도 스윕 샘플·기본 전건)."
    )
    args = parser.parse_args(argv)

    rephraser = QuestionRephraser(temperature=args.temperature)
    try:
        report = run_corpus_rephrase(
            in_path=args.in_path,
            out_path=args.out_path,
            rephraser=rephraser,
            limit=args.limit,
        )
    finally:
        # 짧게 끝나는 CLI — 저작 호출의 Langfuse `l3_routing` 배치를 종료 전에 확정(OPS-84).
        rephraser.flush()
    json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
