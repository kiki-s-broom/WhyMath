r"""공유 계약 fixture(`data/` 최상위) · backend 잡 입력 경로 ↔ CI `changes` 경로 필터의
**트리거 배선** 동결.

왜 이 테스트가 있는가 (COLLAB-04 → COLLAB-07 / `collaboration_module_gap_review_r3.md`
§3 D5 + §8-③④⑤ — 2026-08-11)
-----------------------------------------------------------------------------------------
`ci.yml`의 `changes` 잡은 PR diff를 정규식에 걸어 하위 잡의 실행 여부를 정한다. backend 잡
필터에는 `data/notation_contract.json`·`data/render_contract.json` **두 계약만** 개별 나열돼
있었고, 나머지 6종(`access_matrix`·`visual_style_contract`·`scene_contract`·
`segmentation_contract`·`notation_support_manifest`·`notation_missing_baseline`)은 없었다.
즉 **계약 파일만 고치는 PR은 backend 잡이 skip돼 그 계약의 거버넌스 테스트가 돌지 않았다** —
그 게이트가 막으라고 만들어진 바로 그 드리프트 벡터다. 항상 도는 `infra-contracts` 잡은
`tests/infra`만 실행하므로 대체 경로가 아니다(계약 소비 테스트는 전부 `tests/backend/**`).

`COLLAB-04`(1차)는 그 논리를 최상위 `data/*.json`에만 적용했고, **같은 논리가 성립하는 두 축을
남겼다**(r3 §8-③ 실측). `COLLAB-07`(2차)이 상환한 것:

- **`data/corpus/`** — backend 잡의 *상시* 게이트 스텝(표기 커버리지 `notation_coverage`)이
  `data/corpus/problem_bank_*/problems.jsonl`을 읽는데 코퍼스 변경이 backend 잡을 깨우지
  않았다. 코퍼스에 신규 표기를 넣으면 그 게이트가 `exit 1`을 내지만 **그 PR은 게이트를 실행조차
  하지 않았다**.
- **`schemas/`** — `web`·`mobile` 필터에는 있는데 `backend`에만 없었다. 그런데
  `tests/backend/test_failure_prevention_manifest.py`가 `schemas/v1.1/*.yaml` 존재를 하드
  단언한다.
- **죽은 `corpus` 플래그** — `changes` 잡이 내보내는 `corpus` 출력의 유일한 소비처가
  `data_pipeline` 필터로 게이트된 잡 *내부의 스텝*이라, 코퍼스 단독 PR에서는 잡이 통째 skip돼
  그 스텝도 실행되지 않았다. 플래그가 아무것도 제어하지 못하는 상태였다.

`tests/infra/test_test_suite_wiring.py`(OPS-10)가 *"테스트 디렉터리가 CI 실행 경로에
도달하는가"*를 동결한다면, 이 파일은 그 **한 단계 안쪽**을 동결한다 — *"그 테스트·게이트를 깨울
입력 경로가 필터 안에 있는가"*. OPS-10 축은 정당하게 통과했는데도 사각이 남았던 이유가 정확히
이 층이다("돌긴 도는데 깨울 입력이 필터 밖").

분류 기준 (무엇을 '계약 fixture'로 보는가 — 추론 아님)
--------------------------------------------------
- **대상** = `data/` **최상위**(재귀 아님) **전 파일**. `.json` suffix 한정이 아니다 —
  `COLLAB-04` 시점의 suffix 한정은 최상위 비-json 계약(`*.yaml` 등)을 계약으로 **인식조차 하지
  못해** 가드 green·CI skip이 성립했다(r3 §8-④ 합성 실증). 위치로 잡으면 그 사각이 없다.
- **대상 밖** = `data/` 하위 디렉터리. 단 하위 중 backend 잡이 *실제로 읽는* 루트는
  `_BACKEND_INPUT_ROOTS`가 별도로 강제한다(아래 계약 ⑥) — "하위는 별도 축이 담당"이라는
  진술은 그 축이 실재할 때만 유효하고, `corpus` 플래그의 경우 실재하지 않았다.
- **예외**는 `_NON_CONTRACT_ALLOWLIST`에 **사유를 명시**해야만 통과한다(무사유 예외 금지 —
  OPS-06·OPS-08 선례). 사라진 파일에 대한 죽은 예외도 실패시킨다.

검증 계약 (각 항목은 변별력이 확인된 것만 — CLAUDE.md "변별력 없는 검증 스텝 금지")
--------------------------------------------------------------------------------
① `data/` 최상위 계약 fixture 전건이 **강제 대상 잡 전건의 필터**에 매치한다(= 계약 단독 수정
   PR이 그 잡들을 깨운다). 하나라도 안 걸리면 RED.
② **강제 대상 잡 목록은 하드코딩이 아니라 `ci.yml`에서 파생**된다 — `changes` 잡이 선언한
   output 전건에서 *사유 명시 제외목록*을 뺀 나머지다. 신규 잡이 output을 추가하면 자동으로
   강제 대상이 되고, 빼려면 사유를 적어야 한다(구 `_ENFORCED_OUTPUTS = ("backend","web")`
   하드코딩은 신규 잡·mobile을 영원히 보지 못했다 — r3 §8-⑤).
③ **집행 정합** — 각 계약을 실제로 읽는 소비 테스트가 `tests/backend/**`에 1건 이상 있다.
   판정 기준은 **비-docstring 문자열 리터럴**(AST)이다. 구 구현은 *파일 전체 substring*이라
   docstring에 이름만 적어도 "소비"로 통과했다(r3 §8-④ 실증) — 주석·docstring은 AST에
   남지 않거나 docstring 노드로 식별돼 제외되므로 "언급"과 "읽기"가 갈린다.
④ 파서가 위장하지 않는다 — `ci.yml`을 못 읽거나, 필터 정규식을 못 찾거나, 플래그 변수 ↔ 잡
   output 매핑에 실패하거나, 테스트 파일 AST 파싱이 깨지면 "위반 0 통과"가 아니라 **예외로
   실패**한다(예외 타입명 동반 — 침묵 실패 금지). "0건 통과"와 "측정 실패"는 절대 같은 색이면
   안 된다.
⑤ 판정 함수 자체의 변별력을 상시 봉인 — 계약 하나를 뺀 합성 필터를 넣으면 검출되고, 완전한
   필터는 통과한다(양성 대조 포함 = 무차별 실패가 아님).
⑥ **backend 잡 입력 루트** — backend 잡이 읽는 하위 경로(`data/corpus/`·`schemas/`)가 backend
   필터 안에 있다. 각 루트는 *그 루트를 읽는 실물 근거*(게이트 스텝·소비 테스트)와 함께 등재되며,
   근거가 사라지면 "통과"가 아니라 예외다.
⑦ **죽은 플래그 금지** — 스텝 `if`가 참조하는 `changes` 플래그는 그 스텝이 속한 잡의 `if`도
   참조해야 한다. 아니면 그 플래그만 참인 PR에서 잡이 통째 skip돼 스텝이 영영 실행되지 않는다
   (죽은 `corpus` 플래그가 정확히 이 형태였다).
⑧ **동결 테스트 입력** — `FROZEN_INPUT_PATHS`를 선언한 `tests/backend/**`의 동결 테스트
   **전부**가 읽는 파일(실패정의 문서·`gates.yaml`·정본 엔티티 모델 문서 …)이 backend 필터
   안에 있다. 경로 목록은 하드코딩이 아니라 각 테스트의 상수를 **AST로 파싱**해 얻고(계약 ②와
   같은 파생 원칙 — 두 벌이면 한쪽만 고쳐진 채 "위반 0"이 나온다), 대상 테스트도 하드코딩이
   아니라 **전수 스캔**으로 얻는다(OPS-62 — 종전 단일 파일 하드코딩은 가드 자신이 전수가
   아니었다). 선언 테스트를 **하나도 못 찾으면 통과가 아니라 예외**다(스캔 0건 = 실패).
   2026-08-30 PR #910 리뷰(P1)가 지목한 사각이며, ⑥과 같은 구조의 다른 입력 축이다.

의도적으로 검증하지 않는 것 (정직한 공백)
--------------------------------------
- **잡 `if`의 불리언 의미론**은 모델링하지 않는다 — 계약 ⑦은 플래그 *참조 유무*만 본다.
  `needs.changes.outputs.corpus == 'false'` 같은 역참조도 "참조"로 계상된다(현행 0건).
  required check 강제 여부는 `test_required_checks_doc.py` 담당이다.
- **정규식 방언** — CI 러너는 `grep -qE`(POSIX ERE), 이 테스트는 `re`로 판정한다. r3 §8-⑤의
  17케이스 차등 테스트 결과 현행 필터가 쓰는 문법 범위에서 **두 엔진은 동치**다(전건 same).
- **git `core.quotePath` 전제(미해결 · r3 §8-⑤)** — 진짜 발산은 정규식 엔진이 아니라 *입력
  표현*에 있다. `git diff --name-only`는 비ASCII 경로를 `"data/\355\221\234..."`처럼 **인용 +
  8진 이스케이프**로 내보내므로 CI의 `grep -qE`는 선행 `"` 때문에 `^data/`가, 후행 `"` 때문에
  `$`가 깨져 **SKIP**인데, 이 가드는 `Path.iterdir()` 원문자열로 판정해 **RUN**이다. 즉
  **비ASCII 이름의 계약 파일이 하나라도 생기면 가드 green / CI skip의 false-green이 성립한다.**
  현재 해당 파일 0건이라 `COLLAB-07`은 이를 고치지 않고 **전제로 명시만** 한다(범위 밖).
  깨지는 조건 자체는 `test_ascii_only_premise_for_contract_paths`가 상시 감시한다 — 비ASCII
  이름의 계약이 착지하는 순간 RED가 되므로, 전제가 조용히 무너지지는 않는다.
- 계약 **내용**의 정합(예: `access_matrix.json` #8의 참조 무결성)은 이 파일의 축이 아니다
  (COLLAB-05 소관).
- `data_pipeline` 필터 정규식 자체의 확장·새 CI 잡 신설은 `COLLAB-07` 범위 밖이다.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_YAML = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_DATA_DIR = _REPO_ROOT / "data"
_BACKEND_TESTS_DIR = _REPO_ROOT / "tests" / "backend"

# 계약 ⑧ — 동결 테스트가 읽는 입력 경로의 선언 상수 이름. **파일을 하드코딩하지 않는다**:
# `tests/backend/**`의 테스트 전건을 훑어 이 상수를 선언한 모듈을 *전부* 대상으로 삼는다
# (OPS-62). 종전에는 `test_failure_definition_freeze.py` 한 파일만 가리켜서, 다른 동결 테스트
# (`test_canonical_entity_model_freeze.py`)의 입력이 필터 밖이어도 "위반 0"이 났다 — 사각을
# 막으라고 만든 가드 자신의 범위가 좁았던 네 번째 동형 사각(PR #997 실증). 경로 목록 자체는
# 여전히 여기 두지 않는다: 단일 진실 원천은 각 동결 테스트의 상수이고 이 파일은 AST로 읽는다.
_FROZEN_PATHS_CONST = "FROZEN_INPUT_PATHS"

# 계약 fixture로 보지 *않을* 최상위 data/ 파일 — 반드시 사유를 적는다(무사유 예외 금지).
# 형식: {"파일명": "왜 계약이 아닌가 + 누가 대신 검사하는가"}
# 2026-08-11 실측 기준 예외 0건(8종 전부가 tests/backend의 소비 테스트를 가진다).
_NON_CONTRACT_ALLOWLIST: dict[str, str] = {}

# `changes` 잡 output 중 계약 트리거 강제 **대상이 아닌** 것 — 사유 필수(계약 ②).
# 나머지 output은 자동으로 강제 대상이 된다. 신규 잡이 output을 추가하면 여기에 사유를 적어
# 빼거나, 아무것도 안 하면 강제된다(누락이 아니라 과강제로 기울이는 fail-safe 방향).
_NON_CONTRACT_OUTPUT_EXCLUSIONS: dict[str, str] = {
    "data_pipeline": (
        "L1 파이프라인 잡. 최상위 계약 fixture를 읽는 소비 테스트가 tests/data_pipeline에 없고, "
        "필터 확장은 COLLAB-07 범위 밖으로 지정됨(r3 §8-③ 하지 말 것)."
    ),
    "docker": (
        "이미지 빌드·기동 스모크 전용. 계약 파일 내용을 판정하지 않으며 ci.yml 주석이 data/ 제외를 "
        "명시적 설계로 선언한다(OPS-03)."
    ),
    "authoring": (
        "PB-13 저작 도구 회귀 잡(corpus-authoring) 트리거. 결정론 스켈레톤 생성기·적재 배치의 "
        "*로직*만 검증하며 최상위 계약 fixture를 읽지 않는다 — 실측(2026-09-01): 이식 테스트 60개와 "
        "생성기·배치 src 60개 전건에서 access_matrix·notation_contract·notation_support_manifest·"
        "render_contract·scene_contract·segmentation_contract·visual_style_contract 참조 0/60. "
        "계약이 바뀌어도 이 잡의 판정은 달라지지 않으므로 트리거 대상이 아니다. "
        "죽은 플래그가 되지 않는지는 계약 ⑦(test_no_dead_changes_flag)이 별도로 강제한다."
    ),
    "corpus": (
        "잡 트리거가 아니라 잡 *내부 스텝* 게이트용 보조 플래그(ARCH-21 qa_pipeline). "
        "최상위 계약이 아니라 data/corpus/ 변경을 재는 축이라 계약 매치 대상이 아니다. "
        "죽은 플래그가 되지 않는지는 계약 ⑦(test_no_dead_changes_flag)이 별도로 강제한다."
    ),
}

# backend 잡이 *실제로 읽는* data/ 하위·비-data 입력 루트 → 그 루트가 backend 필터 안에 있어야
# 한다(계약 ⑥). 값은 "왜 이 루트가 backend 입력인가"의 근거이며, 근거 검증은 각 테스트가 실물로
# 수행한다(문자열 사유만으로 통과시키지 않는다 — r3 §8-⑥ "사유의 진실성" 결함 클래스 회피).
_BACKEND_INPUT_ROOTS: dict[str, str] = {
    "data/corpus/": (
        "backend 잡의 상시 게이트 스텝 `python -m whymath_backend.l3.notation_coverage`가 "
        "data/corpus/problem_bank_*/problems.jsonl을 전수 스캔한다(코퍼스 신규 표기 → exit 1)."
    ),
    "schemas/": (
        "tests/backend가 schemas/v1.1/*.yaml 존재·내용을 단언한다"
        "(test_failure_prevention_manifest.py의 Part 12 근거 방어 목록 등)."
    ),
}

# `grep -qE '<정규식>'; then` 다음 줄의 `<변수>=true` → (정규식, 플래그 변수) 추출.
_FILTER_BLOCK_RE = re.compile(
    r"grep\s+-qE\s+'(?P<regex>[^']*)'\s*;\s*then\s*\n\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)=true"
)

# `echo "backend=$be" >> "$GITHUB_OUTPUT"` → (잡 output 이름, 플래그 변수) 추출.
# 상수 하드코딩 대신 스크립트에서 파생시켜 변수명이 바뀌어도 매핑이 따라가게 한다.
_OUTPUT_BIND_RE = re.compile(
    r'echo\s+"(?P<output>[A-Za-z_][A-Za-z0-9_]*)=\$(?P<var>[A-Za-z_][A-Za-z0-9_]*)"'
)

# `needs.changes.outputs.<flag>` 참조 추출(잡·스텝 `if` 표현식용).
_FLAG_REF_RE = re.compile(r"needs\.changes\.outputs\.([A-Za-z_][A-Za-z0-9_]*)")


# ── ci.yml 파싱 (계약 ④: 실패는 예외로) ────────────────────────────────────────


def _extract_jobs(spec: Any, source: str) -> dict[str, Any]:
    """스펙에서 jobs 매핑을 꺼낸다 — 공백/비매핑이면 예외(파서 무력화 ≠ 통과)."""
    if not isinstance(spec, dict):
        raise AssertionError(f"{source}: 워크플로 YAML이 매핑으로 파싱되지 않았다.")
    jobs = spec.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise AssertionError(f"{source}: jobs 블록이 비었다 — 파서가 배선을 읽지 못하는 상태다.")
    return jobs


def _load_ci_jobs() -> dict[str, Any]:
    if not _CI_YAML.is_file():
        raise AssertionError(f"{_CI_YAML}: CI 워크플로 파일이 없다 — 배선을 읽을 수 없다.")
    try:
        spec = yaml.safe_load(_CI_YAML.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # 침묵 실패 금지 — 예외 타입명을 남긴다.
        raise AssertionError(
            f"{_CI_YAML}: YAML 파싱 실패 {type(exc).__name__} — 측정 실패이지 통과가 아니다."
        ) from exc
    return _extract_jobs(spec, str(_CI_YAML))


def _iter_steps(job: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    steps = job.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if isinstance(step, dict):
            yield step


def _iter_run_steps(job: Mapping[str, Any]) -> Iterator[str]:
    for step in _iter_steps(job):
        if isinstance(step.get("run"), str):
            yield step["run"]


def _changes_filter_script(jobs: Mapping[str, Any]) -> str:
    """`changes` 잡에서 경로 필터를 세팅하는 run 스크립트를 돌려준다(못 찾으면 예외)."""
    changes = jobs.get("changes")
    if not isinstance(changes, dict):
        raise AssertionError("ci.yml: `changes` 잡이 없다 — 경로 필터 정의를 읽을 수 없다.")
    scripts = [run for run in _iter_run_steps(changes) if "GITHUB_OUTPUT" in run]
    if not scripts:
        raise AssertionError(
            "ci.yml: `changes` 잡에서 GITHUB_OUTPUT을 쓰는 run 스텝을 찾지 못했다 — "
            "필터 정의를 읽지 못하는 상태다(측정 실패이지 통과가 아니다)."
        )
    return "\n".join(scripts)


def _declared_outputs(jobs: Mapping[str, Any]) -> list[str]:
    """`changes` 잡이 선언한 output 이름 전건(계약 ②의 파생 원천). 비면 예외."""
    changes = jobs.get("changes")
    if not isinstance(changes, dict):
        raise AssertionError("ci.yml: `changes` 잡이 없다 — output 선언을 읽을 수 없다.")
    outputs = changes.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise AssertionError(
            "ci.yml: `changes` 잡의 outputs 블록이 비었다 — 강제 대상 잡을 파생시킬 수 없다"
            "(빈 목록으로 '위반 0'을 만들지 않는다)."
        )
    return sorted(outputs)


def _enforced_outputs(jobs: Mapping[str, Any]) -> list[str]:
    """계약 ② — 강제 대상 잡 output = 선언 전건 − 사유 명시 제외목록."""
    declared = _declared_outputs(jobs)
    enforced = [name for name in declared if name not in _NON_CONTRACT_OUTPUT_EXCLUSIONS]
    if not enforced:
        raise AssertionError(
            f"강제 대상 잡 output이 0건이다(선언={declared}) — 제외목록이 전부를 삼켰다."
        )
    return enforced


def _filter_regex_by_output(script: str, enforced: Sequence[str]) -> dict[str, str]:
    """필터 스크립트 → {잡 output 이름: 경로 정규식}. 매핑 실패는 예외(계약 ④)."""
    var_to_regex = {m.group("var"): m.group("regex") for m in _FILTER_BLOCK_RE.finditer(script)}
    if not var_to_regex:
        raise AssertionError(
            "필터 스크립트에서 `grep -qE '...'; then <flag>=true` 블록을 하나도 찾지 못했다 — "
            "파서가 필터를 읽지 못하는 상태다."
        )
    output_to_var = {m.group("output"): m.group("var") for m in _OUTPUT_BIND_RE.finditer(script)}
    if not output_to_var:
        raise AssertionError(
            '필터 스크립트에서 `echo "<output>=$<flag>"` 바인딩을 하나도 찾지 못했다 — '
            "플래그 변수와 잡 output을 연결할 수 없다."
        )
    resolved: dict[str, str] = {}
    for output, var in output_to_var.items():
        if var in var_to_regex:
            resolved[output] = var_to_regex[var]
    missing = [o for o in enforced if o not in resolved]
    if missing:
        raise AssertionError(
            f"필터 정규식을 해석하지 못한 잡 output: {missing} — "
            f"발견한 플래그={sorted(var_to_regex)} · 바인딩={sorted(output_to_var)}. "
            "필터 문법이 바뀌었다면 이 파서를 함께 고쳐라(조용한 통과 금지)."
        )
    return resolved


def _backend_filter(jobs: Mapping[str, Any]) -> str:
    """backend 잡 경로 필터 정규식(계약 ⑥ 전용 — 없으면 예외)."""
    regex_by_output = _filter_regex_by_output(_changes_filter_script(jobs), ["backend"])
    return regex_by_output["backend"]


# ── 계약 fixture 목록·소비처 ───────────────────────────────────────────────────


def _contract_fixture_paths() -> list[str]:
    """`data/` 최상위 **전 파일**(suffix 무관) 중 허용목록을 뺀 계약 fixture의 상대 경로."""
    if not _DATA_DIR.is_dir():
        raise AssertionError(f"{_DATA_DIR}: data 디렉터리가 없다 — 계약 목록을 읽을 수 없다.")
    names = sorted(p.name for p in _DATA_DIR.iterdir() if p.is_file())
    if not names:
        raise AssertionError(
            f"{_DATA_DIR}: 최상위 파일이 0건이다 — 스캔이 무력화된 상태다"
            "(빈 목록으로 '위반 0'을 만들지 않는다)."
        )
    return [f"data/{name}" for name in names if name not in _NON_CONTRACT_ALLOWLIST]


def _string_literals(path: Path) -> frozenset[str]:
    """파이썬 파일의 **비-docstring 문자열 리터럴** 전건(AST 기준).

    구 구현(파일 전체 substring)은 docstring·주석의 *언급*만으로 "소비"를 인정했다(r3 §8-④
    실증). 주석은 AST에 남지 않고, docstring은 여기서 명시 제외하므로 "읽기 대상으로 코드에
    등장한 경로 리터럴"만 남는다. f-string 조각(`ast.JoinedStr` 내부 `Constant`)도 포함된다.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:  # 침묵 실패 금지 — 예외 타입명 동반.
        raise AssertionError(
            f"{path}: AST 파싱 실패 {type(exc).__name__}: {exc} — 소비 판정이 불가능한 상태이며 "
            "'소비 없음'으로 접지 않는다(측정 실패 ≠ 통과)."
        ) from exc

    docstring_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            first = body[0] if body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_ids.add(id(first.value))

    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_ids
    }
    return frozenset(literals)


@lru_cache(maxsize=1)
def _backend_test_literal_index() -> tuple[tuple[str, frozenset[str]], ...]:
    """`tests/backend/**`의 (상대경로, 비-docstring 문자열 리터럴 집합) 색인 — 1회 스캔 캐시."""
    if not _BACKEND_TESTS_DIR.is_dir():
        raise AssertionError(f"{_BACKEND_TESTS_DIR}: 백엔드 테스트 트리가 없다.")
    entries = [
        (path.relative_to(_REPO_ROOT).as_posix(), _string_literals(path))
        for path in sorted(_BACKEND_TESTS_DIR.rglob("*.py"))
    ]
    if not entries:
        raise AssertionError(f"{_BACKEND_TESTS_DIR}: *.py가 0건이다 — 소비 스캔이 무력화된 상태다.")
    return tuple(entries)


def _literal_consumers(needle: str) -> list[str]:
    """`tests/backend/**`에서 `needle`을 **코드 리터럴로** 담고 있는 테스트 파일 목록."""
    return [
        rel for rel, literals in _backend_test_literal_index() if any(needle in s for s in literals)
    ]


def _backend_test_consumers(fixture_name: str) -> list[str]:
    """계약 ③ — 이 계약 파일을 *읽는* 테스트 파일 목록(언급 아님 · AST 리터럴 기준)."""
    return _literal_consumers(fixture_name)


# ── 순수 판정 함수 (실 레포와 결함 주입이 같은 함수를 쓴다 — 중복 파서 금지) ──────


def _trigger_violations(
    regex_by_output: Mapping[str, str],
    contracts: Sequence[str],
    enforced: Sequence[str],
) -> list[str]:
    """계약 × 강제 대상 잡에서 필터에 매치하지 않는 조합을 위반으로 모은다."""
    violations: list[str] = []
    for output in enforced:
        pattern = regex_by_output.get(output)
        if pattern is None:
            violations.append(f"[{output}] 필터 정규식을 찾지 못했다")
            continue
        compiled = re.compile(pattern)
        for path in contracts:
            if not compiled.search(path):
                violations.append(f"[{output}] {path} — 필터에 매치하지 않는다(잡 SKIP)")
    return violations


def _dead_flag_violations(jobs: Mapping[str, Any]) -> list[str]:
    """계약 ⑦ — 스텝 `if`가 참조하는 플래그를 그 잡의 `if`가 참조하지 않으면 위반.

    그 플래그만 참인 PR에서는 잡 자체가 skip되므로 스텝은 영영 실행되지 않는다. 죽은 `corpus`
    플래그(ARCH-21 qa_pipeline)가 정확히 이 형태였다 — 플래그는 계산되고 스텝 조건도 걸려 있는데
    잡 게이트가 그 축을 모르니 아무것도 제어하지 못했다.
    """
    violations: list[str] = []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_if = str(job.get("if") or "")
        if not job_if:
            continue  # 무조건 실행 잡 — 스텝 플래그는 항상 도달 가능하다.
        job_flags = set(_FLAG_REF_RE.findall(job_if))
        for step in _iter_steps(job):
            step_if = str(step.get("if") or "")
            for flag in sorted(set(_FLAG_REF_RE.findall(step_if))):
                if flag not in job_flags:
                    name = step.get("name") or step.get("uses") or "(무명 스텝)"
                    violations.append(
                        f"[{job_name}] 스텝 '{name}'이 `{flag}` 플래그로 게이트되는데 "
                        f"잡 `if`는 그 플래그를 모른다 — {flag}만 참인 PR에서 잡 통째 SKIP → "
                        "스텝 영구 미실행(죽은 플래그)."
                    )
    return violations


# ── 계약 ①·② : 실제 ci.yml 판정 ───────────────────────────────────────────────


def test_contract_fixtures_trigger_enforced_jobs() -> None:
    """계약 ①② — `data/` 최상위 계약 fixture 전건이 강제 대상 잡 필터 전건을 깨운다.

    계약 파일만 고치는 PR에서 그 계약의 거버넌스 테스트가 skip되면 게이트가 자기 계약을 지키지
    못한다(D5). 필터를 좁히면(예: `*_contract.json`만 매치) 이 단언이 RED가 된다.
    """
    jobs = _load_ci_jobs()
    enforced = _enforced_outputs(jobs)
    regex_by_output = _filter_regex_by_output(_changes_filter_script(jobs), enforced)
    contracts = _contract_fixture_paths()

    violations = _trigger_violations(regex_by_output, contracts, enforced)
    listed = "\n".join(f"  · {v}" for v in violations)
    current = "\n".join(f"  · {out}: {regex_by_output.get(out)!r}" for out in enforced)
    assert not violations, (
        "계약 fixture가 CI 트리거 축 밖이다 — 그 파일만 수정하는 PR에서 소비 잡이 SKIP된다"
        f"(COLLAB-04/07 · r3 §3 D5·§8-③ 재발).\n{listed}\n필터 현황:\n{current}"
    )


def test_enforced_outputs_are_derived_not_hardcoded() -> None:
    """계약 ② — 강제 대상은 `ci.yml` 선언에서 파생되고, 제외는 사유·실재가 검증된다.

    구 구현의 `_ENFORCED_OUTPUTS = ("backend", "web")` 하드코딩은 신규 잡이 추가돼도 영원히
    보지 못했다(r3 §8-⑤). 이제 신규 output은 자동으로 강제 대상이 되며, 빼려면 사유를 적어야
    한다. 사라진 output에 대한 죽은 제외도 실패시킨다(다음 동명 output을 조용히 면제시킨다).
    """
    jobs = _load_ci_jobs()
    declared = set(_declared_outputs(jobs))
    enforced = set(_enforced_outputs(jobs))

    dead = sorted(set(_NON_CONTRACT_OUTPUT_EXCLUSIONS) - declared)
    assert not dead, (
        f"제외목록에 있으나 ci.yml이 선언하지 않는 output: {dead} — 죽은 제외는 다음 동명 "
        "output을 조용히 면제시킨다. 항목을 지워라."
    )
    for name, reason in _NON_CONTRACT_OUTPUT_EXCLUSIONS.items():
        assert reason.strip(), f"제외 '{name}'의 사유가 비었다 — 무사유 예외 금지."

    assert enforced == declared - set(_NON_CONTRACT_OUTPUT_EXCLUSIONS)
    # 클라이언트 축(mobile)이 강제 대상에 실제로 들어 있는지 못박는다 — r3 §8-⑤가 지목한
    # "하드코딩이라 mobile을 영영 보지 않는다"가 재발하면 여기서 RED.
    assert "mobile" in enforced, (
        f"mobile이 강제 대상에서 빠졌다(현재 강제={sorted(enforced)}) — mobile 골든도 "
        "data/ 최상위 계약을 읽는다. 빼려면 사유를 _NON_CONTRACT_OUTPUT_EXCLUSIONS에 적어라."
    )


# ── 계약 ⑥ : backend 잡 입력 루트(data/corpus/·schemas/) ──────────────────────


def test_backend_filter_covers_backend_job_input_roots() -> None:
    """계약 ⑥ — backend 잡이 읽는 입력 루트가 backend 필터 안에 있다(r3 §8-③).

    실측 표본은 **실재 파일**에서 뽑는다(가상의 경로로 통과/실패를 만들지 않는다).
    """
    jobs = _load_ci_jobs()
    pattern = re.compile(_backend_filter(jobs))

    violations: list[str] = []
    for root, rationale in _BACKEND_INPUT_ROOTS.items():
        sample = _sample_repo_path_under(root)
        if not pattern.search(sample):
            violations.append(f"  · {root} (표본 {sample}) — {rationale}")
    assert not violations, (
        "backend 잡이 읽는 입력 루트가 backend 필터 밖이다 — 그 경로만 바꾸는 PR에서 backend 잡이 "
        "SKIP돼 상시 게이트가 자기 입력 변경에 깨어나지 않는다(COLLAB-07 ①).\n"
        + "\n".join(violations)
        + f"\n현재 backend 필터: {_backend_filter(jobs)!r}"
    )


def test_backend_input_root_rationales_are_backed_by_real_artifacts() -> None:
    """계약 ⑥ 보조 — 루트 등재 사유가 **실물 근거**로 뒷받침되는지 확인한다.

    사유 문자열이 비어있지 않은지만 보는 검사는 "사유의 진실성"을 보지 못한다(r3 §8-⑥가 지목한
    결함 클래스 — `COLLAB-04` 주석의 틀린 정당화가 정확히 그렇게 통과했다). 여기서는 근거가
    실재하는지를 저장소에서 직접 확인하고, 사라졌으면 통과가 아니라 **실패**시킨다.
    """
    jobs = _load_ci_jobs()

    # ⓐ data/corpus/ — backend 잡에 notation_coverage 게이트 스텝이 실재하고, 그 CLI가
    #    problem_bank 코퍼스를 읽는다.
    backend_job = jobs.get("backend")
    assert isinstance(backend_job, dict), "ci.yml: backend 잡이 없다 — 계약 ⑥의 전제가 사라졌다."
    runs = "\n".join(_iter_run_steps(backend_job))
    assert "whymath_backend.l3.notation_coverage" in runs, (
        "backend 잡에서 표기 커버리지 게이트 스텝을 찾지 못했다 — data/corpus/ 등재 사유의 "
        "근거가 사라졌다. 게이트가 옮겨갔다면 _BACKEND_INPUT_ROOTS를 함께 고쳐라(조용한 통과 금지)."
    )
    cli_src = _REPO_ROOT / "src" / "backend" / "whymath_backend" / "l3" / "notation_coverage.py"
    assert cli_src.is_file(), f"{cli_src}: 표기 커버리지 CLI 소스가 없다 — 근거 검증 불가."
    cli_text = cli_src.read_text(encoding="utf-8")
    assert "problem_bank_*/problems.jsonl" in cli_text and '"corpus"' in cli_text, (
        f"{cli_src}: 코퍼스 스캔 경로 표현을 찾지 못했다 — CLI가 더 이상 data/corpus를 읽지 "
        "않는다면 _BACKEND_INPUT_ROOTS에서 빼라."
    )

    # ⓑ schemas/ — tests/backend가 schemas/ 경로 리터럴을 코드에서 쓴다(docstring 언급 아님).
    schema_consumers = _literal_consumers("schemas/v1.1/")
    assert schema_consumers, (
        "tests/backend에서 `schemas/v1.1/` 경로 리터럴을 쓰는 테스트를 찾지 못했다 — "
        "schemas/ 등재 사유의 근거가 사라졌다(사유만 남고 사실이 사라지는 상태를 통과시키지 않는다)."
    )


def _sample_repo_path_under(root: str) -> str:
    """등재 루트 아래의 **실재하는** 파일 하나를 표본으로 고른다(없으면 예외)."""
    base = _REPO_ROOT / root
    if not base.is_dir():
        raise AssertionError(f"{base}: 등재된 입력 루트가 저장소에 없다 — 표본을 뽑을 수 없다.")
    for path in sorted(base.rglob("*")):
        if path.is_file():
            return path.relative_to(_REPO_ROOT).as_posix()
    raise AssertionError(f"{base}: 파일이 0건이다 — 빈 표본으로 '위반 0'을 만들지 않는다.")


# ── 계약 ⑧ : 동결 테스트의 입력 경로가 backend 필터 안에 있는가 ────────────────


def _parse_frozen_input_paths(source: str, label: str) -> tuple[str, ...] | None:
    """모듈 소스에서 최상위 `FROZEN_INPUT_PATHS` 선언을 **AST로** 읽는다(import 불가 — 이 잡에는
    backend 패키지가 설치되지 않는다).

    반환: 선언이 없으면 `None`(이 모듈은 대상이 아니다), 있으면 문자열 튜플. 선언은 있는데 파서가
    읽을 수 없는 형태(빈 튜플·f-string·연산·비문자열 원소)면 **예외** — 그런 선언은 강제 대상에서
    조용히 빠지므로 "없음"과 구별해 크게 알린다.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # 예외 타입명 동반 — 침묵 실패 금지
        raise AssertionError(f"{label}: AST 파싱 실패({type(exc).__name__}: {exc})") from exc

    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if not any(isinstance(t, ast.Name) and t.id == _FROZEN_PATHS_CONST for t in targets):
            continue
        value = node.value
        if not isinstance(value, ast.Tuple) or not value.elts:
            raise AssertionError(
                f"{label}: {_FROZEN_PATHS_CONST}가 비어있지 않은 리터럴 튜플이 아니다 "
                "— 파서가 읽을 수 없는 형태(f-string·연산 등)로 바뀌면 강제가 무력해진다."
            )
        paths = [
            e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if len(paths) != len(value.elts):
            raise AssertionError(
                f"{label}: {_FROZEN_PATHS_CONST}에 문자열 상수가 아닌 원소가 있다 — "
                "AST로 확정할 수 없는 경로는 강제 대상에서 조용히 빠진다."
            )
        return tuple(paths)
    return None


def _frozen_input_declarations(
    tests_root: Path = _BACKEND_TESTS_DIR,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """`tests_root/**`의 pytest 수집 모듈(`test_*.py` · `*_test.py`) 전건을 훑어 `FROZEN_INPUT_PATHS`를
    선언한 (테스트 상대경로, 경로 튜플) 목록을 돌려준다 — **전수 스캔**이 대상을 정한다(단일 파일
    하드코딩 금지 · OPS-62).

    **스캔 0건은 통과가 아니라 예외다**(CLAUDE.md 2026-09-01 ④): 종전 하드코딩은 최소 1건을 보장했으나
    전수 스캔은 그 보장이 사라지므로, 상수 이름이 바뀌거나 동결 테스트가 전부 옮겨지면 "위반 0"으로
    위장되지 않고 여기서 RED가 난다. `tests_root`를 받는 이유는 합성 트리로 이 스캐너 자체의 변별력을
    실측하기 위해서다(실 레포와 결함 주입이 같은 함수를 쓴다 — 중복 파서 금지).
    """
    if not tests_root.is_dir():
        raise AssertionError(f"{tests_root}: 백엔드 테스트 트리가 없다.")
    root_for_label = tests_root if tests_root != _BACKEND_TESTS_DIR else _REPO_ROOT
    declarations: list[tuple[str, tuple[str, ...]]] = []
    # pytest 기본 수집 패턴 **둘 다**(`python_files` 기본값 = test_*.py · *_test.py — backend
    # pyproject는 이를 오버라이드하지 않는다). 한쪽만 훑으면 `canonical_freeze_test.py` 같은
    # 정상 수집 모듈의 선언이 조용히 빠진다(PR #1005 Codex P2).
    candidates = set(tests_root.rglob("test_*.py")) | set(tests_root.rglob("*_test.py"))
    for path in sorted(candidates):
        label = path.relative_to(root_for_label).as_posix()
        paths = _parse_frozen_input_paths(path.read_text(encoding="utf-8"), label)
        if paths is not None:
            declarations.append((label, paths))
    if not declarations:
        raise AssertionError(
            f"{tests_root}: {_FROZEN_PATHS_CONST}를 선언한 동결 테스트가 0건이다 — 상수 이름이 바뀌었거나 "
            "동결 테스트가 전부 사라졌다. 빈 목록으로 '위반 0'을 만들지 않는다(스캔 0건 = 실패)."
        )
    return tuple(declarations)


def _frozen_input_paths() -> list[str]:
    """선언 전건의 경로를 평탄화한 목록(선언 순서 보존·중복 제거)."""
    seen: dict[str, None] = {}
    for _label, paths in _frozen_input_declarations():
        for rel in paths:
            seen.setdefault(rel, None)
    return list(seen)


def _frozen_input_violations(
    declarations: Sequence[tuple[str, Sequence[str]]],
    backend_filter: str,
    *,
    repo_root: Path | None = _REPO_ROOT,
) -> list[str]:
    """순수 판정 — 선언된 입력 경로 중 backend 필터에 매치되지 않는 것(`테스트: 경로`).

    `repo_root`가 주어지면 각 경로의 **실재**도 요구한다(표본을 가상 경로로 만들지 않는다). 합성
    주입에서는 `None`을 넘겨 실재 검사를 끈다 — 판정 로직은 양쪽이 같은 함수를 쓴다.
    """
    pattern = re.compile(backend_filter)
    violations: list[str] = []
    for test_rel, paths in declarations:
        for rel in paths:
            if repo_root is not None and not (repo_root / rel).is_file():
                raise AssertionError(
                    f"{test_rel}: 동결 테스트가 선언한 입력 {rel!r}이 저장소에 없다 — 표본을 뽑을 수 없다."
                )
            if not pattern.search(rel):
                violations.append(f"  · {test_rel}: {rel}")
    return violations


def test_backend_filter_covers_frozen_freeze_test_inputs() -> None:
    """계약 ⑧ — `FROZEN_INPUT_PATHS`를 선언한 동결 테스트 **전부**의 입력이 backend 필터 안에 있다.

    동결 테스트는 정본 문서·서명 기록을 해시로 동결한다. 그런데 그 입력이 backend 필터 밖이면
    **그 파일만 고치는 PR에서 backend 잡이 SKIP**되고, skip은 required check에서 *충족*으로
    계상된다 — 동결 테스트가 막으라고 만들어진 바로 그 벡터(문서·서명의 조용한 수정)에서 테스트가
    실행되지 않는 상태다. data/corpus·schemas(COLLAB-07 ①②)·G0 동결 입력(PR #910 P1)·정본 엔티티
    모델 문서(PR #997)가 겪은 같은 형태의 사각이며, 마지막 것은 **이 가드가 한 파일만 봐서** 놓쳤다.

    실측 표본은 **실재 파일 경로**를 쓴다(가상 경로로 통과/실패를 만들지 않는다).
    """
    jobs = _load_ci_jobs()
    declarations = _frozen_input_declarations()
    violations = _frozen_input_violations(declarations, _backend_filter(jobs))
    assert not violations, (
        "동결 테스트의 입력이 backend 필터 밖이다 — 그 파일만 바꾸는 PR에서 backend 잡이 "
        "SKIP돼 동결이 집행되지 않는다(PR #910 P1 · PR #997).\n"
        + "\n".join(violations)
        + f"\n현재 backend 필터: {_backend_filter(jobs)!r}"
    )


def test_frozen_input_parser_is_discriminating() -> None:
    """계약 ⑧ 보조 — 파서·판정의 변별력(양성·음성 대조 양쪽).

    "못 찾았으니 위반 없음"이 아니라 **예외**임을 실측한다(빈 목록 위장 금지).
    """
    # ⓐ 실제 선언이 읽힌다(양성 대조 — 무차별 실패가 아님). 전수 스캔이 단일 파일 시절보다
    #    좁아지지 않았음을 실 레포로 못 박는다: G0 동결 테스트 + 정본 엔티티 모델 동결 테스트.
    declarations = _frozen_input_declarations()
    declared_tests = {label for label, _ in declarations}
    assert {
        "tests/backend/schema/test_failure_definition_freeze.py",
        "tests/backend/db/test_canonical_entity_model_freeze.py",
    } <= declared_tests, f"전수 스캔이 기대 선언 테스트를 놓쳤다: {sorted(declared_tests)}"
    paths = _frozen_input_paths()
    assert paths and all(isinstance(p, str) for p in paths)

    # ⓑ 현행 필터가 그 경로를 실제로 매치한다 + 편입 이전 필터였다면 검출된다(음성 대조).
    jobs = _load_ci_jobs()
    assert not _frozen_input_violations(declarations, _backend_filter(jobs))
    legacy = r"^(src/backend/|tests/backend/|data/[^/]+$|data/corpus/|schemas/)"
    assert _frozen_input_violations(declarations, legacy, repo_root=None), (
        "편입 이전 필터로도 전건이 매치된다면 이 가드는 아무것도 막지 못한다 — "
        "동결 입력이 이미 다른 경로로 커버되는지 재확인하라."
    )


def test_frozen_input_scan_follows_new_freeze_tests(tmp_path: Path) -> None:
    """계약 ⑧ 보조 — **합성 트리**로 스캐너·판정의 변별력(OPS-62 ④).

    ⓐ 새 동결 테스트가 늘면 가드가 *따라온다*(하드코딩이면 못 따라온다) ⓑ 그 입력이 필터 밖이면
    RED ⓒ 선언 0건이면 통과가 아니라 예외 ⓓ 읽을 수 없는 선언(빈 튜플·비문자열)도 예외.
    실 레포 판정과 **같은 함수**를 쓴다 — 주입용 파서를 따로 두면 그것이 위장이 된다.
    """
    tree = tmp_path / "backend"
    (tree / "db").mkdir(parents=True)
    (tree / "schema").mkdir()
    # ⓒ 선언 0건 — 스캔 0건은 실패다.
    (tree / "db" / "test_nothing.py").write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="0건"):
        _frozen_input_declarations(tree)

    # ⓐ 신규 동결 테스트 2건을 합성 추가 — 스캔이 둘 다 따라온다.
    (tree / "schema" / "test_a_freeze.py").write_text(
        'FROZEN_INPUT_PATHS: tuple[str, ...] = ("docs/a.md", "backlog/gates.yaml")\n',
        encoding="utf-8",
    )
    (tree / "db" / "test_b_freeze.py").write_text(
        'FROZEN_INPUT_PATHS = ("docs/architecture/b.md",)\n', encoding="utf-8"
    )
    # pytest의 두 번째 기본 수집 패턴(`*_test.py`)도 대상이다 — 한쪽만 훑으면 정상 수집 모듈의
    # 선언이 조용히 빠진다(Codex P2). 비수집 이름(helpers.py)은 선언해도 대상이 아니다.
    (tree / "db" / "c_freeze_test.py").write_text(
        'FROZEN_INPUT_PATHS = ("docs/c.md",)\n', encoding="utf-8"
    )
    (tree / "db" / "helpers.py").write_text(
        'FROZEN_INPUT_PATHS = ("docs/not_collected.md",)\n', encoding="utf-8"
    )
    declarations = _frozen_input_declarations(tree)
    assert [label for label, _ in declarations] == [
        "db/c_freeze_test.py",
        "db/test_b_freeze.py",
        "schema/test_a_freeze.py",
    ]

    # ⓑ 판정 — 필터가 둘 중 하나만 덮으면 나머지가 위반으로 잡힌다(과소 검출 금지).
    only_gates = r"^(backlog/gates\.yaml$)"
    violations = _frozen_input_violations(declarations, only_gates, repo_root=None)
    assert violations == [
        "  · db/c_freeze_test.py: docs/c.md",
        "  · db/test_b_freeze.py: docs/architecture/b.md",
        "  · schema/test_a_freeze.py: docs/a.md",
    ]
    assert not _frozen_input_violations(declarations, r"^(docs/|backlog/)", repo_root=None)

    # ⓓ 읽을 수 없는 선언은 "없음"으로 접히지 않고 예외다.
    (tree / "db" / "test_b_freeze.py").write_text("FROZEN_INPUT_PATHS = ()\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="리터럴 튜플"):
        _frozen_input_declarations(tree)
    (tree / "db" / "test_b_freeze.py").write_text(
        'FROZEN_INPUT_PATHS = ("docs/x.md", 3)\n', encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="문자열 상수가 아닌"):
        _frozen_input_declarations(tree)


# ── 계약 ⑦ : 죽은 플래그 금지 ─────────────────────────────────────────────────


def test_no_dead_changes_flag() -> None:
    """계약 ⑦ — 스텝 게이트에 쓰인 `changes` 플래그를 그 잡의 `if`도 알고 있다.

    죽은 `corpus` 플래그(r3 §8-③): 플래그는 계산되고 스텝 `if`도 걸려 있었지만, 그 스텝이 사는
    `data-pipeline` 잡의 `if`가 `data_pipeline` 플래그만 보므로 **코퍼스 단독 PR에서 잡이 통째
    skip** → 스텝은 한 번도 실행될 수 없었다. 플래그가 존재하는 것과 발화하는 것은 다르다.
    """
    jobs = _load_ci_jobs()
    violations = _dead_flag_violations(jobs)
    assert not violations, "죽은 `changes` 플래그:\n" + "\n".join(f"  · {v}" for v in violations)


# ── 계약 ③ : 집행 정합(깨운 잡에 그 계약을 보는 검사가 있는가) ─────────────────


def test_every_contract_fixture_has_a_backend_test_consumer() -> None:
    """계약 ③ — 각 계약 fixture를 **읽는** 소비 테스트가 `tests/backend/**`에 1건 이상 있다.

    트리거를 붙여도 그 계약을 검사하는 테스트가 없으면 잡을 깨우는 의미가 없다. 판정은 AST
    리터럴 기준이라 docstring에 이름만 적은 테스트는 소비로 계상되지 않는다(구 substring 판정의
    사각 — r3 §8-④). 새 계약이 소비 테스트 없이 착지하면 여기서 RED.
    (해당 테스트가 실제 CI 잡의 수집 범위에 드는지는 `test_test_suite_wiring.py`가 동결한다.)
    """
    contracts = _contract_fixture_paths()
    assert _BACKEND_TESTS_DIR.is_dir(), f"{_BACKEND_TESTS_DIR}: 백엔드 테스트 트리가 없다."

    orphans = [path for path in contracts if not _backend_test_consumers(Path(path).name)]
    assert not orphans, (
        "계약 fixture인데 `tests/backend/**`에 소비 테스트가 없다 — 트리거를 붙여도 볼 사람이 "
        "없다(계약을 검사하는 테스트를 붙이거나, 계약이 아니라면 사유와 함께 "
        "_NON_CONTRACT_ALLOWLIST에 등재하라).\n" + "\n".join(f"  · {p}" for p in orphans)
    )


def test_allowlist_entries_have_reasons_and_exist() -> None:
    """계약 ③ 보조 — 허용목록은 사유 필수이며, 사라진 파일에 대한 죽은 예외를 남기지 않는다."""
    for name, reason in _NON_CONTRACT_ALLOWLIST.items():
        assert reason.strip(), f"허용목록 '{name}'의 사유가 비었다 — 무사유 예외 금지."
        assert (_DATA_DIR / name).is_file(), (
            f"허용목록 '{name}'에 해당하는 파일이 data/에 없다 — 죽은 예외는 다음 동명 파일을 "
            "조용히 면제시킨다. 항목을 지워라."
        )


def test_ascii_only_premise_for_contract_paths() -> None:
    """정직한 공백의 **감시 장치**(r3 §8-⑤ · COLLAB-07 ⑥) — 비ASCII 계약 파일명 0건 전제.

    `git diff --name-only`는 `core.quotePath` 기본값에서 비ASCII 경로를 인용 + 8진 이스케이프로
    내보내므로 CI의 `grep -qE '^data/...'`는 SKIP인데 이 가드는 `iterdir()` 원문자열로 RUN이다.
    즉 비ASCII 이름 계약이 생기면 **가드 green / CI skip**의 false-green이 성립한다. 그 조건이
    실제로 발생하는 순간 조용히 통과하지 않도록, 전제를 문서에만 적지 않고 여기서 감시한다.
    (해결 자체는 COLLAB-07 범위 밖 — 발생 시 별도 태스크로 등재한다.)
    """
    offenders = [p for p in _contract_fixture_paths() if not p.isascii()]
    assert not offenders, (
        "비ASCII 이름의 계약 파일이 생겼다 — 이 가드의 전제(경로 표현 동일)가 깨졌다. CI의 grep은 "
        "인용·8진 이스케이프된 경로를 받아 SKIP인데 가드는 RUN이라 false-green이 성립한다. "
        "COLLAB-07 범위 밖이므로 태스크로 등재하고 필터를 quotePath-안전하게 고쳐라.\n"
        + "\n".join(f"  · {p}" for p in offenders)
    )


# ── 계약 ④ : 파서가 위장하지 않는지 ───────────────────────────────────────────


def test_parser_fails_loudly_on_broken_workflow() -> None:
    """계약 ④ — 워크플로/필터를 못 읽으면 '0건 통과'가 아니라 예외로 실패한다."""
    with pytest.raises(AssertionError, match="jobs 블록이 비었다"):
        _extract_jobs({"name": "empty", "on": ["push"]}, source="fake.yml")
    with pytest.raises(AssertionError, match="매핑으로 파싱되지 않았다"):
        _extract_jobs(None, source="fake.yml")
    with pytest.raises(AssertionError, match="`changes` 잡이 없다"):
        _changes_filter_script({"backend": {"steps": []}})
    with pytest.raises(AssertionError, match="GITHUB_OUTPUT을 쓰는 run 스텝"):
        _changes_filter_script({"changes": {"steps": [{"run": "echo hi"}]}})
    with pytest.raises(AssertionError, match="outputs 블록이 비었다"):
        _declared_outputs({"changes": {"outputs": {}}})


def test_filter_parser_fails_loudly_on_unreadable_syntax() -> None:
    """계약 ④ — 필터 문법이 파서 밖으로 바뀌면 조용히 통과하지 않고 예외로 실패한다."""
    # grep 블록은 있으나 output 바인딩이 없는 경우
    with pytest.raises(AssertionError, match="바인딩을 하나도 찾지 못했다"):
        _filter_regex_by_output(
            "if printf x | grep -qE '^src/'; then\n  be=true\nfi\n", ["backend"]
        )
    # output 바인딩은 있으나 grep 블록이 없는 경우
    with pytest.raises(AssertionError, match="블록을 하나도 찾지 못했다"):
        _filter_regex_by_output('echo "backend=$be" >> "$GITHUB_OUTPUT"\n', ["backend"])
    # 강제 대상 잡 하나(web)의 필터를 해석하지 못하는 경우
    partial = (
        "if printf x | grep -qE '^src/backend/'; then\n  be=true\nfi\n"
        'echo "backend=$be" >> "$GITHUB_OUTPUT"\n'
        'echo "web=$web" >> "$GITHUB_OUTPUT"\n'
    )
    with pytest.raises(AssertionError, match="필터 정규식을 해석하지 못한 잡 output"):
        _filter_regex_by_output(partial, ["backend", "web"])


def test_literal_scanner_fails_loudly_on_unparsable_file(tmp_path: Path) -> None:
    """계약 ④ — 소비 스캔 대상이 파싱 불가면 '소비 없음'이 아니라 예외 타입명과 함께 실패한다."""
    broken = tmp_path / "broken_test.py"
    broken.write_text("def f(:\n    pass\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="AST 파싱 실패 SyntaxError"):
        _string_literals(broken)


# ── 계약 ⑤ : 판정 함수의 변별력 봉인 (결함 주입 + 양성 대조) ────────────────────


_ENFORCED_SAMPLE = ("backend", "web")
_COMPLETE_FILTER = {
    "backend": r"^(src/backend/|tests/backend/|data/[^/]+$)",
    "web": r"^(src/web/|data/[^/]+$)",
}
_LEGACY_INDIVIDUAL_FILTER = {
    # 사고 당시의 형태 — 개별 나열이라 새 계약(access_matrix)이 빠져 있다.
    "backend": r"^(src/backend/|tests/backend/|data/notation_contract\.json$)",
    "web": r"^(src/web/|data/notation_contract\.json$)",
}
_SAMPLE_CONTRACTS = ["data/access_matrix.json", "data/notation_contract.json"]


def test_judge_passes_on_complete_filter() -> None:
    """계약 ⑤ 양성 대조 — 계약 전건을 덮는 필터에서는 위반 0(무차별 실패가 아니다)."""
    assert _trigger_violations(_COMPLETE_FILTER, _SAMPLE_CONTRACTS, _ENFORCED_SAMPLE) == []


def test_judge_detects_missing_contract_in_filter() -> None:
    """계약 ⑤ 결함 주입 — 개별 나열에서 한 계약이 빠지면 두 잡 모두에서 검출된다."""
    violations = _trigger_violations(_LEGACY_INDIVIDUAL_FILTER, _SAMPLE_CONTRACTS, _ENFORCED_SAMPLE)
    assert len(violations) == 2, violations
    assert any(v.startswith("[backend] data/access_matrix.json") for v in violations)
    assert any(v.startswith("[web] data/access_matrix.json") for v in violations)


def test_judge_detects_json_only_pattern_missing_non_json_contract() -> None:
    """계약 ⑤ 결함 주입 — `.json` 한정 접두 패턴은 최상위 비-json 계약을 놓친다.

    이 결함이 현실적인 이유: 계약이 늘 json이라는 보장이 없다(`data/policy_contract.yaml`
    형태의 합성 사례로 r3 §8-④가 실증). 구 가드는 대상 자체를 `.json`으로 걸러 **계약으로
    인식조차 하지 못했고**, 그래서 가드 green·CI skip이 성립했다.
    """
    json_only = {
        "backend": r"^(src/backend/|data/[^/]+\.json$)",
        "web": r"^(src/web/|data/[^/]+\.json$)",
    }
    violations = _trigger_violations(json_only, ["data/policy_contract.yaml"], _ENFORCED_SAMPLE)
    assert len(violations) == 2, violations


def test_judge_detects_narrowed_pattern() -> None:
    """계약 ⑤ 결함 주입 — 접두 패턴을 `*_contract.json`으로 좁히면 비-contract 계약이 검출된다.

    이 결함이 현실적인 이유: `access_matrix.json`·`notation_support_manifest.json`처럼 이름에
    `_contract`가 없는 계약이 실재한다. "계약 파일은 이름에 contract가 들어간다"는 추론이
    그대로 사각이 된다.
    """
    narrowed = {
        "backend": r"^(src/backend/|data/[a-z_]+_contract\.json$)",
        "web": r"^(src/web/|data/[a-z_]+_contract\.json$)",
    }
    violations = _trigger_violations(narrowed, ["data/access_matrix.json"], _ENFORCED_SAMPLE)
    assert len(violations) == 2, violations


def test_judge_reports_missing_output_instead_of_passing() -> None:
    """계약 ⑤ — 필터 자체가 없는 잡은 '위반 0'이 아니라 위반으로 보고된다."""
    violations = _trigger_violations({"backend": r"^data/"}, _SAMPLE_CONTRACTS, _ENFORCED_SAMPLE)
    assert any("[web] 필터 정규식을 찾지 못했다" in v for v in violations), violations


def test_dead_flag_judge_detects_and_acquits() -> None:
    """계약 ⑦ 변별력 — 죽은 플래그 형태는 검출하고, 잡 `if`가 아는 형태는 통과시킨다."""
    dead = {
        "data-pipeline": {
            "if": "needs.changes.outputs.data_pipeline == 'true'",
            "steps": [{"name": "qa", "if": "needs.changes.outputs.corpus == 'true'", "run": "x"}],
        }
    }
    violations = _dead_flag_violations(dead)
    assert len(violations) == 1, violations
    assert "corpus" in violations[0] and "죽은 플래그" in violations[0]

    live = {
        "data-pipeline": {
            "if": (
                "needs.changes.outputs.data_pipeline == 'true' || "
                "needs.changes.outputs.corpus == 'true'"
            ),
            "steps": [{"name": "qa", "if": "needs.changes.outputs.corpus == 'true'", "run": "x"}],
        }
    }
    assert _dead_flag_violations(live) == []

    # 잡 `if`가 없으면(무조건 실행) 스텝 플래그는 항상 도달 가능 — 무차별 실패가 아니다.
    unconditional = {
        "always": {"steps": [{"name": "s", "if": "needs.changes.outputs.corpus == 'true'"}]}
    }
    assert _dead_flag_violations(unconditional) == []
