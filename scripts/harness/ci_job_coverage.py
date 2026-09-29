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

판정 입력 (HARN-172 — scope·check·ci_mirror 자동 선택이 같은 규칙을 공유한다):
  변경 파일 목록의 출처는 셋이다 — `--changed-file`(반복) · `--stdin`(파이프 명시 소비) ·
  둘 다 없으면 `git diff --name-only <diff-base>...HEAD`. 사고(2026-09-25 PR #1305)는
  staged만 한 변경을 파이프로 넘겼는데 도구가 stdin을 읽지 않고 커밋된 diff(0건)로 판정해
  **변경 파일 0건·exit 0**으로 상시 잡만 내놓은 것이다. 그래서:
    · 변경 파일 0건은 exit 2 — 의도한 0건은 `--allow-empty`로만 통과(스캔 0건은 실패 규칙)
    · 파이프로 들어온 목록을 조용히 버리지 않는다 — `--stdin` 없이 데이터가 있으면 exit 2
    · 머리말에 건수만이 아니라 **사용한 파일 목록 전체**와 출처를 찍고, diff-base 계산에서
      빠진 미커밋 변경(staged·unstaged·untracked)의 건수를 경고로 낸다 — 머리말과 마지막 줄 둘 다
      (`tail`로 잘라 읽어도 보이게).

exit code: 0 통과 · 1 미달(빠진 잡·열거 0건·판정 불가 잔존)
  · 2 사용 오류(판정 대상 변경 파일 0건 · stdin 무시 거부 · git 실패 포함)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Callable
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


class InputRejectedError(RuntimeError):
    """판정 입력을 판정할 수 없는 상태로 받았다 — 사용 오류(exit 2), 통과로 접지 않는다(HARN-172).

    변경 파일 0건 · `--stdin` 없이 파이프로 들어온 목록 · 터미널에서의 `--stdin` · UTF-8이 아닌
    입력이 여기로 온다. 모두 "그대로 진행하면 조용히 다른 입력으로 판정하게 되는" 경우다.
    """


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


# ── 판정 입력 해석 (HARN-172) ──────────────────────────────────────────────
#: 미커밋 변경의 종류와 그것을 내는 git 명령. 튜플 순서가 출력 순서다.
#: `git diff --name-only`와 같은 경로 표기(core.quotePath 인용 포함)를 쓰므로 diff-base 목록과
#: 문자열 그대로 대조할 수 있다 — `-z` 표기로 바꾸면 두 목록의 표기가 갈려 대조가 틀린다.
UNCOMMITTED_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("staged", ("git", "diff", "--name-only", "--cached")),
    ("unstaged", ("git", "diff", "--name-only")),
    ("untracked", ("git", "ls-files", "--others", "--exclude-standard")),
)

#: 파이프 입력을 기다리는 유예(초). 파이프의 쓰는 쪽(`git diff … |`)은 이 도구와 **동시에**
#: 뜨므로, 쓰기가 아직 안 끝났을 수 있다. 유예 안에 아무것도 안 오면 "데이터 없음"으로 본다 —
#: 열린 채 비어 있는 파이프(일부 하네스·CI의 비대화형 stdin)를 거부하면 도구를 못 쓰게 된다.
STDIN_GRACE_SECONDS = 0.5

#: 경고에 늘어놓는 미커밋 파일 수 상한 — 넘으면 "외 N건"으로 줄이되 총수는 항상 말한다.
#: (사용한 변경 파일 목록은 자르지 않는다 — 그것이 판정 입력 자체이기 때문이다.)
_LISTED_EXCLUDED = 20


@dataclass
class ChangedInput:
    """판정에 쓴 변경 파일 목록과 그 출처 — 판정 결과와 함께 반드시 드러낸다."""

    files: list[str]
    source: str
    #: diff-base 출처일 때만 채운다. None = 확인하지 않음(명시 입력) 또는 확인 실패(아래 오류).
    uncommitted: dict[str, list[str]] | None = None
    uncommitted_error: str | None = None
    allow_empty: bool = False

    @property
    def excluded(self) -> list[str] | None:
        """미커밋 변경 중 판정 목록에 없는 경로 — diff-base가 못 본 것. None = 모른다."""
        if self.uncommitted is None:
            return None
        used = set(self.files)
        out: list[str] = []
        for kind, _cmd in UNCOMMITTED_COMMANDS:
            for path in self.uncommitted.get(kind, []):
                if path not in used and path not in out:
                    out.append(path)
        return out

    def excluded_breakdown(self) -> str:
        """빠진 미커밋 변경의 종류별 건수 — `staged 1 · unstaged 0 · untracked 2`."""
        used = set(self.files)
        parts = []
        for kind, _cmd in UNCOMMITTED_COMMANDS:
            paths = (self.uncommitted or {}).get(kind, [])
            parts.append(f"{kind} {len([p for p in paths if p not in used])}")
        return " · ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        excluded = self.excluded
        return {
            "changed_files_source": self.source,
            "allow_empty": self.allow_empty,
            "uncommitted_excluded": excluded,
            "uncommitted_excluded_count": None if excluded is None else len(excluded),
            "uncommitted_error": self.uncommitted_error,
        }


def _clean_paths(items: list[str]) -> list[str]:
    """앞뒤 공백·CR을 벗기고 빈 줄을 버리며 순서를 지켜 중복을 없앤다."""
    out: list[str] = []
    for item in items:
        text = item.strip()
        if text and text not in out:
            out.append(text)
    return out


def uncommitted_paths(repo_root: Path) -> dict[str, list[str]]:
    """커밋되지 않은 변경 경로를 종류별로 돌려준다. git 실패는 예외 — 0건으로 접지 않는다."""
    found: dict[str, list[str]] = {}
    for kind, cmd in UNCOMMITTED_COMMANDS:
        proc = subprocess.run(list(cmd), cwd=repo_root, capture_output=True, timeout=60)
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"{' '.join(cmd)} 실패(exit {proc.returncode}): {stderr[:300]}")
        out = proc.stdout.decode("utf-8", errors="replace")
        found[kind] = [line for line in out.splitlines() if line.strip()]
    return found


# ── 표준 입력 감지 ─────────────────────────────────────────────────────────
def stdin_pending_data(stream: Any = None, grace: float = STDIN_GRACE_SECONDS) -> bool | None:
    """표준 입력에 아직 읽지 않은 데이터가 있는가 — **소비하지 않고, 멈추지 않고** 본다.

    True = 있다(파이프·파일 리다이렉트) · False = 없다(터미널·문자 장치(/dev/null·NUL)·
    닫힌 빈 파이프·유예 안에 아무것도 안 온 열린 파이프) · None = 판정 불가(fileno 없는 대체
    객체 — pytest 캡처처럼 이 CLI에 파이프를 댄 것이 아닌 경우 — 또는 플랫폼 조회 실패).

    설계 제약 (acceptance ② 주의):
      · 블로킹 read 금지 — 열린 빈 파이프에서 read하면 쓰는 쪽이 닫을 때까지 멈춘다.
        POSIX는 `select`로 유예만큼 기다린 뒤 `FIONREAD`로 남은 바이트 수를 센다.
      · Windows 파이프에는 `select`가 안 된다(소켓 전용). `PeekNamedPipe`로 남은 바이트를 센다.
      · 소비 금지 — 1바이트를 읽어 EOF와 데이터를 가르는 방식은 호출자의 stdin을 갉아 먹는다
        (`… | while read f; do tool …; done` 루프에서 다음 줄이 깨진다). 두 조회 모두 비소비다.
    한계: 유예보다 늦게 쓰기 시작하는 파이프는 "없음"으로 보인다 — 그때도 머리말의 출처
    표기(`git diff …`)와 사용 목록이 그 사실을 드러낸다.
    """
    stream = sys.stdin if stream is None else stream
    if stream is None:
        return False
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):  # io.UnsupportedOperation 포함
        return None
    try:
        if os.isatty(fd):
            return False
        mode = os.fstat(fd).st_mode
        if stat.S_ISREG(mode):
            # `< 목록.txt` 리다이렉트 — 남은 바이트(크기 − 현재 위치)로 본다.
            return os.fstat(fd).st_size > os.lseek(fd, 0, os.SEEK_CUR)
    except OSError:
        return None
    if not (stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)):
        return False  # 문자 장치(/dev/null·NUL) 등 — 파이프로 넘긴 목록이 아니다
    if os.name == "nt":  # pragma: no cover - Windows 전용 경로(판정 로직은 _poll_pipe가 검증됨)
        return _poll_pipe(lambda: _windows_pipe_peek(fd), grace)
    return _posix_pipe_has_data(fd, grace)


def _posix_pipe_has_data(fd: int, grace: float) -> bool | None:
    """select로 '읽을 수 있음(데이터 또는 EOF)'을 유예만큼 기다린 뒤 FIONREAD로 바이트를 센다."""
    import array  # noqa: PLC0415  (POSIX 전용 경로에서만 필요)
    import fcntl  # noqa: PLC0415  (Windows에 없는 모듈)
    import select  # noqa: PLC0415
    import termios  # noqa: PLC0415  (Windows에 없는 모듈)

    try:
        select.select([fd], [], [], grace)
        buf = array.array("i", [0])
        fcntl.ioctl(fd, termios.FIONREAD, buf, True)
    except (OSError, ValueError):
        return None
    return buf[0] > 0


def _poll_pipe(
    peek: Callable[[], tuple[int | None, bool]],
    grace: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool | None:
    """`peek()` = (남은 바이트 수|None=조회 실패, 쓰는 쪽이 닫혔는가)를 유예만큼 폴링한다.

    데이터가 보이면 True, 쓰는 쪽이 닫혔는데 비었으면 False(EOF), 유예가 끝나도 비었으면
    False, 조회가 실패하면 None(모른다). Windows 경로가 이 판정을 쓴다.
    """
    deadline = clock() + grace
    while True:
        available, closed = peek()
        if available is None:
            return None
        if available > 0:
            return True
        if closed or clock() >= deadline:
            return False
        sleep(0.02)


def _windows_pipe_peek(fd: int) -> tuple[int | None, bool]:  # pragma: no cover - Windows 전용
    """PeekNamedPipe로 남은 바이트 수를 비소비·비차단으로 조회한다."""
    import ctypes  # noqa: PLC0415
    import msvcrt  # noqa: PLC0415  (Windows 전용 모듈)
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    available = wintypes.DWORD(0)
    try:
        handle = msvcrt.get_osfhandle(fd)
    except OSError:
        return None, False
    ok = kernel32.PeekNamedPipe(
        wintypes.HANDLE(handle), None, 0, None, ctypes.byref(available), None
    )
    if ok:
        return int(available.value), False
    if ctypes.get_last_error() == 109:  # ERROR_BROKEN_PIPE — 쓰는 쪽이 닫혔고 남은 것이 없다
        return 0, True
    return None, False


def read_stdin_paths(stream: Any = None) -> list[str]:
    """`--stdin` — 표준 입력을 끝까지 읽어 경로 목록으로 만든다.

    터미널이면 거부한다(사람이 Ctrl-D를 칠 때까지 멈추는 것을 막는다). UTF-8이 아니면
    거부한다 — 깨진 경로는 어느 필터에도 안 맞아 "안 닿음"으로 조용히 접힌다.
    """
    stream = sys.stdin if stream is None else stream
    if stream is None:
        raise InputRejectedError("--stdin인데 표준 입력이 없다")
    try:
        is_tty = bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        is_tty = False
    if is_tty:
        raise InputRejectedError(
            "--stdin인데 표준 입력이 터미널이다 — 입력을 기다리며 멈추지 않도록 거부한다. "
            "목록을 파이프로 넘겨라(예: git diff --cached --name-only | … --stdin)"
        )
    raw = stream.buffer.read() if hasattr(stream, "buffer") else stream.read()
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InputRejectedError(
                f"--stdin 입력이 UTF-8이 아니다({exc.reason} @ byte {exc.start}) — "
                f"경로를 깨진 채 판정하지 않는다"
            ) from exc
    else:
        text = str(raw).lstrip("﻿")
    return _clean_paths(text.splitlines())


def resolve_changed_files(
    *,
    changed_file: list[str] | None,
    use_stdin: bool,
    diff_base: str,
    repo_root: Path,
    allow_empty: bool,
    stdin: Any = None,
) -> ChangedInput:
    """판정 입력을 정한다 — scope·check·ci_mirror 자동 선택의 단일 창구(HARN-172 ①②③④).

    ② 파이프 입력 정책 — **거부**를 택했다(`--stdin`은 명시 소비 경로로 둔다):
      `--changed-file`도 `--stdin`도 없는데 표준 입력에 데이터가 있으면 exit 2로 거부한다.
      자동 소비를 택하지 않은 이유: 자동 소비는 "데이터가 있는가" 감지가 틀리는 두 방향에서
      모두 조용히 오동작한다 — 거짓 음성이면 오늘처럼 목록이 버려지고, 거짓 양성(열린 빈
      파이프)이면 블로킹 read로 멈춘다. 거부는 감지가 틀려도 결과가 시끄럽고(exit 2 또는 출처
      표기), 소비는 `--stdin`이 명령 문자열에 남아 **무엇을 판정 입력으로 썼는지 명령만 보고
      재현할 수 있다**. 감지는 `--changed-file`이 없을 때만 한다(acceptance ② 문면) — 명시
      목록을 준 호출(예: `while read` 루프 안의 호출)을 거짓 거부하지 않기 위해서다.
    ① 0건은 `--allow-empty` 없이는 exit 2 — 스캔 0건은 통과가 아니다.
    ③ diff-base 출처면 미커밋 변경을 함께 조회해, 판정에서 빠진 경로를 경고 재료로 남긴다.
    """
    explicit = _clean_paths(list(changed_file or []))
    if use_stdin:
        files = _clean_paths(explicit + read_stdin_paths(stdin))
        source = "--stdin" + (" + --changed-file" if explicit else "")
        info = ChangedInput(files=files, source=source)
    elif changed_file:
        info = ChangedInput(files=explicit, source="--changed-file")
    else:
        if stdin_pending_data(stdin):
            raise InputRejectedError(
                "표준 입력으로 목록이 들어왔는데 --stdin이 없다 — 조용히 버리고 "
                f"`git diff {diff_base}...HEAD`로 판정하지 않는다.\n"
                "  → 파이프로 넘긴 목록으로 판정하려면 --stdin을 붙여라 "
                "(예: git diff --cached --name-only | … --stdin)\n"
                "  → diff-base로 판정하려면 파이프를 빼라"
            )
        files = changed_files_from_git(diff_base, repo_root)
        info = ChangedInput(files=files, source=f"git diff --name-only {diff_base}...HEAD")
        try:
            info.uncommitted = uncommitted_paths(repo_root)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            info.uncommitted_error = f"{type(exc).__name__}: {exc}"
    info.allow_empty = allow_empty
    if not info.files and not allow_empty:
        raise InputRejectedError(empty_input_reason(info))
    return info


def _uncommitted_detail(info: ChangedInput) -> str:
    excluded = info.excluded
    if excluded is None:
        if info.uncommitted_error:
            return f"미커밋 변경 확인 실패({info.uncommitted_error}) — 빠졌는지 모른다"
        return "미커밋 변경은 확인하지 않았다(명시 입력)"
    if not excluded:
        return "미커밋 변경 0건 — diff-base와 HEAD 사이에 커밋된 변경도 없다"
    return (
        f"미커밋 변경 {len(excluded)}건({info.excluded_breakdown()})이 이 계산에서 빠졌다: "
        + ", ".join(excluded[:_LISTED_EXCLUDED])
        + (f" 외 {len(excluded) - _LISTED_EXCLUDED}건" if len(excluded) > _LISTED_EXCLUDED else "")
    )


def empty_input_reason(info: ChangedInput) -> str:
    """0건 거부 사유 — 사람이 다음 행동을 고를 수 있게 원인 후보를 실측값과 함께 적는다."""
    return (
        "판정 대상 없음 — `--diff-base`가 커밋되지 않은 변경을 못 보는지, "
        "`--changed-file`을 빠뜨렸는지 확인하라\n"
        f"  · 변경 파일 0건 (출처: {info.source})\n"
        f"  · {_uncommitted_detail(info)}\n"
        "  → 목록을 넘기려면 --changed-file <경로>(반복) 또는 `<목록 명령> | … --stdin`\n"
        "  → 정말 변경이 없어 상시 잡만 보려면 --allow-empty로 의도를 명령에 남겨라 "
        "(스캔 0건은 통과가 아니다)"
    )


def input_warning_details(info: ChangedInput) -> list[str]:
    """머리말용 경고 — 미커밋 변경이 판정에서 빠졌거나, 빠졌는지 모를 때."""
    excluded = info.excluded
    if excluded is None and not info.uncommitted_error:
        return []
    if excluded == []:
        return []
    lines = [f"⚠ {_uncommitted_detail(info)}"]
    if excluded:
        lines.append(
            "  → diff-base는 커밋된 변경만 본다. 판정에 넣으려면 커밋한 뒤 다시 돌리거나 "
            "목록을 --changed-file/--stdin으로 넘겨라"
        )
    return lines


def input_warning_tail(info: ChangedInput) -> str | None:
    """마지막 줄용 한 줄 경고 — 출력을 `tail`로 잘라 읽어도 보이게 머리말 경고를 반복한다."""
    excluded = info.excluded
    if excluded:
        return (
            f"⚠ 미커밋 변경 {len(excluded)}건({info.excluded_breakdown()})이 이 판정에서 "
            f"빠졌다 — 머리말 목록 참조"
        )
    if excluded is None and info.uncommitted_error:
        return "⚠ 미커밋 변경을 확인하지 못했다 — 이 판정이 무엇을 빠뜨렸는지 모른다"
    return None


def render_changed_input(info: ChangedInput) -> list[str]:
    """사용한 변경 파일 목록 **전체**와 출처 — 판정 입력을 그대로 드러낸다(acceptance ③)."""
    lines = [f"사용한 변경 파일 {len(info.files)}건 (출처: {info.source})"]
    if not info.files:
        lines.append("  (0건 — --allow-empty로 의도한 판정: 상시·판정 불가 잡만 대상이다)")
    lines.extend(f"  - {path}" for path in info.files)
    lines.extend(input_warning_details(info))
    return lines


# ── 출력 ───────────────────────────────────────────────────────────────────
_STATUS_LABEL = {
    TRIGGERED: "● 닿음",
    ALWAYS: "● 상시",
    NOT_TRIGGERED: "○ 안 닿음",
    SCHEDULE_ONLY: "◌ 야간 전용",
    UNKNOWN: "? 판정 불가",
}


def render_scopes(
    scopes: list[JobScope], changed_files: list[str], changed_input: ChangedInput | None = None
) -> str:
    lines = [f"CI 잡 {len(scopes)}건 · 변경 파일 {len(changed_files)}건"]
    if changed_input is not None:
        # 건수만으로는 "무엇으로 판정했는가"를 모른다 — 사용 목록 전체와 출처를 찍는다(HARN-172).
        lines.extend(render_changed_input(changed_input))
    lines.append("")
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


def _resolve_changed_files(args: argparse.Namespace) -> ChangedInput:
    return resolve_changed_files(
        changed_file=args.changed_file,
        use_stdin=args.stdin,
        diff_base=args.diff_base,
        repo_root=args.workflow.resolve().parent.parent.parent,
        allow_empty=args.allow_empty,
    )


def _print_json_warnings(info: ChangedInput) -> None:
    """JSON 모드는 stdout이 순수 JSON이어야 하므로 경고를 stderr로 낸다(값은 JSON에도 실린다)."""
    for line in input_warning_details(info):
        print(line, file=sys.stderr)


def cmd_scope(args: argparse.Namespace) -> int:
    workflow = load_workflow(args.workflow)
    info = _resolve_changed_files(args)
    changed = info.files
    scopes = classify_jobs(workflow, changed, event_name=args.event)
    if args.json:
        _print_json_warnings(info)
        print(
            json.dumps(
                {
                    "changed_files": changed,
                    **info.to_dict(),
                    "jobs": [s.to_dict() for s in scopes],
                    "to_cover": jobs_to_cover(scopes),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_scopes(scopes, changed, info))
        print(f"로컬이 봐야 하는 잡: {', '.join(jobs_to_cover(scopes)) or '(없음)'}")
        tail = input_warning_tail(info)
        if tail:
            print(tail)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    workflow = load_workflow(args.workflow)
    info = _resolve_changed_files(args)
    changed = info.files
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
        "changed_files": changed,
        **info.to_dict(),
    }
    if args.json:
        _print_json_warnings(info)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_scopes(scopes, changed, info))
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
        tail = input_warning_tail(info)
        if tail:
            print(tail)

    return 1 if (actionable or unknown_names) else 0


def _add_input_arguments(parser: argparse.ArgumentParser) -> None:
    """scope·check 공통 판정 입력 인자 (HARN-172)."""
    parser.add_argument("--changed-file", action="append", default=[], help="변경 파일(반복 지정)")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="표준 입력의 경로 목록(줄 단위)을 판정 입력으로 명시 소비한다 — 없으면 파이프 입력은 "
        "거부된다(조용히 버리지 않는다)",
    )
    parser.add_argument(
        "--diff-base",
        default="origin/main",
        help="--changed-file·--stdin 미지정 시 git diff 기준(커밋된 변경만 본다)",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="변경 파일 0건을 의도한 판정으로 허용한다 — 없으면 0건은 exit 2(스캔 0건은 실패)",
    )


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
    _add_input_arguments(ps)
    ps.add_argument("--event", default="pull_request", help="이벤트 이름(기본 pull_request)")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_scope)

    pc = sub.add_parser("check", help="실제로 돌린 잡과 대조 — 빠진 잡이 있으면 exit 1")
    pc.add_argument("--ran", action="append", default=[], help="로컬에서 돌린 잡 이름(반복 지정)")
    _add_input_arguments(pc)
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
    except InputRejectedError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    except (RuntimeError, yaml.YAMLError) as exc:
        print(f"✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
