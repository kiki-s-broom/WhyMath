# 「Phase 3 — Math EOS 과목 완성 실행계획」 ↔ 빌드 하네스 백로그 변환 대조표 (1회차 · P3-00a)

> **판정 기준: main `e91a75d3`** (2026-09-20) · 백로그 736건 → **748건**(본 변환 +12) · 게이트 57건 → **58건**(+1)
>
> **태스크**: `EOS-128-phase3-plan-backlog-conversion` · **성격**: 대장 변환 + 대조 기록. **실행 승인이 아니다.**
> **원 문서**: Kiki 제공 외부 문서 「Phase 3 — Math EOS 과목 완성 실행계획」(2026.10.26~11.22) — **본 세션에 미첨부**.
> 확보한 입력 = 집행 지시문 세트 [01/20] `P3-00a`(마스터 프리앰블 포함 `.md` 1건).
>
> **선례**: `EOS-09` 계획서 300(Phase 2) 변환 — `docs/strategy/plan300_phase2_backlog_crosswalk.md`(PR #1178). 본 문서는 그 형식과 판정 어휘를 그대로 쓴다.

---

## §0. 먼저 읽을 것 — 이 변환의 지위와 입력 상태

### 0-1. 입력 결손 (가장 중요)

| 구분 | 내용 | 상태 |
|---|---|---|
| 첨부된 것 | `P3-00a` 지시문 — 마스터 프리앰블(Phase 3 목표·범위 규율·**Not Now List 12종 전문**·아키텍처/콘텐츠/착수/검증/산출 규율) + 이번 항목 지시 5개 | ✅ |
| 첨부되지 않은 것 ⓐ | 실행계획 **본문** — Week 1~4 작업 · 측정 지표 7종 · Release Gate A~E | ❌ |
| 첨부되지 않은 것 ⓑ | `P3-01~P3-14` 기준 분해안(세트 02~15/20) — 지시문 1이 "기준 분해안으로 삼되 대조하라"고 지목한 것 | ❌ |
| 첨부되지 않은 것 ⓒ | 세트 16~20/20 | ❌ |

**저장소 실측 — "내가 찾은 방법으로는 0건"** (검색 방법을 적는다):

- 파일명: 원격 브랜치 32개 전건 `git ls-tree -r --name-only` → `phase3|phase_3|p3_|p3-|not_now|notnow` 0건
- 본문: 원격 브랜치 32개 전건 `git grep -l -E "P3-01|Math EOS 과목 완성|Not Now List" -- docs` 0건 · main `grep -rlE "10\.26|11\.22|Release Gate A|Coverage ×|연결밀도|Not Now List|Digital Twin 고도화"` → 3파일 hit는 전부 Phase 2 문서(계획서 300 지시문 세트·크로스워크·N1~N10 갭 리뷰의 G3 11/22 언급)
- 히스토리: `git fetch --unshallow origin`(EXIT 0) 후 `git log --all --grep`(`Phase 3 —`·`P3-0`·`Not Now`·`과목 완성 실행`) 0건 — hit는 전부 ROADMAP의 다른 "Phase 3"(영재·대시보드·Part2 Phase 3 등)
- GitHub: 열린 PR 10건 제목·헤드 브랜치에 Phase 3 세트 0건 · PR 검색(`Phase 3 OR P3-00a OR "과목 완성" OR "Not Now"`) 128건 중 Phase 3 세트 0건(전부 Phase 2 슬라이스·게이트 판정 PR)
- 이벤트 대장 `backlog/events.ndjson`: `P3-|Phase 3|not.?now` 0건

**귀결**: 지시 1·2·3(Week 1~4·지표 7종·Gate A~E 분해와 P3-01~P3-14 대조)은 **이 회차에 수행할 수 없다** — 원 문서 없이 분해안을 쓰면 그것은 대조가 아니라 창작이다(CLAUDE.md "확실하지 않을 때 자신 있게 말함 금지"). 지시 4·5(Not Now 12종·산출 4종)는 지시문 자체가 목록 전문을 담고 있으므로 수행했다. 완료 판정은 **부분 충족**이다(§8).

### 0-2. 시작 조건 "Phase 2 Gate 2 PASS"의 실측 — 현재 미충족

- `EOS-22-gate2-final-judgment`(done · PR #1229) 판정문 `docs/reviews/eos_phase2_gate2_judgment_2026-09-19.md` §7 — **FAIL**. 10조건은 전건 충족, 추가 최종 조건 "무개입 연속 3루프"가 미충족(조건부 PASS 없음). 판정 시점은 원 계획 Gate 2(10/25)보다 5주 이르다(§0-1 그 문서).
- 이름 주의: 저장소 정본의 `G2`는 **앵커 콘텐츠 생산 게이트**(10/25)이고 계획서 300의 `Gate 2`와 이름만 같다(선언 정본 §1.3 · 2026-09-03 Kiki 확정). `P3-00a`가 말하는 "Phase 2 Gate 2"는 계획서 쪽 뜻이다.
- **본 변환은 등재이지 착수가 아니다**(`EOS-09` §0-2 선례: "등재는 대장에 올리는 것이고 착수는 별개다"). 그래서 시작 조건 미충족 상태에서도 대장 준비 작업으로 진행했다. **Phase 3 착수 여부·Gate 2 재판정 시점은 Kiki 결정 사항**이며 이 문서는 그것을 대신하지 않는다.

### 0-3. 이 변환이 하지 않는 것

Phase 3 일정 배정 · 착수 승인 · 대표 과정 동결(`P3-01`의 몫) · 지표 7종/Gate A~E의 저장소 편입 판정 — 전부 하지 않았다. §7이 각각의 이유를 적는다.

---

## §1. 방법

- 판정 근거는 **실파일 경로·명령 출력·태스크 ID** 중 하나여야 한다. 문서 언급만으로 "충족"한 행은 없다.
- **"식별자 부재 ≠ 기능 부재"**(CLAUDE.md) — Not Now 12종 각각을 계획서가 쓴 이름이 아니라 **역할 정규식**으로 코드(`src/backend/whymath_backend`·`src/mobile/lib`·`src/data-pipeline`)와 대장(736건 YAML 전문)에서 검색했다. 정규식은 §2 표에 그대로 적었으므로 재현·반증이 가능하다.
- **"trunk 부재 ≠ 미구현"** — shallow 클론을 `git fetch --unshallow origin`(EXIT 0)으로 해제한 뒤 `git log --all --grep`으로 미머지 구현을 확인했다.
- **판정 시점** — 상단 기준 커밋 해시 고정. 미머지 근거는 열을 나눠 적는다(본 문서에서 미머지 근거로 판정을 닫은 행은 없다).
- **보호 장치는 주입으로 검증** — "보류 상태"를 만드는 게이트가 실제로 착수 후보를 막는지, 게이트를 열어 RED(후보 등장)를 확인했다(§2-2).
- 재현 명령(읽기 전용):

```bash
cd /home/user/WhyMath
git fetch --unshallow origin
git rev-parse origin/main
python3 scripts/harness/backlog.py next --n 800 --json | grep -o 'NOTNOW-[0-9]*' | sort -u | wc -l
python3 scripts/harness/backlog.py gates list | grep -A3 G-not-now-v1-release-recheck
python3 scripts/harness/backlog.py validate
python3 scripts/harness/backlog.py audit-deps
```

---

## §2. 대조표 ① — Not Now List 12종 ↔ 태스크 ID

> 판정 어휘(`EOS-09`와 동일): **신규**(대응물 0건 → 등재) / **기존충족**(이미 대장·게이트가 덮음 → amend) / 인접 = 이름이 닮았으나 **다른 축**이라 겹침이 아닌 것

| # | Not Now 항목 | 처분 | 태스크 ID | 코드 실측(역할 정규식 → 파일 수) | 대장 인접(다른 축 — 겹침 아님) |
|---|---|---|---|---|---|
| 1 | Digital Twin 고도화 | 신규 | `NOTNOW-01-digital-twin-advanced` | `digital.?twin\|디지털 트윈` → **0** | `EOS-10`·`EOS-103`(LearnerState 단일 표면·영속 — 상태 모델이지 시뮬레이션 트윈이 아니다). 대장 hit 2건(`EOS-103`·`EOS-122`)은 §15 동결 준수 문구로만 언급 |
| 2 | 가상 학습 실험 | 신규 | `NOTNOW-02-virtual-learning-experiment` | `virtual.?(learning\|experiment)\|가상 학습` → **0** | `EOS-122`(페르소나 3종 여정 — 회귀 테스트 픽스처이지 실험 플랫폼이 아니다)·`PED-36`(시나리오 뱅크) |
| 3 | 성장 경로 장기 예측 | 신규 | `NOTNOW-03-growth-path-long-term-prediction` | `growth.?(path\|traject)\|성장 경로\|long.?term.?predict` → **0** | `ASM-02`·`ASM-07`·`ASM-12`(등급·백분위·합격예측 5필드의 **봉인** — 이미 있는 단기 예측치의 노출 정책)·`MGMT-06`(그 5필드 export 법률 검토 — 진행 중이나 예측 모델 개발이 아님, §3) |
| 4 | 교수법 자동 개선 | 신규 | `NOTNOW-04-auto-pedagogy-improvement` | `auto.*pedagog\|자동.*교수법\|prompt.?optimi[sz]` → **0** | `PED-*` 교수법 팩(사람 설계)·`docs/standards/prompt_engineering.md` A/B(사람 주도·Langfuse 버전). 계획서 300 §15 "자동 교수법 개선"·"고급 A/B framework"와 같은 계열 |
| 5 | 콘텐츠 자동 리팩토링 | 신규 | `NOTNOW-05-auto-content-refactoring` | `auto.*refactor\|콘텐츠 리팩` → **0** (`refactor` 대장 hit 3건은 코드·인벤토리 리팩토링 문맥) | `OPS-24` 백필 드리프트 검사·`EOS-97` 생성 산출물 리콜·`EOS-87` 오개념 canonical 수렴(사람 판정) |
| 6 | 다과목 Adapter | **기존충족 → amend** | `E1-01-dimensional-consistency`(대표) + `subject-expansion` 트랙 15건 | `SubjectAdapter`는 **계약 수준**(`EOS-66` done)·과목 팩 구현 **0** | 트랙 `entry_gate` `G-s5-subject-expansion`[kiki/decision]이 이미 하드락 — 계획서 300 변환 §2 #4·#5와 동일 판정("P3 + stage E + 게이트 3중 동결"). 신규 등재 대신 `E1-01`에 Not Now 게이트를 **추가 부착**(두 게이트가 모두 열려야 착수) |
| 7 | 연구자 협업 | 신규 | `NOTNOW-07-researcher-collaboration` | `researcher\|연구자` → **0** (`SEC-21` hit는 다른 문맥) | `COLLAB-01~07`(보호자·교사 접근 매트릭스 — 연구자 역할 0)·`docs/legal/pipa_data_matrix.md`. 재개 선결 = 미성년자 데이터 외부 공유 금지 레일·명시 동의·법무 검토(기계 대체 불가) |
| 8 | 복잡한 Agent 협업 | 신규 | `NOTNOW-08-complex-agent-collaboration` | `multi.?agent\|agent.?orchestr\|에이전트 협업` → **0** | WH-1 튜터링·WH-S 솔버 하네스(단일 루프 + 도구 호출·라우터 경유). 계획서 300 §15 "새로운 Agent architecture"와 같은 계열 |
| 9 | Graph 자동 군집화 | 신규 | `NOTNOW-09-graph-auto-clustering` | `community_detect\|louvain\|leiden\|pagerank\|graph.?cluster\|군집화` → **0** | `S4-12`(풀이 유형 동치 군집 — **풀이 축**·사람 검수 큐·자동 확정 금지)·`KG-*`(개념 그래프 수동 정본·PG 단일 평면 2,683노드). 계획서 300 §15 "고급 Knowledge Graph 분석"과 같은 계열 |
| 10 | 자동 교육과정 생성 | 신규 | `NOTNOW-10-auto-curriculum-generation` | `curriculum.?gen\|auto.?curriculum\|교육과정 생성\|커리큘럼 생성` → **0** | `PATH-*`(학생 **개인** 학습 경로 추천 — 폐쇄루프의 일부)·`CUR-*`(기존 교육과정에의 정렬). "Curriculum은 Overlay" 원칙 |
| 11 | 국제 Curriculum 확장 | 신규 | `NOTNOW-11-international-curriculum-expansion` | `international\|다국\|multi.?country` → **9** — 실체는 `schema/curriculum_entry.py` **Schema v1.1 다국 커리큘럼 매트릭스 셀 모델(31필드·슬라이스 8a)**: 스키마는 있고 **9~12개국 데이터 확장·적재가 0** | `docs/data/curriculum_matrix.md`(Phase 1 = 한국 + 참고용 미국·IMO)·`ROADMAP.md:186,193`("다국 커리큘럼 매트릭스 9~12개국 풀스케일") — ROADMAP에는 있으나 **대장 태스크가 0건이던 축** |
| 12 | 고급 추론 엔진 | 신규 | `NOTNOW-12-advanced-reasoning-engine` | `advanced.?reason\|추론 엔진\|self.?evol\|자기진화` → **12** — 실체는 기존 WH-S 솔버 하네스(`whs/` 14모듈 · `self_evolution.py`·`prm_builder.py` 실재 · `S2-02` done)와 `reasoning_type` 태그: **고도화 축이지 신설 아님** | `ROADMAP.md:47`("WH-S 자기진화 라운드·PRM(S2~S3)")·`docs/architecture/03b_wh_s_solver_harness.md`. 재개 시 기존 `whs` 위에서 설계(별도 엔진 신설 금지 — 이중 진실 원천) |

**12종 전건에 처분이 대응한다** — 신규 **11건** · 기존충족→amend **1건**(#6). 신규 11건의 공통 속성:

| 속성 | 값 | 이유 |
|---|---|---|
| `track` / `stage` | `math-completion` / `S5` | S5 = "수학 완성 후"(status_roadmap §3) — "v1.0 이후"와 같은 위치. `stage_order`상 S0~S4 뒤라 `next` 정렬에서도 뒤로 간다 |
| `priority` | **5**(최하) | 지시 4 "priority를 최하로" |
| `eos_priority` | **P3**(장기 연구·플랫폼) | `add`가 요구하는 12월 검증 관여도 축. Not Now = 12월 출시 이후 = 정의상 P3 |
| `requires_gates` | `G-not-now-v1-release-recheck` | "11월 착수 금지"의 **집행 지점**(§2-1) |
| `notes` | "v1.0 이후, 11월 착수 금지" + 중복 실측 + 인접 | 지시 4 원문 그대로 |
| `acceptance` | 자리표시 3항(게이트 전 착수 금지 · 재개 시 acceptance를 실제 설계로 교체 · 실측 없는 재개 금지·미재개 시 cancel) | **지금 설계하지 않는다** — 계획서 300 §15가 같은 계열을 production code 동결로 지정했고 그 동결은 유지된다. 설계 문서를 지금 쓰는 것도 하지 않았다(범위 규율) |
| `subject` | `cross` | 과목 중립 플랫폼 축 |

`id` 접두 `NOTNOW`는 12종이 **한 묶음으로 식별·조회**되게 하기 위한 것이다(`ls backlog/tasks/NOTNOW-*`). 번호는 Not Now List 순서이며 **06은 결번**이다(#6이 기존 E축 amend로 처분됐기 때문 — 번호를 당겨 채우면 목록 순서와 어긋난다).

### 2-1. "보류 상태"의 집행 — notes가 아니라 게이트

지시 4는 "notes에 적고 priority를 최하로"까지만 요구한다. 그러나 **`selector.py`는 notes를 읽지 않는다**(CLAUDE.md "선행 조건을 산문에만 적고 대장에 집행하지 않기 금지"). priority 5인 `todo`는 여전히 착수 후보 풀 안에 있고, 어느 세션이든 `backlog.py start`로 잡을 수 있다. 그래서 산문 위에 **게이트**를 얹었다:

| 게이트 | `G-not-now-v1-release-recheck` |
|---|---|
| kind / assignee | `decision` / `kiki` |
| 재확인 지점 | **v1.0(12월 출시) 이후 첫 계획 세션** — `remind_after_days: 100`(2026-12-29 리마인드) |
| 판정 3택 | ①유지(다음 재확인 지점을 새 게이트로 재생성) ②재개(해당 태스크 acceptance를 실제 설계로 갱신 후 착수 허용) ③폐기(`cancel`) |
| 선례 동형 | `G-arch38-verdict-recheck`·`G-arch56-availability-trigger` — "재확인을 태스크로만 등재하면 selector가 즉시 착수 후보로 계산한다"는 같은 이유로 게이트를 쓴 선례 |

`block`을 쓰지 않은 이유: `block`은 "차단 사유가 해소되면 `unblock`"이라는 **주체 없는 대기**이고, 게이트는 **사람 소유 결정 지점 + 만료 리마인드 + `gates clear --evidence` 판정 근거 요구(HARN-68)**라 "만료 없는 유예 금지" 규칙에 맞는다. 12종 중 진행 중인 것이 0건이라(§3) `block` 판단을 Kiki께 요청할 대상도 없다.

### 2-2. 주입 검증 — 정상 입력에서 초록인 것은 증거가 아니다

"게이트가 보류를 만든다"는 주장을 게이트를 열어 확인했다(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지").

| 단계 | 조작 | 관측(`next --n 800 --json` · 절단 없는 전건) |
|---|---|---|
| 정상 | 없음 | `NOTNOW-*` 후보 **0/11** · `E1-01` 후보 0 |
| 주입 | `backlog/gates.yaml`의 해당 게이트 `status: pending` → `cleared`(앵커 1건 단언 · 길이 산술 단언 · `cp` 백업 선행) | `NOTNOW-*` 후보 **11/11 등장 = RED** · `E1-01`은 여전히 0(트랙 `entry_gate`가 2차 잠금) |
| 원복 | `cp` 백업 → `cmp` **바이트 동일** | `git diff --stat backlog/gates.yaml` = 신규 게이트 블록 +10줄만 |

해석: 보류를 실제로 만드는 것은 게이트 하나다. 게이트가 열리면 11건이 **즉시** 착수 후보가 된다 — 그래서 clear 판정이 "유지=재생성 / 재개 / 폐기"의 3택이어야 하고, "일단 열어 두자"는 없다.

---

## §3. 대조표 ② — Not Now ∩ 진행중 (Kiki 판단용)

지시 4: "이미 진행 중인(in_progress·열린 PR) 것이 있으면 따로 표로 내라 — block 처리 여부는 Kiki가 판단한다."

**모집단**(2026-09-20 실측): `status` 출력의 in_progress **8건** + SessionStart 브리핑의 타 세션 원격 claim **8건** + GitHub 열린 PR **10건**. 각각을 Not Now 12종과 대조했다:

| 진행 중 항목 | 출처 | Not Now와의 관계 | 판정 |
|---|---|---|---|
| `MGMT-06` 열람권 export 예측 5필드 법률 검토 | 원격 claim + PR #1061 | #3 성장 경로 예측과 **어휘만** 겹침 — 대상은 이미 존재하는 단기 예측치의 법적 처리 | 비해당 |
| `MP-02` 첫 LLM 저작 회차 | 원격 claim | #5 콘텐츠 리팩토링 아님(생성·검수) | 비해당 |
| S4-16 강등전 PR #844·#856·#865 | 열린 PR | #8 Agent 협업 아님(단일 LLM 강등전·OpenRouter 공급) | 비해당 |
| `LIC-01` Rights & Provenance MVP | in_progress + PR #858 | 12종 어디에도 없음 | 비해당 |
| `EOS-117`·`EOS-119`·`EOS-63`·`SKB-03`·`SKB-04`·`PB-13`·`MOB-18`·`NLP-05`·`ASM-10`·`HARN-56`·`HARN-82`·`OPS-73` | in_progress / 원격 claim / PR | 경계 집행·시나리오·적재·코퍼스 회수·모바일·채점·귀속·머지 큐·필수 체크·인벤토리 — 12종 어디에도 없음 | 비해당 |
| PR #1226·#1076·#1007·#975 | 열린 PR | 하네스·판정·회수 | 비해당 |

**Not Now ∩ 진행중 = 0건.** `EOS-16`(2026-09-16 · LOOP/SUPPORT/FUTURE 감사)의 "FUTURE∩진행중 0건"과 일치한다. **Kiki께 block 판단을 요청할 항목은 없다.**

---

## §4. 대조표 ③ — `P3-00a` 프리앰블이 담은 Phase 3 규율 ↔ 저장소 집행 장치

원 문서 없이도 확인 가능한 것은 프리앰블의 **규율**이다. 이것들은 태스크가 아니라 **이미 서 있는 집행 장치**에 대응한다 — 등재 대상이 아니라 "지켜지고 있는가"의 대상이다.

| 프리앰블 규율 | 저장소 집행 장치(실재) | 판정 |
|---|---|---|
| 신규 EOS Core Entity 금지 | `ARCH-37` 검사 ②(20번째 엔티티 RED) · `tests/backend/db/test_canonical_entity_model_freeze.py` | 기계 집행 중 |
| 새로운 AI Agent / Subject Adapter 추가 금지 | `EOS-67`·`EOS-117` import-linter 3계약 + CI `lint-imports`(경계 위반 RED 실증 PR #1215) · `G-s5-subject-expansion` | 기계 집행 중 |
| LLM은 학습 상태를 직접 결정하지 않는다 | `harness/wh1_llm_policy.py` `_enforce_invariants` · `EOS-105` 상태 머신(전이는 Assessment/Mastery/Policy만) | 코드 집행 중(계획서 300 변환 §5 #12) |
| `if subject == "math"` 분기 금지 | `EOS-04` CORE 수학어휘 ratchet 게이트 · `scripts/analysis/eos_core_boundary_probe.py` | 기계 집행 중 |
| 라우터 경유 + Langfuse · SymPy 단일 권위 | `l3/router.py` · `EOS-77` 우회 게이트 · Langfuse 실배선 | 집행 중 |
| 오개념 preload 금지 · depth ≤ 2 | `test_llm_subgraph_budget_invariant`(graph→LLM 빌더 0 동결) · reactive retrieval 경로 | 집행 중(`ARCH-11`이 트리거 대기) |
| 지표는 CLI가 exit code로 판정 | `ops/validation_scorecard.py`(KPI 12종) · `EOS-15`(Phase 2 KPI 5종) | 집행 중 — 단 **Phase 3 지표 7종은 미확보**(§7-②) |
| 대규모 DB Schema 변경 · 대규모 UI 구조 변경 금지 | 기계 게이트 **없음** — 사람 규율(PR 리뷰) | 미집행(정직 표기) — 필요하면 별건 등재는 Kiki 판단 |

---

## §5. 산출 ① — 등재·수정된 태스크 전체 목록

### 5.1 신규 등재 12건

| 태스크 ID | 구분 | priority | eos_priority | stage |
|---|---|---|---|---|
| `EOS-128-phase3-plan-backlog-conversion` | 변환 태스크 자신(in_progress) | 2 | P1 | S3 |
| `NOTNOW-01-digital-twin-advanced` | Not Now #1 | 5 | P3 | S5 |
| `NOTNOW-02-virtual-learning-experiment` | Not Now #2 | 5 | P3 | S5 |
| `NOTNOW-03-growth-path-long-term-prediction` | Not Now #3 | 5 | P3 | S5 |
| `NOTNOW-04-auto-pedagogy-improvement` | Not Now #4 | 5 | P3 | S5 |
| `NOTNOW-05-auto-content-refactoring` | Not Now #5 | 5 | P3 | S5 |
| `NOTNOW-07-researcher-collaboration` | Not Now #7 | 5 | P3 | S5 |
| `NOTNOW-08-complex-agent-collaboration` | Not Now #8 | 5 | P3 | S5 |
| `NOTNOW-09-graph-auto-clustering` | Not Now #9 | 5 | P3 | S5 |
| `NOTNOW-10-auto-curriculum-generation` | Not Now #10 | 5 | P3 | S5 |
| `NOTNOW-11-international-curriculum-expansion` | Not Now #11 | 5 | P3 | S5 |
| `NOTNOW-12-advanced-reasoning-engine` | Not Now #12 | 5 | P3 | S5 |

### 5.2 기존 태스크 수정(amend) 1건

| 태스크 ID | 변경 | 사유 |
|---|---|---|
| `E1-01-dimensional-consistency` | `requires_gates` + `G-not-now-v1-release-recheck` · notes에 Not Now 표식 | Not Now #6 다과목 Adapter의 대표 좌석(§2 #6) |

### 5.3 게이트 신규 1건

`G-not-now-v1-release-recheck`(§2-1) — 부착 태스크 12건(NOTNOW 11 + `E1-01`).

전부 `backlog.py add / amend / gates add` CLI 경유(대장 손편집 0 · 번호 추론 0). `validate` 748건 green · `audit-deps` 위반 0.

---

## §6. 산출 ② — 겹침으로 등재하지 않은 항목

| Not Now 항목 | 등재하지 않은 근거 |
|---|---|
| #6 다과목 Adapter | `subject-expansion` 트랙 15건(`E1-01`~`E6-01`·`ARCH-30`·`ARCH-34`·`ARCH-35`·`E1-90` 등)이 전건 `todo`·`eos_priority P3`·stage E1~E6이고 트랙 `entry_gate` `G-s5-subject-expansion`이 하드락 — 계획서 300 변환 §2 #4·#5가 "3중 동결"로 판정한 상태 그대로다. 새 태스크는 그 위에 **네 번째 사본**을 만들 뿐이다. 대표 1건 amend로 Not Now 표식·게이트를 얹었다 |

---

## §7. 산출 ③ — 원 문서가 요구하지만 등재할 수 없었던 것

| # | 요구 | 등재 불가 사유 |
|---|---|---|
| ① | **Week 1~4 작업 분해** | 원 문서 본문 미첨부(§0-1). 항목명조차 확보되지 않아 "0건 등재"가 아니라 **판정 불가**다 |
| ② | **측정 지표 7종** | 미첨부. 확보되더라도 **편입 판정이 선행**한다 — 저장소 KPI 정본은 12종(`validation_scorecard.py:129`)이고 Phase 2 KPI 5종(`EOS-15`)이 이미 별축으로 얹혀 있다. 7종을 그냥 얹으면 KPI 정본이 **셋**이 된다(`EOS-09` §9-③ 동형) |
| ③ | **Release Gate A~E** | 미첨부. 확보되더라도 **이름 충돌 예방이 선행**한다 — 저장소에는 이미 "Gate 0 A~E"(Phase 0·PR #1168)와 G0~G5(선언 부록 E)가 있다. `G2` 이름 충돌 3회차(선언 §1.3) 선례대로 등재 시 `Phase 3 Release Gate A`로 전체 표기해야 한다 |
| ④ | **`P3-01~P3-14`와의 대조** | 세트 02~15/20 미첨부 |
| ⑤ | **대표 과정 범위 동결** | `P3-01`의 결정 사항이며 착수 단위가 아니다. 이 문서는 대표 과정이 무엇인지 모른다 |
| ⑥ | **"10/26부터 이것을 한다"는 일정** | 시작 조건(Gate 2 PASS)이 현재 FAIL(§0-2). 게다가 종료일 11/22는 저장소 `G3`(폭 확장·붕괴지점 — 앵커 전부 60 CU+·HIT ≤6분)와 **같은 날짜에 다른 판정 대상**이다(선언 부록 E). 어느 것이 11/22의 정본인지는 결정 사항 |
| ⑦ | **Not Now 12종의 설계 문서** | 지시 4는 등재만 요구하고, 계획서 300 §15는 "설계 문서는 남겨도 되나 코드는 동결"이라 했다. 본 변환은 설계 문서도 쓰지 않았다 — 자리표시 acceptance가 "재개 시 실제 설계로 교체"를 첫 행위로 지정한다. 지금 설계하면 v1.0 실측 없이 상상으로 쓰게 된다 |

---

## §8. 완료 판정 — **부분 충족**

`P3-00a` 완료 판정 = "원 문서 각 항목이 태스크 ID에 대응되는 대조표가 main에 있고, Not Now 12종이 보류 상태로 등재됨"

| 축 | 판정 | 근거 |
|---|---|---|
| 원 문서 각 항목 ↔ 태스크 ID 대조표 | **미충족** | 원 문서 미첨부 — §0-1·§7 ①~④. 창작하지 않았다 |
| Not Now 12종 보류 등재 | **충족** | 신규 11 + amend 1(§5) · 보류 = 게이트 집행 · 주입 RED 확인(§2-2) · `validate`·`audit-deps` green |

**다음 회차 재실행 조건**: 원 문서 본문 + `P3-01~P3-14`(세트 02~15) 첨부. 같은 태스크 `EOS-128`을 **이어서** 쓴다(acceptance ①이 미이행이므로 `done` 처리하지 않는다 — 1회차 PR은 미완 예외가 아니라 *산출물이 있는 부분 완료*라 PR을 연다). 2회차는 본 문서에 §9 이후를 **추가**하고 상단 기준 해시를 갱신한다.

---

## §9. 다음 항목(`P3-01`)에 넘기는 선행 조건

1. **원 문서 첨부 → 본 변환 2회차**(Week 1~4·지표 7종·Gate A~E 분해 + `P3-01~P3-14` 대조). 이것 없이 `P3-01`을 실행하면 대표 과정 동결이 대장 밖에서 일어난다.
2. **Gate 2 재판정 또는 시작 조건 면제** — `EOS-22` FAIL의 미충족 축은 "무개입 연속 3루프"(판정문 §6-1) 하나다. 재판정은 그 축의 소유자(판정문이 지목한 후속)가 착지한 뒤 별도 판정 세션에서 한다(지시문 세트 주의 3번: 구현 세션과 판정 세션 분리).
3. **지표 7종·Gate A~E의 저장소 편입 방식 결정**(§7 ②③) — 정본 셋·이름 충돌을 피하는 표기가 정해진 뒤 등재한다.

---

**작성**: 2026-09-20 · `EOS-128-phase3-plan-backlog-conversion` · 판정 기준 main `e91a75d3`
