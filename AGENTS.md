# AGENTS.md — WhyMath (와이매스) 에이전트 가이드

> 이 파일은 AI 코딩 에이전트가 이 저장소에서 작업할 때 필요한 사실만 모은 안내다.
> **정본은 `CLAUDE.md`**(프로젝트 마스터 가이드 — 정체성·절대 금기·7계층 아키텍처·검증 규칙)이며,
> 충돌 시 CLAUDE.md가 우선한다. 작업 전 반드시 CLAUDE.md를 먼저 읽을 것.
> 결정 로그·현재 상태는 `MEMORY.md`, 일정은 `ROADMAP.md` 참조.

---

## 프로젝트 개요

**WhyMath(와이매스)** — "답이 아닌, 이유를 묻는 수학". 한국 중·고등학생을 위한 메타인지 중심·사고력 우선·단계별 진단 기반 AI 수학 학습 앱. 단순 사진→답 풀이 앱(콴다류)이나 강의 플랫폼(EBSi류)이 아니라, *생각하는 법*을 가르치는 것이 목표다.

핵심 설계 축:

- **7계층 아키텍처**: L1 데이터 기반 → L2 학습자 모델 → L3 콘텐츠 생성·검증 → L4 교수학 엔진 → L5 상호작용/클라이언트 → L6 응용 모드 → L7 커뮤니티. 상위 계층은 하위를 *호출*할 수 있지만 역방향 의존은 금지(정적 강제: import-linter, 아래 참조).
- **L1~L4 = 독립 수학 코어**: UI 밖 플랫폼. 클라이언트(Flutter·웹)는 API로만 소비하며 수학 로직을 클라이언트에 두지 않는다.
- **표현 ≠ 의미**: 문항·수식은 렌더러-중립 LaTeX + 구조 태그로 코어에 저장, 렌더는 각 클라이언트 몫.
- **LLM 안전**: 모든 LLM 호출은 라우터 경유 + Langfuse 추적, 학생에게 나가는 응답은 PRM/도구(SymPy) 검증 통과 후.

로드맵: Phase 1(0~6개월, MVP) → Phase 5(글로벌). 상세는 `ROADMAP.md`.

---

## 저장소 레이아웃

모노레포. **루트에 pyproject.toml/공통 패키지 설정은 없다** — 영역별로 개별 매니페스트를 가진다.

```
WhyMath/
├── CLAUDE.md / MEMORY.md / ROADMAP.md / IDEA.md   # 마스터 가이드·결정 로그·로드맵
├── conftest.py                # pytest 루트: src/data-pipeline을 sys.path에 주입 + randomly seed 리포트
├── Dockerfile                 # 백엔드 프로덕션 이미지 (빌드 컨텍스트 = 레포 루트)
├── docker-compose.demo.yml / .pilot.yml / .prod.yml
├── package.json               # 루트 Node 의존성 1종(@openrouter/sdk) — 스크립트 없음
│
├── src/
│   ├── backend/               # Python 3.12 + FastAPI — 패키지 whymath_backend/ (pyproject.toml, alembic/)
│   │   └── whymath_backend/   #   api, l1~l6, schema, db, config, ops, privacy, harness, whs, security.py …
│   ├── data-pipeline/         # Python — 패키지 data_pipeline/ (pyproject.toml, typer CLI)
│   ├── mobile/                # Flutter + Riverpod (pubspec.yaml) — lib/{core,features,theme}
│   ├── web/graphing-calculator/  # Vite + React SPA (package.json) — 국소 임베드용
│   └── ml-models/             # README만 (스캐폴드)
│
├── tests/                     # 소스와 분리된 테스트 트리 (src 패키지와 동명 디렉토리 주의)
│   ├── backend/  data_pipeline/  harness/  infra/
│
├── scripts/
│   ├── harness/backlog.py     # 빌드 하네스 CLI (작업일정 정본)
│   ├── demo/run_demo.ps1|sh   # 로컬 데모 일괄 기동
│   └── coverage/check_layer_coverage.py  # 계층별 커버리지 게이트
│
├── backlog/                   # tasks/*.yaml · gates.yaml · policy.yaml · tracks.yaml · events.ndjson
├── data/                      # corpus/, ncic/, notation/render 계약 JSON (런타임이 레포 상대 경로로 읽음)
├── schemas/                   # v1.0, v1.1 — 공유 엔티티·계약 명세
├── docs/                      # architecture/(7계층 상세·런북) standards/ strategy/ data/ prompts/ …
├── infra/phaiakes9/           # 개발 머신(Phaiakes9) 운영 쉘 스크립트·벤치마크
├── .claude/                   # Claude Code 하네스: agents/(도메인 서브에이전트 7종) commands/(슬래시 명령) settings.json
└── .github/workflows/         # ci.yml, deploy.yml
```

---

## 기술 스택 (확정 — 변경 시 MEMORY.md 결정 로그 필수)

| 영역 | 스택 |
|---|---|
| 백엔드 | Python 3.12 · FastAPI + uvicorn · SQLAlchemy 2 (async, asyncpg) · alembic · Celery · pydantic v2 |
| DB | PostgreSQL 16 + **pgvector**(벡터 통합) · Redis 7 · (조건부 확장: ClickHouse, S3/MinIO). **Neo4j는 런타임 미도입**(2026-08-03 정정 — 개념 그래프 정본은 PG 단일 평면, Neo4j는 data-pipeline 옵셔널 extra의 적재 실험 경로뿐) |
| LLM | 로컬 Ollama(qwen2-math, qwen2.5, **qwen3:30b-a3b**(QUALITY·MoE), qwen3-vl:8b — 정본 `whymath_backend/l3/router.py` `LOCAL_MODEL_MATRIX`·`QUALITY_MODEL_ID`) · 클라우드 Anthropic(claude-sonnet-4-6 / claude-opus-4-7만 배선됨 · **2026-09-24~12-31 사용 중단** — `anthropic_api_enabled=False` 기본, Claude는 Max 구독 개발 도구로만 · ARCH-66) — **포트폴리오는 측정 기반 개방 목록**: 신규 프로바이더(OpenRouter 등)·신규 모델(DeepSeek 계열 등)을 전제 배제하지 않고 품질·지연·비용 실측으로 상시 재평가. 채택 조건 = ①라우터 경유 ②실측 근거 ③MEMORY 결정 로그 (2026-08-16 결정, 2026-08-22 QUALITY MoE 채택). 검증 계약(SymPy 단일 권위·학생 제공 전 검증)은 프로바이더 무관 불변 |
| 임베딩 | 로컬 bge-m3 기본(sentence-transformers, `[embedding]` extra) · OpenAI text-embedding-3-large 옵션 |
| 검증·도구 | SymPy(동치·검증 단일 권위) · pdfplumber |
| 관측성 | Langfuse(`>=2.50,<5` 상한 핀, 실집행 단독) · structlog · **OpenTelemetry는 선언만·import 0건(미배선, 2026-08-11 실측 — 판정은 `OPS-32`)** |
| 모바일 | Flutter 3.41.x / Dart 3.11 · Riverpod 3 · go_router · freezed · dio+retrofit · flutter_math_fork · webview_flutter |
| 웹 | React + Vite (graphing-calculator SPA) · Vitest |
| OCR | rapidocr-onnxruntime · rapid-latex_ocr · rapid-layout(`[ocr]`/`[ocr-layout]` extras, ONNX 기반·torch 불요) |

**의존성 핀 정책**: 외부 SDK는 실제 호출하는 표면을 실물 설치로 실측 검증한 메이저까지 **상한을 건다**(`langfuse<5` 선례). 무상한 pin 금지. 무거운 extra(embedding·ocr)는 lazy import라 미설치 환경에서도 import·mypy green이 유지되어야 한다.

---

## 빌드·테스트 명령

개발 머신은 Windows(PowerShell 기본, Git Bash/WSL 보조). **실행기는 단독 호출하지 말고 항상 `python -m pip` / `python -m pytest` 형태**로 같은 인터프리터를 강제한다(다중 venv 환경).

### 백엔드 (`src/backend`)

```bash
cd src/backend
python -m pip install -e ".[dev]"          # editable 설치 필수 (런타임이 레포 상대 경로로 data/를 읽음)
python -m pip install -e ../data-pipeline  # 교차계층 거버넌스 테스트가 data_pipeline을 import

ruff check . ../../tests/backend
black --check --line-length 100 . ../../tests/backend   # tests는 위에 pyproject가 없어 100 명시 필수
mypy --strict whymath_backend
lint-imports                               # 7계층 단방향 계약 (import-linter)
python -m pytest                           # tests/backend, 커버리지 --cov-fail-under=70 (CI)
python ../../scripts/coverage/check_layer_coverage.py coverage.xml  # 계층별 바닥선 게이트
```

- 엔트리포인트는 **팩토리**: `uvicorn whymath_backend.app:create_app --factory --host 0.0.0.0 --port 8000` (모듈 전역 `app` 없음).
- 마이그레이션: `python -m alembic upgrade head` (컨테이너 기동 시 자동 실행하지 않음 — 배포 런북의 별도 스텝).
- CI 게이트(로컬 재현 가능): `python -m whymath_backend.harness.defect_detection_eval …`, `coach_prose_leak_eval`, `pedagogy_pack_fidelity_eval`, `l3.notation_coverage` — ci.yml backend 잡 참조.

### 데이터 파이프라인 (`src/data-pipeline`)

```bash
cd src/data-pipeline
python -m pip install -e ".[dev]"          # extras: playwright / postgres / neo4j / xlsx
ruff check . ../../tests/data_pipeline
black --check --line-length 100 . ../../tests/data_pipeline
mypy --strict data_pipeline
python -m pytest                           # tests/data_pipeline, 커버리지 70%+
```

CLI: `whymath-ncic`(NCIC 성취기준), `whymath-misconception`(오개념) — typer 기반.

### 모바일 (`src/mobile`) — CI가 유일한 검증 게이트 (로컬 Flutter SDK 없을 수 있음)

```bash
cd src/mobile
flutter pub get
dart run build_runner build --delete-conflicting-outputs   # freezed/retrofit/riverpod codegen (산출물 미커밋)
flutter analyze
flutter test --coverage                    # 라인 커버리지 ≥ 60% 게이트
```

실기기 실행은 백엔드 도달성이 선결: `scripts/demo/run_demo.ps1`로 백엔드 기동 후 `flutter run --dart-define=API_URL=http://<LAN IP>:8000 --dart-define=DEMO_TOKEN=<토큰>`(run_demo 출력 라인을 통째로 복사).

### 웹 (`src/web/graphing-calculator`)

```bash
npm ci && npm run coverage && npm run build   # Vitest (src/lib 70%+ 게이트) + Vite 빌드
```

### 하네스·인프라·전체

```bash
python3 scripts/harness/backlog.py validate        # 백로그 무결성
python3 -m pytest tests/harness -q                 # 하네스 테스트
python3 -m pytest tests/infra -q                   # 운영 자산 계약 테스트
```

### Docker

```bash
docker build -f Dockerfile -t whymath-backend:<tag> .   # 컨텍스트 = 반드시 레포 루트
```

로컬 DB 지도: **prod용 로컬 = docker `whymath-pg`(포트 5433, pgvector/pg16, trust)** · 시연용 = `whymath-demo-db`(55432, 일회용) · 5432는 타 프로젝트 점유(사용 금지).

---

## 코드 스타일

- **언어**: docstring·주석·커밋 메시지·문서는 **한국어**, 식별자는 영어(ruff `N` 규칙 활성). 주석은 "왜"와 사고 경위를 적는 문화 — CLAUDE.md/소스의 기존 주석 밀도를 따른다.
- **포맷**: line-length 100 공통. ruff(`E,F,I,N,B,W`) + black + **mypy --strict**(pydantic 플러그인) — CI 4스텝(ruff·black·mypy·pytest)이 영역별로 강제. lint/format은 src뿐 아니라 **tests도 대상**.
- **pytest**: `--import-mode=importlib`, `--strict-markers --strict-config`, `asyncio_mode=auto`, pytest-randomly 상시(실패 재현은 헤더의 `--randomly-seed=N`을 되먹인다).
- **커버리지**: 집계 70% + 계층별(l1~l4·api) 바닥선 게이트(`scripts/coverage/check_layer_coverage.py`). 모든 PR에 테스트 동반.
- **아키텍처 강제**: import-linter layers 계약(`api > l6 > l5 > l4 > l3 > l2 > l1 > schema`) — 역방향 import는 CI에서 차단.
- **DB 접근은 ORM/쿼리 빌더만**(원시 SQL 최소화), **LLM 호출은 라우터(`l3/router.py`) 경유만** — 직접 호출 금지.
- 무거운 optional 의존성은 함수 내 lazy import + 미설치 시 명확한 RuntimeError(조용한 폴스루 금지). 기본 설치 환경에서 collection·mypy가 깨지면 안 된다.
- 외부 도구가 로케일 인코딩(cp949)으로 읽는 설정 파일(예: uvicorn `--log-config`)은 **ASCII 전용** — 회귀 테스트 `test_wh1_shadow_logconfig.py` 참조.

## 테스트 전략

- 테스트는 소스와 분리: `tests/{backend,data_pipeline,harness,infra}`. 루트 `conftest.py`가 `src/data-pipeline`을 sys.path에 주입해 동명 디렉토리 충돌을 회피한다.
- `integration` 마크는 기본 skip — 실 네트워크·라이브 서비스(PG·Neo4j·Ollama 등) 호출. 활성화는 `WHYMATH_RUN_INTEGRATION=1` + 해당 서비스 도달 필요(CI는 별도 잡에서 실 PG·Neo4j 서비스 컨테이너로 실행).
- **전체 스위트 통과만 "회귀 없음"의 근거** — 부분 디렉터리 실행은 순서 의존 오염을 못 본다. 전체를 못 돌렸으면 그 사실을 명시하고 CI를 최종 판정으로 넘긴다.
- 게이트 철학(초인간 검증 기준, `docs/standards/superhuman_verification_standard.md`): 판정은 CLI exit 0/1(Wilson 단측 경계) — 점추정·인상 판정 금지. 핵심 판정치는 외부 SaaS에만 의존하지 않고 인프로세스 이중 회계.
- 침묵 실패 금지: best-effort 예외 삼키기 코드는 반드시 **예외 타입명을 로그에 포함**.

## 빌드 하네스 (작업 관리 — 추론 금지, CLI 사용)

"다음 할 일"·태스크 상태의 정본은 `backlog/` + `scripts/harness/backlog.py`다.

```bash
python3 scripts/harness/backlog.py status    # 현재 상태
python3 scripts/harness/backlog.py next      # 착수 가능 후보 계산
python3 scripts/harness/backlog.py add ...   # 새 태스크 등재 — 번호는 CLI만 배정 (추론으로 YAML 만들지 말 것)
python3 scripts/harness/backlog.py start <id>   # 착수(claim)
python3 scripts/harness/backlog.py done <id>    # 완료(증적 필수)
python3 scripts/harness/backlog.py gates        # 사람 게이트 대장
```

- **backlog YAML·events.ndjson을 손편집으로 우회하지 않는다** — 하네스의 거부(deny)는 판정이다. CLI 경로가 없는 설계 공백이면 태스크로 등재.
- 병렬 세션: 1 세션 = 1 도메인 = 1 브랜치 = 1 worktree (`scripts/new-session-worktree.sh`, `docs/standards/parallel_sessions.md`).
- Claude Code 훅(`.claude/settings.json`): SessionStart에 `backlog.py brief`, Edit/Write 후 `check-edit`, Stop 시 `check-stop`. 참고: 같은 파일이 `defaultMode = "plan"`이라 Claude Code 세션은 기본 plan 모드로 시작한다.
- 슬래시 명령: `/plan` `/implement` `/review` `/drive` `/gates` `/status` `/dataset` `/prompt-design` `/deploy` `/demo-doctor` (`.claude/commands/`). 도메인 서브에이전트 7종: data-engineer·ml-engineer·llm-architect·pedagogy-designer·flutter-engineer·backend-engineer·content-curator (`.claude/agents/`).

## 완료·병합 (2026-08-11 Kiki 지정 — CLAUDE.md "✅ 절대 원칙" 정본)

- **산출물이 있으면 요청 없이 PR을 연다** — "PR을 요청받지 않았다"는 보류 사유가 아니다. 이 저장소는 미병합 고립 사고가 반복(4회차)된 전력이 있어, 커밋이 있고 아래 예외가 아니면 **PR 생성이 기본값**.
- **main 머지는 `"pr"` 지시 또는 Kiki 판단** — `"pr"` 단축어 = PR 생성 → CI 통과 대기 → 자동 머지(squash)까지 일괄.
- **PR을 열지 않는 예외 4종**: ① 조사·계획 전용 ② 미완·사람 게이트 대기 ③ CI red ④ Kiki 명시 보류. 예외로 끝낼 때는 **어느 예외인지 1줄 보고** — 침묵 보류는 구멍.
- **집행 지점**: `backlog.py done`은 증적에 PR 참조(`#NNN`)가 없으면 exit 1로 거부. 예외 통과는 `--no-pr {investigation|incomplete|ci-red|kiki-hold}`뿐.

## CI/CD·배포

- **CI**(`.github/workflows/ci.yml`, push/PR + 야간 schedule): 변경 경로 판별로 doc-only PR은 무거운 잡 skip. 잡: `data-pipeline` · `backend`(린트·타입·import-linter·pytest·계층 커버리지·기계 게이트 4종) · `backend-migrations`(실 PG: alembic upgrade head → downgrade base → 재upgrade 왕복 + 통합테스트) · `data-pipeline-integration`(실 PG) · `data-pipeline-neo4j`(실 Neo4j) · `mobile`(Flutter 3.41.9 고정) · `web` · `infra-contracts`(tests/infra 항상 실행) · `docker-build`(이미지 빌드→기동 스모크 /health/live→비루트·시크릿·compose fail-closed 계약) · `infra-shell` · `policy-guard` · `harness-integrity` · `e2e-nightly`(야간 관통 슬라이스).
- **배포**: `deploy.yml`(수동 승인) + 런북 `docs/architecture/deployment_cd_runbook.md`. 대상 인프라는 아직 미프로비저닝.
- 이미지 계약: 비루트(appuser uid 10001) · 시크릿 0(런타임 env 주입만) · 헬스체크는 의존성 0인 `/health/live`(레디니스는 `/health/ready`) · `docker-compose.prod.yml`은 `${VAR:?}` fail-closed(빈 env 기동 거부, trust 인증 흔적 금지). 계약은 `tests/infra/test_deploy_artifacts.py`가 동결.

## 보안·법적 고려사항 (요약 — 전문은 CLAUDE.md 절대 금기)

- **시크릿 하드코딩 금지** — CI policy-guard가 패턴(sk-*, sk-ant-*, ghp_*, AKIA…) 차단. 이미지 레이어에도 굽지 않는다.
- **미성년자 데이터**: 채팅 평문 저장 금지(암호화 필수 — `WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY`), 명시 동의 없이 학습 사용 금지, 학부모/14세 미만 동의 절차 준수, 개인 식별 가능 분석 외부 노출 금지.
- **저작권**: 검정교과서·EBS·평가원 기출의 본문·문항·그림 복제 절대 금지 — 구조 메타데이터(단원·코드·페이지)만 인용하고 문제는 자체 동등문제로 대체. policy-guard가 출판사명+본문 패턴을 차단(의도적 사용은 `# codeowner-ack`). 라이선스 정본: `docs/data/licensing_safety.md`.
- `yaml.safe_load`만 사용. AGPL 의존성(ultralytics 등) 거부 — 법적 준수가 비용·속도보다 우선(의사결정 우선순위: 학생 안전 > 법적·윤리 > 교수학 정확성 > 학습 효과 > UX > 비용 > 개발 속도).

## 프로세스 금기·행동 규칙 (요약 — 전문과 사고 경위는 CLAUDE.md "⚖️ 절대 금기")

이 프로젝트는 *반복된 실수를 규칙으로 봉인*해 온 역사가 있다. 자주 걸리는 것만 추린다:

- **검사 출력을 억제하고 판정 금지** — `-q`/`--quiet`/`| tail -N`로 잘라 보이는 문자열만으로 통과 선언 금지. 판정은 **exit code**(`; echo "EXIT=${PIPESTATUS[0]}"` 병기). CI가 쓰는 명령을 대상 경로·플래그까지 그대로 재현.
- **미커밋 작업분이 있는 트리에서 `git checkout --`·`git restore`·`git stash`로 원복 금지** — 뮤테이션 검증의 원복은 사전 `cp` 백업을 `cp`로 되돌리기뿐. git 원복은 미커밋 구현분까지 무증상 소실시킨다.
- **trunk 부재를 "미구현"으로 단정 금지** — 장기 미머지 브랜치가 수십 개라 trunk은 실제 진척을 대표하지 못한다. "없다" 판정 전에 `backlog.py next`의 미머지 완료 경고를 읽고 `git log --all --grep=<TASK-ID>`로 원격을 실측.
- **태스크 ID 추론 배정 금지** — 항상 `backlog.py add` 경유(병렬 세션의 인플라이트 번호는 눈으로 못 본다).
- **검증 장치를 만들고 배선 확인 없이 완료 선언 금지** — 테스트·게이트·계약이 실제 CI/서빙 경로에서 도는지 확인 후 완료.
- **검증 권위 서열**: ① 기계 증명(SymPy·도구) ② 측정 통과 기계 게이트 ③ 인간 폴백(측정 미달 구간만). 오류율 미측정 검출기를 최종 권위로 가정 금지.
- **실수 관리 의무**: 시스템 실수·반복 실수(동일 유형 2회+)는 세션 종료 전 재발방지대책 등재가 의무 — 형태는 규칙(CLAUDE.md)·코드(테스트 동결)·태스크(추적) 중 하나 + MEMORY 결정 로그에 사고 경위.
- **컨텍스트 위생**: 장기 작업은 서브에이전트로(메인 컨텍스트에 코드 누적 금지), MEMORY.md가 진실 원천, 결정은 항상 문서화.
- **사람(Kiki)에게 실행을 안내할 때**: PowerShell 기준 복사-붙여넣기 가능한 명령 블록 + 작업 디렉터리(`C:\Users\kiki\Desktop\__AI\WhyMath` 고정) + 각 단계 자가검증 스텝을 동봉. 미머지 브랜치의 파일이 필요하면 fetch/checkout 명령 선행. 시크릿 예시는 생략 문자(`sk-…`) 금지, `여기에_실제_키_전체` 형태 + 등록 직후 자가검증. 6항목 사전 브리핑(명칭·목적·절차·성공 기준·환경·창 구분)은 CLAUDE.md 참조.

## 지식그래프·LLM 컨텍스트 작업 시 (구축 플레이북 철칙 — L1/L3/L4 변경 시 필수)

단 하나의 원칙: **"수학 전체를 모델링하지 말고 교육적으로 압축된 인지 그래프만. LLM에 전체 그래프를 통째로 주지 마라."**

- **Concept Purity** — 노드는 순수 개념만(renderer·curriculum·prompt·misconception·UI·embedding 혼입 금지), 노드 파일 1~4KB(10KB 금지)
- **관계 타입 5~8개만** — `similar_to`/`related_to`를 traversal에 사용 금지, `prerequisite`만 DAG 강제
- **Minimal Reasoning Subgraph** — LLM에는 depth ≤ 2, max_nodes ≤ 12~20, max_tokens ≤ 3000만 전달
- **오개념은 reactive retrieval만** — 초기 context preload 금지(오염 방지)
- **embedding은 chunk 단위 분리** + concept/atom/misconception 네임스페이스 물리·논리 분리(cross-table 코사인 금지 — `test_embedding_namespace_governance.py`)

## 주요 문서 포인터

- `CLAUDE.md` — 마스터 가이드(7계층·금기·검증 규칙·워크플로우). **충돌 시 최우선.**
- `MEMORY.md` — 결정 로그·슬라이스 히스토리(대형 파일 — 필요한 부분만 검색해서 읽기)
- `docs/architecture/00_overview.md` + `01`~`07` — 계층별 상세 명세
- `docs/standards/dev_constitution.md` — 경량 개발 헌법 · `testing.md` · `security_privacy.md` · `build_harness.md` · `coding_flutter.md`
- `src/backend/README.md`는 일부 낡았다(chromadb·mathpix·`src.main:app` 언급 — 현행은 pgvector·PaddleOCR 계열·`whymath_backend.app:create_app`). 코드와 ci.yml이 사실의 정본.
