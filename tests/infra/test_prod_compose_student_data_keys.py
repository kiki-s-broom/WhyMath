"""SEC-36 — 운영 compose가 학생 데이터 암호화 키를 **빠짐없이 · 필수로** 앱에 넘기는가 (hermetic).

사고 경위(운영 배포 전 잠재 결함 · `docs/reviews/system_full_review_2026-09-25.md` §3-7):
SEC-31이 학생 답안·풀이 본문 키(`student_work_encryption_key`)를 Settings에 추가했지만 운영 compose
(`docker-compose.prod.yml`)는 그 키를 컨테이너에 넘기지 않았다. 앱 쪽 방어선
(`api/_crypto.py::require_student_work_cipher` — 운영인데 키가 없으면 부팅 거부)은
`config.is_production_like`(카카오·네이버 client_id 구성 여부)에 기대는데, compose가 OAuth 변수도
넘기지 않아 운영 스택이 '비운영'으로 판정됐다. 두 누락이 겹쳐 학생 답안 3테이블이 평문으로 저장되는
상태였다.

손으로 적는 필수 목록(`test_deploy_artifacts.py::_MUST_FAIL_CLOSED`)은 그 누락을 잡지 못했다 — 키를
추가한 사람이 목록도 함께 고쳐야만 성립하기 때문이다. 그래서 이 파일은 **Settings에서 유도**한다:

  ① Settings의 `*_encryption_key` 필드 전부가 운영 compose `app`에 전달된다. 선택으로 둘 키는 사유와
     함께 `_OPTIONAL_WITH_REASON`에 적고, 나머지는 `${VAR:?사유}` 필수다.
  ② 운영 판정 신호(OAuth client_id 두 개)가 `app`에 전달된다.
  ③ compose의 `:?` 필수 변수 전부를 CI `docker-build` 정상 렌더 스텝과 운영 런북 §1-2 자가검증이
     채운다 — compose만 늘리면 CI 렌더 스텝이 `docker compose config`에서 실패하고, 런북만 빠지면
     운영자 자가검증이 거짓 OK를 낸다.
  ④ 학생 데이터 키는 `app` 밖으로 새지 않는다(최소 권한 — retention-purge 등은 복호화하지 않는다).

`whymath_backend`를 import하지 않는다 — infra-contracts 잡은 백엔드를 설치하지 않는다. config.py는
AST로 읽는다. 유도식이 조용히 0건이 되면 위 검사들이 공허하게 통과하므로, 수락 기준이 이름으로
지목한 키는 리터럴로도 따로 단언한다(`_NAMED_STUDENT_DATA_KEYS`).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.prod.yml"
_CONFIG = _ROOT / "src" / "backend" / "whymath_backend" / "config.py"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_RUNBOOK = _ROOT / "docs" / "architecture" / "deployment_cd_runbook.md"

#: Settings의 환경변수 접두(`config.py` `env_prefix`).
_ENV_PREFIX = "WHYMATH_"

#: 선택(빈 값 허용)으로 두는 암호화 키와 그 근거. 여기 없는 `*_encryption_key`는 전부 필수다.
_OPTIONAL_WITH_REASON: dict[str, str] = {
    "WHYMATH_EVIDENCE_PAYLOAD_ENCRYPTION_KEY": (
        "evidence_event에는 평문 컬럼이 없어 키 부재 = 원문 미저장(평문 노출 경로 없음) · "
        "원문 payload 생산자 0건(encrypt_evidence_payload 호출부 · SEC-36 ④ 2026-09-27)"
    ),
}

#: 수락 기준이 이름으로 지목한 학생 데이터 키(대화·디바이스·학생 답안) — 리터럴로 적는다.
_NAMED_STUDENT_DATA_KEYS = (
    "WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY",
    "WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY",
    "WHYMATH_STUDENT_WORK_ENCRYPTION_KEY",
)

#: 운영 판정 신호 — `config.is_production_like`가 읽는 `kakao_configured`·`naver_configured`의 원천.
_PRODUCTION_SIGNAL_VARS = ("WHYMATH_KAKAO_CLIENT_ID", "WHYMATH_NAVER_CLIENT_ID")

_REQUIRED_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*):\?")


def _compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    return data


def _service_env(name: str) -> dict[str, str]:
    env = _compose()["services"][name].get("environment") or {}
    assert isinstance(env, dict), f"{name}.environment가 매핑이 아니다 — 이 검사는 매핑형만 읽는다"
    return {key: "" if value is None else str(value) for key, value in env.items()}


def _config_tree() -> ast.Module:
    return ast.parse(_CONFIG.read_text(encoding="utf-8"))


def _settings_encryption_key_envs() -> set[str]:
    """config.py `Settings`의 `*_encryption_key` 필드 → 환경변수 이름(`WHYMATH_` 접두 대문자)."""
    settings = [
        node
        for node in _config_tree().body
        if isinstance(node, ast.ClassDef) and node.name == "Settings"
    ]
    assert (
        len(settings) == 1
    ), f"config.py에서 Settings 클래스를 1개 찾아야 한다(찾음 {len(settings)})"
    return {
        _ENV_PREFIX + stmt.target.id.upper()
        for stmt in settings[0].body
        if isinstance(stmt, ast.AnnAssign)
        and isinstance(stmt.target, ast.Name)
        and stmt.target.id.endswith("_encryption_key")
    }


def _compose_required_vars() -> set[str]:
    """compose의 `${VAR:?사유}` 필수 변수 — YAML **값**에서만 모은다(헤더 주석의 예시 문구 제외)."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            found.update(_REQUIRED_RE.findall(node))

    walk(_compose())
    return found


def _ci_render_env_vars() -> set[str]:
    """CI `docker-build`의 정상 렌더 스텝이 `/tmp/deploy.env`에 채우는 변수 이름."""
    steps = yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]["docker-build"]["steps"]
    render = [step for step in steps if "/tmp/deploy.env" in (step.get("run") or "")]
    assert len(render) == 1, f"docker-build의 정상 렌더 스텝을 1개 찾아야 한다(찾음 {len(render)})"
    return set(re.findall(r'echo "([A-Z_][A-Z0-9_]*)=', render[0]["run"]))


def _runbook_required_vars() -> set[str]:
    """운영 런북 §1-2 자가검증의 `$required` 목록."""
    text = _RUNBOOK.read_text(encoding="utf-8")
    match = re.search(r"\$required\s*=\s*((?:'[A-Z_][A-Z0-9_]*',?\s*)+)", text)
    assert match, "런북 §1-2 자가검증의 `$required` 목록을 찾지 못했다"
    return set(re.findall(r"'([A-Z_][A-Z0-9_]*)'", match.group(1)))


# ──────────────────────────────────────────────────────────────────────────
# ① 학생 데이터 키 — Settings에서 유도 · 선택은 사유와 함께만
# ──────────────────────────────────────────────────────────────────────────
def test_settings_scan_finds_the_named_keys() -> None:
    """스캔 0건은 실패 — 유도식이 조용히 비면 아래 검사들이 공허하게 통과한다."""
    keys = _settings_encryption_key_envs()
    missing = set(_NAMED_STUDENT_DATA_KEYS) - keys
    assert not missing, (
        f"config.py Settings에서 지목한 키를 찾지 못했다: {sorted(missing)} — AST 스캔이 깨졌거나 "
        "필드 이름이 바뀌었다(이 파일의 유도식을 함께 고쳐야 한다)"
    )


def test_every_student_data_key_reaches_the_app() -> None:
    """① Settings의 `*_encryption_key` 전부가 `app`에 전달된다 — 필수는 `:?`, 선택은 `:-`."""
    app = _service_env("app")
    problems: list[str] = []
    for var in sorted(_settings_encryption_key_envs()):
        value = app.get(var)
        if value is None:
            problems.append(f"{var}: app에 전달되지 않는다(앱은 빈 값 = 평문 폴백으로 뜬다)")
        elif var in _OPTIONAL_WITH_REASON:
            if not value.startswith("${" + var + ":-"):
                problems.append(f"{var}: 선택 키는 `${{{var}:-}}` 형태여야 한다")
        elif not value.startswith("${" + var + ":?"):
            problems.append(f"{var}: 필수 키가 `${{{var}:?사유}}` 형태가 아니다")
    assert not problems, "운영 compose의 학생 데이터 키 전달 결함:\n  " + "\n  ".join(problems)


def test_named_student_data_keys_are_fail_closed() -> None:
    """① 수락 기준의 세 키(대화·디바이스·학생 답안)는 필수다 — 유도식과 독립된 리터럴 단언."""
    app = _service_env("app")
    not_required = [
        var
        for var in _NAMED_STUDENT_DATA_KEYS
        if not app.get(var, "").startswith("${" + var + ":?")
    ]
    assert not not_required, (
        f"필수(`:?`)가 아닌 학생 데이터 키: {not_required} — 비면 평문 저장 폴백이다"
        "(CLAUDE.md 절대 금기 '학생 데이터 암호화 저장')"
    )


def test_optional_allowlist_names_real_keys_with_reasons() -> None:
    """① 선택 목록은 실재하는 키만, 사유와 함께 — 죽은 항목이 새 키의 면제 통로가 되지 않게."""
    stale = set(_OPTIONAL_WITH_REASON) - _settings_encryption_key_envs()
    assert not stale, f"Settings에 없는 키가 선택 목록에 남아 있다: {sorted(stale)}"
    assert not set(_OPTIONAL_WITH_REASON) & set(
        _NAMED_STUDENT_DATA_KEYS
    ), "필수로 지목된 키가 선택 목록에 들어 있다"
    short = [var for var, reason in _OPTIONAL_WITH_REASON.items() if len(reason.strip()) < 20]
    assert not short, f"선택 사유가 비었거나 너무 짧다: {short}"


# ──────────────────────────────────────────────────────────────────────────
# ② 운영 판정 신호
# ──────────────────────────────────────────────────────────────────────────
def test_production_signal_reaches_the_app() -> None:
    """② `is_production_like`의 신호(OAuth client_id)가 `app`에 전달된다.

    먼저 운영 판정이 여전히 정확히 그 두 신호에 기대는지 AST로 확인한다 — 판정이 바뀌거나
    늘면(MGMT-03 다신호화) 이 테스트가 무엇을 지켜야 하는지도 바뀌므로 여기서 멈춰 다시 보게 한다.
    신호는 **`return` 식 안의 `getattr(settings, "<신호>", ...)` 인자**로만 읽는다 — 함수 전체의
    문자열을 보면 `hasattr` 검사와 오류 메시지에 남은 이름 때문에 판정식에서 신호를 빼도 통과한다
    (뮤테이션으로 실측한 결함).
    """
    functions = [
        node
        for node in _config_tree().body
        if isinstance(node, ast.FunctionDef) and node.name == "is_production_like"
    ]
    assert len(functions) == 1, "config.py에서 is_production_like를 찾지 못했다"
    decision_signals = {
        call.args[1].value
        for ret in ast.walk(functions[0])
        if isinstance(ret, ast.Return)
        for call in ast.walk(ret)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "getattr"
        and len(call.args) >= 2
        and isinstance(call.args[1], ast.Constant)
        and isinstance(call.args[1].value, str)
    }
    assert decision_signals == {"kakao_configured", "naver_configured"}, (
        f"is_production_like의 판정 신호가 바뀌었다(지금: {sorted(decision_signals)}) — "
        "_PRODUCTION_SIGNAL_VARS와 운영 compose 전달 목록을 함께 다시 판정하라"
    )
    app = _service_env("app")
    missing = [var for var in _PRODUCTION_SIGNAL_VARS if var not in app]
    assert not missing, (
        f"운영 판정 신호가 app에 전달되지 않는다: {missing} — 운영 스택이 '비운영'으로 판정돼 운영 전용 "
        "안전장치(암호화 키 fail-closed·스키마 버전 가드)가 꺼진다"
    )


# ──────────────────────────────────────────────────────────────────────────
# ③ 필수 변수 정합 — compose ⊆ CI 렌더 env · compose ⊆ 런북 자가검증
# ──────────────────────────────────────────────────────────────────────────
def test_compose_required_scan_is_not_empty() -> None:
    """③의 전제 — 필수 변수 스캔이 비면 정합 검사가 공허하게 통과한다."""
    required = _compose_required_vars()
    assert (
        set(_NAMED_STUDENT_DATA_KEYS) <= required
    ), f"필수 스캔 결과가 이상하다: {sorted(required)}"


def test_ci_render_env_fills_every_required_var() -> None:
    """③ CI `docker-build`의 정상 렌더 스텝이 compose의 필수 변수를 전부 채운다.

    이 스텝은 docker가 필요해 로컬 CI 미러가 재현하지 못한다 — 목록 누락은 PR CI에서야 red로
    드러난다. 그 전에 여기서 막는다.
    """
    missing = _compose_required_vars() - _ci_render_env_vars()
    assert not missing, (
        f"CI docker-build 정상 렌더 스텝(/tmp/deploy.env)이 채우지 않는 필수 변수: {sorted(missing)} "
        "— 그 스텝의 `docker compose config`가 실패한다"
    )


def test_runbook_selfcheck_lists_every_required_var() -> None:
    """③ 운영 런북 §1-2 자가검증이 compose의 필수 변수를 전부 본다 — 빠지면 거짓 OK를 낸다."""
    missing = _compose_required_vars() - _runbook_required_vars()
    assert not missing, (
        f"런북 §1-2 `$required`에 없는 compose 필수 변수: {sorted(missing)} — 운영자 자가검증이 "
        "그 키를 보지 않아 '전부 OK' 뒤에 compose가 기동을 거부한다"
    )


# ──────────────────────────────────────────────────────────────────────────
# ④ 최소 권한
# ──────────────────────────────────────────────────────────────────────────
def test_student_data_keys_stay_in_the_app() -> None:
    """④ 학생 데이터 키는 `app`에만 — 다른 서비스는 복호화하지 않는다(유출 시 피해 범위 축소)."""
    keys = _settings_encryption_key_envs()
    leaks = [
        (service, var)
        for service in _compose()["services"]
        if service != "app"
        for var in sorted(keys & set(_service_env(service)))
    ]
    assert not leaks, f"app 밖으로 주입된 학생 데이터 키: {leaks}"
