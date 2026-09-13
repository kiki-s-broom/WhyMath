# `main` 브랜치 보호 규칙 — 수동 설정 가이드

> GitHub REST API의 *Branch Protection* 엔드포인트(`/protection`)는 **세션·CI 토큰**으로
> 접근할 수 없어(`Resource not accessible by integration` — 2026-07-26 실측) *설정*은
> **GitHub Settings UI에서 5분 수동 작업**이 필요합니다.
>
> **[정정 2026-09-03]** *읽기*는 다르다 — **Kiki 머신의 `gh` 토큰으로는
> `gh api repos/doldori7/WhyMath/rules/branches/main`이 EXIT=0으로 읽힌다**(실측). 그래서
> 재발 탐지는 자동화돼 있다: **조회는 사람, 판정은 기계**(§재발 탐지 실행법 · `HARN-63`).
> 아래 "접근 불가" 표현이 남아 있는 곳은 전부 *설정 API* 이야기다.
>
> 자동 가능한 부분(CODEOWNERS·CI status check)은 이미 코드로 표현되어 있습니다 —
> 이 가이드는 그것들을 *강제하는* 정책만 다룹니다.

---

## 📋 사전 브리핑 (Kiki 직접 수행 과제)

1. **과제 명칭** — `main` 브랜치 보호 규칙 설정 (특히 **required status checks 16종 등록**)
2. **목적** — CI가 실패한 코드가 `main`에 들어가지 못하게 막는다. 현재는 이 설정이
   불완전해 **전체 테스트·mypy·커버리지 잡(`backend — lint·type·test`)이 머지를 막지
   못한다** — 2026-07-26에 이 구멍으로 실제 red가 main에 들어갔다(아래 사고 기록).
3. **구체적 절차** — Settings → Branches → `main` 규칙 편집 → *Require status checks*
   섹션에서 아래 16개 이름을 하나씩 검색해 추가 → Save. 소요 약 5분(체크 16개 검색·추가가
   대부분). 나머지 항목(PR 필수·linear history 등)은 이미 설정돼 있으면 건드리지 않는다.
4. **성공 기준** — §저장 후 확인의 **자가검증 B**(가장 중요): 새 PR에서 `backend` 잡이
   *아직 돌고 있는 동안* 머지 버튼이 **비활성**이고 "Required statuses must pass"가
   보이면 성공. 머지가 가능하면 **실패**(= 등록이 안 된 것) → 검색 이름 오타를 의심하고
   §트러블슈팅 참조.
5. **실행 환경** — 웹 브라우저(GitHub). PowerShell·리포 클론 불요. 저장소 admin 권한 필요.
6. **창 구분** — 브라우저 탭 1개. 서버·프로세스 점유 없음, 이후 조작 제약 없음.

---

## 진입 경로

1. https://github.com/kiki-s-broom/WhyMath 접속
2. 우상단 **Settings** 탭 → 좌측 사이드바 **Branches**
3. *Branch protection rules* 섹션 → **Add branch protection rule** 또는 **Add rule** 클릭

---

## 적용할 설정 (체크 박스 그대로 따라가기)

### Branch name pattern
```
main
```

### Protect matching branches
- [x] **Require a pull request before merging**
  - [x] Require approvals — *최소 1명*
  - [x] Dismiss stale pull request approvals when new commits are pushed
  - [x] Require review from Code Owners *(CODEOWNERS 파일 활용)*

- [x] **Require status checks to pass before merging**
  - [x] Require branches to be up to date before merging
  - **Status checks that are required** — 아래 블록의 이름을 *그대로* 검색해 전부 추가:

<!-- REQUIRED_CHECKS_BEGIN — 이 블록은 tests/infra/test_required_checks_doc.py가 ci.yml과 대조해 동결한다. 잡 추가·개명 시 여기도 갱신해야 CI가 통과한다. -->
- `changes — 변경 경로 판별`
- `backend — lint·type·test`
- `backend — 마이그레이션·통합 (실 PG)`
- `data-pipeline — lint·type·test`
- `data-pipeline — 적재 통합 (실 PG)`
- `data-pipeline — 적재 통합 (실 Neo4j)`
- `mobile — flutter analyze·test`
- `concept-reach — mobile 호출 표면 회귀 가드`
- `web — graphing-calculator test·build`
- `infra-contracts — 운영 자산 계약 테스트 (tests/infra)`
- `docker-build — 이미지 빌드·기동 스모크(/health/live)`
- `infra/phaiakes9 — bash syntax`
- `policy-guard — CLAUDE.md 금기 가드`
- `harness-integrity — backlog 무결성·claim 교차 검증`
- `declared-unwired-audit — 선언≠배선 4축 정적 감사 (OPS-22)`
- `corpus-authoring — 결정론 저작 도구 회귀 (생성기·배치)`
<!-- REQUIRED_CHECKS_END -->

  **제외 2종**: `e2e-nightly — 관통 슬라이스 (실 PG·야간)`와
  `backend — 전체 스위트 직렬 (교차 파일 오염 탐지·야간)`는 `if: github.event_name == 'schedule'`
  라 PR에서 항상 skip된다. required로 걸어도 통과하지만(아래 참조) *야간 잡을 머지 게이트로
  선언*하는 것은 의미가 어긋나므로 넣지 않는다. 후자는 특히 required로 걸면 PR 머지 게이트에
  직렬 26분이 되돌아와 병렬화(OPS-58)가 무의미해진다 — 배선 실재성은
  `tests/infra/test_backend_serial_nightly_wiring.py`가 대신 동결한다.

  **경로 필터로 skip되는 잡을 required로 걸어도 안전한 이유**: GitHub은 `skipped` 결론을
  required check 충족으로 센다. 이 레포는 이미 그 동작에 의존한다 — `ci.yml`의
  "doc-only PR이면 skip(비용 절감·**required check는 skipped=충족**)" 주석 3곳. 따라서
  `docker-build`(docker 경로 변경 시에만 실행)처럼 조건부 잡도 목록에 넣어야 한다. 빼면
  *실행됐을 때* 실패해도 머지를 막지 못한다.

  ⚠️ CI workflow가 *한 번이라도 실행*되어야 검색 결과에 등장합니다.
  → 먼저 이 PR을 만들거나 main에 한 번 push하여 CI를 가동한 후 등록하세요.

### 정책 파라미터 선언 (체크 목록 *외*의 축)

체크 목록만 대조하면 **승인 수·strict 정책 축을 통째로 놓친다** — 2026-09-03 실측에서 실제로
승인 수가 어긋나 있었다(문서 "최소 1명" vs 라이브 0). 아래 블록은 위 체크 목록과 같은 자격의
*의도 선언*이며, `scripts/harness/ruleset_drift.py`가 라이브 JSON과 기계 대조한다.

<!-- RULESET_POLICY_BEGIN — scripts/harness/ruleset_drift.py가 라이브 JSON과 대조한다. tests/infra/test_ruleset_drift.py가 이 블록의 실재를 동결한다. -->
- `required_check_integration_id` = `15368`
- `strict_required_status_checks_policy` = `true`
- `required_approving_review_count` = `1`
- `dismiss_stale_reviews_on_push` = `true`
- `require_code_owner_review` = `true`
- `required_review_thread_resolution` = `true`
- `required_linear_history` = `true`
- `deletion` = `true`
- `non_fast_forward` = `true`
- `merge_queue` = `true`
<!-- RULESET_POLICY_END -->

`required_check_integration_id`는 GitHub Actions 앱의 id다 — required check 항목을 이 앱으로
pin해야 *다른 주체*가 같은 컨텍스트 이름으로 성공을 보고해도 충족되지 않는다.

### 알면서 유예한 축 (만료 필수)

문서를 **라이브에 맞춰 낮추지 않는다** — 문서가 의도이고 라이브가 결함이다. 다만 의도적으로
당장 맞추지 않는 축은 여기에 *만료일과 함께* 적는다. 만료일이 지나면 탐지기가 유예를 **위반으로
승격**시킨다(CLAUDE.md "만료 없는 유예·제외 금지"). 형식:
``- `키` until `YYYY-MM-DD` — 사유``

<!-- RULESET_DEVIATIONS_BEGIN — 만료 없는 유예 금지. 만료일이 지나면 ruleset_drift.py가 위반으로 승격한다. -->
- `required_approving_review_count` until `2026-12-31` — 1인 개발 단계에서 승인 1명을 요구하면 자가승인이 불가해 머지가 막힌다. 문서를 현실에 맞출지 설정을 문서에 맞출지는 Kiki 판단 사안(HARN-63 ⑤). 만료 시 재판정.
- `dismiss_stale_reviews_on_push` until `2026-12-31` — 위와 같은 승인 축 일괄. 승인 요구가 0인 상태에서 stale dismiss는 단독으로 의미가 없다.
- `require_code_owner_review` until `2026-12-31` — 위와 같은 승인 축 일괄. 1인 단계에서는 Code Owner = 작성자라 충족이 구조적으로 불가하다.
<!-- RULESET_DEVIATIONS_END -->

### 재발 탐지 실행법 (HARN-63 — 조회는 사람·판정은 기계)

세션·CI 토큰으로는 이 설정을 읽을 수 없지만 **Kiki 머신의 `gh` 토큰으로는 읽힌다**(2026-09-03
실측). 그래서 조회만 사람이 하고 판정은 기계가 한다. 30일이 지나면 SessionStart 브리핑이
재확인을 리마인드한다(`.github/ruleset-check-state.json`의 나이를 읽는다).

```powershell
# Windows PowerShell (= Phaiakes9) — 진입 명령 불요
cd C:\Users\kiki\Desktop\__AI\WhyMath
Test-Path scripts\harness\ruleset_drift.py
```

**자가검증**: 위가 `True`여야 다음으로 갑니다. `False`면 판정기가 이 체크아웃에 없다는 뜻입니다
— 아래 §트러블슈팅 "판정기 파일이 없다"를 먼저 보세요. (이 스텝은 변별력이 있습니다: 실제로
2026-09-05에 미머지 상태의 main에서 실행돼 `[Errno 2] No such file or directory`가 났고,
`$LASTEXITCODE`는 판정기의 exit 2와 **구별되지 않는 2**였습니다 — 즉 이 스텝이 없으면
"측정 실패"로 오독됩니다.)

```powershell
# Windows PowerShell — 위 자가검증이 True일 때만
cd C:\Users\kiki\Desktop\__AI\WhyMath
gh api repos/kiki-s-broom/WhyMath/rules/branches/main | Out-File -Encoding utf8 ruleset.json
python scripts\harness\ruleset_drift.py ruleset.json --record
echo "EXIT=$LASTEXITCODE"
```

> **`>` 대신 `Out-File -Encoding utf8`을 쓰는 이유**: Windows PowerShell 5.1의 `>`는 네이티브
> 명령 출력을 **UTF-16LE**로 씁니다. 그러면 판정기가 읽다가 `UnicodeDecodeError`로 죽어
> exit 0/1/2 어느 것도 나오지 않습니다(2026-09-05 실측). 읽기측도 UTF-16·BOM을 관용하도록
> 고쳤지만(`read_json_text`), 산출측에서 먼저 맞추는 것이 정본입니다 —
> CLAUDE.md "외부 도구가 읽는 파일은 그 도구의 읽기 인코딩에 맞춘다".

| EXIT | 판정 | 다음 행동 |
|---|---|---|
| `0` | 정합 (권고만 있어도 0) | 없음 — 기록 갱신됨 |
| `1` | **드리프트 위반** | 출력의 "시정 순서"를 위에서부터 따른다 |
| `2` | **측정 실패** (빈 응답·권한 부족·필드 부재) | 통과가 아니다 — `gh auth status`부터 확인 |

기록 파일(`.github/ruleset-check-state.json`)은 `--record`가 쓴다. **손편집 금지** — 확인하지
않고 날짜만 미루면 리마인드가 위장이 된다.

---

> ### 🔴🔴 3회차 재발 — 라이브 설정 실측 (2026-09-03 · HARN-56 ① 부수 발견)
>
> **이 문서가 선언한 16건 중 10건이 실제로는 등록돼 있지 않았다.** Kiki가
> `gh api repos/doldori7/WhyMath/rules/branches/main`을 실행해 확인했다(EXIT=0).
>
> **라이브에 등록된 6건**: `data-pipeline — lint·type·test` · `data-pipeline — 적재 통합 (실 PG)` ·
> `data-pipeline — 적재 통합 (실 Neo4j)` · `backend — 마이그레이션·통합 (실 PG)` ·
> `infra/phaiakes9 — bash syntax` · `policy-guard — CLAUDE.md 금기 가드`
>
> **미강제 10건**: `changes` · **`backend — lint·type·test`** · `mobile — flutter analyze·test` ·
> `concept-reach` · `web — graphing-calculator test·build` · **`infra-contracts (tests/infra)`** ·
> `docker-build` · **`harness-integrity`** · `declared-unwired-audit` · `corpus-authoring`
>
> **또 `backend — lint·type·test`다.** 2026-07-26과 같은 잡이 같은 방식으로 빠졌다. 이 상태에서는
> 전체 테스트·mypy·커버리지가 red여도 머지가 막히지 않는다. `infra-contracts`가 빠진 것도
> 뼈아프다 — 운영 자산 계약(백업·스케줄·머지큐 배선)을 지키는 잡 자신이 머지를 못 막는다.
>
> **승인 축도 어긋나 있다**: 이 문서는 `Require approvals — 최소 1명`·`Dismiss stale approvals`·
> `Require review from Code Owners`를 모두 체크로 적었으나, 라이브는
> `required_approving_review_count: 0` · `dismiss_stale_reviews_on_push: false` ·
> `require_code_owner_review: false`다.
>
> **문서와 정합한 항목**(참고): `strict_required_status_checks_policy: true`(= up to date 요구) ·
> `required_review_thread_resolution: true` · `required_linear_history: true` · deletion·
> non_fast_forward 보호.
>
> #### ✅ 시정 완료 (같은 날 2026-09-03 · 게이트 `G-required-checks-live-drift-fix`)
>
> Kiki가 미강제 10건을 ruleset(ID `16623542`)에 등록했다. 재조회 후 이 문서의
> REQUIRED_CHECKS 블록과 **기계 대조**한 결과 라이브 고유 16건 = 문서 16건, 미강제 0건.
> 이제 `backend — lint·type·test`가 red면 머지가 막힌다.
>
> **잔여(비차단) 2건** — `HARN-63`이 승계한다:
> - **소스 pin 미지정 7건** (`integration_id` 실측 2026-09-03 · 게이트
>   `G-required-checks-source-pin-cleanup`): required check 항목은 보고 주체를 특정 앱으로
>   pin할 수 있다. pin이 없으면 **어느 주체든 같은 컨텍스트 이름으로 성공을 보고하면 충족**된다
>   — 이 저장소가 늘 경계하는 "이름만 같으면 통과하는 좌석"이다. 실측 분포:
>
>   | 등급 | 대상 | 처분 |
>   |---|---|---|
>   | 🔴 **pin 항목이 0건** | `concept-reach — mobile 호출 표면 회귀 가드` | **Actions pin 항목을 먼저 추가**한 뒤 unpinned를 제거 |
>   | ⚠ pin+unpin 혼재 (6) | `web` · `infra-contracts` · `docker-build` · `harness-integrity` · `declared-unwired-audit` · `corpus-authoring` | unpinned 쪽만 제거(pin된 쌍이 남는다) |
>   | ✅ pin만 (9) | 나머지 | 조치 없음 |
>
>   **⚠ 순서 제약**: "unpinned를 지운다"를 일괄 적용하면 `concept-reach`는 항목이 하나도 남지
>   않아 **완전 미강제로 되돌아간다** — 바로 위에서 고친 사고의 재생산이다. 그 하나만 추가가
>   먼저다. 막는 힘 자체는 지금도 있으므로(Actions가 실제 보고자다) 이 정리는 비차단이다.
>
>   **드리프트 비교기는 개수가 아니라 집합으로 대조해야 한다** — 중복 때문에 항목 22 vs 문서
>   16이 나오고, 개수로 보면 정상 상태가 위반으로 오판된다.
> - **승인 축**: 이 문서는 `Require approvals — 최소 1명`·stale dismiss·CODEOWNERS를 체크로
>   적었으나 라이브는 전부 off(`required_approving_review_count: 0`)다. **의도적으로 바꾸지
>   않았다** — 1인 개발에서 승인 1명을 요구하면 자가승인이 불가해 머지가 막힌다. 문서를
>   현실에 맞출지 설정을 문서에 맞출지는 Kiki 판단 사안이다(`HARN-63` ⑤).

> #### 왜 기존 방어가 못 잡았나 — 저장소 경계 밖이라서
>
> `tests/infra/test_required_checks_doc.py`는 **문서 ↔ `ci.yml`**을 대조한다. 두 축 다 저장소
> *안*이다. 라이브 GitHub 설정은 저장소 *밖*이라 어떤 테스트도 보지 않는다. 그래서 문서가
> 정확하고 `ci.yml`이 정확해도 **설정이 비어 있으면 전부 초록으로 통과**한다. 이 구멍을 메우는
> 것이 `HARN-63`이며, 시정(체크 10건 등록·승인 수) 자체는 게이트
> `G-required-checks-live-drift-fix`다. **시정만 하면 4회차가 온다** — 탐지가 따로 필요하다.
>
> #### 정정: API 접근 가능성 (아래 2026-07-26 기록의 마지막 문장)
>
> 아래 박스는 "Branch Protection API는 이 토큰으로 접근 불가"로 적고 있다. 그것은 **세션
> 토큰**에 대해서는 여전히 참이지만, **Kiki 머신의 `gh` 토큰으로는 읽기가 된다**(2026-09-03
> 실측). 따라서 자동 대조의 읽기 경로가 존재한다 — 조회는 사람이, 판정은 기계가 하는 분업이
> 가능하다는 뜻이다(HARN-63 ①의 설계 전제).

> ### 🔴 왜 이 목록이 중요한가 (2026-07-26 사고)
>
> 이 문서는 오랫동안 required check를 **3종만**(`data-pipeline`·`infra/phaiakes9`·
> `policy-guard`) 나열했고 **`backend — lint·type·test`가 빠져 있었다**. CI 잡이 3개에서
> 14개로 늘어나는 동안 목록이 따라가지 못한 것이다.
>
> **더 나아가 — 실측 결과 그 3종조차 등록돼 있지 않았다**(`enforcement_level=off`·
> `checks=[]`, 자가검증 C). `protected: true`(PR 필수·force-push 차단)는 켜져 있었으나
> **status check 강제 자체가 통째로 꺼져 있었다**. 즉 "backend만 빠진 것"이 아니라
> **어떤 CI 잡도 머지를 막지 못하는 상태**였다.
>
> 결과: 전체 테스트·mypy·커버리지를 보는 **가장 중요한 잡이 머지를 막지 못했다.**
> PR #603·#604·#605·#606·#607 **다섯 번 연속** 이 잡의 완주 전에 auto-merge가 발동했고,
> #606에서 실제로 `1 failed`가 나 **main이 red**가 됐다(테스트 전역 오염). 그 red를 고치는
> PR #607조차 같은 방식으로 머지됐다 — 수정이 맞는지는 머지 이후에야 알 수 있었다.
>
> 목록의 *정확성*은 코드로 지킬 수 있어 `tests/infra/test_required_checks_doc.py`로 동결했다
> (오타 하나면 UI 검색이 실패하고 그 체크는 조용히 미설정으로 남는다). 그러나 **설정 자체를
> 적용하는 것은 Kiki의 UI 작업**이다 — GitHub Branch Protection API는 이 토큰으로 접근
> 불가가 실측 확인됐다(`Resource not accessible by integration`).

- [x] **Require conversation resolution before merging**
  - 코드 리뷰 코멘트가 모두 해결되어야 머지 가능

- [x] **Require linear history**
  - merge commit 금지 → squash 또는 rebase만. 히스토리 깔끔.

- [ ] Require deployments to succeed before merging *(Phase 1에서는 X)*

- [ ] Require signed commits *(Phase 2+ 권장)*

### Rules applied to everyone including administrators
- [x] **Do not allow bypassing the above settings**
  - *주의*: 본인에게도 적용. 1인 단계에서는 약간 불편할 수 있으나
    *우발적 main 직접 push 방지* 효과가 큼.

- [x] **Restrict who can push to matching branches**
  - 비워두기 (PR만으로 머지)

- [x] **Allow force pushes** — **체크 해제** (force push 차단)
  - *Specify who can force push* 도 비워두기

- [x] **Allow deletions** — **체크 해제** (main 삭제 방지)

---

## 머지 경합 — merge queue **사용 중** (2026-09-09 전환)

> **현행 사실**: `main` 룰셋에 merge queue가 켜져 있다. 큐가 PR을 최신 `main` 위에 얹어
> 재검증하므로 `Require branches to be up to date`를 **유지한 채** 재동기화가 자동화된다 —
> 보호를 낮추지 않고 충족만 자동화한다는 원 취지 그대로다.
>
> 이 절은 2026-09-07~09-08에 정반대 내용("이 저장소에서는 쓸 수 없다")을 담고 있었다.
> **그때는 그 판정이 옳았다** — 아래 「전제가 바뀐 이력」이 왜 바뀌었는지를 기록한다.

### 무엇이 달라졌는가 (실측)

| 축 | 2026-09-07 | 2026-09-09 |
|---|---|---|
| 소유자 | `doldori7` (`owner.type` = **`User`**, 개인 계정) | `kiki-s-broom` (`owner.type` = **`Organization`**) |
| `visibility` | `public` | `public` |
| merge queue | 조직 소유 전용이라 룰셋 항목 **자체가 없음** | 룰셋에 활성 |

merge queue는 **조직(Organization) 소유 저장소 전용**이다 — 공개 저장소는 조직 소유면 무료
플랜에서도 되고, 비공개는 조직 + Enterprise Cloud가 필요하다. 개인 계정 소유는 공개·비공개
모두 제공되지 않는다. 이 조건은 변하지 않았고, **저장소가 조건을 넘어갔다.**

### 큐가 실제로 일한다는 근거

라이브 룰셋 덤프가 아니라 **큐가 한 일**로 확인했다(설정 조회보다 강한 증거다):

- PR #1067이 큐 브랜치 `gh-readonly-queue/main/pr-1067-94d1f28a`에서 검증됨
- `merge_group` 이벤트로 CI 실행 생성 (`ci.yml` run `34318528035`) — 그 전까지 이 이벤트의
  실행은 **역대 0건**이었다
- 그 큐 브랜치의 head `a374d2e0`이 그대로 `main`이 됨

**큐에서는 경로 기반 잡 스킵이 걸리지 않는다.** 무거운 잡의 `if`가 전부
`github.event_name != 'pull_request'` 형태라 `merge_group`에서는 전건 실행된다 — PR
컨텍스트에서 skip되던 backend·mobile·web·data-pipeline이 큐에서 처음 돌았다. 의도된 동작이다
(큐의 목적이 최신 base 위 전체 재검증이므로). 야간 전용 잡은 큐에서도 계속 스킵된다.

### 전제가 바뀐 이력 (사고 기록 — 지우지 않는다)

> 2026-09-07 세션이 라이브 룰셋에서 `merge_queue` 규칙이 **없음**을 확인하고 그것을 "아직 안
> 켰다"로 읽었다. 부재는 *미설정*일 수도 *미제공*일 수도 있는데 앞의 것만 가정했고, 그 상태로
> Kiki에게 결정을 올려 왕복 1회를 태웠다. **설정 부재는 설정 가능을 함의하지 않는다** — 기능
> 도입을 제안하기 전에 그 기능이 이 저장소의 *계정 유형·가시성·플랜*에서 제공되는지부터
> 확인한다. 이 사고가 CLAUDE.md v0.2.18 "설정 부재를 설정 가능으로 단정 금지"의 발생 근거다.
>
> **그 규칙은 지금도 유효하다.** 전제가 바뀐 것이지 규칙이 틀린 것이 아니다 — 오히려 이 절이
> 그 규칙의 실례다: 2026-09-07의 "쓸 수 없다"는 *그 시점 계정 유형에서는* 실측으로 옳았고,
> 소유자가 바뀌자 사실도 바뀌었다. **판정은 시점에 종속된다.**
>
> `ruleset_drift.py`의 규칙 타입 축에서 `merge_queue`를 당시 **의도적으로 뺐던** 이유도
> 같다 — 충족 불가한 것을 선언하면 위반이 상시 보고돼 판정기 전체가 소음이 된다(CLAUDE.md
> "상시 실패하는 fail-open 보호"). 그 주석은 "저장소가 조직으로 이관되면 그때 이 튜플에
> 추가한다"고 조건을 박아 뒀고, **2026-09-09에 그 조건이 충족돼 편입했다**(HARN-98).
> 지금은 반대 방향이 위험하다: 큐가 머지 경로를 지탱하는데 감시 축에 없으면 누가 큐를 꺼도
> 판정기가 모른다.

### 대신 하는 것 — 자동 재동기화 (`pr-auto-resync.yml` · HARN-85)

보호를 낮추는 대신(=`strict` 해제) **충족을 자동화**한다. `Require branches to be up to date`는
그대로 유지된다 — 그 게이트는 실제로 일하고 있다(#931이 `ReviewStatus`에 `quarantined`를
추가하자 #935의 단언이 red가 됐다. 동기화하지 않았으면 머지 후 `main`에서 터졌다).

예약 워크플로우가 주기적으로 열린 PR을 훑어, **auto-merge가 켜져 있고 `behind`인 것만**
`PUT /repos/{owner}/{repo}/pulls/{n}/update-branch`로 최신화한다. 사람이 누르던 "Update branch"를
기계가 누르는 것이다.

**한계(명시)** — 큐가 아니다:
- **직렬화하지 않는다.** 동시에 여러 PR이 auto-merge 대기 중이면 모두 같은 `main` 위로
  최신화되고, 그중 하나가 먼저 머지되면 나머지는 다시 `behind`가 된다(다음 주기에 또 최신화).
  PR 동시 대기 수가 많을수록 CI 소모가 늘어난다 — 큐의 `Maximum entries to build`에 해당하는
  절약 장치가 없다.
- **충돌은 사람 몫이다.** `update-branch`가 409를 내면(내용 충돌) 워크플로우는 건너뛰고
  로그에 PR 번호와 응답 본문을 남긴다. 조용히 넘기지 않는다.
- **auto-merge를 켜지 않은 PR은 건드리지 않는다.** 의도적이다 — 아직 리뷰 중인 PR의 브랜치를
  임의로 전진시키면 리뷰어가 보던 diff가 바뀐다.

**토큰 — 이것이 없으면 워크플로는 멈춘다(fail-closed)**: `GITHUB_TOKEN`이 만든 push는
workflow를 재발화시키지 않는다(GitHub 문서화 제약). 그 토큰으로 `update-branch`를 하면
브랜치는 최신화되지만 **새 head에 required check가 하나도 보고되지 않아** strict 하에서 그
PR은 "체크 대기"로 **영구히** 막힌다 — `behind`는 사람이 Update branch를 눌러 풀 수 있지만
(사람 행위는 CI를 재발화시킨다) 체크 없는 head는 그 탈출구마저 없앤다. **즉 폴백은 아무것도
안 하느니 나쁘다**: 성공을 보고하면서 PR을 좌초시킨다.

그래서 폴백으로 진행하지 않고 **쓰기 전에 멈춘다**. 저장소 시크릿
`PR_AUTO_RESYNC_TOKEN`(fine-grained PAT · `Contents: Read and write` +
`Pull requests: Read and write`)이 없으면 스크립트가 `쓰기 자격 없음`을 내고 exit 1 —
게이트 `G-pr-auto-resync-token`이 그 발급을 추적한다.

> 이 결정은 제약의 성립 여부와 **무관하게** 옳다. 제약이 실재하지 않는다면 비용은 "PAT를
> 불필요하게 요구했다" 1회이고, 실재한다면 폴백의 비용은 "좌초된 PR"이다 — 비대칭이 크므로
> 측정을 기다리지 않고 안전한 쪽을 택한다. (`HARN-85` ②의 실측은 PAT 착지 후에도 유효하다:
> 폴백 경로가 실제로 어떻게 실패하는지는 여전히 모르는 채로 남는다.)

**수동 확인**: Actions 탭 → `pr-auto-resync` → Run workflow → `dry_run` = `1`. 읽기 전용이라
**PAT 없이도 돈다** — 쓰기 자격 검사를 통과해 후보와 분모(스캔 N건 · BEHIND+auto-merge M건)만
출력한다. 배선 확인 경로를 일부러 열어 둔 것이다.

## 저장 후 확인

1. 페이지 하단 **Create** 또는 **Save changes** 클릭
2. Branches 탭에 *Branch protection rule applied to* `main` 확인

### 자가검증 C — API로 직접 읽는다 (**가장 확실·이것부터**)

브랜치 보호 *설정* 엔드포인트(`/protection`)는 admin 권한이 필요해 읽기 토큰으로 403이지만,
**`/branches/main`은 `metadata=read`로도 읽히고 그 안에 required check 요약이 들어 있다**
(2026-07-26 실측). 눈으로 세는 A보다 정확하고, 머지 타이밍을 지켜보는 B보다 즉시 나온다.

```bash
# 어디서든(claude 세션 포함) 실행 가능 — 토큰만 있으면 된다
curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/kiki-s-broom/WhyMath/branches/main" |
  python3 -c "import sys,json;p=json.load(sys.stdin)['protection']['required_status_checks'];print(p['enforcement_level'], len(p['checks']), sorted(c['context'] for c in p['checks']))"
```

| 출력 | 판정 |
|---|---|
| `off 0 []` | ❌ **required check가 하나도 없다** — 미설정 상태 |
| `non_admins 16 [...]` 또는 `everyone 16 [...]` | ✅ 16종 등록 완료 |
| 개수가 16 미만 | ⚠️ 일부 누락 — 목록 출력과 문서 블록을 1:1 대조 |

> **설정 전 실측값(2026-07-26)**: `enforcement_level=off · contexts=[] · checks=[]`.
> 즉 문서가 나열하던 3종조차 **실제로는 등록돼 있지 않았다** — `protected: true`(PR 필수·
> force-push 차단 등)는 켜져 있으나 **status check 강제만 통째로 꺼져 있던** 상태다.
> 이 검사는 미설정 상태에서 확실히 `off 0 []`를 내므로 변별력이 있다.

### 자가검증 A — 등록된 체크 *개수*를 눈으로 센다

규칙 편집 화면의 *Require status checks* 목록에 **16개**가 있는지 센다.
16개 미만이면 검색이 빈 이름이 있었다는 뜻이다(오타·개명). 위 목록과 1:1 대조하라.

> **왜 개수를 세나**: UI는 "검색 결과 없음"을 조용히 보여줄 뿐 실패를 만들지 않는다.
> 추가했다고 생각하고 넘어가면 그 체크는 **미설정으로 남는다** — 이것이 2026-07-26
> 사고에서 `backend` 잡이 required가 아니었던 경로다.

### 자가검증 B — 실패 상태에서 실제로 막히는지 (가장 중요)

**이 검증만이 "설정이 작동한다"를 증명한다.** A는 화면에 보이는 것을 셀 뿐이다.

1. 아무 PR이나 새로 연다(문서 한 줄 수정으로 충분).
2. CI가 시작되면 **`backend — lint·type·test`가 아직 `in_progress`인 동안** PR 화면을 본다.
3. **성공 판정**: Merge 버튼이 비활성이고 *"Required statuses must pass before merging"*
   또는 *"Waiting for status to be reported"*가 보인다.
   **실패 판정**: 그 잡이 도는 중인데 머지가 가능하다 → **등록 안 됨**. §트러블슈팅으로.

> **이 검증이 변별력을 갖는 이유**: 설정 전 상태(현재)에서는 실제로 머지가 **가능하다**.
> PR #603·#604·#605·#606·#607이 전부 이 잡의 완주 전에 머지됐다 — 즉 이 검사는 실패
> 상태에서 실패 신호를 낸다(성공/실패 양쪽에서 같은 값을 내는 검사가 아니다).

3. 다음 push 시도가 막히는지 검증:
   ```bash
   # 막혀야 함:
   git checkout main
   git commit --allow-empty -m "직접 push 시도"
   git push origin main
   # → ! [remote rejected] main -> main (protected branch hook declined)
   ```
4. PR 흐름이 정상 작동하는지 검증:
   ```bash
   git checkout -b test/protection-check
   git commit --allow-empty -m "PR 흐름 검증"
   git push -u origin test/protection-check
   # → GitHub에서 PR 생성 → CI 통과 → Code Owner 승인 → Merge
   ```

---

## 트러블슈팅

### 판정기 파일이 없다 (`ruleset_drift.py` ... No such file or directory)

`scripts\harness\ruleset_drift.py`가 **아직 main에 병합되지 않은 상태**입니다(HARN-63 PR).
`git checkout -B main origin/main` 뒤에 실행하면 당연히 없습니다. 병합 전에 돌리려면 그 PR
브랜치를 체크아웃해야 합니다:

```powershell
# Windows PowerShell — 병합 전 실행용 (병합 후에는 main에서 그냥 됩니다)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin claude/test-driven-development-03elxp
git checkout -B claude/test-driven-development-03elxp origin/claude/test-driven-development-03elxp
Test-Path scripts\harness\ruleset_drift.py
```

> **왜 `pull`이 아니라 `fetch` + `checkout -B`인가**: 재시작(force-push)된 브랜치에서 `pull`은
> diverged 상태의 add/add 머지 충돌을 냅니다(2026-07-17 실측). CLAUDE.md 규약.

**주의 — `$LASTEXITCODE=2`가 두 가지를 뜻합니다**: 파이썬이 *파일을 못 찾은* 2와 판정기의
*측정 실패* 2는 값이 같습니다. 그래서 위 `Test-Path` 자가검증이 앞에 와야 합니다 — 그것 없이
`EXIT=2`만 보면 "측정 실패"로 오독하고 `gh auth status`부터 뒤지게 됩니다.

### 소스 pin 시정 — 경로 B (API · UI가 안 될 때)

탐지기가 등급ⓐ(pin 항목 0건)나 권고(중복·혼재)를 냈는데 GitHub UI에서 소스 선택이 안 보이면
API로 고친다. 룰셋 `PUT`은 **본문이 잘못되면 보호를 통째로 약화**시키므로, 본문은 손으로
쓰지 않고 `scripts/harness/ruleset_pin_plan.py`가 만든다 — 그 도구는 "중복 제거 + GitHub
Actions pin" 외에는 아무것도 바꾸지 않음을 코드가 집행하고 테스트가 동결한다
(`tests/infra/test_ruleset_pin_plan.py`). 네트워크 호출은 하지 않는다 — 조회·적용은 아래 `gh`가 한다.

**① 도구 실재 확인 + 백업** (읽기 전용 — 백업 파일이 롤백 수단이다, 지우지 말 것)
```powershell
# Windows PowerShell (= Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath
Test-Path scripts\harness\ruleset_pin_plan.py
gh api repos/kiki-s-broom/WhyMath/rulesets/16623542 | Out-File -Encoding utf8 ruleset-backup.json
Test-Path ruleset-backup.json
```
첫 `Test-Path`가 `False`면 변경안 도구가 이 체크아웃에 없다 — 위 §"판정기 파일이 없다"와 같은
상황(미머지)이며 같은 복구 절차(브랜치 fetch + checkout -B)를 쓴다. **2026-09-05 실측**: 미머지
상태에서 ②가 `[Errno 2]`로 죽었는데도 ③이 그대로 실행됐다 — 파일이 없어 gh가 거부했기에
무사했지만, 오래된 변경안이 남아 있었다면 그대로 PUT됐을 것이다. 그래서 ③은 아래처럼 자가
가드를 가진다.

**② 변경안 + 롤백 본문 생성** (오프라인 — 표가 나오고 파일 **두 개**가 생긴다)
```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
python scripts\harness\ruleset_pin_plan.py ruleset-backup.json --out ruleset-plan.json --rollback-out ruleset-rollback.json
echo "EXIT=$LASTEXITCODE"
Test-Path ruleset-plan.json
Test-Path ruleset-rollback.json
```
`EXIT=0` + 두 `Test-Path`가 `True` + 표의 "→ 변경" 행이 **탐지기가 지목한 항목과 일치**하면
③으로. `EXIT=2`는 거부(규칙 부재·**체크 목록 빈 배열**·타 앱 pin·형식 이상)이며 본문이 만들어지지
않고 **이전 실행의 산출물도 먼저 지워진다** — 오래된 본문이 PUT되는 일을 막기 위해서다. 출력의
사유를 보고 사람이 판단한다.

`ruleset-rollback.json`은 **적용 전 상태**로 되돌리는 PUT 본문이다. 백업 JSON을 그대로 PUT하면
읽기 전용 필드 때문에 GitHub이 거부할 수 있어, 롤백 본문도 기계가 만들고 같은 불변식으로
검증한다 — 보호가 약해진 직후에 사람이 보안 민감 본문을 손으로 고치는 일이 없게.

**③ 적용** (쓰기 — ②의 표를 확인한 뒤에만. 블록 자체가 ② 산출물 두 개의 실재를 확인하고,
하나라도 없으면 **PUT을 보내지 않는다**)
```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
if ((Test-Path ruleset-plan.json) -and (Test-Path ruleset-rollback.json)) { gh api -X PUT repos/kiki-s-broom/WhyMath/rulesets/16623542 --input ruleset-plan.json | Out-Null; "PUT_EXIT=$LASTEXITCODE" } else { "중단 — 변경안 또는 롤백 본문이 없다. ②를 먼저 성공시킨다." }
```

**④ 재검증** — 위 §재발 탐지 실행법의 조회+판정 블록을 다시 돌린다. `EXIT=0`이면 완료
(그때 `.github/ruleset-check-state.json`을 커밋한다).

**⑤ 롤백** — ④가 `EXIT≠0`이거나 ③의 `PUT_EXIT≠0`일 때만. 블록 자체가 **④의 마지막 판정을
읽어** `ok`면 되돌리기를 거부한다 — 정합 상태를 되돌릴 이유는 없다.
```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$v = if (Test-Path .github\ruleset-check-state.json) { (Get-Content .github\ruleset-check-state.json -Raw | ConvertFrom-Json).verdict } else { 'unknown' }
if ($v -ne 'ok') { gh api -X PUT repos/kiki-s-broom/WhyMath/rulesets/16623542 --input ruleset-rollback.json | Out-Null; "ROLLBACK_EXIT=$LASTEXITCODE" } else { "중단 — 마지막 판정이 정합(ok)이라 되돌릴 이유가 없다. ④가 실패했을 때만 실행한다." }
```
> **왜 가드가 필요한가 (2026-09-05 실측)**: ③ `PUT_EXIT=0` → ④ **위반 0·권고 0·정합** → 그런데
> 같은 메시지에 있던 ⑤가 그대로 붙여넣기되어 `ROLLBACK_EXIT=0` — 방금 닫힌 게이트가 다시
> 열렸고, ④가 기록한 상태 파일(`ok`)은 **거짓**이 됐다. "④가 실패했을 때만"이라는 산문은
> 통째 붙여넣기를 막지 못한다. 가드가 막는다. (한편 이 사고는 변경안·롤백 **두 본문이 라이브
> PUT에서 모두 유효함**을 증명했다.)
롤백 후 조회+판정 블록을 다시 돌리면 **적용 전과 같은 판정**(같은 위반·권고)이 나와야 한다 —
그것이 롤백이 실제로 된 증거다. `ROLLBACK_EXIT≠0`이면 출력 전문을 세션에 보낸다.

### Status check가 검색 결과에 안 보임
- CI workflow가 한 번도 실행되지 않은 상태. 임의 PR을 만들어 CI를 가동한 뒤 설정.

### Code Owners 검토가 자동 요청되지 않음
- `.github/CODEOWNERS` 파일의 사용자명이 GitHub 계정과 일치하는지 확인 (대소문자·@ 포함)
- 본인이 PR 작성자면 *Code Owner = 작성자* 충돌 → 별도 리뷰어 추가 (Phase 2 합류 시 자연 해소)

### Force push가 *여전히* 가능
- *Allow force pushes* 체크 해제 누락 가능. 위 체크리스트 다시 확인.

---

## 적용 후 MEMORY.md 업데이트

설정 완료 후 `MEMORY.md` *2026-05-14: GitHub 원격 저장소 연결* 결정 로그 마지막 줄
> "다음 단계는 GitHub Settings → Branches 에서 `main` 보호 규칙 ... 적용 예정."

을 다음으로 교체:

```
**상태**: 확정. main 브랜치 보호 규칙 적용 완료 (2026-MM-DD):
PR 1+승인·Code Owners·CI status check 3종·linear history·force-push 차단·deletion 차단.
```
