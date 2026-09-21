# syntax=docker/dockerfile:1
#
# WhyMath 백엔드 프로덕션 이미지 (OPS-03) — FastAPI(uvicorn) 단일 프로세스.
#
# ★ 빌드 컨텍스트는 **레포 루트**다: `docker build -f Dockerfile -t whymath-backend:<tag> .`
#   src/backend만 담으면 안 된다 — 런타임 코드가 `Path(__file__).resolve().parents[5]`로
#   레포 루트를 계산해 `data/corpus/**`(교수법 팩·성취기준·원자 그래프)를 읽기 때문이다
#   (whymath_backend/l4/pedagogy/pack_registry.py:34, l1/pedagogy/compile.py:37 — 2026-07-26 실측).
#   따라서 이미지 안에서도 `/app/src/backend/whymath_backend/...` + `/app/data/...` 레이아웃을
#   그대로 보존한다. 같은 이유로 패키지는 **editable(-e) 설치**다: 비-editable 설치는 코드를
#   site-packages로 옮겨 parents[5]가 `/usr/local/lib`를 가리키게 되고 팩·코퍼스 로드가 깨진다.
#
# ★ 시크릿 0: ARG·ENV로 키·비밀번호를 굽지 않는다(이미지 레이어는 누구나 `docker history`로
#   본다). 모든 자격증명은 런타임 env 주입뿐이며, 그 주입은 docker-compose.prod.yml의
#   `${VAR:?}` fail-closed 계약이 강제한다. CLAUDE.md "API 키·시크릿 코드 하드코딩 금지"의
#   이미지판이다. 이 계약은 tests/infra/test_deploy_artifacts.py가 동결한다.

# ──────────────────────────────────────────────────────────────────────
# stage 1 — builder: 컴파일 도구·pip 캐시를 여기 가둔다
# ──────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# 휠이 없는 의존성이 섞여도 여기서 빌드된다. 런타임 이미지에는 gcc·헤더가 남지 않는다
# (공격면·용량) — 멀티스테이지의 실익.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app
# 의존성만 먼저 설치하는 "빈 패키지 stub" 캐시 트릭은 쓰지 않는다 — pyproject의 hatch
# force-include(whymath_backend/l4/misconception/probes_v1.jsonl)가 *실파일*을 요구해서
# stub 상태로는 빌드가 실패한다. 소스를 먼저 복사하고 설치한다(캐시 효율 < 정확성).
COPY src/backend/pyproject.toml /app/src/backend/pyproject.toml
COPY src/backend/whymath_backend /app/src/backend/whymath_backend

# [dev]·[embedding]·[ocr] extra는 설치하지 않는다 — 런타임 불요(torch 수 GB)이며
# lazy import라 미설치 상태에서도 기본 경로가 동작한다(pyproject 주석 참조).
RUN pip install --upgrade pip \
 && pip install -e /app/src/backend

# ──────────────────────────────────────────────────────────────────────
# stage 2 — runtime: venv + 소스 + 데이터만
# ──────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

# 비루트 실행 — 컨테이너 침해 시 피해 최소화. /app·/opt/venv는 root 소유로 남겨(앱은 읽기만)
# 실행 중 코드·데이터 변조를 막는다. 앱은 디스크에 쓰지 않는다(로그는 stdout → 도커 로깅).
RUN useradd --system --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src/backend /app/src/backend

# alembic은 배포 시 별도 스텝(`docker compose run --rm app alembic upgrade head`)으로 돌린다 —
# 컨테이너 기동 시 자동 마이그레이션은 하지 않는다(다중 인스턴스 동시 기동 시 경합·롤백 판단을
# 사람이 하도록. 런북 §3·§6).
COPY src/backend/alembic.ini /app/src/backend/alembic.ini
COPY src/backend/alembic /app/src/backend/alembic

# 런타임이 레포 상대 경로로 읽는 자산(헤더 주석 참조) — 13MB(2026-07-26 실측 `du -sh data/corpus`).
COPY data /app/data
# L3 프롬프트 정본(OPS-16) — `prompt_assets.py`가 `__file__` 기준 `/app/docs/prompts`를 읽는다.
# EOS-89 이후 `create_app()`이 부팅 시 수학 어댑터를 즉시 조립하므로 `l3.cross_verify`의
# 모듈 수준 `prompt_text()`가 부팅 경로에 들어왔다 — 이 파일들이 없으면 컨테이너가 기동 중
# 죽는다(2026-09-07 docker-build 스모크 실측: PromptAssetError). `.dockerignore`의 `docs` 제외에
# `!docs/prompts` 예외가 짝으로 있어야 한다(test_deploy_artifacts.py가 둘을 함께 고정).
COPY docs/prompts /app/docs/prompts

# alembic.ini가 여기 있어야 런북 §3 명령이 그대로 동작한다.
WORKDIR /app/src/backend

USER appuser
EXPOSE 8000

# 판정치는 **의존성 0인 라이브니스**(/health/live · OPS-01)뿐이다 — DB·Redis 미도달 상황에서도
# "프로세스는 살아있다"를 정확히 보고해야 도커가 멀쩡한 컨테이너를 재시작하지 않는다.
# 트래픽 투입 가부(레디니스)는 /health/ready가 담당하며 그것은 외부 모니터·프록시의 몫이다.
# curl을 설치하지 않고 표준 라이브러리로 검사한다(런타임 표면 최소화).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200 else 1)"]

# 모듈 전역 `app` 객체가 없다 — create_app 팩토리다(scripts/demo/run_demo.sh와 동일 진입점).
# 0.0.0.0 바인딩은 *컨테이너 내부* 기준이며, 외부 노출 범위는 compose의 ports 바인딩 주소가
# 정한다(docker-compose.prod.yml 기본 127.0.0.1).
CMD ["uvicorn", "whymath_backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
