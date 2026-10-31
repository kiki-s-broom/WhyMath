# EOS 후속 태스크·pending 결정 게이트 분류표 — 12/31 판정 기준 (D13 결정 대기)

> **D13 결정 기록**: **대기 중** — Kiki 결정문(`10_…/D13_1104`)을 받으면 이 칸에 원문 그대로 옮기고, §5의 명령으로 대장에 반영한다. 결정 전에는 `eos_priority`도 게이트도 바꾸지 않는다.
>
> **판정 기준**: main `3a83ed64` (2026-10-30). 아래 표의 "기준" 열은 모두 이 커밋이다. 대장 수치(미완료 14건 · pending decision 게이트 22건)는 이 커밋의 `backlog/tasks/EOS-2*.yaml`·`backlog/gates.yaml`을 읽어 센 값이다. **미머지 근거는 "미머지"라고 따로 표시했다** — 같은 레인의 PR #1780(P3-17 선행 5건)·#1781(WP 소유 태스크 10건)은 이 문서 작성 시점에 main에 없다.
>
> **이 문서는 분류 제안이다.** 감리 WP-J(레인 01-D)의 산출물이며, 판정이 아니다. 분류 결정은 Kiki 몫(D13 · 기한 11/4)이다. 초안은 독립 검토(읽기 전용 · 결함만)를 한 번 거쳤고 지적 12건을 반영했다.

## 0. Kiki께 드리는 결정 요청 (D13)

1. **EOS-200~218 미완료 14건** — 12/31 필수 5건 · 2027 이월 9건으로 나누는 안을 승인할지(§2). 이월 9건 중 지금 P1인 3건(EOS-200·201·214)은 P2로 내린다. **EOS-201은 이월 조건이 하나 붙는다**(다시 보기 중 HIT 시계가 흐름 — §2-2) — 조건이 지켜지기 어렵다고 보시면 필수로 옮긴다.
2. **pending decision 게이트 22건** — 네 묶음으로 나누는 안을 승인할지(§3). "2027 보류" 14건은 notes에 표지만 붙이고 status는 pending으로 둔다(`gates waive`는 쓰지 않는다 — §3 끝). 그중 6건은 2027 전에 독촉이 뜬다 — 독촉 주기도 함께 미룰지(§3-D 끝).
3. **Graph Connectivity(Phase 3 지표 ⑦)를 11/15 판정에서 어떻게 다룰지** — 현재 **4/10**(목표 0.95)이고, 10/10이 되려면 `P3-44`(진행 중)·`P3-52`(게이트 `G-p345` 대기)·`P3-50`(P2 todo)이 모두 필요하다. 셋을 `P3-17` 선행으로 붙일지, 판정문이 ⑦ 미달을 FAIL 사유로 적을지(§4-2).
4. **12/31 만료 12곳의 처분 시점** — 처분 없이 해를 넘기면 2027-01-01부터 main CI가 여러 곳에서 RED다. 12/27 동결 전에 처분할지, 소유 태스크를 등재할지(§4-1).
5. **`G-eos-g2`는 10/28에 PASS로 판정 기록됐는데 status가 pending이다** — clear(`gates clear --as kiki`)만 남았다(§3-C).

## 1. 무엇을 기준으로 나눴는가

12/31 판정은 `G-internal-completion-2026-12-31`이 정의한다. 조건 3개다.

| 조건 | 게이트·근거 | 판정 시점 |
|---|---|---|
| ① Phase 3 Release Gate A~E PASS | `G-p3-w3-release-merged` (여는 작업 `P3-17`) | 11/15 |
| ② EOS G5 판정 완료 | `G-eos-g5` (입력 `ARCH-67`) — 앞 단계 `G-eos-g2`(PASS 기록 10/28) · `G-eos-g3`(11/22) · `G-eos-g4`(12/13) | 12/27 동결 → 12/31 |
| ③ EOS 생산 물증 커밋 | `data/runs/*/cu.jsonl` + `metrics/weekly.json`(측정된 KPI 포함)이 main에 있음 (D4 2026-10-23) — WP-C(A6) 몫은 이미 main에 있고(`data/runs/eos197-a6-*` · `weekly.json` measured true), WP-F(A4) 몫이 남았다 | 12/31 |

"12/31 필수"는 다음 넷 중 하나에 해당하는 것으로 한정했다.

- **(가) 판정 불능** — 조건 하나를 판정할 수 없게 만든다
- **(나) 측정값 오염** — 판정에 쓰는 값을 틀리게 만든다
- **(다) 산출 실패 위험** — 판정은 가능하지만 판정 재료(A4 30 CU 등)를 만드는 과정 자체가 막힌다
- **(라) 커밋물 위생** — 조건 ③이 main에 커밋하라는 산출물에 들어가면 안 되는 것이 들어간다

"판정하면 FAIL이 나올 수 있다"는 그 자체로는 필수 사유가 아니다(FAIL도 판정이다). 학생 노출이 12/31 이후로 연기된 기능(ARCH-66 ⑥ · `G-student-work-after-internal-completion`)의 결함은, 연기가 풀리기 전에 막는 장치가 있으면 이월로 본다.

## 2. EOS-200~218 미완료 14건

범위 안 done 5건(EOS-202·207·208·210·211)은 분류 대상이 아니다.

### 2-1. 12/31 필수 제안 — 5건 (저작 경로 결함 · WP-L)

공통 배경: G4(12/13)는 **두 번째 앵커 A4 30 CU 저작 회차**(WP-F)와 **자동검증 1차 통과율 ≥70%**를 요구한다. A6 회차(EOS-197)에서 드러난 저작 경로 결함을 고치지 않고 A4 회차를 돌리면 같은 결함이 G4 재료에 그대로 들어간다. EOS-207 첫 측정은 1차 통과율 **0.1171(13/111)**이다(`docs/reviews/eos207_g3_measures_2026-10-29.md` §1). 불통과 98건 중 가장 큰 덩어리인 `needs_review` 44건은 아래 5건 어디에도 귀속되지 않는다 — 5건을 고쳐도 ≥70%가 보장되지는 않는다.

| 태스크 | 지금 등급 | 제안 | 기준 | 근거 1줄 | 판정 기준 |
|---|---|---|---|---|---|
| EOS-203 로컬 좌석 수락률(사고 모드 끄기·Ollama 타임아웃) | P1 | **12/31 필수** · P1 유지 | (다) | 로컬 좌석 시도 45건 중 수락 3건(ReadTimeout 25 — EOS-197 ⑦(a)). ReadTimeout은 1차 통과율 분모 밖이라 값 오염은 아니지만, 이대로면 A4 30 CU를 사실상 클라우드 좌석 하나로 만들어야 한다 | `3a83ed64` |
| EOS-204 구조적 중복 사전 차단 | P1 | **12/31 필수** · P1 유지 | (나) | A6 회차에서 완전 중복 2쌍이 F8로 기록돼 실패 분포가 왜곡됐다 — G5 F-Ⅲ(실패 분포)와 HIT 표본의 입력이다(EOS-197 ⑦(c)) | `3a83ed64` |
| EOS-205 동어반복 검산식 거부·정답 키·단원 코드 고정 | P1 | **12/31 필수** · P1 유지 | (나) | 게이트 통과 35건 중 22건이 정답 재진술 검산식(우회)이라 원시 통과율 0.3153과 실통과율 0.1171이 갈린다 — G4 ≥70% 판정의 분자 자체이고 F-Ⅱ(수학 오류율) 위험이다 | `3a83ed64` |
| EOS-209 오케스트레이터 보완·첫 Windows 실회차 체크리스트 | P1 | **12/31 필수** · P1 유지 | (다) | WP-F 회차는 Kiki PC에서 이 오케스트레이터로 돈다. ①(b)의 낡은 잠금(창을 X로 닫으면 잠금이 남음)·(c) 예약 풀기 거짓 성공은 그 회차를 멈추거나 상태를 틀리게 남긴다. ②는 그 회차와 함께 수행하는 동반 작업이다 | `3a83ed64` |
| EOS-212 GenerationLog `error_detail`에서 공급사 응답 본문 제거 | P1 | **12/31 필수** · P1 유지 | (라) | `cu.genlog.jsonl`도 main에 커밋된다(`data/runs/eos197-a6-*`). A6 회차의 공급사 실패 25행은 전부 로컬(Ollama) 좌석의 ReadTimeout이라 본문이 없었고 openrouter 좌석 실패는 0건이었지만, A4 회차에서 HTTP 오류(`SeatHttpError`)가 나면 공급사 응답 본문 최대 2000자가 저장소에 들어간다 | `3a83ed64` |

`eos_priority`는 바꾸지 않는다. P0("없으면 12월 검증이 성립하지 않는다")로 올리지 않은 이유: 다섯 건 모두 없어도 G4·G5 판정 자체는 가능하다. 대신 WP-F 2회차 저작 태스크 `EOS-225`의 `depends_on`으로 집행하는 안을 PR #1781(**미머지**)이 담고 있다(EOS-209 제외 — 동반 작업).

### 2-2. 2027 이월 제안 — 9건

| 태스크 | 지금 등급 | 제안 | 근거 1줄 (이월이 안전한 조건) | 판정 기준 |
|---|---|---|---|---|
| EOS-200 터미널 검수 크래시(사유 없는 메모·2000자) | **P1** | **2027 이월 · P1→P2** | 검수 창(GUI)은 같은 입력을 쓰기 전에 거부한다(notes) — 조건: WP-F 사람 단독 HIT 표본은 검수 창으로만 받는다(터미널 [J] 미사용) | `3a83ed64` |
| EOS-201 검수 창 보완(다시 보기 이력 한정 등) | **P1** | **2027 이월 · P1→P2 (조건부)** | ②: 다시 보기(◀▶) 중에도 현재 문항의 HIT 시계가 계속 흐른다(`review_session_gui.py` `review_back` 설명 "현재 문항의 시계는 계속 흐른다"). 위 EOS-200 조건이 검수 창 사용을 강제하므로, 이월하려면 **WP-F 사람 단독 HIT 회차에서 ◀▶를 쓰지 않거나 쓴 문항을 HIT 집계에서 제외**하는 조건이 필요하다 — 그 HIT는 F-Ⅰ의 A4 쪽 유일한 입력이다. ①(다른 검수자·옛 지문 판정 표시)은 새 CU·단일 검수자라 해당 없음. ④(정지 세션 판정 누락)는 정지가 나면 판정 행 수를 큐 길이와 대조하는 조건 | `3a83ed64` |
| EOS-214 CU 사후 힌트 단계 SymPy 검산 | **P1** | **2027 이월 · P1→P2** | 틀린 시연 식이 학생에게 나가는 위험은 서빙 좌석이 없어 아직 없다 — 조건 ① EOS-215 ③("EOS-214 검산 착지 전 노출 금지")이 유지된다 ② CU 정의(선언 부록 C)에 3단계 힌트가 들어 있으므로, G5 증거 문서에 "힌트 단계 식은 SymPy 미검산"을 한계로 적는다(F-Ⅱ 표본에 힌트가 포함되는지는 확인하지 않았다) | `3a83ed64` |
| EOS-206 주간 KPI 단위비용 정의 | P2 | 2027 이월 · 유지 | 실지출 기준(실패 시도 포함)으로 바꿔도 17.6원/CU로 기술 KPI 목표(≤250원/CU · 상한 400)와 거리가 멀어 판정이 바뀌지 않는다 — 조건: 판정문에 "현 정의는 실패 시도 비용 제외(약 3.4배 과소)"를 한계로 적는다 | `3a83ed64` |
| EOS-213 L3 never-break 경고의 예외 원문 로그 제거 | P2 | 2027 이월 · 유지 | 로그는 저장소에 커밋되지 않는다(EOS-212와 다른 점) · 학생 대면 서빙은 12/31 이후 | `3a83ed64` |
| EOS-215 CU 힌트 DB 좌석 | P2 | 2027 이월 · 유지 | 조건 ①~③ 어디에도 DB 적재가 없다 · 서빙 노출은 학생 연기와 함께 미룬다 | `3a83ed64` |
| EOS-216 저작 경로 실패 호출 Langfuse 추적 | P2 | 2027 이월 · 유지 | 실패 호출은 인프로세스 genlog(이중 회계)에 남는다 — 판정 측정치는 genlog에서 산출한다(EOS-207) | `3a83ed64` |
| EOS-217 CU 힌트 패스 견고성 | P2 | 2027 이월 · 유지 | ①~④는 드문 경로이고 측정을 거짓 PASS로 만들지 않는다(notes). ⑤(런북 쓰기 블록이 무관한 main 머지로 거부)는 10/29 라이브 실행에서 실측됐다 — 비용은 [A-2] 재생성 왕복 1회이고 판정값에는 닿지 않는다 | `3a83ed64` |
| EOS-218 힌트 누설 사람 판정 좌석 보강 | P2 | 2027 이월 · 유지 | 판정자 간 일치도·중재는 판정자 2인 이상일 때 의미가 있다 — 조건: G3·G5 F-Ⅴ 판정문에 "판정자 1인 · 보정 문항(R19-02) 없음 — 판정자 오류율 미측정"을 한계로 적는다 | `3a83ed64` |

## 3. pending decision 게이트 22건

| 묶음 | 건수 | 게이트 |
|---|---|---|
| A. 11/15 판정에 필요 | 2 | `G-p3-w3-release-merged` · `G-p345-m0677-link-disposition` |
| B. G3·G4·G5 입력 | 1 | `G-required-tier-caller-recheck-g5` |
| C. 12/31 판정 게이트와 G2~G5 게이트 자체 | 5 | `G-internal-completion-2026-12-31` · `G-eos-g2` · `G-eos-g3` · `G-eos-g4` · `G-eos-g5` |
| D. 2027 보류 | 14 | 아래 표 (그중 2건은 12/31 만료와 엮여 있음 — ⚠ 표시) |

묶음 D 게이트를 `requires_gates`로 기다리는 태스크는 대장 전수 조사 결과 모두 `P3-17` 선행 사슬과 G3~G5 입력 밖이다(독립 검토 확인).

### A. 11/15 판정에 필요 — 2건

| 게이트 | 근거 1줄 | 판정 기준 |
|---|---|---|
| `G-p3-w3-release-merged` | 11/15 통합 판정 게이트 자체이며 12/31 조건 ①이다. 남은 Kiki 몫: Solution QA 검증 가능 비율 하한값(D9 (다) — P3-62 실측 후 확정 · 현재 0.48885, 후보 60%) | `3a83ed64` |
| `G-p345-m0677-link-disposition` | 처분이 나야 `P3-52`(02-09)가 착수된다. Phase 3 지표 ⑦ Graph Connectivity는 현재 **4/10**(`docs/reviews/p3_g2_week2_gate_evidence_2026-10-18/phase3_coverage_output.txt` · `p3_65_…_2026-10-26.md` 표)이고 목표는 0.95(`ops/phase3_metrics.py` 모듈 설명 ⑦ · P3-33) — 02-09는 10/10에 필요한 세 갈래 중 하나다(§4-2) | `3a83ed64` |

### B. G3·G4·G5 입력 — 1건

| 게이트 | 근거 1줄 | 판정 기준 |
|---|---|---|
| `G-required-tier-caller-recheck-g5` | 재확인 지점이 G5 데이터 동결(12/27)이고, `G-eos-g5`의 입력 `ARCH-67`이 이 게이트를 `requires_gates`로 기다린다 | `3a83ed64` |

### C. 12/31 판정 게이트와 G2~G5 자체 — 5건

| 게이트 | 판정 시점 | 근거 1줄 | 판정 기준 |
|---|---|---|---|
| `G-eos-g2` | **판정 기록됨** | corrections에 "[2026-10-28] verdict PASS — Kiki 판정 PASS(판정 기준 main `4ec479e6`)"가 있는데 status는 pending이다 — clear만 남았다(D13 5번) | `3a83ed64` |
| `G-eos-g3` | 11/22 | Kiki 결정(10/28)으로 11/22까지 보류 · 미측정이던 3항목 측정 경로는 EOS-207(done)이 만들었다 | `3a83ed64` |
| `G-eos-g4` | 12/13 | A4 30 CU · 1차 통과율 ≥70% · 무개입 루프 3연속 · 테스트 계정 ≥20 · P0 결함 0. 대장상 입력은 **`EOS-155`(blocked · P1 — Kiki 머신의 검수 데이터 필요)** 하나다 — G4 위험(§4-4). WP-F 측정 문서 `EOS-227`을 입력으로 잇는 안은 PR #1781(**미머지**) | `3a83ed64` |
| `G-eos-g5` | 12/27→12/31 | 원문 불변 · 증거 문서 = `docs/reviews/eos_g5_evidence_2026-12-27.md`(WP-G — 아직 없음 · 소유 태스크 `EOS-228`은 PR #1781 **미머지**) | `3a83ed64` |
| `G-internal-completion-2026-12-31` | 12/31 | 12/31 판정 게이트 자체 · 입력 P3-17 · 판정문(WP-H · `EOS-229` — PR #1781 **미머지**)이 필요하다 | `3a83ed64` |

### D. 2027 보류 — 14건 (표지만 · status pending 유지)

| 게이트 | 근거 1줄 | 다음 독촉 | 판정 기준 |
|---|---|---|---|
| `G-arch38-verdict-recheck` | 12/31 조건과 무관한 데이터 모델 재확인. 재확인 지점(10/26)은 이미 지났다 — 보류 대신 기본값 ①(판정 유지)로 지금 닫아도 되며, 판정 근거 ①은 테스트가 자동 감시한다 | 10/26(경과) | `3a83ed64` |
| `G-arch56-availability-trigger` | 트리거형(OpenRouter 가용성 측정). 주의: 발동 조건 ⓐ("학생 대면 트래픽을 받기로 결정")가 ARCH-64(2026-09-29 · 학생 대면 서빙 기본 좌석 = openrouter)로 이미 성립했을 수 있다 — 학생 트래픽 자체는 12/31 이후라 보류 제안은 유지. WP-F 회차에서 429 실패율이 한 회차 50% 이상이면(ⓒ) 묶음 B로 옮긴다 | 12/17 | `3a83ed64` |
| `G-arch66-anthropic-api-pause-review` | 방침 만료 지점 = 12/31 내부 완성. `G-internal-completion` 문면이 완성 판정 *뒤에* 차례로 판정하는 재개 게이트로 지목 | 12/31 | `3a83ed64` |
| `G-const-a0005-part1-corrections` ⚠ | 헌법 파트 I 집행 장치 정합 정정 채택 판정 — 12/31 조건과 무관. 단 아래 R4-02와 같은 계보다 | 없음 | `3a83ed64` |
| `G-const-r4-02-decision` ⚠ | A0005 채택 뒤 닫는 게이트(문면). **이 게이트의 (나)안(10/06)이 "어긋남은 만료 2026-12-31로 동결"이고, 그 만료가 `tests/constitution/test_schema_model_sync.py`의 `EXPIRES`다** — 보류해도 그 만료는 1/1에 RED를 낸다. 처분은 D13 4번과 묶는다 | 없음 | `3a83ed64` |
| `G-eos02-default-flip-recheck` | Kiki 판정 ②(10/03): 재판정 시점 = `G-arch66` 이후 | 11/20 | `3a83ed64` |
| `G-external-counsel-restart-after-internal-completion` | 내부 완성 이후 재개 게이트(문면) | 2027-01-01 | `3a83ed64` |
| `G-not-now-v1-release-recheck` | 내부 완성 이후 첫 계획 세션(문면) | 12/29 | `3a83ed64` |
| `G-opus5-billing-path-prod-recheck` | 프로덕션 배포 판정 시 또는 학생 대면 트래픽이 개발 좌석을 넘을 때(문면) — 12/31 전 발동 없음 | 12/20 | `3a83ed64` |
| `G-p356-signature-activation` | verdict FAIL 기록됨(10/27 · 운영 그림자 레코드 0건). 활성화 기준 오답 시도 n≥300은 운영 트래픽이 필요하다 | 11/01 | `3a83ed64` |
| `G-p359-m0672-shadow-disposition` | 판정 입력 완성(verdict PASS 10/18) · 세션 권고 ③ 현상 유지 · "오늘의 해 0", P3-06 종료 코드에도 영향 없음(판정문 §1) — 보류 대신 ③으로 지금 닫아도 된다 | 10/25(경과) | `3a83ed64` |
| `G-s302-free-use-remeasure-restart` | 연기 만료 지점 = 12/31 이후(문면) | 12/31 | `3a83ed64` |
| `G-s5-subject-expansion` | 수학 K-12 완성 전 타과목 착수 금지(불변 전제) | 없음 | `3a83ed64` |
| `G-student-work-after-internal-completion` | 내부 완성 이후 재개 게이트(문면) · Gate A 원문 학생 조건의 이관처 | 12/31 | `3a83ed64` |

"다음 독촉" = `requested + remind_after_days`. **2027 전에 독촉이 뜨는 것은 6건**이다(`G-arch38`·`G-p359`는 이미 경과, `G-p356` 11/01 · `G-eos02` 11/20 · `G-arch56` 12/17 · `G-opus5` 12/20). 지시문은 "표지만"을 요구했으므로 §5 기본 명령은 notes 표지만 붙인다. 독촉도 미루려면 `gates amend --remind-after-days`로 고친다(선례: `G-android-release-store-signing`의 30→107 정정) — D13 2번에서 함께 정해 주시면 된다.

**왜 `gates waive`를 쓰지 않는가**: waive는 status를 바꿔 그 게이트를 기다리던 태스크(학생 작업·변호사·API 재개 등)를 **해금**하고 notes를 사유로 덮어쓴다. "요건은 살아 있고 시점만 미뤘다"는 `gates amend --note`(status 불변 · notes append)로만 표현된다(`scripts/harness/backlog.py`의 `_cmd_gates_amend` 설명).

## 4. 범위 밖 발견 (고치지 않음 · 보고만)

### 4-1. 만료일 2026-12-31 유예가 12곳에 몰려 있다

내가 찾은 방법(`grep -rnE 'date\(2026, ?12, ?31\)'` — `tests`·`scripts`·`src`의 `.py`, 테스트 픽스처 문자열 제외)으로 **12곳**이다.

| 위치 | 건수 | 만료 시 동작 | CI 배선 | 소유 |
|---|---|---|---|---|
| `tests/constitution/test_schema_model_sync.py:33` `EXPIRES` | 1 | `date.today() <= EXPIRES` 단언 → RED | 테스트 | `G-const-r4-02-decision` 계보((나)안) · 처분 태스크 없음 |
| `tests/infra/test_architecture_doc_numbers.py:32` | 1 | 만료일 경과 시 RED | `infra-contracts` | `ARCH-72`(todo · P2) |
| `scripts/ops/check_provider_seat_contract.py:113-123` | 4 | 만료를 위반으로 기록(:281) → exit 1(:364) | `ci.yml:615`(`backend`) | 없음 |
| `scripts/ops/check_runbook_blocks.py:218-226` | 6 | 만료를 위반으로 처리(:780) | `ci.yml:1579`(`infra-contracts`) | 없음 |

처분 없이 해를 넘기면 12/31 판정 직후 main CI가 여러 곳에서 동시에 RED가 된다. 처분(해소 또는 의식적 연장)을 12/27 동결 전에 할지가 D13 4번이다.

### 4-2. Graph Connectivity 10/10까지 세 갈래가 필요한데 하나만 11/15 판정에 걸려 있다

Phase 3 지표 ⑦ 목표는 0.95다(P3-33). 현재 실측은 4/10이다(10/18 P3-G2 증거 · 10/26 P3-65 표). P3-44 설계 문서(10/16)의 "5/10 → 9/10, 02-09(P3-52)가 닫혀야 10/10"은 **P3-49(10/18)가 02-01 사슬을 끊기 전의 기준**이라 지금은 맞지 않는다. 독립 검토의 계산(추정 — 실측은 P3-14 CLI로 다시 재야 한다): `P3-44` 완료 시 8/10 → `P3-52`(02-09) 9/10 → `P3-50`(02-01 · todo · P2) 10/10. 셋 다 `P3-17` 선행이 아니다. PR #1780(**미머지**)이 `P3-17`에 다른 선행 5건(OPS-137·P3-62·P3-78·EOS-194·EOS-195)을 붙이는 중이므로, 이 셋을 더할지 Release Gate B 판정에서 ⑦ 미달을 FAIL 사유로 적을지를 함께 정해야 한다 — D13 3번.

### 4-3. `P3-90`(P1)의 게이트 조건은 운영 트래픽을 요구한다

`G-p356-signature-activation`의 소유 태스크 `P3-90`은 P1이지만, 기준 C1(오답 시도 n≥300)은 학생 트래픽 없이 채우기 어렵다. 이 레인의 분류 대상(EOS-200~218) 밖이라 등급 제안은 하지 않는다.

### 4-4. G4의 유일한 대장 입력 `EOS-155`가 blocked다

`G-eos-g4`의 `depends_on`은 `EOS-155-qa-engine-golden-rotation1-defect-sample`(blocked · P1) 하나다. `gates clear`는 입력이 전부 done이어야 통과하므로, 12/13 전에 이 차단이 풀리지 않으면 G4는 clear할 수 없다(FAIL 기록은 가능).

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

반영 뒤 검사: `python3 scripts/harness/backlog.py validate` · `audit-deps` exit 0, 그리고 표지 14건이 notes에 실재하는지 YAML을 읽어 대조한다. 독촉 주기 조정·Graph Connectivity 선행·만료 처분은 결정문 내용에 따라 별도 명령으로 반영한다.
