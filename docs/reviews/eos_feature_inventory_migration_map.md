# EOS 기능 인벤토리 + Migration Difficulty Matrix v1 (EOS-68)

> **지위**: `EOS-68-feature-inventory-migration-map` 산출물. 계획서 100 §3.3(인벤토리 필드)·
> §3.14(6축 18점 매트릭스)의 저장소 적용이며, **Gate 0-D(Migration) 판정 재료**다.
>
> **장부 정본은 이 문서가 아니라 기계다** — 생성기 `scripts/analysis/eos_feature_inventory.py`
> (점수 임계·메타의 단일 진실 원천) → 장부 `backlog/inventory/feature_inventory.yaml`(기계가
> 읽는 표·acceptance ③). 본 문서는 전사·해설이다. 재생성:
> `python3 scripts/analysis/eos_feature_inventory.py --write`
>
> 대조 시점: 2026-08-31 · 브랜치 `claude/review-status-differences-jw5m4a`(EOS-65~67 착지 후).
>
> **v2 관계 (2026-09-03 · EOS-83)**: 이 문서의 모집단은 *라우터 단위* 23행이며 §1이 자인한 대로
> 행 수는 **하한**이다. 계획서 100 §3.3의 "기능" 단위(약 120개)로 내린 전수 장부는
> `docs/reviews/eos_feature_inventory_v2_2026-09-03.md`(생성기 `eos_feature_inventory_v2.py` ·
> 장부 `backlog/inventory/feature_inventory_v2.{yaml,csv}`)다. 두 장부는 **대체가 아니라 두 해상도**다 —
> Gate 0-D 4문항은 이 문서(라우터 해상도)로 판정하고, EOS Ownership·Migration Action의 행별
> 판정은 v2(기능 해상도)를 읽는다. 6축 임계는 v2가 이 생성기에서 import하므로 정본은 하나다.

---

## §1. 모집단 정의 (acceptance ① 선결)

**기능 = FastAPI 앱에 실제로 등록된 서빙 표면 1단위.** `app.py`의 `include_router()` 호출
22건을 파싱해 기계로 도출하고, `app.py` 자체 엔드포인트(health·status·`/v1/generate`·
`/v1/jobs`)를 `app-core` 1건으로 더해 **모집단 23**이다.

**모집단이 아닌 것** (경계를 명시해야 "전수"가 성립한다):
- `backlog/` 456태스크 — *작업* 단위이지 기능 단위가 아니다(acceptance ①이 명시 배제)
- `harness/` 72모듈·`scripts/` CLI — 운영자 도구·배치. 학생·관리자에게 서빙되지 않는다
- Flutter 앱·web — 클라이언트는 View Layer(수학 로직 미포함 원칙)라 이전 대상이 백엔드 표면과 동일
- WS·cron 등 비HTTP 서빙 — 현재 0건 실측. 생기면 생성기 파서와 이 정의를 함께 고친다

계획서 100의 "기존 120개 기능"과 수가 다른 이유: 그쪽 모집단(원본 xlsx)은 저장소 외부라 대조
불가하고(선행 대조 문서 §6-1), 이쪽은 **재현 가능한 정의**를 우선했다. 라우터 1개가 계획서
기준 여러 "기능"일 수 있으므로(예: `me`는 36 엔드포인트) 이 표의 행 수는 하한이다.

## §2. 방법 — 6축을 감이 아니라 대리지표로

계획서 100 §3.13의 목적 그대로 — *"전체 재작성 여부도 감이 아니라 수치로 판단"*. 각 축의
대리지표·임계는 생성기 상수에 전부 드러나 있고, 바꾸면 전 기능이 일관되게 재채점된다
(행별 손조정 불가 — 그것이 이 표를 신뢰할 근거다). 대리지표의 한계는 생성기 docstring
표에 축별로 명시했다(1-hop 폐쇄·원시 SQL 사각·공유 스위트 과대평가 등).

판정 밴드는 §3.14 그대로: 0~4 KEEP · 5~9 REFACTOR · 10~13 HEAVY_REFACTOR ·
14~18 REPLACE_CANDIDATE. 이름이 CANDIDATE인 이유 — 계획서 100 자신이 "REPLACE는 코드가
낡아서가 아니라 **경계를 복구할 수 없을 때만**"이라 했으므로, 14점+는 검토 대상이지 선고가
아니다(§4-①의 coach가 정확히 그 사례).

## §3. 결과 (23기능 전수 — 점수 내림차순)

| 기능 | 사용자 | Domain | EP(쓰기) | Adapter 의존 | 테스트fn | A B C D E F | 계 | 판정 | 출시(제안) |
|---|---|---|---|---|---:|---|---:|---|---|
| `coach` | Student | Pedagogy | 4(3) | 2A/2M | 381 | 3 3 3 0 2 3 | **14** | REPLACE_CANDIDATE | verification-loop |
| `me` | Student | Learning Model | 36(11) | 0A/2M | 269 | 1 3 3 0 3 3 | **13** | HEAVY_REFACTOR | verification-loop |
| `auth` | Student | Identity | 7(5) | 0A/1M | 33 | 1 1 2 0 2 2 | **8** | REFACTOR | platform-invariant |
| `users` | Student | Identity | 5(3) | 0A/1M | 15 | 1 1 2 0 2 2 | **8** | REFACTOR | platform-invariant |
| `curricula` | Admin | Curriculum | 4(0) | 0A/1M | 22 | 1 2 2 0 0 3 | **8** | REFACTOR | verification-loop |
| `app-core` | Platform | AI Orchestration | 6(1) | 1A/5M | 43 | 3 0 3 0 1 0 | **7** | REFACTOR | verification-loop |
| `concepts` | Student | Knowledge Graph | 8(3) | 0A/0M | 59 | 0 1 2 0 2 2 | **7** | REFACTOR | verification-loop |
| `study` | Student | Pedagogy | 2(2) | 0A/1M | 35 | 1 1 2 0 1 2 | **7** | REFACTOR | verification-loop |
| `problems` | Student | Content | 7(3) | 0A/2M | 64 | 1 1 1 0 2 1 | **6** | REFACTOR | verification-loop |
| `verify` | Student | Assessment | 3(3) | 3A/2M | 38 | 3 0 1 0 2 0 | **6** | REFACTOR | verification-loop |
| `gating` | Student | Application Mode | 6(0) | 0A/2M | 56 | 1 2 1 0 0 2 | **6** | REFACTOR | deferred-candidate |
| `interactions` | Student | Event | 1(1) | 0A/1M | 6 | 1 1 1 1 1 1 | **6** | REFACTOR | verification-loop |
| `speech` | Student | Interaction | 1(1) | 1A/3M | 5 | 3 0 1 1 1 0 | **6** | REFACTOR | deferred-candidate |
| `rights` | Platform | Content | 3(2) | 0A/1M | 0 | 1 0 1 3 1 0 | **6** | REFACTOR | verification-loop |
| `alignments` | Admin | Curriculum | 1(0) | 0A/0M | 9 | 0 2 1 1 0 2 | **6** | REFACTOR | verification-loop |
| `privacy` | Student | Security | 1(1) | 0A/1M | 10 | 1 1 1 0 1 1 | **5** | REFACTOR | platform-invariant |
| `ocr` | Student | Interaction | 2(2) | 2A/2M | 44 | 3 0 1 0 1 0 | **5** | REFACTOR | deferred-candidate |
| `reports` | Student | QA | 1(1) | 0A/1M | 16 | 1 1 1 0 1 1 | **5** | REFACTOR | deferred-candidate |
| `dsl` | Admin | Content | 3(3) | 0A/7M | 5 | 1 0 1 1 2 0 | **5** | REFACTOR | verification-loop |
| `visualization` | Student | Interaction | 3(2) | 0A/1M | 20 | 1 0 2 0 1 0 | **4** | KEEP | deferred-candidate |
| `scene` | Student | Interaction | 1(1) | 0A/0M | 28 | 0 0 2 0 1 0 | **3** | KEEP | deferred-candidate |
| `devices` | Student | Security | 3(2) | 0A/0M | 203 | 0 0 1 0 1 0 | **2** | KEEP | platform-invariant |
| `solution_paths` | Student | Content | 1(0) | 0A/0M | 6 | 0 0 0 1 0 0 | **1** | KEEP | verification-loop |

**대시보드**: 모집단 23 · 분류율 23/23 · 검증 관여 제안(P0 상당) 17 · 이월 후보 6 · 판정 분포 {'KEEP': 4, 'REFACTOR': 17, 'HEAVY_REFACTOR': 1, 'REPLACE_CANDIDATE': 1}

## §4. 판정이 말하는 것

**① `coach` 14점(REPLACE 검토)은 계획서 100 §3.4가 예언한 바로 그 패턴이다.** *"problem_service
안에서 동시에 문제 조회 + 채점 + 오개념 추론 + 학생 상태 갱신 + 다음 문제 추천을 수행한다면
기능 자체는 버릴 필요가 없다. 분리하면 된다."* — coach가 그렇다: ADAPTER 2종(verify_final_answer·
verify_solution) 직접 호출 + DB 3점 + 결합 3점. 그리고 **치료법은 이미 등재돼 있다**:
EOS-69(SubjectAdapter 경유 배선)가 A축을 3→1로 내리면 총점 12(HEAVY_REFACTOR)로 내려온다.
계획서의 처방(분리) = 이 저장소의 EOS-69·66이며, 재작성이 아니다.

**② `me` 13점(HEAVY_REFACTOR)은 갓-라우터다.** 36 엔드포인트·쓰기 11·DB 3점. 수학 결합은
없다(0A) — 문제는 과목이 아니라 **비대함**이다. 분할 후보(sessions/assessments/dialogues 축)는
있으나 12월 검증에 필수는 아니므로 등재는 유보한다(§0-5 신규 기능 게이트 — 검증 관여 근거 부족).

**③ `rights` 테스트 0건이 D축 3점으로 기계 검출됐다.** 저작권 레일(A4·G축)의 서빙 표면인데
전용 테스트가 없다 — LIC-01(in_progress)의 완결 조건에 이 축이 포함돼야 한다. 신규 태스크는
등재하지 않는다(LIC-01이 소유·중복 등재 금지).

**④ KEEP 4건의 공통점 = 낮은 결합.** devices(2점)·solution_paths(1점)·scene(3점)·
visualization(4점) — 전부 Adapter 0·DB 0~1. 계획서 100의 KEEP 기준("과목 의존성 낮음·API
명확·테스트 존재")과 기계 점수가 일치한다.

**⑤ REFACTOR 17/23(74%)** — 계획서 100 §3.4의 예상("40~60%가 REFACTOR")보다 높다. 이유는
모집단 차이다: 이 표는 *서빙 표면만* 세므로 유틸·순수 함수(대부분 KEEP)가 빠졌다. 방향은
계획서 예상과 정합("가장 많은 기능이 REFACTOR").

## §5. Gate 0-D 판정 (계획서 100 §3.17)

| 문항 | 판정 |
|---|---|
| 기존 기능이 전부 분류됐는가? | **서빙 표면 기준 YES** — 23/23 분류율 100%. 단 계획서의 "120개" 모집단 정합은 판정 불가(원본 외부) |
| owner가 존재하는가? | 부분 — REPLACE 검토 1건(coach)은 EOS-69가 소유. 나머지 REFACTOR는 개별 태스크 미배정(§7 한계) |
| REPLACE 대상이 특정됐는가? | **YES** — 1건(coach·14점), 치료는 재작성이 아니라 EOS-66/69 경유 분리 |
| 전체 rewrite가 아니라 module-level migration 계획인가? | **YES** — REPLACE_CANDIDATE 1/23, 전면 재작성 대상 0 |

**대시보드 5숫자 중 이 표가 채우는 2개** (acceptance ③ — `feature_inventory.yaml`
`dashboard:` 블록에서 기계 산출):
- **기존 기능 분류율 = 23/23 (100%)**
- **Release P0(제안) 수 = 17** (verification-loop 13 + platform-invariant 4)

## §6. 출시 우선도는 제안이다 (acceptance ④ 중복 회피 별항)

`release_relevance`는 검증설계서 v1(EOS-51) 개발항목 코드와의 좌석 대응(장부 `seat` 필드에
전건 인용)에서 나온 **기계 제안**이며, **확정은 Kiki 몫**이다. PR #916의
`eos_verification_relevance_triage`(잔여 182건)와는 축이 다르다 — 그쪽은 *backlog 태스크*의
"12월 검증 관여 여부", 이쪽은 *서빙 기능*의 "Core/Adapter 귀속 + 이전 난이도"다. 겹치는
판단(관여 여부의 최종 확정)은 재판정하지 않고 그 프로토콜로 넘긴다 — 두 표가 모두 "제안"
상태로 Kiki 판정을 기다리는 구조가 의도다.

이월 후보 제안 6건(gating·ocr·speech·visualization·scene·reports)은 **삭제가 아니다**
(계획서 006 §26 "POSTPONE ≠ 삭제"). 특히 ocr은 "E1이 MathLive 입력"이라는 검증설계서 §2
근거로 제안된 것이지 기능 가치 판정이 아니다.

## §7. 정직한 공백

1. **Migration Map의 "이동 계획" 절반은 비어 있다** — 계획서 100 P0-09는 분류(어렵기)와 이동
   계획(어디로·언제)을 요구하는데, 이 표는 전자만 채웠다. 후자는 EOS-69(코드 이동의 실체)와
   G0 이후 주간 계획이 소유한다 — 여기서 일정을 지어내지 않는다.
2. **REFACTOR 17건에 개별 소유 태스크가 없다** — 전건 등재는 §0-5 게이트(12월 검증 관여)를
   통과하지 못한다. 검증 경로가 실제로 밟는 기능부터 EOS-69 진행 중 필요분만 등재가 옳다.
3. **대리지표의 사각** — 생성기 docstring 표 참조. 특히 D축(테스트부족)은 전용 파일 기준이라
   공유 스위트·통합 테스트가 커버하는 기능을 과대평가할 수 있다(devices 203fn처럼 전용이
   두터운 쪽은 정확하다).
4. **6축 중 F(데이터이전난이도)가 B(DB결합도)와 같은 원천**(모델 모듈 수)의 다른 밴드다 —
   행 수·마이그레이션 이력을 반영한 독립 지표가 아니다. 정밀화는 실제 이전 착수 시점 몫.

## §8. 다음 검토일

EOS-69 착지 시 재생성(`--write`) — coach의 A축 하락이 판정 변화의 첫 실측이 된다.
