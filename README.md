# WhyMath (와이매스) 하네스 (WhyMath Project Harness)

> **"답이 아닌, 이유를 묻는 수학" — The math that asks why.**
>
> 한국 중·고등학생을 위한 메타인지·사고력 중심 AI 수학 학습 앱 **WhyMath**의 Claude Code 하네스.
> Kiki의 CRAFT 프레임워크 + "AI 길들이기" 4시스템 호환.

## 빠른 시작

```bash
# 1. Claude Code로 프로젝트 진입
cd whymath
claude

# 2. 첫 명령
> /status        # 현재 진행 상태 확인
> /plan Phase 1  # Phase 1 MVP 계획 수립
> /implement L1-data-foundation  # L1 데이터 기반 구현 착수
```

## 로컬 부트스트랩 — 새 기기에서 서비스 띄우기

> 임의의 새 기기·새 세션 기준이다(Kiki 머신 전용 데모 런북 `docs/ops/**`와 별개). 전제: **Python 3.12** · **Docker**(또는 pgvector가 들어 있는 PostgreSQL 16). 명령은 저장소 루트에서 시작한다. 각 단계의 `자가검증`은 **그 단계 산출물 자체**를 본다 — 실패하면 다음 단계로 가지 않는다.

**1. 파이썬 환경과 의존성**

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade "pip<27"
python -m pip install -e "src/backend[dev]"
python -m pip install -e src/data-pipeline
```

자가검증 — 두 패키지가 같은 인터프리터에서 import 된다.

```bash
python -c "import whymath_backend, data_pipeline"
```

**2. 데이터베이스 (pgvector 포함 PostgreSQL 16)** — 호스트 포트는 `5433`을 쓴다(5432는 다른 프로젝트가 쓰는 경우가 많다).

```bash
docker run -d --name whymath-pg -p 5433:5432 \
  -e POSTGRES_USER=whymath -e POSTGRES_DB=whymath \
  -e POSTGRES_HOST_AUTH_METHOD=trust pgvector/pgvector:pg16
export WHYMATH_DATABASE_URL=postgresql+asyncpg://whymath@127.0.0.1:5433/whymath
```

자가검증 — DB가 실제로 쿼리에 답한다(컨테이너가 떴다는 사실만으로는 부족하다).

```bash
docker exec whymath-pg psql -U whymath -d whymath -tAc "SELECT 1"
```

**3. 마이그레이션**

```bash
cd src/backend
python -m alembic upgrade head
```

자가검증 — 현재 리비전이 head 이다.

```bash
python -m alembic current | grep -q "(head)"
```

**4. 서버 기동** (같은 셸 · `src/backend`에서)

```bash
nohup python -m uvicorn whymath_backend.app:create_app --factory --host 127.0.0.1 --port 8000 > uvicorn.log 2>&1 &
SERVER_PID=$!
sleep 8
```

자가검증 — **내가 띄운 프로세스**가 살아 있고 기동을 끝냈다. `/health/live`가 200이어도 이것을 대신하지 못한다: 포트를 먼저 잡고 있던 다른 프로세스(이전 서버·좀비)가 응답했을 수 있고, 그 사이 새 서버는 `address already in use`로 죽어 있을 수 있다.

```bash
kill -0 "$SERVER_PID" && grep -q "Application startup complete" uvicorn.log
```

스모크 — DB 연결까지 포함한 준비 상태(위 자가검증이 통과한 뒤에만 의미가 있다).

```bash
curl -fsS http://127.0.0.1:8000/health/ready | python -c "import sys, json; sys.exit(0 if json.load(sys.stdin)['components']['database']['reachable'] else 1)"
```

> `redis`·`llm_router`가 `reachable: false`로 보이는 것은 정상이다(필수 구성요소가 아니다 — `required: false`).

**5. 테스트 확인** (저장소 루트에서)

```bash
cd ../..
python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend tests/backend/test_config.py tests/backend/test_app.py
```

테스트 경로를 그냥 넘기면 pytest 가 설정 파일을 못 읽어 **가드가 막는다**(`-c`·`--rootdir` 가 그 이유다). 판정은 종료 코드로 한다 — 출력을 `-q`·`| tail`로 줄이지 않는다.

**6. 정리**

```bash
kill "$SERVER_PID"
docker stop whymath-pg
```

> 이 절의 경로·명령이 저장소에 실재하는지는 `tests/infra/test_readme_bootstrap.py`가 대조한다. 스택을 바꾸면 이 절도 함께 고친다.

## 프로젝트 정체성

**한 줄 요약**: 성취기준 정밀 매핑 + 메타인지·사고력 코칭 + 단계별 진단 + 로컬 LLM 비용 구조 = 한국 사교육 시장의 *비어 있는 자리*에 자리 잡는 앱.

**차별화**:
- 콴다처럼 답을 빠르게 주는 게 아니라, *생각하는 법*을 가르침
- EBSi처럼 강의를 주는 게 아니라, *진단·코칭*을 제공
- 메가스터디처럼 콘텐츠를 파는 게 아니라, *사고를* 제공

## 디렉토리 구조

```
whymath/
├── CLAUDE.md                    # 마스터 가이드 (Claude Code 진입 시 자동 로드)
├── MEMORY.md                    # 결정 로그·현재 상태 (수동 업데이트)
├── ROADMAP.md                   # 90일 / 1년 / 3년 로드맵
├── README.md                    # 본 문서
│
├── .claude/
│   ├── settings.json           # Claude Code 설정
│   ├── commands/               # 슬래시 명령
│   │   ├── plan.md            # /plan
│   │   ├── implement.md       # /implement
│   │   ├── review.md          # /review
│   │   ├── prompt-design.md   # /prompt-design
│   │   ├── dataset.md         # /dataset
│   │   └── status.md          # /status
│   │
│   └── agents/                 # 도메인별 서브에이전트
│       ├── data-engineer.md   # L1 — 데이터 기반
│       ├── ml-engineer.md     # L2 — 학습자 모델
│       ├── llm-architect.md   # L3 — 콘텐츠 생성
│       ├── pedagogy-designer.md  # L4 — 교수학 엔진
│       ├── flutter-engineer.md   # L5 — 모바일
│       ├── backend-engineer.md   # L5 — 서버
│       └── content-curator.md    # L6/L7 — 콘텐츠
│
├── docs/
│   ├── architecture/           # 7계층 상세 명세
│   │   ├── 00_overview.md
│   │   ├── 01_data_foundation.md
│   │   ├── 02_learner_model.md
│   │   ├── 03_content_generation.md
│   │   ├── 04_pedagogy_engine.md
│   │   ├── 05_interaction.md
│   │   ├── 06_application_modes.md
│   │   └── 07_community.md
│   │
│   ├── strategy/               # 시장·차별화·리스크
│   │   ├── market_positioning.md
│   │   ├── differentiation.md
│   │   ├── risks.md
│   │   └── partnerships.md
│   │
│   ├── standards/              # 코딩·데이터·프롬프트 기준
│   │   ├── coding_python.md
│   │   ├── coding_flutter.md
│   │   ├── data_pipeline.md
│   │   ├── prompt_engineering.md
│   │   ├── testing.md
│   │   └── security_privacy.md
│   │
│   ├── data/                   # 데이터 소스·라이선스
│   │   ├── ncic_scheme.md
│   │   ├── textbook_mapping.md
│   │   ├── eval_data.md
│   │   └── licensing_safety.md
│   │
│   └── prompts/                # 프롬프트 템플릿 라이브러리
│       ├── socratic_template.md
│       ├── polya_4step.md
│       ├── misconception_diagnosis.md
│       ├── multi_solution_gen.md
│       └── prm_verification.md
│
├── src/                        # 구현 스캐폴딩
│   ├── backend/                # Python FastAPI
│   ├── mobile/                 # Flutter + Riverpod
│   ├── data-pipeline/          # 데이터 수집·정제
│   └── ml-models/              # BKT·IRT·PRM
│
└── scripts/                    # 운영 스크립트
```

## 사용 원칙 (5가지)

### 1. CLAUDE.md를 항상 컨텍스트에 둔다
새 세션마다 Claude가 자동 로드. 프로젝트 정체성·결정사항·금기·표준이 모두 여기에.
코딩 구조 결함 규범은 별도의 **코딩 헌법** `constitution/`에 있고 사람(Kiki)만 고친다(AI는 읽기만 — 가드 훅). 두 규범의 관계는 `docs/standards/coding_constitution_transplant.md`.

### 2. MEMORY.md를 결정 로그로 활용
새로운 결정, 폐기된 접근, 핵심 인사이트는 MEMORY.md에 추가. *대화의 휘발성*을 막는 핵심 도구.

### 3. 서브에이전트로 컨텍스트 격리
L1~L7 영역별 작업은 해당 서브에이전트 위임. 메인 컨텍스트 오염 방지.

### 4. 슬래시 명령으로 워크플로우 표준화
`/plan` → `/implement` → `/review` 사이클. 검증된 패턴 반복.

### 5. 7계층 경계를 침범하지 않는다
L3가 L2를 호출은 OK. L3가 L2 코드를 *직접 작성*은 금지. 각 계층 책임 분리가 유지보수의 핵심.

## Phase 로드맵 요약

| Phase | 기간 | 목표 |
|---|---|---|
| **Phase 1** | 0~6개월 | MVP: 메타인지 사고력 모드, 1개 학년 |
| **Phase 2** | 6~12개월 | 학교진도 + 수능 대비, 풀 K-12 |
| **Phase 3** | 12~24개월 | 영재 트랙·부모·교사 대시보드 |
| **Phase 4** | 18~30개월 | B2B 학교·교육청 |
| **Phase 5** | 30~36개월 | 글로벌 (영문화·베트남·인도) |

상세는 `ROADMAP.md` 참조.

## 도움말

- 무엇을 해야 할지 모를 때: `/status`
- 새 영역 시작할 때: `/plan [영역]`
- 코드 작성 후: `/review`
- 프롬프트 설계할 때: `/prompt-design [목적]`
- 데이터 작업: `/dataset [소스]`

---

**작성일**: 2026-05  
**버전**: 0.1.0  
**기반 프레임워크**: CRAFT 120 tips + AI 길들이기 4시스템
