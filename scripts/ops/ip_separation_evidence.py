#!/usr/bin/env python3
"""겸직 IP 귀속 분리 증빙 — 커밋 신원·시각·환경 증거 생성기 (IP-SEP).

**무엇을 만드는가**: 게이트 `G-eos-ip-separation-evidence`의 **①번 축**
("개인 장비·개인 계정·개인 시간 작업 사실 증빙 — 커밋 타임스탬프 등")에 쓸
기계 증거를 저장소 이력에서 산출한다. 산출물은 실사(due diligence)에 그대로
제출할 수 있는 JSON + Markdown 한 쌍이다.

**무엇을 만들지 않는가**: 이 도구는 **판정하지 않는다**. 귀속의 법적 판단은
사람(변호사·본인) 몫이고, 여기서 나오는 것은 *사실 자료*뿐이다. 게이트의 ②
(재직사 자산 무사용 확인서)·③(IP 양도 예정 기록)은 사람의 의사표시라 애초에
기계 대체가 금지돼 있다(CLAUDE.md "법령 유래 절차의 기계 대체 금지").

측정 축 4개
-----------
  · `IDENT-01` **신원 혼입** — author·committer·`Co-Authored-By` 신원이 선언된
    개인 신원 밖인가. 유일하게 **exit 1을 내는 축**이다. 재직사 도메인 이메일이
    한 건이라도 섞이면 그 커밋은 귀속 다툼의 입구가 된다.
  · `ENV-01` **작업 환경 분포** — author 타임존 오프셋의 분포. `+09:00`은 KST
    로컬 작업, 그 외는 다른 환경(클라우드 세션 컨테이너 등)을 뜻한다. 판정이
    아니라 **분포 보고**다 — "전부 개인 장비"라는 순진한 주장을 이 도구가 대신
    해 주지 않는다는 뜻이기도 하다.
  · `TIME-01` **시각 분포** — KST 기준 요일·시각 히스토그램과 평일 업무시간
    (09:00~18:00) 비율. 기본값으로는 신호를 내지 않는다(임계 미지정). 임계에
    법적 의미가 없는데 숫자를 하나 박아 두면 그 숫자가 근거처럼 읽히기 때문이다.
    `--work-hours-threshold`를 준 사람만 그 임계로 판정을 받는다.
  · `AI-01` **AI 저작 비율** — author가 도구 신원인 커밋 **과** `Co-Authored-By`
    트레일러에 도구 신원이 있는 커밋. AI 생성물의 저작권 귀속은 별개 쟁점이라
    **정보 축**으로만 낸다.

스캔 범위 — 기본이 `--all`인 이유 (2026-09-07 실측)
--------------------------------------------------
초판은 `git log HEAD`만 순회했다. 이 저장소에서 그렇게 재면 **2297건 중 1018건**
(44%)만 보고 "이력 전체에서 혼입 0건"이라고 선언한다 — 나머지 1279건은 미머지
브랜치·원격 참조에 있어 HEAD에서 도달할 수 없기 때문이다. 증빙 문서에 실리면
그대로 거짓 진술이므로 **기본 범위를 모든 ref(`--all`)로 바꿨다**.

`--rev`·`--since`로 범위를 좁히면 리포트는 그 사실을 `scope.is_full_history=false`와
`unmeasured` 항목으로 **스스로 표시**하고, "이력 전체" 문구를 쓰지 않는다.

설계 계약 (CLAUDE.md 준수)
--------------------------
① **측정 실패 ≠ 통과**: shallow 클론·git 실패·신원 미선언·커밋 0건은 전부
   exit 2다. 잘린 이력에서 나온 "혼입 0건"은 안심이 아니라 거짓말이다.
② **침묵 실패 금지**: 모든 실패 사유에 **예외 타입명**을 담는다.
③ **실패해도 증거가 남는다**: `--jsonl`을 주면 커밋 1건을 읽을 때마다 즉시
   flush한다. 중간에 죽어도 그 시점까지의 수집이 남는다.
④ **서브프로세스 타임아웃**: `git log` 스트림에 **watchdog 스레드**로 마감을
   건다. 블로킹 `read()` 뒤에서만 deadline을 보면 출력 없이 멈춘 프로세스에는
   타임아웃이 영영 걸리지 않는다(2026-09-07 리뷰 지적). stderr는 파이프가 아니라
   임시 파일로 받는다 — 파이프가 가득 차 교착되는 경로를 없앤다.
⑤ **판정은 exit code**로 한다 — 출력 문자열 매칭이 아니다.
⑥ **증명 한계를 리포트가 스스로 말한다**: git author date는 클라이언트가 정하는
   값이라 위조 가능하고, git은 **장비 소유를 증명하지 않는다**. 이 한계는 옵션이
   아니라 리포트 본문에 항상 실린다.

리포트를 **읽는** 경로 — `--summary-from` (2026-09-08 추가)
-----------------------------------------------------------
리포트 JSON의 신원 키는 사람의 이름·이메일이라 `Claude <…>`와 `claude <…>`가
공존할 수 있다. Windows PowerShell 5.1의 `ConvertFrom-Json`은 객체 키를 대소문자
**무시**로 다뤄 이런 JSON을 통째로 거부한다(`DuplicateKeysInJsonString`). 키를
우리가 통제할 수 없으므로 **소비 경로를 준다**: `--summary-from <report.json>`은
git을 건드리지 않고 리포트를 읽어 평면 `KEY=VALUE`만 낸다.

exit code
    0 — 수집 성공 · 신원 혼입 없음
    1 — 수집 성공 · 주의 항목 있음(혼입 또는 지정 임계 초과)
    2 — 수집 자체가 불가 — "이상 없음"으로 읽지 말 것

    `--summary-from` 모드에서는
    0 — 리포트를 읽었고 게이트 clear의 기계 조건 충족 (`CLEAR_READY=1`)
    1 — 읽었으나 조건 미충족 — 사유는 `CLEAR_BLOCKERS`. **신원 혼입(IDENT-01)도
        여기 포함**된다: 생성 명령이 exit 1을 낸 리포트로 게이트가 닫히면
        재직사 계정이 이력에 있는 채로 "귀속 분리 확보"가 선언된다
    2 — **읽기 자체가 불가** — 값을 한 줄도 내지 않는다(실패가 값으로 위장되지 않게)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 상수 ──────────────────────────────────────────────────────────────────
GIT_TIMEOUT = 300  # ④ git log 스트림 전체 마감(초)

# KST는 **고정 오프셋**으로 다룬다. `zoneinfo`를 쓰면 Windows에서 tzdata 패키지가
# 없을 때 ZoneInfoNotFoundError로 죽는데, 한국은 1988년 이후 서머타임이 없어
# +09:00 고정이 정확하다 — 의존성을 늘리지 않고 같은 값을 얻는다.
KST = timezone(timedelta(hours=9), "KST")

# 레코드·필드 구분자. 커밋 제목·본문에 개행이 들어와도 파싱이 깨지지 않게 ASCII
# 제어문자를 쓴다(git이 %x1e/%x1f로 그대로 출력한다).
_RS = "\x1e"
_FS = "\x1f"
# **소문자 `%ae`/`%ce`를 쓴다 — 대문자 `%aE`/`%cE`는 `.mailmap`이 적용된 값이다.**
# 2026-09-07 실측: 저장소에 `개인 <kiki@ex.com> 사내계정 <worker@employer.co.kr>`
# 한 줄만 있으면 `%aE`는 재직사 커밋을 개인 이메일로 출력한다 — 귀속 증빙 도구가
# 정확히 잡아야 할 것을 못 보고 "혼입 0종"으로 exit 0을 낸다. 이름도 같은 이유로
# 원본(`%an`/`%cn`)을 쓴다(`%aN`/`%cN`이 매핑본).
_FIELDS = ("%H", "%an", "%ae", "%cn", "%ce", "%aI", "%cI", "%s", "%b")
_FORMAT = _FS.join(_FIELDS) + _RS

# 기본 스캔 범위 — 모든 ref. HEAD만 보면 미머지 브랜치의 커밋이 통째로 빠진다.
DEFAULT_REVS = ("--all",)

# 사람이 아니라 **플랫폼·도구**가 쓰는 신원. 혼입(IDENT-01)이 아니라 별도 집계
# 대상이다. `noreply@github.com`은 GitHub 웹 머지의 서버 서명이고,
# `noreply@anthropic.com`은 Claude Code가 저작한 커밋이다.
DEFAULT_TOOL_IDENTITIES = (
    "noreply@github.com",
    "noreply@anthropic.com",
    "actions@github.com",
    # 빌드 하네스 봇. 2026-09-07 실측: 이 신원의 932건은 **전부**
    # `origin/harness-claims`(claim 대장 orphan 브랜치)에만 있고, 그 브랜치의
    # 트리는 `claims/` 하나뿐이다 — 소스가 아니라 기계가 쓰는 장부다.
    # 사람이 아니므로 혼입(IDENT-01)이 아니라 도구로 분류한다. 숨기는 것이
    # 아니다: 리포트 §1의 신원 표에 건수와 함께 그대로 실린다.
    "harness@whymath.invalid",
)

# 업무시간 정의 — 평일 09:00~18:00 (KST). 법적 정의가 아니라 실사에서 질문받는
# 구간의 관용적 근사다. `--work-hours`로 바꿀 수 있다.
WORK_START, WORK_END = 9, 18

# `Co-Authored-By: 이름 <메일>` 트레일러. git은 대소문자를 가리지 않으므로
# 검사도 가리지 않는다.
_COAUTHOR_RE = re.compile(
    r"^\s*co-authored-by\s*:\s*(?P<name>.*?)\s*<(?P<email>[^>]+)>\s*$",
    re.IGNORECASE | re.MULTILINE,
)

PRESCRIPTION = {
    "IDENT-01": (
        "해당 커밋의 신원을 확인하고, 재직사 계정·도메인이면 " "귀속 정리 전에 변호사와 상의한다"
    ),
    "TIME-01": "업무시간 커밋의 사유(휴가·연차·재량근무 등)를 확인서에 사실대로 적는다",
}


class EvidenceError(RuntimeError):
    """수집 실패 — 메시지에 **예외 타입명**을 담는다(②)."""


@dataclass
class Commit:
    """커밋 1건의 귀속 관련 메타데이터."""

    sha: str
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    author_date: str  # ISO8601 (오프셋 포함 — 원본 그대로)
    commit_date: str
    subject: str
    # `Co-Authored-By` 트레일러의 (이름, 이메일) 쌍. 공동저작자는 잠재적 공동
    # 권리자이므로 신원 검사(IDENT-01)와 AI 집계(AI-01) 양쪽에 들어간다.
    coauthors: list = field(default_factory=list)


@dataclass
class Finding:
    code: str
    subject: str
    detail: str
    prescription: str = ""

    def __post_init__(self) -> None:
        self.prescription = PRESCRIPTION.get(self.code, "")


@dataclass
class Report:
    status: str  # ok | shallow | error
    message: str = ""
    total_commits: int = 0
    # 무엇을 스캔했는가. `is_full_history=False`면 이 리포트는 전수가 아니다.
    scope: dict = field(default_factory=dict)
    identities: dict = field(default_factory=dict)
    environments: dict = field(default_factory=dict)
    # 사람이 저작한 커밋만의 시각 분포 — "개인 시간 작업" 질문에 답하는 축.
    time_profile: dict = field(default_factory=dict)
    # 스캔한 전체(도구 커밋 포함) 시각 분포 — 감추지 않기 위해 함께 싣는다.
    time_profile_all_scanned: dict = field(default_factory=dict)
    ai_profile: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    # 재지 못한 축. 비어 있지 않으면 이 리포트는 **부분 측정**이다.
    unmeasured: list = field(default_factory=list)
    generated_at: str = ""
    head_sha: str = ""  # 체크아웃의 HEAD — 확인서 §1의 "기준 커밋"


# ── git I/O ───────────────────────────────────────────────────────────────
def _git(root: Path, *args: str, timeout: int = 60) -> str:
    """git 1회 호출. 실패를 삼키지 않고 타입명과 함께 올린다(②)."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            # HARN-19 — 로케일 인코딩 디코드 금지. Kiki 머신(한국어 Windows)은
            # cp949라 한글 커밋 제목에서 붕괴한다. git 출력은 UTF-8이다.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise EvidenceError(f"TimeoutExpired: git {args[0]} — {timeout}s 초과") from exc
    except OSError as exc:  # git 미설치·권한
        raise EvidenceError(f"{type(exc).__name__}: {exc}") from exc
    if proc.returncode != 0:
        raise EvidenceError(
            f"GitExitError({proc.returncode}): git {args[0]} — {proc.stderr.strip()[:200]}"
        )
    return proc.stdout


def is_shallow(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-shallow-repository").strip() == "true"


def count_refs(root: Path) -> int:
    """스캔 범위에 들어오는 ref 수 — 리포트에 남겨 범위를 감사 가능하게 한다."""
    out = _git(root, "for-each-ref", "--format=%(refname)")
    return len([line for line in out.splitlines() if line.strip()])


def stream_commits(
    root: Path,
    *,
    revs=DEFAULT_REVS,
    since: str | None = None,
    jsonl: Path | None = None,
    timeout: int = GIT_TIMEOUT,
):
    """커밋을 **스트리밍**하며 하나씩 내놓는다. `jsonl`이 있으면 즉시 flush(③).

    `subprocess.run`으로 한 번에 받지 않는 이유: 이력이 크거나 중간에 죽었을 때
    아무것도 남지 않으면 그 실행은 정보가 아니라 낭비다. 스트림으로 읽으면서
    바로 기록하면 죽은 지점까지는 증거가 남는다.

    타임아웃은 **watchdog 스레드**가 건다(④). 블로킹 `read()` 뒤에서만 마감을
    검사하면, git이 출력 없이 멈춘 경우 그 검사 지점에 영영 도달하지 못한다.
    stderr는 파이프가 아니라 임시 파일로 받는다 — 파이프가 가득 차 교착되는
    경로 자체를 없앤다.
    """
    args = ["git", "log", f"--format={_FORMAT}"]
    if since:
        args.append(f"--since={since}")
    args.extend(revs)

    errfile = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            args,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=errfile,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        errfile.close()
        raise EvidenceError(f"{type(exc).__name__}: git log 기동 실패 — {exc}") from exc

    timed_out = threading.Event()

    def _on_timeout() -> None:
        # watchdog 스레드가 호출한다. 여기서는 깨우기만 하고, 실제 수거는
        # `finally`의 `_reap(proc)`이 단일 경로로 처리한다.
        timed_out.set()
        proc.kill()

    watchdog = threading.Timer(timeout, _on_timeout)
    watchdog.daemon = True
    watchdog.start()

    # 증거 sink는 **부모 디렉터리째** 만든다. 없으면 FileNotFoundError가 그대로
    # 올라와 수집 전체가 죽는데, "증거를 남기려다 증거를 못 만드는" 실패다.
    sink = None
    if jsonl:
        try:
            jsonl.parent.mkdir(parents=True, exist_ok=True)
            sink = jsonl.open("w", encoding="utf-8")
        except OSError as exc:
            watchdog.cancel()
            _reap(proc)
            errfile.close()
            raise EvidenceError(f"{type(exc).__name__}: jsonl 생성 실패 — {exc}") from exc

    buf = ""
    try:
        assert proc.stdout is not None
        for chunk in iter(lambda: proc.stdout.read(8192), ""):
            buf += chunk
            while _RS in buf:
                raw, buf = buf.split(_RS, 1)
                commit = _parse_record(raw)
                if commit is None:
                    continue
                if sink:  # ③ 커밋 1건마다 즉시 flush
                    sink.write(json.dumps(asdict(commit), ensure_ascii=False) + "\n")
                    sink.flush()
                yield commit
        proc.wait(timeout=10)
        if timed_out.is_set():
            raise EvidenceError(f"TimeoutExpired: git log — {timeout}s 초과")
        if proc.returncode != 0:
            errfile.seek(0)
            stderr = errfile.read().strip()[:200]
            raise EvidenceError(f"GitExitError({proc.returncode}): git log — {stderr}")
    except subprocess.TimeoutExpired as exc:
        raise EvidenceError("TimeoutExpired: git log 종료 대기 초과") from exc
    finally:
        # 정상 종료·조기 close()·jsonl 실패가 **같은 정리 경로**를 지난다.
        # kill만 하고 wait하지 않으면 POSIX에서 자식이 zombie로 남고 종료 자체도
        # 확정되지 않는다(2026-09-07 리뷰 지적). stdout을 먼저 닫아 write end가
        # 막힌 프로세스가 깨어나게 한 뒤 kill → wait 순서로 반드시 거둔다.
        watchdog.cancel()
        _reap(proc)
        if sink:
            sink.close()
        errfile.close()


def _reap(proc) -> None:
    """자식 프로세스를 확실히 종료·수거한다. **모든 종료 경로의 단일 출구**.

    `kill()`만으로는 부족하다 — 커널이 프로세스를 정리해도 파이썬이 `wait()`을
    하지 않으면 zombie 항목이 남고, 그것은 이후 다른 `subprocess` 호출이나 GC
    시점까지 따라다닌다. 예외를 올리지 않는다: 이 함수는 `finally`에서만 불리며,
    여기서 터지면 **원래 실패 원인을 덮어쓴다**.
    """
    try:
        if proc.stdout is not None:
            proc.stdout.close()
    except OSError:
        pass
    try:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _parse_record(raw: str) -> Commit | None:
    """레코드 1건 파싱. 필드 수가 안 맞으면 **조용히 버리지 않고** None을 낸다."""
    # maxsplit을 걸어 본문(%b) 안의 제어문자가 필드를 밀지 않게 한다.
    fields = raw.lstrip("\n").split(_FS, len(_FIELDS) - 1)
    if len(fields) != len(_FIELDS):
        return None
    *head, body = fields
    return Commit(*head, coauthors=parse_coauthors(body))


def parse_coauthors(body: str) -> list:
    """커밋 본문 → `Co-Authored-By` (이름, 이메일) 목록. **순수 함수**.

    git의 `%(trailers:key=...)` 대신 본문을 직접 파싱한다 — 그 포맷 지시자는
    git 2.22+가 필요하고, Kiki 머신·러너의 git 버전에 판정이 종속되면 "환경에
    따라 다른 수치가 나오는 증빙"이 된다.
    """
    return [[m.group("name"), m.group("email")] for m in _COAUTHOR_RE.finditer(body)]


# ── 순수 판정 로직 (git 없이 테스트 가능) ──────────────────────────────────
def _norm(email: str) -> str:
    return email.strip().lower()


def classify_identities(commits, personal, tool):
    """신원 분포 + 혼입 신호(IDENT-01). **순수 함수** — I/O 없음.

    판정을 git 호출에서 분리한 이유: 저장소 상태 없이 임계 동작을 양방향으로
    동결할 수 있어야 한다 — 정상 상태에서 침묵하고 결함 상태에서 발화하는지
    ("변별력 없는 검증 스텝 금지").

    author·committer·**coauthor 셋 다** 본다. 재직사 계정이 committer로만 찍힌
    커밋도, `Co-Authored-By`로만 등장하는 사람도 귀속 다툼의 입구다 — 공동저작자는
    잠재적 공동 권리자이므로 실사에서 가장 늦게 발견되면 가장 비싸다.
    """
    personal = {_norm(e) for e in personal}
    tool = {_norm(e) for e in tool}

    by_author = Counter(f"{c.author_name} <{c.author_email}>" for c in commits)
    by_committer = Counter(f"{c.committer_name} <{c.committer_email}>" for c in commits)
    by_coauthor = Counter(f"{name} <{email}>" for c in commits for name, email in c.coauthors)

    foreign: dict = {}
    for c in commits:
        roles = [
            ("author", c.author_name, c.author_email),
            ("committer", c.committer_name, c.committer_email),
        ]
        roles += [("coauthor", name, email) for name, email in c.coauthors]
        for role, name, email in roles:
            key = _norm(email)
            if key in personal or key in tool:
                continue
            foreign.setdefault(f"{role}:{name} <{email}>", []).append(c.sha[:12])

    findings = [
        Finding(
            "IDENT-01",
            ident,
            f"선언된 개인·도구 신원 밖 — {len(shas)}건 (예: {', '.join(shas[:5])})",
        )
        for ident, shas in sorted(foreign.items())
    ]

    profile = {
        "declared_personal": sorted(personal),
        "declared_tool": sorted(tool),
        "by_author": dict(by_author.most_common()),
        "by_committer": dict(by_committer.most_common()),
        "by_coauthor": dict(by_coauthor.most_common()),
        "foreign_identities": {k: len(v) for k, v in sorted(foreign.items())},
    }
    return profile, findings


def environment_profile(commits) -> dict:
    """author 타임존 오프셋 분포 — ENV-01.

    **판정이 아니라 분포다.** 오프셋 `+09:00`은 KST 로컬 작업 환경을, 그 외는
    다른 환경(클라우드 세션 컨테이너·CI 러너 등)을 시사한다. 이 도구는 "전부
    개인 장비"를 대신 주장해 주지 않는다 — 실제로 이 저장소의 이력에는 여러
    오프셋이 섞여 있고, 그것을 감추는 리포트는 실사에서 더 나쁘다.
    """
    offsets = Counter()
    for c in commits:
        offsets[_offset_label(_parse_iso(c.author_date))] += 1
    return {
        "by_author_utc_offset": dict(offsets.most_common()),
        "local_kst_commits": offsets.get("+09:00", 0),
        "non_kst_commits": sum(v for k, v in offsets.items() if k != "+09:00"),
    }


def time_profile(commits, *, work_start: int = WORK_START, work_end: int = WORK_END) -> dict:
    """KST 기준 요일·시각 히스토그램과 평일 업무시간 비율 — TIME-01.

    **모든 커밋을 KST로 환산해서** 센다. 오프셋이 섞인 이력에서 현지시각을 그대로
    세면 서로 다른 벽시계를 한 히스토그램에 합치는 셈이라 무의미하다.
    """
    hours = Counter()
    weekdays = Counter()
    work_hours = 0
    for c in commits:
        kst = _parse_iso(c.author_date).astimezone(KST)
        hours[kst.hour] += 1
        weekdays[kst.weekday()] += 1  # 0=월 … 6=일
        if kst.weekday() < 5 and work_start <= kst.hour < work_end:
            work_hours += 1
    total = len(commits)
    return {
        "timezone": "KST(+09:00 고정)",
        "work_hours_definition": f"평일 {work_start:02d}:00~{work_end:02d}:00",
        "by_hour_kst": {str(h): hours.get(h, 0) for h in range(24)},
        "by_weekday_kst": {
            n: weekdays.get(i, 0) for i, n in enumerate(["월", "화", "수", "목", "금", "토", "일"])
        },
        "work_hours_commits": work_hours,
        "off_hours_commits": total - work_hours,
        "work_hours_ratio": round(work_hours / total, 4) if total else 0.0,
    }


def person_authored(commits, tool):
    """author가 도구 신원이 **아닌** 커밋만 — 시각 분포의 모집단. **순수 함수**.

    봇·AI가 author인 커밋의 시각은 그 프로세스가 돈 시각이지 사람이 일한 시각이
    아니다. 그것을 근무시간 분포에 넣으면 "개인 시간에 작업했는가"라는 질문에
    기계의 스케줄이 답한다.
    """
    tool = {_norm(e) for e in tool}
    return [c for c in commits if _norm(c.author_email) not in tool]


def ai_profile(commits, tool) -> dict:
    """AI 도구 신원의 저작 관여 집계 — AI-01 (정보 축, 판정 아님).

    author만 세면 크게 빗나간다(2026-09-07 실측: author 25건 vs `Co-Authored-By`
    998건). 이 저장소의 관례는 사람이 author이고 AI가 **공동저작자 트레일러**로
    들어가는 형태라, 트레일러를 빼면 AI 관여를 40배 과소계상한다.
    """
    tool = {_norm(e) for e in tool}
    authored = [c for c in commits if _norm(c.author_email) in tool]
    coauthored = [c for c in commits if any(_norm(email) in tool for _, email in c.coauthors)]
    involved = {c.sha for c in authored} | {c.sha for c in coauthored}
    total = len(commits)
    return {
        "tool_authored_commits": len(authored),
        "tool_coauthored_commits": len(coauthored),
        "tool_involved_commits": len(involved),
        "tool_involved_ratio": round(len(involved) / total, 4) if total else 0.0,
        "by_tool_identity": dict(
            Counter(f"{c.author_name} <{c.author_email}>" for c in authored).most_common()
        ),
        "note": (
            "AI 생성물의 저작권 귀속은 겸직 귀속과 별개의 쟁점이다 — "
            "이 수치는 실사 질문에 대비한 사실 자료이지 판정이 아니다."
        ),
    }


def _parse_iso(value: str) -> datetime:
    """git `%aI`(strict ISO8601) 파싱. 실패는 타입명과 함께 올린다(②)."""
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceError(f"ValueError: author date 파싱 실패 — {value!r}") from exc


def _offset_label(dt: datetime) -> str:
    off = dt.utcoffset() or timedelta(0)
    total = int(off.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


def evaluate_thresholds(time_prof: dict, *, work_hours_threshold) -> list:
    """임계 판정 — 임계를 **준 사람에게만** 신호를 낸다.

    기본값으로 숫자를 박지 않는 이유: 업무시간 커밋 비율에는 법적 임계가 없다.
    임의의 기본 임계는 근거처럼 읽히면서 실제로는 아무것도 재지 않는다
    ("측정 없는 기계 게이트를 인간 검수 대체로 선언 금지"의 같은 축).
    """
    if work_hours_threshold is None:
        return []
    ratio = time_prof.get("work_hours_ratio", 0.0)
    if ratio <= work_hours_threshold:
        return []
    scanned = time_prof.get("work_hours_commits", 0) + time_prof.get("off_hours_commits", 0)
    return [
        Finding(
            "TIME-01",
            "평일 업무시간 커밋 비율",
            f"{ratio:.1%} > 임계 {work_hours_threshold:.1%} "
            f"({time_prof.get('work_hours_commits')}건 / 스캔 {scanned}건)",
        )
    ]


def build_scope(revs, since: str | None, *, refs: int, scanned: int) -> dict:
    """이 실행이 **무엇을 봤는지** 기록한다. **순수 함수**.

    `is_full_history`가 False인 리포트는 "이력 전체" 문구를 쓸 자격이 없다.
    범위를 좁힌 실행의 "혼입 0건"이 저장소 전체의 진술로 읽히면, 좁힌 사실
    자체가 증빙을 거짓으로 만든다.
    """
    revs = list(revs)
    full = revs == ["--all"] and not since
    return {
        "revs": revs,
        "since": since,
        "refs_in_repo": refs,
        "commits_scanned": scanned,
        "is_full_history": full,
        "description": (
            f"저장소의 모든 ref({refs}개) 전수"
            if full
            else f"부분 범위 — revs={revs}" + (f", since={since}" if since else "")
        ),
    }


# ── 수집 ──────────────────────────────────────────────────────────────────
def collect(
    root: Path,
    *,
    personal,
    tool,
    revs=DEFAULT_REVS,
    since: str | None = None,
    jsonl: Path | None = None,
    work_start: int = WORK_START,
    work_end: int = WORK_END,
    work_hours_threshold=None,
) -> Report:
    """이력을 훑어 리포트를 만든다. 실패는 status로 구분한다(①)."""
    now = datetime.now(timezone.utc).isoformat()
    if not personal:
        # 누가 '개인'인지 선언하지 않으면 혼입 판정 자체가 성립하지 않는다.
        # 빈 allowlist로 돌리면 **모든 신원이 혼입**으로 잡혀 리포트가 무의미해진다.
        return Report(
            status="error",
            message="개인 신원 미선언 — --identity 를 1개 이상 지정해야 한다",
            generated_at=now,
        )
    try:
        if is_shallow(root):
            # shallow에서 "혼입 0건"은 잘린 이력에 대한 참일 뿐 저장소에 대한
            # 참이 아니다. 증빙 문서에 실리면 그대로 거짓 진술이 된다.
            return Report(
                status="shallow",
                message=(
                    "shallow 클론 — 이력이 잘려 있어 신원 혼입 판정이 성립하지 않는다. "
                    "`git fetch --unshallow origin` 후 재실행"
                ),
                generated_at=now,
            )
        head = _git(root, "rev-parse", "HEAD").strip()
        refs = count_refs(root)
        commits = list(stream_commits(root, revs=revs, since=since, jsonl=jsonl))
    except EvidenceError as exc:
        return Report(status="error", message=str(exc), generated_at=now)

    scope = build_scope(revs, since, refs=refs, scanned=len(commits))
    scope["person_authored"] = len(person_authored(commits, tool))
    if not commits:
        # 스캔 0건은 성공이 아니다 — 대상을 하나도 못 찾은 전수 가드는 공허하게
        # 통과한다(CLAUDE.md "스캔 0건은 실패").
        return Report(
            status="error",
            message=f"커밋 0건 — 수집 대상이 없다 ({scope['description']})",
            generated_at=now,
            head_sha=head,
            scope=scope,
        )

    idents, findings = classify_identities(commits, personal, tool)
    # **시각 분포는 사람이 저작한 커밋만 센다.** 하네스 봇의 장부 커밋 932건이
    # 섞이면 "개인 시간에 작업했는가"라는 질문에 봇의 실행 시각이 답하게 된다
    # (2026-09-07 실측: 전체 기준 35.4% vs 사람 저작 기준은 다른 값). 감추지는
    # 않는다 — 전체 스캔분도 `time_profile_all_scanned`로 함께 싣는다.
    people = person_authored(commits, tool)
    times = time_profile(people, work_start=work_start, work_end=work_end)
    times_all = time_profile(commits, work_start=work_start, work_end=work_end)
    findings += evaluate_thresholds(times, work_hours_threshold=work_hours_threshold)
    unmeasured = []
    if not scope["is_full_history"]:
        unmeasured.append(f"범위 밖 커밋({scope['description']})")
    return Report(
        status="ok",
        total_commits=len(commits),
        scope=scope,
        identities=idents,
        environments=environment_profile(commits),
        time_profile=times,
        time_profile_all_scanned=times_all,
        ai_profile=ai_profile(commits, tool),
        findings=findings,
        unmeasured=unmeasured,
        generated_at=now,
        head_sha=head,
    )


# ── 렌더 ──────────────────────────────────────────────────────────────────
# 증명 한계. **옵션이 아니다** — 리포트를 읽는 사람(투자 실사자·변호사)이
# git 메타데이터의 증명력을 과대평가하지 않도록 항상 함께 실린다(⑥).
LIMITS = [
    "**author date는 위조 가능하다** — git의 author/commit 시각은 커밋을 만든 "
    "클라이언트가 정하는 값이며 서버가 검증하지 않는다. 시각 증거로 단독 사용할 수 "
    "없고, GitHub 서버가 기록하는 push 이벤트·PR 머지 시각으로 보강해야 한다.",
    "**git은 장비 소유를 증명하지 않는다** — 타임존 오프셋은 커밋이 만들어진 "
    "환경의 시간대일 뿐 장비의 소유자가 아니다. 개인 장비 증빙은 구매 영수증·"
    "기기 일련번호 등 저장소 밖 자료로 별도 확보한다.",
    "**계정 귀속은 정황 증거다** — 개인 이메일·개인 GitHub 계정으로 커밋됐다는 "
    "사실은 재직사 계정 무사용의 정황이지, 재직사 자산·데이터 무사용의 증명이 "
    "아니다. 그 축은 게이트 ②(자체 확인서)가 담당한다.",
    "**이 리포트는 이 클론이 가진 ref만 본다** — 원격에만 있고 fetch되지 않은 "
    "브랜치는 스캔 범위 밖이다. `git fetch --all` 후 실행하고, 리포트 §0의 ref "
    "수가 원격 브랜치 수와 맞는지 확인한다.",
    "**이 리포트는 판정하지 않는다** — 귀속의 법적 판단은 변호사·본인 몫이며, "
    "여기 실린 것은 사실 자료뿐이다.",
]


def render(report: Report, *, root_name: str = "WhyMath") -> str:
    """실사 제출용 Markdown. 한계(⑥)를 본문에 항상 싣는다."""
    out = [
        f"# IP 귀속 분리 증빙 — 커밋 신원·시각 실측 ({root_name})",
        "",
        f"- 생성 시각(UTC): `{report.generated_at}`",
        f"- 기준 커밋(HEAD): `{report.head_sha or '미측정'}`",
        f"- 상태: **{report.status}**",
    ]
    if report.status != "ok":
        out += [
            "",
            f"> ⛔ **수집 실패** — {report.message}",
            "",
            "> 이 상태의 리포트를 증빙으로 쓰지 말 것. 수집 실패는 '이상 없음'이 아니다.",
        ]
        return "\n".join(out)

    scope = report.scope
    out += [
        f"- 총 커밋: **{report.total_commits}건**",
        "",
        "## 0. 스캔 범위",
        "",
        f"- 범위: **{scope.get('description', '미기록')}**",
        f"- 이 클론의 ref 수: {scope.get('refs_in_repo', '미측정')}",
        f"- 전수 여부: **{'전수' if scope.get('is_full_history') else '부분 측정'}**",
        "",
    ]
    if report.unmeasured:
        out += [
            f"> ⚠ **부분 측정** — 재지 못한 축: {', '.join(report.unmeasured)}",
            ">",
            "> 아래 수치는 **스캔한 범위 안에서만** 참이다. 저장소 전체에 대한 진술로",
            "> 읽지 말 것.",
            "",
        ]

    scanned = f"스캔한 {report.total_commits}건"
    out += ["## 1. 신원 (IDENT-01)", ""]
    out += [f"- 선언된 개인 신원: {', '.join(report.identities['declared_personal'])}"]
    out += [f"- 선언된 도구 신원: {', '.join(report.identities['declared_tool'])}", ""]
    out += ["| 역할 | 신원 | 커밋 수 |", "|---|---|---|"]
    for role, key in (
        ("author", "by_author"),
        ("committer", "by_committer"),
        ("coauthor", "by_coauthor"),
    ):
        for ident, n in report.identities.get(key, {}).items():
            out.append(f"| {role} | `{ident}` | {n} |")
    foreign = report.identities["foreign_identities"]
    out += [
        "",
        (
            f"**혼입 신원: {len(foreign)}종** — "
            + (
                "선언 밖 신원이 발견됐다. 아래 §5를 확인할 것."
                if foreign
                else f"{scanned}에서 선언된 개인·도구 신원 외의 계정은 발견되지 않았다."
            )
        ),
        "",
    ]

    env = report.environments
    out += [
        "## 2. 작업 환경 (ENV-01)",
        "",
        "author 타임존 오프셋 분포. **판정이 아니라 분포다** — 오프셋은 커밋이 만들어진",
        "환경의 시간대이지 장비의 소유자가 아니다.",
        "",
        "| UTC 오프셋 | 커밋 수 |",
        "|---|---|",
    ]
    out += [f"| `{k}` | {v} |" for k, v in env["by_author_utc_offset"].items()]
    out += [
        "",
        f"- KST(+09:00) 환경: **{env['local_kst_commits']}건**",
        f"- 그 외 환경: **{env['non_kst_commits']}건** "
        "(클라우드 세션 컨테이너·CI 러너 등 — 재직사 장비를 뜻하지 않으며, 그 반대도 아니다)",
        "",
    ]

    tp = report.time_profile
    tpa = report.time_profile_all_scanned
    person_n = tp["work_hours_commits"] + tp["off_hours_commits"]
    out += [
        "## 3. 시각 분포 (TIME-01)",
        "",
        f"**모집단: 사람이 저작한 커밋 {person_n}건** — author가 도구 신원(하네스 봇·"
        "AI)인 커밋은 제외했다. 봇이 커밋한 시각은 그 프로세스가 돈 시각이지 사람이",
        '일한 시각이 아니므로, 섞으면 "개인 시간에 작업했는가"라는 질문에 기계의',
        "스케줄이 답한다.",
        "",
        f"- 기준 시간대: {tp['timezone']} (모든 커밋을 KST로 환산해 집계)",
        f"- 업무시간 정의: {tp['work_hours_definition']}",
        f"- 업무시간 커밋: **{tp['work_hours_commits']}건** ({tp['work_hours_ratio']:.1%})",
        f"- 업무시간 외 커밋: **{tp['off_hours_commits']}건** "
        f"({1 - tp['work_hours_ratio']:.1%})",
        "",
        f"> 참고 — 스캔한 전체 {report.total_commits}건(도구 커밋 포함) 기준으로는 "
        f"업무시간 {tpa.get('work_hours_commits', 0)}건"
        f"({tpa.get('work_hours_ratio', 0):.1%})이다. 감추지 않기 위해 병기한다.",
        "",
        "| 요일(KST) | 커밋 수 |",
        "|---|---|",
    ]
    out += [f"| {k} | {v} |" for k, v in tp["by_weekday_kst"].items()]
    out += ["", "| 시각(KST) | 커밋 수 |", "|---|---|"]
    out += [f"| {int(k):02d}시 | {v} |" for k, v in tp["by_hour_kst"].items()]

    ap = report.ai_profile
    out += [
        "",
        "## 4. AI 저작 커밋 (AI-01 · 정보 축)",
        "",
        f"- 도구 신원이 author: **{ap['tool_authored_commits']}건**",
        f"- 도구 신원이 Co-Authored-By: **{ap['tool_coauthored_commits']}건**",
        f"- 둘 중 하나라도 해당(합집합): **{ap['tool_involved_commits']}건** "
        f"({ap['tool_involved_ratio']:.1%})",
        f"- {ap['note']}",
        "",
    ]

    out += ["## 5. 신호", ""]
    if report.findings:
        out += ["| 코드 | 대상 | 상세 | 처방 |", "|---|---|---|---|"]
        out += [
            f"| {f['code'] if isinstance(f, dict) else f.code} "
            f"| {f['subject'] if isinstance(f, dict) else f.subject} "
            f"| {f['detail'] if isinstance(f, dict) else f.detail} "
            f"| {f['prescription'] if isinstance(f, dict) else f.prescription} |"
            for f in report.findings
        ]
    else:
        out.append(f"신호 없음 — {scanned}에서 선언된 신원 밖 커밋이 발견되지 않았다.")

    out += ["", "## 6. 이 증거가 증명하지 **못하는** 것", ""]
    out += [f"{i}. {line}" for i, line in enumerate(LIMITS, 1)]
    out += [
        "",
        "---",
        "",
        "본 리포트는 게이트 `G-eos-ip-separation-evidence`의 **①번 축**(개인 계정·시각 "
        "증빙)만 담당한다. ②(재직사 자산·데이터 무사용 확인서)와 ③(신설 법인 IP 양도 "
        "예정 기록)은 사람의 의사표시라 기계가 대체하지 않는다 — "
        "`docs/legal/templates/` 참조.",
        "",
    ]
    return "\n".join(out)


# ── 서명 실물 유출 가드 ────────────────────────────────────────────────────
# 게이트 ②③의 **기입된 실물**에는 재직사명·서명이 들어가므로 저장소에 남길
# 성질의 문서가 아니다. 1차 방어는 `.gitignore`이지만 `git add -f` 한 번이면
# 뚫리므로, 추적된 파일을 실제로 훑는 2차 가드를 둔다.
#
# **두 갈래로 본다** (2026-09-07 리뷰 지적 반영):
#   ① Markdown은 **첫 줄 마커**로 본다. "이 문자열이 어디든 들어 있으면 위반"
#      형태로 만들면 마커를 *설명하는* 문서(런북·이 파일 자신)가 전부 위반이 되고,
#      그 오탐을 면제하기 시작하면 가드가 스스로 구멍이 된다(CLAUDE.md
#      "금지 패턴 열거 대신 산출물 검사" — 위치가 곧 산출물이다).
#   ② 서명 **스캔본**(PDF·이미지)은 첫 줄을 읽을 수 없다. 런북이 "스캔하거나
#      PDF로 저장"을 안내하므로 그 경로가 비어 있으면 가드가 절반만 존재하는
#      셈이다. 그래서 *파일명*과 *확장자·위치*로 본다.
SIGNED_MARKER = "<!-- IP-SEP-DOC: signed -->"
TEMPLATE_MARKER = "<!-- IP-SEP-DOC: template -->"

# 런북이 지시하는 실물 파일명(확장자 무관). 이름을 바꿔 넣으면 이 가드는 뚫린다 —
# 그것이 이 가드의 한계이며, 1차 방어는 "저장소 밖 보관"이라는 런북 지시다.
SIGNED_NAME_HINTS = (
    "재직사자산무사용확인서",
    "ip양도예정기록",
    "no_employer_assets_declaration_signed",
    "ip_assignment_intent_record_signed",
)
# 서명 스캔본이 놓일 수 있는 형식. 법무 문서 폴더에는 이런 바이너리가 없어야 한다.
SCAN_SUFFIXES = (".pdf", ".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff")
# 그 규칙을 적용할 경로 — 좁게 잡는다. 저장소 전체에 걸면 정상 자산까지 잡는다.
SCAN_GUARDED_PREFIXES = ("docs/legal/",)


def marker_of(first_line: str):
    """첫 줄 → 마커 종류. **순수 함수** — I/O 없음."""
    line = first_line.strip()
    if line == SIGNED_MARKER:
        return "signed"
    if line == TEMPLATE_MARKER:
        return "template"
    return None


def looks_like_signed_binary(rel_path: str):
    """추적 경로 → 서명 실물 의심 사유(없으면 None). **순수 함수**.

    첫 줄을 읽을 수 없는 형식(스캔본)을 이름과 위치로 본다.
    """
    lowered = rel_path.lower()
    name = lowered.rsplit("/", 1)[-1]
    for hint in SIGNED_NAME_HINTS:
        if hint in name:
            return f"서명 실물 파일명 패턴 '{hint}'"
    if name.endswith(SCAN_SUFFIXES) and lowered.startswith(SCAN_GUARDED_PREFIXES):
        return f"법무 문서 경로의 스캔본 형식({name.rsplit('.', 1)[-1]})"
    return None


def scan_tracked_documents(root: Path) -> dict:
    """git이 **추적 중인** 파일에서 서명 실물 흔적을 찾는다.

    작업 트리 전체가 아니라 `git ls-files`를 쓰는 이유: 가드가 막으려는 것은
    "커밋된 서명 실물"이지 로컬에 놓인 초안이 아니다. 무시된 파일까지 훑으면
    사용자가 `docs/private/`에 정상적으로 보관한 실물이 위반으로 잡힌다.
    """
    out: dict = {"signed": [], "template": [], "signed_binary": [], "unreadable": []}
    listing = _git(root, "ls-files", "-z")
    for rel in listing.split("\0"):
        if not rel:
            continue
        reason = looks_like_signed_binary(rel)
        if reason:
            out["signed_binary"].append(f"{rel} — {reason}")
            continue
        if not rel.lower().endswith(".md"):
            continue
        try:
            with (root / rel).open("r", encoding="utf-8", errors="replace") as fh:
                first = fh.readline()
        except OSError:
            # 읽을 수 없는 추적 파일은 **조용히 건너뛰지 않는다** — 스캔 대상에서
            # 빠졌다는 사실 자체가 가드의 구멍이므로 목록에 남긴다.
            out["unreadable"].append(rel)
            continue
        kind = marker_of(first)
        if kind:
            out[kind].append(rel)
    return out


# ── 리포트 소비 (CONSUME-01) ──────────────────────────────────────────────
#
# 왜 이 절이 있는가 (2026-09-08 라이브 실측)
# -----------------------------------------
# 이 도구는 리포트를 **잘 만들었는데 소비자가 읽지 못했다**. Kiki가 게이트
# 런북을 실행해 `EXIT=0` · 전수 2621건까지 성공했으나, 그 다음 자가검증 줄의
# `ConvertFrom-Json`이 리포트를 통째로 거부했다:
#
#     JSON 문자열에서 변환된 사전에 중복된 키 'Claude <noreply@anthropic.com>'
#     및 'claude <noreply@anthropic.com>'이(가) 포함되어 있기 때문에 …
#
# Windows PowerShell 5.1의 `ConvertFrom-Json`은 JSON 객체를 **대소문자 무시**
# 사전으로 만든다. 우리 리포트의 신원 키는 사람의 이름·이메일이라 대소문자를
# 우리가 통제할 수 없다 — 누군가 한 번 `claude`로 커밋하면 그 순간부터 이
# 저장소의 모든 리포트가 PowerShell에서 파싱 불가가 된다.
#
# 그러므로 **키를 고치는 대신 소비 경로를 준다**. `--summary-from`은 리포트를
# 파이썬으로 읽어 평면 `KEY=VALUE`로 낸다. 파이썬 dict는 대소문자를 구별하므로
# 두 신원이 각자 살아남고, PowerShell은 JSON 파서를 쓰지 않는다.
#
# 함께 고친 축: 실패가 **성공처럼 보이던 것**. 파싱이 깨진 뒤에도 런북은
# `FOREIGN=0종`을 출력했다($J가 null인데 `.PSObject.Properties.Count`가 0을
# 냈다) — "혼입 없음"으로 읽히는 화면이다. 이 모드는 읽기에 실패하면 값을
# 하나도 내지 않고 `SUMMARY_OK=0` + `REASON=<예외타입>: …`만 낸다.


def case_collision_keys(node, _path: str = "$") -> list:
    """같은 객체 안에서 **대소문자만 다른 형제 키**를 전부 찾는다.

    반환 형식: `"identities.by_coauthor: Claude <…> ~ claude <…>"` 문자열 목록.
    빈 목록이면 이 payload는 대소문자 무시 파서(PowerShell 5.1 등)에서도
    안전하다. 리포트가 자신의 소비 가능성을 **스스로 말하게** 하는 축이다.
    """
    hits: list = []
    if isinstance(node, dict):
        buckets: dict = {}
        for key in node:
            buckets.setdefault(str(key).casefold(), []).append(str(key))
        for _folded, names in buckets.items():
            if len(names) > 1:
                hits.append(f"{_path}: {' ~ '.join(sorted(names))}")
        for key, value in node.items():
            hits += case_collision_keys(value, f"{_path}.{key}" if _path != "$" else str(key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            hits += case_collision_keys(value, f"{_path}[{i}]")
    return hits


def consumption_profile(payload: dict) -> dict:
    """리포트에 실리는 소비 가능성 블록 — 소비자가 조용히 깨지지 않게."""
    collisions = case_collision_keys(payload)
    return {
        "case_collision_keys": collisions,
        "powershell_convertfrom_json_safe": not collisions,
        "safe_consumption": (
            "python scripts/ops/ip_separation_evidence.py "
            "--summary-from <report.json> [--expect-head <sha>]"
        ),
        "note": (
            "Windows PowerShell 5.1의 ConvertFrom-Json은 JSON 객체 키를 대소문자 "
            "무시로 다뤄 위 키 쌍을 중복으로 거부한다(DuplicateKeysInJsonString). "
            "이 리포트를 PowerShell에서 읽을 때는 --summary-from을 쓴다."
        ),
    }


def consumption_note(collisions: list) -> str:
    """Markdown 부록 — 충돌이 **있을 때만** 붙인다."""
    lines = [
        "",
        "## 7. 이 리포트를 읽는 방법 (CONSUME-01)",
        "",
        f"이 리포트의 JSON에는 **대소문자만 다른 키가 {len(collisions)}쌍** 있다. "
        "커밋 신원의 이름·이메일이 그대로 키가 되기 때문이며, 데이터 오류가 아니다.",
        "",
        "- Windows PowerShell 5.1의 `ConvertFrom-Json`은 이런 JSON을 "
        "**거부한다**(`DuplicateKeysInJsonString`) — 객체 키를 대소문자 무시로 "
        "다루기 때문이다.",
        "- 안전한 읽기 경로: "
        "`python scripts/ops/ip_separation_evidence.py --summary-from <report.json>`",
        "",
    ]
    lines += [f"  - `{c}`" for c in collisions[:10]]
    if len(collisions) > 10:
        lines.append(f"  - … 외 {len(collisions) - 10}쌍")
    lines.append("")
    return "\n".join(lines)


def _same_head(report_head: str, expect_head: str) -> bool:
    """짧은 sha·긴 sha를 함께 받아들이되 **7자 미만은 비교로 치지 않는다**.

    7자 미만을 접두 비교하면 우연 일치가 '같은 커밋'으로 통과한다 — 그 통과는
    다른 시점의 리포트로 게이트를 닫게 만든다.
    """
    a, b = report_head.strip().lower(), expect_head.strip().lower()
    if len(a) < 7 or len(b) < 7:
        return False
    return a.startswith(b) or b.startswith(a)


def _flat(value) -> str:
    """KEY=VALUE 한 줄에 담기게 만든다 — 줄바꿈이 섞이면 파서가 무너진다."""
    return " ".join(str(value).split())


def summary_of(payload: dict, *, expect_head: str = "") -> tuple:
    """게이트 판정에 필요한 값만 평면 추출한다. 반환: (fields, blockers).

    `blockers`가 비어 있어야 게이트 clear의 **기계 축**이 성립한다. 판정을
    런북(PowerShell)이 아니라 여기서 하는 이유: 런북의 조건식은 실패했을 때
    조용히 빈 값을 내지만, 여기서는 사유가 `CLEAR_BLOCKERS`로 나온다.
    """
    scope = payload.get("scope") or {}
    identities = payload.get("identities") or {}
    time_prof = payload.get("time_profile") or {}
    foreign = identities.get("foreign_identities") or {}

    status = str(payload.get("status", ""))
    commits = int(payload.get("total_commits") or 0)
    head = str(payload.get("head_sha") or "")
    is_full = bool(scope.get("is_full_history"))

    blockers: list = []
    if status != "ok":
        blockers.append(f"status={status or '미기록'}")
    if commits <= 0:
        blockers.append(f"commits={commits}")
    if not is_full:
        blockers.append("full_history=false")
    if expect_head:
        if not _same_head(head, expect_head):
            blockers.append(f"head_mismatch(report={head or '없음'} expect={expect_head})")

    # 신원 혼입·임계 신호는 **사람이 조사할 일**이므로 기계가 clear하지 못하게 막는다.
    # 이 축이 없으면 생성 명령이 exit 1(혼입 발견)을 낸 리포트로도 요약은 exit 0을 내
    # 게이트가 닫힌다 — 재직사 계정이 이력에 있는 채로 "귀속 분리 증빙 확보"가
    # 선언되는 것이며, 이 도구가 막으려던 실패 그 자체다 (2026-09-08 Codex P1).
    # 혼입이 오분류였다면 해소 경로는 게이트를 통과시키는 것이 아니라 그 신원을
    # `--identity`로 선언하고 다시 재는 것이다.
    findings = payload.get("findings") or []
    if foreign:
        blockers.append(f"foreign_identities={len(foreign)}")
    # IDENT-01은 위에서 이미 이름이 붙었으므로 중복 계상하지 않는다. 나머지 축
    # (예: TIME-01 임계 초과)은 코드와 함께 따로 남긴다 — 무엇이 막았는지 보이게.
    other = [
        f
        for f in findings
        if not (isinstance(f, dict) and str(f.get("code", "")).startswith("IDENT-"))
    ]
    if other:
        codes = sorted({str(f.get("code", "?")) if isinstance(f, dict) else "?" for f in other})
        blockers.append(f"findings={len(other)}({','.join(codes)})")

    fields = {
        "SUMMARY_OK": "1",
        "STATUS": _flat(status),
        "COMMITS": str(commits),
        "HEAD": _flat(head),
        "SCOPE": _flat(scope.get("description", "미기록")),
        "FULL": "1" if is_full else "0",
        "PERSON_AUTHORED": str(scope.get("person_authored", "")),
        "FOREIGN": str(len(foreign)),
        "WORK_HOURS_RATIO": _flat(time_prof.get("work_hours_ratio", "")),
        "FINDINGS": str(len(payload.get("findings") or [])),
        "CASE_COLLISIONS": str(len(case_collision_keys(payload))),
        "EXPECT_HEAD": _flat(expect_head),
        "SAME_HEAD": ("na" if not expect_head else ("1" if _same_head(head, expect_head) else "0")),
        "CLEAR_READY": "0" if blockers else "1",
        "CLEAR_BLOCKERS": _flat(" | ".join(blockers)),
    }
    return fields, blockers


def render_summary(fields: dict) -> str:
    return "\n".join(f"{k}={v}" for k, v in fields.items())


def summarize_cli(path, *, expect_head: str = "") -> int:
    """`--summary-from` 본체.

    exit 0 — 읽었고 게이트 clear의 기계 조건 충족
    exit 1 — 읽었으나 조건 미충족 (사유는 `CLEAR_BLOCKERS`)
    exit 2 — **읽기 자체가 불가** — 값이 한 줄도 나오지 않는다
    """

    def _fail(reason: str) -> int:
        # 실패할 때 값을 내지 않는 것이 이 함수의 계약이다. 'FOREIGN=0' 같은
        # 값이 실패 화면에 섞이면 그 화면은 '이상 없음'으로 읽힌다.
        print("SUMMARY_OK=0")
        print(f"REASON={_flat(reason)}")
        return 2

    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return _fail(f"{type(exc).__name__}: {exc} — 리포트 파일을 읽지 못했다")
    except UnicodeDecodeError as exc:  # pragma: no cover - 방어
        return _fail(f"{type(exc).__name__}: {exc}")
    try:
        payload = json.loads(raw)
    except ValueError as exc:  # json.JSONDecodeError 포함
        return _fail(f"{type(exc).__name__}: {exc} — 리포트 JSON이 손상됐다")
    if not isinstance(payload, dict) or "status" not in payload:
        return _fail(
            "SchemaError: 이 파일은 IP-SEP 리포트가 아니다('status' 필드 없음) — "
            "경로를 확인할 것"
        )

    fields, blockers = summary_of(payload, expect_head=expect_head)
    print(render_summary(fields))
    return 1 if blockers else 0


# ── CLI ───────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="겸직 IP 귀속 분리 증빙 생성기 (IP-SEP) — 커밋 신원·시각·환경 실측"
    )
    p.add_argument("--root", type=Path, default=Path.cwd(), help="저장소 경로")
    p.add_argument(
        "--rev",
        action="append",
        default=[],
        metavar="REV",
        help="집계 대상 리비전 (반복 지정). 기본 --all = 모든 ref 전수. "
        "좁히면 리포트가 '부분 측정'으로 표시된다",
    )
    p.add_argument("--since", help="git log --since 값 (예: '2026-01-01'). 범위를 좁힌다")
    p.add_argument(
        "--identity",
        action="append",
        default=[],
        metavar="EMAIL",
        help="개인 신원 이메일 (반복 지정). **필수** — 미지정은 exit 2",
    )
    p.add_argument(
        "--tool-identity",
        action="append",
        default=[],
        metavar="EMAIL",
        help=f"도구·플랫폼 신원 (기본: {', '.join(DEFAULT_TOOL_IDENTITIES)})",
    )
    p.add_argument(
        "--summary-from",
        type=Path,
        metavar="REPORT_JSON",
        help="이미 만든 리포트 JSON을 읽어 평면 KEY=VALUE 요약만 낸다(git 접근 없음). "
        "대소문자 무시 JSON 파서(Windows PowerShell 5.1 ConvertFrom-Json)에서 "
        "리포트가 거부되는 문제의 안전 소비 경로",
    )
    p.add_argument(
        "--expect-head",
        metavar="SHA",
        help="--summary-from과 함께: 리포트가 이 커밋을 잰 것인지 대조한다. "
        "불일치면 CLEAR_READY=0",
    )
    p.add_argument("--out", type=Path, help="리포트 저장 디렉터리 (JSON + Markdown)")
    p.add_argument("--jsonl", type=Path, help="커밋별 원자료를 즉시 flush할 경로")
    p.add_argument("--json", action="store_true", help="기계 판독 출력(stdout)")
    p.add_argument("--work-hours", default=f"{WORK_START}-{WORK_END}", metavar="H-H")
    p.add_argument(
        "--work-hours-threshold",
        type=float,
        metavar="RATIO",
        help="업무시간 커밋 비율이 이 값을 넘으면 신호(0.0~1.0). 미지정이면 판정하지 않는다",
    )
    args = p.parse_args(argv)

    # 요약 모드는 **git을 건드리지 않는다** — 이미 만든 리포트를 읽을 뿐이므로
    # shallow·네트워크·작업 트리 상태와 무관하게 성립해야 한다.
    if args.summary_from is not None:
        return summarize_cli(args.summary_from, expect_head=args.expect_head or "")

    try:
        ws, we = (int(x) for x in args.work_hours.split("-", 1))
    except ValueError:
        print("❌ --work-hours 형식 오류 — 'H-H' (예: 9-18)", file=sys.stderr)
        return 2

    report = collect(
        args.root,
        personal=set(args.identity),
        tool=set(args.tool_identity or DEFAULT_TOOL_IDENTITIES),
        revs=tuple(args.rev) if args.rev else DEFAULT_REVS,
        since=args.since,
        jsonl=args.jsonl,
        work_start=ws,
        work_end=we,
        work_hours_threshold=args.work_hours_threshold,
    )

    payload = asdict(report)
    payload["findings"] = [asdict(f) if not isinstance(f, dict) else f for f in report.findings]
    payload["limits"] = LIMITS
    payload["consumption"] = consumption_profile(payload)
    markdown = render(report, root_name=args.root.resolve().name)
    if payload["consumption"]["case_collision_keys"]:
        # 충돌이 있으면 **리포트 본문이 스스로 말한다**. 이 사실을 알리지 않으면
        # 소비자(런북·실사 담당자)는 파서가 거부할 때에야 알게 되고, 그때는
        # 이미 "도구가 고장났다"로 읽힌다.
        markdown += consumption_note(payload["consumption"]["case_collision_keys"])

    if args.out:
        # 저장 실패를 **exit 2(수집 실패)** 로 바꾼다. 그냥 두면 `OSError`가
        # 빠져나가 파이썬이 exit 1을 내는데, 이 CLI에서 1은 "수집 성공 · 혼입
        # 발견"으로 예약된 값이다 — 디스크·권한 문제가 신원 혼입으로 오분류되고,
        # 이전 실행의 리포트가 남아 있으면 런북이 **그것을 다시 읽는다**
        # (2026-09-07 리뷰 지적). 실패는 실패의 색을 가져야 한다.
        try:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "ip_separation_evidence.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (args.out / "ip_separation_evidence.md").write_text(markdown, encoding="utf-8")
        except OSError as exc:
            print(
                f"❌ 리포트 저장 실패 — {type(exc).__name__}: {exc}\n"
                "   이 실행의 산출물은 신뢰할 수 없다. 증빙으로 쓰지 말 것.",
                file=sys.stderr,
            )
            return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else markdown)

    if report.status != "ok":
        return 2  # 측정 실패는 통과(0)도 신호(1)도 아니다 — 세 번째 색이다
    return 1 if report.findings else 0


if __name__ == "__main__":
    sys.exit(main())
