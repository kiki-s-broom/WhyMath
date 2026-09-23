# 「Phase 3 — Math EOS 과목 완성 실행계획」 ↔ 빌드 하네스 백로그 변환 대조표 (1회차 · P3-00a)

> **판정 기준: main `e91a75d3`** (2026-09-20) · 백로그 736건 → **748건**(본 변환 +12) · 게이트 57건 → **58건**(+1)
>
> **태스크**: `EOS-128-phase3-plan-backlog-conversion` · **성격**: 대장 변환 + 대조 기록. **실행 승인이 아니다.**
> **원 문서**: Kiki 제공 외부 문서 「Phase 3 — Math EOS 과목 완성 실행계획」(2026.10.26~11.22) — **본 세션에 미첨부**.
> 확보한 입력 = 집행 지시문 세트 [01/20] `P3-00a`(마스터 프리앰블 포함 `.md` 1건).
>
> **선례**: `EOS-09` 계획서 300(Phase 2) 변환 — `docs/strategy/plan300_phase2_backlog_crosswalk.md`(PR #1178). 본 문서는 그 형식과 판정 어휘를 그대로 쓴다.
>
> **⚠ 이 문서는 회차별 누적이다 — 최신 판정은 문서 *끝*에 있다.** 위 §0~§9는 **1회차**(판정 기준 `e91a75d3`) 것이고, 아래로 갈수록 최신이다: 2회차 §10~§15(`266c3d55`) → 3회차 §18~§21(`5afc1c34`) → **4회차 §22(`1671b9d4`)**. 각 회차의 상단 해시는 그 회차 시점의 것이며 소급 갱신하지 않는다 — 판정은 시점에 종속되므로 해시 없는 판정은 재현 불가다.
> **4회차 처분 요약**: §16-3 미결 2건과 §21-1 ①②가 **Kiki 결정 2건으로 닫혔다**(게이트 `G-p3-w3-release-merged` 신규 + waive 2건 · 태스크 `EOS-130` 신규). 각 절에 포인터를 달았고 집행 증거는 §22에 있다.

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

---
---

# 2회차 (2026-09-22) — 원 문서 본문 수령 후 대조

> **판정 기준: main `266c3d55`** (2026-09-22) · 백로그 **783건** · 게이트 **62건**
> **이번 회차의 변경: 0건** — 신규 등재도 amend도 하지 않았다. 이 회차는 **대조 전용**이다(사유 §10-2).
> **1회차 판정 기준(main `e91a75d3`)과 열이 다르다** — 위 §0~§9는 그 시점의 판정이며 갱신하지 않았다.

## §10. 2회차 입력 상태 — 절반이 도착했다

### 10-1. 무엇이 왔고 무엇이 아직 없는가

| 구분 | 1회차(09-20) | 2회차(09-22) |
|---|---|---|
| `P3-00a` 지시문 [01/20] | ✅ | ✅ |
| 실행계획 **본문** (Week 1~4 · 지표 7종 · Gate A~E) | ❌ | ✅ **도착** |
| `P3-01~P3-14` 기준 분해안 (세트 02~15/20) | ❌ | ❌ **여전히 없음** |
| 세트 16~20/20 | ❌ | ❌ |

도착한 본문은 저장소에 전사 보존했다 — `docs/strategy/phase3_math_eos_completion_plan_source.md`.
출처 sha256 `b109941c324d1aa5dbdc112e1878309899d75b9d5bc70cd659b2ea65bee7a012` · 원본 27,032바이트 · 추출 7,108자.
전사 충실도는 기계 대조했다(원문 고유 항목 91건 전건 존재 · 누락 0). **이 보존이 §0-1이 기록한 "원 문서가 저장소 어디에도 없다"를 영구 해소한다** — 1회차 차단은 세션의 망각이 아니라 입력이 채팅에만 있었던 구조 때문이었다.

### 10-2. 이번 회차가 **등재하지 않은** 이유

`P3-01~P3-14`는 Kiki가 이미 만든 **14개 분해 단위**다. 그것 없이 내가 Phase 3를 임의 단위로 쪼개 등재하면, 나중에 그 분해안이 도착했을 때 **같은 일이 두 번 등재된 대장**이 된다. 그것이 acceptance ②(중복 실측 → 겹치면 신규 등재 금지)가 막으려는 바로 그 상태이고, 태스크 acceptance는 append 전용이라 되돌리기도 어렵다.

그래서 범위를 나눴다 — **(가) 원 문서 항목 전수 열거 + 기존 태스크 대조는 수행**(신규 등재가 없으므로 `P3-01~P3-14`가 와도 버려지지 않는다) · **(나) 신규 태스크 등재는 보류**. 이 회차는 (가)다.

(가)의 부수 효과가 하나 있다: 아래 대조표는 `P3-01~P3-14`가 **무엇을 덮어야 하는지**를 보여준다. 이미 태스크가 있는 항목을 다시 분해하면 그것이 중복이다.

### 10-3. 방법 — §1을 그대로 쓰되 두 가지를 더했다

- **역할 정규식 색인** — 백로그 783건의 `id·title·acceptance·notes·paths·layer·subject·track`을 한 문자열로 합쳐 색인하고, 원 문서 항목마다 **이름이 아니라 역할**로 검색했다(식별자 부재 ≠ 기능 부재). 정규식은 아래 표의 각 행에 그대로 적었으므로 재현·반증이 가능하다.
- **0건은 2차 검색으로 재확인** — 1차 0건인 항목은 ⓐ다른 관용어 ⓑ소비자측(호출하는 코드) ⓒ실제 소스 파일 순으로 다시 찾았다. **네 항목이 1차 0건이었는데 그중 둘은 2차에서 실재가 확인됐다**(W1-2 대상 범위 → `EOS-52` · W3-2 Tutor output → `CoachResponse` 코드). 즉 1차 0건을 그대로 "부재"로 적었으면 **오판정 2건**이었다. 나머지 둘(W2-1·지표②)은 2차·코드까지 확인해도 0건이라 "대응 없음"으로 판정했다.

---

## §11. 대조표 ④ — Week 1~4 작업 ↔ 태스크 ID

판정 어휘: **대응 있음**(기존 태스크가 그 일을 소유) · **부분 대응**(일부만 소유·나머지는 미소유) · **대응 없음**(내가 찾은 방법으로는 0건).

### 11-1. Week 1 (10/26~11/1) — 대표 과정 동결 + Coverage

| # | 원 문서 항목 | 판정 | 대응 태스크 / 근거 |
|---|---|---|---|
| W1-1 | 출시 대표 과정 1개 | **대응 있음** | `EOS-52-anchor-asset-audit`(done) — 앵커 후보 **8단원**의 원자·성취기준·오개념·detection_rule·문항 코퍼스 실측 커버리지. 저장소는 "대표 과정"을 **앵커**라고 부른다 |
| W1-2 | 대상 학년/과목/단원 범위 | **부분 대응** | 같은 `EOS-52`가 단원 범위를 실사했다. 다만 **"동결한다"는 결정 행위**를 소유한 태스크는 못 찾았다 — 실사는 있고 동결은 없다 |
| W1-3 | Curriculum Node 목록 | **대응 있음** | `CUR-03`(done·성취수준 A~E·평가기준 반입) · `EOS-82`(done) · `S4-03`(todo) |
| W1-4 | Concept 목록 | **대응 있음** | `ARCH-13`(done) — `atom_node` **2,697**·`concept_edge` 437 입도 통합. `SKB-03`가 2,683노드 적재 완료(CLAUDE.md 실측) |
| W1-5 | Skill 목록 | **대응 있음** | `SKB-01`(done·`concept_behavior_skill` 적재) · `EOS-63`(todo·`skill_mastery_tracking` 소비 전환) |
| W1-6 | 핵심 오개념 목록 | **대응 있음** | 22건 hit. 대표 = `ASM-01`·`ASM-09`·`ARCH-49`·`EOS-05` + 크로스워크 계약 정본 `docs/standards/crosswalk_gate_contract.md` |
| W1-7 | 필수 Problem Type 목록 | **대응 있음** | `CONT-04`(todo·rephrased_v0 429문 유형 태깅 — **16.2% 미상환**) · `PB-09`(todo·변형 3종 발화) |
| W1-8 | 문제 수량 목표 | **대응 있음** | `EOS-54`(done·CU 단위 생산 계측) · `CUR-19`·`QUAL-09`(todo) |
| W1-9 | 콘텐츠 completeness 기준 | **부분 대응** | `EOS-51`(done·CU 스키마 동결)이 *한 CU의* 완전성을 정의한다. 원 문서가 말하는 *과정 전체의* completeness 기준은 미소유 |
| W1-금지1 | EOS Core 신규 Entity 동결 | **대응 있음** | 좌석 계약 체계 — `ARCH-37`·`ARCH-38`·`ARCH-39`(done) 등. 부재 동결 4종·전수 귀속 스캔이 CI `infra-contracts` 잡에서 집행 |
| W1-금지2 | 대규모 DB Schema 변경 동결 | **대응 있음** | prod 스키마 프로브(신규 alembic 리비전 미등재 차단) — `HARN-109`(done)·`OPS-72`(done) |
| W1-금지3 | 새 AI Agent 추가 동결 | **대응 있음** | `NOTNOW-08-complex-agent-collaboration`(todo·P3·게이트 `G-not-now-v1-release-recheck` 부착) — **1회차 산출** |
| W1-금지4 | 새 Subject Adapter 추가 동결 | **대응 있음** | `subject-expansion` 트랙 15건 전건 `todo`·P3 + `entry_gate` `G-s5-subject-expansion` 하드락 = §6이 판정한 **3중 동결** 그대로 |
| W1-금지5 | 대규모 UI 구조 변경 동결 | **부분 대응** | `HARN-103-feature-code-freeze-rules`(todo)가 기능 동결 규칙을 소유하나 **미착지**. 현재 UI 구조 변경을 막는 기계 장치는 내가 찾은 방법으로는 0건 |
| W1-완료 | Curriculum→Concept→Skill→Problem 최소구조 | **대응 있음** | `EOS-07`(done) — **모든 Problem이 최소 1개 Skill 연결**을 계약 테스트로 동결. `EOS-100`·`EOS-03`(done) |
| W1-완료 | 핵심개념 + Prerequisite/Misconception/Solution/Hint/Pedagogy | **부분 대응** | `ARCH-17`(done·DAG)·`CUR-06`(todo·학교급 경계 연결 **20/2210 = 0.9%**·고→대 0). Hint 저장 좌석은 `ARCH-39`가 "선언 정본 ↔ 저장 실측 불일치 **유일** 엔티티"로 지목 |
| W1-지표 | Content Coverage Rate ≥95% | **부분 대응** | `ARCH-18`(done·공급측 커버리지 리포트)·`ASM-05`(done·수요측 도달 관측)·`CUR-02`(done). **목표치 95%를 게이트로 거는 장치는 0건** — 관측은 있고 판정은 없다 |

### 11-2. Week 2 (11/2~11/8) — Problem/Solution/Misconception 밀도

| # | 원 문서 항목 | 판정 | 대응 태스크 / 근거 |
|---|---|---|---|
| W2-1 | Concept당 문제 6종(대표·기본·응용·오개념유발·진단·숙련도확인) | **대응 없음** | 1차 0건 → 2차(생산 규격 관용어)도 이 **6종 분류 자체**는 0건. 가장 가까운 것이 `EOS-51`의 CU 스키마인데 그것은 *유형 세트*가 아니라 *한 단위의 형식*이다. **이번 회차에서 가장 명확한 공백** |
| W2-2 | Problem 필드 7종 | **부분 대응** | `difficulty`=`S1-16`(done·IRT)·`concept`/`skill`=`EOS-07`(done)·`solution`/`answer`=문항 스키마 실재. `misconception signature`=`SignaturePattern` enum 실재 · **`hint strategy` 필드는 `ARCH-39`가 저장 좌석 부재로 지목** |
| W2-3 | Wrong Answer → Error Signature | **대응 있음** | `ASM-06`(done·오답지↔오개념 역링크)·`ASM-09`(done)·`MISC-30`(done) |
| W2-3b | Misconception Candidate + Confidence | **대응 있음** | 코드 실재 — `MisconceptionMatch.confidence: float(0~1)`·`matched_signals`·`attribution_unclear` (`l4/misconception/models.py:132`) |
| W2-3c | Remediation Strategy | **부분 대응** | 66건 hit이나 대부분 소음. 확정 대응 = `EOS-123`(todo) — "정답 회차가 오개념 감쇠 시계를 돌리지 않는다 · 채점↔코치 **반증 비대칭**". 즉 교정 경로는 있으나 **반증 축에 알려진 결함**이 있다 |

### 11-3. Week 3 (11/9~11/15) — AI Tutor 품질

| # | 원 문서 항목 | 판정 | 대응 태스크 / 근거 |
|---|---|---|---|
| W3-1 | Tutor context 9종 | **대응 있음 (초과)** | `CoachRequest`(`api/coach.py:234`)가 원 문서 9종을 **전부 포함하고 더 받는다** — `polya_state`·`mastery_level`·`bkt_mastery`·`coaching_focus`·`solution_steps`·`solution_step_types`·`ocr_confidence`·`persona`. 컨텍스트 폭주 방어는 `ARCH-11`(blocked·subgraph depth guard) |
| W3-2 | Tutor output 구조화 | **대응 있음 (초과)** | **1차 0건이었으나 코드에 실재**한다. `CoachResponse`(`api/coach.py:350`)가 원 문서 제안 스키마 8필드를 전부 덮고 초과한다 — 아래 11-4 대조표 |
| W3-3 | AI 품질 Gate 8축 | **부분 대응** | 아래 11-5 대조표 |

#### 11-4. 원 문서 제안 Tutor output 스키마 ↔ 저장소 실제 (`CoachResponse`)

| 원 문서 제안 필드 | 저장소 실제 | 비고 |
|---|---|---|
| `diagnosis.concept_id` / `misconception_id` | `misconceptions: list[MisconceptionMatch]` | 단수 → **복수 후보 리스트**로 확장 |
| `diagnosis.confidence` | `MisconceptionMatch.confidence: float(0~1)` | 동일 |
| `response_strategy` | `decision: PedagogyDecision` | `socratic_category`·`polya_stage_to_advance` 포함 |
| `hint_level` | `PedagogyDecision.hint_level: Literal[1,2,3,4]` | 값 범위까지 동일 |
| `explanation` | `decision` + `solution_coaching` | |
| `next_action` | `problem_complete`·`awaiting_reflection`·`intervention` | 분화 |
| `mastery_update_allowed` | `completion_evidence: AssessmentEvidence`·`completed_attempt_id` | **증거 기반**으로 강화 |
| (없음) | `match_low_quality`·`match_attribution_unclear`·`no_confident_match`·`lthc`·`prerequisite_coaching`·`answer_form` | 저장소 초과분 6종 |

**판정**: 원 문서가 "가능하면 구조화합니다"라고 권한 것은 **이미 되어 있고 더 나아가 있다.** Week 3에서 이 항목을 새로 만들면 중복이다.

#### 11-5. AI 품질 Gate 8축 ↔ 저장소 판정 장치

| 원 문서 축 | 판정 | 근거 |
|---|---|---|
| 수학적 정확성 | **대응 있음** | KPI `수학적 오류율 ≤0.5%`(독립 모델 심판 전수) + Hard Gate `F-Ⅱ`(검수 통과 CU 오류율 >2%) · SymPy 단일 권위 |
| 정답 누설 | **대응 있음** | KPI `힌트 누설률 L1·L2 (무관용 0%)` + Hard Gate `F-Ⅴ`(의미적 누설 ≥10%) |
| 오개념 판정 정확도 | **대응 있음** | KPI `오개념 op-code 라벨 정확도 ≥85%` + `EOS-60`(done·혼동행렬 FN율) |
| Hint 적절성 | **부분 대응** | 누설(위)은 측정하나 *적절성* 자체의 지표는 내가 찾은 방법으로는 0건 |
| 설명 일관성 | **부분 대응** | `풀이 비약 지적률 ≤10%`(LLM 심판 κ≥0.5)가 인접하나 동일 축은 아니다 |
| 학생 수준 적합성 | **대응 있음** | KPI `난이도 타당도`(깊이 Spearman ρ≥0.5·폭 전문가 순위 ρ≥0.6) |
| hallucination | **대응 있음** | PRM/도구 검증 필수 계약 + `수학적 오류율` |
| Curriculum 범위 이탈 | **대응 있음** | KPI `교육과정 정합률 ≥92%`(블라인드 역매핑) + `MATH-04`(todo·표기 범위 게이트) |

### 11-4b. Week 4 (11/16~11/22) — CMS + QA + Publish

| # | 원 문서 항목 | 판정 | 대응 태스크 / 근거 |
|---|---|---|---|
| W4-1 | Draft→Review→QA→Approved→Published→Deprecated/Rollback | **부분 대응** | Draft~Approved는 있다 — `ADMIN-07`(todo·**P0**·DRAFT→PRESCREENED→APPROVED 전이)·`EOS-62`(done·APPROVED_WITH_EDIT)·`CONT-01`(done·검수 게이트). **Published/Rollback은 약하다** — `EOS-50-publish-gate-pipeline`(todo·미착지)·`ADMIN-12`(todo·`problem.is_published`·`publish_at` **소비처 0건 — 게시 축이 선언만 존재**) |
| W4-2 | CMS 12종 | **부분 대응** | 아래 표 |

**[정정 이력]** 이 표의 1판은 백로그(태스크)만 뒤져 Concept·Problem을 "대응 없음"으로 적었는데 **둘 다 코드에 실재**했다. 부재 판정을 소비자측(실제 라우터)까지 확인하지 않은 오류이며, 아래는 `src/backend/whymath_backend/api/` 실측으로 교체한 2판이다. 측정 명령: 파일별 `@router.(post|put|patch|delete)` 개수.

| 원 문서 CMS | 판정 | 대응 (코드 실측 · main `266c3d55`) |
|---|---|---|
| Curriculum (조회·수정·버전) | **부분 대응** | `api/curricula.py` — 읽기 5 · **쓰기 0**. 조회만 되고 수정·버전 표면이 없다 |
| Concept (CRUD·관계) | **대응 있음** | `api/concepts.py` — POST·PATCH·DELETE 3건, 전부 `RequireContentAdmin`(`Role.CONTENT_ADMIN`) 게이트 (SEC-07 D1) |
| Skill (Concept 연결) | **대응 없음** | 전용 라우터 0건 |
| Problem (문제·정답·난이도) | **대응 있음** | `api/problems.py` — POST·PATCH·DELETE 3건 |
| Solution (풀이 관리) | **부분 대응** | `api/solution_paths.py` — 읽기만, 쓰기 0 |
| Misconception (Signature·교정) | **대응 없음** | 전용 라우터 0건 |
| Pedagogy (교수전략) | **대응 없음** | 전용 라우터 0건 |
| Content (설명/힌트) | **대응 없음** | 전용 라우터 0건 |
| QA (검수상태) | **부분 대응** | `ADMIN-07`(todo·**P0**·검수 큐 UI·Phase B 진입점) — **미착지** |
| Version (변경이력) | **대응 있음** | `EOS-49`(done·ConceptVersion 계약·VersionHeader 공유) |
| Publish (배포) | **부분 대응** | `EOS-50`(todo·미착지)·`ADMIN-12`(todo·`is_published` 소비처 0건) |
| Rollback (이전 버전 복구) | **대응 없음** | 내가 찾은 방법으로는 0건 |

**집계**: 대응 있음 3 · 부분 대응 4 · 대응 없음 5.

**중요한 단서 — 표면은 있으나 운영자 화면이 아니다**: Concept·Problem 쓰기는 `/v1/admin/*`이 아니라 `/v1/concepts`·`/v1/problems`에 있고, `ADMIN-05`가 적었듯 **`/v1/admin/*` 라우터는 0건**이다(내 실측도 0건). 즉 *API는 있고 CMS는 없다* — 콘텐츠 운영자가 쓰려면 `ADMIN-06`(백오피스 웹 셸)·`ADMIN-04`(모듈 레지스트리)가 필요한데 **둘 다 미착지**다. 원 문서가 Week 4에서 요구하는 것은 API가 아니라 **개발자 없이 쓸 수 있는 화면**이므로, 이 구분이 판정의 핵심이다.

---

## §12. 대조표 ⑤ — 측정 지표 7종 ↔ 저장소 KPI 정본

### 12-1. 핵심 발견 — 두 지표군은 **측정 평면이 다르다**

1회차 §7-②는 "7종을 그냥 얹으면 KPI 정본이 셋이 된다"고 적었다. 원 문서를 받고 보니 **더 정확한 진단은 다르다** — 저장소 KPI 12종은 **생산(저작) 공정**을 재고, 원 문서 7종은 **제품 완성도**를 잰다. 겹치는 축이 거의 없다.

| 저장소 KPI 정본 12종 (`ops/validation_scorecard.py`) | 재는 것 |
|---|---|
| HIT(CU당 인간 개입 ≤4분) · 자동검증 1차 통과율 ≥85% · 재작업률 ≤15% · 처리량 ≥30 CU/h · 단위 비용 ≤250원/CU · 실패 유형 분포 ≥60% | **공정 6종** — 콘텐츠를 *얼마나 싸고 빠르게 만드는가* |
| 수학적 오류율 ≤0.5% · 교육과정 정합률 ≥92% · 오개념 라벨 정확도 ≥85% · 풀이 비약 지적률 ≤10% · 난이도 타당도 · 힌트 누설률 0% | **내용 6종** — 만든 콘텐츠가 *맞는가* |

### 12-2. 7종 개별 대조

| # | 원 문서 지표 | 목표 | 판정 | 저장소 대응 |
|---|---|---|---|---|
| ① | Curriculum Coverage | ≥98% | **관측 있음·판정 없음** | `CUR-02`·`EOS-82`(done)·`S4-03`(todo)가 커버리지를 **관측**한다. 98% 임계를 exit code로 거는 게이트는 0건 |
| ② | Concept Completeness | ≥95% | **대응 없음** | 1차·2차 모두 0건. 인접한 것은 `ARCH-43`(done)인데 그것은 오히려 **"필드 채움 검사는 배제 선언한 과목도 통과한다(반증력 0)"**고 판정한 태스크다 — 즉 저장소는 이 방식의 지표를 *반증력 없음*으로 이미 한 번 기각했다. **7종 중 가장 주의가 필요한 항목** |
| ③ | Problem Coverage | ≥95% | **부분 대응** | `EOS-52`(done)가 앵커 8단원 문항 코퍼스를 실측. Skill별 문항 확보율을 상시 재는 장치는 0건 |
| ④ | Solution QA Pass | ≥99% | **대응 있음 (더 엄격)** | 저장소 `수학적 오류율 ≤0.5%` = **99.5% 통과**. 원 문서 99%보다 높다. 측정 근거는 `EOS-60`(done·혼동행렬) |
| ⑤ | Learning Loop Success | ≥95% | **부분 대응** | `EOS-22`(done·Gate 2 판정 — **무개입 연속 3루프 미충족으로 FAIL**)·`EOS-81`·`EOS-86`(done). E2E 완료*율*을 백분율로 재는 장치는 0건 — 현재는 **연속 N루프 통과/실패**의 이진 판정이다 |
| ⑥ | Critical Defect | 0 | **대응 있음** | Hard Gate `F-Ⅰ~F-Ⅴ` — 하나라도 triggered면 `NO_GO`. 원 문서의 "0"과 같은 뜻 |
| ⑦ | Graph Connectivity Coverage (추천) | — | **관측 있음·판정 없음** | `CUR-05`(done)·`CUR-06`(todo) — **학교급 경계 통과 엣지 20/2210 = 0.9%·고→대 0**. 원 문서가 "이 값이 높아야 Education OS"라고 한 바로 그 지표이며, **실측값이 매우 낮다** |

### 12-3. 편입 판정 — 여전히 Kiki 결정 사항

측정 평면이 다르므로 "정본이 셋"이 아니라 **"정본 12종(생산) + 신설 7종(제품)"의 2평면 구조**가 자연스럽다. 다만 ④는 이미 더 엄격한 축이 있어 **중복이고**, ②는 저장소가 반증력 없음으로 기각한 방식이다. 그래서 7종을 그대로 얹으면 안 된다 — **①③⑤⑦ 4종 신설 · ④ 기존 흡수 · ⑥ 기존 흡수 · ② 재설계**가 내 권고이나, 이것은 등재가 아니라 제안이며 판정은 Kiki 몫이다.

---

## §13. 대조표 ⑥ — Release Gate A~E ↔ 저장소

**표기 주의**(§7-③ 유지): 저장소에는 이미 "Gate 0 A~E"(Phase 0)와 `G0~G5`(선언 부록 E)가 있다. 아래는 전부 **`Phase 3 Release Gate X`**를 줄여 쓴 것이며, 등재 시에는 전체 표기가 필요하다.

| Gate | 원 문서 요구 | 판정 | 근거 |
|---|---|---|---|
| **A** 학생 폐쇄루프 | 진단→추천→학습→문제→답안→채점→오개념→Hint/Tutor→Mastery→다음추천 **10단, 사람이 DB 미수정** | **부분 대응** | 루프 자체는 있다 — `EOS-100`·`EOS-105`·`EOS-109`·`EOS-116`(done). 무개입 판정은 `EOS-22`가 **FAIL**(무개입 연속 3루프 미충족). 시나리오 회귀는 `EOS-119`(진행 중·`SCENARIO-001~010`) — 다만 `EOS-120`이 **PED-36과 중복 소유**를 지적 중 |
| **B** 콘텐츠 | 대표 과정 주요 Curriculum/Concept/Skill이 출시 기준 이상 | **부분 대응** | `EOS-52`(done·앵커 8단원 실사)·`EOS-95`·`EOS-79`(done). **"출시 기준"의 수치가 저장소에 없다** — §12-①②③이 전부 판정 장치 부재 |
| **C** 운영 (수정→QA→승인→Publish) | 콘텐츠 오류를 개발자 없이 고쳐 배포 | **부분 대응** | 4단 중 *수정*은 API로 가능하다(Concept·Problem CRUD·`CONTENT_ADMIN` 게이트). *QA*는 `ADMIN-07`(todo·P0)·*Publish*는 `EOS-50`(todo) 둘 다 **미착지**, *Rollback*은 0건. 결정적으로 **`/v1/admin/*` 라우터가 0건**이라 "개발자 없이"가 성립하지 않는다(§11-4b). **5개 Gate 중 가장 취약** |
| **D** 데이터 (이벤트) | 8종 이벤트 기록 | **대응 있음 (초과)** | 아래 13-1 |
| **E** EOS Architecture 경계 | Math 로직이 Core에 침투하지 않음 | **대응 있음** | `lint-imports` 아키텍처 계약이 CI에서 집행 · `ARCH-43`(done·과목 중립성 반증 가능 검사)·`ARCH-48`·`ARCH-59`(done·LLM↔상태 권위 경계 AST 가드)·`EOS-92`(done·Physics 프로브) |

### 13-1. Gate D 이벤트 8종 ↔ 저장소 카탈로그 실측

저장소 카탈로그 = `l2/learning_event_trace.py` **19종**.

| 원 문서 이벤트 | 저장소 | 판정 |
|---|---|---|
| `learning_started` | `diagnostic_started` · `learner_state_created` | **이름만 다름** — 역할 대응 |
| `concept_viewed` | `concept_selected` + `content_viewed` | **둘로 분화** — 역할 대응 |
| `problem_attempted` | `problem_attempted` | 정확히 일치 |
| `answer_submitted` | `answer_submitted` | 정확히 일치 |
| `misconception_detected` | `misconception_detected` | 정확히 일치 |
| `hint_requested` | `hint_requested` (+`hint_provided`) | 일치 + 초과 |
| `mastery_updated` | `mastery_updated` (+`skill_mastery_updated`) | 일치 + 초과 |
| `recommendation_generated` | `recommendation_generated` | 정확히 일치 |

**판정: 8/8 역할 대응** (이름 일치 6 · 이름 상이 2). 저장소 초과분 11종(`assessment_failed`·`ability_measured`·`skills_resolved`·`verification_recorded`·`stuck_detected`·`visualization_interacted`·`diagnostic_completed` 등).
**단서**: `learning_started`·`concept_viewed`를 이름으로 grep하면 **0건**이다. 이름으로 부재를 판정했으면 "이벤트 2종 미구현"이라는 오판정이 나왔을 자리다.

---

## §14. 2회차 산출 — 4종

### 14-1. 산출 ① 등재·수정된 태스크

**0건.** 이 회차는 대조 전용이다(§10-2). 1회차 산출(신규 11 + amend 1 + 게이트 1)은 §5 그대로이며 변경하지 않았다.

### 14-2. 산출 ② 원 문서 항목 ↔ 태스크 ID 대조표

**주 항목 39건 + 세부 대조표 36행.** 집계는 기계로 셌다(표별 행 수·판정 키워드 파싱 — 수작업 계수는 1차에 틀렸다).

**주 항목 39건**

| 표 | 행 | 대응 있음 | 부분 대응 | 대응 없음 |
|---|---|---|---|---|
| §11-1 Week 1 | 17 | 12 | 5 | 0 |
| §11-2 Week 2 | 5 | 2 | 2 | 1 |
| §11-3 Week 3 | 3 | 2 | 1 | 0 |
| §11-4b Week 4 | 2 | 0 | 2 | 0 |
| §12 지표 7종 | 7 | 2 | 4 | 1 |
| §13 Gate A~E | 5 | 2 | 3 | 0 |
| **합계** | **39** | **20 (51%)** | **17 (44%)** | **2 (5%)** |

**세부 대조표 36행** (주 항목 안을 더 쪼갠 것 — 위 39건과 **중복 계상하지 않는다**)

| 표 | 행 | 요지 |
|---|---|---|
| §11-4 Tutor output 스키마 | 8 | 원 문서 제안 8필드 전건 대응 + 저장소 초과 6종 |
| §11-5 AI 품질 Gate 8축 | 8 | 있음 6 · 부분 2 · 없음 0 |
| §11-4b CMS 12종 | 12 | 있음 3 · 부분 4 · **없음 5** (코드 실측 2판) |
| §13-1 Gate D 이벤트 8종 | 8 | **8/8 역할 대응**(이름 일치 6 · 상이 2) |

**주 항목 '대응 없음' 2건**: W2-1(Concept당 문제 6종) · 지표②(Concept Completeness). **이 둘이 원 문서가 요구하는 것 중 저장소에 아무 대응도 없는 전부**다.

**세부의 '대응 없음' 5건**은 전부 CMS다 — Skill·Misconception·Pedagogy·Content의 관리 표면과 Rollback. 여기에 **`/v1/admin/*` 라우터 0건**(운영자 화면 부재)이 겹쳐 Gate C를 '부분 대응'에 묶어 두고 있다.

**판정의 무게**: '대응 없음'이 2건뿐이라는 것은 낙관의 근거가 아니다. **'부분 대응' 17건(44%)의 대부분이 "관측은 하는데 판정(게이트)이 없다" 또는 "태스크는 있는데 미착지"**다 — 예: Content Coverage Rate는 관측하지만 95% 임계를 exit code로 거는 장치가 0건이고, CMS의 그릇인 `ADMIN-04`·`ADMIN-06`은 전부 `todo`다. Phase 3의 실제 작업량은 '없음 2건'이 아니라 **'부분 17건을 닫는 것'**에 있다.

### 14-3. 산출 ③ Not Now ∩ 진행중

§3(1회차)에서 갱신 없음 — 이 회차는 Not Now 태스크를 건드리지 않았다. `NOTNOW-01~12`는 전건 `todo`·P3·게이트 `G-not-now-v1-release-recheck`(pending) 부착 상태 유지.

### 14-4. 산출 ④ 등재할 수 없었던 항목과 이유

| # | 항목 | 사유 |
|---|---|---|
| ① | `P3-01~P3-14` 대조 | 세트 02~15/20 **여전히 미첨부**. §7-④ 그대로 |
| ② | Week 1~4 작업의 **신규 태스크 등재** | 입력은 확보했으나 §10-2 — `P3-01~P3-14`와 중복 등재 위험. 등재 자체를 보류한 것이지 판정 불가가 아니다(1회차와 다른 사유) |
| ③ | 지표 7종 편입 | §12-3 — 2평면 구조·중복 2종·재설계 1종 판정이 선행. Kiki 결정 |
| ④ | Gate A~E 등재 | §13 표기 주의 + Gate C 실질 부재. 이름 확정이 선행 |
| ⑤ | 대표 과정 범위 **동결** | §11 W1-2 — 실사(`EOS-52`)는 있으나 동결 행위의 소유자가 없다. `P3-01`의 몫 |
| ⑥ | 11/22 일정 충돌 해소 | §7-⑥ 그대로 — 저장소 `G3`와 같은 날짜·다른 판정 대상 |

### 14-5. 새로 드러난 쟁점 — Phase 번호 체계 충돌

원 문서는 **"현재 시점인 2026년 8월 27일"**을 전제하고 Phase 2를 9/28~10/25로 잡는다. 그런데 저장소는 2026-09-19에 이미 Phase 2 Gate 2를 판정했다(`docs/reviews/eos_phase2_gate2_judgment_2026-09-19.md` = FAIL). 원 문서 일정표대로면 그 시점에 Phase 2는 **아직 시작 전**이다.

두 해석이 가능하고 **나는 어느 쪽인지 판정하지 못했다**:
- ⓐ 저장소가 원 문서 일정보다 앞서 있다(Phase 2를 5주 일찍 끝내고 판정)
- ⓑ 원 문서의 "Phase 2"와 저장소의 "Phase 2"가 서로 다른 체계다

이것이 확정되지 않으면 **§11~§13 대조표 전체가 엉뚱한 단계에 매핑될 수 있다.** 2회차가 대조만 하고 등재하지 않은 또 하나의 이유다. `G2` 이름 충돌 3회차(선언 §1.3) 선례가 있으므로 가볍게 볼 쟁점이 아니다.

---

## §15. 2회차 완료 판정 — **여전히 부분 충족**

| 축 | 1회차 | 2회차 | 근거 |
|---|---|---|---|
| Not Now 12종 보류 등재 | 충족 | 충족(유지) | §5·§2-2 |
| 원 문서 각 항목 ↔ 태스크 ID 대조표 | 미충족 | **충족** | §11~§13 **주 항목 39건 + 세부 36행** 전수 · 판정 기준 main `266c3d55` |
| `P3-01~P3-14` 대조 | 미충족 | **미충족** | 미첨부 |
| 분해 단위 신규 등재 | 미충족 | **보류** | §10-2 — 불가가 아니라 **의도적 보류** |

**3회차 재실행 조건**: `P3-01~P3-14`(세트 02~15/20) 첨부. 그때 할 일은 ⓐ 내 주 항목 39건 열거와 Kiki의 14개 분해 단위를 대조 ⓑ §14-2의 **대응 없음 2건 · 부분 대응 17건 · CMS 세부 없음 5건**을 분해안이 덮는지 확인 ⓒ 안 덮는 것만 신규 등재. `done` 처리는 그때 판정한다.

---

## §16. Kiki 결정 수용 (2026-09-22) — 확정 2건 · 미결 2건

Kiki가 "결정 수용"으로 회신했다. **내가 권고를 드린 항목만 확정으로 옮긴다** — 권고 없이
쟁점만 제기한 항목은 수용할 대상이 없었으므로 미결로 남는다. 이 구분을 뭉개면 나중에
"결정된 줄 알았다"가 된다.

### 16-1. 확정 — 측정 지표 7종 편입 방식 (§12-3 권고 그대로)

| # | 원 문서 지표 | 확정된 처분 | 근거 |
|---|---|---|---|
| ① | Curriculum Coverage ≥98% | **신설** | 관측만 있고 임계 판정 장치가 0건(§12-2) |
| ② | Concept Completeness ≥95% | **재설계** | `ARCH-43`이 "필드 채움 검사는 배제 선언한 과목도 통과한다(반증력 0)"로 같은 방식을 이미 기각했다. 원 문서 정의 그대로 신설하면 반증력 없는 지표가 하나 더 생긴다 |
| ③ | Problem Coverage ≥95% | **신설** | `EOS-52`가 앵커 1회 실측했을 뿐 상시 계측이 없다 |
| ④ | Solution QA Pass ≥99% | **기존 흡수** | 저장소 `수학적 오류율 ≤0.5%`(= 99.5%)가 **더 엄격**하다. 별도 신설은 느슨한 정본을 하나 더 만드는 것 |
| ⑤ | Learning Loop Success ≥95% | **신설** | 현재는 "무개입 연속 N루프" 이진 판정이라 백분율 축이 없다 |
| ⑥ | Critical Defect 0 | **기존 흡수** | Hard Gate `F-Ⅰ~F-Ⅴ`가 하나라도 triggered면 `NO_GO` — 같은 뜻 |
| ⑦ | Graph Connectivity Coverage | **신설** | 원 문서가 "이 값이 높아야 Education OS"라 한 축이며 실측이 0.9%로 낮다(`CUR-06`) |

**구조**: 정본이 셋이 되는 것이 아니라 **2평면**이다 — 기존 KPI 12종은 *생산 공정*, 신설
4종(①③⑤⑦)은 *제품 완성도*. 신설분은 그 구분을 이름·문서에 명시해 얹는다.

### 16-2. 확정 — Release Gate A~E 표기

**`Phase 3 Release Gate A`~`E`로 전체 표기**한다. 약칭 `Gate A`는 쓰지 않는다 — 저장소에
이미 Phase 0의 "Gate 0 A~E"와 선언 부록 E의 `G0~G5`가 있고, `G2` 이름 충돌이 3회차였다
(선언 §1.3). 이 문서의 §13 표도 그 약속 아래 읽는다.

### 16-3. 미결 — 수용으로 닫히지 않는 2건

| # | 쟁점 | 왜 미결인가 |
|---|---|---|
| ③ | 종료일 11/22 충돌 | 저장소 `G3`(폭 확장·붕괴지점)와 **같은 날짜에 다른 판정 대상**이라는 사실만 보고했고 **어느 쪽을 옮기자는 권고는 드리지 않았다.** 일정 우선순위는 세션이 정할 사안이 아니다 |
| ④ | Phase 번호 체계 충돌 | §14-5 — 원 문서는 Phase 2를 9/28~10/25로 잡는데 저장소는 2026-09-19에 Phase 2 Gate 2를 판정했다(FAIL). ⓐ저장소가 앞선 것인지 ⓑ서로 다른 체계인지 **내가 판정하지 못했다**. 판정 없이 수용하면 §11~§13 대조표 전체가 엉뚱한 단계에 매핑될 수 있다 |

> **→ 4회차(2026-09-23) 처분 완료.** 위 ③④는 **Kiki 결정 2건**으로 닫혔다 — ③(종료일 충돌)은 `ⓐ 저장소 G3 우선 · P3-G4를 11/15로 옮겨 P3-G3와 통합`, ④(Phase 번호 체계)는 `ⓑ Phase 2 Gate 2 재판정 즉시 착수`다. 이 표는 2회차 시점의 **미결 기록**으로 보존하고, 집행 결과는 §22에 적는다. 이 표기가 "판정"이 아니라 **결정 기록**인 이유: ③④는 세션이 판정할 사안이 아니라 Kiki가 정할 사안이었고(위 표의 사유 열), 결정 주체가 바뀌었을 뿐이다.

### 16-4. 신설 4종의 등재는 아직 하지 않았다

①③⑤⑦의 **처분은 확정됐으나 태스크 등재는 3회차로 미룬다.** 사유는 §10-2와 같다 —
`P3-01~P3-14`가 그 4종을 이미 자기 단위로 쪼개 뒀을 수 있고, acceptance는 append 전용이라
중복 등재를 되돌릴 수 없다. **다만 이 유예는 무기한이 아니다**(만료 없는 유예 금지):
`P3-01~P3-14`가 존재하지 않는 것으로 확인되면 그 즉시 내 분해로 등재한다.

---
---

# 3회차 (2026-09-22) — 기준 분해안 수령 후 등재

> **판정 기준: main `5afc1c34`** · 백로그 783 → **798건**(+15) · 게이트 62 → **67건**(+5)
> **입력 완결**: 2026-09-22 04:38Z 에 `P3-00a~P3-14` + 판정 회차 `P3-G1~G4` **전 20회차 병합본**이 도착했다.
> 저장소 보존 = `docs/strategy/phase3_math_eos_completion_instruction_set.md` (sha256 `f02dcc45e8aff7e8bfa77a3b67504528183af799970311621c3a645efaa7404d` · 107,735자).
> 이로써 `EOS-128` acceptance ①이 요구한 입력 2종이 모두 저장소에 있다.

## §18. 분해안의 실제 형태 — 14가 아니라 20이다

1·2회차는 "`P3-01~P3-14`"라고 적었으나 실제 세트는 **착수 단위 15 + 판정 회차 5 = 20회차**다.

| 구분 | 회차 | 처분 |
|---|---|---|
| 착수 전 | `P3-00a` · `P3-00b` | `P3-00a` = 이 태스크(`EOS-128`) · `P3-00b` = 신규 |
| W1 (10/26~11/1) | `P3-01`~`P3-03` | 신규 3 |
| W2 (11/2~11/8) | `P3-04`~`P3-07` | 신규 4 |
| W3 (11/9~11/15) | `P3-08`~`P3-10` | 신규 3 |
| W4 (11/16~11/22) | `P3-11`~`P3-14` | **amend 1**(`EOS-50`) + 신규 3 |
| 판정 회차 | `P3-G1`~`P3-G4` | **게이트 4건**(태스크 아님) |
| 상시 | `S-01`~`S-03` | 태스크 미등재 — 지시문 차원의 규율이고 저장소 집행은 기존 가드가 소유(§18-3) |

## §18-1. 회차 ↔ 태스크 ID 대조표 (Kiki 실행용)

각 회차 세션이 **첫 행위로 `start` 할 태스크 ID**다. 지시문 파일 번호 순서 그대로다.

| 파일 | 회차 | 착수할 태스크 ID | 처분 |
|---|---|---|---|
| 01 | `P3-00a` | `EOS-128-phase3-plan-backlog-conversion` | 기존 (이 태스크) |
| 02 | `P3-00b` | `P3-00-phase2-acceptance-check` | 신규 |
| 03 | `P3-01` | `P3-01-scope-freeze` | 신규 |
| 04 | `P3-02` | `P3-02-coverage-instruments` | 신규 |
| 05 | `P3-03` | `P3-03-coverage-fill` | 신규 |
| 06 | `P3-G1` | (게이트) `G-p3-g1-week1` | 게이트 |
| 07 | `P3-04` | `P3-04-problem-metadata-and-slots` | 신규 |
| 08 | `P3-05` | `P3-05-triangle-density` | 신규 |
| 09 | `P3-06` | `P3-06-wrong-answer-remediation-pipeline` | 신규 |
| 10 | `P3-07` | `P3-07-solution-qa-machine-verification` | 신규 |
| 11 | `P3-G2` | (게이트) `G-p3-g2-week2` | 게이트 |
| 12 | `P3-08` | `P3-08-tutor-context-builder` | 신규 |
| 13 | `P3-09` | `P3-09-tutor-output-schema` | 신규 |
| 14 | `P3-10` | `P3-10-ai-quality-eval-suite` | 신규 |
| 15 | `P3-G3` | (게이트) `G-p3-g3-week3` | 게이트 |
| 16 | `P3-11` | **`EOS-50-publish-gate-pipeline`** | **기존 amend** |
| 17 | `P3-12` | `P3-12-cms-minimal-screens` | 신규 |
| 18 | `P3-13` | `P3-13-learning-events-and-boundary-recheck` | 신규 |
| 19 | `P3-14` | `P3-14-phase3-metrics-cli` | 신규 |
| 20 | `P3-G4` | (게이트) `G-p3-g4-release` | 게이트 |

**ID 표기 주의 2건**: ⓐ `P3-00b`의 태스크 ID는 `P3-00-...`이다 — 대장 ID 형식이 숫자만 받아 `00b`를 쓸 수 없었다 ⓑ `P3-11`에는 `P3-` 태스크가 **없다**. `EOS-50`이 그 회차의 소유자다(아래 §18-2).

## §18-2. 신규 등재하지 않은 3회차와 그 이유

| 회차 | 처분 | 근거 |
|---|---|---|
| `P3-11` 콘텐츠 상태 워크플로우 | **`EOS-50` amend** | `EOS-50`(todo·미claim)이 이미 Draft→Publish 검증 게이트를 소유한다. 신규 등재하면 같은 Publish 축의 두 번째 사본이 된다. Rollback·전이 데이터 선언·미정의 전이 RED 3축을 acceptance ⑨~⑫로 덧붙였다 |
| `P3-12` CMS 12종 | **신규 + 선행 4건** | 세 태스크(`ADMIN-04`·`ADMIN-06`·`ADMIN-07`)가 그릇을 나눠 가진다. 어느 하나에 amend 하면 나머지 둘과의 관계가 대장에서 사라지므로, 통합 완성 축을 신규로 두고 셋 + `EOS-50`을 선행으로 걸었다 |
| `P3-13` 이벤트·경계 | **신규 + 선행** | 경계 축은 `EOS-117`이 소유하는데 **타 세션이 in_progress**다. 남의 in-flight 작업에 범위를 얹지 않기 위해 amend 대신 선행으로 걸었다 |

## §18-3. 상시 지시문 `S-01`~`S-03`을 태스크로 등재하지 않은 이유

`S-01`(Not Now·금지 변경 차단)·`S-02`(범위 이탈 차단)·`S-03`(주간 마감 보고)은 **세션 운영 규율**이지 착수 단위가 아니다. 저장소 집행은 이미 있는 것이 가진다 — Not Now 12종은 `NOTNOW-01~12` + 게이트 `G-not-now-v1-release-recheck`(1회차 산출), 금지 변경 5종은 좌석 계약·스키마 프로브·`entry_gate`·`NOTNOW-08`이 덮는다(2회차 §11-1). 다만 **금지5(대규모 UI 구조 변경)만 기계 집행이 없다** — `HARN-103`(기능 동결 규칙·todo)이 소유자이나 미착지다.

## §19. 등재 결과 — 신규 15 · amend 1 · 게이트 5

**신규 태스크 15건**: `P3-00` · `P3-01` · `P3-02` · `P3-03` · `P3-04` · `P3-05` · `P3-06` · `P3-07` · `P3-08` · `P3-09` · `P3-10` · `P3-12` · `P3-13` · `P3-14` (Phase 3 14건) + `HARN-136`(사고 대책 1건 — §20).
**기존 amend 1건**: `EOS-50-publish-gate-pipeline`(= `P3-11`).
**게이트 5건**: `G-p3-entry-gate2-pass`(진입) · `G-p3-g1-week1` · `G-p3-g2-week2` · `G-p3-g3-week3` · `G-p3-g4-release`.

선행은 산문이 아니라 `depends_on`으로 걸었다(`selector`는 notes를 읽지 않는다). 주차 경계는 게이트로, 주차 내부는 선행 체인으로 잇는다 — 지시문의 시작 조건 표기와 1:1이다.

### 19-1. 주입 검증 — 무엇이 실제로 막는가

"착수 후보에 P3가 0건"은 그 자체로 증거가 아니다. `P3-00`에 2×2 주입을 걸어 차단 주체를 갈랐다(`cp` 백업 경유 · 원복 바이트 동일 단언 내장).

| 주입 | 착수 후보 등장 | 해석 |
|---|---|---|
| A 정상(게이트+선행) | False | — |
| B 게이트만 제거 | False | 선행이 막는다 |
| C **선행만 제거** | **False** | **게이트가 단독으로 막는다** |
| D 둘 다 제거 | **True** | 대조군 — 조회 자체는 유효(총 157건 반환) |

**C가 결정적이다.** 1차 주입은 B만 해서 "게이트가 막는다"를 확인하지 못했고, 그 상태로 적었으면 차단 주체를 틀리게 지목한 것이 된다.

## §20. 이번 회차에 낸 사고 1건 — `git checkout --`로 이벤트 대장 유실

ID 체계 시험용 태스크를 지우면서 `git checkout -- backlog/events/`를 실행해 **이 세션의 미커밋 이벤트 약 10건이 소실**됐다(게이트 5건 add · `HARN-134` start/unblock · 시험 태스크 add/cancel). 파일이 HEAD 기준 90줄로 되돌아갔다. 실체(`gates.yaml` 5건·신규 문서)는 살아남아 피해는 **감사 추적 단절**에 그쳤다.

**동일 유형 2회차**다 — 1회차는 2026-08-10 `OPS-24`로, 뮤테이션을 같은 명령으로 원복하다 미커밋 구현분 +59/-6을 잃었다. 그때 대책이 산문 규칙이었고 그 문면이 '뮤테이션 원복'으로 좁아 **일반 정리 작업에는 적용되지 않는 것처럼 읽혔다.** 그래서 이번 대책은 코드다 — `HARN-136`(PreToolUse 훅으로 git 원복 계열을 차단하되, 탐지 기준은 "git 원복 명령"이 아니라 "**그 경로에 잃을 것이 있는가**").

무증상성이 핵심이다: 명령은 exit 0이고 `git status`에서 파일이 조용히 사라질 뿐이다. 직후 `wc -l` 대조를 했기 때문에 발견했다.

## §21. 3회차 완료 판정 — acceptance ①~⑤

| 축 | 판정 | 근거 |
|---|---|---|
| ① 원 문서 각 항목 ↔ 태스크 ID 대조표 | **충족** | 2회차 §11~§13(주 39건+세부 36행) + 3회차 §18-1(20회차 ↔ 태스크 ID) |
| ② 중복 실측 | **충족** | 회차마다 역할 정규식 + 코드 실측. 겹친 3건은 신규 등재하지 않았다(§18-2) |
| ③ `backlog.py add`로만 등재 · 선행은 `--depends` | **충족** | 번호 추론 0건(`HARN-135` 충돌 시 CLI 제안 번호 사용) · 선행 전건 `--depends` · `audit-deps` green |
| ④ Not Now 12종 보류 등재 | **충족(1회차)** | `NOTNOW-01~12` + `G-not-now-v1-release-recheck` 유지 |
| ⑤ 산출 4종 | **충족** | ①등재 목록 §19 ②대조표 §18-1 ③Not Now ∩ 진행중 §3(변동 없음) ④미귀속 §21-1 |

### 21-1. 여전히 등재하지 않은 것

| # | 항목 | 사유 |
|---|---|---|
| ① | 종료일 11/22 ↔ 저장소 `G3` 충돌 | **Kiki 미결**(§16-3). 일정 우선순위는 세션이 정할 사안이 아니다 |
| ② | Phase 번호 체계 충돌 | **Kiki 미결**(§14-5). 다만 분해안 수령으로 범위가 좁아졌다 — 지시문이 "Phase 2 Gate 2(10/25) PASS"를 명시하므로 원 문서의 Phase 2와 저장소의 Gate 2는 **같은 것**으로 읽힌다. 남은 불일치는 *날짜*(저장소가 5주 이르다)이지 *체계*가 아닐 가능성이 높다 — 그러나 이것은 **읽어서 그렇게 보인다**이지 실측이 아니다 |
| ③ | 금지5 대규모 UI 구조 변경의 기계 집행 | `HARN-103`(todo·미착지)이 소유자다. 신규 등재하면 두 번째 사본이 된다 |
| ④ | 상시 지시문 `S-01`~`S-03` | §18-3 — 세션 운영 규율이지 착수 단위가 아니다 |

> **→ 4회차(2026-09-23) 처분 결과.** ①②는 **Kiki 결정 2건으로 닫혀 처분 완료**됐다(③④는 승계 유지). 이 표는 3회차 시점의 기록으로 보존하고, 집행 증거는 §22에 적는다.
>
> | # | 4회차 처분 | 집행 증거 |
> |---|---|---|
> | ① | **처분 완료** — 저장소 `G3` 우선 · P3-G4를 11/15로 옮겨 P3-G3와 통합 | 게이트 `G-p3-w3-release-merged` 신규(11/15·`kind: decision`·`assignee: kiki`), `G-p3-g3-week3`·`G-p3-g4-release` **waived**(요건 승계) — §22-1 |
> | ② | **처분 완료** — Phase 2 Gate 2 **즉시 재판정 착수** | 태스크 `EOS-130-phase2-gate2-rejudgment` 신규 등재(`eos_priority: P0`·`depends_on: EOS-21`) — §22-2. 단 §7 ⓑ가 "실측 아님"으로 남긴 *체계 vs 날짜* 축은 **이 회차도 닫지 않았다** |
> | ③ | **승계 유지** | `HARN-103`(todo·미착지)이 소유자 — 신규 등재하면 두 번째 사본 |
> | ④ | **승계 유지** | 세션 운영 규율 — 착수 단위 아님 |

**`EOS-128`은 이제 `done` 처리 가능한 상태다** — acceptance ①~⑤가 전부 충족됐고, 미귀속 4건은 전부 "등재할 수 없는 이유"가 명시된 것들이다. 다만 ①②가 Kiki 결정이므로 done 판정 자체도 Kiki 확인 후에 한다.

---

**작성**: 2026-09-22 · `EOS-128-phase3-plan-backlog-conversion` 3회차 · 세션 `claude/compassionate-hypatia-chznsu` · 판정 기준 main `5afc1c34`

---
---

**작성**: 2026-09-22 · `EOS-128-phase3-plan-backlog-conversion` 2회차 · 세션 `claude/compassionate-hypatia-chznsu` · 판정 기준 main `266c3d55`
---

# 4회차 (2026-09-23) — Kiki 결정 2건 집행 + `EOS-128` 종결

> **판정 기준: main `1671b9d4d88434a3d93bfcaa93d52c34738bd55e`** · 검증 시점 `origin/main` = `ade56c4845c912aa9892c4e7343121d7becc99d4`(타 세션 push로 전진)
> 백로그 **819건** · 게이트 **75건** · 트랙 3건
> **앞 세 회차(§0~§21)의 판정은 그 시점의 것이며 갱신하지 않았다.** §16-3과 §21-1에는 이 회차의 처분을 가리키는 포인터만 달았다.
> 상세 검증 보고서 = `docs/reviews/p3_00a_trunk_verification_2026-09-23.md`

## §22. 이 회차의 성격 — 검증이지 신규 등재가 아니다

지시문 `01_P3-00a`는 이 작업을 미착수로 전제하지만, trunk 실측 결과 **1~3회차에 걸쳐 이미 착지**했다(PR #1233 · PR #1276). 재실행은 지시문 자신의 acceptance ②(중복 실측)를 위반하므로, 이 회차는 재실행 대신 셋을 했다:

1. **trunk 기준 검증** — `EOS-128` acceptance ①~⑤를 **원 문면**과 1:1 재대조(§21의 자기 판정을 신뢰하지 않았다) + 3회차 산출물 30건 실재 전수 검사(**누락 0건**)
2. **Kiki 결정 2건 집행** — 아래 §22-1·§22-2
3. **`EOS-128` 종결** — §22-5

## §22-1. ⓐ 처분 — 종료일 충돌: 저장소 `G3` 우선 · P3-G4를 11/15로 옮겨 P3-G3와 통합

§16-3 ③이 "일정 우선순위는 세션이 정할 사안이 아니다"로 Kiki 미결로 남긴 건이다. 2026-09-22 Kiki 결정을 집행한 결과:

| 게이트 | 처분 |
|---|---|
| `G-p3-w3-release-merged` | **신규**(11/15) — Week 3 판정 + Phase 3 Release Gate A~E 판정을 한 회차로 통합. `kind: decision` · `assignee: kiki` · `remind_after_days: 55` |
| `G-p3-g3-week3` | **waived** — 요건은 통합 게이트 (가)축으로 **승계**(폐기 아님) |
| `G-p3-g4-release` | **waived** — 요건은 통합 게이트 (나)축으로 **승계**(폐기 아님) |

`gates` 서브커맨드는 `list/add/clear/waive/show` 5종이고 **정정 CLI(`amend`)가 없다.** 게이트 날짜·문면은 제목 문자열에만 있어, 손편집 금지 규율 아래에서 `waive + add`가 유일한 경로였다. Waive 사유에 "요건은 폐기가 아니라 이동"을 적어 보존했다.

**부수 결과(정직 기록)**: Phase 3 실효 기간이 10/26~11/15로 줄어 Week 4 작업이 압축된다 — **구현은 11/14까지 끝나야 한다.** 이것이 수용 불가라면 Release 판정을 11/22로 되돌리는 것이 유일한 대안이며, 그것은 Kiki 결정을 뒤집는 것이므로 세션이 정하지 않았다.

## §22-2. 순환 결함 1건 — 병합이 만든 자기 전제 (집행 중 발견)

통합 게이트의 Release 축은 Week 4 작업 묶음(`P3-11`~`P3-14`)이 완료된 시점의 판정을 전제하는데, 그 묶음의 첫 작업(`EOS-50` = P3-11)이 통합 게이트를 `requires_gates`로 걸고 있었다.

즉 11/15에 Release 축을 판정하려면 P3-11이 완료돼 있어야 하는데, P3-11은 그 게이트가 통과해야 착수된다 — **자기 자신을 전제로 요구하는 순환**이라 통합 게이트를 정상 경로로 닫을 수 없다. 원 게이트 2건에는 이 순환이 없었다: Week 3 게이트는 Week 4의 *진입* 조건, Release 게이트는 Week 4 *이후* 판정이라 역할이 분리돼 있었다. **병합이 진입 조건과 완료 요건을 같은 게이트에 겹치게 했다.**

`EOS-50`의 `requires_gates`에서 통합 게이트를 떼어 순환을 끊었다. Week 4 착수 경계는 `depends_on`이 이미 지킨다(`P3-10-ai-quality-eval-suite` = Week 3 작업 완료가 선행). **게이트가 하던 일을 의존 체인이 하므로 요건 손실은 없다.**

## §22-3. ⓑ 처분 — Phase 2 Gate 2 FAIL: 즉시 재판정 착수

**재판정 태스크는 실재하지 않았다.** 이름으로 찾으면 0건이고 기능으로 찾으면 두 태스크가 나오므로, 그 둘이 재판정이 *아님*을 확인하는 것이 실측의 본체였다:

- `EOS-22-gate2-final-judgment` — `done` · 최종 **FAIL**. **1회차 판정**이고 후속이 없다.
- `P3-00-phase2-acceptance-check` — 제목에 "Gate 2 10조건·KPI 5종 main 기준 재실측"이 있어 재판정으로 오독하기 쉬우나, 그 태스크 자신의 notes가 "**등재는 착수가 아니다 — 착수 전제는 Phase 2 Gate 2 PASS**(게이트 `G-p3-entry-gate2-pass`)"라고 적어 진입 **후** 인수 점검임을 밝히고 있다. 게다가 `requires_gates`로 그 진입 게이트를 걸고 있어 **자기가 증거를 대야 할 게이트에 막힌다** — 재판정 소유자가 될 수 없다.

그래서 신규 등재했다.

| 항목 | 값 |
|---|---|
| ID | `EOS-130-phase2-gate2-rejudgment` |
| 등급 | `eos_priority: P0` — 정의("없으면 12월 검증(G0~G5)이 성립하지 않는다")에 해당. Gate 2는 저장소 `G2`(기준선 확보)의 판정 대상이고 재판정 없이는 `G2` verdict가 2026-09-19 FAIL로 고정된다. P0 예산 50건 대비 비종결 P0 5건이라 교환 불필요 |
| 선행 | `depends_on: EOS-21-week-gate-harnesses-never-run-in-ci` — `EOS-22`의 유일 미충족 조건이 "무개입 연속 3루프"이고 그 루프의 판정 하네스 중 3종이 어느 CI 잡에서도 실행되지 않는다 |
| 게이트 | **미부착** — 걸면 자기가 증거를 대야 할 진입 게이트에 막혀 `P3-00`과 같은 순환이 된다. 재판정은 진입 게이트 *앞*에서 도는 유일한 Phase 3 관련 작업이다 |

**등급 불일치를 은폐하지 않고 적는다**: 원 판정 `EOS-22`는 `P2`로 등급돼 있었다. 이 등급은 그와 다르다. 등급 불일치는 맞출 대상이 아니라 보고 대상이다.

**"즉시 착수"의 실현 형태**: `EOS-21`은 `depends_on`·`requires_gates`가 모두 비어 지금 착수 가능하다. 임계 경로는 `EOS-21` 착지 → 재판정이다. 재판정을 배선 상태를 모른 채 돌리면 같은 FAIL을 반복하므로 선행을 걸었고, 그 결과 "즉시"는 재판정 단독으로는 성립하지 않는다 — 이것이 결정의 실제 비용이다.

**게이트 clear는 Kiki 소유다.** `G-p3-entry-gate2-pass`는 `kind: decision` · `assignee: kiki`이고, 재판정 태스크는 그 게이트의 *증거를 만드는* 것이지 닫는 것이 아니다. 에이전트가 `--as kiki`로 대행하지 않았다(거부의 우회 금지).

## §22-4. 이 회차에 낸 사고 1건 — 같은 기능을 두 번 등재 (`HARN-162` 취소)

`gates`에 `amend`가 없음을 실측하고 "게이트 정정 경로가 없다"로 결론해 `HARN-162-gates-amend-missing`을 등재했는데, 등재 직후 harness의 의미 중복 고지가 `HARN-124-gate-title-correction-path`를 similarity 0.15로 지목했다. 확인 결과 **같은 기능을 이미 소유**하고 있었다.

원인은 **부재 판정의 검색 방법 오류**다 — CLI 표면(도구)만 확인하고 태스크 대장(소유자)을 확인하지 않았다. 계보는 3대째다: `HARN-133` → `HARN-135` → `HARN-160`이 등재됐다가 `HARN-124`에 편입·취소됐고, **그 태스크의 notes가 "두 태스크가 각각 경로를 열면 중복이 된다"고 적어 둔 바로 그 중복**을 재생산했다.

`HARN-162`는 `cancel`하고, 새 증거는 버리지 않고 `HARN-124` acceptance ⑧(2026-09-23 통합 집행이 같은 벽에 부딪힌 두 번째 트리거)과 ⑨(이번 중복 등재의 자기 사례화)로 편입했다.

**재발방지대책 형태**: 새 산문 규칙을 만들지 않았다 — 2026-09-20 Kiki 지정 「새 산문 규칙 등재 동결」에 따라 대책은 **태스크**(`HARN-124` ⑨)와 **MEMORY 결정 로그**로만 등재한다.

## §22-5. 이 회차의 대장 변경 내역

| 종류 | ID | 처분 |
|---|---|---|
| add | `EOS-130-phase2-gate2-rejudgment` | ⓑ 집행 |
| add | `G-p3-w3-release-merged` | ⓐ 집행 |
| waive | `G-p3-g3-week3` · `G-p3-g4-release` | ⓐ 집행(요건 승계) |
| amend | `EOS-50-publish-gate-pipeline` | 게이트 재지정 1회 + 순환 해소 1회 |
| amend | `HARN-124-gate-title-correction-path` | 실측 트리거 2건 편입(⑧⑨) |
| cancel | `HARN-162-gates-amend-missing` | 중복 등재 취소 |
| add | `HARN-166-test-local-git-helper-locale-decode` | **별건** — CI 스텝 정합 검증 중 발견한 선재 결함(§22-7 ⑤) |

최종 상태: `validate` green(태스크 819건·게이트 75건·트랙 3건) · `audit-deps` green(위반 0건 · 레거시 그랜드파더 0건 · 소프트 분류 8건).

## §22-6. `EOS-128` 종결 판정

acceptance ①~⑤ 전건 충족(검증 보고서 §1) · 3회차 산출물 30건 실재(§2) · 미등재 잔여 4건 전부 처분 또는 승계 명시(§7).

**`EOS-128`을 `done` 처리한다.** 3회차가 "①②가 Kiki 결정이므로 done 판정 자체도 Kiki 확인 후에 한다"로 남긴 조건은 2026-09-22 Kiki 결정 2건으로 해소됐고, 그 집행이 이 회차다.

## §22-7. 한계 (명시)

1. **이 회차는 검증이지 신규 등재가 아니다.** Phase 3 착수 단위의 등재는 3회차에 끝났다.
2. **`ⓑ`의 "체계 vs 날짜" 축은 여전히 실측되지 않았다.** §21-1 ②가 "읽어서 그렇게 보인다"로 남긴 그대로다.
3. **게이트 문면 정정은 이 회차에서 하지 않았다.** `G-not-now-v1-release-recheck`의 stale 기간 표기(Phase 3 기간이 10/26~11/22로 남아 있다)와 병합으로 늘어난 게이트 ID 3개는 `HARN-124`가 정정 경로를 열 때 함께 정리한다.
4. **`claims reap --apply`는 실행하지 않았다.** `HARN-56`이 로컬 `in_progress`이면서 TTL 회수 가능 상태로 보였으나, 사유 확정 없이 회수하면 진행 중 작업을 끊는다.
5. **`pytest tests/harness`는 3건 red다 — 선재 결함이며 실측으로 판정했다.** 백그라운드 래퍼의 완료 알림은 exit 0이었고(래퍼가 종료 코드를 가림), 로그의 `PYTEST_EXIT=1`로 판정했다. 분기 기준 `1671b9d4`의 프로브 워크트리에서 **동일하게 3 failed** — 이 회차의 대장 변경이 원인이 아니다. 소유자 없는 축이라 `HARN-166`으로 등재했다(§22-5). 상세는 검증 보고서 §8-6.

---

**작성**: 2026-09-23 · `EOS-128-phase3-plan-backlog-conversion` 4회차 · 세션 `claude/docs-p3-00a-verification-17ea81` · 판정 기준 main `1671b9d4`