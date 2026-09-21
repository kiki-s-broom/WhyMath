"""배포 산출물 계약 동결 테스트 (hermetic — docker 데몬·실 호스트 불요).

OPS-03-deploy-cd-iac: 프로덕션/스테이징 배포 자산(`Dockerfile`·`docker-compose.prod.yml`·
`.env.prod.example`·CI/CD 워크플로)이 지켜야 할 안전 계약을 파일 수준에서 동결한다.
docker 실행이 필요한 검증(이미지가 실제로 빌드·기동되는가)은 CI `docker-build` 잡이 맡고,
여기서는 **실행 없이도 확정 가능한 계약**만 본다:

  ① **demo와의 분리** — `docker-compose.demo.yml`(일회용 시연·trust 인증·볼륨 없음·55432)의
     설정이 운영 스택에 유입되지 않는다. 특히 `POSTGRES_HOST_AUTH_METHOD: trust` 부재.
  ② **영속성** — db·redis가 named volume에 붙는다(demo는 볼륨이 없어 컨테이너 삭제 =
     데이터 소멸). 운영 스택에서 이 차이는 곧 학생 데이터 소실 여부다.
  ③ **시크릿 0 + fail-closed** — 자격증명 리터럴이 없고(`${...}` 참조만), 필수 변수는
     `${VAR:?사유}` 형식이라 미설정 시 compose가 *기동을 거부*한다. 조용한 기본값 기동 금지
     (CLAUDE.md "API 키·시크릿 하드코딩 금지"·"침묵 실패 금지").
  ④ **이미지 계약** — 멀티스테이지·비루트 USER·시크릿 ARG/ENV 부재·`/health/live`
     HEALTHCHECK·레포 레이아웃 보존(editable 설치 + data 동봉). 마지막 항목은 런타임 코드가
     `parents[5]`로 `data/corpus`를 읽기 때문에 깨지면 교수법 팩 로드가 실패한다.
  ⑤ **CI 게이트 실재** — ci.yml에 `docker-build` 잡과 `/health/live` 스모크·fail-closed
     검사가 살아 있다. 이 잡이 사라지면 위 계약들은 "그렇게 써 뒀다"는 주장만 남는다.
  ⑥ **배포 워크플로의 정직성** — deploy.yml은 수동 트리거 전용이고, 대상 시크릿 미설정 시
     명시 실패하며(조용한 성공 금지), 시크릿 값을 echo하지 않는다.
  ⑦ **문서-구현 정합** — compose가 요구하는 모든 변수가 `.env.prod.example`에 키로 존재하고,
     그 템플릿에는 값이 하나도 채워져 있지 않다(ASCII 전용).
  ⑧ **보존 파기 스케줄 배선(SEC-12)** — `retention-purge` 서비스가 compose에 정의돼 있고
     `privacy.retention_purge_cli`를 실제로 호출한다. `privacy/retention_purge_cli.py`는
     완비돼 있었지만 그 CLI를 부르는 cron·Celery beat 정의가 0건이라 보존 정책이 *집행되지
     않는 상태*였다(`docs/architecture/account_security_gap_review.md` D6). 이 서비스 정의를
     지우면 이 테스트가 깨진다 — "존재함 ≠ 돌아감"(OPS-03/08/10/11 선례).

실제 배포 실행 절차·롤백은 런북 `docs/architecture/deployment_cd_runbook.md`가 담당한다.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.prod.yml"
_DOCKERFILE = _ROOT / "Dockerfile"
_ENV_EXAMPLE = _ROOT / ".env.prod.example"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"
_GITIGNORE = _ROOT / ".gitignore"

# 자격증명성 키 판별 — 이 이름이 붙은 값은 리터럴이면 안 된다(반드시 ${...} 참조).
_SECRETISH = re.compile(r"(PASSWORD|SECRET|TOKEN|API_KEY|_KEY$)", re.IGNORECASE)


def _compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    return data


def _compose_text() -> str:
    return _COMPOSE.read_text(encoding="utf-8")


def _compose_config_text() -> str:
    """주석을 제외한 설정 라인만 — 계약 검사가 '금지 사항을 설명하는 주석'에 반응하면 안 된다.

    (헤더 주석은 `POSTGRES_HOST_AUTH_METHOD: trust`·`${VAR:?사유}` 같은 문구를 *금지 근거*로
    인용한다. 그 인용을 위반으로 오판하면 테스트가 문서화를 처벌하게 된다.)
    """
    return "\n".join(
        line
        for line in _COMPOSE.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    )


def _workflow(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


# ──────────────────────────────────────────────────────────────────────
# 존재·파싱
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "path",
    [_COMPOSE, _DOCKERFILE, _ENV_EXAMPLE, _CI, _DEPLOY],
    ids=["compose.prod", "Dockerfile", "env.example", "ci.yml", "deploy.yml"],
)
def test_artifact_exists(path: Path) -> None:
    """산출물 실재 — 경로 이동/개명 시 계약 테스트가 유령이 되는 것 방지."""
    assert path.is_file(), f"배포 산출물 부재: {path}"


def test_compose_parses_as_yaml() -> None:
    """compose.prod가 YAML로 파싱된다(`${VAR:?...}` 보간 문법 포함)."""
    data = _compose()
    assert set(data) >= {"services", "volumes"}, "services·volumes 최상위 키가 있어야 한다"


# ──────────────────────────────────────────────────────────────────────
# ① demo와의 분리
# ──────────────────────────────────────────────────────────────────────
def test_no_trust_auth_anywhere() -> None:
    """① prod 스택에 trust 인증이 없다 — demo(비밀번호 없음)의 유일한 결정적 차이."""
    text = _compose_config_text()
    assert "POSTGRES_HOST_AUTH_METHOD" not in text, (
        "docker-compose.prod.yml에 POSTGRES_HOST_AUTH_METHOD가 등장한다 — "
        "trust 인증은 demo(일회용) 전용이며 운영 DB에서는 금지"
    )
    # 값 수준 검사 — 어떤 서비스의 어떤 env도 값이 "trust"이면 안 된다. (fail-closed 메시지
    # 안의 "trust 인증 금지" 같은 *설명 문구*는 값이 아니므로 여기 걸리지 않는다.)
    trust_values = [(svc, key) for svc, key, value in _iter_env_pairs() if value.strip() == "trust"]
    assert not trust_values, f"값이 trust인 설정 존재: {trust_values}"
    db_env = _compose()["services"]["db"]["environment"]
    assert "POSTGRES_PASSWORD" in db_env, "운영 DB는 비밀번호 인증이어야 한다"


def test_no_demo_assets_reused() -> None:
    """① demo 컨테이너명·포트가 운영 스택에 섞이지 않는다(오조작 시 일회용 DB 오인 방지)."""
    text = _compose_text()
    for token in ("whymath-demo-db", "55432", "docker-compose.demo"):
        # 주석에서 '혼동 금지'로 언급하는 것은 허용하되, 설정 값으로 쓰이면 안 된다.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert (
                token not in stripped
            ), f"운영 compose의 설정 라인에 demo 자산({token})이 유입됨: {line}"


def test_demo_compose_untouched_contract() -> None:
    """① demo compose는 여전히 일회용 계약(trust·볼륨 없음)을 유지한다 — 두 파일의 역할 분리."""
    demo = yaml.safe_load((_ROOT / "docker-compose.demo.yml").read_text(encoding="utf-8"))
    demo_db = demo["services"]["demo-db"]
    assert demo_db["environment"]["POSTGRES_HOST_AUTH_METHOD"] == "trust"
    assert "volumes" not in demo_db, "demo DB에 볼륨이 생기면 '일회용' 전제가 깨진다"


# ──────────────────────────────────────────────────────────────────────
# ② 영속성
# ──────────────────────────────────────────────────────────────────────
def test_db_and_redis_use_named_volumes() -> None:
    """② db·redis 데이터가 named volume에 영속된다(컨테이너 교체가 데이터 소실이 아니게)."""
    data = _compose()
    top_volumes = data["volumes"]
    assert {"db-data", "redis-data"} <= set(top_volumes), "영속 볼륨 2종이 선언돼야 한다"

    db_mounts = data["services"]["db"]["volumes"]
    assert any(
        str(m).startswith("db-data:") for m in db_mounts
    ), "db 서비스가 named volume(db-data)에 붙어 있지 않다 — 컨테이너 삭제 시 학생 데이터 소실"
    redis_mounts = data["services"]["redis"]["volumes"]
    assert any(str(m).startswith("redis-data:") for m in redis_mounts)

    # 볼륨 이름에 환경이 박혀 staging이 prod 볼륨을 건드리지 못한다.
    for name in ("db-data", "redis-data"):
        assert "${DEPLOY_ENV" in str(
            top_volumes[name]["name"]
        ), f"{name} 볼륨 이름에 DEPLOY_ENV가 없다 — staging/prod가 같은 볼륨을 공유할 수 있다"


def test_db_image_is_pgvector() -> None:
    """② alembic이 `CREATE EXTENSION vector`를 실행한다 — 순정 postgres:16이면 upgrade 실패."""
    assert _compose()["services"]["db"]["image"] == "pgvector/pgvector:pg16"


def test_restart_policy_present() -> None:
    """② 재부팅·크래시 후 자동 복귀(운영 스택의 최소 조건)."""
    for svc in ("app", "db", "redis"):
        assert (
            _compose()["services"][svc].get("restart") == "unless-stopped"
        ), f"{svc}에 restart 정책이 없다"


# ──────────────────────────────────────────────────────────────────────
# ③ 시크릿 0 + fail-closed
# ──────────────────────────────────────────────────────────────────────
def _iter_env_pairs() -> list[tuple[str, str, str]]:
    """(service, key, value) — 모든 서비스의 environment 매핑을 평탄화."""
    pairs: list[tuple[str, str, str]] = []
    for svc_name, svc in _compose()["services"].items():
        env = svc.get("environment") or {}
        if isinstance(env, dict):
            pairs.extend((svc_name, k, "" if v is None else str(v)) for k, v in env.items())
    return pairs


def test_no_hardcoded_credentials() -> None:
    """③ 자격증명성 값은 전부 `${...}` 참조 — 리터럴 비밀번호·키가 존재하지 않는다."""
    offenders = [
        (svc, key, value)
        for svc, key, value in _iter_env_pairs()
        if _SECRETISH.search(key) and "${" not in value
    ]
    assert not offenders, (
        f"하드코딩된 자격증명 의심: {offenders} — 값은 env 파일에서만 주입한다"
        " (CLAUDE.md '시크릿 코드 하드코딩 금지')"
    )


def test_dsn_urls_interpolate_credentials() -> None:
    """③ DB·Redis DSN에 비밀번호가 리터럴로 박혀 있지 않다."""
    app_env = dict((k, v) for _s, k, v in _iter_env_pairs() if _s == "app")
    assert "${WHYMATH_DB_PASSWORD" in app_env["WHYMATH_DATABASE_URL"]
    assert "${WHYMATH_REDIS_PASSWORD" in app_env["WHYMATH_REDIS_URL"]


# 미설정 시 *기동을 거부*해야 하는 변수들. 각각의 근거:
#   DEPLOY_ENV/COMPOSE 격리 → staging이 prod 볼륨을 덮는 사고 차단
#   IMAGE_TAG → 롤백 좌표(불변 태그) 상실 차단
#   DB/REDIS PASSWORD → 무인증 운영 DB 차단
#   JWT → 인증 불가 상태로 뜨는 것 차단
#   DIALOGUE/DEVICE 암호화 키 → 미성년 대화·디바이스 secret 평문 저장 차단(절대 금기)
_MUST_FAIL_CLOSED = {
    "DEPLOY_ENV",
    "WHYMATH_IMAGE_TAG",
    "APP_PORT",
    "WHYMATH_DB_PASSWORD",
    "WHYMATH_REDIS_PASSWORD",
    "WHYMATH_JWT_SECRET_KEY",
    "WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY",
    "WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY",
}


def _fail_closed_vars() -> set[str]:
    return set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*):\?", _compose_config_text()))


def test_required_vars_are_fail_closed() -> None:
    """③ 필수 변수는 `${VAR:?사유}` — 미설정/빈 값이면 compose가 기동을 거부한다."""
    declared = _fail_closed_vars()
    missing = _MUST_FAIL_CLOSED - declared
    assert not missing, (
        f"fail-closed(`:?`)가 아닌 필수 변수: {sorted(missing)} — "
        "기본값으로 조용히 뜨면 무인증 DB·평문 저장 상태가 무증상으로 운영된다"
    )


def test_fail_closed_messages_are_actionable() -> None:
    """③ 거부 메시지가 '무엇이 왜 필요한지'를 말한다(침묵·무의미 실패 금지)."""
    for var, message in re.findall(r"\$\{([A-Z_][A-Z0-9_]*):\?([^}]*)\}", _compose_config_text()):
        assert len(message.strip()) >= 10, f"{var}의 fail-closed 메시지가 비었거나 너무 짧다"


def test_image_tag_is_not_latest() -> None:
    """③ 이미지 태그는 변수 참조(불변 태그) — `latest` 고정이면 롤백 좌표가 사라진다."""
    image = str(_compose()["services"]["app"]["image"])
    assert "${WHYMATH_IMAGE_TAG" in image, "app 이미지 태그가 변수 참조가 아니다"
    assert not image.endswith(":latest"), "latest 태그 금지(롤백 불가)"


def test_db_and_redis_ports_not_published() -> None:
    """③ db·redis는 호스트 포트를 공개하지 않는다(노출면 축소 + 포트 충돌 회피)."""
    for svc in ("db", "redis"):
        assert "ports" not in _compose()["services"][svc], (
            f"{svc}가 호스트 포트를 공개한다 — 앱은 compose 네트워크로 붙으면 되고, "
            "관리 접속은 docker exec로 한다"
        )


def test_app_binds_loopback_by_default() -> None:
    """③ 앱 포트 기본 바인딩이 127.0.0.1 — TLS·프록시 없이 LAN/인터넷에 열지 않는다."""
    ports = _compose()["services"]["app"]["ports"]
    assert any(
        "${APP_BIND_ADDR:-127.0.0.1}" in str(p) for p in ports
    ), "기본 바인딩 주소가 127.0.0.1이 아니다 — 평문 HTTP 학생 API의 무의식적 노출 위험"


# ──────────────────────────────────────────────────────────────────────
# ④ 이미지 계약 (Dockerfile)
# ──────────────────────────────────────────────────────────────────────
def _dockerfile_text() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


def _dockerfile_directives() -> list[str]:
    """주석·빈 줄을 뺀 지시어 라인(계약 검사는 주석 문구에 반응하면 안 된다)."""
    return [
        line.strip()
        for line in _dockerfile_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_dockerfile_is_multistage_on_slim_base() -> None:
    """④ 멀티스테이지 + python:3.12-slim — 빌드 도구가 런타임 이미지에 남지 않는다."""
    froms = [line for line in _dockerfile_directives() if line.upper().startswith("FROM ")]
    assert len(froms) >= 2, f"멀티스테이지가 아니다(FROM {len(froms)}개)"
    assert all(
        "python:3.12-slim" in line for line in froms
    ), f"베이스 이미지가 python:3.12-slim이 아니다: {froms}"


def test_dockerfile_runs_as_non_root() -> None:
    """④ 비루트 실행 — 마지막 USER 지시어가 root가 아니다."""
    users = [line for line in _dockerfile_directives() if line.upper().startswith("USER ")]
    assert users, "USER 지시어가 없다 — 컨테이너가 root로 돈다"
    last = users[-1].split(None, 1)[1].strip()
    assert last not in ("root", "0"), f"마지막 USER가 root다: {users}"


def test_dockerfile_bakes_no_secrets() -> None:
    """④ ARG/ENV로 시크릿을 굽지 않는다 — 이미지 레이어는 `docker history`로 읽힌다."""
    offenders = [
        line
        for line in _dockerfile_directives()
        if line.upper().startswith(("ARG ", "ENV "))
        and _SECRETISH.search(line.split(None, 1)[1].split("=")[0])
    ]
    assert not offenders, f"이미지에 시크릿성 ARG/ENV가 있다: {offenders}"


def test_dockerfile_healthcheck_uses_liveness_path() -> None:
    """④ HEALTHCHECK 판정치는 의존성 0인 /health/live(OPS-01)."""
    text = _dockerfile_text()
    assert "HEALTHCHECK" in text, "HEALTHCHECK 지시어가 없다"
    healthcheck_block = text[text.index("HEALTHCHECK") :]
    assert "/health/live" in healthcheck_block.split("CMD", 1)[1].split("\n\n", 1)[0], (
        "HEALTHCHECK가 /health/live를 쓰지 않는다 — DB 의존 경로를 라이브니스로 쓰면 "
        "DB 장애 때 멀쩡한 앱 컨테이너가 재시작 루프에 빠진다"
    )


def test_dockerfile_preserves_repo_layout() -> None:
    """④ 레이아웃 보존 계약 — editable 설치 + data 동봉.

    런타임 코드가 `Path(__file__).resolve().parents[5]`로 레포 루트를 계산해
    `data/corpus/**`(교수법 팩·성취기준)를 읽는다(l4/pedagogy/pack_registry.py). 비-editable
    설치는 코드를 site-packages로 옮겨 그 계산을 깨뜨리고, data 미동봉은 팩 로드를 실패시킨다.
    """
    text = _dockerfile_text()
    assert re.search(
        r"pip install\s+-e\s+/app/src/backend", text
    ), "editable 설치가 아니다 — parents[5] 경로 계산이 깨져 교수법 팩·코퍼스 로드가 실패한다"
    assert re.search(
        r"^COPY data /app/data$", text, re.MULTILINE
    ), "data/ 동봉이 사라졌다 — 런타임이 읽는 data/corpus가 이미지에 없다"
    # EOS-89 이후 `create_app()`이 부팅 시 수학 어댑터를 즉시 조립 → `l3.cross_verify`의 모듈 수준
    # `prompt_text()`가 부팅 경로에 들어와 `docs/prompts/l3_*.md`가 없으면 컨테이너가 기동 중 죽는다
    # (2026-09-07 docker-build 스모크 실측). 이 줄이 빠지면 /health/live 스모크가 RED다.
    assert re.search(
        r"^COPY docs/prompts /app/docs/prompts$", text, re.MULTILINE
    ), "docs/prompts 동봉이 사라졌다 — 부팅 시 PromptAssetError로 컨테이너가 죽는다(EOS-89)"


def test_dockerignore_keeps_required_paths() -> None:
    """④ .dockerignore가 런타임 필수 경로(data·src/backend)를 제외하지 않는다."""
    ignore = (_ROOT / ".dockerignore").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in ignore.splitlines() if ln.strip() and not ln.startswith("#")]
    for forbidden in ("data", "data/", "src", "src/", "src/backend", "src/backend/"):
        assert forbidden not in lines, (
            f".dockerignore가 런타임 필수 경로를 제외한다: {forbidden} — 이미지가 기동만 하고 "
            "교수법 팩 로드에서 깨진다"
        )
    assert ".venv" in lines, ".venv 제외가 사라졌다 — 818MB 컨텍스트 전송(2026-07-26 실측)"
    # `docs`를 통째로 제외하면서 프롬프트 정본만 되살리는 부정 패턴 — Dockerfile `COPY docs/prompts`의
    # 짝이다. 이 줄이 빠지면 COPY가 빌드 단계에서 "no such file"로 실패한다(EOS-89 · 2026-09-07).
    assert "!docs/prompts" in lines, (
        ".dockerignore에 `!docs/prompts` 예외가 없다 — `docs` 제외가 프롬프트 정본까지 지워 "
        "`COPY docs/prompts`가 빌드 단계에서 실패한다"
    )


# ──────────────────────────────────────────────────────────────────────
# ⑤ CI 게이트 실재 (ci.yml)
# ──────────────────────────────────────────────────────────────────────
def test_ci_yaml_parses_and_has_docker_build_job() -> None:
    """⑤ ci.yml 정합 + docker-build 잡 실재."""
    ci = _workflow(_CI)
    assert (
        "docker-build" in ci["jobs"]
    ), "docker-build 잡이 사라졌다 — 이미지 계약의 유일한 실행 게이트"


def test_ci_changes_filter_wires_docker_flag() -> None:
    """⑤ 기존 changes 필터 관행 준수 — docker 출력이 있고 docker-build가 그것을 참조한다."""
    ci = _workflow(_CI)
    assert "docker" in ci["jobs"]["changes"]["outputs"], "changes 잡에 docker 출력이 없다"
    condition = ci["jobs"]["docker-build"]["if"]
    assert (
        "needs.changes.outputs.docker" in condition
    ), "docker-build가 changes 필터를 참조하지 않는다(doc-only PR에서도 매번 빌드)"


def _smoke_script() -> str:
    """docker-build 잡의 /health/live 스모크 스텝 본문(GitHub 표현식 없음 — 그대로 실행 가능)."""
    steps = _workflow(_CI)["jobs"]["docker-build"]["steps"]
    smoke = [
        s
        for s in steps
        if "/health/live" in (s.get("run") or "") and "curl" in (s.get("run") or "")
    ]
    assert smoke, "docker-build에 /health/live 스모크 스텝이 없다"
    body: str = smoke[0]["run"]
    assert "${{" not in body, "스모크 본문에 GitHub 표현식이 섞였다(결함주입 실행 불가)"
    return body


def _run_smoke(tmp_path: Path, *, code: str, body: str, running: str) -> int:
    """스모크 스크립트를 curl·docker **스텁**과 함께 실행한다(실 docker 불요).

    스텁이 상황을 주입한다: HTTP 코드(code)·응답 본문(body)·컨테이너 생존(running).
    """
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    (stub_dir / "curl").write_text(
        "#!/usr/bin/env bash\n"
        'out=""\n'
        'while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; *) shift;; esac; done\n'
        '[ -n "$out" ] && printf "%s" "$STUB_BODY" > "$out"\n'
        'printf "%s" "$STUB_CODE"\n',
        encoding="utf-8",
    )
    (stub_dir / "docker").write_text(
        "#!/usr/bin/env bash\n"
        'case "$1" in\n'
        '  inspect) printf "%s" "$STUB_RUNNING";;\n'
        '  logs) echo "(stub) container logs";;\n'
        '  *) echo "(stub) docker $*";;\n'
        "esac\n",
        encoding="utf-8",
    )
    for name in ("curl", "docker"):
        (stub_dir / name).chmod(0o755)

    env = dict(os.environ)
    env.update(
        PATH=f"{stub_dir}:{env['PATH']}",
        STUB_CODE=code,
        STUB_BODY=body,
        STUB_RUNNING=running,
    )
    proc = subprocess.run(
        ["bash", "-c", _smoke_script()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode


def test_ci_smoke_passes_when_liveness_healthy(tmp_path: Path) -> None:
    """⑤ 양성 대조 — 200 + status=ok면 스모크가 통과한다(항상 실패하는 게이트가 아님을 증명)."""
    assert _run_smoke(tmp_path, code="200", body='{"status":"ok"}', running="true") == 0


@pytest.mark.parametrize(
    ("code", "body", "running", "case"),
    [
        ("000", "", "false", "컨테이너가 기동 중 죽음"),
        ("500", "internal error", "false", "앱이 5xx"),
        ("200", '{"status":"degraded"}', "true", "200이지만 본문 계약 위반"),
    ],
)
def test_ci_smoke_fails_on_injected_faults(
    tmp_path: Path, code: str, body: str, running: str, case: str
) -> None:
    """⑤ **결함 주입** — 고장 상황에서 스모크가 실제로 비0으로 끝난다.

    이 테스트가 없으면 "스모크 스텝이 있다"는 사실만 확인될 뿐, 그것이 *실패를 실패로 만드는가*는
    측정되지 않는다(CLAUDE.md "변별력 없는 검증 스텝 금지" — 성공/실패 양쪽에서 같은 값을 내는
    검사는 위장이다).

    보증 범위(정직 기술): 여기서 보장되는 것은 **행동**("고장 → 비0 종료")이지 스크립트의
    특정 줄이 아니다. 스모크는 상태코드와 본문을 이중으로 검사하므로 한쪽 가드를 지워도
    다른 쪽이 같은 고장을 잡는다(2026-07-26 변이 실험에서 확인 — 등가 변이).
    """
    assert (
        _run_smoke(tmp_path, code=code, body=body, running=running) != 0
    ), f"고장 상황({case})에서 스모크가 통과했다 — CI 게이트가 위장이다"


def test_ci_actually_runs_infra_contract_tests() -> None:
    """⑤ tests/infra가 CI에서 **실제로 실행**된다 — 배선 없는 계약 동결은 주장일 뿐이다.

    2026-07-26 실측: 이 배선 전까지 tests/infra를 도는 CI 잡이 하나도 없었다(backend는
    tests/backend, harness-integrity는 tests/harness만). 그 상태로 회귀하면 이 테스트가 막는다.
    의존성 4종(pytest-asyncio·PyYAML·SQLAlchemy)은 로컬 격리 venv 실측으로 확정한 최소 집합이며,
    하나라도 빠지면 CI에서 collection 오류·실패가 난다.
    """
    ci = _workflow(_CI)
    runs = {
        job: "\n".join(step.get("run") or "" for step in body.get("steps", []))
        for job, body in ci["jobs"].items()
    }
    running = [job for job, text in runs.items() if re.search(r"pytest\s+tests/infra", text)]
    assert running, "tests/infra를 실행하는 CI 잡이 없다 — 계약 테스트가 게이트가 아니다"
    for dep in ("pytest-asyncio", "pyyaml", "sqlalchemy"):
        assert any(
            dep in runs[job].lower() for job in running
        ), f"tests/infra 실행 잡이 {dep}를 설치하지 않는다 — CI에서 실패한다(실측 최소 의존성)"


def test_ci_smoke_dumps_logs_on_failure() -> None:
    """⑤ 실패 시 진단 로그 덤프(원인 없는 빨간 X 방지)."""
    assert "docker logs" in _smoke_script(), "실패 시 진단 로그 덤프가 없다"


def test_ci_checks_compose_fail_closed_both_directions() -> None:
    """⑤ fail-closed 변별력 검사(빈 env=거부 / 채운 env=성공)가 CI에 살아 있다."""
    steps = _workflow(_CI)["jobs"]["docker-build"]["steps"]
    runs = "\n".join(s.get("run") or "" for s in steps)
    assert (
        "empty.env" in runs and "fail-closed" in runs
    ), "빈 env 거부 검사가 없다 — `${VAR:?}` 계약이 측정되지 않는 주장으로 남는다"
    assert "trust" in runs, "렌더 결과의 trust 흔적 검사가 없다"


def test_ci_checks_non_root_and_no_baked_secrets() -> None:
    """⑤ 비루트·시크릿 미포함이 CI에서도 실행 검증된다(텍스트 동결 + 실행 검증 이중)."""
    steps = _workflow(_CI)["jobs"]["docker-build"]["steps"]
    runs = "\n".join(s.get("run") or "" for s in steps)
    assert "id -u" in runs, "비루트 실행 검사가 없다"
    assert "Config.Env" in runs, "이미지 시크릿 미포함 검사가 없다"


# ──────────────────────────────────────────────────────────────────────
# ⑥ 배포 워크플로의 정직성 (deploy.yml)
# ──────────────────────────────────────────────────────────────────────
def test_deploy_is_manual_dispatch_only() -> None:
    """⑥ 배포는 수동 트리거 전용 — push/PR로 자동 배포되지 않는다."""
    dep = _workflow(_DEPLOY)
    # PyYAML은 `on:`을 불리언 True로 파싱한다(YAML 1.1) — 두 키를 모두 허용해 조회한다.
    triggers = dep.get("on", dep.get(True))
    assert set(triggers) == {"workflow_dispatch"}, f"수동 트리거 외 이벤트 존재: {sorted(triggers)}"


def test_deploy_has_environment_approval_gate() -> None:
    """⑥ deploy 잡에 environment 게이트(승인 규칙 부착 지점)가 있다."""
    dep = _workflow(_DEPLOY)
    assert "environment" in dep["jobs"]["deploy"], "environment 승인 게이트가 없다"


_DEPLOY_SECRET_NAMES = (
    "DEPLOY_SSH_HOST",
    "DEPLOY_SSH_USER",
    "DEPLOY_SSH_KEY",
    "DEPLOY_SSH_KNOWN_HOSTS",
    "DEPLOY_PATH",
)


def _preflight_secret_script() -> str:
    """preflight의 '대상 시크릿 존재 검사' 스텝 본문(GitHub 표현식 없음 — 그대로 실행 가능)."""
    steps = _workflow(_DEPLOY)["jobs"]["preflight"]["steps"]
    found = [s for s in steps if "DEPLOY_SSH_HOST" in (s.get("run") or "")]
    assert found, "preflight에 대상 시크릿 존재 검사 스텝이 없다"
    body: str = found[0]["run"]
    assert "${{" not in body, "검사 본문에 GitHub 표현식이 섞였다(결함주입 실행 불가)"
    return body


def _run_preflight(tmp_path: Path, *, secrets_set: bool) -> int:
    env = {k: v for k, v in os.environ.items() if not k.startswith("DEPLOY_")}
    env["GITHUB_STEP_SUMMARY"] = str(tmp_path / "summary.md")
    if secrets_set:
        env.update({name: f"dummy-{name.lower()}" for name in _DEPLOY_SECRET_NAMES})
    proc = subprocess.run(
        ["bash", "-c", _preflight_secret_script()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode


def test_deploy_preflight_fails_when_target_missing(tmp_path: Path) -> None:
    """⑥ **결함 주입** — 대상 시크릿이 비면 preflight가 실제로 비0으로 끝난다.

    이것이 이 태스크의 핵심 정직성 계약이다: 프로덕션 인프라가 아직 없으므로 지금 배포를
    돌리면 *반드시* 실패해야 한다. "0건 배포인데 green"은 조용한 성공이며 위장 게이트다
    (CLAUDE.md "측정 없는 기계 게이트"·"침묵 실패 금지").
    """
    assert (
        _run_preflight(tmp_path, secrets_set=False) != 0
    ), "시크릿이 하나도 없는데 preflight가 통과했다 — 존재하지 않는 대상에 배포한 척하는 게이트"


def test_deploy_preflight_passes_when_target_configured(tmp_path: Path) -> None:
    """⑥ 양성 대조 — 시크릿이 모두 설정되면 통과한다(항상 실패하는 장식이 아님을 증명)."""
    assert _run_preflight(tmp_path, secrets_set=True) == 0


def test_deploy_preflight_reports_reason(tmp_path: Path) -> None:
    """⑥ 실패 시 *어느* 시크릿이 없는지 이름으로 알린다(원인 없는 실패 금지)."""
    _run_preflight(tmp_path, secrets_set=False)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "DEPLOY_SSH_HOST" in summary, f"실패 요약에 미설정 시크릿 이름이 없다:\n{summary}"
    assert "미프로비저닝" in summary or "배포 불가" in summary, "사유 설명이 없다"


def test_deploy_never_echoes_secret_values() -> None:
    """⑥ 시크릿 값을 출력하는 라인이 없다(이름·길이만 허용)."""
    text = _DEPLOY.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "secrets." in line and re.search(r"\b(echo|printf|cat)\b", line):
            pytest.fail(f"시크릿 값을 출력할 수 있는 라인: {line.strip()}")


def test_deploy_rejects_mutable_tag() -> None:
    """⑥ latest 등 가변 태그 거부 — 롤백은 '이전 불변 태그 재실행'이라야 성립한다."""
    text = _DEPLOY.read_text(encoding="utf-8")
    assert "latest" in text and "image_tag" in text, "가변 태그 거부 로직이 사라졌다"
    runs = "\n".join(s.get("run") or "" for s in _workflow(_DEPLOY)["jobs"]["preflight"]["steps"])
    assert 'IMAGE_TAG" = "latest"' in runs, "latest 거부 검사가 preflight에 없다"


# ──────────────────────────────────────────────────────────────────────
# ⑦ 문서-구현 정합 (.env.prod.example · .gitignore)
# ──────────────────────────────────────────────────────────────────────
def _env_example_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for line in _ENV_EXAMPLE.read_text(encoding="ascii").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        keys[name.strip()] = value
    return keys


def test_env_example_is_ascii_only() -> None:
    """⑦ ASCII 전용 — 로케일 인코딩(cp949) 환경에서도 안전(backup 스크립트 선례)."""
    data = _ENV_EXAMPLE.read_bytes()
    try:
        data.decode("ascii")
    except UnicodeDecodeError as exc:
        pytest.fail(
            f".env.prod.example에 비ASCII 바이트 (offset {exc.start}: "
            f"{data[exc.start:exc.start + 8]!r}) — 한국어 설명은 런북에 둔다"
        )


def test_env_example_has_no_values() -> None:
    """⑦ 템플릿에 실제 값이 없다 — 커밋된 시크릿 0."""
    filled = {k: v for k, v in _env_example_keys().items() if v.strip()}
    assert not filled, f".env.prod.example에 값이 채워진 키가 있다: {sorted(filled)}"


def test_every_compose_variable_documented() -> None:
    """⑦ compose가 참조하는 모든 변수가 템플릿에 키로 존재한다(누락 시 운영자가 알 방법 없음)."""
    referenced = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)[:}]", _compose_config_text()))
    documented = set(_env_example_keys())
    missing = referenced - documented
    assert not missing, f".env.prod.example에 없는 compose 변수: {sorted(missing)}"


def test_real_env_files_stay_ignored() -> None:
    """⑦ 실제 배포 env는 계속 무시되고, 값 없는 템플릿만 추적 예외다."""
    ignore = _GITIGNORE.read_text(encoding="utf-8")
    assert "*.env" in ignore, "deploy/*.env 무시 규칙이 사라졌다 — 실 시크릿 커밋 위험"
    assert "!.env.prod.example" in ignore, "템플릿 추적 예외가 사라졌다"


def test_runbook_exists_and_documents_gaps() -> None:
    """⑦ 런북 실재 + 정직한 공백 절 — 미프로비저닝 사실이 문서에 남아 있다."""
    runbook = _ROOT / "docs" / "architecture" / "deployment_cd_runbook.md"
    assert runbook.is_file(), "배포 런북 부재"
    text = runbook.read_text(encoding="utf-8")
    for token in ("미프로비저닝", "롤백", "자가검증", "db_backup_dr_runbook.md"):
        assert token in text, f"런북에 필수 절/연계가 없다: {token}"


# ──────────────────────────────────────────────────────────────────────
# ⑧ 보존 파기 스케줄 배선(SEC-12) — "CLI가 있다"와 "CLI가 불린다"는 다르다
# ──────────────────────────────────────────────────────────────────────
def _retention_purge_service() -> dict[str, Any]:
    services = _compose()["services"]
    assert "retention-purge" in services, (
        "docker-compose.prod.yml에 retention-purge 서비스가 없다 — "
        "privacy/retention_purge_cli.py를 부르는 스케줄이 사라지면 보존 정책이 "
        "다시 집행되지 않는 상태(SEC-12 이전)로 돌아간다"
    )
    service: dict[str, Any] = services["retention-purge"]
    return service


def _command_text(service: dict[str, Any]) -> str:
    command = service.get("command", [])
    return " ".join(command) if isinstance(command, list) else str(command)


def test_retention_purge_service_calls_the_cli() -> None:
    """⑧ 서비스 명령이 실제로 `whymath_backend.privacy.retention_purge_cli`를 참조한다."""
    command = _command_text(_retention_purge_service())
    assert (
        "whymath_backend.privacy.retention_purge_cli" in command
    ), f"retention-purge 서비스 명령이 CLI를 호출하지 않는다: {command!r}"


def test_retention_purge_reuses_app_image_no_new_dockerfile() -> None:
    """⑧ 신규 이미지 0 — `app`과 동일 이미지(불변 태그) 재사용."""
    app_image = str(_compose()["services"]["app"]["image"])
    purge_image = str(_retention_purge_service()["image"])
    assert purge_image == app_image, (
        f"retention-purge가 app과 다른 이미지를 쓴다({purge_image!r} != {app_image!r}) — "
        "새 Dockerfile·새 이미지를 만들지 않는다는 설계(SEC-12)를 위반한다"
    )


def test_retention_purge_restarts_on_failure() -> None:
    """⑧ 크래시(트레이스백) → 재기동해 다음 파기를 재시도(파기는 cutoff 재조회라 멱등·안전)."""
    assert _retention_purge_service().get("restart") == "unless-stopped"


def test_retention_purge_healthcheck_disabled() -> None:
    """⑧ 베이스 이미지의 HTTP 라이브니스 HEALTHCHECK는 이 서비스엔 무해당 — 비활성화돼 있다.

    비활성화가 없으면 도커가 8000 포트 무응답을 영구 'unhealthy'로 오판한다(이 서비스는 HTTP
    서버가 아니다).
    """
    assert _retention_purge_service().get("healthcheck", {}).get("disable") is True


def test_retention_purge_needs_no_encryption_keys() -> None:
    """⑧ 파기는 `retention_until`/타임스탬프로 행을 지울 뿐 복호화하지 않는다 — 암호화 키 불요.

    필요 이상의 시크릿을 주입하지 않는 것 자체가 최소 권한 원칙(불필요한 키 유출 시 피해 범위
    축소).
    """
    env = _retention_purge_service().get("environment", {})
    assert "WHYMATH_DATABASE_URL" in env
    for forbidden in (
        "WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY",
        "WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY",
        "WHYMATH_JWT_SECRET_KEY",
    ):
        assert forbidden not in env, f"retention-purge에 불필요한 시크릿이 주입됨: {forbidden}"
