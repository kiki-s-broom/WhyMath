"""EOS Core ↔ Math Adapter 경계 스캔 — 경계 배정 정본 + Core→Adapter 위반 실측 (EOS-65).

산출물 정본: `docs/architecture/eos_core_adapter_boundary.md`.
이 파일의 `BOUNDARY_MAP`이 **경계 배정의 단일 진실 원천**이다(선례: `eos_anchor_asset_audit.py`
의 `ANCHOR_DEFS`가 EOS-51 앵커 동결 정본). 문서는 이 표를 전사·해설하며, 배정을 바꾸려면
여기를 고친다.

⚠️ **정본화 ≠ 집행** — 이 스크립트는 *측정*만 한다. 배정을 기계가 강제하는 지점은
`EOS-67`(import-linter forbidden 계약 2건)이며, 이 파일만으로는 어떤 import도 차단되지 않는다.

**집행은 2026-08-31에 붙었다**(`EOS-67` done). 계약은 `src/backend/pyproject.toml`에 있고 CI
`backend` 잡의 `lint-imports` 스텝이 매 PR 판정하며, 그 배선 자체를
`tests/infra/test_eos_boundary_contract_wiring.py`가 동결한다. 따라서 아래 "위반 0"은 더 이상
"아무도 막고 있지 않다"가 아니다 — **다만 여전히 "전부 막혔다"도 아니다.** 이 스캔도 계약도
세는 것은 **AST 직접 import**이고, 계약은 `allow_indirect_imports=true`라 *경유* 의존을 보지
않는다(합성 루트를 통해 어댑터에 닿는 간선은 계약의 `ignore_imports`에 간선 단위로 적혀 있으며
재확인 지점은 G1 2026-09-27이다). 또한 MIXED 배정 모듈은 위반 계산에서 빠진다.

판정 규칙 (doc-100 §3.7 — "Core가 이차방정식을 알게 만들면 안 된다"):
  CORE    — Physics를 붙일 때 **고치지 않아도 되는** 모듈. 과목 의미론을 모른다.
  ADAPTER — 수학 의미론(기호 조작·수식 표기·수학 엔티티 타입)을 인코딩한 모듈.
  INFRA   — 횡단 관심사(설정·DB 세션·보안·관측성). 경계 계약의 대상이 아니다.
  MIXED   — 한 모듈 안에 CORE 기계와 ADAPTER 의미론이 함께 있어 파일 단위로 못 가르는 것.
            **날조 금지** — 애매하면 CORE/ADAPTER로 반올림하지 않고 MIXED로 적는다.

수학 신호(sympy import·수학 어휘 밀도)는 **배정의 근거 자료이지 배정 자체가 아니다**.
밀도 0인 모듈이 ADAPTER일 수 있고(수학 엔티티를 실어 나르는 순수 적재기), 밀도가 높아도
CORE일 수 있다(수학 코퍼스를 다루는 범용 하네스). 배정은 사람이 하고 근거만 기계가 잰다.

사용법:
    python3 scripts/analysis/eos_core_adapter_boundary_scan.py
    python3 scripts/analysis/eos_core_adapter_boundary_scan.py --json out.json --markdown out.md

종료코드: 0 = 스캔 성공(위반 유무와 무관) · 1 = 스캔 자체가 실패(측정 불가).
  위반 건수로 exit 1을 내지 않는 이유: 이 스크립트는 게이트가 아니라 계측기다.
  게이트는 EOS-67이 import-linter로 세운다.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["CORE", "ADAPTER", "INFRA", "MIXED"]

ROOT_PACKAGE = "whymath_backend"
DEFAULT_SOURCE = pathlib.Path("src/backend/whymath_backend")

# ──────────────────────────────────────────────────────────────────────
# 경계 배정 정본 — 키는 `whymath_backend` 기준 점 표기 모듈 경로(접두사).
# 더 긴(구체적인) 키가 이긴다. 각 항목의 사유는 문서 전사 대상이다.
# ──────────────────────────────────────────────────────────────────────
BOUNDARY_MAP: dict[str, tuple[Verdict, str]] = {
    # ── L1 데이터 기반 — 개념·교육과정·성취기준 골격은 과목 중립 ──
    "": ("INFRA", "패키지 루트 __init__ — 배정 대상 아님"),
    "l1": ("CORE", "지식 골격(개념·원자·교육과정·성취기준·권리)은 과목 교체 시 데이터만 바뀐다"),
    "l1.formula_graph": (
        "MIXED",
        "적재 기계는 범용(problem_type_graph와 동일 패턴)이나 실어 나르는 엔티티가 "
        "latex·SymPy-parseable canonical 식이라 Core가 수식을 알게 된다",
    ),
    "l1.strategy_graph": ("MIXED", "풀이 전략 그래프 — 전략 개념은 중립이나 수록 전략이 수학 전용"),
    # ── L2 학습자 모델 — 수학 신호 0(전 22모듈 실측) ──
    "l2": ("CORE", "BKT·IRT·숙련도·추천은 과목 무관 통계 모델. sympy·latex 참조 0건 실측"),
    # ── L3 콘텐츠 생성·검증 — 오케스트레이션(Core)과 수학 검증(Adapter)이 한 계층에 동거 ──
    "l3": ("CORE", "기본값: 생성·캐시·큐·관측 파이프라인은 과목 무관"),
    "l3.router": ("CORE", "AI Orchestration — 모델 라우팅은 과목 무관"),
    "l3.providers": ("CORE", "프로바이더 어댑터 — LLM 벤더 경계이지 과목 경계가 아님"),
    "l3.cache": ("CORE", "응답 캐시 구현"),
    "l3.queue": ("CORE", "비동기 작업 큐(QUALITY 티어 전용 경로)"),
    "l3.trace": ("CORE", "관측성 싱크(Langfuse)"),
    "l3.interfaces": ("CORE", "Protocol 정의 — 캐시·트레이스 계약"),
    "l3.pipeline": ("CORE", "생성 파이프라인 조립"),
    "l3.pregenerate": ("MIXED", "빌드타임 사전생성 기계는 범용이나 시드 검증이 SymPy 경유"),
    "l3.dsl": ("MIXED", "DSL 컴파일러 골격은 범용, variable_engine·validators는 수식 전제"),
    "l3.render": ("CORE", "교수법-중립 콘텐츠 → 전략별 화면. 전략 선택은 L4"),
    "l3.pedagogy": ("CORE", "발주서 → 콘텐츠 슬롯 생성·예심·검수 파이프라인"),
    "l3.cross_verify": ("CORE", "독립 다관점 LLM 교차검증 — 검출기 구조가 과목 무관"),
    "l3.visualization": ("CORE", "개념 → 선언적 시각화 *명세*(구조·JSON). 렌더는 클라"),
    "l3.viz_eval": ("CORE", "시각화 명세 생성 품질 채점·집계"),
    "l3.solution_path": ("CORE", "SolutionPath/Step/Justification 구조 — 단계형 풀이는 과목 무관"),
    "l3.solution_path_store": ("CORE", "위 구조의 영속"),
    "l3.verification_tier": (
        "MIXED",
        "검증 등급('증명된 축의 집합') 자체는 중립이나 축 정의가 수학 검증 계약",
    ),
    "l3.models": ("CORE", "L3 공용 데이터 모델"),
    "l3.prompt_assets": ("CORE", "프롬프트 자산 레지스트리"),
    "l3.escalation_defaults": ("CORE", "에스컬레이션 기본값 정책"),
    "l3.generation_seed": ("CORE", "생성 재현 seed 정책 — 경로별 지원·값 추출(과목 무관)"),
    "l3.equivalent": ("ADAPTER", "수식 동치 판정·정규화 — doc-100 Adapter 'equation equivalence'"),
    "l3.symbolic_equivalence": ("ADAPTER", "기호 조작 — doc-100 'symbolic manipulation'"),
    "l3.verifier": ("ADAPTER", "모듈 스스로 '통합 *수학* 검증기 v2'로 자인"),
    "l3.verify_answer_form": (
        "ADAPTER",
        "답 표기 형태 판정 — 기약분수·인수분해형 같은 **형태 어휘가 수학 소유**이고 SymPy로 "
        "표면을 파싱한다. 신설 시 l3 기본값(CORE)을 물려받아 sympy를 import하는 CORE 모듈이 "
        "됐던 것을 정정한다 — EOS-69가 청소한 유형을 같은 세션에서 재생산했다 (EOS-28)",
    ),
    "l3.verify_answer": ("ADAPTER", "수학 정답 판정 — doc-100 'math problem validators'"),
    "l3.verify_step": ("ADAPTER", "인접 단계 수식 동치 연쇄 검사"),
    "l3.verify_final_answer": ("ADAPTER", "최종 답 수식 판정"),
    "l3.verify_solution": ("ADAPTER", "풀이 전체 수식 판정"),
    "l3.solution_set": ("ADAPTER", "해집합 표현·비교"),
    "l3.multi_solution": ("ADAPTER", "다중 풀이법 생성 — 수학 접근법 분류(ApproachType)"),
    "l3.finite_probability": ("ADAPTER", "유한 확률 전수 검증"),
    "l3.statistical_claim": ("ADAPTER", "통계 자료형 결정론 검증기"),
    "l3.notation_coverage": ("ADAPTER", "수학 표기 커버리지 게이트"),
    "l3.speech": ("ADAPTER", "수식 AST → 한국어 낭독 — doc-100 'mathematical expression parsing'"),
    "l3.speech_parse": ("ADAPTER", "낭독 역파싱"),
    # ── 과목 중립 언어 유틸 (EOS-69) ──
    "lang": (
        "CORE",
        "한국어 조사·표기 유틸 — 어떤 과목이든 한국어로 가르치면 필요하다. "
        "표준 라이브러리만 import(모듈 자인). 경계 문서 §4 B분류 3건의 해소처",
    ),
    # ── L4 교수학 엔진 — Polya·소크라테스·오개념 *기계*는 중립, 수학 검출기만 Adapter ──
    "l4": ("CORE", "Polya 4단계·소크라테스·LTHC·힌트 지연은 교수학 구조이지 수학이 아님"),
    "l4.misconception": (
        "CORE",
        "오개념 카탈로그·crosslink·판정 큐·probe 36모듈 중 sympy 접촉 2건뿐 — 기계는 중립",
    ),
    "l4.misconception.wrong_form_match": (
        "ADAPTER",
        "수학 오답 형태 SymPy 매칭 — doc-100 'math misconception detectors'",
    ),
    "l4.misconception.wrong_form_shadow_harvest": ("ADAPTER", "위 검출기의 shadow 수확"),
    "l4.misconception.answer_signature": (
        "ADAPTER",
        "오답 서명(문항 식 = 제출 답) SymPy 거짓형 정합 — attempt 단위 검출기(EOS-104). "
        "wrong_form_match와 같은 사유로 ADAPTER: '식을 이어 거짓 항등식을 읽는다'는 독법이 "
        "수학 고유다. Core는 schema.verification_capabilities의 선택층 Protocol만 안다",
    ),
    "l4.subject_adapter_math": (
        "ADAPTER",
        "MathSubjectAdapter(EOS-66) — SubjectAdapter 계약의 수학 구현. CORE인 l4에 살지만 "
        "배정은 파일 단위(선례: wrong_form_match). CORE가 이것을 import하면 위반이 맞다 — "
        "Core는 schema.subject_adapter Protocol만 알아야 하고 구현체는 DI로만 주입된다",
    ),
    "l4.solution_coaching": (
        "CORE",
        "[EOS-86 재배정] verify_solution/wrong_form_match 직접 import 제거 — 단계 연쇄 검증은 "
        "StepChainVerifier(선택층 계약) 주입 경유로 교체(합성 루트 default_step_chain_verifier)."
        " 코칭 오케스트레이션은 원래도 중립이었고, 남은 수식 전제는 없다",
    ),
    "l4.speech": ("MIXED", "낭독 교수 정책 — 정책은 중립, 대상이 수식"),
    # ── L5 상호작용 — OCR은 수식 인식 그 자체 ──
    "l5": ("CORE", "상호작용 계층 골격"),
    "l5.ocr": ("ADAPTER", "손글씨 수식 인식 — doc-100 'mathematical expression parsing'"),
    # ── L6 응용 모드 — 수학 신호 0(전 9모듈 실측) ──
    "l6": ("CORE", "모드 오케스트레이션(학교진도·수능·사고력·메타인지·영재). sympy·latex 0건"),
    # ── API·스키마·DB·횡단 ──
    "api": ("CORE", "HTTP 표면 — 과목 중립 라우팅"),
    "api.verify": ("MIXED", "검증 엔드포인트 — 표면은 중립이나 요청·응답이 수식 계약"),
    "api.speech": ("MIXED", "낭독 엔드포인트 — 동상"),
    "api.ocr": ("MIXED", "OCR 엔드포인트 — 동상"),
    "api._ocr_state": (
        "INFRA",
        "OCR 부품의 app.state 보관·조회 배관(`_l3_state`와 동형) — `OcrComponents`가 **타입 "
        "주석으로만** 등장하고 필드를 한 번도 읽지 않는다(실측: 저장·조회·503 사유·도달 카운터). "
        "과목이 바뀌어도 고칠 것이 없어 CORE 기준을 만족하나, 배관은 경계 계약의 대상이 아니라 "
        "INFRA로 적는다. **이것은 배선 수정이 아니라 분류 정정이다** — 위반이 사라진 이유가 "
        "코드 변경이 아님을 여기 남겨 둔다 (EOS-69)",
    ),
    "schema": ("CORE", "순수 타입 — 대부분 과목 중립(학습자·활동·권리·이벤트)"),
    "schema.subject_adapter": (
        "CORE",
        "SubjectAdapter 계약(EOS-66) — 과목 중립 Protocol·순수 타입",
    ),
    "schema.problem": (
        "MIXED",
        "S1-16 착지(2026-08-31) 후에도 MIXED다 — 수학 전용 4필드가 `extensions.math`로 "
        "*구조화*됐으나 legacy top-level 필드가 하위호환을 위해 남아 양방향 동기화된다. "
        "CORE 승격은 legacy 축 제거(breaking)가 선결이며 S1-16이 의도적으로 하지 않았다",
    ),
    "schema.enums": ("MIXED", "과목 중립 enum과 수학 전용 enum이 한 파일에 동거"),
    "schema.answer_submission": ("MIXED", "답안 제출 계약 — 봉투는 중립, 답 표현이 수식"),
    "schema.student_solution_step": ("MIXED", "학생 풀이 단계 — 구조는 중립, 단계 내용이 수식"),
    "schema.ocr": ("MIXED", "OCR 계약 — 인식 대상이 수식"),
    "schema.speech": ("MIXED", "낭독 계약 — 낭독 대상이 수식"),
    "db": ("INFRA", "영속 계층 — 모델 컬럼에 수학 타입이 있으나 경계 계약 대상이 아님"),
    "ops": ("INFRA", "운영·계측·감사"),
    "privacy": ("INFRA", "미성년 PII 횡단 인프라"),
    "composition": (
        "INFRA",
        "합성 루트 — 능력 계약(schema)과 과목 구현(l4 어댑터)을 잇는 유일한 배선 지점. "
        "판정 로직 0·팩토리만 노출. 과목 추가 시 *고쳐야 하는* 파일이라 CORE가 아니며, "
        "경계의 목적은 변경 지점 제거가 아니라 한 곳으로의 집중이다 (EOS-69)",
    ),
    "config": ("INFRA", "설정"),
    "security": ("INFRA", "인증·인가"),
    "consent": ("INFRA", "동의 절차"),
    "consent_grant": ("INFRA", "동의 부여"),
    "app": ("INFRA", "ASGI 조립"),
    "harness": (
        "INFRA",
        "측정·배치 하네스 — 상위 계층 호출이 정상이라 계층 계약 밖(pyproject 주석과 동일 처리)",
    ),
    "whs": ("INFRA", "WH-S 솔버 하네스 — 동상"),
}

# 계획서 200 §5가 "Core 내부에 등장하면 경고" 예시로 든 7어휘 중 `desmos`·`equation_solver`가
# 빠져 있었다(실측 2026-09-16). 추가하면서 **기준선이 얼마나 올라가는지 먼저 쟀다** — CORE
# 적중 +3(`schema.visualization` 2·`l3.visualization` 1), MIXED +1(`schema.enums`). 네 건 전부
# **docstring 산문**이며 "렌더는 D3/Plotly/Desmos가 한다"고 *설명하는* 문장이다(=렌더러를
# 플러그인으로 미는 설계를 기술한 것이지 Core가 수학을 아는 코드가 아니다).
#
# 그래도 세는 이유: 이 정규식은 **배정의 근거 자료**이고, ratchet 게이트는 *증가*를 잡는다.
# Core 모듈이 새로 특정 렌더러 이름을 말하기 시작하는 것은 사람이 한 번 볼 가치가 있는
# 신호다(플레이북 8대 원칙 ④ "Renderer는 Plugin — 구현체 이름을 노드에 넣지 않는다").
# 산문이라 무해한 건은 기준선에 그대로 실려 유예되며, 무엇이 산문인지는
# `tests/infra/test_core_math_vocabulary_ratchet.py`의 기준선 주석이 건별로 적는다.
MATH_TOKEN_RE = re.compile(
    r"\b(sympy|latex|polynomial|quadratic|factoriz\w*|derivative|integral|"
    r"inequality|geometry|theorem|proof|desmos|equation_solver)\b",
    re.IGNORECASE,
)
SYMPY_IMPORT_RE = re.compile(r"(?m)^\s*(?:from\s+sympy|import\s+sympy)")


@dataclass
class ModuleFact:
    module: str
    path: str
    verdict: Verdict
    rationale: str
    matched_key: str
    loc: int
    sympy_imports: int
    math_tokens: int
    internal_imports: list[str] = field(default_factory=list)
    parse_error: str | None = None


def classify(module: str) -> tuple[Verdict, str, str]:
    """가장 구체적인(가장 긴) 접두사 키가 이긴다."""
    best_key: str | None = None
    for key in BOUNDARY_MAP:
        if module == key or (key and module.startswith(key + ".")):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    if best_key is None:
        # 미등재는 조용히 CORE로 반올림하지 않는다 — 배정 누락이 눈에 띄어야 한다
        return ("MIXED", "BOUNDARY_MAP 미등재 — 배정 필요", "")
    verdict, rationale = BOUNDARY_MAP[best_key]
    return (verdict, rationale, best_key)


def module_name(path: pathlib.Path, source_root: pathlib.Path) -> str:
    rel = path.relative_to(source_root).with_suffix("")
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join(parts) if parts else ""


def internal_imports(tree: ast.AST) -> list[str]:
    """`whymath_backend.*` 내부 import만 추린다(외부 의존은 경계 계약 대상이 아니다)."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(ROOT_PACKAGE + "."):
                    found.append(alias.name[len(ROOT_PACKAGE) + 1 :])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 상대 import — 이 저장소는 절대 import 관례라 관측 시 기록만
                continue
            if node.module and node.module.startswith(ROOT_PACKAGE + "."):
                base = node.module[len(ROOT_PACKAGE) + 1 :]
                for alias in node.names:
                    found.append(f"{base}.{alias.name}")
                if not node.names:
                    found.append(base)
    return found


def scan(source_root: pathlib.Path, log) -> tuple[list[ModuleFact], list[str]]:
    """단계별 즉시 기록 — 중간에 죽어도 그때까지의 사실은 log에 남는다."""
    facts: list[ModuleFact] = []
    errors: list[str] = []
    files = sorted(source_root.rglob("*.py"))
    log(f"[scan] 대상 {len(files)}파일 · 루트 {source_root}")
    for path in files:
        mod = module_name(path, source_root)
        verdict, rationale, key = classify(mod)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # 침묵 실패 금지 — 예외 타입명을 남긴다
            msg = f"{path}: READ {type(exc).__name__}: {exc}"
            errors.append(msg)
            log(f"[scan][error] {msg}")
            continue
        fact = ModuleFact(
            module=mod,
            path=path.as_posix(),
            verdict=verdict,
            rationale=rationale,
            matched_key=key,
            loc=text.count("\n"),
            sympy_imports=len(SYMPY_IMPORT_RE.findall(text)),
            math_tokens=len(MATH_TOKEN_RE.findall(text)),
        )
        try:
            fact.internal_imports = internal_imports(ast.parse(text, filename=str(path)))
        except SyntaxError as exc:
            fact.parse_error = f"{type(exc).__name__}: {exc}"
            errors.append(f"{path}: PARSE {fact.parse_error}")
            log(f"[scan][error] {path}: PARSE {fact.parse_error}")
        facts.append(fact)
    log(f"[scan] 완료 — 사실 {len(facts)}건 · 오류 {len(errors)}건")
    return facts, errors


def violations(facts: list[ModuleFact]) -> list[dict[str, str]]:
    """CORE로 배정된 모듈이 ADAPTER로 배정된 모듈을 import하는 간선."""
    out: list[dict[str, str]] = []
    for fact in facts:
        if fact.verdict != "CORE":
            continue
        for target in fact.internal_imports:
            tv, _, tkey = classify(target)
            if tv == "ADAPTER":
                out.append(
                    {"from": fact.module, "from_path": fact.path, "to": target, "to_key": tkey}
                )
    return out


def summarize(facts: list[ModuleFact]) -> dict[str, dict[str, int]]:
    agg: dict[str, dict[str, int]] = defaultdict(
        lambda: {"modules": 0, "loc": 0, "sympy_imports": 0, "math_tokens": 0}
    )
    for fact in facts:
        row = agg[fact.verdict]
        row["modules"] += 1
        row["loc"] += fact.loc
        row["sympy_imports"] += fact.sympy_imports
        row["math_tokens"] += fact.math_tokens
    return dict(agg)


def render_markdown(facts, viols, summary, errors) -> str:
    lines = ["# EOS Core↔Adapter 경계 스캔 결과 (기계 생성)", ""]
    lines.append("## 배정 분포")
    lines.append("")
    lines.append("| 배정 | 모듈 | LOC | sympy import | 수학어휘 | 어휘/kloc |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for verdict in ("CORE", "ADAPTER", "MIXED", "INFRA"):
        row = summary.get(verdict)
        if not row:
            continue
        dens = row["math_tokens"] / row["loc"] * 1000 if row["loc"] else 0.0
        lines.append(
            f"| {verdict} | {row['modules']} | {row['loc']:,} | {row['sympy_imports']} "
            f"| {row['math_tokens']} | {dens:.1f} |"
        )
    lines += ["", f"## CORE → ADAPTER import 위반: **{len(viols)}건**", ""]
    if viols:
        lines.append("| from (CORE) | to (ADAPTER) |")
        lines.append("|---|---|")
        for v in viols:
            lines.append(f"| `{v['from']}` | `{v['to']}` |")
    else:
        lines.append(
            "없음. ⚠️ 단 이 0의 범위를 좁게 읽을 것 — **AST 직접 import 기준**이며 "
            "`allow_indirect_imports=true`인 계약과 마찬가지로 *경유* 의존(합성 루트 등)은 "
            "세지 않는다. 집행은 `EOS-67`(import-linter 계약 2건 · CI `backend` 잡 "
            "`lint-imports`)이 2026-08-31부터 맡고 있고, 경유 잔여 간선은 그 계약의 "
            "`ignore_imports`에 간선 단위로 적혀 있다(재확인 지점 = G1 2026-09-27)."
        )
    lines += ["", f"## 스캔 오류: {len(errors)}건", ""]
    lines += [f"- `{e}`" for e in errors] or ["- 없음"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE)
    parser.add_argument("--json", type=pathlib.Path, default=None)
    parser.add_argument("--markdown", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)  # 단계별 즉시 flush

    if not args.source.is_dir():
        log(f"[fatal] 소스 루트 없음: {args.source} (cwd={pathlib.Path.cwd()})")
        return 1

    try:
        facts, errors = scan(args.source, log)
    except Exception as exc:  # noqa: BLE001 — 최상위 계측기: 원인 타입을 남기고 실패한다
        log(f"[fatal] 스캔 실패 {type(exc).__name__}: {exc}")
        return 1

    if not facts:
        log("[fatal] 사실 0건 — 측정 실패이지 '위반 없음'이 아니다")
        return 1

    viols = violations(facts)
    summary = summarize(facts)
    markdown = render_markdown(facts, viols, summary, errors)
    print(markdown)

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "summary": summary,
                    "violations": viols,
                    "errors": errors,
                    "modules": [vars(f) for f in facts],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"[out] json → {args.json}")
    if args.markdown:
        args.markdown.write_text(markdown, encoding="utf-8")
        log(f"[out] markdown → {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
