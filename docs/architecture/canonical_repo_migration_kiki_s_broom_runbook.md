# 정본 저장소 전환 런북 — doldori7/WhyMath → kiki-s-broom/WhyMath

**작성일**: 2026-09-09 (같은 날 1차 정정) · **관련 태스크**: `HARN-96-canonical-repo-migration-kiki-s-broom` · **관련 게이트**: `G-canonical-repo-cutover-kiki-s-broom`(확인 대기), `G-canonical-repo-migrate-decision`(전환 결정 — cleared) · **선행 결정**: `G-merge-queue-or-strict-relax`(2026-09-07 cleared)

## 1. 무슨 일이 있었나 (쉬운 설명)

2026-09-07에 우리는 "PR 하나 머지하는 데 재동기화가 여러 번 필요한 문제"를 풀려고 GitHub의 **merge queue**(병합 대기열 — PR들을 줄 세워 자동으로 최신 상태 위에서 검증·머지해주는 기능)를 켜려고 했습니다. 그런데 이 기능은 **조직(Organization) 계정** 저장소에만 있고, `doldori7/WhyMath`는 **개인(User) 계정** 저장소라 설정 화면에 그 항목 자체가 없었습니다. 그래서 대신 "자동 재동기화 워크플로우"(`HARN-85`)라는 우회 방법을 만들어 썼습니다.

2026-09-09, Kiki가 `kiki-s-broom/WhyMath`라는 저장소의 main 브랜치에 merge queue 등록을 성공시켰다고 알려왔고, 이 저장소를 앞으로의 정본(진짜 작업 대상)으로 삼기로 결정했습니다.

이 세션은 처음에 이것을 "코드가 복사된 새 저장소"로 이해하고 시크릿·브랜치 보호 규칙을 손으로 다시 설정해야 한다고 안내했습니다(아래 §6 정정 이력 참고). 하지만 실제로 커밋을 push해 보니 GitHub가 다음과 같이 응답했습니다:

> `This repository moved. Please use the new location: https://github.com/kiki-s-broom/WhyMath.git`

그리고 그 주소로 fetch하니 `doldori7/WhyMath`에서 다른 세션들이 작업 중이던 브랜치(예: `claude/status-iraoq3`)가 그대로 있었습니다. 즉 이것은 **복사본이 아니라 GitHub의 "Transfer repository"(저장소 소유자 이전) 기능으로 실제 이전된 같은 저장소**입니다. GitHub 저장소 전환은 커밋·브랜치·이슈·PR뿐 아니라 **Actions 시크릿·브랜치 보호 규칙·webhook도 함께 자동으로 옮깁니다** — 그래서 애초에 걱정했던 "시크릿을 손으로 다시 등록해야 하나"라는 문제는 대부분 발생하지 않습니다.

## 2. 이 세션이 실측으로 확인한 것

- `kiki-s-broom/WhyMath`로 git push했을 때 "저장소가 이전됨" 리다이렉트 응답을 받았다(위 인용).
- 그 주소로 직접 fetch하니 `doldori7/WhyMath`의 브랜치·claim 이력과 완전히 동일했다 — 별도 owner의 새 저장소가 아니라 **같은 저장소**임이 확정됐다.
- 조직 관리자가 Claude GitHub App을 재설치한 뒤 push·PR 생성(GitHub API 경유)이 정상 동작했다 — 이 PR(`HARN-96` 등재분)이 그 증거다.
- **여전히 확인하지 못한 것**: `kiki-s-broom`이 GitHub API 기준으로 정확히 Organization 계정인지는 이 세션에서 직접 조회하지 못했다(아래 §4의 도구 제약). merge queue 등록 성공 + 저장소 전환 확인은 강한 정황 증거이지만, 계정 유형 자체의 API 실측은 별도 항목(`HARN-96` acceptance ①)으로 남아 있다.

## 3. Kiki가 확인만 하면 되는 것 (재설정이 아니라 "승계 확인")

저장소 전환이 시크릿·브랜치 보호를 자동으로 옮기므로, Kiki가 할 일은 "다시 만들기"가 아니라 "잘 옮겨졌는지 훑어보기"입니다.

1. **과제 명칭**: kiki-s-broom/WhyMath 저장소 설정이 전환 후에도 정상인지 확인
2. **목적**: 자동 승계가 GitHub의 표준 동작이라도, 이번처럼 큰 변화 뒤에는 실제로 확인하는 편이 안전합니다(우리 프로젝트 CLAUDE.md의 "설정 성공 보고만으로 확정하지 않는다" 원칙과 같은 이유).
3. **구체적 절차**:
   - ① `kiki-s-broom/WhyMath` → Settings → Secrets and variables → Actions 에서 `DEPLOY_SSH_HOST`·`DEPLOY_SSH_USER`·`DEPLOY_SSH_KEY`·`DEPLOY_SSH_KNOWN_HOSTS`·`DEPLOY_PATH`·`PR_AUTO_RESYNC_TOKEN` 6개가 목록에 그대로 있는지 확인만 합니다(값은 안 보여도 정상 — 이름만 확인).
   - ② `kiki-s-broom/WhyMath` → Settings → Rules → Rulesets → main 에서 기존 필수 체크 목록과 "Require branches to be up to date"가 그대로 있는지 확인하고, 이번엔 **Require merge queue** 항목이 실제로 보이는지(=Organization 계정 확정) 확인합니다. 이미 Kiki가 켰다고 한 부분이므로 상태만 재확인.
   - ③ Actions 탭에서 `pr-auto-resync` 워크플로를 `workflow_dispatch`로 1회 수동 실행해 정상 동작하는지 확인합니다.
   - 이름이 하나라도 빠져 있거나 ③이 실패하면, 그 시크릿만 새로 발급해 등록하면 됩니다(전체를 다시 할 필요는 없습니다).
4. **성공 기준**: ①의 6개 시크릿 이름이 모두 보임 / ②에서 merge queue가 켜진 상태로 보임 / ③의 수동 실행이 success로 끝남.
5. **실행 환경**: GitHub 웹사이트(브라우저). PowerShell·터미널 불필요.
6. **창 구분**: 해당 없음 (웹 브라우저 설정 화면 작업).

## 4. 왜 Claude 세션이 API 확인까지는 못 하는가

이 세션은 시작할 때부터 `doldori7/WhyMath`(현재는 `kiki-s-broom/WhyMath`로 전환됨) 저장소에 고정되어 있습니다. `kiki-s-broom` owner로 별도 부착을 시도하면 다음 오류가 납니다:

> `cross-tier adds are not supported in v1: requested "kiki-s-broom/whymath" but session already has repos from owner(s) [doldori7]`

git push/fetch/PR 생성은 저장소가 같은 실체이기 때문에 GitHub가 리다이렉트해줘서 정상 동작했지만, "이 저장소의 owner.type이 Organization인가" 같은 세부 API 조회는 이 세션의 도구 스코프로는 확인할 수 없습니다. 그 확인은 `kiki-s-broom/WhyMath`를 시작 저장소로 하는 새 세션에서 하거나, Kiki가 웹에서 직접 확인해야 합니다(§3 ②가 사실상 같은 확인을 대신합니다).

## 5. 다음 단계

1. Kiki가 위 §3을 완료 (게이트 `G-canonical-repo-cutover-kiki-s-broom` clear 대상).
2. 새 세션(또는 이 정보를 넘겨받은 세션)에서 `HARN-96`의 나머지 acceptance(계정 유형 API 확인·CI 배선 실측·정본 참조 갱신)를 진행.
3. 이미 저장소가 전환되어 있으므로, `doldori7/WhyMath`에서 진행 중이던 다른 세션들의 브랜치·claim은 그대로 `kiki-s-broom/WhyMath`에 남아 있습니다 — 별도 이관 작업은 불필요합니다(§6 참고).

## 6. 정정 이력

- **2026-09-09 (같은 날 1차 정정)**: 최초 작성 시 "복사본 + 수동 시크릿 재등록 필요"로 안내했으나, 이 브랜치를 실제로 push하는 과정에서 GitHub의 저장소 전환 리다이렉트를 확인해 정정했다. 함께 갱신: `HARN-96` acceptance ⑨ 추가, 게이트 `G-canonical-repo-cutover-kiki-s-broom` 제목·notes 정정.
