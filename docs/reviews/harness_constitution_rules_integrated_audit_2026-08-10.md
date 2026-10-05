# 하네스·헌법·규칙파일 통합점검 (2026-08-10)

> **범위**: ①빌드 하네스(`backlog/`+`scripts/harness/`+`.claude/` 훅·commands) ②개발 헌법(`docs/standards/dev_constitution.md`) ③규칙 파일(CLAUDE.md 본체 + `docs/standards/*`) — 그리고 이 3축 **사이의** 상호 정합(규칙↔집행 지점·규칙↔MEMORY 추적성·규약↔스킬).
> **성격**: Kiki 지시("하네스를 비롯한 헌법, 규칙파일 점검" → "통합점검") 단일 통합 감사. 조사(Explore 3축 병렬) → 정정 즉시 반영 + 태스크 등재 + 본 보고서.
> **결론 3줄**:
> 1. **골격은 건강하다** — backlog validate green(위반 0)·CLAUDE.md 참조 아티팩트 9/9 실재·깨진 참조 0건·CI 테스트 배선 사각 0·규칙→사고 경위 추적성 6/6. 이 규모(표준 38문서·태스크 232건)에서 이례적으로 양호.
> 2. **부패는 "표기·전파" 축에 몰려 있었다** — 정본(CLAUDE.md·코드)은 맞는데 하위 문서가 낡은 형태(Mathpix 6곳·KoSimCSE·우선순위 대체·버전 표기 3개월 괴리 등 D-1~D-29). 이번 세션에서 문서·스킬 결함 전량 정정 완료(커밋 ①).
> 3. **최대 발견 = 비가시 부채 HARN-15** — 미머지 브랜치에만 존재해 어떤 조율 화면(next/status/drive)에도 안 뜨던 미해결 태스크를 정본 그대로 main행 회수(커밋 ②). 신규 하네스 결함 2건은 HARN-20·21로 등재.

관련 정본: `CLAUDE.md`(v0.2.0으로 본 점검이 갱신) · `docs/standards/build_harness.md`(v1.2) · `docs/standards/dev_constitution.md` §0.1 · `scripts/harness/{backlog,models,store,remote_claims,selector,pathscope,report}.py` · `.claude/settings.json`·`.claude/commands/*` · `.github/workflows/ci.yml` · `MEMORY.md` 결정 로그(2026-08-10 통합점검 항목 신설) · 직계 선례 `docs/reviews/dev_constitution_review_v1.md`

---

## §0. 점검 방법과 한계 (먼저 밝힘)

- **방법**: 읽기 전용 병렬 조사 3축(하네스 구현↔규약 / 표준 문서↔CLAUDE.md 전문 대조 / MEMORY 추적성·CI 배선) + 메인 세션 직접 실측(validate·status 실행, CLI `--help`, `git ls-tree`/`ls-remote`, 마커 추출 검증). 상태 변경 명령(start/done/claim)은 조사 중 미사용 — 등재는 전건 `backlog.py add` CLI 경유.
- **한계 ①**: 이 컨테이너에 **pytest 미설치** — `tests/harness` 251건·`tests/infra`를 로컬 실행하지 못했다. **전체 테스트는 확인하지 못했으며 CI(required check: harness-integrity·infra-contracts)가 최종 판정이다.** 대체 검증으로 CLAUDE.md 동결 마커 61건을 AST 추출→전건 존재 대조했다(missing=0, 부록 E).
- **한계 ②**: **shallow clone(50커밋·경계 2026-08-04)** — "git 최종 수정일" 주장 중 2026-08-04로 나온 것은 "그 이후 수정 없음"의 하한이다.
- **한계 ③**: 조사 시점과 병렬 세션 활동 사이의 경합 — 원격 claim 목록·미머지 브랜치 분류는 세션 중에도 바뀌었다(실제로 점검 도중 q8tvcx가 "이미 포팅됨—원본 정리만 필요" 분류로 전환되는 것을 관측, §1-G1).

## §1. 축 A — 빌드 하네스 (규약 ↔ 구현)

**건강 실측**: `validate` green(점검 시작 시 태스크 229·게이트 7·트랙 3, 위반 0 · 종료 시 232건 green) · HARN-06~19 등재분 13건 전부 done · 테스트 251건(`tests/harness`)+배선 계약(`tests/infra`)이 CI required check 2잡으로 실행 · 훅 3종(SessionStart brief / PostToolUse check-edit / Stop check-stop) 배선 실재·`test_session_start_brief_wiring.py` 동결.

### G1 — HARN-15 비가시 부채 (최대 갭 · 단일 진실 원천 축) → ✅ 회수 완료

| 항목 | 실측 |
|---|---|
| 결함 | `HARN-15-id-collision-cross-branch-scan`(번호 가드의 관측 표면 확장 + OPS-17/18 이중 배정 처분)이 **미머지 브랜치 `claude/whymath-ai-recommendation-review-q8tvcx`에만 존재** — main `backlog/tasks/`는 HARN-06~19 중 15만 공백 |
| 영향 | "backlog = 단일 진실 원천"이 이 항목에서 파손 — `next`/`status`/`/drive` 어디에도 안 뜸. "HARN-15가 정본 소유자·중복 등재 금지" 원칙(HARN-16 등재 경위) 때문에 main에 대체 표식도 없음 |
| 소실 경로 | 브랜치 정리 파이프라인 실가동 중(MEMORY 2026-08-10 "17건 전건 삭제 성공·Actions 경유") + q8tvcx가 브리핑에서 "이미 포팅됨—원본 정리만 필요" 분류 = **다음 삭제 배치 후보**. 원격 실존 실측: `ls-remote` → `e1835c0c`(2026-08-10) |
| 처리 | Kiki 확정(택1 질문): **정본 YAML 그대로 회수** — `git checkout origin/...q8tvcx -- backlog/tasks/HARN-15-*.yaml`(ID·소유권·acceptance 보존, 손편집 아님·포팅 관례) → validate green. **재채번 실행 판정은 acceptance 원문 그대로 Kiki 전권 유보** |
| 잔여 | `claude/s3-25-bucket-c-renumber-fix` 브랜치(재채번 수정분·push만 되고 PR 미생성)는 "미해결 11건" 목록의 Kiki 결정 대기 그대로 |

### G2~G3 — 스킬↔규약 불일치 → ✅ 정정 완료

- **G2** `.claude/commands/gates.md` 말미가 **gates.yaml 손편집을 지시** — HARN-18(2026-08-10 머지)로 `gates add` CLI가 생겼는데 미반영. "대장은 CLI로만·거부의 우회 금지" 규약을 스킬이 스스로 위반 유도 → CLI 경유 §4 절 신설로 정정.
- **G3** `.claude/commands/plan.md` §4 add 명령 블록에 **`--path` 부재** — 규약 v1.1 "add --path 관례화"와 불일치, /plan 산출 태스크가 구조적으로 paths 없이(겹침 감지 입력 없이) 등재되던 상태 → 블록·불릿 보강.

### G4~G5 — CLI 자체의 선언≠배선·데이터 파괴 → 📋 HARN-20 등재

- **G4** `STATUS_TRANSITIONS`(models.py:76-83)가 선언한 `review`·`cancelled` 상태에 대응 CLI 동사가 없어 **도달 불가**(실데이터 0건/229·in-flight 취급 코드는 존재). `declared_unwired_audit`(OPS-22)는 제품 하네스만 감사해 이 축은 사각.
- **G5** `block`이 `task.notes = args.reason` **덮어쓰기**(backlog.py:603) — 태스크의 발견 경위·설계 근거가 block 1회로 소실(blocked 4건 전건 흔적)·unblock 미복원.

### G6~G7 — 번호 가드·reap의 잠복 결함 → 📋 HARN-21 등재

- **G6** `store.id_number_of`의 `_ID_NUMBER_RE`가 끝 하이픈(슬러그)을 요구 → **슬러그 없는 정규 ID(`HARN-20`)는 1선(add)·2선(validate) 번호 충돌 검사를 양쪽 다 통과**(실측 `id_number_of('HARN-20')=None`). `_next_free_number`는 index≥100에서 `TASK_ID_RE(\d{2})` 위반 3자리 제안(E1-90 실재 — E1-99 도달 시 발현).
- **G7** `claims reap`의 `task_missing` 분류(remote_claims.py:759-762) — 타 세션이 add+claim한 직후 내 클론에 YAML이 없으면 **TTL 무관 즉시 reap 대상**. 병렬 세션 창에서 살아있는 claim 삭제 가능.

### G8 — 규약 문서·주석 노후 → ✅ 정정 완료 (문서분)

`build_harness.md` §7에 `gates add` 누락 · 테스트 수 3중 불일치(문서 188/CI 주석 153/실측 251) · v1.1 이후 §4(HARN-16) 추가에도 버전 미갱신 → v1.2로 정정. 코드 docstring의 옛 `refs/claims/*` 네임스페이스 4곳(models.py:250·selector.py:65·report.py:164·remote_claims.py:120)과 `check-stop`의 unknown-branch 자동 통과(backlog.py:970-994)는 **보고만**(§7 — 주석·경계 동작이라 코드 태스크 대비 위험 낮음, HARN-20 작업 시 동반 정리 권장).

### 관측 정상 확인

정책 3룰(path_overlap/scope_drift/adhoc_edit) 전부 `warn` 유지 — `events.ndjson`에 adhoc_edit 경고가 축적 중(측정 설계 의도대로 작동). 승격은 §3c 기준(2주/30세션·정탐률≥50%) 미충족으로 판단 유보가 옳다. **본 세션의 문서 편집도 adhoc_edit warn으로 기록됐다** — Kiki 직접 지시 세션이며 관측이 일하고 있다는 실측이다.

## §2. 축 B — 헌법·표준 문서 ↔ CLAUDE.md (D-1~D-29)

깨진 참조(완전 부재 경로) **0건** · 헌법↔CLAUDE.md 종속 선언(정본 관계·충돌 시 우선) **완전 일치** · 정합 확인 축 15개(모델 핀 3자 일치·pgvector 4자 일치·Wolfram 미구현 3자 일치·검증 권위 서열 3자 정합·crosswalk 비대칭 문구 일치 등). 결함은 아래 29건 — **🔴 5·🟡 17·🟢 7, 처리: ✅ 정정 22 · ⏸ 보고만 7**.

| # | 파일·위치 | 결함 | 심각도 | 처리 |
|---|---|---|---|---|
| D-1 | `CLAUDE.md` 푸터 | "버전 0.1.0·최종 수정 2026-05" vs 본문 2026-08-09 규칙·git 실측 08-09 — 3개월 괴리, 다음 검토일 무기한 | 🔴 | ✅ v0.2.0·08-10·갱신 의무 부기 |
| D-2 | `CLAUDE.md` 스택 표 Graph DB | Neo4j를 단서 없이 런타임 스택처럼 제시 — 실측: 런타임 미도입(2026-08-03 확정)·data-pipeline 옵셔널 한정·backend 의존 0 (Wolfram·GPT-5 행은 단서 有) | 🔴 | ✅ 실측 단서 병기 |
| D-3 | `00_overview.md` :13·:131·:167 | 폐기 스택 Mathpix 3곳 잔존 — CLAUDE.md:57이 지목하는 계층 정본이 2026-05-28 폐기 스택 보유 | 🔴 | ✅ PaddleOCR+Qwen3-VL |
| D-4 | `data_pipeline.md` :15-16 | Mathpix 2곳 잔존(같은 표 22행 pgvector만 갱신된 부분 갱신) | 🔴 | ✅ |
| D-5 | `dev_constitution.md` §0.1 | 우선순위 3번 **"교수학적 정확성"이 "데이터 무결성"으로 통째 대체**(미자각) + 1번 "웰빙" 누락(자각·부기만) — 정체성 축이 헌법 우선순위에서 실종 | 🔴 | ✅ 정본 7항 정렬·정정 이력 절 |
| D-6 | `00_overview.md` :131 | OCR을 L3 배치(정본은 L5 상호작용) | 🟡 | ✅ L5 |
| D-7 | `00_overview.md` :166 | 임베딩 te-3-large 옛 표기(정본·코드 = bge-m3 기본) | 🟡 | ✅ |
| D-8 | `data_pipeline.md` :20 | KoSimCSE — 코드 어디에도 없음 | 🟡 | ✅ bge-m3 |
| D-9 | `ROADMAP.md` :48 vs :39 | "Mathpix API 계정" 미완료 항목 잔존 — :39 교정 선언과 한 파일 내 자기모순 | 🟡 | ✅ |
| D-10 | `ROADMAP.md` :30 | "미반영" 목록에 이미 반영된 항목(페르소나 5종·OCR 결정) 잔존 | 🟡 | ✅ |
| D-11 | `ssm_scan_2026-Q3.md` #9 | "임베딩 표/코드 불일치(실재 미결)" — 현행 CLAUDE.md는 이미 정정 완료, 열린 항목 미폐쇄 | 🟡 | ⏸ 시점 리포트 불변(본 절이 폐쇄 기록) |
| D-12 | `ssm_scan_2026-Q3.md` :17 | 미배선 GPT-5·Gemini를 "현행 베이스라인"으로 기술 | 🟡 | ⏸ 동상 |
| D-13 | `ssm_scan_2026-Q3.md` :58·:156·:215 | Neo4j 삼중 store·403노드 — 2026-08-03 정정 전 세계관 | 🟡 | ⏸ 동상 |
| D-14 | `CLAUDE.md` :42 | L6 모드 5개 나열 vs 정본 `06_application_modes.md` 7개 | 🟡 | ✅ 7모드 정렬(00_overview :11 6개도) |
| D-15 | `build_checkpoint_questions.md` :20 vs :48-54 | 노드 수치 자기모순(437/403·2,697/1,837) + 문서 간 4가지 수치(2,683·541엣지) | 🟡 | ⏸ DB 실측 불가 — §7 |
| D-16 | `CLAUDE.md` 문서 인덱스 | 구속력 있는 정본 다수 누락(testing·security_privacy·SLO·crosswalk·coding·data_pipeline·parallel_sessions·checklist) | 🟡 | ✅ 8줄 보강 |
| D-17 | `testing.md` :97·`coding_python.md` :51 | "LLM 반드시 모킹" 무단서 — SDK 표면 실측 검증 금기(langfuse 사고)와 긴장 | 🟡 | ✅ 단서 부기 |
| D-18 | `coding_python.md` :49-50 | 커버리지 "핵심 80%+" — testing.md 계층 floor(l4=90%)에 미달하는 낡은 수치 | 🟡 | ✅ 정본 포인터로 교체 |
| D-19 | `dev_constitution.md` :23 | `CLAUDE.md:287` 줄 앵커 부식(실제 :292) — 줄-앵커 방식의 구조적 부식 표본 | 🟡 | ✅ 절-제목 앵커로 전환 |
| D-20 | `build_harness.md` :242 | 테스트 수 188(실측 251·CI 주석 153) | 🟡 | ✅ 실측+스냅샷 주의 부기 |
| D-21 | `prompt_engineering.md` | 표준 문서 중 유일 메타데이터 전무 + `docs/prompts/` 10종과 연결 고리 없음 | 🟡 | ⏸ §7(내용 개정은 별도 판단) |
| D-22 | `00_overview.md` | 문서 수준 버전·갱신 이력 없음(인라인 날짜만) | 🟡 | ⏸ §7 |
| D-23 | `superhuman_...md` :91 | seeder 경로 오도(`harness/` → 실제 `l4/misconception/`) | 🟢 | ✅ |
| D-24 | `superhuman_...md` :39 vs :129 | 590문 vs 620문 자기모순 | 🟢 | ✅ 620·확장 전 수치 부기 |
| D-25 | 3문서 공식 4번째 항 | "1세션=1도메인=1브랜치=1{태스크 vs worktree}" 흔들림 | 🟢 | ⏸ §7(실질 동치 — 세션당 worktree 1=브랜치 1=태스크 1) |
| D-26 | `math_ai_failure_checklist.md` :66 | 카탈로그 32/64종·841/839 문서 간 차이(기준일 상이) | 🟢 | ⏸ §7 |
| D-27 | `current_phase_checklist.md` :55 | ChromaDB 명칭 잔존(괄호로 해소된 문맥) | 🟢 | ⏸ 오독 위험 낮음 |
| D-28 | `CLAUDE.md` 워크플로우 | `/deploy` 스킬 실재하나 헌법에 미언급 | 🟢 | ✅ 배포 시 블록 신설 |
| D-29 | `build_harness.md` :243 | CI `pytest -q` 표기가 2026-08-09 "-q 판정 금지" 금기와 표면 긴장(실질 위반 아님 — exit code 판정) | 🟢 | ✅ 예외 아님·준수 사례 1줄 부기 |

**문서 버전·날짜 위생(횡단 관찰)**: 조사 8종 중 표기가 실체와 맞는 문서는 `system_superiority_maintenance.md` 1종뿐이었다. `prompt_engineering`·`parallel_sessions`·`playbook_part_review_questions`는 헤더 메타데이터 자체가 없다. 이번 정정으로 CLAUDE.md·build_harness는 갱신 의무·버전을 정렬했으나, **표준 문서 전반의 헤더 메타 의무화는 규칙 신설 없이 관찰로 남긴다**(§7 — 1회 관측이며 기계 강제 설계 없이 산문 규칙만 늘리는 것은 규칙 폭발).

## §3. 축 C — MEMORY 추적성·CI 집행

### 추적성 (규칙 ↔ 결정 로그)

- **순방향 6/6 온전**: CLAUDE.md 규칙이 인용하는 6대 사고(07-16 게이트②·07-17 좀비 uvicorn·07-26 OPS-06·07-27 claims 403·08-04 PED-06·08-09 black -q) 전건 MEMORY 실재.
- **역방향 미등재 2건 발견 → ✅ 본문 등재**: MEMORY가 "재발방지 등재"로 선언했으나 CLAUDE.md에 없던 ①**"작동한 비율" 원칙**(MEMORY:1616·2026-08-03·반복 실수 8회차) ②**"유예·제외의 만료 지점" 규칙**(MEMORY:1780 — 의도적 코드 착지였으나 CLAUDE.md만 읽는 세션은 원칙을 모름). 둘 다 프로세스·안내 절에 사고 경위 1줄 병기로 등재.
- **부분 미반영 1건 → ✅ 확장**: HARN-19가 스스로 "인코딩 규칙을 서브프로세스 출력 축으로 확장"이라 분류했으나 CLAUDE.md 규칙 본문은 설정 파일 축만 — 본문에 축 추가.
- **MEMORY 자체 위생(보고만·소급 수정 금지)**: :490이 PED-06 경위를 "PED-08"로 오기(CLAUDE.md:138이 정확) · :519의 줄번호 참조(:135) 드리프트 · "시간 역순" 선언이 07~08 구간에서 미준수(날짜 뒤섞임 — 줄 순서로 시간 추정 금지) · 트레일러 "최종 수정 2026-05-28" stale·"매월 첫째 주 정기 리뷰" 실행 기록 0건. → 신규 결정 로그 항목에 정정 부기(본문 소급 변조 없이).

### CI 집행 (규칙 → 기계 배선)

- **배선 사각 0**: `tests/` 최상위 4디렉터리 전부 잡에 연결(backend·data_pipeline·harness·infra) — `test_test_suite_wiring.py`가 기계 동결, `_INTENTIONALLY_UNWIRED = {}`. 린트도 파이썬 트리 전역 커버.
- **특성 3건(보고 — §7)**: ①경로 필터로 skip된 잡을 GitHub가 required check *충족*으로 처리 — 문서 단독 PR은 backend 게이트 7종 미실행(이번 점검도 해당: **CLAUDE.md 마커 동결 테스트 2종은 merge 후 main push CI에서야 돈다** — 그래서 커밋 전 마커 61건 로컬 대조를 수행, 부록 E) ②fail-open 잔존 2곳: `qa_pipeline` 게이트 `continue-on-error`(S3-28 완료 시 제거 예정 — 기존 태스크 소유)·shellcheck ③`policy-guard`는 CLAUDE.md 금기 중 2종(교과서 본문 패턴·시크릿)만 기계 집행 — 나머지 규칙의 집행은 훅·테스트·사람 관측 분산.

## §4. 축 간 상호 정합 — 통합 판정

| 이음새 | 판정 | 근거 |
|---|---|---|
| 규약 문서 ↔ 하네스 구현 | ⚠️→✅ | CLI 실체가 문서보다 앞서 있었다(gates add·테스트 수·버전) — 문서를 실체로 정렬. 남은 선언≠배선(전이표)은 HARN-20 |
| 스킬(.claude/commands) ↔ 규약 | ❌→✅ | /gates 손편집 지시·/plan --path 누락 — 스킬이 규약 위반을 *유도*하던 두 곳 정정. 스킬은 규칙의 실행 표면이므로 규약 개정 시 스킬 동기화가 후속 관례여야 함 |
| 헌법 ↔ CLAUDE.md | ⚠️→✅ | 종속 선언은 완전 일치·본문 1개 절(§0.1)만 어긋남 — 정렬 완료. 헌법의 "repo가 헌법보다 앞섬" 자인 구조는 모범 유지 |
| CLAUDE.md ↔ 하위 정본 문서 | ⚠️→✅ | 정본이 가리키는 문서(00_overview)가 폐기 스택 보유 — 참조 대상의 신선도가 참조자의 신뢰를 결정한다. 전파 정정 완료 |
| 규칙 ↔ MEMORY | ⚠️→✅ | 순방향 온전·역방향 2건 미등재 — "등재 선언"과 "등재 실행" 사이 간극은 PED-06(정본화≠집행)의 문서 축 변형이다 |
| 규칙 ↔ CI 집행 지점 | ⚠️ 관찰 | 기계 집행은 2금기+훅+테스트 동결에 한정 — 구조적으로 온전하나, 문서 단독 변경의 검증 창이 좁다(마커 로컬 대조로 보완, §7) |
| 백로그 ↔ 미머지 브랜치 | ❌→✅ | HARN-15 비가시 — "단일 진실 원천"의 유일한 실측 파손점. 회수 완료·관측 표면 확장 자체는 HARN-15가 소유 |

## §5. 이번 세션 반영분 (정정 실행 기록)

- **커밋 ① `150da189`** — 문서·스킬 정정 11파일(+73/−36): CLAUDE.md(규칙 2건 등재·HARN-19 축·Neo4j 단서·L6 7모드·인덱스 8줄·/deploy·푸터 v0.2.0) · dev_constitution §0.1 · 00_overview·data_pipeline·ROADMAP 스택 잔존 · /gates·/plan 스킬 · build_harness v1.2 · superhuman·coding_python·testing.
- **커밋 ② `5151b987`** — backlog 4파일(+91): HARN-15 회수 + HARN-20·21 등재 + events.
- **스택 표 변경 의무 이행**: Graph DB 행 단서 병기는 "변경 시 MEMORY 결정 로그 필수" 규칙에 따라 MEMORY 2026-08-10 항목에 근거 기록.
- **검증**: `backlog.py validate` → green 232건·exit 0 / CLAUDE.md 동결 마커 61건 전건 보존(missing=0) / diff 내 시크릿·교과서 본문 패턴 0 / **pytest 로컬 미실행 — CI가 최종 판정**.

## §6. 태스크 등재 (전건 `backlog.py add` CLI 경유 — ID 손편집 0)

| 태스크 | 요지 | stage | priority | 근거 |
|---|---|---|---|---|
| `HARN-15-id-collision-cross-branch-scan` | (회수 — 신규 아님) 번호 가드 관측 표면 확장 + OPS-17/18 처분(Kiki 판정) | S3 | 3 | §1 G1 — q8tvcx 정본 그대로 |
| `HARN-20-cli-transition-wiring-and-block-notes` | review·cancelled CLI 도달 불가 + block의 notes 파괴 | S4 | 2 | §1 G4·G5 |
| `HARN-21-id-guard-parser-and-reap-hardening` | 슬러그 없는 ID 미인식·3자리 제안 + reap task_missing 유예 | S4 | 3 | §1 G6·G7 |

**중복 소유권 회피 실측**: 등재 전 확인 — 열린 HARN 태스크 0건(등재분 13건 전부 done)·HARN-15의 acceptance와 HARN-21의 범위가 겹치지 않도록 HARN-21 ⑤에 "관측 표면 확장은 HARN-15 소유·중복 착수 금지"를 명문화. 원격 claim 목록(ASM-05·MISC-04/06·SEC-15)과 paths 무겹침. add CLI의 번호 충돌 검사 통과(제안 번호 수정 없음).

## §7. 정직한 공백 — 이 점검이 하지 않은 것

1. **재채번 실행** — S3-26/27/28·OPS-17/18 이중 배정의 재배번 대상·시점은 HARN-15 acceptance 원문대로 **Kiki 전권**. 회수는 가시화까지만. — *후속(2026-08-11): 판정 완료. S3-26/27/28은 재채번 불실행 확정(moot 추인), 착지대 브랜치는 SHA `05a1a344` 보존+폐기, 판정 권한은 `HARN-213`(원 HARN-22)으로 승계. 정본 = `docs/reviews/id_renumber_verdict_2026-08-11.md`. 같은 실측에서 미등재 live 이중 배정 16건이 새로 발견됐다(부채 회전).*
2. **시점 리포트 원본 수정 안 함** — ssm_scan 2026-Q3(D-11~13)·arch_audit r1~r8 등은 시점 산출물 불변 관례(완료 태스크의 근거 소급 변조 금지). 폐쇄 기록은 본 보고서 §2가 보유.
3. **MEMORY 본문 소급 수정 안 함** — :490 오기 등은 신규 항목에 정정 부기.
4. **노드 수치 정본화 안 함**(D-15) — 이 환경에서 DB 실측 불가. 4가지 수치의 어느 것이 현재값인지 판정하지 않았다.
5. **CI 경로 필터·fail-open 재설계 안 함** — qa_pipeline은 S3-28 기존 소유, 문서 단독 PR 창 문제는 관찰만(이번엔 마커 로컬 대조로 보완). 별도 태스크 등재는 실익 대비 과잉으로 판단.
6. **정책 warn→block 승격 안 함** — §3c 측정 기준 미충족(측정 없는 승격 금지).
7. **표준 문서 헤더 메타 의무화 규칙 신설 안 함** — 기계 강제 설계 없는 산문 규칙 추가는 규칙 폭발. 재발 시(2회+) 실수 관리 규약에 따라 등재.
8. **refs/claims 옛 docstring 4곳·check-stop unknown-branch 우회·declared_unwired_audit 빌드 하네스 축** — HARN-20 작업 시 동반 정리 권장으로만 남김(acceptance ⑤에 사각 명시).
9. **prompt_engineering.md 내용 개정** — 메타데이터 부재만 지적(D-21). 프롬프트 기준 자체의 개정은 `/prompt-design` 축 별도 작업.

## §8. 반복 실수 대장 연동

| 유형 | 회차 | 이번 점검에서의 위치 |
|---|---|---|
| 선언≠배선(정본화를 집행으로 착각) | 기존 등재(PED-06 계열) | **문서 축 변형 2건 발견**: MEMORY "규칙 등재" 선언 후 CLAUDE.md 미반영(§3) · 전이표 선언 후 CLI 미배선(§1 G4) — 규칙 신설 없이 기존 규칙의 사례로 흡수(동일 유형 신규 발생 시 회차 승계) |
| 문서 표기 stale(부분 갱신) | 다수 표본(D-1·D-4·D-10·D-20) | 정정 + CLAUDE.md 푸터에 갱신 의무 부기. 기계 동결은 미설계(§7-7) |
| 미병합 고립 | 3회차(2026-08-03 등재 계보) | HARN-15가 4번째 표본이 되기 직전 회수 — "만료 없는 유예·제외 금지" 규칙 본문 등재(§3)가 이 계보의 텍스트 축 보강 |

## 부록 — 실측 근거 (2026-08-10)

- **A. 하네스 실측**: `backlog.py validate` → `✔ 백로그 무결성 green — 태스크 232건, 게이트 7건, 트랙 3건`·exit 0. 상태 분포(점검 시): done 171·todo 53·blocked 4·in_progress 1 = 229 → 회수·등재 후 232. `status` 스테이지: S1 14/15·S2 완료·S3 73/89·S4 66/95·S5 0/1.
- **B. HARN-15 계보**: 파일 `backlog/tasks/HARN-15-id-collision-cross-branch-scan.yaml`(blob `f9cc2f87`, q8tvcx 최종 커밋 `e1835c0c` 2026-08-07) · 원격 실존 `ls-remote` → `e1835c0c`(2026-08-10 실측) · 경위 문서 `docs/reviews/unmerged_branch_triage_2026-08-04.md:133-162`·`backlog/tasks/HARN-16-*.yaml` notes · 재채번 부채 MEMORY:581·596-609.
- **C. 코드 앵커**: STATUS_TRANSITIONS `scripts/harness/models.py:76-83` · block 덮어쓰기 `backlog.py:603` · 번호 정규식 `store.py`(`_ID_NUMBER_RE`)·grandfather 2건 `store.py:393-405` · reap 분류 `remote_claims.py:759-762` · check-stop 통과 조건 `backlog.py:970-994` · 훅 배선 `.claude/settings.json`(SessionStart=`brief --format hook`).
- **D. CI 앵커**: `ci.yml` 16잡 — `harness-integrity`(:977~·validate+claims 교차검증+ruff/black+pytest tests/harness)·`infra-contracts`(:708~·pytest tests/infra)·`policy-guard`·`declared-unwired-audit`. required check 목록 `.github/branch-protection-setup.md` ↔ `test_required_checks_doc.py` 동결. 브랜치 정리 경로 `branch-cleanup.yml`(MEMORY 2026-08-10 17건 삭제 실측).
- **E. 마커 검증**: `tests/backend/test_failure_prevention_manifest.py`·`test_ai_collaboration_protocol_manifest.py`의 모듈 레벨 튜플 str 상수 61건을 AST 추출 → 경로형은 실재·마커형은 참조 문서 집합 부분일치 대조 → `checked=61 missing=0`(스크립트: 세션 스크래치 `check_markers.py` — 원리: 경로/마커 분류 후 전건 대조).
- **F. 정합 확인 15축(문제없음)**: 클라우드 모델 핀(config.py:351-359 ↔ CLAUDE.md:77) · LOCAL_MODEL_MATRIX 3자 일치 · pgvector 4자 · bge-m3(config.py:891·901) · Wolfram 미구현 3자 · PaddleOCR 결정 5문서 · 검증 권위 서열 3자 · crosswalk "승인은 사람 전용" 문구·코드 동결 · 시크릿 3자 역할 분담 · 라우터 경유 계층 정합 · 커버리지 집행(check_layer_coverage.py 실재) · 병렬 세션 CODEOWNERS 일치 · 플레이북 상보 구조 · 금기 무모순 · 참조 실재성 전수.

---

**작성**: 2026-08-10 통합점검 세션(브랜치 `claude/whymath-constitution-rules-check-azdnov`) | **정정 커밋**: ① `150da189` ② `5151b987` | **MEMORY**: 2026-08-10 (통합점검·거버넌스) 항목
