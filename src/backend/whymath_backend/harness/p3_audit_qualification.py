"""P3-03 미분 은행 감사자 자격 측정 — 결함 주입 강등전 CLI(순수·결정론·LLM 호출 0).

정본: `docs/standards/superhuman_verification_standard.md` §0·§3과
`docs/data/p3_calculus1_diff_audit/qualification/README.md`.

왜 필요한가
-----------
은행 `problem_bank_p3_calculus1_diff_v0`(504건)은 LLM 감사 4회에 불합격했고, 사람 표본 검수 경로는
철회됐다(2026-10-08). 이유는 같다 — 감사자(사람이든 LLM이든) 자신의 **검출률·오경보율을 잰 적이 없는
채로** 그 판정을 승인 근거로 쓰려 했다. 이 도구는 감사자를 먼저 시험한다: 정답을 아는 결함
120건 + 정상 120건 시험지(`l3/equivalent/p3_diff_defect_seeder`)를 블라인드로 내고, 감사
프로토콜(기계 게이트 ∪ LLM 이중 판정)의 검출률·오경보율을 Wilson 경계로 판정한다. 측정을
통과한 프로토콜의 판정만 은행 S5(결함률 상한) 근거가 된다.

합격 기준(Kiki 결정 2026-10-08 — 아래 상수가 단일 원천)
----------------------------------------------------
· 시험지: 결함 120 + 정상 120 = 240(seed 고정·결정론), 결함 7종·종류마다 15건 이상.
· 감사 프로토콜 = 기계 게이트 전부 ∪ LLM 이중 판정(판정자 2명 이상, 한 명이라도 결함이면 결함).
· 합격 = 전체 검출률 Wilson 95% 단측 하한 ≥ 0.90 **그리고** 결함 종류별 검출률 점추정 ≥ 0.80
  **그리고** 정상 문항 오경보율 Wilson 95% 단측 상한 ≤ 0.10.
· 합격 뒤 은행 S5: 프로토콜로 504건을 감사해 관측 결함 k → 보정 상한 = Wilson 상한(k, 504) ÷ 검출률
  Wilson 하한 ≤ 0.02이면 승인 근거. 두 경계는 **각각 단측 97.5%**(`S5_CONFIDENCE` — 판정 전
  사전 등록 `qualification/rater_protocol.md` "S5 보정의 신뢰도")로 다시 계산해 합성 신뢰도
  ≥ 95%를 맞춘다. 자격 판정(위 세 줄)의 95%와는 별개다.

서브커맨드
----------
  emit     시험지(블라인드)·정답지·정답지 sha256·매니페스트 발행. `--check`는 재생성해 커밋된 시험지
           바이트와 등록 지문을 대조한다(드리프트 1).
  machine  기계 게이트 전부를 문항마다 돌려 판정 라벨(어느 게이트가 잡았는지 포함)을 낸다. 시험지와
           은행 둘 다에 쓴다(`--id-field`). `--check`는 커밋된 라벨과 대조.
  score    시험지·정답지(+사전 등록 지문)·기계 라벨·LLM 판정자 라벨 → 기계 단독·LLM 단독·프로토콜
           표와 합격 판정. `--machine-only`는 기계 구성요소만 판정한다(프로토콜 판정이 아니다).
  bank-sheets  은행 504건 → 판정자 묶음(시험지와 같은 필드·`item_id` 자리에 `problem_id`). 은행
           순서를 seed로 섞어 같은 크기로 나누고 묶음별 sha256을 매니페스트에 적는다. `--check`는
           재생성해 커밋된 매니페스트와 대조한다(묶음 파일은 저장소 밖 판정자 입력 폴더에 둔다).
  s5       은행 감사 라벨(기계 + LLM ≥ 2) + 합격한 자격 측정 결과 → 보정 결함률 상한 판정.

종료 코드: 0 = 합격 · 1 = 불합격 · 2 = 입력 오류(시험지 id 누락·중복·미지 id, 판정자 수 부족, 정답지
지문 불일치, 기준 상수 불일치 — 통과로 위장하지 않는다).

7계층: harness(검증 게이트 층) — L1(파생 형태 규칙)·L3(수용 게이트·재검증·판정기·스캐너·주입기)·
L4(오개념 카탈로그 — 시험지에 오개념 설명을 싣는 용도)를 읽기만 한다. DB 0·네트워크 0·LLM 호출 0
(LLM 판정자 라벨은 이 도구 밖에서 만들어 파일로 들어온다).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from whymath_backend.harness.corpus_reverify import reverify_corpus
from whymath_backend.harness.p3_calculus1_diff_batch import GENERATORS
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l1.problem_bank.derived_form_rules import derived_form_violations
from whymath_backend.l3.equivalent.acceptance import evaluate_equivalent_candidate
from whymath_backend.l3.equivalent.p3_diff_defect_seeder import (
    BANK_DEFECT_CLASSES,
    QUALIFICATION_SEED,
    SeededBankItem,
    build_qualification_set,
)
from whymath_backend.l3.equivalent.p3_diff_shortcut_guard import (
    POST_QUALIFICATION_RULE_IDS,
    probe_from_record,
    shortcut_violations,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import seeded_order
from whymath_backend.l3.equivalent.p3_diff_text_scanner import (
    josa_and_notation_defects,
    round2_defects,
    undefined_function_defects,
)
from whymath_backend.l3.equivalent.retag import StatementConsistencyAuditor
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.schema.enums import GenerationType, LicenseType
from whymath_backend.schema.problem import Problem
from whymath_backend.schema.provenance import ContentProvenance

__all__ = [
    "CONFIDENCE",
    "MAX_FALSE_ALARM_UPPER",
    "MIN_CLASS_DETECTION_POINT",
    "MIN_DEFECTS_PER_CLASS",
    "MIN_DETECTION_LOWER",
    "MIN_LLM_JUDGES",
    "QUALIFICATION_N_CLEAN",
    "QUALIFICATION_N_DEFECTIVE",
    "BANK_AUDIT_SEED",
    "BANK_AUDIT_SHARDS",
    "S5_BANK_SIZE",
    "S5_CONFIDENCE",
    "S5_MAX_CORRECTED_UPPER",
    "EXCLUDED_GUARD_RULES",
    "VOTING_GATES",
    "BankSheets",
    "ComponentResult",
    "QualificationInputError",
    "build_bank_sheets",
    "corrected_upper_bound",
    "criteria",
    "evaluate_component",
    "machine_label",
    "main",
    "s5_detection_lower",
]

# ──────────────────────────────────────────────────────────────────────────
# 합격 기준 — Kiki 결정 2026-10-08(코드 상수가 단일 원천 · README가 같은 값을 적는다)
# ──────────────────────────────────────────────────────────────────────────
QUALIFICATION_N_DEFECTIVE: Final = 120
QUALIFICATION_N_CLEAN: Final = 120
MIN_DEFECTS_PER_CLASS: Final = 15
CONFIDENCE: Final = 0.95
MIN_DETECTION_LOWER: Final = 0.90
MIN_CLASS_DETECTION_POINT: Final = 0.80
MAX_FALSE_ALARM_UPPER: Final = 0.10
MIN_LLM_JUDGES: Final = 2
S5_BANK_SIZE: Final = 504
S5_MAX_CORRECTED_UPPER: Final = 0.02
#: S5 보정에 쓰는 두 단측 경계의 신뢰도(Bonferroni: 1 − 2 × 0.025 = 0.95). 판정 전 사전
#: 등록(`rater_protocol.md` "S5 보정의 신뢰도" · 커밋 c1529ffd). 자격 판정 기준이 아니므로
#: `criteria()`에 넣지 않는다 — 넣으면 이미 채점된 자격 결과(`score.json`)의 기준 묶음이 바뀌어
#: 재채점이 필요해진다.
S5_CONFIDENCE: Final = 0.975
#: 은행 감사 묶음 — 504 = 8 × 63(자격 측정 묶음 60건에 가장 가까운 등분). 순서 시드는 자격 측정과
#: 같은 날짜 시드를 쓰되 용도 접미사로 구분한다(`seeded_order` 문자열 시드).
BANK_AUDIT_SHARDS: Final = 8
BANK_AUDIT_SEED: Final = 20261008
#: 점수 JSON의 95% 검출 하한과 같은 JSON의 원 계수에서 다시 계산한 값의 허용 오차(부동소수 반올림).
_LOWER_RECOMPUTE_TOL: Final = 1e-9

EXIT_PASS: Final = 0
EXIT_FAIL: Final = 1
EXIT_INPUT_ERROR: Final = 2

#: 판정에 투표하는 기계 게이트(하나라도 걸면 결함).
#: 이름은 라벨 파일·보고서·정답지 `gate_overlap`의 어휘다.
VOTING_GATES: Final[tuple[str, ...]] = (
    "schema",
    "reverify",
    "acceptance",
    "shortcut_guard",
    "text_scanner",
    "derived_form",
)
#: 진단 전용(투표하지 않음) — 발문-수식 정합 감사기는 이 은행의 정상 504건 중 164건을 거부한다
#: (2026-10-08 실측 — 이차방정식 단일 등식 발문용으로 설계돼 'f(x) = x^6'을 '(x) = x^6'으로 뽑는다).
#: 투표에 넣으면 오경보율이 구성상 기준을 넘으므로 빼고, 그 수치는 보고서에 따로 낸다.
DIAGNOSTIC_GATES: Final[tuple[str, ...]] = ("statement_auditor",)
#: 감사 프로토콜의 기계 투표에서 빼는 우회로 판정기 규칙 — 자격 측정을 통과한 프로토콜은 4회차 규칙
#: 집합의 판정기다. 측정 뒤에 더한 회차 규칙 전부(`POST_QUALIFICATION_RULE_IDS` — 5회차 은행 감사
#: 처분 + 6회차 은행 감사 2회차 처분 + 7회차 은행 감사 3회차 처분)는 생성기 빌드의 fail-loud
#: 가드로만 쓴다: 5회차 규칙만 투표에 넣어도 시험지 정상 120건 중 26건을 거부해(그 문항들은 은행
#: v0의 같은 부류) 오경보가 6 → 27로 늘고 프로토콜이 자격 기준(오경보 상한 ≤ 0.10)을 잃는다. 새
#: 은행은 그 규칙들을 빌드에서 통과해야만 만들어지므로 투표에 넣든 빼든 은행 라벨은 같다.
EXCLUDED_GUARD_RULES: Final[frozenset[str]] = POST_QUALIFICATION_RULE_IDS

_VERDICTS: Final = frozenset({"ok", "defect"})
_BLIND_VERIFY_KEYS: Final = (
    "conditions",
    "answer_map",
    "solution_steps",
    "answer_selection",
    "answer_kind",
)
_MISCONCEPTIONS_V1: Final = Path("data/corpus/misconceptions_v1/misconceptions.json")
_BANK_PATH: Final = Path("data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl")
_QUAL_DIR: Final = Path("docs/data/p3_calculus1_diff_audit/qualification")
_BANK_AUDIT_DIR: Final = Path("docs/data/p3_calculus1_diff_audit/bank_audit")
#: S5 1회차 감사(k = 68)를 받은 은행 v0의 동결 사본(sha256 cc7e9539…). 자격 시험지(emit)는
#: 이 은행에서 만들어졌으므로 생성기 교정으로 현 은행이 바뀐 뒤에도 재현 대조는 이 사본을
#: 기준으로 한다.
_AUDITED_BANK_PATH: Final = _BANK_AUDIT_DIR / "audited_bank.jsonl"


class QualificationInputError(ValueError):
    """입력 오류 — exit 2. 판정을 내릴 수 없는 입력은 통과로도 불합격으로도 위장하지 않는다."""


def criteria() -> dict[str, float | int]:
    """합격 기준 상수 묶음 — 점수 JSON에 박아 s5가 기준 변경(위·변조 포함)을 알아챈다."""
    return {
        "n_defective": QUALIFICATION_N_DEFECTIVE,
        "n_clean": QUALIFICATION_N_CLEAN,
        "min_defects_per_class": MIN_DEFECTS_PER_CLASS,
        "confidence": CONFIDENCE,
        "min_detection_lower": MIN_DETECTION_LOWER,
        "min_class_detection_point": MIN_CLASS_DETECTION_POINT,
        "max_false_alarm_upper": MAX_FALSE_ALARM_UPPER,
        "min_llm_judges": MIN_LLM_JUDGES,
        "s5_bank_size": S5_BANK_SIZE,
        "s5_max_corrected_upper": S5_MAX_CORRECTED_UPPER,
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise QualificationInputError(f"{path} {number}행: JSON 파싱 실패({exc.msg})") from exc
        if not isinstance(row, dict):
            raise QualificationInputError(f"{path} {number}행: 객체가 아니다")
        rows.append(row)
    return rows


def _jsonl_text(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# emit — 블라인드 시험지·정답지
# ──────────────────────────────────────────────────────────────────────────
def _misconception_statements() -> dict[str, str]:
    """오개념 id → 설명(판정자가 선지 연결을 판단할 재료). kebab은 L4 카탈로그, M-id는 v1 코퍼스."""
    out = {
        mid: f"{entry.name_kr}: {entry.canonical_statement}" for mid, entry in CATALOG_BY_ID.items()
    }
    path = _repo_root() / _MISCONCEPTIONS_V1
    corpus = json.loads(path.read_text(encoding="utf-8"))
    for row in corpus.get("misconceptions", []):
        mid = str(row.get("mis_id") or "")
        if mid and mid not in out:
            out[mid] = (
                f"{row.get('canonical_statement', '')} — {row.get('student_wrong_thinking', '')}"
            )
    return out


def _blind_record(
    item: SeededBankItem, item_id: str, statements: Mapping[str, str]
) -> dict[str, Any]:
    """시험지 1문 — 문항 필드만(결함 여부·종류·원본 id·slug·problem_id 없음)."""
    return _blind_fields(item.record, item_id, statements)


def _blind_fields(
    rec: Mapping[str, Any], item_id: str, statements: Mapping[str, str]
) -> dict[str, Any]:
    """판정자에게 주는 문항 필드(시험지·은행 감사 묶음 공용 — 형식이 같아야 검출률이 옮겨 간다)."""
    verify = rec.get("verify") or {}
    distractors = rec.get("distractor_map")
    blind_map = None
    if isinstance(distractors, list):
        blind_map = [
            {
                "choice_index": entry["choice_index"],
                "misconception_id": entry["misconception_id"],
                "misconception_statement": statements.get(str(entry["misconception_id"]), ""),
            }
            for entry in distractors
        ]
    return {
        "item_id": item_id,
        "achievement_standard_codes": rec.get("achievement_standard_codes"),
        "tags": rec.get("tags"),
        "question_format": rec.get("question_format"),
        "answer_format": rec.get("answer_format"),
        "question_text": rec.get("question_text"),
        "choices": rec.get("choices"),
        "answer": rec.get("answer"),
        "answer_explanation": rec.get("answer_explanation"),
        "distractor_map": blind_map,
        "verify": {k: verify[k] for k in _BLIND_VERIFY_KEYS if k in verify},
    }


def _key_record(item: SeededBankItem, item_id: str) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "is_defective": item.is_defective,
        "defect_class": item.defect_class,
        "variant": item.variant,
        "gt_basis": item.gt_basis,
        "gate_overlap": item.gate_overlap,
        "source_problem_id": item.source_problem_id,
        "mutation_note": item.mutation_note,
    }


@dataclass(frozen=True, slots=True)
class EmittedSet:
    """발행 산출(바이트) — 시험지·정답지·지문 파일·매니페스트."""

    blind: str
    answer_key: str
    sha256_line: str
    manifest: str


def build_emitted_set(bank_path: Path, seed: int) -> EmittedSet:
    """은행 → 시험지·정답지 텍스트(결정론). 시험지 순서는 seed로 섞고 id는 q001…로 재부여한다."""
    bank_bytes = bank_path.read_bytes()
    bank = _read_jsonl(bank_path)
    items = build_qualification_set(bank, seed=seed)
    ordered = list(seeded_order(f"{seed}:blind-order", items))
    statements = _misconception_statements()
    width = len(str(len(ordered)))
    ids = [f"q{index:0{width}d}" for index in range(1, len(ordered) + 1)]
    blind = _jsonl_text(
        [_blind_record(i, q, statements) for i, q in zip(ordered, ids, strict=True)]
    )
    key = _jsonl_text([_key_record(i, q) for i, q in zip(ordered, ids, strict=True)])
    key_sha = _sha256(key.encode("utf-8"))
    counts = Counter(str(i.defect_class) for i in items if i.is_defective)
    manifest = {
        "task": "P3-03-coverage-fill",
        "purpose": "감사자 자격 측정(결함 주입 강등전) 시험지",
        "seed": seed,
        "bank": str(_BANK_PATH),
        "bank_sha256": _sha256(bank_bytes),
        "blind_sha256": _sha256(blind.encode("utf-8")),
        "answer_key_sha256": key_sha,
        "n_items": len(items),
        "n_defective": sum(counts.values()),
        "n_clean": len(items) - sum(counts.values()),
        "defect_class_counts": {cls: counts[cls] for cls in BANK_DEFECT_CLASSES},
        "criteria": criteria(),
        "generator": "whymath_backend.l3.equivalent.p3_diff_defect_seeder.build_qualification_set",
    }
    return EmittedSet(
        blind=blind,
        answer_key=key,
        sha256_line=f"{key_sha}  answer_key.jsonl\n",
        manifest=json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )


@dataclass(frozen=True, slots=True)
class BankSheets:
    """은행 감사 묶음(바이트) — 묶음 텍스트 목록·매니페스트."""

    shards: tuple[str, ...]
    manifest: str


def build_bank_sheets(bank_path: Path, seed: int, n_shards: int) -> BankSheets:
    """은행 → 판정자 묶음(결정론). 은행 순서를 seed로 섞어 같은 크기로 나눈다.

    은행 파일 순서는 개념·슬롯별로 몰려 있다 — 그대로 자르면 묶음 하나가 한 개념만 담아 판정자의
    주의 패턴이 자격 측정(개념이 섞인 시험지)과 달라진다. 그래서 섞는다. `item_id` 자리에는
    `problem_id`를 그대로 둔다(사전 등록 지침 "산출 형식" — s5가 은행 id로 라벨을 맞춘다).
    """
    bank_bytes = bank_path.read_bytes()
    bank = _read_jsonl(bank_path)
    ids = [str(r.get("problem_id") or "") for r in bank]
    if len(set(ids)) != len(ids) or "" in ids or len(bank) != S5_BANK_SIZE:
        raise QualificationInputError(
            f"은행 문항 {len(bank)}건(고유 id {len(set(ids))}) — 기준 {S5_BANK_SIZE}건과 다르다"
        )
    if n_shards <= 0 or len(bank) % n_shards:
        raise QualificationInputError(f"은행 {len(bank)}건을 묶음 {n_shards}개로 등분할 수 없다")
    statements = _misconception_statements()
    canonical = sorted(bank, key=lambda r: str(r["problem_id"]))
    ordered = seeded_order(f"{seed}:bank-audit-order", canonical)
    size = len(ordered) // n_shards
    shards = tuple(
        _jsonl_text(
            [
                _blind_fields(rec, str(rec["problem_id"]), statements)
                for rec in ordered[index * size : (index + 1) * size]
            ]
        )
        for index in range(n_shards)
    )
    manifest = {
        "task": "P3-03-coverage-fill",
        "purpose": "은행 감사(S5) 판정자 묶음 — 자격 측정과 같은 필드·같은 지침(rater_protocol.md)",
        "seed": seed,
        "bank": str(_BANK_PATH),
        "bank_sha256": _sha256(bank_bytes),
        "n_items": len(bank),
        "n_shards": n_shards,
        "shard_size": size,
        "shards": [
            {"file": f"shard{index + 1}.jsonl", "sha256": _sha256(text.encode("utf-8"))}
            for index, text in enumerate(shards)
        ],
        "rater_protocol_sha256": _sha256(
            (_repo_root() / _QUAL_DIR / "rater_protocol.md").read_bytes()
        ),
    }
    return BankSheets(
        shards=shards, manifest=json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )


def _cmd_bank_sheets(args: argparse.Namespace) -> int:
    sheets = build_bank_sheets(Path(args.bank), args.seed, args.shards)
    manifest_path = Path(args.manifest)
    if args.check:
        same = (
            manifest_path.exists() and manifest_path.read_text(encoding="utf-8") == sheets.manifest
        )
        print("bank-sheets --check:", "일치" if same else f"매니페스트 드리프트: {manifest_path}")
        return EXIT_PASS if same else EXIT_FAIL
    if args.out_dir is None:
        raise QualificationInputError("--out-dir 경로가 필요하다(판정자 입력 폴더 — 저장소 밖)")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for index, text in enumerate(sheets.shards, start=1):
        (out_dir / f"shard{index}.jsonl").write_text(text, encoding="utf-8")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(sheets.manifest, encoding="utf-8")
    print(f"묶음 {len(sheets.shards)}개 → {out_dir} · 매니페스트 {manifest_path}")
    return EXIT_PASS


def _registered_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    digest = text.split()[0] if text else ""
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise QualificationInputError(f"{path}: sha256 지문 형식이 아니다")
    return digest


def _cmd_emit(args: argparse.Namespace) -> int:
    emitted = build_emitted_set(Path(args.bank), args.seed)
    blind_path, sha_path = Path(args.blind), Path(args.sha256)
    manifest_path = Path(args.manifest) if args.manifest else blind_path.parent / "manifest.json"
    if args.check:
        problems = []
        if not blind_path.exists() or blind_path.read_text(encoding="utf-8") != emitted.blind:
            problems.append(f"시험지 드리프트: {blind_path}")
        if not sha_path.exists() or _registered_sha(sha_path) != emitted.sha256_line.split()[0]:
            problems.append(f"정답지 지문 드리프트: {sha_path}")
        if (
            not manifest_path.exists()
            or manifest_path.read_text(encoding="utf-8") != emitted.manifest
        ):
            problems.append(f"매니페스트 드리프트: {manifest_path}")
        for problem in problems:
            print(problem)
        print("emit --check:", "일치" if not problems else f"불일치 {len(problems)}건")
        return EXIT_FAIL if problems else EXIT_PASS
    if args.answer_key is None:
        raise QualificationInputError("--answer-key 경로가 필요하다(저장소 밖에 둔다)")
    key_path = Path(args.answer_key)
    for path in (blind_path, key_path, sha_path, manifest_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    blind_path.write_text(emitted.blind, encoding="utf-8")
    key_path.write_text(emitted.answer_key, encoding="utf-8")
    sha_path.write_text(emitted.sha256_line, encoding="utf-8")
    manifest_path.write_text(emitted.manifest, encoding="utf-8")
    print(f"시험지 {blind_path} · 정답지 {key_path} · 지문 {sha_path} · 매니페스트 {manifest_path}")
    print(f"정답지 sha256 {emitted.sha256_line.split()[0]}")
    return EXIT_PASS


# ──────────────────────────────────────────────────────────────────────────
# machine — 기계 게이트 전부
# ──────────────────────────────────────────────────────────────────────────
_GENERATOR_BY_CODE: Final = {g.standard_code: g for g in GENERATORS}
_PROVENANCE: Final = ContentProvenance(
    generation_type=GenerationType.FULLY_GENERATED,
    license=LicenseType.WHYMATH_GENERATED,
    original_source=None,
)


def _slot_of(record: Mapping[str, Any]) -> str:
    for tag in record.get("tags") or []:
        if str(tag).startswith("p3-slot:"):
            return str(tag).split(":", 1)[1]
    return ""


def _problem_of(record: Mapping[str, Any], ident: str) -> Problem:
    """문항 필드 → 수용 게이트가 받는 `Problem`(시험지에 없는 메타는 개념 생성기에서 채운다)."""
    code = str((record.get("achievement_standard_codes") or [""])[0])
    generator = _GENERATOR_BY_CODE.get(code)
    slot = _slot_of(record)
    if generator is None or slot not in generator.slot_difficulty:
        raise QualificationInputError(f"{ident}: 알 수 없는 개념·슬롯({code}·{slot})")
    distractors = record.get("distractor_map")
    return Problem.model_validate(
        {
            "problem_id": uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:p3-qualification:{ident}"),
            "slug": f"wm-p3-qual-{ident}",
            "source_type": "자체생성",
            "curriculum_version": "2022_REVISION",
            "valid_from_year": 2022,
            "subject": "미적분",
            "unit_codes": [generator.unit_code],
            "difficulty_overall": generator.slot_difficulty[slot],
            "question_format": record.get("question_format"),
            "answer_format": record.get("answer_format"),
            "achievement_standard_codes": record.get("achievement_standard_codes"),
            "question_text": record.get("question_text"),
            "choices": record.get("choices"),
            "answer": record.get("answer"),
            "answer_explanation": record.get("answer_explanation"),
            "distractor_map": (
                [
                    {"choice_index": e["choice_index"], "misconception_id": e["misconception_id"]}
                    for e in distractors
                ]
                if isinstance(distractors, list)
                else None
            ),
            "tags": record.get("tags"),
        }
    )


def _text_findings(record: Mapping[str, Any]) -> list[str]:
    question = str(record.get("question_text") or "")
    explanation = str(record.get("answer_explanation") or "")
    texts = [question, explanation, *(str(c) for c in record.get("choices") or [])]
    found = [kind for text in texts for kind, _ in josa_and_notation_defects(text)]
    found += [f"undefined:{name}" for name in undefined_function_defects(question, explanation)]
    found += round2_defects(record)
    return sorted(set(found))


def machine_label(record: Mapping[str, Any], ident: str) -> dict[str, Any]:
    """문항 1건에 기계 게이트 전부 → 라벨(투표 게이트 중 하나라도 걸면 defect)."""
    raw_verify = record.get("verify")
    verify: dict[str, Any] = raw_verify if isinstance(raw_verify, dict) else {}
    conditions = verify.get("conditions")
    if not isinstance(conditions, (str, list)):
        raise QualificationInputError(f"{ident}: verify.conditions가 없다")
    answer_map = {str(k): str(v) for k, v in (verify.get("answer_map") or {}).items()}
    fired: list[str] = []
    reasons: list[str] = []
    diagnostic: dict[str, str] = {}

    problem: Problem | None = None
    try:
        problem = _problem_of(record, ident)
    except ValidationError as exc:
        fired.append("schema")
        reasons.append(f"schema: {type(exc).__name__} {exc.error_count()}건")

    report = reverify_corpus(
        [{"slug": ident, "answer": record.get("answer"), "verify": verify}], use_fuzz=False
    )
    if report.failed:
        fired.append("reverify")
        reasons.append(f"reverify: {report.failures[0][1][:120]}")

    if problem is not None:
        code = str((record.get("achievement_standard_codes") or [""])[0])
        spec = _GENERATOR_BY_CODE[code].spec_for(_slot_of(record))
        verdict = evaluate_equivalent_candidate(
            spec,
            problem,
            provenance=_PROVENANCE,
            conditions=conditions,
            answer_map=answer_map,
            solution_steps=verify.get("solution_steps"),
            answer_selection=verify.get("answer_selection"),
            answer_kind=verify.get("answer_kind"),
        )
        if not verdict.accepted:
            fired.append("acceptance")
            reasons.append(f"acceptance: {'; '.join(verdict.reasons)[:160]}")
        audit = StatementConsistencyAuditor(conditions=conditions).audit(
            problem, answer_selection=verify.get("answer_selection")
        )
        diagnostic["statement_auditor"] = "pass" if audit.consistency_ok else "fail"

    rules = sorted(
        {v.rule for v in shortcut_violations(probe_from_record(record))} - EXCLUDED_GUARD_RULES
    )
    if rules:
        fired.append("shortcut_guard")
        reasons.append(f"shortcut_guard: {', '.join(rules)}")

    findings = _text_findings(record)
    if findings:
        fired.append("text_scanner")
        reasons.append(f"text_scanner: {', '.join(findings)}")

    derived = derived_form_violations(
        standard_codes=[str(c) for c in record.get("achievement_standard_codes") or []],
        question_text=str(record.get("question_text") or ""),
        answer=str(record.get("answer") or ""),
        conditions=conditions,
        answer_map=answer_map,
        answer_selection=verify.get("answer_selection"),
    )
    if derived:
        fired.append("derived_form")
        reasons.append(f"derived_form: {', '.join(v.rule for v in derived)}")

    return {
        "item_id": ident,
        "verdict": "defect" if fired else "ok",
        "fired": fired,
        "diagnostic": diagnostic,
        "reasons": reasons,
    }


def build_machine_labels(records: Sequence[Mapping[str, Any]], id_field: str) -> str:
    rows = []
    seen: set[str] = set()
    for number, record in enumerate(records, start=1):
        ident = str(record.get(id_field) or "")
        if not ident:
            raise QualificationInputError(f"{number}행: {id_field}가 없다")
        if ident in seen:
            raise QualificationInputError(f"{id_field} 중복: {ident}")
        seen.add(ident)
        rows.append(machine_label(record, ident))
    return _jsonl_text(rows)


def _cmd_machine(args: argparse.Namespace) -> int:
    labels = build_machine_labels(_read_jsonl(Path(args.input)), args.id_field)
    out = Path(args.out)
    if args.check:
        same = out.exists() and out.read_text(encoding="utf-8") == labels
        print("machine --check:", "일치" if same else f"드리프트({out})")
        return EXIT_PASS if same else EXIT_FAIL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(labels, encoding="utf-8")
    flagged = sum(1 for line in labels.splitlines() if '"verdict": "defect"' in line)
    print(f"기계 라벨 {out} — {len(labels.splitlines())}건 중 결함 판정 {flagged}건")
    return EXIT_PASS


# ──────────────────────────────────────────────────────────────────────────
# score — 구성요소별·프로토콜 판정
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class ComponentResult:
    """구성요소 1개(기계·LLM·프로토콜·판정자 1명)의 검출 집계와 합격 판정."""

    name: str
    per_class: dict[str, tuple[int, int]]
    detected: int
    n_defective: int
    false_alarm: int
    n_clean: int
    per_variant: dict[str, tuple[int, int]] = field(default_factory=dict)
    non_circular: tuple[int, int] = (0, 0)

    @property
    def detection_lower(self) -> float:
        return wilson_lower_bound(self.detected, self.n_defective, CONFIDENCE)

    @property
    def false_alarm_upper(self) -> float:
        return wilson_upper_bound(self.false_alarm, self.n_clean, CONFIDENCE)

    def class_points(self) -> dict[str, float]:
        return {cls: (d / n if n else 0.0) for cls, (d, n) in self.per_class.items()}

    def failures(self) -> list[str]:
        """합격 기준 미달 사유 — 비어 있으면 합격."""
        out: list[str] = []
        if self.detection_lower < MIN_DETECTION_LOWER:
            out.append(
                f"전체 검출률 Wilson 하한 {self.detection_lower:.4f} < {MIN_DETECTION_LOWER}"
            )
        for cls, point in self.class_points().items():
            if point < MIN_CLASS_DETECTION_POINT:
                out.append(f"{cls} 검출률 {point:.3f} < {MIN_CLASS_DETECTION_POINT}")
        if self.false_alarm_upper > MAX_FALSE_ALARM_UPPER:
            out.append(
                f"오경보율 Wilson 상한 {self.false_alarm_upper:.4f} > {MAX_FALSE_ALARM_UPPER}"
            )
        return out

    @property
    def passed(self) -> bool:
        return not self.failures()

    def as_json(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "n_defective": self.n_defective,
            "detection_lower": self.detection_lower,
            "false_alarm": self.false_alarm,
            "n_clean": self.n_clean,
            "false_alarm_upper": self.false_alarm_upper,
            "per_class": {k: list(v) for k, v in self.per_class.items()},
            "passed": self.passed,
            "failures": self.failures(),
        }


def evaluate_component(
    name: str, key: Sequence[Mapping[str, Any]], flagged: Mapping[str, bool]
) -> ComponentResult:
    """정답지 + 문항별 결함 판정 → 집계. 오경보 분모는 정상 문항 수, 검출 분모는 결함 문항 수."""
    per_class: dict[str, list[int]] = {cls: [0, 0] for cls in BANK_DEFECT_CLASSES}
    per_variant: dict[str, list[int]] = {}
    detected = n_defective = false_alarm = n_clean = 0
    nc_detected = nc_total = 0
    for row in key:
        hit = bool(flagged[str(row["item_id"])])
        if row["is_defective"]:
            n_defective += 1
            cls = str(row["defect_class"])
            per_class[cls][1] += 1
            mark = " ◆" if row.get("gate_overlap") else ""
            variant = per_variant.setdefault(f"{cls}/{row.get('variant')}{mark}", [0, 0])
            variant[1] += 1
            if not row.get("gate_overlap"):
                nc_total += 1
            if hit:
                detected += 1
                per_class[cls][0] += 1
                variant[0] += 1
                if not row.get("gate_overlap"):
                    nc_detected += 1
        else:
            n_clean += 1
            if hit:
                false_alarm += 1
    return ComponentResult(
        name=name,
        per_class={k: (v[0], v[1]) for k, v in per_class.items()},
        detected=detected,
        n_defective=n_defective,
        false_alarm=false_alarm,
        n_clean=n_clean,
        per_variant={k: (v[0], v[1]) for k, v in sorted(per_variant.items())},
        non_circular=(nc_detected, nc_total),
    )


def _label_map(rows: Sequence[Mapping[str, Any]], ids: set[str], source: str) -> dict[str, bool]:
    """라벨 파일 → item_id → 결함 여부. 누락·중복·미지 id·판정값 오류는 입력 오류."""
    out: dict[str, bool] = {}
    for row in rows:
        ident = str(row.get("item_id") or "")
        verdict = row.get("verdict")
        if ident in out:
            raise QualificationInputError(f"{source}: item_id 중복 {ident}")
        if ident not in ids:
            raise QualificationInputError(f"{source}: 시험지에 없는 item_id {ident!r}")
        if verdict not in _VERDICTS:
            raise QualificationInputError(f"{source}: {ident} verdict {verdict!r}(ok|defect만)")
        out[ident] = verdict == "defect"
    missing = sorted(ids - set(out))
    if missing:
        raise QualificationInputError(
            f"{source}: 시험지 문항 {len(missing)}건 누락(예 {missing[:3]})"
        )
    return out


def _validated_key(
    blind: Sequence[Mapping[str, Any]], key_path: Path, sha_path: Path
) -> tuple[list[dict[str, Any]], set[str]]:
    ids = [str(r.get("item_id") or "") for r in blind]
    if len(set(ids)) != len(ids) or "" in ids:
        raise QualificationInputError("시험지 item_id가 비었거나 중복된다")
    key_bytes = key_path.read_bytes()
    if _sha256(key_bytes) != _registered_sha(sha_path):
        raise QualificationInputError("정답지 sha256이 사전 등록 지문과 다르다(바꿔치기 의심)")
    key = _read_jsonl(key_path)
    key_ids = [str(r.get("item_id") or "") for r in key]
    if sorted(key_ids) != sorted(ids):
        raise QualificationInputError("정답지와 시험지의 item_id 집합이 다르다")
    defective = [r for r in key if r.get("is_defective")]
    counts = Counter(str(r.get("defect_class")) for r in defective)
    if len(defective) != QUALIFICATION_N_DEFECTIVE or len(key) - len(defective) != (
        QUALIFICATION_N_CLEAN
    ):
        raise QualificationInputError(
            f"시험지 설계 불일치: 결함 {len(defective)}·정상 {len(key) - len(defective)}"
            f"(기준 {QUALIFICATION_N_DEFECTIVE}·{QUALIFICATION_N_CLEAN})"
        )
    if set(counts) != set(BANK_DEFECT_CLASSES) or min(counts.values()) < MIN_DEFECTS_PER_CLASS:
        raise QualificationInputError(f"결함 종류 구성 불일치: {dict(counts)}")
    return key, set(ids)


def _fmt_component(result: ComponentResult) -> list[str]:
    pct = round(CONFIDENCE * 100)
    lines = [f"[{result.name}]"]
    for cls, (d, n) in result.per_class.items():
        point = d / n if n else 0.0
        mark = "" if point >= MIN_CLASS_DETECTION_POINT else "  ← 기준 미달"
        lines.append(f"  {cls:28s} {d:>3d}/{n:<3d} ({point:.3f}){mark}")
    point = result.detected / result.n_defective if result.n_defective else 0.0
    lines.append(
        f"  전체 검출 {result.detected}/{result.n_defective} (점추정 {point:.3f} · "
        f"{pct}% 하한 {result.detection_lower:.4f} · 기준 ≥ {MIN_DETECTION_LOWER})"
    )
    lines.append(
        f"  오경보 {result.false_alarm}/{result.n_clean} ({pct}% 상한 "
        f"{result.false_alarm_upper:.4f} · 기준 ≤ {MAX_FALSE_ALARM_UPPER})"
    )
    lines.append(
        "  판정: " + ("합격" if result.passed else "불합격 — " + " / ".join(result.failures()))
    )
    return lines


def _fmt_machine_detail(
    result: ComponentResult, gate_hits: Mapping[str, Counter[str]]
) -> list[str]:
    lines = ["[기계 — 변이별 검출(◆ = GT 규칙과 같은 규칙의 게이트가 있는 변이: 구성상 검출)]"]
    for name, (d, n) in result.per_variant.items():
        lines.append(f"  {name:52s} {d:>2d}/{n:<2d}")
    d, n = result.non_circular
    if n:
        lower = wilson_lower_bound(d, n, CONFIDENCE)
        lines.append(f"  순환 변이를 뺀 기계 검출 {d}/{n} (점추정 {d / n:.3f} · 하한 {lower:.4f})")
    lines.append("[기계 — 게이트별 결함/정상 문항 적중]")
    for gate in (*VOTING_GATES, *DIAGNOSTIC_GATES):
        hits = gate_hits.get(gate, Counter())
        lines.append(f"  {gate:18s} 결함 {hits['defect']:>3d} · 정상 {hits['clean']:>3d}")
    return lines


def _cmd_score(args: argparse.Namespace) -> int:
    blind = _read_jsonl(Path(args.blind))
    key, ids = _validated_key(blind, Path(args.answer_key), Path(args.answer_key_sha256))
    machine_rows = _read_jsonl(Path(args.machine))
    machine = _label_map(machine_rows, ids, "기계 라벨")
    llm_paths = [Path(p) for p in args.llm or []]
    if not args.machine_only and len(llm_paths) < MIN_LLM_JUDGES:
        raise QualificationInputError(
            f"LLM 판정자 라벨 {len(llm_paths)}개 — 프로토콜은 {MIN_LLM_JUDGES}명 이상이 필요하다"
        )
    if len({p.resolve() for p in llm_paths}) != len(llm_paths):
        raise QualificationInputError("같은 판정자 라벨 파일이 두 번 들어왔다")
    judges = [_label_map(_read_jsonl(p), ids, str(p)) for p in llm_paths]

    is_defective = {str(r["item_id"]): bool(r["is_defective"]) for r in key}
    gate_hits: dict[str, Counter[str]] = {}
    for row in machine_rows:
        side = "defect" if is_defective[str(row["item_id"])] else "clean"
        for gate in row.get("fired") or []:
            gate_hits.setdefault(str(gate), Counter())[side] += 1
        for gate, state in (row.get("diagnostic") or {}).items():
            if state == "fail":
                gate_hits.setdefault(str(gate), Counter())[side] += 1

    machine_result = evaluate_component("기계 단독", key, machine)
    results = [machine_result]
    decisive = machine_result
    if judges:
        llm_union = {i: any(j[i] for j in judges) for i in ids}
        protocol = {i: machine[i] or llm_union[i] for i in ids}
        results.append(evaluate_component("LLM 단독(판정자 합집합)", key, llm_union))
        protocol_result = evaluate_component("프로토콜(기계 ∪ LLM)", key, protocol)
        results.append(protocol_result)
        for path, judge in zip(llm_paths, judges, strict=True):
            results.append(evaluate_component(f"판정자 {path.name}", key, judge))
        if not args.machine_only:
            decisive = protocol_result

    lines = ["=" * 72, "P3-03 미분 은행 감사자 자격 측정 — 결함 주입 강등전", "=" * 72]
    for result in results:
        lines += _fmt_component(result)
    lines += _fmt_machine_detail(machine_result, gate_hits)
    verdict = "합격" if decisive.passed else "불합격"
    scope = "기계 구성요소(프로토콜 판정 아님)" if args.machine_only else "감사 프로토콜"
    lines += ["=" * 72, f"최종 판정 — {scope}: {verdict}", "=" * 72]
    print("\n".join(lines))

    if args.json_out:
        payload = {
            "scope": "machine_only" if args.machine_only else "protocol",
            "passed": decisive.passed,
            "criteria": criteria(),
            "blind_sha256": _sha256(Path(args.blind).read_bytes()),
            "answer_key_sha256": _sha256(Path(args.answer_key).read_bytes()),
            "n_llm_judges": len(judges),
            "components": {r.name: r.as_json() for r in results},
            "protocol": decisive.as_json(),
        }
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return EXIT_PASS if decisive.passed else EXIT_FAIL


# ──────────────────────────────────────────────────────────────────────────
# s5 — 합격한 프로토콜로 은행 504건을 감사한 결과의 보정 상한
# ──────────────────────────────────────────────────────────────────────────
def corrected_upper_bound(k: int, n: int, detection_lower: float) -> float:
    """보정 결함률 상한 = Wilson 단측 97.5% 상한(k, n) ÷ 검출률 하한.

    근거(README §S5 보정): 감사가 결함 하나를 잡을 확률을 d라 하면 관측 결함 수 k의 기대는
    n·p·d 이상(오경보는 k를 키우므로 보수 쪽)이다. U = Wilson 상한(k, n)은 p·d의 97.5% 상한이고
    d ≥ 하한 L(역시 97.5% — `s5_detection_lower`)이므로 p ≤ U/L. 두 단측 97.5% 경계를 함께 쓰므로
    합성 신뢰도는 Bonferroni로 ≥ 95%다(초인간 검증 S5의 "95% 상한").
    """
    if not 0.0 < detection_lower <= 1.0:
        raise QualificationInputError(f"검출률 하한 {detection_lower}는 (0, 1] 밖이다")
    return wilson_upper_bound(k, n, S5_CONFIDENCE) / detection_lower


def s5_detection_lower(protocol: Mapping[str, Any]) -> float:
    """자격 결과의 프로토콜 검출 계수 → S5용 단측 97.5% 검출률 하한.

    점수 JSON의 `detection_lower`는 자격 판정용 95% 값이라 S5에 그대로 쓰면 사전 등록과 어긋난다.
    그래서 원 계수(`detected`·`n_defective`)에서 다시 계산한다. 계수가 시험지 설계와 다르거나, 같은
    JSON의 95% 하한이 계수에서 재현되지 않으면(손편집·위변조 의심) 입력 오류다.
    """
    try:
        detected = protocol["detected"]
        n_defective = protocol["n_defective"]
        stored_lower = float(protocol["detection_lower"])
    except (KeyError, TypeError, ValueError) as exc:
        raise QualificationInputError(
            f"자격 결과에 프로토콜 검출 계수가 없다({type(exc).__name__})"
        ) from exc
    if (
        type(detected) is not int
        or type(n_defective) is not int
        or n_defective != QUALIFICATION_N_DEFECTIVE
        or not 0 <= detected <= n_defective
    ):
        raise QualificationInputError(
            f"자격 결과의 검출 계수 {detected!r}/{n_defective!r}가 시험지 설계"
            f"(결함 {QUALIFICATION_N_DEFECTIVE})와 맞지 않는다"
        )
    recomputed = wilson_lower_bound(detected, n_defective, CONFIDENCE)
    if abs(recomputed - stored_lower) > _LOWER_RECOMPUTE_TOL:
        raise QualificationInputError(
            f"자격 결과의 95% 검출 하한 {stored_lower}이 계수 {detected}/{n_defective}에서 재현되지"
            f" 않는다(재계산 {recomputed})"
        )
    return wilson_lower_bound(detected, n_defective, S5_CONFIDENCE)


def _cmd_s5(args: argparse.Namespace) -> int:
    bank = _read_jsonl(Path(args.bank))
    ids = {str(r.get("problem_id") or "") for r in bank}
    if len(ids) != len(bank) or "" in ids or len(bank) != S5_BANK_SIZE:
        raise QualificationInputError(
            f"은행 문항 {len(bank)}건(고유 id {len(ids)}) — 기준 {S5_BANK_SIZE}건과 다르다"
        )
    try:
        qualification = json.loads(Path(args.qualification).read_text(encoding="utf-8"))
        protocol = qualification["protocol"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise QualificationInputError(
            f"자격 측정 결과를 읽지 못했다({type(exc).__name__})"
        ) from exc
    if not isinstance(protocol, Mapping):
        raise QualificationInputError("자격 측정 결과의 protocol이 객체가 아니다")
    if qualification.get("criteria") != criteria():
        raise QualificationInputError("자격 측정 결과의 기준 상수가 현재 코드와 다르다")
    if qualification.get("scope") != "protocol":
        raise QualificationInputError(
            "자격 측정 결과가 프로토콜 판정이 아니다(--machine-only 산출)"
        )
    if not qualification.get("passed"):
        print("s5: 감사 프로토콜이 자격 측정에 불합격했다 — 그 판정은 S5 근거가 아니다")
        return EXIT_FAIL
    detection_lower = s5_detection_lower(protocol)

    machine = _label_map(_read_jsonl(Path(args.machine)), ids, "은행 기계 라벨")
    llm_paths = [Path(p) for p in args.llm or []]
    if len(llm_paths) < MIN_LLM_JUDGES:
        raise QualificationInputError(
            f"은행 LLM 판정자 라벨 {len(llm_paths)}개 — {MIN_LLM_JUDGES}명 이상이 필요하다"
        )
    if len({p.resolve() for p in llm_paths}) != len(llm_paths):
        raise QualificationInputError("같은 판정자 라벨 파일이 두 번 들어왔다")
    judges = [_label_map(_read_jsonl(p), ids, str(p)) for p in llm_paths]
    flagged = {i: machine[i] or any(j[i] for j in judges) for i in ids}
    k = sum(flagged.values())
    n = len(ids)
    upper = wilson_upper_bound(k, n, S5_CONFIDENCE)
    corrected = corrected_upper_bound(k, n, detection_lower)
    passed = corrected <= S5_MAX_CORRECTED_UPPER
    print("=" * 72)
    print("P3-03 미분 은행 S5 — 자격 통과 프로토콜 감사의 보정 결함률 상한")
    print("=" * 72)
    print(f"  관측 결함(프로토콜 합집합) k = {k} / n = {n}")
    llm_k = sum(any(j[i] for j in judges) for i in ids)
    print(f"    기계 {sum(machine.values())} · LLM 합집합 {llm_k}")
    s5_pct = f"{S5_CONFIDENCE * 100:g}%"
    print(f"  Wilson {s5_pct} 단측 상한 U = {upper:.5f}")
    print(
        f"  자격 측정 검출률 {s5_pct} 단측 하한 L = {detection_lower:.5f}"
        f" ({protocol['detected']}/{protocol['n_defective']})"
    )
    print(
        f"  보정 상한 U / L = {corrected:.5f} (기준 ≤ {S5_MAX_CORRECTED_UPPER}) · 합성 신뢰도 ≥ 95%"
    )
    print(f"  판정: {'승인 근거 성립' if passed else '불합격'}")
    print("=" * 72)
    return EXIT_PASS if passed else EXIT_FAIL


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _parser() -> argparse.ArgumentParser:
    root = _repo_root()
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.p3_audit_qualification",
        description="P3-03 미분 은행 감사자 자격 측정(결함 주입 강등전) — emit·machine·score·s5.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    emit = sub.add_parser("emit", help="블라인드 시험지·정답지·지문·매니페스트 발행")
    emit.add_argument(
        "--bank",
        default=str(root / _AUDITED_BANK_PATH),
        help="시험지를 만든 은행(기본 = 동결 사본)",
    )
    emit.add_argument("--seed", type=int, default=QUALIFICATION_SEED)
    emit.add_argument("--blind", default=str(root / _QUAL_DIR / "blind_240.jsonl"))
    emit.add_argument("--answer-key", default=None, help="정답지 경로(감사 종료 전까지 저장소 밖)")
    emit.add_argument("--sha256", default=str(root / _QUAL_DIR / "answer_key.sha256"))
    emit.add_argument("--manifest", default=None)
    emit.add_argument("--check", action="store_true", help="재생성해 커밋된 시험지·지문과 대조")

    machine = sub.add_parser("machine", help="기계 게이트 전부 → 문항별 판정 라벨")
    machine.add_argument("--input", default=str(root / _QUAL_DIR / "blind_240.jsonl"))
    machine.add_argument("--out", default=str(root / _QUAL_DIR / "machine_labels.jsonl"))
    machine.add_argument("--id-field", default="item_id", help="시험지=item_id · 은행=problem_id")
    machine.add_argument("--check", action="store_true", help="재계산해 커밋된 라벨과 대조")

    score = sub.add_parser("score", help="기계·LLM·프로토콜 검출률 판정")
    score.add_argument("--blind", required=True)
    score.add_argument("--answer-key", required=True)
    score.add_argument("--answer-key-sha256", required=True, help="사전 등록 지문 파일")
    score.add_argument("--machine", required=True)
    score.add_argument("--llm", action="append", help="판정자별 라벨 파일(2개 이상)")
    score.add_argument("--machine-only", action="store_true", help="기계 구성요소만 판정")
    score.add_argument("--json-out", default=None, help="판정 결과 JSON(s5 입력)")

    sheets = sub.add_parser("bank-sheets", help="은행 504건 → 판정자 묶음·매니페스트")
    sheets.add_argument("--bank", default=str(root / _BANK_PATH))
    sheets.add_argument("--seed", type=int, default=BANK_AUDIT_SEED)
    sheets.add_argument("--shards", type=int, default=BANK_AUDIT_SHARDS)
    sheets.add_argument("--out-dir", default=None, help="묶음 파일 폴더(판정자 입력 — 저장소 밖)")
    sheets.add_argument("--manifest", default=str(root / _BANK_AUDIT_DIR / "manifest.json"))
    sheets.add_argument("--check", action="store_true", help="재생성해 커밋된 매니페스트와 대조")

    s5 = sub.add_parser("s5", help="은행 감사 라벨 → 보정 결함률 상한 판정")
    s5.add_argument("--bank", default=str(root / _BANK_PATH))
    s5.add_argument("--machine", required=True, help="은행 기계 라벨(item_id = problem_id)")
    s5.add_argument("--llm", action="append", help="은행 판정자별 라벨 파일(2개 이상)")
    s5.add_argument("--qualification", required=True, help="score --json-out 산출(프로토콜 합격)")
    return parser


_COMMANDS: Final = {
    "emit": _cmd_emit,
    "machine": _cmd_machine,
    "score": _cmd_score,
    "bank-sheets": _cmd_bank_sheets,
    "s5": _cmd_s5,
}


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점 — exit 0(합격)/1(불합격)/2(입력 오류)."""
    args = _parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except (QualificationInputError, FileNotFoundError) as exc:
        print(f"입력 오류({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
