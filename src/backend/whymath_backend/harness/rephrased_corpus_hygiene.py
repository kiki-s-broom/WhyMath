"""rephrased 코퍼스 발문 위생 일괄 적용 CLI — 위반 문항 제거(정직 축소·S3-12·결정론·LLM 0).

S3-09 감사가 확정한 rephrase 발문 텍스트 결함(한자·가나 주입/메타 라벨 누출/비표준 용어/
요구-정답 부정합/조사 오류)은 **결정론 교정이 불가**하다 — 수치 불변 봉인 때문에 발문만 LLM으로
다시 써야 하는데 이 환경은 LLM 재생성이 불가하다(Phaiakes9 라이브 전용). 따라서 위반 문항의
**탈락(제거)이 정본**이다: `rephrase_hygiene.question_hygiene_violations`(rephrase 수용 게이트
⑤축과 동일 검사기)를 커밋 코퍼스 전건에 적용해 위반 레코드를 걷어낸다.

바이트 보존: 생존 레코드는 **원 JSONL 라인 그대로** 다시 쓴다(재직렬화 0 — 무변경 필드의
바이트 드리프트 금지). 산출 리포트는 총·생존·탈락 수, 사유 분포, 탈락 (slug, 사유) 목록을
JSON으로 낸다(재검수 근거·조용한 축소 금지).

개별 감사 확정 제거(`_KNOWN_DEFECTIVE_SLUGS`): rotation-1 재검수가 발견한 어형 붕괴(존재하지
않는 활용형 — "크다음 근"·"크다 가르키는")는 결정론 패턴화가 불가능해(형태소 분석 필요·과공학
방지) 명시 slug로 소급 제거한다. 패턴 축(①~⑥)과 달리 이 목록은 **범용 게이트가 아니다** —
신규 재서술 배치의 같은 결함은 여기서 안 잡힌다(정직 한계).

QUAL-03(2026-08-10)이 `question_hygiene_violations`에 ⑦축(무변화 — `original_text` 선택 인자)을
추가했지만, **이 CLI는 의도적으로 그 인자를 넘기지 않는다**. 이유 둘: ① 이 도구는 라인 단위
순회(`run_corpus_hygiene_sweep`이 한 줄씩 읽고 그 자리에서 판정한다)라 "이 레코드의 원본"을
알려면 `relations[].parent_slug`로 다른 레코드(같은 파일 또는 다른 코퍼스)를 찾아 조인해야
하는데, 그건 현재 구조와 맞지 않는다(전체 코퍼스를 먼저 인덱싱해야 함 — 별도 설계). ② 더
결정적으로, `write=True`가 기본값이다(위 경고 그대로) — ⑦축을 여기 켠 채로 실수로 write 모드를
돌리면 무변화 레코드 전부가 **조용히 코퍼스에서 사라진다**. 무변화 레코드의 처리(재생성/은퇴/
현행유지)는 콘텐츠 판정이라 사람/오케스트레이터의 몫이지 이 자동 스윕의 몫이 아니다. 재서술
*신규 생성* 시점의 무변화 차단은 `l3/equivalent/rephrase.classify_invariance_failure`가
담당한다(그 함수는 rephrase 직후 `original_text=`원 발문을 넘겨 ⑦축을 활성화한다 — 아직
코퍼스에 편입되기 *전*에 막으므로 삭제 위험이 없다). 기존(커밋된) 재서술 레코드의 무변화 실측치는
`harness.problem_duplication_audit`(QUAL-01/QUAL-03 통합 리포트 §7)를 참고한다 — 이 파일은
`write=False`(`--dry-run`)로 실행해도 무변화를 계산하지 않는다(위 이유대로 배선하지 않았으므로).

사용:
    python -m whymath_backend.harness.rephrased_corpus_hygiene            # 커밋 코퍼스 in-place
    python -m whymath_backend.harness.rephrased_corpus_hygiene --dry-run       # 판정만 출력
    python -m whymath_backend.harness.rephrased_corpus_hygiene --in A --out B  # 경로 지정

harness는 import-linter 계약 밖(조성/ops 층 — problem_corpus_rephrase 선례).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.l3.equivalent.rephrase_hygiene import question_hygiene_violations

__all__ = ["HygieneSweepReport", "main", "run_corpus_hygiene_sweep"]

# 개별 감사 확정 제거(GRAMMAR_BREAK) — rotation-1 재검수가 발견한 어형 붕괴 실사례
# (`wm-skel-d5f5ea458863` "두 실근 중 크다음 근을"·`wm-skel-21ac53993db8` "크다 가르키는 값" —
# 존재하지 않는 활용형)는 형태소 분석·맞춤법 검사기 없이는 결정론 일반화가 불가능하다
# (`rephrase_hygiene.py` 도크스트링 "잔존 한계" 참조 — 과공학 방지). 개별 확인된 결함이므로
# 패턴화 대신 명시 목록으로 제거한다 — 신규 재서술 배치가 같은 어형 붕괴를 다시 만들면
# 이 목록이 아니라 재서술 프롬프트/모델 축에서 막아야 한다(이 목록은 소급 청소 전용).
_KNOWN_DEFECTIVE_SLUGS: frozenset[str] = frozenset({"wm-skel-d5f5ea458863", "wm-skel-21ac53993db8"})
_REASON_MANUAL_AUDIT = "MANUAL_AUDIT_GRAMMAR_BREAK"


def _default_corpus_path() -> Path:
    # src/backend/whymath_backend/harness/ → repo root 4단계(problem_corpus_batch 규약 미러).
    root = Path(__file__).resolve().parents[4]
    return root / "data" / "corpus" / "problem_bank_rephrased_v0" / "problems.jsonl"


@dataclass(frozen=True, slots=True)
class HygieneSweepReport:
    """일괄 적용 결과 — 총/생존/탈락 + 사유 분포 + 탈락 (slug, 사유들) 목록(불변)."""

    total: int
    kept: int
    dropped: int
    reason_counts: dict[str, int]
    dropped_items: tuple[tuple[str, tuple[str, ...]], ...]

    def to_json(self) -> dict[str, object]:
        return {
            "total": self.total,
            "kept": self.kept,
            "dropped": self.dropped,
            "reason_counts": dict(sorted(self.reason_counts.items())),
            "dropped_items": [
                {"slug": slug, "violations": list(violations)}
                for slug, violations in self.dropped_items
            ],
        }


def run_corpus_hygiene_sweep(
    in_path: Path, out_path: Path | None, *, write: bool = True
) -> HygieneSweepReport:
    """코퍼스 전건에 발문 위생 게이트 적용 — 위반 제거·생존 라인 바이트 보존(순수 파일 IO).

    각 라인을 파싱해 `question_text`를 검사하고, 위반이 하나라도 있으면 탈락시킨다. 파싱 불가
    라인은 **오염으로 단정하지 않고 예외를 그대로 던진다**(침묵 실패 금지 — 코퍼스 형식 파손은
    위생 문제가 아니라 적재 문제라 fail-loud).
    """
    raw_lines = [line for line in in_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept_lines: list[str] = []
    dropped_items: list[tuple[str, tuple[str, ...]]] = []
    reason_counts: Counter[str] = Counter()
    for line_num, line in enumerate(raw_lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:  # 형식 파손은 fail-loud(예외 타입 포함).
            raise ValueError(f"JSONDecodeError line {line_num}: {exc}") from exc
        question = str(record.get("question_text") or "")
        slug = str(record.get("slug") or f"line-{line_num}")
        violations = question_hygiene_violations(question)
        if slug in _KNOWN_DEFECTIVE_SLUGS:
            violations = (*violations, _REASON_MANUAL_AUDIT)
        if violations:
            dropped_items.append((slug, violations))
            for violation in violations:
                reason_counts[violation.split(":", 1)[0]] += 1
        else:
            kept_lines.append(line)

    if write:
        resolved_out = out_path if out_path is not None else in_path
        resolved_out.write_text(
            "\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8"
        )
    return HygieneSweepReport(
        total=len(raw_lines),
        kept=len(kept_lines),
        dropped=len(dropped_items),
        reason_counts=dict(reason_counts),
        dropped_items=tuple(dropped_items),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI — rephrased 코퍼스 발문 위생 일괄 적용(탈락 목록·사유 분포 JSON 출력·exit 0)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.rephrased_corpus_hygiene",
        description="rephrase 발문 위생 게이트를 커밋 코퍼스에 일괄 적용해 위반 문항 제거.",
    )
    parser.add_argument("--in", dest="in_path", default=None, help="입력 코퍼스 JSONL 경로.")
    parser.add_argument("--out", dest="out_path", default=None, help="출력 경로(기본 in-place).")
    parser.add_argument("--dry-run", action="store_true", help="파일 기록 없이 판정만 출력.")
    args = parser.parse_args(argv)

    in_path = Path(args.in_path) if args.in_path else _default_corpus_path()
    out_path = Path(args.out_path) if args.out_path else None
    report = run_corpus_hygiene_sweep(in_path, out_path, write=not args.dry_run)
    print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
