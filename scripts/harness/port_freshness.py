#!/usr/bin/env python3
"""위임 산출물 이식의 기준 신선도 판정 — HARN-205.

왜 필요한가 (사고 대장 계열 `delegated-output-stale-base` 1회차 · 2026-09-29):
  ARCH-71에서 워크트리 격리 서브에이전트가 `ab9f29f2`(ARCH-69 착지 이전 main)에서 분기해
  학생 대면 컷오버 런북을 썼다. 메인 세션은 그 결과를 `git diff base..HEAD | git apply`로
  이식하면서 "옮긴 파일이 바이트 동일한가"만 검증했다. 그런데 이식 시점 브랜치 기준
  `c13c04ed`에는 이미 ARCH-69(`eb633ee1` · 런타임 LOCAL 강등)가 들어와 있어, 런북이 서술한
  동작("1차 좌석 실패 → 5xx")은 이미 거짓("LOCAL 강등 200")이었다. 독립 리뷰가 PR 전에 잡았다.
  이식 검증이 묻지 않은 질문은 하나다 — **산출물이 서술·참조하는 코드가 위임 기준 이후 바뀌었는가.**
  이 도구가 그 질문을 기계로 묻는다.

무엇을 하는가:
  산출물 본문에서 저장소 경로 참조를 뽑아 저장소 파일로 풀고, `git diff --name-only
  <위임 기준>..<대상>`과 겹치는지 본다. 겹치면 그 경로와 그 경로를 바꾼 커밋 목록을 낸다.
  이 도구는 *이름*으로만 판정한다 — 겹친 파일의 변경이 산출물의 서술을 실제로 거짓으로
  만들었는지는 사람(세션)이 커밋을 읽고 대조해야 한다. 도구의 몫은 "대조할 목록을
  빠뜨리지 않는 것"이다.

참조 추출 설계 (과잉·과소 사이의 판단):
  · 대상 토큰 = **확장자로 끝나는 경로 모양 문자열**. 백틱 안이든 산문이든 같은 규칙으로 뽑는다
    — `a/b.py`(슬래시+확장자) · `app.py`(단독 파일명) · `l3/router.py`(상대 조각) ·
    `.\\scripts\\x.ps1`(Windows 구분자) · `/home/.../WhyMath/x.py`(절대 경로).
    파일명 부분은 유니코드 단어 문자를 허용한다(이 저장소에 한글 파일명이 실재한다 —
    `docs/standard-book/…`). 확장자는 ASCII 글자로 시작해야 한다(`8.61168`·`v1.2.3` 제외).
  · 토큰 경계: 앞은 경로 문자가 아닌 곳에서 시작하고, 뒤는 확장자 다음이 ASCII 영숫자가
    아닌 곳에서 끝난다 — 그래서 한국어 조사가 붙은 `app.py를`에서 `app.py`만 떨어진다.
    `l3/router.py` 안의 `router.py`를 따로 뽑지 않는다(토큰 중간에서 시작하지 않는다).
  · 확장자 없는 경로는 **백틱 안에 저장소 파일 경로 그대로** 적힌 경우만 받는다
    (`.github/CODEOWNERS` 등 — 이 저장소의 확장자 없는 파일은 3개뿐이다).
  · 디렉터리 참조(`src/backend/`)는 **의도적으로 판정 밖**이다. 접두사로 풀면 거의 모든
    변경이 걸려 경고가 소음이 되고, 소음이 된 경고는 습관적으로 무시된다.
  · 점으로 시작하고 풀리지 않는 단독 토큰(`.Count`·`.get` — 멤버 접근)은 경로가 아니므로
    세지 않는다. 풀리는 것(`.gitignore`)만 참조다.
  · 파이썬 모듈 경로(`whymath_backend.l3.router`)는 파일로 푼다 — 이 저장소의 런북은 Python
    프로브를 품고 있어 바뀐 모듈을 *모듈 이름으로만* 참조하는 일이 흔하다(실사례: ARCH-71 런북이
    `whymath_backend.config`·`…l3.providers.openrouter`를 import했고 둘 다 ARCH-69가 바꿨다).
    `a.b.c`를 `a/b/c.py`·`a/b/c/__init__.py` 접미사로 풀고, 안 풀리면 뒤 조각을 떼며
    (`whymath_backend.config.settings` → `whymath_backend/config.py`) 두 조각까지 시도한다.
    `json.dumps`·`os.environ.get` 같은 표준 라이브러리 참조는 저장소에 그 파일이 없어 풀리지 않는다.
    파일명 매칭이 먼저이고, 모듈 풀이는 파일명으로 안 풀릴 때만 한다(`config.py`는 파일명이다).
  · 슬래시가 섞인 모듈식 토큰(`l3/pipeline.generate`)은 풀지 않는다 — 저장소 밖으로 센다
    (알려진 한계).

경로 풀이 (풀이 대상 = 위임 기준 트리 ∪ 대상 트리의 파일 목록 · `git ls-tree -r`):
  · 슬래시가 있는 토큰: 그 경로와 같거나 `/<토큰>`으로 끝나는 저장소 파일(상대 조각 → 접미사).
    절대 경로 표지(`/`·`~`·드라이브 문자 뒤·셸 변수 `$Root\\…` 뒤)가 있고 그렇게 풀리지 않으면,
    토큰의 꼬리 중 가장 긴 저장소 경로로 푼다.
  · 단독 파일명: 파일명이 같은 저장소 파일(**파일명 매칭**). 안 풀리면 모듈 경로로 푼다.
  · 합집합을 쓰는 이유: 기준 이후 **삭제·개명**된 파일을 참조하는 산출물이 가장 위험한데,
    대상 트리만 보면 그 참조는 "저장소 밖"으로 사라진다.
  · 결과는 셋 중 하나다 — 단일(후보 1) · 모호(후보 2+) · 저장소 밖(후보 0).
    모호 참조는 후보 중 바뀐 것이 있으면 **모름**으로 따로 센다. 전 후보가 무변경이면
    어느 파일을 뜻했든 바뀌지 않았으므로 판정이 가능하다(무변경으로 센다).

변경 목록: `git diff --name-only --no-renames -z <기준> <대상>`. `--no-renames`가 핵심이다 —
  개명 탐지가 켜진 diff는 새 이름만 내서, 옛 경로를 참조하는 산출물을 놓친다. `-z`는
  비ASCII 경로의 C 인용(`core.quotepath`)을 끈다.

대상에 이식 자신이 들어 있는 경우(판정 불가):
  이식을 커밋한 뒤 대상=HEAD로 돌리면 기준→대상 변경에 이식 자신이 섞여, 산출물이 참조하는
  위임 측 파일이 전부 "바뀜"으로 보인다. 산출물 경로가 변경 목록에 있고 대상의 그 파일이
  산출물과 내용이 같으면 이 상태로 판정해 exit 2로 멈춘다(오경보가 습관화되면 경고 전체가
  소음이 된다). 해법: `git apply`만 하고 **커밋하기 전에** 돌리거나 `--target <이식 직전 커밋>`.
  내용이 다르면 대상 쪽에서 그 파일 자체가 바뀐 것이므로 교집합과 같이 exit 1로 센다.

사용법:
  # ① 이식 직후 — git apply만 하고 커밋하기 전 (대상 = HEAD, 기본값)
  python3 scripts/harness/port_freshness.py --delegate-base <위임 기준 커밋> <산출물 경로...>
  # ② PR 직전 — 그 사이 main이 더 움직였을 수 있다
  python3 scripts/harness/port_freshness.py --delegate-base <위임 기준 커밋> \\
      --target origin/main <산출물 경로...>
  # 산출물을 작업 트리 대신 특정 커밋에서 읽는다(경로는 저장소 상대)
  python3 scripts/harness/port_freshness.py --delegate-base ab9f29f2 --target c13c04ed \\
      --artifact-ref 4dc0609f docs/ops/arch71_student_facing_cloud_mid_live_runbook.md
  `--json`은 판정 전체를 JSON으로 낸다. 작업 트리 산출물 경로는 현재 디렉터리 기준이다.

exit code:
  0 신선 — 판정 대상 참조가 1건 이상이고 교집합·모름·산출물 자체 변경이 모두 0건
  1 신선도 의심 — 교집합 1건+ 또는 모름 1건+ 또는 산출물 자체가 대상에서 바뀜
  2 판정 불가 — 사용 오류(인자·커밋 없음·산출물 없음·git 실패) · 판정 대상 참조 0건
    (스캔 0건은 통과가 아니다) · 대상에 이식 자신이 들어 있음

git 호출은 HARN-19 헬퍼(`remote_claims._git` — 출력 utf-8 고정 디코드)를 재사용한다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import remote_claims

# ── 상수 ──────────────────────────────────────────────────────────────────
EXIT_FRESH = 0
EXIT_STALE = 1
EXIT_UNJUDGEABLE = 2

#: `--target`을 생략했을 때의 대상. 위임 기준으로 되돌리면 변경 목록이 늘 0건이 되어
#: 모든 판정이 공허하게 "신선"이 된다 — 테스트가 이 기본값을 동결한다.
DEFAULT_TARGET = "HEAD"

UNIQUE = "unique"
AMBIGUOUS = "ambiguous"
OUTSIDE = "outside"

#: 확장자로 끝나는 경로 모양 토큰. 설계 근거는 모듈 docstring "참조 추출 설계".
_PATH_TOKEN_RE = re.compile(
    r"(?<![\w\-.~/\\])"  # 토큰 중간에서 시작하지 않는다
    r"(?:~?[/\\])?"  # 절대 경로 표지(선택)
    r"(?:[\w\-.~]+[/\\])*"  # 디렉터리 조각
    r"[\w\-.~]*\.[A-Za-z][A-Za-z0-9]{0,15}"  # 파일명.확장자
    r"(?![A-Za-z0-9_])"  # 확장자 뒤가 ASCII 영숫자면 확장자가 아니다
)

#: 한 줄짜리 백틱 스팬 — 확장자 없는 저장소 파일 경로를 받는 보조 채널.
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")

#: 토큰 바로 앞이 이것이면 알 수 없는 뿌리 아래의 경로다 — 드라이브 문자(`C:\...`)·
#: 셸 변수(`$Root\...`·`%ROOT%\...`·`${Root}/...`). 절대 경로 표지와 같게 다룬다.
_ROOTED_BEFORE_RE = re.compile(r"(?:[A-Za-z]:|[$%}])$")

#: 파이썬 식별자 — 모듈 경로 조각 판별.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class UsageError(RuntimeError):
    """판정을 시작할 수 없는 입력 — exit 2(사용 오류)로 끝난다."""


# ── 데이터 구조 ────────────────────────────────────────────────────────────
@dataclass
class Artifact:
    """판정 대상 산출물 하나."""

    label: str  # 출력용 이름(`<ref>:<경로>` 또는 입력 경로)
    text: str
    repo_path: str | None  # 저장소 상대 경로(저장소 밖 파일이면 None)


@dataclass
class Resolution:
    """경로 토큰 하나의 풀이 결과."""

    token: str
    kind: str  # UNIQUE | AMBIGUOUS | OUTSIDE
    candidates: tuple[str, ...] = ()
    sources: list[str] = field(default_factory=list)  # 이 토큰이 나온 산출물 label


@dataclass
class RepoIndex:
    """풀이 대상 파일 목록(위임 기준 ∪ 대상)과 파일명 색인."""

    files: frozenset[str]
    by_basename: dict[str, tuple[str, ...]]

    @classmethod
    def build(cls, paths: Iterable[str]) -> RepoIndex:
        files = frozenset(p for p in paths if p)
        grouped: dict[str, list[str]] = {}
        for path in files:
            grouped.setdefault(path.rsplit("/", 1)[-1], []).append(path)
        return cls(files, {k: tuple(sorted(v)) for k, v in grouped.items()})


@dataclass
class Verdict:
    """판정 결과 전체."""

    delegate_base: str
    target: str
    target_ref: str
    target_is_default: bool
    artifacts: list[str]
    drift: list[str]
    resolutions: list[Resolution]
    intersection: list[str]
    unknown: list[tuple[Resolution, list[str]]]
    ambiguous_unchanged: list[Resolution]
    artifact_self_changed: list[str]
    self_included: list[str]
    base_is_ancestor: bool | None
    commits: dict[str, list[str]] = field(default_factory=dict)

    @property
    def judged(self) -> int:
        """판정 대상 참조 수 = 저장소 경로로 풀린 참조(단일 + 모호)."""
        return sum(1 for r in self.resolutions if r.kind != OUTSIDE)

    @property
    def exit_code(self) -> int:
        if self.self_included:
            return EXIT_UNJUDGEABLE
        if self.judged == 0:
            return EXIT_UNJUDGEABLE
        if self.intersection or self.unknown or self.artifact_self_changed:
            return EXIT_STALE
        return EXIT_FRESH

    def to_dict(self) -> dict:
        by_kind = {k: [r for r in self.resolutions if r.kind == k] for k in (UNIQUE, AMBIGUOUS)}
        outside = [r for r in self.resolutions if r.kind == OUTSIDE]
        refs_of = {}
        for res in by_kind[UNIQUE]:
            refs_of.setdefault(res.candidates[0], []).append(res.token)
        return {
            "delegate_base": self.delegate_base,
            "target": self.target,
            "target_ref": self.target_ref,
            "target_is_default": self.target_is_default,
            "base_is_ancestor": self.base_is_ancestor,
            "artifacts": self.artifacts,
            "drift_count": len(self.drift),
            "refs": {
                "tokens": len(self.resolutions),
                "judged": self.judged,
                "unique": len(by_kind[UNIQUE]),
                "ambiguous": len(by_kind[AMBIGUOUS]),
                "outside": len(outside),
                "outside_tokens": sorted(r.token for r in outside),
            },
            "intersection": [
                {
                    "path": path,
                    "referenced_as": sorted(refs_of.get(path, [])),
                    "commits": self.commits.get(path, []),
                }
                for path in self.intersection
            ],
            "unknown": [
                {
                    "token": res.token,
                    "candidates": list(res.candidates),
                    "changed_candidates": changed,
                    "commits": {c: self.commits.get(c, []) for c in changed},
                }
                for res, changed in self.unknown
            ],
            "ambiguous_unchanged": [
                {"token": r.token, "candidates": list(r.candidates)}
                for r in self.ambiguous_unchanged
            ],
            "artifact_self_changed": self.artifact_self_changed,
            "self_included": self.self_included,
            "exit": self.exit_code,
        }


# ── git ───────────────────────────────────────────────────────────────────
def _git_out(repo: Path, *argv: str, timeout: int = 60) -> str:
    """git을 돌려 stdout을 돌려준다. 실패는 원인(stderr)을 담은 UsageError다."""
    proc = remote_claims._git(repo, *argv, timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else "(stderr 없음)"
        raise UsageError(f"git {' '.join(argv[:3])} 실패(exit {proc.returncode}): {tail}")
    return proc.stdout or ""


def repo_toplevel(start: Path) -> Path:
    """`start`가 속한 저장소의 최상위 디렉터리."""
    return Path(_git_out(start, "rev-parse", "--show-toplevel").strip())


def resolve_commit(repo: Path, rev: str) -> str:
    """커밋을 전체 해시로 푼다. 없으면 얕은 체크아웃 여부까지 담아 UsageError."""
    proc = remote_claims._git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    if proc.returncode == 0 and (proc.stdout or "").strip():
        return proc.stdout.strip()
    shallow = remote_claims._git(repo, "rev-parse", "--is-shallow-repository")
    hint = ""
    if (shallow.stdout or "").strip() == "true":
        hint = " — 얕은(shallow) 체크아웃이다: `git fetch --unshallow` 또는 CI fetch-depth: 0"
    raise UsageError(f"커밋을 찾을 수 없다: {rev}{hint}")


def _nul_split(out: str) -> list[str]:
    return [item for item in out.split("\0") if item]


def drift_paths(repo: Path, base: str, target: str) -> list[str]:
    """위임 기준 → 대상 사이에 바뀐 파일(개명은 삭제+추가로 편다)."""
    return sorted(
        _nul_split(_git_out(repo, "diff", "--name-only", "--no-renames", "-z", base, target))
    )


def tree_files(repo: Path, commit: str) -> list[str]:
    """커밋 트리의 파일 전량."""
    return _nul_split(_git_out(repo, "ls-tree", "-r", "--name-only", "-z", commit))


def commits_touching(repo: Path, base: str, target: str, path: str) -> list[str]:
    """`base..target`에서 `path`를 바꾼 커밋 목록(`<짧은 해시> <날짜> <제목>`)."""
    out = _git_out(
        repo,
        "--literal-pathspecs",
        "log",
        "--no-renames",
        "--date=short",
        "--format=%h %ad %s",
        f"{base}..{target}",
        "--",
        path,
    )
    return [line for line in out.splitlines() if line.strip()]


def base_is_ancestor(repo: Path, base: str, target: str) -> bool | None:
    """위임 기준이 대상의 조상인가(판정 불가면 None)."""
    proc = remote_claims._git(repo, "merge-base", "--is-ancestor", base, target)
    if proc.returncode in (0, 1):
        return proc.returncode == 0
    return None


def show_file(repo: Path, commit: str, path: str) -> str | None:
    """`commit:path`의 내용. 그 커밋에 파일이 없으면 None."""
    proc = remote_claims._git(repo, "show", f"{commit}:{path}")
    if proc.returncode != 0:
        return None
    return proc.stdout or ""


# ── 산출물 읽기 ────────────────────────────────────────────────────────────
def _as_repo_relative(spec: str) -> str:
    """`--artifact-ref`용 경로 정규화 — 저장소 상대 경로여야 한다."""
    rel = spec.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        raise UsageError(f"--artifact-ref의 산출물 경로는 저장소 상대 경로여야 한다: {spec}")
    return rel


def read_artifacts(
    repo: Path, specs: list[str], artifact_ref: str | None, cwd: Path
) -> list[Artifact]:
    """산출물 본문을 읽는다 — 작업 트리 파일 또는 `artifact_ref` 커밋의 파일."""
    artifacts: list[Artifact] = []
    for spec in specs:
        if artifact_ref is not None:
            rel = _as_repo_relative(spec)
            text = show_file(repo, artifact_ref, rel)
            if text is None:
                raise UsageError(f"산출물이 {artifact_ref[:8]}에 없다: {rel}")
            artifacts.append(Artifact(f"{artifact_ref[:8]}:{rel}", text, rel))
            continue
        path = Path(spec)
        if not path.is_absolute():
            path = cwd / path
        if not path.is_file():
            raise UsageError(f"산출물 파일이 없다: {spec}")
        text = path.read_bytes().decode("utf-8", errors="replace")
        try:
            rel_path: str | None = path.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            rel_path = None  # 저장소 밖 파일(스크래치 등) — 자기 포함 검사 대상이 아니다
        artifacts.append(Artifact(spec, text, rel_path))
    return artifacts


# ── 참조 추출·풀이 ─────────────────────────────────────────────────────────
def extract_tokens(text: str) -> list[tuple[str, bool]]:
    """본문에서 경로 토큰을 뽑는다 — `(토큰, 절대 경로 표지 여부)` 목록(등장 순 · 중복 제거)."""
    seen: dict[str, bool] = {}
    for match in _PATH_TOKEN_RE.finditer(text):
        raw = match.group(0)
        before = text[max(0, match.start() - 2) : match.start()]
        absolute = raw[:1] in ("/", "\\", "~") or bool(_ROOTED_BEFORE_RE.search(before))
        token = _normalize(raw)
        if token and token not in seen:
            seen[token] = absolute
        elif token and absolute:
            seen[token] = True
    return list(seen.items())


def backtick_exact_paths(text: str, index: RepoIndex) -> list[str]:
    """백틱 안에 저장소 파일 경로가 그대로 적힌 것(확장자 없는 파일 보조 채널)."""
    found = []
    for match in _BACKTICK_RE.finditer(text):
        token = _normalize(match.group(1).strip())
        if token in index.files:
            found.append(token)
    return found


def _normalize(raw: str) -> str:
    """구분자 통일(`\\`→`/`) · 앞머리 `~`·`./`·`../`·`/` 제거 · 중복 `/` 축약."""
    token = raw.replace("\\", "/").lstrip("~")
    while True:
        if token.startswith("./"):
            token = token[2:]
        elif token.startswith("../"):
            token = token[3:]
        elif token.startswith("/"):
            token = token[1:]
        else:
            break
    token = re.sub(r"/{2,}", "/", token)
    return "" if token in ("", ".", "..") else token


def match_basename(index: RepoIndex, name: str) -> list[str]:
    """단독 파일명 → 파일명이 같은 저장소 파일(파일명 매칭)."""
    return list(index.by_basename.get(name, ()))


def _suffix_matches(index: RepoIndex, rel: str) -> list[str]:
    """`rel`과 같거나 `/<rel>`로 끝나는 저장소 파일."""
    tail = rel.rsplit("/", 1)[-1]
    return [f for f in index.by_basename.get(tail, ()) if f == rel or f.endswith("/" + rel)]


def match_module(index: RepoIndex, token: str) -> list[str]:
    """파이썬 모듈 경로 → 저장소 파일. 가장 긴 조각부터, 두 조각까지 떼며 시도한다."""
    parts = token.split(".")
    if len(parts) < 2 or not all(_IDENT_RE.match(p) for p in parts):
        return []
    for k in range(len(parts), 1, -1):
        rel = "/".join(parts[:k])
        found = _suffix_matches(index, rel + ".py") + _suffix_matches(index, rel + "/__init__.py")
        if found:
            return found
    return []


def resolve_token(token: str, absolute: bool, index: RepoIndex) -> Resolution:
    """토큰 하나를 저장소 파일로 푼다 — 단일·모호·저장소 밖."""
    if "/" in token:
        candidates = _suffix_matches(index, token)
        if not candidates and absolute:
            parts = token.split("/")
            for i in range(1, len(parts)):
                suffix = "/".join(parts[i:])
                if suffix in index.files:
                    candidates = [suffix]
                    break
    else:
        candidates = match_basename(index, token)
        if not candidates:
            candidates = match_module(index, token)
    if not candidates:
        return Resolution(token, OUTSIDE)
    kind = UNIQUE if len(candidates) == 1 else AMBIGUOUS
    return Resolution(token, kind, tuple(sorted(candidates)))


def resolve_artifacts(artifacts: list[Artifact], index: RepoIndex) -> list[Resolution]:
    """산출물 전체의 참조를 풀어 토큰별로 합친다(같은 토큰은 출처만 늘린다)."""
    merged: dict[str, Resolution] = {}
    for art in artifacts:
        tokens = extract_tokens(art.text)
        tokens += [(t, False) for t in backtick_exact_paths(art.text, index)]
        for token, absolute in tokens:
            res = merged.get(token)
            if res is None or (res.kind == OUTSIDE and absolute):
                fresh = resolve_token(token, absolute, index)
                if fresh.kind == OUTSIDE and _is_member_access(token):
                    continue  # `.Count`·`.get` — 경로가 아니다(세지 않는다)
                fresh.sources = res.sources if res is not None else []
                merged[token] = res = fresh
            if art.label not in res.sources:
                res.sources.append(art.label)
    return list(merged.values())


def _is_member_access(token: str) -> bool:
    """점으로 시작하는 단독 토큰 — 풀리지 않으면 멤버 접근(`.Count`)이지 경로가 아니다."""
    return token.startswith(".") and "/" not in token


# ── 판정 ──────────────────────────────────────────────────────────────────
def judge(
    repo: Path,
    delegate_base: str,
    target_ref: str,
    artifact_specs: list[str],
    *,
    artifact_ref: str | None = None,
    target_is_default: bool = False,
    cwd: Path | None = None,
) -> Verdict:
    """판정 본체 — CLI와 테스트가 같은 경로를 쓴다."""
    base_sha = resolve_commit(repo, delegate_base)
    target_sha = resolve_commit(repo, target_ref)
    ref_sha = resolve_commit(repo, artifact_ref) if artifact_ref is not None else None
    artifacts = read_artifacts(repo, artifact_specs, ref_sha, cwd or Path.cwd())

    drift = drift_paths(repo, base_sha, target_sha)
    drift_set = set(drift)
    index = RepoIndex.build([*tree_files(repo, base_sha), *tree_files(repo, target_sha)])
    resolutions = resolve_artifacts(artifacts, index)

    unique_paths = [r.candidates[0] for r in resolutions if r.kind == UNIQUE]
    hits = sorted(set(unique_paths) & drift_set)

    unknown: list[tuple[Resolution, list[str]]] = []
    ambiguous_unchanged: list[Resolution] = []
    for res in resolutions:
        if res.kind != AMBIGUOUS:
            continue
        changed = sorted(set(res.candidates) & drift_set)
        if changed:
            unknown.append((res, changed))
        else:
            ambiguous_unchanged.append(res)

    self_included: list[str] = []
    self_changed: list[str] = []
    for art in artifacts:
        if art.repo_path is None or art.repo_path not in drift_set:
            continue
        at_target = show_file(repo, target_sha, art.repo_path)
        if at_target is not None and at_target == art.text:
            self_included.append(art.repo_path)
        else:
            self_changed.append(art.repo_path)

    commits: dict[str, list[str]] = {}
    for path in sorted({*hits, *(c for _, changed in unknown for c in changed), *self_changed}):
        commits[path] = commits_touching(repo, base_sha, target_sha, path)

    return Verdict(
        delegate_base=base_sha,
        target=target_sha,
        target_ref=target_ref,
        target_is_default=target_is_default,
        artifacts=[a.label for a in artifacts],
        drift=drift,
        resolutions=resolutions,
        intersection=hits,
        unknown=unknown,
        ambiguous_unchanged=ambiguous_unchanged,
        artifact_self_changed=sorted(set(self_changed)),
        self_included=sorted(set(self_included)),
        base_is_ancestor=base_is_ancestor(repo, base_sha, target_sha),
        commits=commits,
    )


# ── 출력 ──────────────────────────────────────────────────────────────────
_SAMPLE = 12  # 저장소 밖 토큰 표본 수 — 전량은 --json


def _commit_lines(commits: list[str], indent: str) -> list[str]:
    if not commits:
        return [f"{indent}(이 경로를 바꾼 커밋 조회 0건 — 머지 해소로 바뀐 경우일 수 있다)"]
    return [f"{indent}{line}" for line in commits]


def render_text(v: Verdict) -> str:
    data = v.to_dict()
    refs = data["refs"]
    target_note = "기본값" if v.target_is_default else "--target"
    lines = [
        "port_freshness — 위임 산출물 기준 신선도 판정 (HARN-205)",
        f"  위임 기준 : {v.delegate_base[:8]}",
        f"  대상      : {v.target[:8]} ← {v.target_ref} ({target_note})",
        f"  산출물    : {', '.join(v.artifacts)}",
        f"  기준→대상 변경 파일: {len(v.drift)}건",
        f"  참조 추출 : 경로 토큰 {refs['tokens']}건 → 저장소 경로로 풀림 {refs['judged']}건"
        f"(단일 {refs['unique']} · 모호 {refs['ambiguous']}) · 저장소 밖 {refs['outside']}건",
    ]
    if v.base_is_ancestor is False:
        lines.append(
            "  ⚠ 위임 기준이 대상의 조상이 아니다 — 변경 목록에 기준 쪽에만 있는 변경도 섞인다"
        )
    if v.delegate_base == v.target:
        lines.append("  ⚠ 대상이 위임 기준과 같은 커밋이다 — 변경 0건(대조군 형태)")
    outside = refs["outside_tokens"]
    if outside:
        shown = ", ".join(outside[:_SAMPLE])
        more = f" 외 {len(outside) - _SAMPLE}건(전량은 --json)" if len(outside) > _SAMPLE else ""
        lines.append(f"  저장소 밖 토큰: {shown}{more}")

    if v.self_included:
        lines.append(
            f"✗ 판정 불가 — 대상에 이식 자신이 들어 있다: {', '.join(v.self_included)}\n"
            "  기준→대상 변경에 이식이 섞여 위임 측 파일이 전부 '바뀜'으로 보인다.\n"
            "  `git apply`만 하고 커밋하기 전에 돌리거나 `--target <이식 직전 커밋>`을 주라."
        )
    if v.judged == 0:
        lines.append(
            "✗ 판정 대상 0건 — 저장소 경로로 풀린 참조가 없다. 스캔 0건은 통과가 아니다.\n"
            "  산출물 경로가 맞는지, 산출물이 경로를 확장자와 함께 적었는지 확인하라."
        )

    contaminated = " (참고용 — 이식 자신이 섞인 값이다)" if v.self_included else ""
    lines.append(f"{'✗' if v.intersection else '✓'} 교집합 {len(v.intersection)}건{contaminated}")
    for item in data["intersection"]:
        lines.append(f"  · {item['path']}  (참조: {', '.join(item['referenced_as'])})")
        lines.extend(_commit_lines(item["commits"], "      "))
    lines.append(
        f"{'?' if v.unknown else '✓'} 모름 {len(v.unknown)}건 "
        f"(파일명이 여러 경로로 풀리고 그중 바뀐 것이 있다 · 전 후보 무변경 모호 "
        f"{len(v.ambiguous_unchanged)}건은 무변경으로 셈)"
    )
    for item in data["unknown"]:
        lines.append(
            f"  · {item['token']} → 후보 {len(item['candidates'])}건 중 변경: "
            f"{', '.join(item['changed_candidates'])}"
        )
        for path, commits in item["commits"].items():
            lines.append(f"      [{path}]")
            lines.extend(_commit_lines(commits, "      "))
    if v.artifact_self_changed:
        lines.append(f"✗ 산출물 자체가 기준 이후 대상에서 바뀜 {len(v.artifact_self_changed)}건")
        for path in v.artifact_self_changed:
            lines.append(f"  · {path}")
            lines.extend(_commit_lines(v.commits.get(path, []), "      "))

    code = v.exit_code
    if code == EXIT_FRESH:
        tail = "신선 — 산출물이 참조하는 경로는 위임 기준 이후 대상에서 바뀌지 않았다"
    elif code == EXIT_STALE:
        tail = (
            "신선도 의심 — 위 커밋의 변경이 산출물의 서술을 거짓으로 만들었는지 "
            "이식 전에 대조하라(도구는 이름만 본다)"
        )
    else:
        tail = "판정 불가 — 위 사유를 해소하고 다시 돌려라"
    lines.append(f"판정: exit {code} — {tail}")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="port_freshness.py",
        description="위임 산출물 이식의 기준 신선도 판정 (HARN-205)",
    )
    parser.add_argument(
        "--delegate-base", required=True, help="위임 워크트리가 분기한 커밋(위임 기준)"
    )
    parser.add_argument(
        "--target",
        default=None,
        help=f"대상 커밋(기본 {DEFAULT_TARGET} — 이식 직후. PR 직전엔 origin/main)",
    )
    parser.add_argument(
        "--artifact-ref",
        default=None,
        help="산출물을 작업 트리 대신 이 커밋에서 읽는다(산출물 경로는 저장소 상대)",
    )
    parser.add_argument("--repo", default=".", help="저장소 안의 아무 경로(기본 현재 디렉터리)")
    parser.add_argument("--json", action="store_true", help="판정 전체를 JSON으로 출력")
    parser.add_argument("artifacts", nargs="+", help="이식한 산출물 경로(1개 이상)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target_ref = args.target if args.target is not None else DEFAULT_TARGET
    try:
        repo = repo_toplevel(Path(args.repo))
        verdict = judge(
            repo,
            args.delegate_base,
            target_ref,
            args.artifacts,
            artifact_ref=args.artifact_ref,
            target_is_default=args.target is None,
            cwd=Path.cwd(),
        )
    except UsageError as exc:
        print(f"✗ 사용 오류: {exc}", file=sys.stderr)
        return EXIT_UNJUDGEABLE
    except (OSError, subprocess.SubprocessError, remote_claims.GitOutputDecodeError) as exc:
        # 침묵 실패 금지 — 예외 타입명을 남긴다(CLAUDE.md AI·신뢰).
        print(f"✗ 판정 불가({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_UNJUDGEABLE
    if args.json:
        print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_text(verdict))
    return verdict.exit_code


if __name__ == "__main__":
    import _stdio  # 스크립트 실행이면 이 디렉터리가 sys.path[0]이다 (OPS-53)

    _stdio.ensure_utf8_stdio()
    sys.exit(main())
