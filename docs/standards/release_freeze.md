# Feature Freeze / Code Freeze 규칙 (HARN-103)

> 정본: 이 문서(사람말) + `scripts/ops/check_release_freeze.py`(집행). 두 곳의 날짜·라벨 일치는
> `tests/infra/test_release_freeze.py`가 동결한다. 근거: EOS 계획서 ①§29·§30,
> `docs/reviews/eos_source_docs_gap_review_2026-08-31.md` §4 B7.

## 1. 한 줄 요약

11월 30일부터는 제품 동작을 바꾸는 PR에 `release-blocker` 라벨이 있어야 하고, 12월 14일부터는
`code-freeze-approved` 라벨도 있어야 한다. 2027년 1월 15일에 **날짜로 자동 해제**된다.

## 2. 일정 (코드 상수와 동일 — 바꾸려면 둘 다 고친다)

| 단계 | 기간 | 동결 경로를 바꾸는 PR에 필요한 라벨 |
|---|---|---|
| OPEN | ~ 2026-11-29 | 없음 |
| FEATURE_FREEZE | 2026-11-30 ~ 2026-12-13 | `release-blocker` |
| CODE_FREEZE | 2026-12-14 ~ 2027-01-14 | `release-blocker` + `code-freeze-approved` |
| RELEASED | 2027-01-15 ~ | 없음 (동결 해제) |

- 12/31은 외부 출시일이 아니라 **내부 검증 판정일**이다(`eos_transition_declaration_2026-08-30.md`).
  해제 지점을 판정일 뒤 2주(1/15)로 둔 이유는 판정 직후 정리·후속 PR이 막히지 않게 하기 위해서다.
- **동결에는 만료가 있다.** 해제를 사람의 기억에 맡기지 않는다 — 만료 없는 동결은 이 저장소가
  금지한 유예 그 자체다(CLAUDE.md '만료 없는 유예·제외 금지'). 연장하려면 이 표와
  `FREEZE_EXPIRES` 상수를 함께 고친다.

## 3. 무엇이 동결되는가

| 구분 | 경로 | 시작 |
|---|---|---|
| 제품 코드 | `src/`, `infra/`, `schemas/` | Feature Freeze |
| 콘텐츠 데이터 | `data/` | Code Freeze (12/27 데이터 동결 전 마지막 보호막) |
| **동결 안 됨** | `docs/`, `tests/`, `backlog/`, `scripts/`, `.github/`, `MEMORY.md` 등 | — |

문서·테스트·대장만 바꾸는 PR은 어느 단계에서도 라벨 없이 통과한다. 테스트와 문서는 출시 안정화
기간에 오히려 늘어야 하기 때문이다.

## 4. 라벨과 예외 절차

| 라벨 | 뜻 | 붙이는 기준 |
|---|---|---|
| `release-blocker` | 이 변경이 없으면 출시(검증 판정)가 막힌다 | PR 본문에 "무엇이 막히는가"를 한 줄 적는다 |
| `code-freeze-approved` | Code Freeze 중 Kiki가 예외를 승인했다 | Kiki가 승인한 뒤에만 붙인다 |

- 새 기능은 라벨로 통과시키지 않는다. 라벨은 **차단 버그·회귀 수정·판정 필수 계측**용이다.
- 라벨을 붙이면 같은 PR에서 검사가 다시 돈다(`labeled`/`unlabeled` 트리거).

## 5. 집행 축 분리 (정본화 ≠ 집행)

| 축 | 내용 | 상태 |
|---|---|---|
| ① 문서 | 이 문서 | 착지 |
| ② 기계 검사 | `scripts/ops/check_release_freeze.py` + `.github/workflows/release-freeze.yml` | 착지 — 단 **required check 아님** |
| ③ 저장소 설정 (Kiki) | 라벨 2종 생성 · 룰셋에 `release-freeze` required 등록 | **게이트 `G-release-freeze-labels-and-required`로 이관** |

③은 되돌리기 어려운 저장소 설정 조작이라 세션이 하지 않는다. 그 전까지 ②는 빨간 체크를
보여 줄 뿐 머지를 막지 못한다.

### 가용성 실측 (2026-10-08)

- 저장소 `kiki-s-broom/WhyMath`: `owner.type=Organization` · `visibility=public` · 호출자
  `permissions.admin=true`. 라벨·룰셋·merge queue 모두 이 조건에서 제공된다.
- `release-blocker` 라벨 조회는 "not found" — 이는 **미설정**이지 미제공이 아니다(라벨은 모든 저장소가
  제공). `code-freeze-approved`는 조회하지 않았다(미확인, 같은 미설정으로 추정).

## 6. 정직한 공백

- `code-freeze-approved`를 **누가** 붙였는지는 검사가 모른다. triage 권한이면 누구나 붙일 수 있어서
  이 라벨은 승인의 증거가 아니라 **승인 요청이 가시화됐다는 표지**다. 승인 주체를 강제하려면
  CODEOWNERS·룰셋 승인 규칙이 필요하다(Kiki 설정).
- 기능 추가와 버그 수정을 의미로 가르지 못한다. 경로와 라벨만 본다.
- 동결 경로 목록(§3)은 이 시점의 기본값이다. 11/30 직전에 Kiki가 대상(특히 `data/`)을 확정해야
  규칙이 빈 껍데기가 되지 않는다(태스크 acceptance ⑥).
- 날짜는 UTC 기준이다. 한국 시간 11/30 00:00~09:00에 열린 PR은 UTC로 11/29라 아직 OPEN으로 판정된다.
