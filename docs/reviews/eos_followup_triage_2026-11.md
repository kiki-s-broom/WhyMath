# EOS 후속 태스크·pending 결정 게이트 분류표 — 12/31 판정 기준 (D13 결정 대기)

> **D13 결정 기록**: **대기 중** — Kiki 결정문(`10_…/D13_1104`)을 받으면 이 칸에 원문 그대로 옮기고, §5의 명령으로 대장에 반영한다. 결정 전에는 `eos_priority`도 게이트도 바꾸지 않는다.
>
> **판정 기준**: main `3a83ed64` (2026-10-30). 아래 표의 "기준" 열은 모두 이 커밋이다. 대장 수치(미완료 14건 · pending decision 게이트 22건)는 이 커밋의 `backlog/tasks/EOS-2*.yaml`·`backlog/gates.yaml`을 읽어 센 값이다.
>
> **이 문서는 분류 제안이다.** 감리 WP-J(레인 01-D)의 산출물이며, 판정이 아니다. 분류 결정은 Kiki 몫(D13 · 기한 11/4)이다.

## 0. Kiki께 드리는 결정 요청 (D13)

1. **EOS-200~218 미완료 14건** — 12/31 필수 5건 · 2027 이월 9건으로 나누는 안을 승인할지(§2). 이월 9건 중 지금 `eos_priority` P1인 3건(EOS-200·201·214)은 P2로 내린다.
2. **pending decision 게이트 22건** — 네 묶음으로 나누는 안을 승인할지(§3). "2027 보류" 14건은 notes에 표지만 붙이고 status는 pending으로 둔다(`gates waive`는 쓰지 않는다 — §3 끝).
3. **(선택) `P3-52`를 `P3-17` 선행으로 붙일지** — Phase 3 지표 ⑦ Graph Connectivity 목표가 0.95인데 02-09가 닫히지 않으면 9/10(0.90)에 머문다(§4-2).

## 1. 무엇을 기준으로 나눴는가

12/31 판정은 `G-internal-completion-2026-12-31`이 정의한다. 조건 3개다.

| 조건 | 게이트·근거 | 판정 시점 |
|---|---|---|
| ① Phase 3 Release Gate A~E PASS | `G-p3-w3-release-merged` (여는 작업 `P3-17`) | 11/15 |
| ② EOS G5 판정 완료 | `G-eos-g5` (입력 `ARCH-67`) — 앞 단계 `G-eos-g2`(11/8) · `G-eos-g3`(11/22) · `G-eos-g4`(12/13) | 12/27 동결 → 12/31 |
| ③ EOS 생산 물증 커밋 | `data/runs/*/cu.jsonl` + `metrics/weekly.json`(측정된 KPI 포함)이 main에 있음 (D4 2026-10-23) | 12/31 |

"12/31 필수"는 **위 조건 중 하나를 판정할 수 없게 만들거나, 판정에 쓰는 측정값을 오염시키는 것**으로 한정했다. "판정하면 FAIL이 나올 수 있다"는 필수 사유가 아니다(FAIL도 판정이다). 학생 노출이 12/31 이후로 연기된 기능(ARCH-66 ⑥ · `G-student-work-after-internal-completion`)의 결함은, 연기가 풀리기 전에 막는 장치가 있으면 이월로 본다.

## 2. EOS-200~218 미완료 14건

범위 안 done 6건(EOS-202·207·208·210·211·219)은 분류 대상이 아니다.

### 2-1. 12/31 필수 제안 — 5건 (저작 경로 결함 · WP-L)

공통 근거: G4(12/13)는 **두 번째 앵커 A4 30 CU 저작 회차**(WP-F)와 **자동검증 1차 통과율 ≥70%**를 요구한다. A6 회차(EOS-197)에서 드러난 저작 경로 결함을 고치지 않고 A4 회차를 돌리면 같은 결함이 G4 측정값에 그대로 들어간다. EOS-207 첫 측정은 1차 통과율 **0.1171(13/111)**이고 그 차이의 상당 부분이 아래 결함에서 나왔다(`docs/reviews/eos207_g3_measures_2026-10-29.md` §1).

| 태스크 | 지금 등급 | 제안 | 근거 1줄 | 기준 |
|---|---|---|---|---|
| EOS-203 로컬 좌석 수락률(사고 모드 끄기·Ollama 타임아웃) | P1 | **12/31 필수** · P1 유지 | 로컬 좌석 시도 45건 중 수락 3건(ReadTimeout 25) — A4 회차 좌석 비교·1차 통과율 분모를 오염시킨다(EOS-197 ⑦(a)) | `3a83ed64` |
| EOS-204 구조적 중복 사전 차단 | P1 | **12/31 필수** · P1 유지 | A6 회차에서 완전 중복 2쌍이 F8로 기록돼 실패 분포가 왜곡됐다 — G5 F-Ⅲ(실패 분포)·HIT 표본의 입력이다(EOS-197 ⑦(c)) | `3a83ed64` |
| EOS-205 동어반복 검산식 거부·정답 키·단원 코드 고정 | P1 | **12/31 필수** · P1 유지 | 게이트 통과 35건 중 22건이 정답 재진술 검산식(우회)이라 1차 통과율 0.3153→0.1171로 갈린다 — G4 ≥70% 판정의 분자 자체 · F-Ⅱ(수학 오류율) 위험 | `3a83ed64` |
| EOS-209 오케스트레이터 보완·첫 Windows 실회차 체크리스트 | P1 | **12/31 필수** · P1 유지 | WP-F 회차는 Kiki PC에서 이 오케스트레이터로 돈다 — ②(첫 실회차 확인)는 그 회차와 함께 수행하므로 저작 회차의 선행이 아니라 동반 작업이다 | `3a83ed64` |
| EOS-212 GenerationLog `error_detail`에서 공급사 응답 본문 제거 | P1 | **12/31 필수** · P1 유지 | 조건 ③은 회차 산출물을 main에 커밋하라는 것이고 `cu.genlog.jsonl`도 커밋된다(`data/runs/eos197-a6-*`). A6 회차의 공급사 실패 25행은 전부 ReadTimeout이라 본문이 없었지만, A4 회차에서 HTTP 오류(`SeatHttpError`)가 나면 공급사 응답 본문 최대 2000자가 저장소에 들어간다 | `3a83ed64` |

`eos_priority`는 바꾸지 않는다. P0("없으면 12월 검증이 성립하지 않는다")로 올리지 않은 이유: 다섯 건 모두 없어도 G4·G5 판정 자체는 가능하다(측정값이 나빠지거나 오염될 뿐). 대신 WP-F 2회차 저작 태스크의 `depends_on`으로 집행한다(EOS-209 제외 — 동반 작업). 그 등재는 D13과 별개로 `docs/reviews/eos_wp_owner_tasks_2026-11.md`가 다룬다.

### 2-2. 2027 이월 제안 — 9건

| 태스크 | 지금 등급 | 제안 | 근거 1줄 (이월이 안전한 조건) | 기준 |
|---|---|---|---|---|
| EOS-200 터미널 검수 크래시(사유 없는 메모·2000자) | **P1** | **2027 이월 · P1→P2** | 검수 창(GUI)은 같은 입력을 쓰기 전에 거부한다(notes) — 조건: WP-F 사람 단독 HIT 표본은 검수 창으로만 받는다(터미널 [J] 미사용) | `3a83ed64` |
| EOS-201 검수 창 보완(다시 보기 이력 한정 등) | **P1** | **2027 이월 · P1→P2** | ①의 선입견 오염은 다른 검수자·옛 지문 판정이 있을 때만 생긴다 — 조건: WP-F 표본은 새 CU · 단일 검수자(Kiki)라 해당 판정이 없다. ④(정지 세션 판정 누락)는 기록 도중 실패로 정지할 때만 생긴다 — 조건: 정지가 나면 판정 행 수를 큐 길이와 대조한다 | `3a83ed64` |
| EOS-214 CU 사후 힌트 단계 SymPy 검산 | **P1** | **2027 이월 · P1→P2** | 위험은 틀린 시연 식이 학생에게 나가는 것인데 CU 힌트는 파일 내보내기까지만 있고 서빙 좌석이 없다 — 조건: EOS-215 ③("EOS-214 검산 착지 전 노출 금지")이 유지된다 | `3a83ed64` |
| EOS-206 주간 KPI 단위비용 정의 | P2 | 2027 이월 · 유지 | 실지출 기준으로 바꿔도 17.6원/CU로 기술 KPI 상한(250원/CU)과 거리가 멀어 판정이 바뀌지 않는다 — 판정문에 "현 정의는 실패 시도 비용 제외(약 3.4배 과소)"를 한계로 적는 조건 | `3a83ed64` |
| EOS-213 L3 never-break 경고의 예외 원문 로그 제거 | P2 | 2027 이월 · 유지 | 로그는 저장소에 커밋되지 않는다(EOS-212와 다른 점) · 학생 대면 서빙은 12/31 이후 | `3a83ed64` |
| EOS-215 CU 힌트 DB 좌석 | P2 | 2027 이월 · 유지 | 조건 ①~③ 어디에도 DB 적재가 없다 · 서빙 노출은 학생 연기와 함께 미룬다 | `3a83ed64` |
| EOS-216 저작 경로 실패 호출 Langfuse 추적 | P2 | 2027 이월 · 유지 | 실패 호출은 인프로세스 genlog(이중 회계)에 남는다 — 판정 측정치는 genlog에서 산출한다(EOS-207) | `3a83ed64` |
| EOS-217 CU 힌트 패스 견고성 | P2 | 2027 이월 · 유지 | 4건 모두 드문 경로이고 측정을 거짓 PASS로 만들지 않는다(notes) · ①은 `--redo-incomplete`, ②는 보존본 수동 삭제로 우회 | `3a83ed64` |
| EOS-218 힌트 누설 사람 판정 좌석 보강 | P2 | 2027 이월 · 유지 | 판정자 간 일치도·중재는 판정자 2인 이상일 때 의미가 있다 — 조건: G3·G5 F-Ⅴ 판정문에 "판정자 1인 · 보정 문항(R19-02) 없음 — 판정자 오류율 미측정"을 한계로 적는다 | `3a83ed64` |

## 3. pending decision 게이트 22건

| 묶음 | 건수 | 게이트 |
|---|---|---|
| A. 11/15 판정에 필요 | 2 | `G-p3-w3-release-merged` · `G-p345-m0677-link-disposition` |
| B. G3·G4·G5 입력 | 1 | `G-required-tier-caller-recheck-g5` |
| C. 12/31 판정 게이트와 G2~G5 게이트 자체 | 5 | `G-internal-completion-2026-12-31` · `G-eos-g2` · `G-eos-g3` · `G-eos-g4` · `G-eos-g5` |
| D. 2027 보류 | 14 | 아래 표 |

### A. 11/15 판정에 필요 — 2건

| 게이트 | 근거 1줄 | 기준 |
|---|---|---|
| `G-p3-w3-release-merged` | 11/15 통합 판정 게이트 자체이며 12/31 조건 ①이다. 남은 Kiki 몫: Solution QA 검증 가능 비율 하한값(D9 (다) — P3-62 실측 후 확정 · 현재 0.48885, 후보 60%) | `3a83ed64` |
| `G-p345-m0677-link-disposition` | 처분이 나야 `P3-52`가 착수되고, 그래야 Phase 3 지표 ⑦ Graph Connectivity가 9/10→10/10이 된다 — 목표 0.95(`ops/phase3_metrics.py` 모듈 설명 ⑦ · P3-33)는 9/10(0.90)로 미달 | `3a83ed64` |

### B. G3·G4·G5 입력 — 1건

| 게이트 | 근거 1줄 | 기준 |
|---|---|---|
| `G-required-tier-caller-recheck-g5` | 재확인 지점이 G5 데이터 동결(12/27)이고, `G-eos-g5`의 입력 `ARCH-67`이 이 게이트를 `requires_gates`로 기다린다 | `3a83ed64` |

### C. 12/31 판정 게이트와 G2~G5 자체 — 5건

| 게이트 | 판정 시점 | 근거 1줄 | 기준 |
|---|---|---|---|
| `G-eos-g2` | 11/8 재판정 | ADR-007 개정 조건(A6 ≥30 CU 산출물 커밋 + OPS-90 착지) — 입력 EOS-197·OPS-90 둘 다 done | `3a83ed64` |
| `G-eos-g3` | 11/22 | Kiki 결정(10/28)으로 11/22까지 보류 · 미측정이던 3항목 측정 경로는 EOS-207(done)이 만들었다 | `3a83ed64` |
| `G-eos-g4` | 12/13 | A4 30 CU · 1차 통과율 ≥70% · 무개입 루프 3연속 · 테스트 계정 ≥20 · P0 0 — WP-F 산출물이 입력 | `3a83ed64` |
| `G-eos-g5` | 12/27→12/31 | 원문 불변 · 증거 문서 = `docs/reviews/eos_g5_evidence_2026-12-27.md`(WP-G — 아직 없음) | `3a83ed64` |
| `G-internal-completion-2026-12-31` | 12/31 | 12/31 판정 게이트 자체 · 입력 P3-17 · 판정문(WP-H)이 필요하다 | `3a83ed64` |

### D. 2027 보류 — 14건 (표지만 · status pending 유지)

| 게이트 | 근거 1줄 | 기준 |
|---|---|---|
| `G-arch38-verdict-recheck` | 12/31 조건과 무관한 데이터 모델 재확인. 재확인 지점(10/26)은 이미 지났다 — 보류 대신 기본값 ①(판정 유지)로 지금 닫아도 되며, 판정 근거 ①은 테스트가 자동 감시한다 | `3a83ed64` |
| `G-arch56-availability-trigger` | 트리거형(OpenRouter 가용성 측정). 주의: 발동 조건 ⓐ("학생 대면 트래픽을 받기로 결정")가 ARCH-64(2026-09-29 · 학생 대면 서빙 기본 좌석 = openrouter)로 이미 성립했을 수 있다 — 학생 트래픽 자체는 12/31 이후라 보류 제안은 유지. WP-F 회차에서 429 실패율이 한 회차 50% 이상이면(ⓒ) 묶음 B로 옮긴다 | `3a83ed64` |
| `G-arch66-anthropic-api-pause-review` | 방침 만료 지점 = 12/31 내부 완성. `G-internal-completion` 문면이 완성 판정 *뒤에* 차례로 판정하는 재개 게이트로 지목 | `3a83ed64` |
| `G-const-a0005-part1-corrections` | 헌법 파트 I 집행 장치 정합 정정 채택 판정 — 12/31 조건과 무관. 단 §4-1의 12/31 만료와 이웃한다 | `3a83ed64` |
| `G-const-r4-02-decision` | A0005 채택 뒤 닫는 게이트(문면) — 위와 같은 묶음 | `3a83ed64` |
| `G-eos02-default-flip-recheck` | Kiki 판정 ②(10/03): 재판정 시점 = `G-arch66` 이후 | `3a83ed64` |
| `G-external-counsel-restart-after-internal-completion` | 내부 완성 이후 재개 게이트(문면) | `3a83ed64` |
| `G-not-now-v1-release-recheck` | 내부 완성 이후 첫 계획 세션(문면) | `3a83ed64` |
| `G-opus5-billing-path-prod-recheck` | 프로덕션 배포 판정 시 또는 학생 대면 트래픽이 개발 좌석을 넘을 때(문면) — 12/31 전 발동 없음 | `3a83ed64` |
| `G-p356-signature-activation` | verdict FAIL 기록됨(10/27 · 운영 그림자 레코드 0건). 활성화 기준 오답 시도 n≥300은 운영 트래픽이 필요하다 | `3a83ed64` |
| `G-p359-m0672-shadow-disposition` | 판정 입력 완성(verdict PASS 10/18) · 세션 권고 ③ 현상 유지 · "오늘의 해 0", P3-06 종료 코드에도 영향 없음(판정문 §1) — 보류 대신 ③으로 지금 닫아도 된다 | `3a83ed64` |
| `G-s302-free-use-remeasure-restart` | 연기 만료 지점 = 12/31 이후(문면) | `3a83ed64` |
| `G-s5-subject-expansion` | 수학 K-12 완성 전 타과목 착수 금지(불변 전제) | `3a83ed64` |
| `G-student-work-after-internal-completion` | 내부 완성 이후 재개 게이트(문면) · Gate A 원문 학생 조건의 이관처 | `3a83ed64` |

**왜 `gates waive`를 쓰지 않는가**: waive는 status를 바꿔 그 게이트를 기다리던 태스크(학생 작업·변호사·API 재개 등)를 **해금**하고 notes를 덮어쓴다. "요건은 살아 있고 시점만 미뤘다"는 `gates amend --note`(status 불변 · notes append)로만 표현된다(`scripts/harness/backlog.py`의 `_cmd_gates_amend` 설명).

## 4. 범위 밖 발견 (고치지 않음 · 보고만)

### 4-1. 12/31 만료가 한 날에 몰려 있다

내가 찾은 방법(`grep -rnE 'until=date\(2026, ?12, ?31|EXPIRES = date\(2026, 12, 31'`)으로 만료일 2026-12-31인 유예가 **11곳**이다: `tests/constitution/test_schema_model_sync.py:33`(1) · `scripts/ops/check_provider_seat_contract.py:113-123`(4) · `scripts/ops/check_runbook_blocks.py:218-226`(6). 이 중 `test_schema_model_sync.py`는 직접 읽어 확인했다 — `date.today() <= EXPIRES`를 단언하므로 **2027-01-01부터 RED**다(소유 태스크 `CONST-14`는 done, 재확인 소유자 없음). 나머지 10곳의 만료 시 동작은 확인하지 않았다. 12/31 판정 직후 main CI가 여러 곳에서 동시에 빨개질 수 있으므로, 만료 처분(해소 또는 의식적 연장)을 12/27 동결 전에 할지 Kiki 판단이 필요하다.

### 4-2. `P3-52`가 `P3-17` 선행에 없다

Phase 3 지표 ⑦ Graph Connectivity 목표는 0.95다(P3-33). P3-44 설계 문서는 "승인 각인 후 5/10 → 9/10(90%), 목표 95% 미달 · 02-09(승계 P3-52)가 닫혀야 10/10"이라고 적는다(`docs/reviews/p3_44_new_frames_design_2026-10-16.md:199`). `P3-52`는 `G-p345-m0677-link-disposition`을 기다리고, `P3-17`은 `P3-52`를 기다리지 않는다. Release Gate B(콘텐츠)를 ⑦로 판정한다면 선행으로 붙여야 하고, 그렇지 않다면 판정문이 ⑦ 미달을 어떻게 다룰지 적어야 한다 — D13 3번 질문.

### 4-3. `P3-90`(P1)의 게이트 조건은 운영 트래픽을 요구한다

`G-p356-signature-activation`의 소유 태스크 `P3-90`은 P1이지만, 기준 C1(오답 시도 n≥300)은 학생 트래픽 없이 채우기 어렵다. 이 레인의 분류 대상(EOS-200~218) 밖이라 등급 제안은 하지 않는다.

## 5. D13 결정 후 반영 명령 (결정 전 실행 금지)

결정문이 이 분류와 다르면 결정문을 따른다. 아래는 **이 제안이 그대로 승인될 때**의 명령이다.

```bash
# 2-2: P1 → P2 (3건)
for t in EOS-200 EOS-201 EOS-214; do
  python3 scripts/harness/backlog.py amend "$t" --eos-priority P2 --reason "D13: 12/31 판정 비필수 — 2027 이월(docs/reviews/eos_followup_triage_2026-11.md §2-2)"
done
```

```bash
# 3-D: 2027 보류 표지 (status pending 유지 · waive 금지)
for g in G-arch38-verdict-recheck G-arch56-availability-trigger G-arch66-anthropic-api-pause-review G-const-a0005-part1-corrections G-const-r4-02-decision G-eos02-default-flip-recheck G-external-counsel-restart-after-internal-completion G-not-now-v1-release-recheck G-opus5-billing-path-prod-recheck G-p356-signature-activation G-p359-m0672-shadow-disposition G-s302-free-use-remeasure-restart G-s5-subject-expansion G-student-work-after-internal-completion; do
  python3 scripts/harness/backlog.py gates amend "$g" --note "[D13 2027 보류] 12/31 판정에 쓰지 않는다 · status pending 유지 · 재확인 = 2027-01 첫 계획 세션 (docs/reviews/eos_followup_triage_2026-11.md §3-D)" --reason "D13 분류 반영"
done
```

반영 뒤 검사: `python3 scripts/harness/backlog.py validate` · `audit-deps` exit 0, 그리고 표지 14건이 notes에 실재하는지 YAML을 읽어 대조한다.
