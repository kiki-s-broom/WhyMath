# EOS 기능 인벤토리 v2 — 기능 단위 전수 장부 + Migration Map (EOS-83)

> **지위**: `EOS-83-feature-inventory-v2-feature-granularity` 산출물. Kiki 요청(2026-09-03)
> *"기존 WhyMath 기능 전수 Inventory — 약 120개 기능을 한 장부로. 기능명 단순 나열 금지.
> 가장 중요한 필드는 EOS Ownership과 Migration Action"* 에 대한 답이다.
>
> **장부 정본은 이 문서가 아니라 기계다** — 생성기 `scripts/analysis/eos_feature_inventory_v2.py`
> (카탈로그·규칙의 단일 진실 원천) → 장부 `backlog/inventory/feature_inventory_v2.yaml`(기계가
> 읽는 표) + `feature_inventory_v2.csv`(Excel용·UTF-8 BOM). 본 문서는 전사·해설이다. 생성:
> `python3 scripts/analysis/eos_feature_inventory_v2.py --write`. 전수성·결함 주입은
> `tests/infra/test_eos_feature_inventory_v2.py`가 CI(infra-contracts 잡)에서 동결한다.
>
> ⚠️ **장부 두 파일은 저장소에 커밋되지 않는다 (OPS-76 · 2026-09-12)** — `.gitignore` 대상이며,
> 필요할 때 위 명령으로 각자 만든다. 예전에는 체크인해 두고 "장부 == 생성기 출력"을 비교했으나,
> 생성기의 입력에 백로그 대장과 소스 LOC가 들어가 **백로그를 건드리는 거의 모든 PR이 두 파일을
> 전 행 재생성**했다(30일간 40커밋). 그 재생성분은 자동 병합이 안 되고, **충돌한 PR은 GitHub이
> `refs/pull/N/merge`를 계산하지 못해 CI를 아예 발화시키지 않는다** — 낡은 결과가 화면에 남아
> "CI가 안 돈다"가 "CI가 실패했다"로 보인다(PR #1075에서 이틀). 전수성이라는 진짜 보호는
> 파일이 아니라 생성기를 실제 저장소에 돌리는 테스트가 지키므로, 파일을 빼도 보호는 줄지 않는다.
>
> **v1과의 관계**: `eos_feature_inventory_migration_map.md`(EOS-68)는 *라우터 단위* 23행이며
> 스스로 "행 수는 하한"이라 적었다. v2는 그 하한을 **기능 단위**로 내린 것이다. 두 장부는
> 대체가 아니라 **두 해상도**다 — Gate 0-D 4문항은 v1로 판정하고, 행별 EOS Ownership·Migration
> Action은 v2를 읽는다. 6축 임계는 v2가 v1에서 import하므로 판정 규칙의 정본은 하나다.
>
> 대조 시점: 2026-09-03 · main `186ae532`(MOB-20 착지 후) · 백엔드 모듈 **580** · 엔드포인트 **109**.

---

## §0. 요약 — 숫자 5개

| 항목 | 값 | 뜻 |
|---|---|---|
| **모집단** | **162행** (S 49 · E 88 · O 13 · C 12) | "약 120개"보다 많다 — 이유는 §1. 분류율 162/162 |
| **EOS Ownership** | CORE 108 · INFRA 21 · CLIENT 12 · **MIXED 10** · ADAPTER 8 · CORE+ADAPTER_DEP 3 | Core가 2/3. 수학 어댑터는 8행(+의존 3행)뿐 — 계획서 100 §3.7의 "Core가 이차방정식을 알게 만들면 안 된다"가 이미 대체로 성립 |
| **Migration Action** | **KEEP 113 · REFACTOR 16 · HEAVY 11 · REPLACE 검토 1 · POSTPONE 21** | §3.4 기준(KEEP 6조건·REPLACE 신호)과 §3.14 매트릭스의 **결합 판정**(§2). 재작성 대상 0. REPLACE 검토 1건(§4-③)은 가족 합산 효과 |
| **출시 우선도(기계)** | **P0 101 · P1 40 · P2 19 · P3 2** | "없으면 12/31 폐쇄루프가 깨지는가"를 import 도달성 + app.state DI 다리 + 루프 테이블 유일 writer로 답했다(§7). P0의 80%(81행)가 KEEP — 12월 검증 경로 대부분은 옮길 필요가 없다 |
| **Migration Risk** | High 24 · Med 43 · Low 95 | High 24건 중 MIXED 10 + 총점 ≥10 14 |

**한 줄 판정**: 이전 난이도가 높은 곳은 *수학*이 아니라 **비대한 가족**(성취기준 적재·문제은행·
검수 워크플로·QA 게이트·privacy)이다. 과목 경계(Core↔Adapter)는 MIXED 10행으로 좁혀져 있고
그중 6행은 이미 등재된 태스크가 소유한다(§4-①). **REFACTOR 16행은 전부 §3.4의 정의 그대로
"경계 위반"이다**(MIXED 7 · 수학 직접 호출 2 · shadow/플래그 OFF 4 · 서빙 표면 테스트 0 2 · 동의 1 — §4-⑦).

---

## §1. 모집단 정의 — 왜 120이 아니라 162인가

**기능 = 사용자(학생·보호자·운영자·플랫폼)에게 의미가 있는 능력 1단위.** 네 평면으로 나누고
각 평면의 전수성을 기계가 검사한다(어느 하나라도 빠지면 생성기가 exit 1로 장부를 쓰지 않는다):

| 평면 | 모집단 | 전수성 검사 | 행 |
|---|---|---|---:|
| **S** 서빙 표면 | `app.py`가 include한 22 라우터 + app 자체 엔드포인트의 **엔드포인트 그룹** | 109 엔드포인트 전부 정확히 1행 귀속 | 49 |
| **E** 백엔드 엔진 | `whymath_backend` 모듈 **가족**(l1~l6·whs·harness 런타임·schema·db·infra) | 580 모듈 전부 정확히 1행 귀속(라우터 모듈은 S가 덮음) | 88 |
| **O** 운영자 도구 | `ops`·`privacy` CLI·`harness` 배치/게이트/리포트 가족 | E와 같은 모듈 검사 | 13 |
| **C** 클라이언트 | Flutter `lib/features/*`·`lib/core`·web 그래핑 계산기 | 10 feature 디렉터리 전부 귀속 | 12 |

**120과 다른 이유** — 계획서 100의 "기존 120개"는 저장소 외부 xlsx의 수치라 **대조 불가**(EOS-68
notes·선행 대조 §6-1 동일)다. 이쪽은 *재현 가능한 정의*를 우선했고, 그 정의로 세면 162가 나온다.
차이의 성격은 셋으로 추정된다(추정이라 적는다): ① 외부 표는 운영자 도구(O 13)와 shadow 계열
(E 7)을 기능으로 세지 않았을 가능성 ② 이 표는 `me` 라우터 하나를 16행으로 쪼갰다(외부 표가
"학습 이력 조회" 1행으로 묶었다면 -10) ③ 외부 표가 계획 기능을 포함했다면 방향이 반대다.
**어느 쪽이 맞는지는 원본 xlsx를 저장소에 들여야 판정된다** — 그 전까지 이 장부의 162가
*재현 가능한 하한*이다.

**모집단이 아닌 것**: backlog 태스크(작업 단위) · 테스트 파일 · alembic 리비전 개별 · docs.
`data_pipeline` ETL 12패키지는 독립 행이 아니라 대응 L1 적재 행의 "현재 위치"에 병기했다(ETL과
적재기는 한 기능의 두 절반).

---

## §2. 방법 — 두 핵심 필드는 어떻게 나오나

### EOS Ownership (기계 판정 · 카탈로그에 이 필드가 *없다*)

`eos_core_adapter_boundary_scan.BOUNDARY_MAP`(EOS-65 정본·EOS-67이 CI 강제)으로 행의 **자기
모듈**을 판정한다:

| 값 | 규칙 | EOS 대상 |
|---|---|---|
| `CORE` | 자기 모듈 전부 CORE | EOS Core |
| `ADAPTER` | 전부 ADAPTER | Math Adapter |
| `MIXED` | CORE·ADAPTER 동거 **또는** MIXED 모듈 포함 | Core/Adapter **분리 필요** |
| `CORE+ADAPTER_DEP` | (S 평면) 표면은 중립인데 호출 폐쇄에 ADAPTER 모듈 | EOS Core — 의존을 SubjectAdapter 경유로 절단 |
| `INFRA` | 횡단(db·ops·privacy·harness·security·composition) | EOS Infra |
| `CLIENT` | Flutter·web | Client(View Layer) |

MIXED를 반올림하지 않는다(EOS-65 §1과 같은 이유 — CORE로 올리면 위반이 부풀고 ADAPTER로
내리면 위반이 숨는다).

### Migration Action (기계 판정 · 임계는 v1에서 import)

계획서 100 §3.14 6축 18점 → 0~4 **KEEP** · 5~9 **REFACTOR** · 10~13 **HEAVY_REFACTOR** ·
14~18 **REPLACE_CANDIDATE**. 여기에 규칙 하나: 출시 우선도(§7 기계 판정)가 **P2/P3면 `POSTPONE`으로 덮되
매트릭스 판정은 `matrix_action`에 보존**한다(이월 ≠ 삭제 — 계획서 006 §26).

6축 대리지표는 평면별로 다르다(생성기 docstring에 표로 고정). 특히 **A(과목결합)**: 소유가
ADAPTER인 행은 A=0이다 — 수학 모듈이 수학인 것은 *소속*이지 *부채*가 아니다. MIXED는 A=3.
CORE/INFRA는 v1 규칙(폐쇄의 ADAPTER 의존 수).

### §3.4 KEEP/REFACTOR/REPLACE/POSTPONE 기준 → 최종 판정 (기계)

계획서 100 §3.4는 서술형 기준이고 §3.14는 점수다. 둘을 **측정 가능한 부분만** 불리언으로 옮겨
결합했다(생성기 `_apply_criteria_34` · 상수 `KEEP_MIN_CRITERIA=5`·`REPLACE_MIN_SIGNALS=3`):

| §3.4 KEEP 6조건 | 대리지표 | §3.4 REPLACE 신호 6종(측정 가능분) | 대리지표 |
|---|---|---|---|
| k1 과목 의존성 낮음 | A축 ≤ 1 | r1 핵심 데이터 모델이 EOS 모델과 충돌 | 자기 모듈 중 MIXED 판정 `schema.*` 존재 |
| k2 API 명확 | S/C 평면 · fan-in ≥ 1(재수출 포함) · CLI 진입점 | r2 과목 특화 로직이 Core 깊숙이 침투 | CORE/INFRA/MIXED인데 A축 = 3 |
| k3 테스트 존재 | D축 ≤ 2 | r3 테스트 불가능 | D축 = 3 |
| k4 데이터 모델 EOS 비충돌 | 소유 ≠ MIXED **and** r1 = 0 | r4 동일 기능 중복 구현 | 카탈로그 `duplicate_of` 선언(근거 병기) |
| k5 지나친 결합 없음 | C축 ≤ 1 | r5 상태 변이 추적 없음 | E축 ≥ 2인데 폐쇄에 audit/evidence/provenance/history/ledger 계열 0 |
| k6 실제 동작 검증 | 상태 ≠ Flag-off/Shadow **and** 테스트 fn ≥ 1 | r6 API 계약 자체가 없음 | S 평면에 `response_model`도 204도 없는 엔드포인트 존재 |

"수정 비용 > 재작성 비용"은 측정 불가라 신호에 **넣지 않았다**(사람 판단). 결합 규칙(위에서 첫
성립 조건이 판정):

1. **POSTPONE** — 출시 우선도 P2/P3(§7). 매트릭스 원판정 보존
2. **REPLACE_CANDIDATE** — 매트릭스 14+ **또는** REPLACE 신호 ≥ 3. 단독 신호로 선고하지 않는다
   (계획서 100: *"경계를 복구할 수 없을 때만"* — 복구 가능성 자체는 사람 판정이라 CANDIDATE)
3. **HEAVY_REFACTOR** — 매트릭스 10~13
4. **KEEP** — §3.4 KEEP 6조건 중 **≥ 5**(계획서의 "대부분 만족")
5. **REFACTOR** — 나머지. 장부 `action_basis`에 **어느 조건이 미충족인지** 그대로 적는다

§3.4 단독 판정은 `criteria_action`, 매트릭스 단독 판정은 `matrix_action`으로 남겨 세 값이 서로
어긋나는 행을 대시보드가 센다(`final_differs_from_matrix` 38 · `final_differs_from_criteria` 13).

### 파생 필드

결합도(C축) · 테스트(D축) · Migration Risk(총점 ≥10 또는 MIXED → High) · **상태**는 카탈로그
선언값이지만 `flag`가 지정된 행은 `config.py` 기본값을 **실측**해 꺼져 있으면 `Flag-off`로
덮는다(선언과 실체가 다르면 실체가 이긴다 — 11행이 이 규칙으로 Flag-off가 됐다).
**출시 우선도**는 §7의 폐쇄루프 도달성 규칙이 **기계로** 낸다(P0). P1/P2 경계는 선행 제안(v2.0)을, P3는 horizon 선언을 승계하며 확정은 Kiki.

---

## §3. 전수 표 (162행)

표기: Ownership·Action은 굵게. `…/` = `src/backend/whymath_backend/`, `dp/` = `src/data-pipeline/data_pipeline/`.
S 평면의 "현재 위치"는 파일만 적었다 — 엔드포인트 목록은 yaml/csv `location` 필드에 전부 있다.
POSTPONE 행은 괄호에 매트릭스 원판정을, 우선도가 선행 제안(v2.0)과 다른 행은 `(←이전)`을 병기했다.

### S 서빙 표면 — 엔드포인트 그룹 (49행)

| ID | 기능명 | 현재 위치 | 사용자 | Domain | **EOS Ownership** | 상태 | 결합도 | 테스트 | **Migration Action** | §3.4 KEEP | **우선도** | 우선도 근거 | Risk | A B C D E F | 계 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---:|
| WM-S-001 | 헬스체크·상태 조회 | `…/app.py` | Platform | Operations | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 0 1 0 0 0 | 1 |
| WM-S-002 | LLM 생성 게이트웨이(동기·비동기 잡) | `…/app.py` | Platform | AI Orchestration | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 1 0 1 0 1 0 | 3 |
| WM-S-003 | 소셜 로그인(OAuth 카카오·네이버) | `…/api/auth.py` | Student | Identity | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 0 0 0 1 0 | 1 |
| WM-S-004 | 토큰 회전·로그아웃 | `…/api/auth.py` | Student | Identity | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0** | 루프 seed_route | Med | 0 1 1 0 1 2 | 5 |
| WM-S-005 | 활성 세션 목록·원격 로그아웃 | `…/api/auth.py` | Student | Security | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 1 0 0 1 1 | 3 |
| WM-S-006 | 내 프로필 조회·수정(온보딩) | `…/api/users.py` | Student | Identity | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route, invariant | Low | 0 1 1 0 1 1 | 4 |
| WM-S-007 | 법정대리인 동의 기록·철회·조회 | `…/api/users.py` | Parent | Security | **CORE** | Flag-off | Med | Full | **REFACTOR** | 4/6 | **P0** | 루프 invariant | Med | 1 1 2 0 1 2 | 7 |
| WM-S-008 | 디바이스 등록·폐기·목록 | `…/api/devices.py` | Student | Security | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 0 1 0 1 0 | 2 |
| WM-S-009 | 개인정보 처리 권한 판정(PEP) | `…/api/privacy.py` | Platform | Security | **CORE** | Production | Low | None | **REFACTOR** | 4/6 | **P0** | 루프 invariant | Med | 0 1 1 3 1 1 | 7 |
| WM-S-010 | 내 학습 세션 이력·종료·삭제 | `…/api/me.py` | Student | Event | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1** | 승계(P1) | Med | 1 1 1 0 1 1 | 5 |
| WM-S-011 | 내 진단 이력·완료·삭제 | `…/api/me.py` | Student | Assessment | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1** | 승계(P1) | Med | 1 1 1 0 1 1 | 5 |
| WM-S-012 | 평가 조립(청사진)·측정 캡처 | `…/api/me.py` | Student | Assessment | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 1 1 0 1 1 | 4 |
| WM-S-013 | 내 코치 대화 이력·종료·삭제 | `…/api/me.py` | Student | Pedagogy | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1** | 승계(P1) | Med | 1 1 1 0 1 1 | 5 |
| WM-S-014 | 내 개인정보 감사 이력 조회(삭제·접근) | `…/api/me.py` | Student | Security | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 1 1 0 0 1 | 3 |
| WM-S-015 | 풀이 채점 제출(attempt 적재+숙달 갱신) | `…/api/me.py` | Student | Learning Model | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 1 1 0 1 1 | 4 |
| WM-S-016 | 개념·스킬 숙달 곡선 조회 | `…/api/me.py` | Student | Learning Model | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 1 1 0 0 2 | 4 |
| WM-S-017 | IRT 능력(θ) 추정·스냅샷·성장 곡선 | `…/api/me.py` | Student | Learning Model | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1 (←P0)** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) | Med | 0 2 1 0 1 2 | 6 |
| WM-S-018 | 개념 진단(BKT↔IRT 교차검증)·요약 | `…/api/me.py` | Student | Assessment | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 0 0 0 0 0 | 0 |
| WM-S-019 | 약개념 추천·복습 우선순위 큐 | `…/api/me.py` | Student | Recommendation | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 0 0 0 0 0 | 0 |
| WM-S-020 | 선수개념 갭·학습 경로·개념 코칭 결정 | `…/api/me.py` | Student | Recommendation | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 0 1 0 0 0 | 1 |
| WM-S-021 | 적응형 다음 문항 추천(IRT CAT) | `…/api/me.py` | Student | Recommendation | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 1 1 1 0 0 1 | 4 |
| WM-S-022 | 목표 진행 상황(D-day·성취기준 커버리지) | `…/api/me.py` | Student | Learning Model | **CORE** | Production | Low | Partial | **POSTPONE (KEEP)** | 6/6 | **P2** | 승계(P2) | Low | 0 0 0 1 0 0 | 1 |
| WM-S-023 | 계정 삭제권·데이터 이동권(내보내기) | `…/api/me.py` | Student | Security | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 invariant | Low | 0 0 1 0 1 0 | 2 |
| WM-S-024 | 성장 증거 노출(학생 안전)·대리지표 원시값(admin) | `…/api/me.py` | Student | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 0 1 0 0 0 | 1 |
| WM-S-025 | 학습시간 통계 | `…/api/me.py` | Student | Analytics | **CORE** | Production | Low | Partial | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 1 0 2 0 1 | 4 |
| WM-S-026 | 학습목표 맞춤 학습 단위 공급·결과 기록 | `…/api/study.py` | Student | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 1 0 1 0 1 0 | 3 |
| WM-S-027 | 교수학 통합 결정(stateless 코치) | `…/api/coach.py` | Student | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1 (←P0)** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) | Low | 0 0 0 0 1 0 | 1 |
| WM-S-028 | 코치 대화 세션(생성·턴 추가·조회) | `…/api/coach.py` | Student | Pedagogy | **CORE** | Production | Med | Full | **KEEP (매트릭스 REFACTOR)** | 5/6 | **P0** | 루프 seed_route | Med | 1 1 2 0 1 1 | 6 |
| WM-S-029 | 결정론 채점 3종(단계·풀이·답 검산) | `…/api/verify.py` | Student | Math Engine | **CORE+ADAPTER_DEP** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 5/6 | **P0** | 루프 seed_route | Med | 3 0 1 0 2 0 | 6 |
| WM-S-030 | 문제 조회(공개 투영·단계·관계) | `…/api/problems.py` | Student | Content | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 1 1 1 0 0 1 | 4 |
| WM-S-031 | 문제 저작 CRUD | `…/api/problems.py` | Admin | Content | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1** | 승계(P1) | Med | 1 1 1 0 2 1 | 6 |
| WM-S-032 | 검증 풀이 경로 단계 점층 공개 | `…/api/solution_paths.py` | Student | Content | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 0 0 0 0 0 | 0 |
| WM-S-033 | 개념 그래프 조회(목록·단건·엣지) | `…/api/concepts.py` | Student | Knowledge Graph | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 1 0 0 0 1 | 2 |
| WM-S-034 | 개념 의미검색(pgvector) | `…/api/concepts.py` | Student | Knowledge Graph | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 0 0 0 0 0 | 0 |
| WM-S-035 | 개념 콘텐츠(정의·비유·예시) 조회 | `…/api/concepts.py` | Student | Content | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 1 0 0 0 1 | 2 |
| WM-S-036 | 개념 노드 저작 CRUD | `…/api/concepts.py` | Admin | Knowledge Graph | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1** | 승계(P1) | Med | 0 1 1 0 2 1 | 5 |
| WM-S-037 | 교육과정 프레임워크·버전·노드 조회 | `…/api/curricula.py` | Admin | Curriculum | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1 (←P0)** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) | Med | 0 2 1 0 0 2 | 5 |
| WM-S-038 | 성취기준(학습 성과) 단건 조회 | `…/api/curricula.py` | Admin | Curriculum | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1 (←P0)** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) | Low | 0 1 0 0 0 1 | 2 |
| WM-S-039 | 개념↔성취기준 정렬 통합 조회 | `…/api/alignments.py` | Admin | Curriculum | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1 (←P0)** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) | Low | 0 0 0 0 0 0 | 0 |
| WM-S-040 | 권리(저작권) 판정 게이트웨이 | `…/api/rights.py` | Platform | Content | **CORE** | Production | Low | None | **REFACTOR** | 4/6 | **P0** | 루프 invariant | Med | 1 0 1 3 1 0 | 6 |
| WM-S-041 | L6 응용 모드 게이팅 6종(재수·수능·학교진도·사고력·메타인지·영재) | `…/api/gating.py` | Student | Application Mode | **CORE** | Production | Low | Full | **POSTPONE (KEEP)** | 6/6 | **P2** | 승계(P2) | Low | 1 0 1 0 0 0 | 2 |
| WM-S-042 | 약점 개념 맞춤 시각화 생성 | `…/api/visualization.py` | Student | Interaction | **CORE** | Production | Low | Partial | **POSTPONE (KEEP)** | 6/6 | **P2** | 승계(P2) | Low | 0 0 1 1 1 0 | 3 |
| WM-S-043 | 시각화 명세 검증·공유 링크 | `…/api/visualization.py` | Student | Interaction | **CORE** | Production | Low | Partial | **POSTPONE (KEEP)** | 6/6 | **P2** | 승계(P2) | Low | 1 0 0 1 1 0 | 3 |
| WM-S-044 | 약점 개념 맞춤 학습 장면 생성 | `…/api/scene.py` | Student | Interaction | **CORE** | Production | Low | Full | **POSTPONE (KEEP)** | 6/6 | **P2** | 승계(P2) | Low | 0 0 1 0 1 0 | 2 |
| WM-S-045 | 시각화 조작 이벤트 적재 | `…/api/interactions.py` | Student | Event | **CORE** | Production | Low | Partial | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1** | 승계(P1) | Med | 1 1 1 1 1 1 | 6 |
| WM-S-046 | 손글씨 풀이 OCR(단일·다중 페이지) | `…/api/ocr.py` | Student | Math Engine | **CORE+ADAPTER_DEP** | Flag-off | Low | Full | **POSTPONE (KEEP)** | 4/6 | **P2** | 승계(P2) | Low | 3 0 0 0 1 0 | 4 |
| WM-S-047 | 수식 한국어 낭독 명세 생성 | `…/api/speech.py` | Student | Math Engine | **CORE+ADAPTER_DEP** | Production | Low | Partial | **POSTPONE (REFACTOR)** | 5/6 | **P2** | 승계(P2) | Med | 3 0 1 1 1 0 | 6 |
| WM-S-048 | DSL 콘텐츠 생성·검증·컴파일 | `…/api/dsl.py` | Admin | Content | **CORE** | Production | Low | Partial | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0** | 루프 seed_route | Med | 1 0 1 1 2 0 | 5 |
| WM-S-049 | 학생 결함 신고 접수 | `…/api/reports.py` | Student | QA | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 1 0 0 1 1 | 3 |

### E 백엔드 엔진 — 모듈 가족 (88행)

| ID | 기능명 | 현재 위치 | 사용자 | Domain | **EOS Ownership** | 상태 | 결합도 | 테스트 | **Migration Action** | §3.4 KEEP | **우선도** | 우선도 근거 | Risk | A B C D E F | 계 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---:|
| WM-E-101 | 원자 백본 그래프 적재·검색·중복 검수 | `…/l1/atom_graph, dp/atom_graph` | Platform | Knowledge Graph | **CORE** | Production | Med | Full | **KEEP (매트릭스 REFACTOR)** | 5/6 | **P0** | 루프 student_loop, data_supplier | Med | 1 2 2 0 1 2 | 8 |
| WM-E-102 | 구 개념그래프 적재·임베딩·검색 | `…/api, …/l1/concept_graph, dp/concept_graph` | Platform | Knowledge Graph | **CORE** | Production | Med | Full | **HEAVY_REFACTOR** | 5/6 | **P0 (←P1)** | 루프 student_loop, production_loop, data_suppl | High | 1 2 2 0 3 2 | 10 |
| WM-E-103 | 개념↔원자 크로스워크 이전 | `…/l1/concept_atom_crosswalk, dp/concept_atom_crosswalk` | Platform | Knowledge Graph | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0 (←P1)** | 루프 production_loop, data_supplier | Med | 0 1 1 0 2 2 | 6 |
| WM-E-104 | 개념 콘텐츠 4종 적재·해석 | `…/l1/concept_content, dp/concept_content, dp/concept_content_university` | Platform | Content | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, data_supplier | Low | 0 1 0 0 1 1 | 3 |
| WM-E-105 | 교육과정 프레임워크 로더·해석 | `…/l1/curriculum` | Platform | Curriculum | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, data_supplier | Low | 1 1 1 0 0 1 | 4 |
| WM-E-106 | 성취기준·평가기준 적재·정렬 질의·앵커 레지스트리 | `…/l1/standards, dp/ncic, dp/standards_university` | Platform | Curriculum | **CORE** | Production | Med | Full | **HEAVY_REFACTOR** | 5/6 | **P0** | 루프 student_loop, production_loop, data_suppl | High | 0 3 2 0 3 3 | 11 |
| WM-E-107 | 오개념 카탈로그·크로스링크 적재·승인 게이트 | `…/l1/misconception, dp/misconception` | Platform | Pedagogy | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0** | 루프 student_loop, production_loop, data_suppl | Med | 0 2 1 0 1 3 | 7 |
| WM-E-108 | 교수법 팩·단원 DSL 컴파일·적재 | `…/l1/pedagogy` | Platform | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 data_supplier | Low | 0 1 1 0 0 1 | 3 |
| WM-E-109 | 문제은행 적재·임베딩·시그니처·페르소나 적합·정답분포 | `…/l1/problem_bank` | Platform | Content | **CORE** | Production | Med | Full | **HEAVY_REFACTOR** | 5/6 | **P0** | 루프 student_loop, production_loop, data_suppl | High | 1 2 2 0 2 3 | 10 |
| WM-E-110 | 공식 그래프 적재 | `…/l1/formula_graph, dp/formula_graph` | Platform | Knowledge Graph | **MIXED** | Production | Low | Full | **POSTPONE (REFACTOR)** | 4/6 | **P2** | 승계(P2) | High | 3 1 0 0 1 1 | 6 |
| WM-E-111 | 스킬 그래프 적재·해석 | `…/l1/skill_graph, dp/skill_graph` | Platform | Knowledge Graph | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0** | 루프 data_supplier | Med | 1 1 1 0 1 2 | 6 |
| WM-E-112 | 풀이 전략 그래프 적재 | `…/l1/strategy_graph, dp/strategy_graph` | Platform | Pedagogy | **MIXED** | Production | Low | Full | **POSTPONE (REFACTOR)** | 4/6 | **P2** | 승계(P2) | High | 3 1 0 0 1 1 | 6 |
| WM-E-113 | 문제 유형 그래프 적재 | `…/l1/problem_type_graph, dp/problem_type_graph` | Platform | Content | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 1 0 0 1 1 | 3 |
| WM-E-114 | 진단문항·소크라테스 프로브 적재 | `…/l1/atom_probe` | Platform | Assessment | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 1 0 0 0 1 | 2 |
| WM-E-115 | 저작권 게이트웨이·정책 엔진·귀속 | `…/l1/rights` | Platform | Content | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop, invariant | Low | 1 1 1 0 0 1 | 4 |
| WM-E-116 | 개념 시각화·시각 스타일 오버레이 | `…/l1/concept_visual_style, …/l1/concept_visualization` | Platform | Interaction | **CORE** | Production | Low | Full | **POSTPONE (REFACTOR)** | 6/6 | **P2** | 승계(P2) | Med | 1 1 1 0 0 2 | 5 |
| WM-E-117 | 임베딩 제공자 셀렉터(bge-m3·OpenAI·fake) | `…/l1` | Platform | AI Orchestration | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0 (←P1)** | 루프 student_loop, production_loop | Low | 0 0 0 0 0 0 | 0 |
| WM-E-118 | 그래프 분석 유틸(ETL 측) | `dp/graph_analytics` | Platform | Knowledge Graph | **CORE** | Production | Low | Full | **POSTPONE (KEEP)** | 6/6 | **P2** | 승계(P2) | Low | 0 0 0 0 1 0 | 1 |
| WM-E-201 | BKT 숙달 추정·개념/스킬 숙달 이력 영속 | `…/l2` | Student | Learning Model | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0** | 루프 student_loop | Med | 1 2 1 0 2 2 | 8 |
| WM-E-202 | IRT 문항·능력 동시 추정·θ 시계열 | `…/l2` | Student | Learning Model | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0** | 루프 student_loop, production_loop | Med | 1 2 1 0 0 3 | 7 |
| WM-E-203 | 문항 난이도 JMLE 보정 배치 | `…/l2` | Admin | Assessment | **CORE** | Batch | Low | Partial | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1** | 승계(P1) | Med | 0 1 1 1 1 2 | 6 |
| WM-E-204 | 개념 진단(BKT↔IRT 교차)·LearnerState 조립 | `…/l2` | Student | Assessment | **CORE** | Production | Med | Full | **KEEP (매트릭스 REFACTOR)** | 5/6 | **P0** | 루프 student_loop | Med | 1 2 2 0 1 3 | 9 |
| WM-E-205 | 약개념·선수개념 추천·학습 경로·복습 큐 | `…/l2` | Student | Recommendation | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0** | 루프 student_loop | Med | 1 1 1 0 1 2 | 6 |
| WM-E-206 | 학습 증거 이벤트 적재(attempt·처치·추천 회계) | `…/l2` | Student | Event | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0** | 루프 student_loop | Med | 1 1 1 0 2 2 | 7 |
| WM-E-207 | 목표 진행 조회 좌석 | `…/l2` | Student | Learning Model | **CORE** | Production | Low | Full | **POSTPONE (REFACTOR)** | 6/6 | **P2** | 승계(P2) | Med | 0 2 1 0 1 2 | 6 |
| WM-E-208 | 일별 학습 지표 롤업 writer | `…/harness, …/l2` | Admin | Analytics | **CORE** | Production | Low | Full | **HEAVY_REFACTOR** | 6/6 | **P1** | 승계(P1) | High | 1 2 1 0 3 3 | 10 |
| WM-E-301 | LLM 라우터(3축 결정·모델 매트릭스·seed 정책) | `…/l3` | Platform | AI Orchestration | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop | Low | 1 0 0 0 0 0 | 1 |
| WM-E-302 | LLM 제공자(Ollama·Anthropic·복합) | `…/l3/providers` | Platform | AI Orchestration | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop | Low | 0 0 1 0 1 0 | 2 |
| WM-E-303 | 생성 파이프라인·Redis 캐시·Langfuse 관측 | `…/l3, …/l3/cache, …/l3/trace` | Platform | AI Orchestration | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop, invariant | Low | 1 0 1 0 0 0 | 2 |
| WM-E-304 | QUALITY 티어 비동기 큐(Celery) | `…/l3/queue` | Platform | AI Orchestration | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0 (←P1)** | 루프 student_loop, production_loop | Low | 1 0 1 0 0 0 | 2 |
| WM-E-305 | 데이터 등급 → 국외 반출 게이트 | `…/l3` | Platform | Security | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop, invariant | Low | 1 0 0 0 0 0 | 1 |
| WM-E-306 | 빌드타임 캐시 사전생성(pre-warm)·시드 검증 | `…/l3/pregenerate` | Admin | AI Orchestration | **MIXED** | Batch | Med | Full | **REFACTOR** | 3/6 | **P0 (←P1)** | 루프 student_loop, production_loop | High | 3 0 2 0 2 0 | 7 |
| WM-E-307 | DSL 콘텐츠 생성기(컴파일·검증·복구·변수 엔진) | `…/l3/dsl` | Admin | Content | **MIXED** | Production | Low | Full | **REFACTOR (매트릭스 KEEP)** | 4/6 | **P0** | 루프 production_loop | High | 3 0 0 0 0 0 | 3 |
| WM-E-308 | 교수법 렌더 어댑터 5종·평가 재료 뱅크 | `…/l3/render` | Platform | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop | Low | 1 0 1 0 0 0 | 2 |
| WM-E-309 | 교수 콘텐츠 슬롯 파이프라인(생성→예심→검수) | `…/l3/pedagogy` | Admin | QA | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1 (←P0)** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) | Med | 0 1 1 0 2 2 | 6 |
| WM-E-310 | 비유·예시 생성기·결함 검출기 | `…/l3/pedagogy` | Platform | Pedagogy | **CORE** | Production | High | Full | **KEEP (매트릭스 REFACTOR)** | 5/6 | **P1** | 승계(P1) | Med | 0 1 3 0 1 2 | 7 |
| WM-E-311 | 독립 다관점 LLM 교차검증 | `…/l3` | Platform | QA | **CORE** | Production | Med | Full | **KEEP** | 5/6 | **P0 (←P1)** | 루프 student_loop | Low | 0 0 2 0 0 0 | 2 |
| WM-E-312 | 풀이 경로(SolutionPath) 구조·조회 store | `…/l3` | Platform | Content | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop | Low | 1 1 0 0 0 2 | 4 |
| WM-E-313 | 시각화 명세 생성기·품질 채점 | `…/l3` | Platform | Interaction | **CORE** | Production | Low | Full | **POSTPONE (KEEP)** | 6/6 | **P2** | 승계(P2) | Low | 1 0 1 0 0 0 | 2 |
| WM-E-314 | 프롬프트 자산 레지스트리 | `…/l3` | Platform | Versioning | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop | Low | 0 0 0 0 0 0 | 0 |
| WM-E-351 | 동등문제 생성 파이프라인(생성·수용 게이트·정규화·rephrase·감사) | `…/l3/equivalent` | Admin | Math Engine | **ADAPTER** | Production | High | Full | **KEEP** | 5/6 | **P0** | 루프 student_loop, production_loop | Low | 0 0 3 0 1 0 | 4 |
| WM-E-352 | 단원별 스켈레톤 생성기 41종(초·중·고·대) | `…/l3/equivalent` | Admin | Math Engine | **ADAPTER** | Production | Med | Full | **KEEP (매트릭스 REFACTOR)** | 5/6 | **P0** | 루프 production_loop | Med | 0 0 2 0 3 0 | 5 |
| WM-E-353 | 기호 동치·해집합 보존 판정 primitive | `…/l3` | Platform | Math Engine | **ADAPTER** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop | Low | 0 0 0 0 1 0 | 1 |
| WM-E-354 | 답 검산(Tier1 수치·형태·최종답) | `…/l3` | Student | Math Engine | **ADAPTER** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop | Low | 0 0 1 0 0 0 | 1 |
| WM-E-355 | 단계·풀이 연쇄 검증·검증 등급 | `…/l3` | Student | Math Engine | **MIXED** | Production | Med | Full | **REFACTOR** | 3/6 | **P0** | 루프 student_loop, production_loop | High | 3 0 2 0 0 0 | 5 |
| WM-E-356 | SymPy 불가 영역 검산(유한확률 전수·통계 자료형) | `…/l3` | Platform | Math Engine | **ADAPTER** | Production | Low | Full | **KEEP** | 6/6 | **P0 (←P1)** | 루프 student_loop, production_loop | Low | 0 0 0 0 0 0 | 0 |
| WM-E-357 | 다중 풀이법 생성(접근법 6종) | `…/l3` | Platform | Math Engine | **ADAPTER** | Production | High | Full | **POSTPONE (HEAVY_REFACTOR)** | 5/6 | **P2** | 승계(P2) | High | 0 2 3 0 3 2 | 10 |
| WM-E-358 | 표기 커버리지 게이트 | `…/l3` | Admin | Math Engine | **ADAPTER** | Batch | Low | Full | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 0 0 0 1 0 | 1 |
| WM-E-359 | 수식 낭독(AST→한국어)·역파서·학년별 프로파일 | `…/l3, …/l4/speech` | Student | Math Engine | **MIXED** | Production | Low | Full | **POSTPONE (KEEP)** | 4/6 | **P2** | 승계(P2) | High | 3 0 0 0 0 0 | 3 |
| WM-E-401 | Polya 4단계 코칭 엔진·전이 | `…/l4/polya` | Student | Pedagogy | **CORE** | Production | Med | Full | **KEEP** | 5/6 | **P0** | 루프 student_loop | Low | 0 0 2 0 0 0 | 2 |
| WM-E-402 | 소크라테스 6카테고리 선택 | `…/l4/socratic` | Student | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop | Low | 0 0 0 0 0 0 | 0 |
| WM-E-403 | LTHC 적응(진입점·확장·비계) | `…/l4/lthc` | Student | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0 (←P1)** | 루프 student_loop | Low | 0 0 0 0 0 0 | 0 |
| WM-E-404 | 답 미루기 4단계 힌트·정서 안전 톤필터 | `…/l4` | Student | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop | Low | 0 0 0 0 0 0 | 0 |
| WM-E-405 | 메타인지·보정·선수복습 코칭 결정 | `…/l4` | Student | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop | Low | 0 0 1 0 0 0 | 1 |
| WM-E-406 | 완료 상태머신·턴 메타·세션 회상 | `…/l4` | Student | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop | Low | 1 0 1 0 0 0 | 2 |
| WM-E-407 | 풀이 계산오류 → 검산 코칭 오케스트레이터 | `…/l4` | Student | Pedagogy | **MIXED** | Production | Med | Full | **REFACTOR** | 3/6 | **P0** | 루프 student_loop | High | 3 0 2 0 0 0 | 5 |
| WM-E-408 | 콘텐츠 공급 경로(DSL 캐시·render-vs-generate) | `…/l4` | Student | Pedagogy | **CORE** | Production | Med | Full | **KEEP** | 5/6 | **P0** | 루프 student_loop | Low | 1 0 2 0 0 0 | 3 |
| WM-E-409 | 교수전략 선택기·팩 프롬프트 조립·금지모드 가드 | `…/l4/pedagogy` | Student | Pedagogy | **CORE** | Production | Med | Full | **KEEP (매트릭스 REFACTOR)** | 5/6 | **P0** | 루프 student_loop, production_loop | Med | 1 1 2 0 1 1 | 6 |
| WM-E-410 | 적응 교수법 policy(Thompson sampling·안전제약) | `…/l4/pedagogy/adaptive` | Student | Pedagogy | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1** | 승계(P1) | Med | 1 1 1 0 1 1 | 5 |
| WM-E-411 | 오개념 진단·개입·매칭 게이트·distractor 카탈로그 | `…/l4/misconception` | Student | Pedagogy | **CORE** | Production | Med | Full | **KEEP** | 5/6 | **P0** | 루프 student_loop, production_loop | Low | 1 0 2 0 1 0 | 4 |
| WM-E-412 | 활성 오개념 가설·프로브 선택·웜스타트·증거 저장 | `…/l4/misconception` | Student | Pedagogy | **CORE** | Production | Med | Full | **HEAVY_REFACTOR** | 5/6 | **P0** | 루프 student_loop, production_loop | High | 0 2 2 0 3 3 | 10 |
| WM-E-413 | 오개념 의미(임베딩) 매칭 + shadow | `…/l4/misconception, …/l4/misconception/semantic` | Student | Pedagogy | **CORE** | Flag-off | Med | Full | **REFACTOR** | 4/6 | **P1** | 정적(student_loop, production_loop)했으나 Flag-of | Med | 0 1 2 0 1 1 | 5 |
| WM-E-414 | 오개념 방향 판별 LLM-judge + shadow | `…/l4/misconception` | Student | Pedagogy | **CORE** | Flag-off | Med | Full | **REFACTOR (매트릭스 KEEP)** | 4/6 | **P1** | 정적(student_loop)했으나 Flag-off | Low | 0 0 2 0 1 0 | 3 |
| WM-E-415 | 오개념 크로스링크(kebab↔M-id) 후보·트리아지·검수·shadow | `…/l4/misconception` | Admin | Pedagogy | **CORE** | Flag-off | Med | Full | **REFACTOR (매트릭스 KEEP)** | 4/6 | **P1 (←P0)** | 정적(student_loop, production_loop)했으나 Flag-of | Low | 0 0 2 0 0 0 | 2 |
| WM-E-416 | 오답 형태 SymPy 매칭(canonical_wrong_form) + shadow | `…/l4/misconception` | Student | Math Engine | **ADAPTER** | Flag-off | Low | Full | **KEEP** | 5/6 | **P1** | 정적(student_loop)했으나 Flag-off | Low | 0 0 1 0 0 0 | 1 |
| WM-E-417 | 중간 단계 등가성 shadow 관측·평가 | `…/l4` | Student | Pedagogy | **CORE** | Flag-off | Low | Full | **KEEP** | 5/6 | **P1** | 정적(student_loop)했으나 Flag-off | Low | 1 0 0 0 0 0 | 1 |
| WM-E-418 | 학습 장면(LearningScene) DSL·생성·시각화 정책 | `…/l4` | Student | Interaction | **CORE** | Production | Med | Full | **POSTPONE (KEEP)** | 5/6 | **P2** | 승계(P2) | Low | 1 0 2 0 1 0 | 4 |
| WM-E-419 | SubjectAdapter 계약 + 수학 구현 | `…/l4, …/schema` | Platform | AI Orchestration | **MIXED** | Production | Med | Full | **REFACTOR** | 3/6 | **P0** | 루프 student_loop | High | 3 0 2 0 0 0 | 5 |
| WM-E-420 | L4 공용 모델·인터페이스 | `…/l4` | Platform | Pedagogy | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, production_loop | Low | 0 0 0 0 0 0 | 0 |
| WM-E-501 | OCR 파이프라인(검출→라우팅→인식→조립·검증) | `…/api, …/l5/ocr` | Student | Math Engine | **MIXED** | Flag-off | Med | Full | **REFACTOR** | 2/6 | **P1 (←P2)** | 정적(production_loop)했으나 Flag-off | High | 3 0 2 0 0 0 | 5 |
| WM-E-601 | L6 모드 게이팅 로직 5종(재수·학교진도·사고력·메타인지·영재) | `…/l6/gifted, …/l6/metacognition, …/l6/retake, …/l6/school_progress, …/l6/thinking` | Student | Application Mode | **CORE** | Production | Low | Full | **POSTPONE (KEEP)** | 5/6 | **P2** | 승계(P2) | Low | 1 0 1 0 0 0 | 2 |
| WM-E-602 | 수능 모드 게이팅·적응 추천(게이팅×IRT CAT) | `…/l6, …/l6/suneung` | Student | Recommendation | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0 (←P1)** | 루프 student_loop | Low | 1 0 1 0 0 0 | 2 |
| WM-E-603 | 평가 청사진 테스트셋 조립 | `…/l6/blueprint` | Student | Assessment | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop | Low | 1 0 1 0 1 0 | 3 |
| WM-E-701 | WH-S 솔버 하네스(루프·판정·저장소·코퍼스 replay) | `…/whs` | Platform | Math Engine | **INFRA** | Production | Med | Full | **POSTPONE (HEAVY_REFACTOR)** | 4/6 | **P3 (←P1)** | 장기 연구/플랫폼(horizon 선언) | High | 3 2 2 0 3 3 | 13 |
| WM-E-702 | WH-S 자기진화(PRM·SFT 학습셋 export) | `…/whs` | Admin | Math Engine | **INFRA** | Batch | Low | Full | **POSTPONE (REFACTOR)** | 6/6 | **P3 (←P2)** | 장기 연구/플랫폼(horizon 선언) | Med | 1 2 1 0 2 2 | 8 |
| WM-E-703 | bank_solution → SolutionPath 승격 writer | `…/whs` | Admin | Content | **INFRA** | Batch | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0** | 루프 data_supplier(유일 writer | Med | 1 2 1 0 2 2 | 8 |
| WM-E-704 | WH-1 튜터링 하네스(턴 루프·LLM 정책·프로즈·프로브 공급) | `…/harness` | Student | Pedagogy | **INFRA** | Production | High | Full | **REFACTOR** | 4/6 | **P0** | 루프 student_loop, production_loop | Med | 3 0 3 0 1 0 | 7 |
| WM-E-705 | WH-1 shadow 관측·수확·2단계 종료 게이트 | `…/harness` | Platform | QA | **INFRA** | Flag-off | Med | Full | **REFACTOR (매트릭스 KEEP)** | 4/6 | **P1** | 정적(student_loop, production_loop)했으나 Flag-of | Low | 0 0 2 0 1 0 | 3 |
| WM-E-706 | 성장 증거 대리지표 7종·노출 계약·베이스라인 | `…/harness` | Student | Pedagogy | **INFRA** | Production | Med | Full | **HEAVY_REFACTOR** | 5/6 | **P0 (←P1)** | 루프 student_loop | High | 1 2 2 0 2 3 | 10 |
| WM-E-801 | Pydantic 계약 스키마(문항·활동·이벤트·권리 등 40종) | `…/schema` | Platform | Versioning | **MIXED** | Production | Low | Full | **REFACTOR (매트릭스 KEEP)** | 4/6 | **P0** | 루프 student_loop, production_loop | High | 3 0 0 0 0 0 | 3 |
| WM-E-802 | ORM 모델 54종·세션·스키마 버전·alembic | `…/db, …/db/models` | Platform | Versioning | **INFRA** | Production | High | Full | **KEEP** | 5/6 | **P0** | 루프 student_loop, production_loop | Low | 1 0 3 0 0 0 | 4 |
| WM-E-803 | 인증·인가·암호화·레이트리밋·동시성 배관 | `…/api, …/security.py` | Platform | Security | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0** | 루프 student_loop, production_loop, invariant | Med | 1 1 1 0 0 2 | 5 |
| WM-E-804 | OAuth 제공자 구현(카카오·네이버 httpx) | `…/api` | Platform | Identity | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop | Low | 0 0 0 0 0 0 | 0 |
| WM-E-805 | 동의 절차(14세 미만·동의 부여) | `…/consent.py, …/consent_grant.py` | Parent | Security | **INFRA** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 student_loop, invariant | Low | 0 0 0 0 0 0 | 0 |
| WM-E-806 | 디바이스 저장소·서명 실패 metric | `…/api` | Platform | Security | **CORE** | Production | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P0 (←P1)** | 루프 student_loop, production_loop | Med | 0 1 1 0 3 1 | 6 |
| WM-E-807 | 앱 조립·합성 루트·설정·app.state 배관 | `…/api, …/composition.py, …/config.py` | Platform | Operations | **CORE** | Production | Low | Full | **KEEP** | 5/6 | **P0** | 루프 student_loop, production_loop | Low | 3 0 1 0 0 0 | 4 |
| WM-E-808 | 한국어 조사 유틸 | `…/lang` | Platform | Content | **CORE** | Production | Low | Full | **KEEP** | 6/6 | **P0 (←P1)** | 루프 student_loop, production_loop | Low | 0 0 0 0 0 0 | 0 |
| WM-E-809 | 데모 인증(시연 전용 가짜 OAuth provider) | `…/api` | Admin | Identity | **CORE** | Flag-off | Low | Partial | **KEEP** | 5/6 | **P1** | 정적(student_loop)했으나 Flag-off | Low | 0 0 0 1 0 0 | 1 |

### O 운영자 도구 — CLI·배치·게이트 (13행)

| ID | 기능명 | 현재 위치 | 사용자 | Domain | **EOS Ownership** | 상태 | 결합도 | 테스트 | **Migration Action** | §3.4 KEEP | **우선도** | 우선도 근거 | Risk | A B C D E F | 계 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---:|
| WM-O-901 | 개인정보 삭제권·이동권·PEP·감사 writer | `…/privacy` | Student | Security | **INFRA** | Production | High | Full | **HEAVY_REFACTOR** | 5/6 | **P0** | 루프 invariant | High | 1 3 3 0 3 3 | 13 |
| WM-O-902 | PII 보존기한 파기·대화 봉투 암호화 백필 | `…/privacy` | Admin | Security | **INFRA** | Batch | Med | Full | **HEAVY_REFACTOR** | 5/6 | **P0** | 루프 invariant | High | 0 3 2 0 2 3 | 10 |
| WM-O-903 | 서비스 헬스 딥체크·프리플라이트·로그 스크러버 | `…/ops` | Admin | Operations | **INFRA** | Production | Med | Full | **KEEP (매트릭스 REFACTOR)** | 5/6 | **P0** | 루프 production_loop, invariant | Med | 0 0 2 0 3 0 | 5 |
| WM-O-904 | LLM 비용 프로브·비용 리포트 | `…/ops` | Admin | Analytics | **INFRA** | Batch | Med | Full | **KEEP** | 5/6 | **P1 (←P0)** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) | Low | 0 0 2 0 1 0 | 3 |
| WM-O-905 | 12월 검증 스코어카드·QA 혼동행렬·HIT/CU 계측 | `…/ops` | Admin | QA | **INFRA** | Batch | Low | Full | **KEEP** | 6/6 | **P0** | 루프 production_loop | Low | 1 0 1 0 1 0 | 3 |
| WM-O-906 | 콘텐츠 출처·라이선스 감사 게이트·사이드카 | `…/ops` | Admin | Content | **INFRA** | Batch | Low | Full | **KEEP** | 6/6 | **P0** | 루프 production_loop | Low | 1 0 0 0 0 0 | 1 |
| WM-O-907 | 선언≠배선 감사·추천/슬롯 도달 리포트 | `…/ops` | Admin | QA | **INFRA** | Batch | Med | Full | **HEAVY_REFACTOR** | 5/6 | **P1** | 승계(P1) | High | 1 2 2 0 3 3 | 11 |
| WM-O-908 | 운영자 계정 부트스트랩·역할 좌석·shadow 합성 트래픽 | `…/ops` | Admin | Operations | **INFRA** | Batch | Low | Full | **KEEP (매트릭스 REFACTOR)** | 6/6 | **P1** | 승계(P1) | Med | 1 1 1 0 3 1 | 7 |
| WM-O-909 | 동등문제 코퍼스 축적·후처리 배치(36 단원 배치 포함) | `…/harness` | Admin | Content | **INFRA** | Batch | High | Full | **REFACTOR** | 4/6 | **P0** | 루프 production_loop | Med | 3 0 3 0 3 0 | 9 |
| WM-O-910 | 검수 워크플로(HIT 타이머·검수 세션·워크리스트·표본 패키지) | `…/harness` | Admin | QA | **INFRA** | Batch | Med | Full | **HEAVY_REFACTOR** | 4/6 | **P0** | 루프 production_loop | High | 3 1 2 0 3 1 | 10 |
| WM-O-911 | 골든 벤치마크 승격·경로 게이트·앵커 회차 대장 | `…/harness` | Admin | QA | **INFRA** | Batch | Low | Full | **KEEP (매트릭스 REFACTOR)** | 5/6 | **P0** | 루프 production_loop | Med | 3 0 1 0 2 0 | 6 |
| WM-O-912 | QA 파이프라인·강등전 게이트(Wilson·결함주입·금칙어) | `…/harness` | Admin | QA | **INFRA** | Batch | High | Full | **HEAVY_REFACTOR** | 4/6 | **P0** | 루프 student_loop, production_loop | High | 3 1 3 0 2 1 | 10 |
| WM-O-913 | 커버리지·도달률 관측 리포트 가족 | `…/harness` | Admin | Analytics | **INFRA** | Batch | High | Full | **REPLACE_CANDIDATE** | 4/6 | **P1** | 승계(P1) | High | 3 3 3 0 3 3 | 15 |

### C 클라이언트 — Flutter·Web (12행)

| ID | 기능명 | 현재 위치 | 사용자 | Domain | **EOS Ownership** | 상태 | 결합도 | 테스트 | **Migration Action** | §3.4 KEEP | **우선도** | 우선도 근거 | Risk | A B C D E F | 계 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---:|
| WM-C-001 | 로그인·계정 보안 화면·토큰 배관 | `src/mobile/lib/features/auth, src/mobile/lib/core` | Student | Client UX | **CLIENT** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 0 0 0 2 0 | 2 |
| WM-C-002 | 온보딩(학년·학교유형·목표) | `src/mobile/lib/features/onboarding` | Student | Client UX | **CLIENT** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 0 0 0 0 0 | 0 |
| WM-C-003 | 홈·탭 셸·라우팅 | `src/mobile/lib/features/home, src/mobile/lib/app.dart, src/mobile/lib/main.dart, src/mobile/lib/theme` | Student | Client UX | **CLIENT** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_declared | Low | 0 0 0 0 0 0 | 0 |
| WM-C-004 | 코치 채팅(턴·단계 패널·완료 신호) | `src/mobile/lib/features/chat/application, src/mobile/lib/features/chat/data/coach_api.dart, src/mobile/lib/features/chat/data/coach_models.dart, src/mobile/lib/features/chat/data/interaction_logger.dart, src/mobile/lib/features/chat/domain, src/mobile/lib/features/chat/presentation/chat_screen.dart, src/mobile/lib/features/chat/presentation/coach_emphasis_text.dart, src/mobile/lib/features/chat/presentation/coach_signal_card.dart, src/mobile/lib/features/verify` | Student | Client UX | **CLIENT** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 0 0 0 1 0 | 1 |
| WM-C-005 | MathLive 수식 입력(WebView 임베드) | `src/mobile/lib/features/chat/presentation/mathlive_input_screen.dart, src/mobile/lib/features/chat/presentation/mathlive_input_webview.dart, src/mobile/lib/features/chat/presentation/webview_fallback.dart, src/mobile/assets/mathlive_input` | Student | Client UX | **CLIENT** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_declared | Low | 0 0 0 0 3 0 | 3 |
| WM-C-006 | 학습 장면·풀이 경로 렌더러 | `src/mobile/lib/features/chat/presentation/scene_renderer.dart, src/mobile/lib/features/chat/data/scene_api.dart, src/mobile/lib/features/chat/data/scene_models.dart, src/mobile/lib/features/chat/data/solution_path_api.dart, src/mobile/lib/features/chat/data/solution_path_models.dart` | Student | Client UX | **CLIENT** | Production | Low | Full | **KEEP** | 6/6 | **P0 (←P2)** | 루프 seed_route | Low | 0 0 0 0 0 0 | 0 |
| WM-C-007 | 그래핑 계산기(React WebView 임베드) | `src/mobile/lib/features/chat/presentation/graphing_calculator_webview.dart, src/mobile/assets/graphing_calculator, src/web/graphing-calculator` | Student | Client UX | **CLIENT** | Production | Low | Full | **KEEP** | 6/6 | **P0 (←P2)** | 루프 seed_route | Low | 0 0 0 0 3 0 | 3 |
| WM-C-008 | 진단·문제 풀기 화면 | `src/mobile/lib/features/problems` | Student | Client UX | **CLIENT** | Production | Low | Full | **KEEP** | 6/6 | **P0** | 루프 seed_route | Low | 0 0 0 0 0 0 | 0 |
| WM-C-009 | 손글씨 촬영·OCR 캡처 | `src/mobile/lib/features/ocr` | Student | Client UX | **CLIENT** | Flag-off | Low | Full | **POSTPONE (KEEP)** | 5/6 | **P2** | 승계(P2) | Low | 0 0 0 0 0 0 | 0 |
| WM-C-010 | 나(프로필)·성장 증거 탭 | `src/mobile/lib/features/profile` | Student | Client UX | **CLIENT** | Production | Low | Full | **KEEP** | 6/6 | **P0 (←P1)** | 루프 seed_route | Low | 0 0 0 0 0 0 | 0 |
| WM-C-011 | 탐구(Explore) 탭 | `src/mobile/lib/features/explore` | Student | Client UX | **CLIENT** | Production | Low | Partial | **POSTPONE (KEEP)** | 6/6 | **P2** | 승계(P2) | Low | 0 0 0 1 0 0 | 1 |
| WM-C-012 | 결함 신고 버튼 | `src/mobile/lib/features/reports` | Student | Client UX | **CLIENT** | Production | Low | Partial | **KEEP** | 6/6 | **P1** | 승계(P1) | Low | 0 0 0 1 1 0 | 2 |

---

## §4. 판정이 말하는 것

### ① MIXED 10행 — 과목 경계가 실제로 지나는 자리

| 행 | 무엇이 섞였나 | 소유 태스크 |
|---|---|---|
| WM-E-801 Pydantic 계약 스키마 | `schema.problem`·`enums`·`answer_submission`·`ocr`·`speech`·`student_solution_step` 6모듈 MIXED | S1-16 착지 후에도 legacy 필드 양방향 동기화 — CORE 승격은 breaking(EOS-65 §2) |
| WM-E-355 단계·풀이 연쇄 검증 | `verify_step/solution/verifier`(ADAPTER) + `verification_tier`(MIXED) | S4-55 검증 등급 개편 |
| WM-E-407 검산 코칭 오케스트레이터 | `l4.solution_coaching` 자체 MIXED(L3→L4 결선) | EOS-69 잔여(호출부 능력 주입) |
| WM-E-419 SubjectAdapter 계약+구현 | 계약(CORE)과 수학 구현(ADAPTER)을 **의도적으로** 한 행에 | 설계상 MIXED — 분리 불필요(EOS-66). 두 번째 과목 구현이 붙을 때 행을 가른다 |
| WM-E-307 DSL 생성기 | `l3.dsl` 골격 범용·`variable_engine`·`validators` 수식 전제 | 미등재 — C2가 12월 경로라 P0인데 소유자 없음(§6-②) |
| WM-E-306 pre-warm | 시드 검증이 SymPy 경유 | 미등재(P1) |
| WM-E-359 수식 낭독 | `l3.speech`(ADAPTER)+`l4.speech`(MIXED) | POSTPONE(P2) |
| WM-E-501 OCR 파이프라인 | `l5.ocr`(ADAPTER)+`api.ocr_handoff`(api 기본 CORE) | POSTPONE(P2) — 배정 정정 후보(§6-①) |
| WM-E-110 공식 그래프 · WM-E-112 전략 그래프 | 적재 기계 범용·엔티티 수학 | POSTPONE(P2) |

**Physics를 붙일 때 뜯어야 하는 Core는 이 10행 안에 있다.** 그중 12월 경로(P0)는 4행(801·355·
407·419)이고 419는 설계상 MIXED라 실질 3행이다.

### ② CORE+ADAPTER_DEP 3행 — EOS-69가 남긴 정확한 잔여

`WM-S-029` verify 표면 → `l3.verify_answer/solution/step` · `WM-S-046` OCR 표면 → `l5.ocr.pipeline`
· `WM-S-047` speech 표면 → `l3.speech`. EOS-69가 15건 위반을 0으로 갚을 때 **라우터 모듈 자체는
MIXED로 배정**해 계약 밖에 뒀다(`api.verify`·`api.ocr`·`api.speech`). 그래서 import-linter는
초록인데 이 장부는 의존을 본다 — 두 계측기의 시야 차이지 모순이 아니다. 절단 방법은 같다:
`SubjectAdapter.evaluate_answer()` 경유(EOS-66 계약이 이미 있다).

### ③ REPLACE_CANDIDATE 1건(WM-O-913 · 15점)은 재작성 대상이 아니다

관측 리포트 14 CLI를 한 가족으로 묶은 행이다. A=3(verify_answer 참조)·B=3·C=3·E=3·F=3 — **가족
합산 효과**로 만점 근처가 됐다. v1이 `coach` 14점에 대해 적은 것과 같은 결론: 계획서 100 자신이
"REPLACE는 경계를 복구할 수 없을 때만"이라 했으므로 이것은 *쪼개서 다시 재라*는 신호다. 치료는
OPS-19(러너 배선 — 리포트 11개 중 10개가 러너 0건)이며 이미 등재되어 있다.

### ④ HEAVY_REFACTOR 12행 — 전부 "비대함"이고 수학은 아니다

| 행 | 총점 | 원인 축 |
|---|---:|---|
| WM-E-701 WH-S 솔버 하네스 | 13 | A3(verify 3종 직접 호출)·B2·E3·F3 — INFRA인데 학생 대면 아님, 솔버 자기진화 |
| WM-O-901 privacy 삭제·이동·PEP·감사 | 13 | B3·C3·E3·F3 — 삭제권이 *모든* 학생 테이블을 알아야 하는 구조적 비대 |
| WM-E-106 성취기준·앵커 레지스트리 | 11 | B3·E3·F3 — 적재기 + ETL 2패키지 합산 |
| WM-O-907 선언≠배선 감사·도달 리포트 | 11 | |
| WM-E-102 구 개념그래프 | 10 | E3 — 원자 축 이전 후 보조. **삭제 후보인데 P1로 남아 있다**(§6-③) |
| WM-E-109 문제은행 적재 | 10 | |
| WM-E-208 학습 지표 롤업 | 10 | E3 — 914줄 단일 writer |
| WM-E-412 오개념 가설·프로브·증거 저장 | 10 | |
| WM-E-706 성장 증거 대리지표 | 10 | `wh1_evaluation` 1,953줄 |
| WM-O-902 PII 파기·백필 · WM-O-910 검수 워크플로 · WM-O-912 QA 게이트 | 10 | |

12행 중 **A축 3점은 701 하나**다. 나머지는 DB·상태변경·가족 크기다 — 계획서 100 §3.4의 처방
("분리하면 된다")이 그대로 적용되며, 재작성 근거는 없다.

### ⑤ KEEP 83행(51%) — v1의 REFACTOR 74%와 뒤집힌 이유

v1은 라우터 단위라 유틸·순수 함수가 표에 없었고(v1 §4-⑤ 자인), 기능 단위로 내리면 L4 교수학
엔진(Polya·소크라테스·LTHC·힌트·톤필터 — 전부 0~2점)·L3 어댑터 primitive(동치·검산 — 0~1점)
같은 **작고 순수한 행**이 들어온다. 계획서 100 §3.4의 예상("40~60%가 REFACTOR")과 이 표의
REFACTOR+HEAVY 34%는 모집단 정의 차이로 설명된다 — 방향(REPLACE ≈ 0)은 세 표가 일치한다.

### ⑥ 상태 실측 — Flag-off 11행

`ocr_enabled=False`(S-046·E-501·C-009) · 오개념 4축 shadow 전부 off(E-413~417) · WH-1 shadow off
(E-705) · `parental_consent_grant_enabled=False`(S-007) · `demo_auth_enabled=False`(E-809). 이 중
**S-007 법정대리인 동의가 P0인데 Flag-off**다 — 결함이 아니라 법령 게이트(MGMT-01 변호사 자문
선행)라 의도된 OFF지만, 12월 검증의 학생 표본(G4 ≥20명)에 14세 미만이 있으면 이 플래그가
켜져야 하고 그 조건은 이 장부가 아니라 `G-*` 게이트 대장이 소유한다.

### ⑦ §3.4 기준이 매트릭스를 뒤집은 38행 — 방향이 둘이다

**REFACTOR → KEEP 33행**: 매트릭스 5~9점이지만 §3.4 KEEP 6조건 중 5~6개를 만족하는 행. 점수가
올라간 이유가 DB 모델 수·쓰기 엔드포인트 수(B·E·F축 — *크기*)였고 경계 위반(k1·k4·k5)이 아니었다.
예: WM-S-017 IRT θ(B2·F2·6점) · WM-E-201 BKT(B2·E2·F2·8점) · WM-E-205 추천 5모듈. 계획서 100
§3.4의 KEEP 정의("과목 의존 낮음·API 명확·테스트 존재·모델 비충돌·결합 낮음·검증됨")에 그대로
들어맞으므로 KEEP이 맞다 — 매트릭스는 *옮기는 수고*를 재고 §3.4는 *옮길 이유*를 묻는다.

**KEEP → REFACTOR 5행**: 매트릭스 0~4점(작다)인데 §3.4 조건이 깨진 행 — WM-E-307 DSL 생성기·
WM-E-801 계약 스키마(k1·k4: MIXED) · WM-E-414 judge·WM-E-415 crosslink·WM-E-705 WH-1 shadow
(k5·k6: 결합 + Flag-off라 "실제 동작 검증됨"이 성립하지 않는다). 작아도 경계가 깨졌으면 REFACTOR다.

**최종 REFACTOR 16행 전수 — 전부 §3.4의 "EOS 경계 위반" 정의에 해당한다**:

| 행 | Ownership | 매트릭스 | 미충족 KEEP 조건 |
|---|---|---:|---|
| WM-S-007 법정대리인 동의 기록·철회·조회 | CORE | 7 | k5_coupling_low, k6_verified |
| WM-S-009 개인정보 처리 권한 판정(PEP) | CORE | 7 | k3_tests_exist, k6_verified |
| WM-S-040 권리(저작권) 판정 게이트웨이 | CORE | 6 | k3_tests_exist, k6_verified |
| WM-E-306 빌드타임 캐시 사전생성(pre-warm)·시드 검증 | MIXED | 7 | k1_subject_low, k4_model_ok, k5_coupling_low |
| WM-E-307 DSL 콘텐츠 생성기(컴파일·검증·복구·변수 엔진) | MIXED | 3 | k1_subject_low, k4_model_ok |
| WM-E-355 단계·풀이 연쇄 검증·검증 등급 | MIXED | 5 | k1_subject_low, k4_model_ok, k5_coupling_low |
| WM-E-407 풀이 계산오류 → 검산 코칭 오케스트레이터 | MIXED | 5 | k1_subject_low, k4_model_ok, k5_coupling_low |
| WM-E-413 오개념 의미(임베딩) 매칭 + shadow | CORE | 5 | k5_coupling_low, k6_verified |
| WM-E-414 오개념 방향 판별 LLM-judge + shadow | CORE | 3 | k5_coupling_low, k6_verified |
| WM-E-415 오개념 크로스링크(kebab↔M-id) 후보·트리아지·검수·shadow | CORE | 2 | k5_coupling_low, k6_verified |
| WM-E-419 SubjectAdapter 계약 + 수학 구현 | MIXED | 5 | k1_subject_low, k4_model_ok, k5_coupling_low |
| WM-E-501 OCR 파이프라인(검출→라우팅→인식→조립·검증) | MIXED | 5 | k1_subject_low, k4_model_ok, k5_coupling_low, k6_verified |
| WM-E-704 WH-1 튜터링 하네스(턴 루프·LLM 정책·프로즈·프로브 공급) | INFRA | 7 | k1_subject_low, k5_coupling_low |
| WM-E-705 WH-1 shadow 관측·수확·2단계 종료 게이트 | INFRA | 3 | k5_coupling_low, k6_verified |
| WM-E-801 Pydantic 계약 스키마(문항·활동·이벤트·권리 등 40종) | MIXED | 3 | k1_subject_low, k4_model_ok |
| WM-O-909 동등문제 코퍼스 축적·후처리 배치(36 단원 배치 포함) | INFRA | 9 | k1_subject_low, k5_coupling_low |

네 묶음으로 읽힌다: **MIXED 7행**(k1·k4 — Core/Adapter 분리, OCR 파이프라인 포함) · **수학 직접 호출 2행**
(WM-E-704 WH-1·WM-O-909 코퍼스 배치) · **Flag-off/Shadow 4행**(k6 — 켜지기 전엔 "검증됨"이 아니다) ·
**서빙 표면 테스트 0 2행**(S-009 PEP·S-040 rights — k3·k6) + S-007 법정대리인 동의(결합·Flag-off). REPLACE
신호 2개인 행은 3건(WM-E-102 중복+상태미추적 · WM-E-701 과목침투+상태미추적 · WM-E-801 모델충돌+과목침투)이고
3개 이상은 0 — §3.4 기준으로도 REPLACE 선고 대상은 없다(매트릭스 15점 WM-O-913만 CANDIDATE).

계획서 100 §3.4의 "REFACTOR 40~60%" 예상과 이 표의 REFACTOR+HEAVY 17%(27/162)가 다른 이유:
저장소가 EOS-65~69로 Core→Adapter 정적 의존을 이미 0으로 갚았고(`l2`·`l6` 수학 신호 0), §3.4의
REFACTOR 정의가 정확히 그 위반이기 때문이다. 예상은 *경계 작업 이전* 코드베이스를 전제한 숫자다.

---

## §5. Ownership × Action 교차표

| Ownership \ Action | KEEP | REFACTOR | HEAVY | REPLACE 검토 | POSTPONE | 계 |
|---|---:|---:|---:|---:|---:|---:|
| CORE | 86 | 6 | 5 | 0 | 11 | 108 |
| INFRA | 9 | 3 | 6 | 1 | 2 | 21 |
| CLIENT | 10 | 0 | 0 | 0 | 2 | 12 |
| MIXED | 0 | 7 | 0 | 0 | 3 | 10 |
| ADAPTER | 7 | 0 | 0 | 0 | 1 | 8 |
| CORE+ADAPTER_DEP | 1 | 0 | 0 | 0 | 2 | 3 |

읽는 법: **HEAVY 11건 중 6건이 INFRA**고 **MIXED 10행은 KEEP이 0**이다(P0 6행 전부 REFACTOR). 이전 난이도의 무게 중심은 Core 로직이 아니라 운영·
privacy·검수 인프라에 있다 — EOS 전환에서 "Core를 뜯는 일"보다 "인프라 가족을 쪼개는 일"이
크다는 뜻이다. ADAPTER 8행은 KEEP 7 — 수학 엔진은 *그대로 Math Adapter 패키지로 이동*하면 된다.

---

## §6. 이 장부가 새로 드러낸 것 (등재 여부는 Kiki 판정)

1. **`api._*` 배관 모듈의 배정 공백** — BOUNDARY_MAP은 `api._ocr_state`만 INFRA로 명시하고
   나머지 `api._auth`·`_crypto`·`_rate_limit`·`_l3_state`·`_misconception_state` 등은 `api`
   기본값 CORE를 물려받는다. 그 결과 WM-E-803(인증·암호화 배관)·WM-E-807(app.state 배관)이
   CORE로 판정됐다 — 성격은 INFRA다. **EOS-65 정본 보강 후보**(스크립트 `BOUNDARY_MAP`에 `api._`
   접두 규칙 1줄). 이 장부는 정본을 고치지 않고 정본이 낸 값을 그대로 적었다.
2. **WM-E-307 DSL 생성기(MIXED·P0)에 소유 태스크가 없다.** C2는 "이미 구현"(EOS-53 crosswalk)
   이지만 Core/Adapter 분리 축은 어느 태스크도 들고 있지 않다. `l3.dsl.variable_engine`·
   `validators`·`math_verifier`를 ADAPTER로 배정 정정하는 것만으로 MIXED가 해소될 수 있다
   (파일 단위 배정 선례: `wrong_form_match`).
3. **WM-E-102 구 개념그래프(HEAVY·P1)** — 원자 축 이전(S0-2·ARCH-13) 뒤 보조 좌석인데 E3(변이
   호출 다수)·10점이다. 12월 검증이 이 축을 밟지 않으면 **P2 강등 + POSTPONE**이 맞다(제안).
4. **학생 대면 엔진이 INFRA에 산다** — WM-E-704 WH-1 튜터링 하네스(`harness.wh1_primary` ·
   `wh1_primary_enabled=True` · 학생 발화 생산자)가 `harness` 패키지에 있어 BOUNDARY_MAP이
   INFRA("측정·배치 하네스")로 본다. 계층 계약 밖이라 CORE→ADAPTER 위반 감시도 받지 않는다
   (실측 A=3: `l3.equivalent.rephrase`·`l3.verify_solution` 직접 호출). EOS-65 배정 정정(런타임
   6모듈을 CORE로) 또는 `l4`로 이동 — 어느 쪽이든 **감시 밖에 있는 학생 대면 코드**라는 사실이
   먼저다.
5. **서빙 표면 테스트 0건 2행** — WM-S-009 privacy PEP·WM-S-040 rights 게이트웨이. 둘 다 P0이고
   둘 다 *엔진*(O-901·E-115)에는 테스트가 있는데 **HTTP 표면**을 경로 리터럴로 치는 테스트가
   없다. S-040은 v1이 이미 검출(LIC-01 소유). S-009는 신규 검출.

---

## §7. P0~P3 재분류 — 질문 하나로 (계획서 100 §3.x Scope Freeze)

> *"이 기능이 없으면 12월 31일 수학 EOS의 폐쇄루프가 깨지는가?"* — YES면 P0. 필요/불필요로 나누지
> 않는다. 이 절은 그 질문을 **import 도달성**으로 기계가 답하게 한 결과다.

### 7.1 모집단 — "270개"는 저장소에 없다

| 저장소 안의 모집단 | 크기 | 지위 |
|---|---|---|
| 계획서 "EOS 후보 270개" | — | **외부 xlsx**(선행 대조 §6-1·P0-03). 대조 불가 |
| 전환 선언 부록 A crosswalk(EOS-53) | 53행 · T1 33 / T2 12 / T3 6 / T4 10 | 계획 기능의 저장소 대체 모집단. Tier가 이미 P0~P3에 대응(T1 = 12월 필수) — 새 증거가 없어 재판정하지 않는다 |
| backlog 태스크 `eos_priority`(EOS-80 백필) | P0 16 / P1 85 / P2 95 / P3 16 · 미기재 302(대부분 done) | *작업* 단위 — 기능 단위가 아니다 |
| **이 장부 162행(기존 기능)** | 아래 | 이 절의 대상 |

### 7.2 규칙 — P0는 다섯 가지 증거 중 하나 (2차 검토로 두 사각을 기계로 메움)

폐쇄루프의 **씨앗**을 코드 좌표로 고정하고(생성기 상수 · 실재하지 않으면 exit 1), 씨앗에서 import
간선을 따라 닿는 모듈을 BFS로 모은다(패키지 재수출은 심볼 단위로 풀어 `l6` import가 L6 전부로
번지지 않게 했다). 행의 자기 모듈이 그 집합에 있으면 "없으면 깨진다".

| 증거 | 정의 | 출처 |
|---|---|---|
| `seed_route` | 행의 엔드포인트가 씨앗 경로 자체 · 클라 소스에 씨앗 경로 리터럴 실재 | 학생 루프 25경로 = 계획서 300 §12 API ↔ 저장소 대응표 · 생산 루프 5경로 = `/v1/generate`·`/v1/dsl/*` |
| `student_loop` / `production_loop` | 씨앗에서 정적 도달(학생 207모듈 · 생산 169모듈) — **app.state DI 다리 포함**: app.py의 `app.state.__setattr__(KEY, expr)` 20개 키를 파싱해 KEY 상수를 참조하는 엔드포인트(헬퍼 `api._l3_state` 경유 포함)에 배선 모듈을 의존으로 더한다 | 생산 씨앗 모듈 10 = 선언 부록 E G1~G3·G5 차단 조건의 집행 지점(코퍼스 축적·HIT 타이머·검수큐·QA 파이프라인·골든·회차 대장·provenance·스코어카드) |
| `data_supplier` | ① L1 적재기가 루프가 읽는 테이블을 채운다 ② **2패스**: 루프 테이블 28개 중 P0 writer가 하나도 없는 테이블의 writer(Flag-off·이월 선언·P3 제외)를 P0로 | 데이터가 없으면 루프는 빈 화면이다. ②로 승격된 것은 SolutionPath 승격 writer(E-703) 1건 — 남은 P0-writer-없는 테이블은 `misconception_embedding`(writer가 Flag-off) 하나 |
| `invariant` | 불변 계약 *구현*(privacy·consent·rights·반출 게이트·Langfuse·스크러버) + 인증 배관 자체 | 선언 §0-6 |
| `seed_declared` | import 그래프에 안 잡히는 진입점 — 앱 셸·MathLive 입력 | 카탈로그 선언 **2건**(OAuth provider는 DI 다리로 기계 도달해 선언을 제거했다) |

보정 1개: **정적으로 닿았지만 플래그가 꺼진 기능은 P0가 아니다**(P1 "우회 가능") — import는 되지만
런타임에 실행되지 않는 코드가 없어져도 루프는 돌아간다(7행: 오개념 shadow 4축·step shadow·WH-1
shadow·OCR). P3는 카탈로그 `horizon` 선언으로만 생긴다(WH-S 솔버·자기진화 2행 — 장기 연구). P1/P2
경계는 선행 제안(v2.0)을 승계하되 **선행 P0인데 기계가 닿지 못한 행은 P1로 강등**한다.

### 7.3 결과

| 우선도 \ Action | KEEP | REFACTOR | HEAVY | REPLACE 검토 | POSTPONE | 계 |
|---|---:|---:|---:|---:|---:|---:|
| P0 | 81 | 11 | 9 | 0 | 0 | 101 |
| P1 | 32 | 5 | 2 | 1 | 0 | 40 |
| P2 | 0 | 0 | 0 | 0 | 19 | 19 |
| P3 | 0 | 0 | 0 | 0 | 2 | 2 |

P0 101행의 근거 분포(중복 가능): {'seed_route': 26, 'invariant': 13, 'student_loop': 55, 'data_supplier': 11, 'production_loop': 43, 'seed_declared': 2}. **P0 중 KEEP 81(80%)** — 12월 경로의 대부분은 옮기지
않아도 되고, P0에 REPLACE 검토는 0이다. POSTPONE 21 = P2 19 + P3 2.

### 7.4 선행 제안(v2.0)과 어긋난 26행

| 행 | 선행 → 기계 | 근거 |
|---|---|---|
| WM-S-017 IRT 능력(θ) 추정·스냅샷·성장 곡선 | P0 → **P1** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) |
| WM-S-027 교수학 통합 결정(stateless 코치) | P0 → **P1** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) |
| WM-S-037 교육과정 프레임워크·버전·노드 조회 | P0 → **P1** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) |
| WM-S-038 성취기준(학습 성과) 단건 조회 | P0 → **P1** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) |
| WM-S-039 개념↔성취기준 정렬 통합 조회 | P0 → **P1** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) |
| WM-E-102 구 개념그래프 적재·임베딩·검색 | P1 → **P0** | 폐쇄루프: student_loop, production_loop, data_supplier |
| WM-E-103 개념↔원자 크로스워크 이전 | P1 → **P0** | 폐쇄루프: production_loop, data_supplier |
| WM-E-117 임베딩 제공자 셀렉터(bge-m3·OpenAI·fake) | P1 → **P0** | 폐쇄루프: student_loop, production_loop |
| WM-E-304 QUALITY 티어 비동기 큐(Celery) | P1 → **P0** | 폐쇄루프: student_loop, production_loop |
| WM-E-306 빌드타임 캐시 사전생성(pre-warm)·시드 검증 | P1 → **P0** | 폐쇄루프: student_loop, production_loop |
| WM-E-309 교수 콘텐츠 슬롯 파이프라인(생성→예심→검수) | P0 → **P1** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) |
| WM-E-311 독립 다관점 LLM 교차검증 | P1 → **P0** | 폐쇄루프: student_loop |
| WM-E-356 SymPy 불가 영역 검산(유한확률 전수·통계 자료형) | P1 → **P0** | 폐쇄루프: student_loop, production_loop |
| WM-E-403 LTHC 적응(진입점·확장·비계) | P1 → **P0** | 폐쇄루프: student_loop |
| WM-E-415 오개념 크로스링크(kebab↔M-id) 후보·트리아지·검수·s | P0 → **P1** | 정적 도달(student_loop, production_loop)했으나 Flag-off — 우회 가능 |
| WM-E-501 OCR 파이프라인(검출→라우팅→인식→조립·검증) | P2 → **P1** | 정적 도달(production_loop)했으나 Flag-off — 우회 가능 |
| WM-E-602 수능 모드 게이팅·적응 추천(게이팅×IRT CAT) | P1 → **P0** | 폐쇄루프: student_loop |
| WM-E-701 WH-S 솔버 하네스(루프·판정·저장소·코퍼스 replay) | P1 → **P3** | 장기 연구/플랫폼(horizon 선언) |
| WM-E-702 WH-S 자기진화(PRM·SFT 학습셋 export) | P2 → **P3** | 장기 연구/플랫폼(horizon 선언) |
| WM-E-706 성장 증거 대리지표 7종·노출 계약·베이스라인 | P1 → **P0** | 폐쇄루프: student_loop |
| WM-E-806 디바이스 저장소·서명 실패 metric | P1 → **P0** | 폐쇄루프: student_loop, production_loop |
| WM-E-808 한국어 조사 유틸 | P1 → **P0** | 폐쇄루프: student_loop, production_loop |
| WM-O-904 LLM 비용 프로브·비용 리포트 | P0 → **P1** | 선행 P0 → 강등: 폐쇄루프 미도달(우회 가능) |
| WM-C-006 학습 장면·풀이 경로 렌더러 | P2 → **P0** | 폐쇄루프: seed_route |
| WM-C-007 그래핑 계산기(React WebView 임베드) | P2 → **P0** | 폐쇄루프: seed_route |
| WM-C-010 나(프로필)·성장 증거 탭 | P1 → **P0** | 폐쇄루프: seed_route |

**읽는 법**:
- **강등 8행(P0→P1)** 중 다섯이 *조회 API*다 — 교육과정·성취기준·정렬 조회(S-037~039), IRT θ 표시(S-017),
  stateless 코치(S-027). 계획서 100의 P0 예시에 "Curriculum"이 있지만 루프가 밟는 것은 **데이터**(L1
  적재기 E-105·106·108 → `data_supplier`로 P0 유지)이고 **운영자 조회 API**는 우회 가능하다. 슬롯 파이프라인
  (E-309)·비용 리포트(O-904)는 생산 게이트의 집행 지점이 아니다. 오개념 크로스링크(E-415)는 정적으로
  닿지만 Flag-off라 P1.
- **2차 검토로 정정된 2행**: SolutionPath 승격 writer(E-703)는 1차에 `whs` 소속이라 P1이었다 — 실측하니
  `solution_path` 테이블의 writer가 E-703과 E-357(다중 풀이·C6 이월)뿐이고 읽기 표면(S-032 점층 공개, 클라
  step panel이 호출)은 "쓰기는 승격 어댑터만 한다"고 자인한다. 12월 앵커 신규 문항의 풀이 경로는 이 writer
  없이는 테이블에 실리지 않는다 → 2패스 규칙으로 **P0**. OAuth provider(E-804)는 1차에 손 선언 씨앗이었다 —
  app.py의 `app.state.__setattr__` 배선 20개 키를 파싱하는 DI 다리로 **기계 도달**(auth callback이
  `OAUTH_PROVIDERS_KEY`를 참조)해 선언을 제거했다. 같은 다리로 Celery 큐(E-304)가 `/v1/jobs` 경로의 의존으로
  드러나 P0가 됐다(OPS-27 워커 미배포 — P0인데 배포가 없다는 뜻).
- **승격 14행(P1/P2→P0)**은 전부 정적 도달·DI 다리·유일 writer 실측이다. 주목할 셋: **WM-E-102 구 개념그래프** — 중복
  (`duplicate_of` E-101)인데 학생·생산 루프가 여전히 밟고 루프 테이블을 채운다(교체 전까지는 P0가 맞다);
  **WM-E-306 pre-warm** — 코치가 `l3.pregenerate.validator`를 import한다(배치 도구 안에 런타임 검증
  모듈이 산다 — 귀속 위치 문제); **WM-E-311 교차검증·WM-E-356 비대수 검산** — verifier 경로가 정적으로
  물고 있다.
- **클라 3행(C-006·007·010 → P0)**: 소스에 씨앗 경로 리터럴이 실재한다 — 풀이 경로 단계·`/verify-answer`
  (그래핑 계산기)·약개념/진단 표시(프로필). 화면이 루프 API를 부르면 그 화면이 없을 때 루프가 깨진다.

### 7.5 계획서 100 P0 예시 16종과의 대조

| 계획서 P0 | 이 장부 | 판정 |
|---|---|---|
| Curriculum · Concept · Skill · Problem · Misconception | E-105/106 · E-101/104 · E-111 · E-109 · E-107 전부 P0(`data_supplier`) | 일치 — 단 *조회 API*는 P1 |
| Solution · Hint | E-312 SolutionPath·S-032 점층 공개·E-404 힌트 지연 P0 | 일치. 승격 writer E-703은 P1(§7.4) |
| LearnerState · Assessment · Mastery Update | E-204·S-012·S-018·E-201·S-015·S-016 P0 | 일치 |
| Recommendation · AI Tutor 기본 | E-205·S-019~021 · E-401~406·S-028·E-704 P0 | 일치 |
| Content Version · QA | E-314 프롬프트 자산·E-802 스키마/alembic P0 · O-905·910·911·912 P0 | 일치 |
| User/Auth · Event Logging | S-003/004·E-803/804 P0 · E-206·S-015 P0 | 일치 |

16종 모두 P0 행을 갖는다. 계획서 P1 예시 중 **문제 자동 생성**은 이 저장소에서 **P0**다 — G2(10/25)
차단 조건이 "중등 2앵커 각 60 CU"라 생성 배치(O-909)와 생성 파이프라인(E-351)이 게이트 집행 지점이기
때문이다. 난이도 보정(E-203)·교수전략 추천(E-410)·설명 선택(E-310)은 계획서대로 P1이다.

---

## §8. 정직한 공백

1. **카탈로그의 귀속은 사람이 적었다.** 어느 모듈이 어느 기능인지는 판단이다. 기계가 보장하는
   것은 *빠짐과 중복이 없다*는 것이지 *묶음이 옳다*는 것이 아니다. 묶음을 바꾸면 B~F 점수가
   바뀐다(가족 합산 효과 — §4-③).
2. **D축(테스트)은 파일 단위**라 한 테스트 파일이 여러 행에 계상된다. 행 간 상대 비교용이며
   절대 커버리지가 아니다. 커버리지 정본은 `scripts/coverage/check_layer_coverage.py`.
3. **1-hop만 본다.** 동적 import·문자열 참조·DI 컨테이너 경유는 A·B·C축 사각이다(EOS-65 §4 한계
   동일).
4. **P1/P2 경계와 P3 선언은 아직 사람 판단**이고 그에 종속된 POSTPONE 21건도 그렇다(P0만 기계). Kiki가 P를 바꾸면 Action이
   따라 바뀐다 — 그래서 `matrix_action`을 따로 보존했다.
5. **"이동 계획"(어디로·언제)은 여전히 비어 있다** — v1 §7-1과 같다. 이 장부는 *무엇을·얼마나
   어렵게*까지다. 일정은 G0 이후 주간 계획이 소유하며 여기서 지어내지 않는다.
6. **120 정합은 판정 불가** — §1.
7. **P0 도달성은 정적 import + app.state DI 다리다** — `__setattr__(KEY, …)` 패턴 20개 키는 기계로 잇는다. 그 밖의 주입(FastAPI `Depends` 팩토리·클로저)은 여전히 사각일 수 있다. "정적 참조 ≠ 실행"은 실측했다: 정적 도달만으로 P0인 48행의 import 사용처를 AST로 검사한 결과 **플래그(`settings.*`) 조건문 안에서만 참조되는 행 0·import만 하고 안 쓰는 행 0** — Flag-off 보정 7행 외의 죽은 참조는 이 휴리스틱으로는 발견되지 않았다(런타임 `getattr` 게이트는 못 본다). `data_supplier`는 2패스로 `l1.` 밖까지 넓혔고, 남은 P0-writer-없는 루프 테이블은 `misconception_embedding`(writer Flag-off) 하나다.
8. **§3.4의 "수정 비용 > 재작성 비용"은 측정하지 않았다** — REPLACE 신호 6종은 측정 가능분이고 비용
   비교는 사람 판단으로 남긴다. r5(상태 변이 추적)는 모듈명 패턴 대리지표라 이름이 다른 감사 writer를
   놓칠 수 있다(거짓 신호 방향 — 그래서 단독 신호로는 아무 판정도 바꾸지 않는다).

## §9. 다음 검토일

EOS-65 `BOUNDARY_MAP` 정정(§6-①·④) 또는 S1-16 legacy 필드 제거 착지 시 재생성(`--write`).
MIXED 10 → 몇으로 줄었는지가 첫 실측이 된다.
