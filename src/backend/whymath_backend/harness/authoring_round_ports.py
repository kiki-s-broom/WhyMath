"""저작 회차 오케스트레이터의 외부 경계 (EOS-208 ⑥) — 프로세스·HTTP·시계를 주입 가능하게 분리한다.

왜 분리하는가
-------------
오케스트레이터가 실제로 하는 일은 *남의 CLI를 순서대로 부르고 그 결과로 다음 행동을 고르는* 것이다.
그 판단(거부 조건·이어하기·요약)은 CI(헤드리스·네트워크 없음·PowerShell 없음)에서 고정돼야 하는데,
경계가 코드에 박혀 있으면 테스트가 진짜 git·Ollama·창을 띄워야 한다. 그래서 경계는 셋뿐이다:

- `ProcessRunner` — 모든 외부 프로세스(git·저작 CLI·검수 창·집계 CLI·탐침). **타임아웃이 필수
  인자**다(기본값 없음 — "외부 프로세스 호출에는 전부 타임아웃을 건다"를 시그니처로 강제).
- `HttpGetJson` — Ollama 모델 목록(`/api/tags`) 조회. LLM 호출이 아니다(생성은 저작 CLI가
  라우터 경유로 한다).
- `Clock` — 상태 파일의 시각.

실패 정보 보존(CLAUDE.md "측정·수집 도구를 성공 경로만 보고 설계 금지"): `RunResult`는 종료 코드만이
아니라 **타임아웃 사실·stderr 꼬리**를 함께 돌려준다. 스트리밍 모드(저작 CLI처럼 수십 분 걸리는
것)는 stderr를 화면에 그대로 흘리면서 꼬리 40줄을 따로 남긴다 — 실패 원인이 화면 위로 스크롤돼
사라져도 요약 줄이 그것을 다시 보여 준다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

RunMode = Literal["capture", "stream", "inherit"]
_TAIL_LINES = 40


@dataclass(frozen=True)
class RunResult:
    """외부 프로세스 1회 실행 결과.

    `returncode`는 타임아웃이면 None이다(죽인 프로세스의 코드는 판정 근거가 아니다).
    `launch_error`는 실행 자체가 안 된 경우(파일 없음 등)의 예외 타입명이다.
    """

    returncode: int | None
    stdout: str
    stderr_tail: str
    timed_out: bool = False
    launch_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.launch_error is None

    def failure_reason(self) -> str:
        """사람이 읽을 실패 사유 한 줄(예외 타입명·타임아웃 사실·stderr 꼬리 마지막 줄)."""
        if self.launch_error is not None:
            return f"실행 불가({self.launch_error})"
        if self.timed_out:
            return "TimeoutExpired(타임아웃으로 중단)"
        last = next((ln for ln in reversed(self.stderr_tail.splitlines()) if ln.strip()), "")
        return f"exit {self.returncode}" + (f" — {last.strip()[:300]}" if last else "")


class ProcessRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
        mode: RunMode = "capture",
    ) -> RunResult:
        """`capture`=stdout·stderr 모두 수집 · `stream`=stdout 수집·stderr는 화면+꼬리 ·
        `inherit`=화면 그대로(대화형 창·검수 터미널)."""
        ...


class HttpGetJson(Protocol):
    def get_json(self, url: str, *, timeout_s: float) -> Any: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UrllibHttp:
    """urllib 기반 GET — 실패는 예외로 올린다(호출측이 타입명을 남긴다)."""

    def get_json(self, url: str, *, timeout_s: float) -> Any:
        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as resp:  # noqa: S310
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            # HTTP 본문 요약을 남긴다 — 상태 코드만으로는 원인을 모른다.
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"HTTPError {exc.code}: {detail}") from exc
        return json.loads(body)


def _pump(stream: Any, tail: deque[str], echo: bool) -> None:
    for line in iter(stream.readline, ""):
        tail.append(line.rstrip("\n"))
        if echo:
            try:
                sys.stderr.write(line)
                sys.stderr.flush()
            except (ValueError, OSError):
                pass  # 화면이 닫혀도 꼬리 수집은 계속한다
    stream.close()


class SubprocessRunner:
    """실제 실행기. 인코딩은 UTF-8로 **명시**한다(Windows 로캘 cp949 디코드 붕괴 방지 — HARN-19)."""

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
        mode: RunMode = "capture",
    ) -> RunResult:
        if mode == "inherit":
            try:
                completed = subprocess.run(  # noqa: S603
                    list(argv), cwd=str(cwd), env=dict(env), timeout=timeout_s, check=False
                )
            except subprocess.TimeoutExpired:
                return RunResult(None, "", "", timed_out=True)
            except OSError as exc:
                return RunResult(None, "", "", launch_error=type(exc).__name__)
            return RunResult(completed.returncode, "", "")
        try:
            proc = subprocess.Popen(  # noqa: S603
                list(argv),
                cwd=str(cwd),
                env=dict(env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            return RunResult(None, "", "", launch_error=type(exc).__name__)
        tail: deque[str] = deque(maxlen=_TAIL_LINES)
        out_chunks: list[str] = []
        err_thread = threading.Thread(
            target=_pump, args=(proc.stderr, tail, mode == "stream"), daemon=True
        )

        def _read_out() -> None:
            assert proc.stdout is not None
            out_chunks.append(proc.stdout.read())

        out_thread = threading.Thread(target=_read_out, daemon=True)
        err_thread.start()
        out_thread.start()
        try:
            code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            err_thread.join(timeout=5)
            out_thread.join(timeout=5)
            return RunResult(None, "".join(out_chunks), "\n".join(tail), timed_out=True)
        err_thread.join(timeout=30)
        out_thread.join(timeout=30)
        return RunResult(code, "".join(out_chunks), "\n".join(tail))
