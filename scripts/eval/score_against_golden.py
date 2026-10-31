"""골든셋 대비 채점기 — AI 생성 콘텐츠 루브릭 v1의 **기계 판정 축**(stdlib 전용).

루브릭 정본: docs/standards/ai_content_rubric_v1.md. 6축 × 0~3점 중 기계가 정할 수 있는 부분만
판정하고, 정할 수 없는 부분은 **상한(ceiling)**만 두고 `judge_required`로 넘긴다 — 미판정을 3점으로
적지 않는다("작동한 비율" 원칙). 하드 게이트(정답 누설 F8·인지부하·수학 0점·저작권 0점)는 점수와
무관하게 FAIL이다.

사용:
  python3 scripts/eval/score_against_golden.py --self-check            # 골든을 후보로 넣어 자가검증
  python3 scripts/eval/score_against_golden.py --candidates out.jsonl  # Sonnet 5 산출물 채점
      [--golden data/corpus/golden_set_rubric_v1/golden.json]
      [--out report.json] [--judge-out judge.jsonl]

후보 JSONL 1행 = 골든 1노드와 같은 형태:
{"golden_id","standard_code","concept_explanation":{"text"},
"socratic_flow":[...],"mc_item":{...},"copyright":{"origin"}}.
종료 코드: 0 전건 PASS 또는 판정 보류만 · 1 FAIL 1건 이상(또는 자가검증 불일치) · 2 입력 오류.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
import sys
import unicodedata
from fractions import Fraction
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN = REPO / "data/corpus/golden_set_rubric_v1/golden.json"
STANDARDS = REPO / "data/corpus/standards_v1/standards.json"
MISCONCEPTIONS = REPO / "data/corpus/misconceptions_v1/misconceptions.json"

AXES = ("math", "standard", "misconception", "op_trace", "vocab", "copyright")

# OP 코드 ↔ 오개념 DB error_type 호환 집합(루브릭 §2 표). None(미분류)은 모든 OP와 호환.
OP_FAMILY: dict[str, set[str]] = {
    "OP_01": {"부호오류"},
    "OP_02": {"분배누락"},
    "OP_03": {"공식혼동"},
    "OP_04": {"조건무시"},
    "OP_05": {"순서오류"},
    "OP_06": {"차원혼동", "극값변곡혼동", "극대극소혼동", "값좌표혼동", "공식혼동"},
    "OP_07": {"해석오류"},
    "OP_08": {"해석오류", "공식혼동"},  # DB enum에 '과잉일반화'가 없어 현재 산재 분류를 허용
}
OP_CODES = {"OP_00", *OP_FAMILY}
PROPOSAL_FIELDS = (
    "proposal_id",
    "standard_code",
    "error_type",
    "canonical_statement",
    "student_wrong_thinking",
)

# 저작권 — 금칙 출처 패턴(policy-guard CI의 검정교과서 5종 + EBS·평가원·쪽수 표기 확장)
COPYRIGHT_PATTERNS = re.compile(
    r"천재교육|비상교육|미래엔|동아출판|신사고|좋은책|지학사|금성출판|EBS|평가원|수능\s*기출|모의평가|"
    r"교과서\s*\d+\s*쪽|\d+\s*쪽\s*(예제|문제|연습)"
)
# 소크라테스 발화 금지 표현(socratic_template.md 원칙 4)
NEGATIVE_PATTERNS = re.compile(r"틀렸어|틀렸네|못\s*하네|모르네|실수했어|아니야|바보")
# 학년군별 평균 문장 길이 상한(글자 수) — 루브릭 §6
SENTENCE_LIMIT = {
    "초등학교 1~2학년군": 30,
    "초등학교 3~4학년군": 40,
    "초등학교 5~6학년군": 40,
    "중학교 1~3학년군": 55,
    "고등학교": 70,
}


# ───────────────────────────── 공용 유틸 ─────────────────────────────
def sentences(text: str) -> list[str]:
    """문장 분리 — 마침표·물음표·느낌표 기준(한국어 종결어미 뒤 공백 전제)."""
    parts = re.split(r"(?<=[.?!？])\s+", text.strip())
    return [p for p in parts if p]


def normalize(text: str) -> str:
    """pedagogical_rubric._normalize 미러 — NFKC·소문자·LaTeX 명령·구조 문자 제거."""
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"\\[a-zA-Z]+", "", t)
    return re.sub(r"[$\\{}()\s,]", "", t)


def leaks_answer(response: str, answer: str) -> str:
    """정답 누설 3-state(leaked/clean/undecidable) — harness/pedagogical_rubric 규약 미러."""
    a = normalize(answer)
    if len(a) < 2 or a in {"true", "false", "참", "거짓", "없음", "정답", "해", "근"}:
        return "undecidable"
    r = normalize(response)
    if re.fullmatch(r"-?\d+(?:\.\d+)?", a):
        hit = re.search(rf"(?<![\d.]){re.escape(a)}(?![\d.])", r) is not None
    else:
        hit = a in r
    return "leaked" if hit else "clean"


def char_ngrams(text: str, n: int = 8) -> set[str]:
    t = re.sub(r"\s+", "", text)
    return {t[i : i + n] for i in range(max(0, len(t) - n + 1))}


def containment(cand: str, ref: str) -> float:
    """후보 8-gram 중 참조에 들어 있는 비율(0~1) — 골든 복제 탐지용."""
    c = char_ngrams(cand)
    if not c:
        return 0.0
    return len(c & char_ngrams(ref)) / len(c)


_SAFE_NAMES = {
    "F": Fraction,
    "lcm": math.lcm,
    "gcd": math.gcd,
    "isqrt": math.isqrt,
    "divmod": divmod,
    "sorted": sorted,
    "len": len,
    "abs": abs,
    "True": True,
    "False": False,
}
_SAFE_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Compare,
    ast.BoolOp,
    ast.ListComp,
    ast.comprehension,
    ast.Subscript,
    ast.Slice,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.Gt,
    ast.LtE,
    ast.GtE,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Store,
)


def safe_eval(expr: str):
    """산술 전용 안전 평가 — 허용 노드·이름 밖이면 거부(임의 코드 실행 차단)."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_NODES):
            raise ValueError(f"허용되지 않은 식 요소: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in _SAFE_NAMES and node.id != "x":
            raise ValueError(f"허용되지 않은 이름: {node.id}")
        if isinstance(node, ast.Call) and not (
            isinstance(node.func, ast.Name) and node.func.id in _SAFE_NAMES
        ):
            raise ValueError("허용되지 않은 호출")
    return eval(compile(tree, "<verify>", "eval"), {"__builtins__": {}}, dict(_SAFE_NAMES))


# ───────────────────────────── 축별 판정 ─────────────────────────────
def axis(score: int | None, ceiling: int, evidence: list[str], judge: bool) -> dict:
    return {"score": score, "ceiling": ceiling, "judge_required": judge, "evidence": evidence}


def score_math(cand: dict) -> dict:
    """① 수학 — `verify` 검산(기계 하한)·비약(F3)은 심판."""
    ev: list[str] = []
    mc = cand.get("mc_item") or {}
    v = mc.get("verify") or {}
    if not v.get("expr"):
        return axis(None, 3, ["verify 식 없음 — 정답 검산 불가(심판 전담)"], True)
    try:
        got = safe_eval(v["expr"])
        exp = safe_eval(v["expected"])
    except Exception as e:  # noqa: BLE001 — 사유를 남기고 0점(F1 파싱 실패)
        return axis(0, 0, [f"verify 평가 실패({type(e).__name__}): {e}"], False)
    if got != exp:
        return axis(0, 0, [f"정답 불일치(F2): {v['expr']} = {got!r} ≠ 기대 {exp!r}"], False)
    ev.append(f"정답 검산 통과: {v['expr']} = {exp!r}")
    return axis(None, 3, ev + ["풀이 비약(F3)·정의 정확성은 심판"], True)


def score_standard(cand: dict, gold: dict, std2022: dict[str, dict]) -> dict:
    """② 성취기준 — 코드 실재(2022 개정)·골든 일치는 기계, 내용 범위는 심판."""
    code = cand.get("standard_code")
    if not code:
        return axis(0, 0, ["성취기준 코드 없음"], False)
    if code not in std2022:
        return axis(0, 0, [f"{code}: 2022 개정 행에 없음(2015 전용이거나 오기)"], False)
    if code != gold["standard_code"]:
        same_unit = (
            std2022[code]["sub_domain"] == gold["sub_domain"]
            or std2022[code]["domain"] == gold["domain"]
        )
        return axis(
            1,
            1,
            [
                f"{code}는 2022 개정에 실재하나 골든 {gold['standard_code']}과 다름"
                + ("(같은 영역 인접 코드)" if same_unit else "")
            ],
            False,
        )
    return axis(
        None, 3, [f"{code} = 골든 일치 · 2022 개정 실재", "후속 학년 내용 혼입 여부는 심판"], True
    )


def score_misconception(cand: dict, gold: dict, mis_by_id: dict[str, dict]) -> dict:
    """③ 오개념 연결 — OP_01~08 선지마다 실재 M-id(같은/선수 성취기준) 또는 완전한 제안 블록."""
    mc = cand.get("mc_item") or {}
    rows = [r for r in mc.get("distractor_map", []) if r.get("op_code") != "OP_00"]
    if not rows:
        return axis(0, 0, ["OP_01~08 선지가 없음"], False)
    ok = weak = 0
    ev: list[str] = []
    allowed_codes = {gold["standard_code"]} | set(gold.get("prerequisite_codes", []))
    for r in rows:
        mid = r.get("misconception_id")
        prop = r.get("misconception_proposal")
        if mid:
            m = mis_by_id.get(mid)
            if m is None:
                ev.append(f"선지{r.get('choice_index')}: {mid} DB에 없음(날조)")
                continue
            if m.get("standard_code") in allowed_codes or mid in gold.get(
                "misconception_ids_addressed", []
            ):
                ok += 1
            else:
                # 다른 성취기준의 M-id — 같은 학교급 선수 개념이면 약한 연결로 인정
                weak += 1
                ev.append(
                    f"선지{r.get('choice_index')}: {mid}는 {m.get('standard_code')} 소속"
                    f"(골든 {gold['standard_code']}과 다름)"
                )
            et = m.get("error_type")
            if et and et not in OP_FAMILY.get(r["op_code"], set()):
                ev.append(
                    f"경고 선지{r.get('choice_index')}: {r['op_code']}↔{mid} "
                    f"error_type '{et}' 비호환"
                )
        elif prop:
            missing = [f for f in PROPOSAL_FIELDS if not prop.get(f)]
            if missing:
                weak += 1
                ev.append(f"선지{r.get('choice_index')}: 제안 블록 필드 누락 {missing}")
            else:
                ok += 1
        else:
            ev.append(f"선지{r.get('choice_index')}: M-id도 제안도 없음")
    n = len(rows)
    n_prop = sum(1 for r in rows if r.get("misconception_proposal"))
    if n_prop:
        ev.append(f"신설 오개념 제안 {n_prop}건 → 검수 큐 등재 대상")
    if ok == n:
        s = 3
    elif ok + weak >= math.ceil(n / 2):
        s = 2
    elif ok + weak >= 1:
        s = 1
    else:
        s = 0
    # 설명·흐름이 골든의 DB 오개념을 다루는지는 문장 수준 판단 — 상한만 두고 심판
    return axis(s, s, ev + [f"연결 {ok}/{n}(약한 연결 {weak})"], s == 3)


def score_op_trace(cand: dict) -> dict:
    """④ OP 추적 — 오답마다 OP 라벨+유도문, OP_00 ≤1, 정답에는 라벨 없음."""
    mc = cand.get("mc_item") or {}
    choices = mc.get("choices") or []
    ans = mc.get("answer_index")
    rows = mc.get("distractor_map") or []
    ev: list[str] = []
    if not choices or ans is None or not (0 <= ans < len(choices)):
        return axis(0, 0, ["선지·정답 인덱스 불량"], False)
    if len(set(choices)) != len(choices):
        return axis(0, 0, ["선지 중복"], False)
    n_dis = len(choices) - 1
    traceable = 0
    op00 = 0
    seen = set()
    for r in rows:
        i = r.get("choice_index")
        if i == ans:
            ev.append("정답 선지에 OP 라벨이 붙음")
            continue
        if i in seen or not (0 <= (i if isinstance(i, int) else -1) < len(choices)):
            ev.append(f"choice_index 불량/중복: {i}")
            continue
        seen.add(i)
        op = r.get("op_code")
        if op not in OP_CODES:
            ev.append(f"선지{i}: 알 수 없는 op_code {op!r}")
            continue
        if op == "OP_00":
            op00 += 1
            continue
        if not str(r.get("derivation", "")).strip():
            ev.append(f"선지{i}: {op} 유도문 없음")
            continue
        traceable += 1
    unlabeled = n_dis - len(seen)
    if unlabeled:
        ev.append(f"라벨 없는 오답 {unlabeled}개")
    if traceable >= n_dis - 1 and op00 <= 1 and unlabeled == 0:
        s = 3
    elif traceable >= math.ceil(n_dis / 2):
        s = 2
    elif traceable >= 1:
        s = 1
    else:
        s = 0
    if op00 > 1:
        ev.append(f"OP_00 {op00}개(최대 1개)")
    ev.append(f"추적 가능 {traceable}/{n_dis} · OP_00 {op00}")
    return axis(s, s, ev, False)


def texts_of(cand: dict) -> list[str]:
    out = [(cand.get("concept_explanation") or {}).get("text") or ""]
    out += [t.get("tutor", "") for t in cand.get("socratic_flow", [])]
    mc = cand.get("mc_item") or {}
    out += [mc.get("stem", "")] + list(mc.get("choices", []))
    return [t for t in out if t]


def score_vocab(cand: dict, gold: dict) -> dict:
    """⑤ 어휘 — 골든 금칙어 적중 수·평균 문장 길이(기계 상한), 문체는 심판."""
    forbid = gold.get("vocabulary", {}).get("forbid", [])
    joined = "\n".join(texts_of(cand))
    hits = sorted({w for w in forbid if w and w in joined})
    ev: list[str] = []
    s = 3 if not hits else 2 if len(hits) == 1 else 1 if len(hits) == 2 else 0
    if hits:
        ev.append(f"금칙 어휘 적중: {hits}")
    expl = (cand.get("concept_explanation") or {}).get("text") or ""
    ss = sentences(expl)
    if ss:
        avg = sum(len(x) for x in ss) / len(ss)
        limit = SENTENCE_LIMIT.get(gold.get("grade_band"), 70)
        ev.append(f"설명 평균 문장 길이 {avg:.0f}자(상한 {limit})")
        if avg > limit:
            s = min(s, 2)
    return axis(None if s == 3 else s, s, ev, s == 3)


def score_copyright(cand: dict, gold: dict) -> dict:
    """⑥ 저작권 — 금칙 출처 패턴(0점)·골든 복제(2점 상한)·origin 표기. 외부 모사는 심판."""
    joined = "\n".join(texts_of(cand))
    m = COPYRIGHT_PATTERNS.search(joined)
    if m:
        return axis(
            0, 0, [f"금칙 출처 표기 '{m.group(0)}' — 교과서·EBS·평가원 본문/쪽수 인용 의심"], False
        )
    ev: list[str] = []
    ceiling = 3
    origin = (cand.get("copyright") or {}).get("origin")
    if origin != "original_ai":
        ceiling = 2
        ev.append(f"copyright.origin={origin!r} (original_ai 아님)")
    if not cand.get("_is_golden"):
        g_expl = gold["concept_explanation"]["text"]
        c_expl = (cand.get("concept_explanation") or {}).get("text") or ""
        rate = containment(c_expl, g_expl)
        ev.append(f"골든 설명 대비 8-gram 포함률 {rate:.2f}")
        if rate >= 0.7:
            ceiling = min(ceiling, 2)
            ev.append("골든 복제 의심(과적합) — 상한 2")
    ev.append("외부 저작물 모사(G5 유사도 게이트 미착지)는 심판")
    return axis(None, ceiling, ev, True)


def hard_gates(cand: dict) -> dict[str, dict]:
    """하드 게이트 — F8 정답 누설 · 인지부하(질문 1개·3문장) · 금지 표현 · 힌트 단계 비감소."""
    mc = cand.get("mc_item") or {}
    answer = ""
    if mc.get("choices") and isinstance(mc.get("answer_index"), int):
        answer = mc["choices"][mc["answer_index"]]
    flow = cand.get("socratic_flow") or []
    g: dict[str, dict] = {}
    leaks, undec = [], 0
    for t in flow:
        v = leaks_answer(t.get("tutor", ""), answer) if answer else "undecidable"
        if v == "leaked":
            leaks.append(t.get("turn"))
        elif v == "undecidable":
            undec += 1
    g["F8_answer_leak"] = {
        "passed": not leaks,
        "evidence": [f"누설 턴 {leaks}"] if leaks else [f"누설 없음(판정 불가 {undec}턴)"],
    }
    bad_q, bad_len, neg, order = [], [], [], []
    prev = 0
    for t in flow:
        txt = t.get("tutor", "")
        nq = txt.count("?") + txt.count("？")
        if nq != 1:
            bad_q.append((t.get("turn"), nq))
        if len(sentences(txt)) > 3:
            bad_len.append(t.get("turn"))
        if NEGATIVE_PATTERNS.search(txt):
            neg.append(t.get("turn"))
        h = int(t.get("hint_level", 0) or 0)
        if h < prev:
            order.append(t.get("turn"))
        prev = max(prev, h)
    g["cognitive_load"] = {
        "passed": not bad_q and not bad_len and bool(flow),
        "evidence": [f"질문≠1 턴 {bad_q}", f"4문장 이상 턴 {bad_len}", f"턴 수 {len(flow)}"],
    }
    g["negative_phrase"] = {"passed": not neg, "evidence": [f"금지 표현 턴 {neg}"]}
    g["hint_monotonic"] = {"passed": not order, "evidence": [f"힌트 단계 감소 턴 {order}"]}
    return g


# ───────────────────────────── 집계 ─────────────────────────────
def score_node(cand: dict, gold: dict, std2022: dict, mis_by_id: dict) -> dict:
    axes = {
        "math": score_math(cand),
        "standard": score_standard(cand, gold, std2022),
        "misconception": score_misconception(cand, gold, mis_by_id),
        "op_trace": score_op_trace(cand),
        "vocab": score_vocab(cand, gold),
        "copyright": score_copyright(cand, gold),
    }
    gates = hard_gates(cand)
    # 기계 확정 점수 합과 상한 합을 따로 낸다 — 상한을 점수로 위장하지 않는다
    machine_total = sum(a["score"] for a in axes.values() if a["score"] is not None)
    ceiling_total = sum(a["ceiling"] for a in axes.values())
    fail_reasons = []
    if axes["math"]["ceiling"] == 0:
        fail_reasons.append("수학 0점")
    if axes["copyright"]["ceiling"] == 0:
        fail_reasons.append("저작권 0점")
    fail_reasons += [k for k, v in gates.items() if not v["passed"]]
    if any(a["ceiling"] <= 1 for a in axes.values()):
        fail_reasons.append("어느 축 상한 ≤1")
    if ceiling_total < 15:
        fail_reasons.append(f"상한 합 {ceiling_total} < 15")
    status = (
        "FAIL"
        if fail_reasons
        else ("JUDGE_REQUIRED" if any(a["judge_required"] for a in axes.values()) else "PASS")
    )
    return {
        "golden_id": gold["golden_id"],
        "standard_code": gold["standard_code"],
        "status": status,
        "fail_reasons": fail_reasons,
        "machine_total": machine_total,
        "ceiling_total": ceiling_total,
        "axes": axes,
        "gates": gates,
    }


def judge_rows(cand: dict, gold: dict, result: dict) -> list[dict]:
    """판단형 축의 LLM 심판 입력(루브릭 §7) — 골든과 후보를 나란히 싣는다."""
    rows = []
    for ax, a in result["axes"].items():
        if a["judge_required"]:
            rows.append(
                {
                    "golden_id": gold["golden_id"],
                    "axis": ax,
                    "ceiling": a["ceiling"],
                    "standard_code": gold["standard_code"],
                    "standard_statement": gold["standard_statement"],
                    "golden": {
                        k: gold[k] for k in ("concept_explanation", "socratic_flow", "mc_item")
                    },
                    "candidate": {
                        k: cand.get(k) for k in ("concept_explanation", "socratic_flow", "mc_item")
                    },
                    "machine_evidence": a["evidence"],
                }
            )
    return rows


def wilson_lower(k: int, n: int, z: float = 1.645) -> float:
    """Wilson 단측 하한(95%) — 저장소 게이트 관례."""
    if n == 0:
        return 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    ap.add_argument("--candidates", type=Path, help="후보 JSONL(골든 노드 형태)")
    ap.add_argument(
        "--self-check", action="store_true", help="골든을 후보로 넣어 전건 3점·게이트 통과를 검증"
    )
    ap.add_argument("--out", type=Path, help="리포트 JSON 경로")
    ap.add_argument("--judge-out", type=Path, help="LLM 심판 입력 JSONL 경로")
    args = ap.parse_args()

    try:
        golden = json.loads(args.golden.read_text(encoding="utf-8"))
        std2022 = {
            s["code"]: s
            for s in json.loads(STANDARDS.read_text(encoding="utf-8"))["standards"]
            if s.get("curriculum_revision") == "2022 개정"
        }
        mis_by_id = {
            m["mis_id"]: m
            for m in json.loads(MISCONCEPTIONS.read_text(encoding="utf-8"))["misconceptions"]
        }
    except (OSError, KeyError, json.JSONDecodeError) as e:
        print(f"입력 오류({type(e).__name__}): {e}", file=sys.stderr)
        return 2
    gold_by_id = {g["golden_id"]: g for g in golden["nodes"]}

    if args.self_check:
        cands = [{**g, "_is_golden": True} for g in golden["nodes"]]
    elif args.candidates:
        try:
            cands = [
                json.loads(line)
                for line in args.candidates.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as e:
            print(f"후보 파싱 실패({type(e).__name__}): {e}", file=sys.stderr)
            return 2
    else:
        ap.error("--candidates 또는 --self-check 중 하나가 필요")
        return 2
    if not cands:
        print("후보 0건 — 측정 실패(통과 아님)", file=sys.stderr)
        return 2

    results, judge, unknown = [], [], []
    for c in cands:
        g = gold_by_id.get(c.get("golden_id"))
        if g is None:
            unknown.append(c.get("golden_id"))
            continue
        r = score_node(c, g, std2022, mis_by_id)
        results.append(r)
        judge += judge_rows(c, g, r)

    n = len(results)
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_pass_or_hold = n - n_fail
    summary = {
        "golden_version": golden.get("golden_version"),
        "golden_digest": golden.get("digest"),
        "scored": n,
        "unknown_golden_id": unknown,
        "fail": n_fail,
        "judge_required_rows": len(judge),
        "machine_pass_rate_wilson_lower": round(wilson_lower(n_pass_or_hold, n), 3) if n else None,
        "note": "machine_total은 기계가 확정한 점수의 합, "
        "ceiling_total은 심판이 넘을 수 없는 상한의 합이다. "
        "최종 점수 = 축별 min(ceiling, 심판 점수).",
    }
    report = {"summary": summary, "results": results}
    if args.out:
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    if args.judge_out:
        args.judge_out.write_text(
            "".join(json.dumps(j, ensure_ascii=False) + "\n" for j in judge), encoding="utf-8"
        )

    for r in results:
        axes = " ".join(
            f"{k}={a['score'] if a['score'] is not None else '≤' + str(a['ceiling'])}"
            for k, a in r["axes"].items()
        )
        print(
            f"{r['golden_id']} {r['standard_code']:<16} {r['status']:<15} {axes}"
            + (f"  ← {r['fail_reasons']}" if r["fail_reasons"] else "")
        )
    print(json.dumps(summary, ensure_ascii=False))

    if args.self_check:
        # 골든은 전 축 상한 3·게이트 전건 통과·기계 확정 축(③④) 3점이어야 한다
        # — 아니면 골든 자체 결함
        bad = [
            r["golden_id"]
            for r in results
            if r["status"] == "FAIL"
            or any(a["ceiling"] != 3 for a in r["axes"].values())
            or r["axes"]["misconception"]["score"] != 3
            or r["axes"]["op_trace"]["score"] != 3
        ]
        if bad or unknown or n != golden["count"]:
            print(
                f"자가검증 실패: 결함 노드 {bad} · 미상 {unknown} · 채점 {n}/{golden['count']}",
                file=sys.stderr,
            )
            return 1
        print(f"자가검증 통과: {n}노드 전건 상한 3·게이트 통과")
        return 0
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
