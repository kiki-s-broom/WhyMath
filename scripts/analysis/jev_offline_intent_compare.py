"""Jev 오프라인 의도 비교 — 합성 시험셋으로 규칙·Laya·Jev 3자 판정을 비교한다 (PED-49).

**왜 있나**: PED-48은 laya-ko-whymath를 실학생 트래픽에 *섀도*로 붙였다. 클라우드 Jev(TypeSafe,
미국)도 같은 `/v1/systemone` 형식이라 붙이기는 쉽지만, 실학생 발화를 외부 서버로 보내는 것은
CLAUDE.md(미성년자 데이터 외부 공유 금지)·config 검증(내부망 호스트만)·헌법 R26-02에 걸린다.
그래서 Kiki 결정(2026-10-31)으로 **합성 문장만** 써서 오프라인으로 비교한다.

**불변식**:
- **합성 전용 게이트**: 모든 행에 `"synthetic": true`가 있어야 한다. 한 행이라도 없으면 *어떤
  외부 호출도 하기 전에* 중단한다(부분 전송 방지 — 검사를 전송보다 먼저 끝낸다).
- **같은 질문지**: `_intent_shadow.LAYA_QUESTIONS`(questions_v1)를 그대로 쓴다 — 질문 문구가
  다르면 Laya의 정확도 근거와 비교가 성립하지 않는다.
- **원문 미출력**: 결과 JSON에는 행 번호·라벨·확신도·지연만 담는다(합성이라도 습관을 지킨다).
- **키는 환경변수로만**: `TYPESAFE_API_KEY`(Jev)·`LAYA_API_KEY`(Laya). 명령행 인자로 받지 않는다
  (셸 기록에 남지 않게).
- **침묵 실패 금지**: 호출 실패는 예외 타입명·HTTP 상태로 행마다 기록하고 실패율을 요약에 낸다.

**입력 형식** (JSONL, 한 줄에 하나):
    {"text": "그냥 답 알려줘", "label": "answer_only", "synthetic": true}
  `label`은 6종 중 하나: concept·stuck·answer_only·hint·check·chitchat

**실행 예** (Phaiakes9, PowerShell):
    $env:TYPESAFE_API_KEY = "<콘솔에서 발급한 키>"   # 코드·파일에 쓰지 말 것
    $env:LAYA_API_KEY = "<laya-serve 키>"            # Laya도 비교할 때만
    python scripts/analysis/jev_offline_intent_compare.py `
        --input <합성 272건 경로>.jsonl `
        --laya-url http://127.0.0.1:18080 `
        --output jev_compare_result.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from whymath_backend.api._intent_shadow import LAYA_QUESTIONS, QUESTIONS_VERSION
from whymath_backend.l4.turn_meta import classify_student_intent

# 6종 의도 라벨 — LAYA_QUESTIONS의 choice 보기와 같은 집합이어야 한다(아래에서 검사).
LABELS: tuple[str, ...] = ("concept", "stuck", "answer_only", "hint", "check", "chitchat")

# Jev 공식 엔드포인트. 모델 ID는 고정한다 — `jev-latest`는 예고 없이 새 버전을 가리킬 수 있다.
JEV_BASE_URL = "https://api.typesafe.ai"
JEV_MODEL = "jev-1.13.0"
# laya-serve는 파인튜닝 체크포인트를 `multilingual` 이름으로 서빙한다(_intent_shadow 선례).
LAYA_MODEL = "multilingual"

# 동시 호출 상한 — Jev 공개 한도(분당 1,200건)보다 한참 아래, laya-serve CPU도 굶기지 않게.
MAX_CONCURRENCY = 4


class InputError(ValueError):
    """시험셋 형식·합성 게이트 위반 — 외부 호출 전에 던진다."""


@dataclass
class Prediction:
    """판정기 1개의 행 1건 결과."""

    label: str | None = None
    confidence: float | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    failure: str | None = None
    http_status: int | None = None


@dataclass
class Row:
    index: int
    text: str
    gold: str
    preds: dict[str, Prediction] = field(default_factory=dict)


def load_rows(path: Path) -> list[Row]:
    """JSONL을 읽어 검사한다. 합성 게이트를 *전부* 통과해야 반환한다(부분 전송 방지)."""
    rows: list[Row] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise InputError(f"{lineno}행: JSON 형식 오류({type(exc).__name__})") from exc
            if obj.get("synthetic") is not True:
                # 실학생 문장이 섞였을 가능성 — 외부(미국) 서버로 보내지 않는다.
                raise InputError(
                    f'{lineno}행: "synthetic": true 표시가 없습니다. 합성 문장만 외부 Jev로 '
                    "보낼 수 있습니다(CLAUDE.md 미성년자 데이터 원칙·헌법 R26-02)."
                )
            text = obj.get("text")
            label = obj.get("label")
            if not isinstance(text, str) or not text.strip():
                raise InputError(f"{lineno}행: text가 비었습니다")
            if label not in LABELS:
                raise InputError(f"{lineno}행: label이 6종({', '.join(LABELS)}) 밖입니다")
            rows.append(Row(index=len(rows), text=text, gold=label))
    if not rows:
        raise InputError("시험셋이 비었습니다")
    return rows


def check_questions_contract() -> None:
    """질문지 보기가 LABELS와 같은지 — 다르면 정확도 계산이 조용히 틀어진다."""
    criteria = LAYA_QUESTIONS["intent"]["criteria"]  # type: ignore[index]
    if tuple(criteria) != LABELS:  # type: ignore[arg-type]
        raise RuntimeError(f"LAYA_QUESTIONS 보기가 바뀌었습니다: {list(criteria)}")  # type: ignore[arg-type]


def rule_predict(row: Row) -> Prediction:
    """규칙 분류기 — 결과는 5종 한국어 enum이라 6종 정답과 직접 비교하지 않고 교차표로만 본다.
    has_solution=False 고정(합성 문장엔 풀이 제출이 없다 — PED-48 비교와 같은 조건)."""
    intent = classify_student_intent(student_input=row.text, has_solution=False)
    return Prediction(label=intent.value if intent is not None else None)


async def systemone_predict(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    *,
    base_url: str,
    api_key: str,
    model: str,
    text: str,
    timeout_s: float,
) -> Prediction:
    """`/v1/systemone` 1회 호출 — Laya·Jev 공통(같은 요청 형식). 예외는 흡수하고 타입명을 남긴다."""
    async with sem:
        started = time.perf_counter()
        status: int | None = None
        try:
            async with asyncio.timeout(timeout_s):  # 총 시간 상한(단계별 timeout 합산 방지)
                resp = await client.post(
                    base_url.rstrip("/") + "/v1/systemone",
                    json={"model": model, "state": text, "questions": LAYA_QUESTIONS},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            status = resp.status_code
            resp.raise_for_status()
            body = resp.json()
            intent = body["answers"]["intent"]
            label = intent["choice"]
            if label not in LABELS:
                raise ValueError("보기 밖 응답")
            # Jev·laya-serve 모두 answer_confidence를 준다(실물 응답 픽스처 확인).
            # 없으면 confidence로 대체한다.
            conf = intent.get("answer_confidence", intent.get("confidence"))
            usage = body.get("usage") or {}
            return Prediction(
                label=label,
                confidence=float(conf) if conf is not None else None,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
                input_tokens=usage.get("input_tokens"),
                http_status=status,
            )
        except Exception as exc:  # noqa: BLE001 — 한 행 실패가 전체 측정을 멈추지 않게
            return Prediction(
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
                failure=type(exc).__name__,
                http_status=status,
            )


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1], 1)


def summarize(rows: list[Row], name: str, *, has_gold_labels: bool = True) -> dict[str, Any]:
    """판정기 1개 요약 — 정확도(6종 판정기만)·혼동표·실패율·지연·토큰."""
    preds = [r.preds[name] for r in rows if name in r.preds]
    ok = [p for p in preds if p.failure is None and p.label is not None]
    confusion: dict[str, Counter[str]] = {g: Counter() for g in LABELS}
    for r in rows:
        p = r.preds.get(name)
        if p is None:
            continue
        confusion[r.gold][
            p.label if p.label is not None else ("(실패)" if p.failure else "(없음)")
        ] += 1
    out: dict[str, Any] = {
        "n": len(preds),
        "failures": len(preds) - len(ok),
        "failure_types": dict(Counter(p.failure for p in preds if p.failure)),
        "confusion_gold_to_pred": {g: dict(c) for g, c in confusion.items()},
    }
    if has_gold_labels:
        correct = sum(1 for r in rows if name in r.preds and r.preds[name].label == r.gold)
        # 분모는 전체 행 — 실패를 정답률에서 빼면 실패가 많을수록 점수가 좋아 보인다.
        out["accuracy"] = round(correct / len(rows), 4) if rows else None
        per_label = {}
        for g in LABELS:
            gold_rows = [r for r in rows if r.gold == g]
            hit = sum(1 for r in gold_rows if r.preds.get(name) and r.preds[name].label == g)
            per_label[g] = round(hit / len(gold_rows), 4) if gold_rows else None
        out["recall_by_label"] = per_label
    lat = [p.latency_ms for p in ok if p.latency_ms is not None]
    if lat:
        out["latency_ms"] = {"p50": _percentile(lat, 50), "p95": _percentile(lat, 95)}
    toks = [p.input_tokens for p in ok if isinstance(p.input_tokens, int)]
    if toks:
        out["input_tokens_total"] = sum(toks)
    return out


def agreement(rows: list[Row], a: str, b: str) -> float | None:
    """두 6종 판정기가 같은 라벨을 낸 비율(둘 다 성공한 행 기준)."""
    both = [
        r
        for r in rows
        if r.preds.get(a) and r.preds.get(b) and r.preds[a].label and r.preds[b].label
    ]
    if not both:
        return None
    return round(sum(1 for r in both if r.preds[a].label == r.preds[b].label) / len(both), 4)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    check_questions_contract()
    rows = load_rows(Path(args.input))  # 합성 게이트 — 외부 호출보다 반드시 먼저

    for r in rows:
        r.preds["rule"] = rule_predict(r)

    targets: list[tuple[str, str, str, str]] = []  # (이름, URL, 키, 모델)
    if not args.skip_jev:
        jev_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        if not jev_key:
            raise SystemExit(
                "TYPESAFE_API_KEY 환경변수가 비었습니다 (--skip-jev로 Jev 없이 실행 가능)"
            )
        targets.append(("jev", args.jev_url, jev_key, args.jev_model))
    if args.laya_url:
        laya_key = os.environ.get("LAYA_API_KEY", "").strip()
        if not laya_key:
            raise SystemExit("--laya-url을 줬지만 LAYA_API_KEY 환경변수가 비었습니다")
        targets.append(("laya", args.laya_url, laya_key, LAYA_MODEL))

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for name, url, key, model in targets:
            results = await asyncio.gather(
                *(
                    systemone_predict(
                        client,
                        sem,
                        base_url=url,
                        api_key=key,
                        model=model,
                        text=r.text,
                        timeout_s=args.timeout,
                    )
                    for r in rows
                )
            )
            for r, p in zip(rows, results, strict=True):
                r.preds[name] = p

    names6 = [n for n, *_ in targets]
    report: dict[str, Any] = {
        "questions_version": QUESTIONS_VERSION,
        "jev_model": args.jev_model if "jev" in names6 else None,
        "n_rows": len(rows),
        "gold_distribution": dict(Counter(r.gold for r in rows)),
        "rule": summarize(rows, "rule", has_gold_labels=False),
    }
    for n in names6:
        report[n] = summarize(rows, n)
    if "jev" in names6 and "laya" in names6:
        report["agreement_jev_laya"] = agreement(rows, "jev", "laya")
    if "jev" in names6 and "input_tokens_total" in report["jev"]:
        # 공개 단가 $0.042 / 입력 100만 토큰(2026-10 기준, 출력 무료) — 참고용 추정
        report["jev"]["estimated_cost_usd"] = round(
            report["jev"]["input_tokens_total"] * 0.042 / 1e6, 6
        )
    # 행별 결과 — 원문 없이 행 번호·정답·각 판정만
    report["rows"] = [
        {
            "i": r.index,
            "gold": r.gold,
            **{
                n: {"label": p.label, "conf": p.confidence, "fail": p.failure}
                for n, p in r.preds.items()
            },
        }
        for r in rows
    ]
    return report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="합성 시험셋으로 규칙·Laya·Jev 의도 판정 비교 (PED-49)")
    p.add_argument("--input", required=True, help="합성 JSONL (모든 행 synthetic=true)")
    p.add_argument("--output", default="jev_compare_result.json", help="결과 JSON 경로")
    p.add_argument("--laya-url", default="", help="laya-serve 기준 URL (비우면 Laya 생략)")
    p.add_argument("--jev-url", default=JEV_BASE_URL, help="Jev 기준 URL")
    p.add_argument("--jev-model", default=JEV_MODEL, help="Jev 모델 ID (고정 권장)")
    p.add_argument("--skip-jev", action="store_true", help="Jev 호출 생략 (규칙·Laya만)")
    p.add_argument("--timeout", type=float, default=5.0, help="호출 1건 총 시간 상한(초)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = asyncio.run(run(args))
    except InputError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # 화면에는 핵심만
    for n in ("jev", "laya"):
        if n in report:
            s = report[n]
            print(
                f"{n}: 정확도 {s.get('accuracy')} · 실패 {s['failures']}/{s['n']}"
                f" · 지연 {s.get('latency_ms')}"
            )
    if "agreement_jev_laya" in report:
        print(f"Jev↔Laya 일치율: {report['agreement_jev_laya']}")
    print(f"결과 저장: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
