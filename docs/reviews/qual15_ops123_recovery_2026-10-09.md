# QUAL-15 · OPS-123 회수 판정 기록 (2026-10-09)

판정 기준: main `594ce16b` + 브랜치 `claude/qual-15ops-123-kkj3nz` (미머지 — 이 문서의 "충족"은 브랜치 기준이며 머지 후에야 main 기준이 된다).
원 브랜치: `claude/friendly-pascal-mnmypk`(`c229d21c`) · `claude/blissful-lovelace-ubp9tw`(`d4e4b432`). **머지 전까지 삭제 금지.**

## 1. 요약

- 두 고립 구현을 main 현행 위에 파일 단위로 이식했다. 통째 머지·3-way 병합은 쓰지 않았다(브랜치가 main보다 118·123 커밋 낡음).
- 이식 중 브랜치 자신의 테스트 결함 2건과 격리 미적용 지점 4곳을 찾았다. 앞의 둘은 고쳤고 뒤의 것은 승계 태스크로 분리했다.
- 로컬 CI 재현: 닿는 잡 11개 중 10개 전 스텝 통과, `docker-build`는 도커 데몬이 없어 미재현(§5).

## 2. QUAL-15 — mnmypk 회수

### 이식과 대조

| 대상 | 방식 | 결과 |
|---|---|---|
| 생성기 | 브랜치 diff를 패치로 재적용 | +23/−8. main이 넣은 `deterministic_generator` import·데코레이터 보존 |
| 관례 동결 테스트 | 브랜치 파일 그대로 | 104줄, 6건 통과 |
| 코퍼스 600행 | 이식한 생성기로 CLI 재생성 | 600/600 적재, 게이트 거부 0 |
| `_provenance.json` | `regeneration` 블록 추가 | 기존 `recovery`·`review_status` 보존 |

바이트 단위 비교는 불가능했다. main은 그 사이 모든 행에 `authored_by`를 추가했고, 구 코퍼스는 현행 직렬화기가 내는 `schema_version`·`extensions`·`relations`가 없었다. 그래서 의미 필드로 대조했다: `problem_id`·`slug`·`question_text`·`answer`·`answer_explanation` **600/600 일치**, 공통 키 전체 값 차이 0, 브랜치에 없는 키는 `authored_by` 하나(main 고유).

검수·승인 상태: 코퍼스에 `review_status` 필드는 없고 `is_published`만 있으며 600/600 `False` 그대로다. `authored_by` 600/600 보존.

### 집행 지점

관례 동결 테스트는 `tests/backend/harness/`에 있고 backend 잡의 `Pytest (with coverage)` 스텝(`-m "not corpus_authoring"`, `testpaths=../../tests/backend`)이 수집한다. 이 테스트는 `corpus_authoring` 마커가 없다. 로컬에서 같은 경로로 수집돼 6건 통과.

### 변별력 (주입 적용 `mutated != original`·원복 바이트 동일 단언)

- 생성기 4종 RED: ceil 발문 옛 표현 복귀 · round 발문 옛 표현 복귀 · ceil 정답 계산 변조 · 답=입력값 필터 제거. 사후 해시 동일.
- 코퍼스 3종 RED: 정답 오염 · 옛 발문 · 답=입력값.

### QUAL-11 acceptance 재대조 (main 기준)

| 항 | 판정 |
|---|---|
| ① 537/600 불일치 실측 | 사실 기록 — 이행 대상 아님 |
| ② 발문 교정 + 답=입력값 제외 | 이행 |
| ③ 회귀 동결 테스트 + 뮤테이션 | 이행 |
| ④ 일반화 판정(구현 금지) | 판정 완료(신설 필요). 승계 `QUAL-12`가 main에 이미 등재 |

**QUAL-11은 이 브랜치가 머지된 뒤 닫을 수 있다.** 미이행 항 없음. 교수학 확인은 교과서 정식 표현 관례에 근거한 것이며 사람 교수학자 검수가 아니다.

## 3. OPS-123 — ubp9tw 회수

### 이식

신규 5파일(`l3/isolated_call.py` 365줄 · `api/_isolated_call.py` 92줄 · 테스트 3종)은 그대로, 기존 7파일은 브랜치 diff를 패치로 재적용(`coach.py`·`config.py`는 main이 분기 후 바꿨으나 변경 위치가 떨어져 깨끗이 적용, 적용 후 diff를 읽어 현행 `_final_answer_state` 호출 지점을 확인). 인벤토리는 main 현행 `WM-E-355` 행에 모듈 2종을 귀속했다.

### 브랜치 테스트 결함 2건 (원인 규명 후 수정)

1. `test_coach_final_answer_isolation`: `elapsed < 2.0` 단언이 환경에 취약. `max_workers=1`이라 첫 호출이 워커를 kill한 뒤 폼 판정 호출이 교체 워커의 `ready`(SymPy import)를 약 1.4초 기다린다(설계상 상한 밖). 합계 약 1.9초로 경계에 0.1초 차이였다. 풀의 `timeouts` 카운터 증가(인과 증거)로 대체했다.
2. `test_verify_isolation` 지연 측정 헬퍼: 고정 0.15초 `sleep`이 "느린 요청이 이미 SymPy 안에 있다"를 가정한 경쟁 조건. 핸들러의 SymPy 진입 시각이 0.10~0.33초로 흔들려 대조군이 단독 실행 3회 중 2회 실패(늦어짐 0.49·0.59초), 격리 ON 쪽은 격리를 되돌려도 통과할 위험이 있었다. 진입 시각을 의존성 스레드에서 기록해 기준점으로 삼았고, 수정 후 8/8 통과.

### 서빙 경로 경유 (집행 지점)

`tests/backend/api/test_isolation_call_sites_governance.py`(AST, 5건): `verify.py` 전 `async def`와 `coach.py::_final_answer_state`에서 검증 함수는 `isolated(...)`의 첫 인자로만 나타난다. `to_thread`·`partial`·람다 우회도 같은 참조 규칙으로 걸린다. 주입 4종 RED(코치 격리 제거 · 람다 우회 · 미격리 지점 추가 · 승계 태스크 done).

### 변별력 (OPS-96 ④)

- 뮤테이션 8종 전건 RED: 격리 되돌림 · 초과를 통과로 접기(단계·답) · 코치 초과값을 정답으로 · 코치 격리 제거 · 상한 미적용 · kill 생략 · 체인 총 예산 제거.
- ⓑ 명시: 격리 되돌림에서 `test_light_request_is_not_blocked_by_slow_sympy`가 「가벼운 요청이 5.14s 늦어졌다 — 루프 차단」으로 RED, 정상 코드에서는 통과.

### 상한값 실측 (OPS-96 ⑤)

`scripts/analysis/measure_sympy_isolation_budget.py`로 코퍼스 37종 문항 14,034건의 정답 제출 검증을 쟀다. 전건 `correct`. 소요: p50 1.2ms · p90 2.9ms · p99 11ms · p99.9 24.6ms · 최대 107.5ms. 상한 0.25초 이상 어느 후보값에서도 초과 0건. **기본 5.0초 유지** — 정상 최대의 약 46배이고, 구조 예산을 통과하는 가장 느린 병리 입력(차수 20 방정식 약 3초)은 통과시키되 그보다 느린 것(계수 7919에서 약 10초)은 끊는 위치다.
한계: 학생 풀이 **단계** 입력의 정상 분포는 코퍼스에 없어 미측정이다(`OPS-126`).

### OPS-96 acceptance 재대조

| 항 | 판정 |
|---|---|
| ① 동기 SymPy 호출 지점 AST 전수 열거 | **부분.** 서빙 경로 열거 결과 verify 3 + 코치 최종답 2는 격리 완료. 코치 `step_chain` 3곳·`attempt_misconception_detector` 1곳은 학생 풀이를 이벤트 루프 안에서 동기 검증 → `OPS-125` |
| ② 격리 방식 판정(스레드 vs 프로세스) | 이행 — 프로세스. 스레드는 상한 초과 뒤에도 CPU 계속 소모(모듈 docstring 실측) |
| ③ 상한 초과 = 판정 불가 | 이행 — `unverifiable`, 통과·오답 아님, 사유 로그 |
| ④ 변별력 | 이행 — 위 |
| ⑤ 범위 밖 동결 + 상한 실측 | 최종답 경로 이행, 단계 경로 미측정 → `OPS-126` |

판정: OPS-96의 **명시된 범위**(검증 엔드포인트 + 코치 최종답)는 이행됐다. 그러나 OPS-96이 막으려던 증상(느린 식 1건이 워커를 멈춘다)은 코치 `step_chain` 경로에 `OPS-125` 전까지 남는다. 닫는 시점은 사람이 판단한다.

### 승계 태스크

- `OPS-125-coach-step-chain-isolation` — `_build_response_payload`가 동기 함수라 호출부에서 await로 감쌀 수 없다. 설계 판정이 필요하다.
- `OPS-126-isolation-served-ratio-observability` — `isolation_stats()`를 읽는 비테스트 코드가 0건이다("작동한 비율" 원칙의 갭). 단계 입력 기준 상한 재판정·운영 용량(프로세스 수 × 약 100~150MB)도 포함.

## 4. 기본값 판단

`sympy_isolation_enabled` 기본 ON. 위험한 신규 기능은 기본 OFF, 결함 수정은 기본 ON이 이 저장소 관례이고 OPS-96은 가용성 결함이다. 되돌림 스위치는 `WHYMATH_SYMPY_ISOLATION_ENABLED=false`. **배포 영향: 서버 워커마다 최대 2개의 SymPy 상주 프로세스가 생긴다**(첫 호출에 지연 기동, 앱 기동 직후 0개 실측).

## 5. 로컬 CI 재현 (잡 19개 전수 열거)

| 잡 | 닿는가 | 근거 | 결과 |
|---|---|---|---|
| changes | 간접 | 경로 필터 | — |
| backend | 닿음 | `src/backend/`·`tests/backend/`·`data/corpus/` | ruff·black·mypy --strict·lint-imports·전체 스위트 18240 passed/619 skipped/1 xfailed·계층 커버리지·게이트 17종·tests/constitution 전건 통과 |
| backend-migrations | 닿음 | 같은 `backend` 플래그 | 실 PG16+pgvector 위에서 10스텝 통과, 통합 580 passed/13 skipped(Redis·OpenAI 키 미도달) |
| data-pipeline | 닿음 | `corpus` 플래그(`data/corpus/`)가 이 잡 `if`에 포함 | ruff·black·mypy·pytest 963 passed·`qa_pipeline` 통과 |
| corpus-authoring | 닿음 | `authoring` 플래그(`tests/backend/harness/`·`l3/equivalent/`) | 통과 |
| docker-build | 닿음 | `docker` 플래그(`src/backend/`) | **미재현** — 도커 CLI만 있고 데몬 없음. 대체: 앱 기동 `/health/live` 200·풀 지연 기동 확인, `tests/infra/test_deploy_artifacts.py`는 infra 잡에서 통과 |
| infra-contracts | 상시 | 조건 없음 | 7스텝 통과, `tests/infra` 2940 passed |
| infra-shell · policy-guard · declared-unwired-audit | 상시 | 조건 없음 | 통과 |
| harness-integrity | 상시 | 조건 없음 | 결정론 스텝 전건 통과(audit-deps·rules lint/render·jit·위헌 심사 래칫·헌법 스텝 4종·ruff·black)·`tests/harness` 2256 passed. `backlog validate`는 두 태스크 동시 claim으로 막혀 `done` 처리 뒤 재확인(§7). 네트워크 의존 관측 스텝(ADR 번호·claim·고립 브랜치)은 fail-open이라 미실행 |
| data-pipeline-integration · data-pipeline-neo4j | 안 닿음 | `data_pipeline` 플래그 미발화(`src/data-pipeline/` 무변경) | — |
| mobile · concept-reach-guard · web · webapp | 안 닿음 | 해당 경로 무변경(`data/corpus/`는 `data/[^/]+$`에 안 걸림) | — |
| e2e-nightly · backend-serial-nightly | 안 닿음 | 스케줄 전용 | — |

## 6. 한계

- 도커 이미지 빌드·컨테이너 기동은 확인하지 못했다.
- 격리 풀은 프로세스별 카운터다. 다중 프로세스 합산 관측은 `OPS-126`.
- 타이밍 단언 테스트(`TestEventLoopNotBlocked` 등)는 CI 러너 부하에서 재검증이 필요하다. 이 샌드박스 4코어에서는 전체 스위트 병렬(`-n auto`) 하에서 통과했다.
