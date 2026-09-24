"""헌법 토큰 실측 — 세션 시작 고정비를 추정이 아니라 측정으로 (HARN-121 ①).

왜 필요한가
-----------
`docs/reviews/recurring_failure_taxonomy_2026-09-20.md`는 세션 고정비를 "4.5만~6.8만
토큰"으로 적으면서 **추정임을 명시**한다(문자 구성 기반). 다이어트의 목표가 "코어
≤ 1.5만 토큰"인데 분모가 추정이면 달성 여부를 판정할 수 없다.

무엇을 재나
-----------
세션 시작 고정비 = `CLAUDE.md` + `AGENTS.md`(있으면) + SessionStart 브리핑 출력.
셋을 각각 재고 합계를 낸다 — 어느 쪽이 큰지 알아야 무엇을 줄일지 정해진다.

왜 tiktoken을 쓰지 않는가
------------------------
tiktoken은 OpenAI BPE이고 Claude의 토크나이저가 아니다. 한국어 비중이 높은 문서에서
둘의 차이는 작지 않으므로, 그것으로 낸 수를 "실측"이라 부르면 보고서가 배제한 추정을
이름만 바꿔 되살리는 것이다. 그래서 **Anthropic `count_tokens` API만** 쓰고, 키가
없으면 측정하지 않고 그렇게 말한다(모른다 ≠ 0).

실행 환경: Phaiakes9 (Kiki 머신) — 실 API 키가 있는 유일한 곳.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 세션 시작마다 읽히는 것들 — 없으면 '없음'으로 보고한다(추정하지 않는다).
FIXED_COST_FILES = ("CLAUDE.md", "AGENTS.md")


def _brief_text(root: Path) -> tuple[str, str | None]:
    """SessionStart 브리핑 출력 — (본문, 실패 사유)."""
    import subprocess

    # 자식 stdout을 UTF-8로 강제한다(HARN-169). 한국어 Windows에서 파이프 stdout은 로케일
    # 인코딩(cp949)이 되어 브리핑의 `—`·`⚠`에서 UnicodeEncodeError로 exit 1이 난다 —
    # 그러면 브리핑이 '미측정'으로 떨어지고 합계가 하한이 된다. 읽는 쪽이 utf-8이므로
    # 쓰는 쪽도 맞춘다.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(
            [sys.executable, "scripts/harness/backlog.py", "brief", "--format", "text"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
        return "", f"브리핑 실행 실패 — {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return "", f"브리핑 exit {proc.returncode} — {(proc.stderr or '').strip()[:200]}"
    return proc.stdout, None


def _count(client: object, model: str, text: str) -> int:
    result = client.messages.count_tokens(  # type: ignore[attr-defined]
        model=model, messages=[{"role": "user", "content": text}]
    )
    return int(result.input_tokens)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.ops.measure_constitution_tokens",
        description="CLAUDE.md·AGENTS.md·SessionStart 브리핑의 실토큰 수 (HARN-121 ①)",
    )
    parser.add_argument("--model", default="claude-opus-4-7", help="count_tokens 대상 모델")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로")
    parser.add_argument("--out", type=Path, default=None, help="JSON을 이 파일로도 저장")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "❌ ANTHROPIC_API_KEY 없음 — 측정하지 않는다.\n"
            "   문자 수로 대체하지 않는다: 그것이 보고서가 '추정'이라며 배제한 방식이다.",
            file=sys.stderr,
        )
        return 2
    try:
        import anthropic
    except ImportError:
        print("❌ anthropic SDK 없음 — `python -m pip install anthropic`", file=sys.stderr)
        return 2

    client = anthropic.Anthropic()
    parts: dict[str, dict[str, object]] = {}
    total = 0

    for name in FIXED_COST_FILES:
        path = root / name
        if not path.is_file():
            parts[name] = {"measured": False, "reason": "파일 없음"}
            continue
        text = path.read_text(encoding="utf-8")
        try:
            tokens = _count(client, args.model, text)
        except Exception as exc:  # noqa: BLE001 — 실패 사유를 반드시 남긴다
            parts[name] = {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}
            continue
        parts[name] = {"measured": True, "tokens": tokens, "chars": len(text)}
        total += tokens

    brief, brief_error = _brief_text(root)
    if brief_error:
        parts["SessionStart 브리핑"] = {"measured": False, "reason": brief_error}
    else:
        try:
            tokens = _count(client, args.model, brief)
            parts["SessionStart 브리핑"] = {
                "measured": True,
                "tokens": tokens,
                "chars": len(brief),
            }
            total += tokens
        except Exception as exc:  # noqa: BLE001
            parts["SessionStart 브리핑"] = {
                "measured": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }

    unmeasured = [k for k, v in parts.items() if not v["measured"]]
    payload = {
        "model": args.model,
        "parts": parts,
        "total_tokens_measured_only": total,
        "unmeasured": unmeasured,
        "target_core_tokens": 15000,
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"# 세션 시작 고정비 실측 (model={args.model})\n")
    for name, info in parts.items():
        if info["measured"]:
            print(f"  {name:<22} {info['tokens']:>7,} 토큰  ({info['chars']:,}자)")
        else:
            print(f"  {name:<22} {'미측정':>9}  — {info['reason']}")
    print(f"\n  {'합계(측정분만)':<22} {total:>7,} 토큰")
    if unmeasured:
        print(f"  미측정 {len(unmeasured)}건: {', '.join(unmeasured)} — 합계는 하한이다")
    print(f"\n  목표 코어 ≤ 15,000 토큰 — 현재 {'초과' if total > 15000 else '이내'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
