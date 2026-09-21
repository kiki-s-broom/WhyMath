r"""[OPS-29] CI 강제 상태 선언 계약 — "돌아감≠막음" 일반화.

왜 이 모듈이 있는가
------------------
이 저장소는 같은 사고 사슬을 세 단계로 겪었다:
  ① OPS-10 — "존재함≠돌아감"을 기계화(`tests/infra`가 어느 CI 잡도 실행하지 않던 상태 발견).
  ② OPS-22 — "선언함≠배선됨"을 기계화(`declared_unwired_audit` — 코드는 있으나 소비자가
     없는 공급 표면을 reached/by-design/pending-task 3분류로 강제).
  ③ 이 모듈(OPS-29) — 사슬의 마지막 고리 "돌아감≠막음"을 기계화한다. `ci.yml`의 어떤
     스텝은 *돌아가긴 하지만* `continue-on-error: true`거나 게이트 판정을 `|| true`로
     삼켜서 실패해도 PR을 막지 못한다. 이 자체가 항상 나쁜 것은 아니다(shellcheck
     warnings-only가 좋은 예) — 문제는 그 상태가 **의도적인지 방치인지 아무도 선언하지
     않는다**는 것이다. 실측(착수 시점) `tests/infra/*_wiring.py` 11개 중
     `continue-on-error`를 assert하는 것은 0건이었다.

판정 규약 — OPS-22·ARCH-25를 그대로 이식(새 발명 금지)
------------------------------------------------------
`ci.yml`에서 "비차단 스텝"(아래 두 조건 중 하나)을 찾는다:
    (a) `continue-on-error:` 키가 `false`가 아닌 값을 가진다.
    (b) `run:` 블록의 **마지막 실행 줄**(빈 줄·순수 주석 줄 제외)이 `|| true`/`; true`로
        끝나고, 그 줄에서 그 접미사를 뗀 나머지가 명백한 게이트/검사기 호출
        (`python -m ...`·`pytest ...`·`scripts/*.py` 직접·python 경유 실행)로 시작한다.

각 비차단 스텝은 그 스텝 자신의 YAML 블록(주석 포함) 안에서 다음 선언 중 하나를
가져야 한다(OPS-22 `declared_unwired_audit._MANIFEST` 값 형식 그대로):
    `by-design:<사유>`   — 의도적으로 비차단. 사유 문자열만 있으면 구조적으로 항상 유효.
    `pending-task:<id>`  — 백로그가 추적 중인 유예. `backlog/tasks/*.yaml`에 `id: <id>`인
                            파일이 실재하고 그 `status`가 `done`이 아닐 때만 유효
                            (ARCH-25 `GrandfatherEntry`/`find_grandfather_expiry_violations`
                            만료 계약 이식 — `status: done`인데 항목이 남아 있으면 "방치,
                            게이트를 다시 켜라는 신호"로 위반).
    (선언 없음)           — **unclassified·위반**.

`tests/infra`는 `whymath_backend`를 import하지 않는다(계층 독립성 — 이 잡은 그 패키지를
install하지 않는 `infra-contracts`에서 돈다, 기존 `test_qa_pipeline_wiring.py`·
`test_declared_unwired_audit_wiring.py` 선례와 동형). 그래서 `ops/declared_unwired_audit.py`의
분류 문자열 계약과 `ops/provenance_audit.py`의 그랜드파더 만료 계약을 **이 파일 안에서
가볍게 재구현**한다(`l3/equivalent/rephrase_hygiene.py`가 harness를 import하지 않고
로컬 재구현한 QUAL-03 선례와 동형) — 두 ops 모듈은 import하지 않는다.

`|| true` 판정 기준의 실측 근거(2026-08-11 재확인)
--------------------------------------------------
착수 시점 `ci.yml` 전체에서 `|| true`는 정확히 3건이고(`grep -n '|| true'` 재확인), 셋 다
"게이트 판정을 삼키는" 패턴이 아니라 정당한 방어적 셸 관용구였다:
  · 재시도 루프 안에서 curl 실패를 다음 반복으로 넘기는 것(진짜 판정은 그 아래 명시적
    `exit 1`이 한다) — 이 스텝의 `run:` 블록 마지막 줄은 `echo "PASS ..."`이지 그 curl
    줄이 아니다.
  · 실패 진단용 `docker logs ... || true`(바로 다음 줄이 `exit 1`) — 마지막 줄이 아니다.
  · `if: always()` 컨테이너 정리 스텝의 `docker rm -f ... || true` — 이건 그 run 블록의
    유일한(=마지막) 줄이지만, "게이트/검사기 호출"이 아니라 정리 명령이라 애초에
    검증 대상이 아니다.
위 "마지막 실행 줄 + 게이트 호출 패턴" 조합 기준은 이 3건을 전부 올바르게 제외하면서도
(아래 `TestGateSwallowingTrueClassification`의 대조군 테스트가 이 판별력을 실측 고정한다),
향후 실제 회귀(게이트 호출의 exit code를 `|| true`가 삼키는 신규 패턴)는 계속 잡는다.

선언 위치·문법 규약(이 모듈이 스스로 정의)
-------------------------------------------
YAML 파서는 주석을 버리므로(`yaml.safe_load`), "이 스텝에 선언이 있는가"는 **원문 텍스트**를
스텝 단위로 잘라 스캔해야 한다. 이 저장소의 모든 스텝은 예외 없이 `      - name:`(정확히
6칸 들여쓰기)으로 시작한다(실측: 98건 전수 확인 — `- name:` 아닌 6칸 리스트 항목 0건).
그래서 **스텝의 원문 범위 = 그 스텝의 `- name:` 줄부터 같은 잡 안에서 다음 스텝의
`- name:` 줄 직전까지**(마지막 스텝이면 다음 잡 시작 직전까지)로 정의한다. 그 범위 안의
**`#`으로 시작하는 주석 줄**만 선언 탐색 대상이다(`run:` 블록 안의 실제 셸 `#`은 YAML
주석이 아니라 스크립트 내용이므로 제외 — 혼동 방지). 선언 마커(`by-design:`/
`pending-task:`)와 그 값은 **한 물리 줄 안**에 있어야 한다(여러 줄에 걸친 선언은
지원하지 않는다 — 설계 단순성.가욋 설명은 그 줄 앞뒤에 자유롭게 둘 수 있다).

잡 경계는 `create_app()` 같은 실행 없이, 파싱된 `jobs` 딕셔너리의 **실제 키 이름**만
원문에서 찾는다(`^  <job_key>:\s*$` 정확히 2칸 들여쓰기 + 값 없음) — `on:` 블록의
`push:`/`schedule:` 같은 구조적으로 동일한 모양의 무관한 줄은 job_keys 집합에 없으므로
자연히 제외된다(재현·확인 완료).

수집기 파손 방어(exit 아님 — 여기선 AssertionError)
----------------------------------------------------
YAML에서 파싱한 스텝 개수와 원문에서 찾은 `- name:` 경계 개수가 어긋나면(예: 어떤 스텝이
관례를 어기고 `- name:`이 아닌 다른 키로 시작) "위반 0건"으로 위장하지 않고 즉시
`AssertionError`를 낸다(`declared_unwired_audit.CollectorError`와 동일 철학 — "성공/실패
양쪽에서 같은 값을 내는 검사는 검증이 아니라 위장"의 자기 적용).

`pending-task:` 값으로 짧은 코드가 아니라 전체 슬러그를 쓰는 이유
-------------------------------------------------------------------
`ops/provenance_audit.py`의 `_load_backlog_task_statuses`(ARCH-25가 실제로 돌리는 코드)는
`backlog/tasks/*.yaml`을 전수 스캔해 **그 파일의 `id:` 필드 내용**으로 `{task_id: status}`
맵을 만든다(파일명이 아니라 내용 기준). `declared_unwired_audit.py`의 실제 `_MANIFEST`도
`pending-task:S4-22-attempt-event-signal-consumer-wiring`·`pending-task:S4-16-residue-
gate-demotion-battle`처럼 항상 전체 슬러그를 쓴다(짧은 코드만 쓰는 선례는 이 저장소에
없다). 이 모듈도 같은 이식 규약을 그대로 따른다 — `pending-task:<id>`의 `<id>`는
`backlog/tasks/*.yaml`의 `id:` 필드 값과 정확히 일치해야 한다("ARCH-23" 같은 산문 줄임
표기를 쓰면 그랜드파더 조회가 "태스크 없음"으로 판정해 위반이 된다).

[ARCH-23 정정 — 착수 후 완료] 이 절이 원래 들던 구체 예시(`ci.yml`의 qa_pipeline 스텝이
`pending-task:ARCH-23-qa-gate-enforcement`로 유예됐던 상태)는 ARCH-23 자신이 그 스텝의
`continue-on-error`와 선언을 함께 제거하면서 사라졌다 — 만료 계약이 설계대로 작동한
사례다(태스크가 done이 되기 *전에* 소유 태스크가 직접 걷어냈다는 점에서 "방치 뒤 위반
발견"보다 이른 단계의 정상 경로). 규약 자체(전체 슬러그 요구)는 `declared_unwired_audit.py`
쪽 실사용 예시로 여전히 유효하다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_BACKLOG_TASKS_DIR = _REPO_ROOT / "backlog" / "tasks"

# 스텝 경계 — 이 저장소의 모든 스텝은 정확히 6칸 들여쓰기 `- name:`으로 시작한다(모듈
# docstring "선언 위치·문법 규약" 참조 — 실측 98건 전수 확인).
_STEP_BOUNDARY_RE = re.compile(r"^ {6}- name:")
# 잡 키 줄 — 정확히 2칸 들여쓰기 + 키 + 콜론 + 그 외 아무 것도 없음(값이 있으면 잡 키가
# 아니라 어떤 잡 안의 스칼라 필드다 — `permissions.contents: read` 등).
_JOB_KEY_LINE_RE = re.compile(r"^ {2}([A-Za-z0-9_-]+):\s*$")

# 게이트 판정을 삼키는 `|| true`/`; true` 접미사.
_TRAILING_TRUE_RE = re.compile(r"(\|\|\s*true|;\s*true)\s*$")
# 위 접미사를 뗀 나머지가 "명백한 게이트/검사기 호출"로 시작하는가 — python -m 모듈 실행·
# python 경유 스크립트 실행·pytest 직접 실행·scripts/*.py 직접 실행 4형태만 인정한다
# (보수적 정의 — 오탐이 미탐만큼 나쁘다는 CLAUDE.md "변별력 없는 검증 스텝 금지" 원칙).
_GATE_INVOCATION_RE = re.compile(
    r"^("
    r"python3?\s+-m\s+\S+"
    r"|python3?\s+\.?/?scripts/\S+\.py"
    r"|pytest(\s|$)"
    r"|\.?/?scripts/\S+\.py(\s|$)"
    r")"
)

# 선언 마커 — OPS-22 `declared_unwired_audit._BY_DESIGN`/`_PENDING_TASK` 문자열 계약 그대로.
# 마커와 값은 한 물리 줄 안에 있어야 한다(모듈 docstring "선언 위치·문법 규약" 참조).
_BY_DESIGN_LINE_RE = re.compile(r"by-design:\s*(\S.*)")
_PENDING_TASK_LINE_RE = re.compile(r"pending-task:\s*(\S+)")

_UNCLASSIFIED = "unclassified"
_REASON_CONTINUE_ON_ERROR = "continue-on-error"
_REASON_GATE_SWALLOWING_TRUE = "gate-swallowing-||true"


@dataclass(frozen=True, slots=True)
class Declaration:
    """스텝에서 발견된 선언 — `kind`는 'by-design' 또는 'pending-task', `value`는 그 뒤 텍스트
    (사유 문자열 또는 백로그 태스크 id)."""

    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class StepRef:
    """분류 대상 스텝의 위치 식별자(에러 메시지·테스트 단언용)."""

    job_key: str
    step_name: str
    step_index: int


@dataclass(frozen=True, slots=True)
class ClassifiedStep:
    """ "선언이 필요하다"고 판정된 스텝 1건. `reason`은 그 판정 근거,
    `declaration`은 원문에서 발견된 선언(없으면 None = unclassified)."""

    ref: StepRef
    reason: str
    declaration: Declaration | None


# ──────────────────────────────────────────────────────────────────────────
# 축 A — 스텝이 "비차단"인가(continue-on-error 또는 게이트-swallowing || true)
# ──────────────────────────────────────────────────────────────────────────


def _continue_on_error_active(step: dict[str, Any]) -> bool:
    """`continue-on-error:`가 `false`류가 아닌 값을 가지면 활성으로 본다(단순 `is True`보다
    관대함 — 미래에 `${{ expression }}` 형태로 바뀌어도 안전 방향으로 잡는다)."""
    value = step.get("continue-on-error")
    if value is None or value is False:
        return False
    if isinstance(value, str) and value.strip().lower() == "false":
        return False
    return True


def _last_effective_run_line(run_text: str) -> str | None:
    """`run:` 블록에서 빈 줄·순수 주석 줄(셸 `#`)을 뺀 **마지막 실행 줄**."""
    effective = [
        stripped
        for line in run_text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]
    return effective[-1] if effective else None


def _is_gate_swallowing_step(step: dict[str, Any]) -> bool:
    """마지막 실행 줄이 게이트/검사기 호출을 `|| true`/`; true`로 삼키는가."""
    run_text = step.get("run")
    if not isinstance(run_text, str) or not run_text.strip():
        return False
    last = _last_effective_run_line(run_text)
    if last is None or not _TRAILING_TRUE_RE.search(last):
        return False
    command = _TRAILING_TRUE_RE.sub("", last).strip()
    return bool(_GATE_INVOCATION_RE.match(command))


def step_requires_declaration(step: dict[str, Any]) -> str | None:
    """이 스텝이 선언을 필요로 하는 이유 코드(없으면 None = 강제 게이트 — 선언 불요)."""
    if _continue_on_error_active(step):
        return _REASON_CONTINUE_ON_ERROR
    if _is_gate_swallowing_step(step):
        return _REASON_GATE_SWALLOWING_TRUE
    return None


# ──────────────────────────────────────────────────────────────────────────
# 축 B — 원문 텍스트에서 스텝의 주석 범위를 잘라 선언을 찾는다
# ──────────────────────────────────────────────────────────────────────────


def extract_declaration(step_chunk_text: str) -> Declaration | None:
    """스텝 원문 범위의 `#` 주석 줄들만 스캔해 첫 `by-design:`/`pending-task:` 선언을 낸다.

    `run:` 블록 등 비주석 줄은 보지 않는다(셸 스크립트 내용에 우연히 같은 문자열이 있어도
    오탐하지 않기 위함). 마커와 값이 한 물리 줄에 없으면(모듈 docstring 참조) 그 줄은
    무시되고 다음 줄에서 계속 찾는다.
    """
    for raw_line in step_chunk_text.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("#"):
            continue
        comment = stripped.lstrip("#").strip()
        pending_match = _PENDING_TASK_LINE_RE.search(comment)
        if pending_match:
            return Declaration(kind="pending-task", value=pending_match.group(1))
        by_design_match = _BY_DESIGN_LINE_RE.search(comment)
        if by_design_match:
            return Declaration(kind="by-design", value=by_design_match.group(1).strip())
    return None


def _job_key_line_positions(ci_lines: list[str], job_keys: list[str]) -> dict[str, int]:
    """각 잡 키가 원문에서 시작하는 줄 번호(0-based) — `job_keys`에 실제로 있는 이름만
    인정한다(`on:` 블록의 `push:`/`schedule:` 등 구조적으로 동일한 무관 줄을 자연히 배제)."""
    positions: dict[str, int] = {}
    remaining = set(job_keys)
    for i, line in enumerate(ci_lines):
        if not remaining:
            break
        match = _JOB_KEY_LINE_RE.match(line)
        if match and match.group(1) in remaining:
            positions[match.group(1)] = i
            remaining.discard(match.group(1))
    missing = set(job_keys) - set(positions)
    if missing:
        raise AssertionError(
            f"원문에서 잡 시작 줄을 찾지 못했다: {sorted(missing)} — 수집기 파손 의심"
            "(잡 키 들여쓰기가 2칸이 아니게 바뀌었을 가능성)."
        )
    return positions


def _job_spans(positions: dict[str, int], total_lines: int) -> dict[str, tuple[int, int]]:
    """잡 키 → (원문 시작 줄, 끝 줄 직전) — 파일 순서로 정렬해 다음 잡 시작 직전까지 자른다."""
    ordered = sorted(positions.items(), key=lambda kv: kv[1])
    spans: dict[str, tuple[int, int]] = {}
    for idx, (key, start) in enumerate(ordered):
        end = ordered[idx + 1][1] if idx + 1 < len(ordered) else total_lines
        spans[key] = (start, end)
    return spans


def _step_chunks(ci_lines: list[str], start: int, end: int) -> list[str]:
    """[start, end) 범위 안에서 `- name:` 경계로 스텝별 원문 청크를 자른다(순서 보존)."""
    boundaries = [i for i in range(start, end) if _STEP_BOUNDARY_RE.match(ci_lines[i])]
    chunks: list[str] = []
    for idx, boundary in enumerate(boundaries):
        chunk_end = boundaries[idx + 1] if idx + 1 < len(boundaries) else end
        chunks.append("\n".join(ci_lines[boundary:chunk_end]))
    return chunks


def classify_workflow(ci_text: str) -> list[ClassifiedStep]:
    """`ci.yml` 원문 텍스트 → 선언이 필요한 비차단 스텝 목록(순수 함수·부수효과 없음).

    파서가 위장하지 않는다 — `jobs`가 없거나(파싱 실패류) YAML 스텝 수와 원문 `- name:`
    경계 수가 어긋나면(수집기 파손) "위반 0건"이 아니라 `AssertionError`를 낸다.
    """
    spec: Any = yaml.safe_load(ci_text)
    jobs: Any = spec.get("jobs") if isinstance(spec, dict) else None
    if not isinstance(jobs, dict) or not jobs:
        raise AssertionError("ci.yml에 jobs가 없다 — 워크플로 파싱이 위장 통과할 수 없다.")

    ci_lines = ci_text.splitlines()
    job_keys = [k for k, v in jobs.items() if isinstance(v, dict) and v.get("steps")]
    if not job_keys:
        return []
    positions = _job_key_line_positions(ci_lines, job_keys)
    spans = _job_spans(positions, len(ci_lines))

    results: list[ClassifiedStep] = []
    for job_key in job_keys:
        job = jobs[job_key]
        steps = job.get("steps") or []
        start, end = spans[job_key]
        chunks = _step_chunks(ci_lines, start, end)
        if len(chunks) != len(steps):
            raise AssertionError(
                f"`{job_key}` 잡 — YAML 스텝 수({len(steps)})와 원문 `- name:` 경계 수"
                f"({len(chunks)})가 어긋난다(수집기 파손 의심 — 조용한 통과 위장 방지를 위해 "
                "실패로 처리한다)."
            )
        for idx, (step, chunk) in enumerate(zip(steps, chunks, strict=True)):
            if not isinstance(step, dict):
                continue
            reason = step_requires_declaration(step)
            if reason is None:
                continue
            name = step.get("name")
            step_name = name if isinstance(name, str) else f"<step#{idx}>"
            results.append(
                ClassifiedStep(
                    ref=StepRef(job_key=job_key, step_name=step_name, step_index=idx),
                    reason=reason,
                    declaration=extract_declaration(chunk),
                )
            )
    return results


# ──────────────────────────────────────────────────────────────────────────
# 축 C — pending-task 그랜드파더 만료 계약(ARCH-25 `find_grandfather_expiry_violations` 이식)
# ──────────────────────────────────────────────────────────────────────────


def load_backlog_task_statuses(tasks_dir: Path) -> dict[str, str]:
    """`backlog/tasks/*.yaml`을 가볍게 파싱해 `{id 필드 값: status}`를 낸다.

    `ops/provenance_audit._load_backlog_task_statuses`(ARCH-25)의 관용구를 그대로
    재구현한다 — PyYAML `safe_load`만 사용, 파싱 실패·비딕셔너리 문서·id/status 결손은
    조용히 건너뛴다(태스크 YAML의 사람 손 편집 관용을 존중 — 이 함수의 책임은 그랜드파더
    대조이지 백로그 스키마 검증이 아니다).
    """
    statuses: dict[str, str] = {}
    if not tasks_dir.is_dir():
        return statuses
    for path in sorted(tasks_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        task_id = data.get("id")
        status = data.get("status")
        if isinstance(task_id, str) and isinstance(status, str):
            statuses[task_id] = status
    return statuses


def validate_declarations(
    classified: list[ClassifiedStep], task_statuses: dict[str, str]
) -> list[str]:
    """분류된 스텝 목록 → 위반 메시지 목록(빈 리스트 = 위반 없음).

    `by-design:<사유>`는 사유 문자열 존재만으로 항상 유효(추가 검증 없음 — OPS-22 규약).
    `pending-task:<id>`는 ARCH-25 만료 계약 그대로: `task_statuses`에 없으면 "추적 불가능",
    `status == "done"`이면 "방치 — 게이트 재검토 필요".
    """
    violations: list[str] = []
    for item in classified:
        label = f"[{item.ref.job_key}] {item.ref.step_name!r}({item.reason})"
        decl = item.declaration
        if decl is None:
            violations.append(
                f"{label}: 선언 없음({_UNCLASSIFIED}) — by-design:<사유> 또는 "
                "pending-task:<backlog 태스크 id> 필요."
            )
        elif decl.kind == "pending-task":
            status = task_statuses.get(decl.value)
            if status is None:
                violations.append(
                    f"{label}: pending-task:{decl.value} 이(가) backlog/tasks/*.yaml의 "
                    "id 필드 어디에도 없다 — 추적 불가능한 유예(오타 또는 삭제된 태스크)."
                )
            elif status == "done":
                violations.append(
                    f"{label}: pending-task:{decl.value} 이(가) 이미 done인데 유예가 "
                    "남아 있다 — 방치, 게이트를 다시 켜라는 신호."
                )
        # by-design: 사유 문자열 존재(정규식이 이미 비어있지 않음을 보장) 외 추가 검증 없음.
    return violations


def find_ci_enforcement_violations(ci_text: str, task_statuses: dict[str, str]) -> list[str]:
    """`classify_workflow` + `validate_declarations`를 합친 편의 함수(테스트 주 진입점)."""
    return validate_declarations(classify_workflow(ci_text), task_statuses)


# ──────────────────────────────────────────────────────────────────────────
# 테스트 픽스처 헬퍼
# ──────────────────────────────────────────────────────────────────────────


def _write_task_yaml(tasks_dir: Path, task_id: str, status: str) -> None:
    """ARCH-25 `test_provenance_audit.TestGrandfatherExpiryContract`의 헬퍼와 동형."""
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.yaml").write_text(
        yaml.safe_dump({"id": task_id, "status": status}, allow_unicode=True),
        encoding="utf-8",
    )


def _classify_from_fixture(tmp_path: Path, ci_text: str) -> list[ClassifiedStep]:
    """합성 ci.yml 텍스트를 tmp_path에 실제로 써서 다시 읽은 뒤 분류한다(acceptance ⑤의
    "tmp_path에 만든 합성 fixture" 요구 — `classify_workflow` 자체는 텍스트를 받는 순수
    함수이지만, 테스트는 그 입력이 실제 디스크 파일에서 온 것임을 명시적으로 보인다)."""
    fixture_path = tmp_path / "fake_ci.yml"
    fixture_path.write_text(ci_text, encoding="utf-8")
    return classify_workflow(fixture_path.read_text(encoding="utf-8"))


def _violations_from_fixture(
    tmp_path: Path, ci_text: str, task_statuses: dict[str, str]
) -> list[str]:
    return validate_declarations(_classify_from_fixture(tmp_path, ci_text), task_statuses)


def _make_ci_yaml(step_body: str, job_key: str = "fake-job") -> str:
    """최소 유효 ci.yml 합성 텍스트 — 무해한 Checkout 스텝(선언 불요) 하나 + `step_body`(검사
    대상 스텝 원문, `      - name: ...`부터 시작해야 한다)."""
    return (
        "jobs:\n"
        f"  {job_key}:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Checkout\n"
        "        uses: actions/checkout@v4\n"
        f"{step_body}"
    )


# ──────────────────────────────────────────────────────────────────────────
# 테스트 — continue-on-error 축
# ──────────────────────────────────────────────────────────────────────────


class TestContinueOnErrorClassification:
    """`continue-on-error: true`가 선언 없이 있으면 red, 선언되면 green(양방향 변별력)."""

    def test_undeclared_continue_on_error_is_unclassified_violation(self, tmp_path: Path) -> None:
        ci_text = _make_ci_yaml(
            "      - name: 미분류 게이트\n"
            "        run: python -m fake.gate\n"
            "        continue-on-error: true\n"
        )
        classified = _classify_from_fixture(tmp_path, ci_text)
        assert len(classified) == 1
        assert classified[0].reason == _REASON_CONTINUE_ON_ERROR
        assert classified[0].declaration is None

        violations = _violations_from_fixture(tmp_path, ci_text, {})
        assert len(violations) == 1
        assert _UNCLASSIFIED in violations[0]

    def test_by_design_declared_continue_on_error_is_clean(self, tmp_path: Path) -> None:
        ci_text = _make_ci_yaml(
            "      - name: 미분류 게이트\n"
            "        # by-design:테스트용 사유 — 항상 유효해야 한다\n"
            "        run: python -m fake.gate\n"
            "        continue-on-error: true\n"
        )
        classified = _classify_from_fixture(tmp_path, ci_text)
        assert len(classified) == 1
        assert classified[0].declaration == Declaration(
            kind="by-design", value="테스트용 사유 — 항상 유효해야 한다"
        )
        assert _violations_from_fixture(tmp_path, ci_text, {}) == []

    def test_by_design_marker_without_reason_text_falls_back_to_unclassified(
        self, tmp_path: Path
    ) -> None:
        """`by-design:` 뒤에 아무 내용도 없으면(정규식이 값을 요구) 선언으로 인정하지 않는다
        — "사유 문자열 필수"(OPS-22 규약)를 추출 단계에서부터 강제한다."""
        ci_text = _make_ci_yaml(
            "      - name: 게이트\n"
            "        # by-design:\n"
            "        run: python -m fake.gate\n"
            "        continue-on-error: true\n"
        )
        classified = _classify_from_fixture(tmp_path, ci_text)
        assert classified[0].declaration is None
        assert len(_violations_from_fixture(tmp_path, ci_text, {})) == 1

    def test_continue_on_error_false_is_never_flagged(self, tmp_path: Path) -> None:
        ci_text = _make_ci_yaml(
            "      - name: 정상 게이트\n"
            "        run: python -m fake.gate\n"
            "        continue-on-error: false\n"
        )
        assert _classify_from_fixture(tmp_path, ci_text) == []


# ──────────────────────────────────────────────────────────────────────────
# 테스트 — 게이트-swallowing `|| true` 축(마지막 실행 줄 휴리스틱)
# ──────────────────────────────────────────────────────────────────────────


class TestGateSwallowingTrueClassification:
    """`|| true`가 게이트 호출의 exit code를 삼키면 red, 선언되면 green. 실측 ci.yml의 3개
    정당 관용구(재시도 루프·진단 로그·정리 스텝)와 동형인 대조군으로 오탐 없음도 고정한다."""

    def test_gate_call_with_trailing_true_as_last_line_is_flagged(self, tmp_path: Path) -> None:
        ci_text = _make_ci_yaml(
            "      - name: 삼켜진 게이트\n"
            "        run: |\n"
            "          echo setup\n"
            "          python -m fake.checker || true\n"
        )
        classified = _classify_from_fixture(tmp_path, ci_text)
        assert len(classified) == 1
        assert classified[0].reason == _REASON_GATE_SWALLOWING_TRUE
        assert classified[0].declaration is None

    def test_gate_call_declared_pending_task_is_clean(self, tmp_path: Path) -> None:
        ci_text = _make_ci_yaml(
            "      - name: 삼켜진 게이트\n"
            "        # pending-task:FAKE-TODO-TASK\n"
            "        run: |\n"
            "          echo setup\n"
            "          python -m fake.checker || true\n"
        )
        violations = _violations_from_fixture(tmp_path, ci_text, {"FAKE-TODO-TASK": "todo"})
        assert violations == []

    def test_scripts_py_invocation_with_trailing_true_is_flagged(self, tmp_path: Path) -> None:
        """`python -m` 뿐 아니라 `scripts/*.py` 직접·python 경유 실행도 게이트 호출로
        인정한다(과제 예시 3형태 중 나머지 2형태)."""
        ci_text = _make_ci_yaml(
            "      - name: 스크립트 게이트\n" "        run: scripts/foo/bar.py --check || true\n"
        )
        classified = _classify_from_fixture(tmp_path, ci_text)
        assert len(classified) == 1
        assert classified[0].reason == _REASON_GATE_SWALLOWING_TRUE

    def test_container_cleanup_trailing_true_is_not_flagged(self, tmp_path: Path) -> None:
        """대조군 — 실측 ci.yml :848 '컨테이너 정리' 스텝과 동형. `docker rm -f ... || true`는
        마지막(유일한) 줄이지만 게이트/검사기 호출이 아니므로 선언이 필요 없다(오탐 방지 —
        CLAUDE.md '변별력 없는 검증 스텝 금지': 오탐도 미탐만큼 나쁘다)."""
        ci_text = _make_ci_yaml(
            "      - name: 컨테이너 정리\n" "        run: docker rm -f whatever-container || true\n"
        )
        assert _classify_from_fixture(tmp_path, ci_text) == []

    def test_retry_loop_trailing_true_not_on_last_line_is_not_flagged(self, tmp_path: Path) -> None:
        """대조군 — 실측 ci.yml :801/:813 '/health/live 스모크' 스텝과 동형. 게이트 호출의
        `|| true`가 재시도 루프 안에 있고, 그 뒤 명시적 `exit`/`echo` 판정이 이어지면(즉
        `|| true`가 마지막 실행 줄이 아니면) 선언이 필요 없다."""
        ci_text = _make_ci_yaml(
            "      - name: 재시도 루프\n"
            "        run: |\n"
            "          code=$(python -m fake.checker || true)\n"
            '          if [ "$code" != "0" ]; then exit 1; fi\n'
            "          echo PASS\n"
        )
        assert _classify_from_fixture(tmp_path, ci_text) == []

    def test_diagnostic_log_trailing_true_before_explicit_exit_is_not_flagged(
        self, tmp_path: Path
    ) -> None:
        """대조군 — 실패 진단 로그 출력(`docker logs ... || true`) 바로 다음 줄이 명시적
        `exit 1`이면 그 진단 줄은 마지막 실행 줄이 아니므로 선언 불요."""
        ci_text = _make_ci_yaml(
            "      - name: 실패 진단\n"
            "        run: |\n"
            "          docker logs some-container || true\n"
            "          exit 1\n"
        )
        assert _classify_from_fixture(tmp_path, ci_text) == []


# ──────────────────────────────────────────────────────────────────────────
# 테스트 — pending-task 그랜드파더 만료 계약
# ──────────────────────────────────────────────────────────────────────────


class TestPendingTaskGrandfatherExpiry:
    def test_pending_task_referencing_missing_backlog_task_is_flagged(self, tmp_path: Path) -> None:
        ci_text = _make_ci_yaml(
            "      - name: 유예된 게이트\n"
            "        # pending-task:NONEXISTENT-TASK-XYZ\n"
            "        run: python -m fake.gate\n"
            "        continue-on-error: true\n"
        )
        violations = _violations_from_fixture(tmp_path, ci_text, {})
        assert len(violations) == 1
        assert "NONEXISTENT-TASK-XYZ" in violations[0]

    def test_pending_task_referencing_todo_task_is_clean(self, tmp_path: Path) -> None:
        ci_text = _make_ci_yaml(
            "      - name: 유예된 게이트\n"
            "        # pending-task:FAKE-TODO-TASK\n"
            "        run: python -m fake.gate\n"
            "        continue-on-error: true\n"
        )
        violations = _violations_from_fixture(tmp_path, ci_text, {"FAKE-TODO-TASK": "todo"})
        assert violations == []

    def test_pending_task_referencing_done_task_is_expired_violation(self, tmp_path: Path) -> None:
        """방치 시나리오 — 태스크는 끝났는데 유예 선언만 안 지워진 상태(red)."""
        ci_text = _make_ci_yaml(
            "      - name: 유예된 게이트\n"
            "        # pending-task:FAKE-DONE-TASK\n"
            "        run: python -m fake.gate\n"
            "        continue-on-error: true\n"
        )
        violations = _violations_from_fixture(tmp_path, ci_text, {"FAKE-DONE-TASK": "done"})
        assert len(violations) == 1
        assert "FAKE-DONE-TASK" in violations[0]
        assert "방치" in violations[0]


class TestLoadBacklogTaskStatuses:
    """`load_backlog_task_statuses`(ARCH-25 이식) 자체의 파일 I/O 동작."""

    def test_reads_id_and_status_from_real_files_on_disk(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        _write_task_yaml(tasks_dir, "FAKE-A", status="todo")
        _write_task_yaml(tasks_dir, "FAKE-B", status="done")
        assert load_backlog_task_statuses(tasks_dir) == {
            "FAKE-A": "todo",
            "FAKE-B": "done",
        }

    def test_missing_directory_returns_empty_dict(self, tmp_path: Path) -> None:
        assert load_backlog_task_statuses(tmp_path / "does-not-exist") == {}

    def test_malformed_yaml_file_is_skipped_not_raised(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "BROKEN.yaml").write_text("id: [unterminated\n", encoding="utf-8")
        _write_task_yaml(tasks_dir, "FAKE-OK", status="todo")
        assert load_backlog_task_statuses(tasks_dir) == {"FAKE-OK": "todo"}


# ──────────────────────────────────────────────────────────────────────────
# 테스트 — 수집기 파손 방어
# ──────────────────────────────────────────────────────────────────────────


class TestCollectorBreakageDefense:
    def test_missing_jobs_key_raises(self) -> None:
        with pytest.raises(AssertionError, match="jobs"):
            classify_workflow("not_jobs: {}\n")

    def test_empty_text_raises(self) -> None:
        with pytest.raises(AssertionError, match="jobs"):
            classify_workflow("")

    def test_step_boundary_mismatch_raises(self) -> None:
        """스텝이 이 저장소 관례(`- name:`으로 시작)를 어기면 원문 경계 스캔이 어긋난다 —
        조용히 빈 결과를 내는 대신 명시적으로 실패해야 한다(수집기 파손 방어,
        `declared_unwired_audit.CollectorError`와 동일 철학)."""
        ci_text = (
            "jobs:\n"
            "  fake-job:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"  # name: 없이 시작 — 관례 위반
            "      - name: 두번째 스텝\n"
            "        run: echo hi\n"
        )
        with pytest.raises(AssertionError, match="어긋난다"):
            classify_workflow(ci_text)


# ──────────────────────────────────────────────────────────────────────────
# 테스트 — 실제 ci.yml + 실제 backlog/tasks 통합(②의 실제 배선 증거)
# ──────────────────────────────────────────────────────────────────────────


class TestRealCiWorkflowIntegration:
    def _real_classified(self) -> list[ClassifiedStep]:
        if not _CI_PATH.is_file():
            raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 게이트 배선을 확인할 수 없다.")
        return classify_workflow(_CI_PATH.read_text(encoding="utf-8"))

    def test_detector_is_not_blind_finds_known_non_blocking_steps(self) -> None:
        """수집기 파손 방어(맹목 탐지 방지) — 0건 발견은 "전부 선언됨"과 구분 불가하므로,
        알려진 비차단 스텝 최소 1건(shellcheck)을 실제로 찾는지 먼저 확인한다. 이게 없으면
        아래 "위반 0건" 테스트가 탐지기가 죽어서 통과하는 것인지, 정말 전부 선언됐기
        때문인지 구분할 수 없다.

        [ARCH-23] data-pipeline의 qa_pipeline continue-on-error는 이제 제거됐다(그 스텝이
        더 이상 이 탐지기에 걸리지 않는 것 자체가 ARCH-23의 성공 증거 — 아래
        `test_qa_pipeline_step_no_longer_requires_declaration`이 명시적으로 고정한다)."""
        classified = self._real_classified()
        found = {(c.ref.job_key, c.reason) for c in classified}
        assert ("infra-shell", _REASON_CONTINUE_ON_ERROR) in found, (
            "infra-shell 잡의 shellcheck continue-on-error 스텝을 찾지 못했다 — "
            "탐지기가 깨졌을 가능성(수집기 파손)."
        )
        assert len(classified) >= 1

    def test_real_ci_workflow_has_zero_declaration_violations(self) -> None:
        classified = self._real_classified()
        task_statuses = load_backlog_task_statuses(_BACKLOG_TASKS_DIR)
        violations = validate_declarations(classified, task_statuses)
        assert violations == [], f"CI 강제 상태 선언 계약 위반: {violations}"

    def test_qa_pipeline_step_no_longer_requires_declaration(self) -> None:
        """②의 구체 증거(만료 계약 실현) — ARCH-23이 `continue-on-error`와 그 `pending-task:
        ARCH-23-qa-gate-enforcement` 선언을 함께 제거했으므로, data-pipeline 잡에는 더
        이상 이 탐지기가 걸릴 비차단 스텝이 없다. 이 테스트가 없으면 "선언이 사라진 것"과
        "스텝 자체가 사라진 것"을 구분할 수 없으므로, qa_pipeline 스텝 자체는 여전히
        존재함을 `tests/infra/test_qa_pipeline_wiring.py`를 통해 별도 고정한다(이 파일은
        그 파일과 계층이 달라 직접 import하지 않는다 — 여기서는 이 탐지기 관점의 결과만
        본다)."""
        classified = self._real_classified()
        matches = [
            c
            for c in classified
            if c.ref.job_key == "data-pipeline" and c.reason == _REASON_CONTINUE_ON_ERROR
        ]
        assert matches == [], (
            "data-pipeline 잡에 여전히 continue-on-error 비차단 스텝이 남아 있다 — "
            f"ARCH-23이 제거했어야 한다: {matches}"
        )

    def test_shellcheck_step_declares_by_design(self) -> None:
        """②의 구체 증거 — shellcheck 스텝이 by-design으로 등재됐다."""
        classified = self._real_classified()
        matches = [
            c
            for c in classified
            if c.ref.job_key == "infra-shell" and c.reason == _REASON_CONTINUE_ON_ERROR
        ]
        assert len(matches) == 1
        decl = matches[0].declaration
        assert decl is not None
        assert decl.kind == "by-design"
        assert decl.value  # 사유 문자열 비어있지 않음
