# P3-33 — Phase 3 지표 목표 확정 반영 (2026-10-13)

> **판정 기준**: main `dc214a2f` 위의 작업 브랜치(미머지) · 집행 코드 `ops/phase3_metrics.py` · 정본 `docs/standards/phase3_metrics_contract.md`
> **근거 결정**: 게이트 `G-p314-phase3-metric-targets` (2026-10-12 Kiki)

## 1. 한 줄 결론

지표 7 목표를 명세에서 `null` → **0.95** 로 확정했고, 지표 6 을 Hard Gate **F-Ⅱ·F-Ⅴ 2종**(분모 5 → 2)으로 줄였다. 실 코퍼스에서 지표 7 은 `목표미정` 이 아니라 **측정값 기준 미달(5/10 = 50.0%, 목표 ≥95.0%)** 로 나온다. 뮤테이션 12종 전건 pytest RED(생존 0).

## 2. 변경

| 파일 | 변경 |
|---|---|
| `data/corpus/phase3_scope_v1/scope_spec.yaml` | ⑦ 목표 `null` → `0.95`, 머리말 동결 근거 1항 추가(나머지 4개 목표 값 불변) |
| `ops/phase3_metrics.py` | ⑥ 을 `evaluate_hard_gates` 결과 중 F-Ⅱ·F-Ⅴ 만 판정(스코어카드 정의는 복제하지 않고 호출). 범위 밖 3종은 판정에 쓰지 않으며 출력(`scope`)에 "생산 공정 평면 소관"을 박음. 자가 점검 합성 세계의 '가설 목표 주입' 폐지(명세가 목표를 가짐). 범위 밖 무반응 주입 3종·흡수 입력 삭제(미측정) 주입 1종 추가 → 자가 점검 18 → 22건 |
| `l1/standards/phase3_coverage.py` | ⑦ 결과 note 의 낡은 문구("목표는 기준선 실측 후 제안") 교체 |
| `tests/backend/ops/test_phase3_metrics.py` | ⑥ 테스트를 새 정의로 전면 갱신(F-Ⅱ·F-Ⅴ 주입·범위 밖 무반응·범위 밖 입력 없음≠미측정·흡수 입력 없음=미측정 등), 실 코퍼스에서 ⑦ 이 판정임을 확인하는 테스트 추가 |
| `tests/backend/l1/test_phase3_scope_spec.py` · `test_phase3_coverage.py` | 목표 `null` 을 전제한 테스트 5건 갱신(태스크 `paths` 밖이지만 ①의 직접 귀결). `null` 대조군 보존 + 확정 목표가 판정을 만드는 쌍 테스트 추가 |
| `docs/standards/phase3_metrics_contract.md` | ⑥·⑦ 정의, §4·§5, §6 확정 결과·불일치 ① 해소 반영 |

## 3. 실 코퍼스 판정 (acceptance ④)

명령 `python -m whymath_backend.ops.phase3_metrics --no-db` → **exit 2**(⑤ DB 없음·⑥ payload 없음은 미측정이라 종합은 측정 실패 — 정상 동작).

- ⑦ Graph Connectivity: `5/10 = 50.0% (목표 ≥95.0%)` · 미달 · **목표미정 0건**. 끊긴 곳은 `12미적Ⅰ-02-05·06·08·09·10` 의 `problem→misconception`.
- ⑥ Critical Defect: 이름 줄에 `[Hard Gate F-Ⅱ·F-Ⅴ 2종 — F-Ⅰ·Ⅲ·Ⅳ 는 생산 공정 평면 소관(이 지표 밖)]` 표기, payload 없음 → 미측정.
- 합계: 충족 2(①·④) · 미달 3(②·③·⑦) · 미측정 2(⑤·⑥) · 목표미정 0.

## 4. 뮤테이션 검증 (acceptance ②)

주입 적용(`mutated != orig`)과 원복 바이트 동일성을 하네스가 단언했다. 대조군(무변이)은 pytest·자가 점검 모두 통과.

| # | 주입 | pytest | 자가 점검 |
|---|---|---|---|
| M1 | 흡수 게이트를 5종으로 되돌림 | RED | RED |
| M2 | 필터 제거(`absorbed = gates` 전부) | RED | RED |
| M3 | 판정 불가를 범위 밖까지 센다 | RED | GREEN |
| M4 | 해당(triggered)을 범위 밖까지 센다 | RED | RED |
| M5 | 분모를 5 로(`len(gates)`) | RED | GREEN |
| M6 | 엉뚱한 게이트 흡수(F-Ⅰ·F-Ⅱ) | RED | RED |
| M7 | F-Ⅴ 누락(F-Ⅱ 단독) | RED | GREEN |
| M8 | 출력에서 범위 밖 안내 삭제 | RED | GREEN |
| M9 | 판정 불가가 해당(확정 위반)을 덮음 | RED | GREEN |
| M10 | 흡수 계약 검사를 2종 기준으로 오설정 | RED | RED |
| M11 | 명세 ⑦ 목표를 다시 `null` | RED | RED |
| M12 | 명세 ⑦ 목표를 0.5 로 느슨하게 | RED | GREEN |

**pytest 생존 0 / 12.** 자가 점검 단독은 12종 중 6종만 RED 다 — 분모 값·출력 문구·입력 분기·명세 수치는 pytest 가 겨냥하는 영역이며, 자가 점검은 'CI 상시 게이트'로서 반응성(5종 흡수 회귀 M1·M2·M4·M6·M10 과 명세 `null` 회귀 M11)만 책임진다. 지표 6 만 반응함은 `test_violation_drops_exactly_that_metric`(F-Ⅱ·F-Ⅴ 행)·`test_out_of_plane_gate_violation_does_not_move_any_metric`(F-Ⅰ·Ⅲ·Ⅳ 가 7종 전부 무반응)로 확인한다.

## 5. CI 재현 — 잡 목록 전수 기준 (acceptance ⑤)

워크플로 잡 20개를 전수 열거했다(`changes` · `data-pipeline` · `backend` · `backend-migrations` · `data-pipeline-integration` · `data-pipeline-neo4j` · `mobile` · `concept-reach-guard` · `web` · `webapp` · `infra-contracts` · `docker-build` · `infra-shell` · `policy-guard` · `harness-integrity` · `declared-unwired-audit` · `corpus-authoring` · `e2e-nightly` · `backend-serial-nightly` · `constraints-freshness`). 환경: Python 3.12 가상환경 · `PIP_CONSTRAINT=infra/ci/constraints-py312.txt`(CI 와 같은 제약 파일).

| 잡 | 판정 | 결과 |
|---|---|---|
| `backend` | 닿음(백엔드 src·tests) | ruff·black·`mypy --strict`·`lint-imports` 종료 코드 0 · pytest `19395 passed, 646 skipped, 1 xfailed`(커버리지 게이트 70 포함) · 이후 20스텝(계층 커버리지·게이트 CLI·`phase3_metrics --self-check`·`tests/constitution` 39건) 전건 0 |
| `infra-contracts` | 닿음(`phase3_metrics_wiring`·기능 인벤토리가 phase3 모듈을 참조) | 게이트 4종·ruff·black 0 · `tests/infra` `3053 passed, 1 skipped` · idempotency 11건 |
| `declared-unwired-audit` | 닿음(백엔드 모듈·코퍼스) | 3스텝 0(백필 2스텝은 CI 정의대로 워크스페이스 루트에서 실행) |
| `harness-integrity` | 닿음(backlog 태스크 · 헌법 래칫) | validate·audit-deps·rules lint/render·jit·헌법 4종·관측 리포트 3종·ruff·black 0 · `tests/harness` `2307 passed, 3 skipped` · **헌법 래칫 exit 0 · 차단 0건(기준선 0건 이하)** |
| `policy-guard` | 닿음(docs·yaml 추가) | 본문 패턴 2·시크릿·바이너리·인코딩·충돌 마커 전건 0 |
| `data-pipeline` | 닿음(`data/corpus/` 변경이 `corpus` 플래그를 켠다) | ruff·black·mypy 0 · pytest `995 passed, 12 skipped`(커버리지 70 포함) · `qa_pipeline` 0 |
| `corpus-authoring` | **안 닿음** — 마커 테스트는 `p3_diff_*` 문제 생성기이고 명세·지표 모듈을 읽지 않는다(`phase3_scope`·`scope_spec`·`phase3_metrics` 참조 0건: 내가 찾은 방법 기준) | 미실행 |
| `concept-reach-guard` | 안 닿음 — 모바일 영역 조건 잡, 대상은 `test_concept_reach_report.py` 단일 파일 | 미실행 |
| `backend-migrations` · `docker-build` | **닿음(정정)** — 초안은 '안 닿음'으로 분류했으나 CI 경로 필터가 이 변경으로 두 잡을 깨운다(PR 생성 시 훅의 `CI 도달 잡` 고지). 서비스 컨테이너(postgres)·docker 빌드가 필요해 로컬 재현 불가 | 미실행 — **CI 판정에 맡김** |
| `changes` | 경로 필터 계산 잡 — 미러가 같은 정본(filter 스텝)을 읽어 대신함 | 미러가 대신 |
| `infra-shell` | 상시 잡 | 로컬 CI 미러가 실행해 통과 |
| `data-pipeline-integration` · `data-pipeline-neo4j` · `mobile` · `web` · `webapp` · `constraints-freshness` · `e2e-nightly` · `backend-serial-nightly` | 안 닿음 — 영역 필터·스케줄 센서·야간 전용 잡이며 이 변경은 해당 영역을 건드리지 않는다(*내가 찾은 방법 기준*) | 미실행 |

### 돌리지 못한 것
- `harness-integrity` 중 **네트워크가 필요한 3스텝**(ADR 번호 충돌 검사 · 원격 claim 교차 검증 · 고립 브랜치 관측)은 이 세션에서 돌리지 않았다. 앞의 둘은 PR 시점의 원격 상태를 보는 스텝이다.
- 전부 PR 실행의 CI 가 최종 판정한다. 이 문서의 수치는 로컬 재현이다.

## 6. 재현 중 일어난 일 (기록)

- `mypy --strict` 가 `json.loads` 반환 `Any`(`no-any-return`) 1건을 잡았다 — 이 오류가 CI 의 7번째 스텝이면 뒤 스텝이 통째로 skipped 된다. 로컬에서 먼저 잡혀 수정(반환 타입 명시).
- 재현 스크립트 결함 2건은 모두 내 쪽이었다: ① `declared-unwired-audit` 의 백필 2스텝은 CI 가 작업 디렉터리를 워크스페이스 루트로 재정의하는데 잡 기본값(`src/backend`)으로 돌려 `FileNotFoundError` — 정의대로 재실행해 통과 ② 스텝 추출 루프가 마지막 줄(개행 없음)을 건너뛰어 19/20만 실행 — 빠진 `tests/constitution` 을 따로 실행. ③ `data-pipeline` pytest 는 `[dev]` extras 미설치(`respx`)로 수집 오류 — CI 와 같이 설치해 재실행.
- 재조정 가능 단서: AI 품질 평가 기준선(`P3-10`) 없이 확정한 목표라 ④·⑤·⑥ 은 그 결과를 본 뒤 재조정될 수 있다(별도 결정).
