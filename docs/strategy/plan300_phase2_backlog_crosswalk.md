# 계획서 300 「Phase 2 — EOS Closed Learning Loop」 ↔ 빌드 하네스 백로그 변환 대조표

> **판정 기준: main `2e1220b4`** (2026-09-16) · 백로그 655건(미완 208) · 원 문서 = Kiki 제공 외부 `.docx`
> `300_Phase 2 — EOS Closed Learning Loop 실행계획`(2026-09-28~10-25 · §1~§22 · 본문 전량 확보)
>
> **태스크**: `EOS-09-plan300-phase2-backlog-conversion`
> **성격**: 대장 변환 + 대조 기록. **실행 승인이 아니다**(§0-2 참조).

---

## §0. 먼저 읽을 것 — 이 변환의 지위

### 0-1. 이 문서가 하는 일

계획서 300의 §22 우선순위 20건과 §1·§13·§16·§17·§19의 횡단 요구를 **착수 단위로 분해하고**, 각 단위를 기존 655건과 대조해 ①이미 있는가 ②일부만 있는가 ③정말 없는가를 판정한다. 없는 것만 등재한다.

### 0-2. 이 변환은 실행 지시가 아니다 (가장 중요)

선언 정본 `docs/strategy/eos_transition_declaration_2026-08-30.md` §1.3이 **2026-09-03 Kiki 결정**을 이미 정본화했다 (MEMORY 결정 로그 `2026-09-03 (Kiki 결정·계획서 300 대조)`):

> 계획서 300의 4주 Phase 2는 **실행하지 않고 참고 문서로 강등**한다. 폐쇄루프는 독립 목표가 아니라 **콘텐츠 생산성·학습 효과를 재는 기반 계측기**이며, 10월의 공식 목표는 **G2 앵커 콘텐츠 생산**으로 유지한다. 단 CL-WIRING 2건은 G2·G4 공통 선결조건이므로 수일 규모로 즉시 수행한다. 8상태 학습 상태 머신 신설은 **보류**(재확인 지점 = G4 12/13).

그때의 변환 결과가 3건이었고, 현재 상태는:

| 태스크 | status | eos_priority |
|---|---|---|
| `MOB-20-cl-wiring-attempt-submission` | **done** | P0 |
| `EOS-81-cl-wiring-closed-loop-e2e` | **done** | P0 |
| `HARN-61-p0-swap-exemption-clause` | todo | P2 |

**본 문서는 그 결정을 뒤집지 않는다.** 09-03 대조는 Gate 2 조건·API·경계 축에 집중했고 §22 20건의 전건 분해는 하지 않았으므로, 본 문서는 그 **잔여를 더 높은 해상도로 기록**한다. 여기 등재된 태스크의 *착수*는 09-03 결정의 갱신을 전제로 한다 — 등재는 대장에 올리는 것이고 착수는 별개다.

### 0-3. 원 문서 §3에 `P-01~P-16` 목록은 없다 (실측 정정)

이 변환을 지시한 프롬프트는 "§3 목록(P-01~P-16)을 기준 분해안으로 삼되 그대로 믿지 말고 대조하라"고 했다. **대조 결과 그 목록은 존재하지 않는다.** 원 문서 §3은 「Phase 2의 핵심 상태 머신」(8상태 전이)이다. 항목 목록의 실체는 **§22 우선순위 20건**(P0 7 · P1 5 · P2 3 · P3 5)이며, 프롬프트 3번이 "우선순위는 §22를 그대로 옮기라"고 지목한 바로 그 절이다. 따라서 §22를 분해 기준으로 삼고, §22가 덮지 않는 축(§1 계약 · §13 경계 · §16 시나리오 · §17 Event Trace · §19 KPI · §12 API · §18 Gate · §20 PR 규약 · §11 페르소나)을 추가했다.

---

## §1. 방법

- 판정 근거는 **실파일 경로·명령 출력·태스크 ID** 중 하나여야 한다. 문서 언급만으로 "충족"한 행은 없다.
- **"식별자 부재 ≠ 기능 부재"**(CLAUDE.md) 준수 — 계획서가 쓴 이름으로 0건인 항목은 **역할로 재검색**하고 **소비자(호출측)를 역추적**한 뒤 판정했다. 재검색으로도 0인 것만 갭이다.
- **"trunk 부재 ≠ 미구현"** 준수 — 클론이 shallow였으므로 `git fetch --unshallow origin`(EXIT=0 · 1,148 커밋 복원) 후 `git log --all --grep=<ID>`로 미머지 구현을 확인했다.
- **판정 시점** — 위 기준 커밋 해시 고정. 미머지 근거는 별도 표기한다.
- 재현 명령:

```bash
git fetch --unshallow origin
git rev-parse origin/main                               # 판정 기준 해시
python3 scripts/harness/backlog.py next --n 655 --json   # 전건(절단 금지)
python3 scripts/harness/backlog.py gates list
grep -h "^eos_priority:" backlog/tasks/*.yaml | sort | uniq -c
```

---

## §2. 등재하지 않은 것 ① — §15 동결 13종 (production code 금지)

원 문서 §15는 10월에 **production code 구현을 동결**할 13종을 지정한다("설계 문서는 남겨둘 수 있습니다. 하지만 production code 구현은 동결합니다"). 이들은 **등재 자체가 §15 위반**이므로 신규 태스크를 만들지 않았다. 대신 **현재 준수 상태를 실측**했다 — 동결 대상이 코드에 없다는 것은 갭이 아니라 **준수의 증거**다.

| # | §15 동결 대상 | production code 실측 | 대장 상태 | 판정 |
|---|---|---|---|---|
| 1 | 신규 EOS 기능 번호 추가 | — | `HARN-55` **done** — `backlog.py add`가 `--eos-priority` 미지정 시 **exit 1** | **기계 집행 중** |
| 2 | 새로운 Agent architecture | `agent_framework\|AgentExecutor\|multi_agent` **0 파일** | 대응 태스크 0 | 준수 |
| 3 | 고급 Digital Twin | `digital.?twin\|디지털 트윈` **0 파일** | 대응 태스크 0 | 준수 |
| 4 | 다과목 Adapter 구현 | `SubjectAdapter` 실재하나 **계약 수준**(`schema/subject_adapter.py`·`l4/subject_adapter_math.py`) | `EOS-66` done(계약) · 확장 실구현은 E1~E6 **todo·P3** | 준수(계약≠구현) |
| 5 | Physics/Chemistry/Biology 실제 확장 | 과목 팩 구현 0 | `E1-01`~`E6-01` 전건 **todo·P3·stage E1~E6** + 게이트 `G-s5-subject-expansion`[kiki/decision] | **게이트로 동결 중** |
| 6 | 고급 Knowledge Graph 분석 | `graph_analysis\|centrality\|pagerank\|community_detect` **0 파일** | 대응 태스크 0 | 준수 |
| 7 | 자동 교수법 개선 | `auto.*pedagog\|자동.*교수법` **0 파일** | 대응 태스크 0 | 준수 |
| 8 | 가상 학습 실험 | `virtual.?(learning\|experiment)\|가상 학습` **0 파일** | 대응 태스크 0 | 준수 |
| 9 | 성장 경로 예측 | `growth.?(path\|traject)\|성장 경로` **0 파일** | 대응 태스크 0 | 준수 |
| 10 | 자동 콘텐츠 리팩토링 | `auto.*refactor\|콘텐츠 리팩` **0 파일** | 대응 태스크 0 | 준수 |
| 11 | 연구자 협업 | `researcher\|연구자` **0 파일** | 대응 태스크 0 | 준수 |
| 12 | 고급 A/B framework | `ab_test\|abtest\|experiment_arm` **0 파일** | 대응 태스크 0 | 준수 |
| 13 | 복잡한 ML 추천 | 추천은 IRT CAT·규칙 기반 | `REC-*` 전건이 규칙·회계 축 | 준수 |

> **검색 범위 명시**: 위 실측은 `src/backend/whymath_backend/`·`src/mobile/lib/`를 대상으로 한 **역할 기반 정규식 전수**다. 각 행의 정규식을 그대로 적어 두었으므로 재현·반증이 가능하다. 12번의 초회 검색은 문자열 `A/B`가 한국어 주석에 섞여 17파일을 냈으나, 식별자(`ab_test`·`experiment_arm`)로 좁히면 0이다 — **표기가 아니라 식별자로 판정**했다.

**§14 분류와의 관계**: 원 문서 §14는 기존 기능을 LOOP/SUPPORT/FUTURE로 나누고 "가장 위험한 것은 FUTURE 기능을 계속 개발하면서 LOOP가 완성되지 않는 상황"이라고 경고한다. **이 저장소에서 그 위험은 실현되지 않았다** — FUTURE 7종(교사 협업·연구자 협업·디지털 트윈·가상 학습 실험·자동 콘텐츠 리팩토링·성장 경로 예측·다과목 자동 확장) 중 코드가 있는 것은 0이고, 다과목만 **P3 + stage E1~E6 + 사람 게이트**로 세 겹 동결돼 있다. 프롬프트가 지시한 "FUTURE는 등재하되 priority를 낮추고 10월 착수 금지를 notes에 적는다"는 처방은 **이미 더 강한 형태로 집행 중**이므로(notes 산문이 아니라 stage·게이트), 중복 등재하지 않았다.

## §3. 등재하지 않은 것 ② — 선행 결정이 이미 처분한 항목

| 원 문서 항목 | 처분 | 근거 |
|---|---|---|
| **§3 학습 상태 머신 8상태**<br>(NEW→DIAGNOSING→READY→LEARNING→PRACTICING→ASSESSING→REMEDIATING→ADVANCING) | **보류 — 등재 제외** | 2026-09-03 Kiki 결정(선언 §1.3). 저장소는 상태를 *머신*이 아니라 *이력*으로 모델링한다(`*MasteryHistory` append-only + `attempt_event` 시계열) — 8상태를 세우면 **같은 사실의 두 번째 진실 원천**이 생긴다(붕괴 연쇄 "유지보수 지옥 ← truth source가 하나가 아님"). **만료 없는 유예가 아니다**: 재확인 게이트가 대장에 실재하며(`remind-after-days=101` → G4 2026-12-13 SessionStart 브리핑 노출) 판정 3택(보류 유지 / ADR 채택 / 영구 미채택)까지 적혀 있다 |
| **§18 계획서 300 Gate 2** | **명칭 폐기** | 선언 §1.3-②: `G2` = Anchor Content Production 한 뜻으로만 쓴다. 계획서 300의 `Gate 2`는 사용하지 않는다(이름 충돌 3회차) |
| **CL-WIRING 2건** | **이미 완료** | `MOB-20` done · `EOS-81` done (09-03 결정의 즉시 수행분) |

