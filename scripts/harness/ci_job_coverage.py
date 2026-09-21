#!/usr/bin/env python3
"""CI 잡 커버리지 열거·대조 — HARN-109.

로컬 재현이 CI 잡을 *통째로* 빠뜨리는 축을 기계로 막는다.

왜 필요한가 (같은 계열 4회):
  2026-08-09 대상 경로를 좁힘 → 2026-09-10 검사 종류를 빠뜨림 →
  2026-09-17 잡을 빠뜨림(PR #1189) → 2026-09-19 잡은 열거했으나 스코프 판정을 틀림(PR #1216).
  4회차가 결정적이다 — 세션은 규칙대로 잡을 전수 열거하고 "안 닿는다"는 근거까지 적었는데,
  그 근거를 `changes` 잡의 실제 path filter가 아니라 *머릿속*에서 지어냈다.
  근거를 **적는 것**과 근거를 **정본에서 읽는 것**은 다르다. 그래서 이 도구는
  사람이 스코프를 판단하지 않게 하고, ci.yml 자신을 정본으로 읽어 계산한다.

범위 (acceptance ⑥):
  이 도구는 *열거와 대조*만 한다. 잡을 대신 실행하는 러너가 아니다.
  로컬에서 재현 불가한 잡(이미지 빌드·서비스 컨테이너 의존)은 "재현 불가"로 명시 출력한다 —
  그것을 조용히 "실행했다"로 계상하는 것이 빠뜨리는 것보다 나쁘기 때문이다.

서브커맨드:
  enumerate  잡 전량 + 잡별 실행 환경(working-directory·서비스·설치) 요약
  scope      변경 파일이 닿는 잡 판정 (triggered / not_triggered / always / schedule_only / unknown)
  check      실제로 돌린 잡 집합과 대조 — 빠진 잡이 있으면 이름을 지목하고 exit 1

exit code: 0 통과 · 1 미달(빠진 잡·열거 0건·판정 불가 잔존) · 2 사용 오류
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ── 상수 ──────────────────────────────────────────────────────────────────
DEFAULT_WORKFLOW = Path(".github/workflows/ci.yml")

#: path filter를 계산하는 잡 이름. ci.yml에서 이 잡이 사라지면 판정 근거가 없어지므로
#: "판정 불가"가 되어야지 조용히 "전부 안 닿음"이 되면 안 된다.
FILTER_JOB = "changes"

#: 실행 결과 분류.
TRIGGERED = "triggered"  # 이번 변경이 이 잡을 깨운다
NOT_TRIGGERED = "not_triggered"  # path filter가 이 잡을 걸러낸다
ALWAYS = "always"  # 필터와 무관하게 매 PR에서 돈다
SCHEDULE_ONLY = "schedule_only"  # 야간(schedule) 전용 — PR에서는 안 돈다
UNKNOWN = "unknown"  # 판정 불가 — 모른다는 것은 아니다와 다르다


class ScanEmptyError(RuntimeError):
    """전수 스캔이 0건을 반환 — 통과가 아니라 실패다(CLAUDE.md 2026-09-01 축 ④)."""


class _Unknown:
    """3-값 논리의 '모른다'. 비교·논리 연산에서 전파된다."""

    _instance = None

    def __new__(cls) -> "_Unknown":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - 디버그 편의
        return "UNKNOWN"


UNKNOWN_VALUE = _Unknown()


# ── 데이터 구조 ────────────────────────────────────────────────────────────
@dataclass
class JobEnv:
    """잡 하나의 실행 환경 — 잡 경계를 넘을 때 달라지는 것들(acceptance ⑤)."""

    working_directory: str | None = None
    services: list[str] = field(default_factory=list)
    install_hints: list[str] = field(default_factory=list)
    step_count: int = 0
    reproducible_locally: bool = True
    irreproducible_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "working_directory": self.working_directory or "<repo root>",
            "services": self.services,
            "install_hints": self.install_hints,
            "step_count": self.step_count,
            "reproducible_locally": self.reproducible_locally,
            "irreproducible_reason": self.irreproducible_reason,
        }


@dataclass
class JobScope:
    """잡 하나의 스코프 판정 결과."""

    name: str
    status: str
    reason: str
    flags: list[str] = field(default_factory=list)
    matched_files: list[str] = field(default_factory=list)
    env: JobEnv = field(default_factory=JobEnv)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "flags": self.flags,
            "matched_files": self.matched_files[:5],
            "env": self.env.to_dict(),
        }


# ── 워크플로 읽기 ──────────────────────────────────────────────────────────
def load_workflow(path: Path) -> dict[str, Any]:
    """ci.yml을 YAML로 읽는다.

    정규식이 아니라 yaml.safe_load를 쓴다(acceptance ①) — 들여쓰기·인용·블록 스칼라를
    정규식으로 흉내 내면 잡 이름 하나를 조용히 놓치고, 그 누락은 화면에 흔적을 남기지 않는다.
    """
    if not path.exists():
        raise ScanEmptyError(f"워크플로 파일 없음: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ScanEmptyError(f"워크플로 파싱 결과가 매핑이 아님: {path}")
    return data


def enumerate_jobs(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """잡 전량 열거. 0건이면 통과가 아니라 예외다."""
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise ScanEmptyError("잡 열거 0건 — 스캔 0건은 통과가 아니라 실패다")
    return jobs


# ── path filter 파싱 (정본 읽기) ───────────────────────────────────────────
#: `echo "backend=$be" >> "$GITHUB_OUTPUT"` → (플래그명, 셸 변수명)
_OUTPUT_ECHO_RE = re.compile(
    r'echo\s+"(?P<flag>[a-z_]+)=\$(?P<var>[a-z_]+)"\s*>>\s*"\$GITHUB_OUTPUT"'
)

#: `grep -qE '<ERE>'; then\n  <var>=true` → (정규식, 셸 변수명)
_GREP_BLOCK_RE = re.compile(
    r"grep\s+-qE\s+'(?P<pattern>[^']+)'\s*;\s*then\s*\n\s*(?P<var>[a-z_]+)=true",
    re.MULTILINE,
)


def parse_flag_patterns(workflow: dict[str, Any]) -> dict[str, str]:
    """`changes` 잡의 filter 스텝에서 플래그별 경로 정규식을 뽑는다.

    사람이 상상한 규칙이 아니라 **CI가 실제로 쓰는 식**을 읽는 것이 이 함수의 전부다.
    셸 변수명(be·dp·…)과 출력 플래그명(backend·data_pipeline·…)의 매핑도 echo 줄에서
    읽는다 — 어느 쪽도 이 파일에 하드코딩하지 않는다(두 벌 관리 금지).
    """
    jobs = enumerate_jobs(workflow)
    filter_job = jobs.get(FILTER_JOB)
    if not isinstance(filter_job, dict):
        return {}
    run_text = ""
    for step in filter_job.get("steps") or []:
        if isinstance(step, dict) and isinstance(step.get("run"), str):
            run_text += step["run"] + "\n"
    if not run_text:
        return {}

    var_to_flag = {m.group("var"): m.group("flag") for m in _OUTPUT_ECHO_RE.finditer(run_text)}
    patterns: dict[str, str] = {}
    for m in _GREP_BLOCK_RE.finditer(run_text):
        flag = var_to_flag.get(m.group("var"))
        if flag:
            patterns[flag] = m.group("pattern")
    return patterns


def evaluate_flags(
    patterns: dict[str, str], changed_files: list[str]
) -> dict[str, tuple[bool, list[str]]]:
    """변경 파일 목록을 path filter에 통과시켜 플래그 값을 계산한다.

    grep -E(ERE)의 정규식을 Python re로 평가한다. 두 문법은 이 파일이 쓰는 범위
    (앵커·교대·문자클래스·이스케이프)에서 동일하다.
    """
    out: dict[str, tuple[bool, list[str]]] = {}
    for flag, pattern in patterns.items():
        rx = re.compile(pattern)
        hits = [f for f in changed_files if rx.search(f)]
        out[flag] = (bool(hits), hits)
    return out


# ── 잡 조건(if) 평가 — 3값 논리 ────────────────────────────────────────────
_TOKEN_RE = re.compile(r"\s*(\(|\)|&&|\|\||==|!=|!|'[^']*'|[A-Za-z_][A-Za-z0-9_.\-]*)")


def _tokenize(expr: str) -> list[str] | None:
    """GitHub Actions 식을 토큰으로 자른다. 모르는 문자가 나오면 None(판정 불가)."""
    text = expr.strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    tokens: list[str] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            return None
        tokens.append(m.group(1))
        pos = m.end()
    return tokens


class _ConditionEvaluator:
    """if 식을 3값 논리(True/False/UNKNOWN)로 평가한다.

    UNKNOWN을 False로 접지 않는 것이 핵심이다 — "모른다"를 "안 닿는다"로 읽으면
    이 도구 자신이 4회차 사고를 재생산한다.
    """

    def __init__(self, tokens: list[str], context: dict[str, str]):
        self.tokens = tokens
        self.pos = 0
        self.context = context

    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _next(self) -> str | None:
        tok = self._peek()
        if tok is not None:
            self.pos += 1
        return tok

    def parse(self) -> bool | _Unknown:
        value = self._parse_or()
        if self._peek() is not None:  # 남은 토큰 = 우리가 모르는 문법
            return UNKNOWN_VALUE
        return value

    def _parse_or(self) -> bool | _Unknown:
        left = self._parse_and()
        while self._peek() == "||":
            self._next()
            right = self._parse_and()
            left = self._or(left, right)
        return left

    def _parse_and(self) -> bool | _Unknown:
        left = self._parse_comparison()
        while self._peek() == "&&":
            self._next()
            right = self._parse_comparison()
            left = self._and(left, right)
        return left

    def _parse_comparison(self) -> bool | _Unknown:
        if self._peek() == "!":
            self._next()
            inner = self._parse_comparison()
            if isinstance(inner, _Unknown):
                return UNKNOWN_VALUE
            return not inner
        left = self._parse_primary()
        op = self._peek()
        if op in ("==", "!="):
            self._next()
            right = self._parse_primary()
            if isinstance(left, _Unknown) or isinstance(right, _Unknown):
                return UNKNOWN_VALUE
            return (left == right) if op == "==" else (left != right)
        if isinstance(left, bool):
            return left
        return UNKNOWN_VALUE  # 비교 없는 단독 값 — 우리 문법 범위 밖

    def _parse_primary(self) -> Any:
        tok = self._next()
        if tok is None:
            return UNKNOWN_VALUE
        if tok == "(":
            value = self._parse_or()
            if self._peek() == ")":
                self._next()
                return value
            return UNKNOWN_VALUE
        if tok.startswith("'") and tok.endswith("'"):
            return tok[1:-1]
        if tok in ("true", "false"):
            return tok == "true"
        return self.context.get(tok, UNKNOWN_VALUE)

    @staticmethod
    def _and(a: Any, b: Any) -> bool | _Unknown:
        if a is False or b is False:
            return False
        if isinstance(a, _Unknown) or isinstance(b, _Unknown):
            return UNKNOWN_VALUE
        return bool(a and b)

    @staticmethod
    def _or(a: Any, b: Any) -> bool | _Unknown:
        if a is True or b is True:
            return True
        if isinstance(a, _Unknown) or isinstance(b, _Unknown):
            return UNKNOWN_VALUE
        return bool(a or b)


def evaluate_condition(
    expr: str | None, flag_values: dict[str, bool], event_name: str = "pull_request"
) -> bool | _Unknown:
    """잡의 if 조건을 평가한다. if가 없으면 항상 실행(True)."""
    if expr is None:
        return True
    tokens = _tokenize(str(expr))
    if tokens is None:
        return UNKNOWN_VALUE
    context: dict[str, str] = {"github.event_name": event_name}
    for flag, value in flag_values.items():
        context[f"needs.changes.outputs.{flag}"] = "true" if value else "false"
    return _ConditionEvaluator(tokens, context).parse()


def referenced_flags(expr: str | None) -> list[str]:
    """if 식이 참조하는 changes 플래그 이름 전부."""
    if expr is None:
        return []
    return sorted(set(re.findall(r"needs\.changes\.outputs\.([a-z_]+)", str(expr))))


# ── 잡 환경 요약 (acceptance ⑤) ────────────────────────────────────────────
def describe_job_env(job: dict[str, Any]) -> JobEnv:
    """잡의 working-directory·서비스·설치 스텝을 요약하고 로컬 재현 가능성을 판정한다."""
    env = JobEnv()
    defaults = job.get("defaults") or {}
    run_defaults = defaults.get("run") or {}
    env.working_directory = run_defaults.get("working-directory")

    services = job.get("services") or {}
    if isinstance(services, dict):
        env.services = sorted(services.keys())

    steps = job.get("steps") or []
    env.step_count = len(steps)
    for step in steps:
        if not isinstance(step, dict):
            continue
        run = step.get("run")
        uses = step.get("uses")
        if isinstance(run, str):
            for line in run.splitlines():
                stripped = line.strip()
                if re.match(r"^(python\s+-m\s+)?pip\s+install", stripped) or stripped.startswith(
                    ("npm ci", "npm install", "flutter pub get", "pip install")
                ):
                    env.install_hints.append(stripped[:120])
            if re.search(r"\bdocker\s+(build|compose|run)\b", run):
                env.reproducible_locally = False
                env.irreproducible_reason = "docker 빌드·기동이 필요한 스텝 포함"
        if isinstance(uses, str) and uses.startswith("docker/"):
            env.reproducible_locally = False
            env.irreproducible_reason = f"docker 액션 사용: {uses}"

    if env.services and env.reproducible_locally:
        env.reproducible_locally = False
        env.irreproducible_reason = f"서비스 컨테이너 필요: {', '.join(env.services)}"

    # 중복 제거(순서 보존)
    seen: set[str] = set()
    env.install_hints = [h for h in env.install_hints if not (h in seen or seen.add(h))]
    return env


# ── 스코프 판정 ────────────────────────────────────────────────────────────
def classify_jobs(
    workflow: dict[str, Any], changed_files: list[str], event_name: str = "pull_request"
) -> list[JobScope]:
    """잡 전량을 스코프 분류한다 — 이 함수의 출력이 곧 '무엇을 봐야 하는가'의 답이다."""
    jobs = enumerate_jobs(workflow)
    patterns = parse_flag_patterns(workflow)
    flag_eval = evaluate_flags(patterns, changed_files)
    flag_values = {flag: hit for flag, (hit, _) in flag_eval.items()}

    results: list[JobScope] = []
    for name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        env = describe_job_env(job)
        expr = job.get("if")
        flags = referenced_flags(expr)
        verdict = evaluate_condition(expr, flag_values, event_name=event_name)

        missing_flags = [f for f in flags if f not in patterns]
        if missing_flags:
            # 플래그를 참조하는데 필터 정본에 그 플래그가 없다 — 조용히 접지 않는다.
            results.append(
                JobScope(
                    name=name,
                    status=UNKNOWN,
                    reason=f"필터 정본에 플래그 정의 없음: {', '.join(missing_flags)}",
                    flags=flags,
                    env=env,
                )
            )
            continue

        matched: list[str] = []
        for flag in flags:
            matched.extend(flag_eval.get(flag, (False, []))[1])

        if isinstance(verdict, _Unknown):
            status, reason = UNKNOWN, f"if 식을 판정할 수 없음: {str(expr)[:120]}"
        elif verdict is False:
            if not flags and event_name == "pull_request":
                status, reason = SCHEDULE_ONLY, "PR 이벤트에서 실행되지 않는 잡(야간·schedule 전용)"
            else:
                status = NOT_TRIGGERED
                reason = f"path filter가 걸러냄(플래그 {', '.join(flags) or '없음'} = false)"
        elif not flags:
            status, reason = ALWAYS, "필터와 무관하게 매 PR에서 실행"
        else:
            status = TRIGGERED
            reason = f"플래그 {', '.join(f for f in flags if flag_values.get(f))} = true"

        results.append(
            JobScope(
                name=name, status=status, reason=reason, flags=flags, matched_files=matched, env=env
            )
        )
    return results


def jobs_to_cover(scopes: list[JobScope]) -> list[str]:
    """이번 변경에서 로컬이 봐야 하는 잡 = triggered + always + unknown.

    unknown을 포함하는 것이 의도다 — 판정 못 한 잡을 면제하면 이 도구가
    "안 봤다"를 "안 봐도 된다"로 바꿔 주는 위장이 된다.
    """
    return [s.name for s in scopes if s.status in (TRIGGERED, ALWAYS, UNKNOWN)]


# ── git 연동 ───────────────────────────────────────────────────────────────
def changed_files_from_git(base: str, repo_root: Path) -> list[str]:
    """base 대비 변경 파일 목록. 인코딩을 명시한다(cp949 붕괴 방지 — HARN-19)."""
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=repo_root,
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git diff 실패(exit {proc.returncode}): {stderr[:300]}")
    out = proc.stdout.decode("utf-8", errors="replace")
    return [line for line in out.splitlines() if line.strip()]


# ── 출력 ───────────────────────────────────────────────────────────────────
_STATUS_LABEL = {
    TRIGGERED: "● 닿음",
    ALWAYS: "● 상시",
    NOT_TRIGGERED: "○ 안 닿음",
    SCHEDULE_ONLY: "◌ 야간 전용",
    UNKNOWN: "? 판정 불가",
}


def render_scopes(scopes: list[JobScope], changed_files: list[str]) -> str:
    lines = [f"CI 잡 {len(scopes)}건 · 변경 파일 {len(changed_files)}건", ""]
    for status in (TRIGGERED, ALWAYS, UNKNOWN, NOT_TRIGGERED, SCHEDULE_ONLY):
        group = [s for s in scopes if s.status == status]
        if not group:
            continue
        lines.append(f"{_STATUS_LABEL[status]} ({len(group)}건)")
        for s in group:
            lines.append(f"  · {s.name} — {s.reason}")
            if s.status in (TRIGGERED, ALWAYS, UNKNOWN):
                env = s.env
                wd = env.working_directory or "<repo root>"
                extra = f"    wd={wd} · 스텝 {env.step_count}"
                if env.services:
                    extra += f" · 서비스 {','.join(env.services)}"
                if not env.reproducible_locally:
                    extra += f" · 재현 불가({env.irreproducible_reason})"
                lines.append(extra)
                for hint in env.install_hints[:2]:
                    lines.append(f"    설치: {hint}")
        lines.append("")
    return "\n".join(lines)


# ── 서브커맨드 ─────────────────────────────────────────────────────────────
def cmd_enumerate(args: argparse.Namespace) -> int:
    workflow = load_workflow(args.workflow)
    jobs = enumerate_jobs(workflow)
    envs = {name: describe_job_env(job) for name, job in jobs.items() if isinstance(job, dict)}
    if args.json:
        print(json.dumps({n: e.to_dict() for n, e in envs.items()}, ensure_ascii=False, indent=2))
        return 0
    print(f"CI 잡 {len(envs)}건 ({args.workflow})")
    for name, env in envs.items():
        wd = env.working_directory or "<repo root>"
        flag = "" if env.reproducible_locally else f"  [재현 불가: {env.irreproducible_reason}]"
        print(f"  · {name} — wd={wd} · 스텝 {env.step_count}{flag}")
    return 0


def _resolve_changed_files(args: argparse.Namespace) -> list[str]:
    if args.changed_file:
        return list(args.changed_file)
    return changed_files_from_git(args.diff_base, args.workflow.resolve().parent.parent.parent)


def cmd_scope(args: argparse.Namespace) -> int:
    workflow = load_workflow(args.workflow)
    changed = _resolve_changed_files(args)
    scopes = classify_jobs(workflow, changed, event_name=args.event)
    if args.json:
        print(
            json.dumps(
                {
                    "changed_files": changed,
                    "jobs": [s.to_dict() for s in scopes],
                    "to_cover": jobs_to_cover(scopes),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_scopes(scopes, changed))
        print(f"로컬이 봐야 하는 잡: {', '.join(jobs_to_cover(scopes)) or '(없음)'}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    workflow = load_workflow(args.workflow)
    changed = _resolve_changed_files(args)
    scopes = classify_jobs(workflow, changed, event_name=args.event)
    by_name = {s.name: s for s in scopes}
    required = jobs_to_cover(scopes)
    ran = set(args.ran)

    unknown_names = [n for n in ran if n not in by_name]
    missing = [n for n in required if n not in ran]
    irreproducible = [n for n in missing if not by_name[n].env.reproducible_locally]
    actionable = [n for n in missing if n not in irreproducible]
    unknown_verdict = [s.name for s in scopes if s.status == UNKNOWN]

    payload = {
        "required": required,
        "ran": sorted(ran),
        "missing": missing,
        "missing_actionable": actionable,
        "missing_irreproducible": irreproducible,
        "unknown_verdict": unknown_verdict,
        "unknown_job_names": unknown_names,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_scopes(scopes, changed))
        print(f"봐야 하는 잡 {len(required)}건: {', '.join(required) or '(없음)'}")
        print(f"실제로 돌린 잡 {len(ran)}건: {', '.join(sorted(ran)) or '(없음)'}")
        if unknown_names:
            print(f"✗ ci.yml에 없는 잡 이름 {len(unknown_names)}건: {', '.join(unknown_names)}")
        if actionable:
            print(f"✗ 빠진 잡 {len(actionable)}건: {', '.join(actionable)}")
        if irreproducible:
            print(f"⚠ 재현 불가라 건너뛴 잡 {len(irreproducible)}건: {', '.join(irreproducible)}")
            print("  (이 잡들은 '실행했다'로 계상하지 않는다 — CI가 최종 판정한다)")
        if unknown_verdict:
            print(f"⚠ 스코프 판정 불가 {len(unknown_verdict)}건: {', '.join(unknown_verdict)}")
        if not actionable and not unknown_names:
            print("✔ 커버리지 충족 — 봐야 하는 잡을 전부 돌렸다")

    return 1 if (actionable or unknown_names) else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ci_job_coverage.py",
        description="CI 잡 전수 열거·스코프 판정·로컬 재현 커버리지 대조 (HARN-109)",
    )
    p.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW, help="워크플로 파일 경로")
    sub = p.add_subparsers(dest="command", required=True)

    pe = sub.add_parser("enumerate", help="잡 전량 + 실행 환경 요약")
    pe.add_argument("--json", action="store_true")
    pe.set_defaults(func=cmd_enumerate)

    ps = sub.add_parser("scope", help="변경 파일이 닿는 잡 판정")
    ps.add_argument("--changed-file", action="append", default=[], help="변경 파일(반복 지정)")
    ps.add_argument(
        "--diff-base", default="origin/main", help="--changed-file 미지정 시 git diff 기준"
    )
    ps.add_argument("--event", default="pull_request", help="이벤트 이름(기본 pull_request)")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_scope)

    pc = sub.add_parser("check", help="실제로 돌린 잡과 대조 — 빠진 잡이 있으면 exit 1")
    pc.add_argument("--ran", action="append", default=[], help="로컬에서 돌린 잡 이름(반복 지정)")
    pc.add_argument("--changed-file", action="append", default=[])
    pc.add_argument("--diff-base", default="origin/main")
    pc.add_argument("--event", default="pull_request")
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=cmd_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ScanEmptyError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, yaml.YAMLError) as exc:
        print(f"✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
