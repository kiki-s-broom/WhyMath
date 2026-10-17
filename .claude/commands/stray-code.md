---
description: 떠돌이 코드 정리 — 미머지 고립 브랜치 전수 감사·회수 태스크 등재·삭제 배치. "떠도는 코드"·"머지 안 된 브랜치"·"고립된 작업" 점검 요청 시 사용
argument-hint: "[report-only] (인자 없으면 판정+등재+삭제배치까지, report-only면 판정 보고만)"
---

# /stray-code — 떠돌이 코드(미머지 고립 브랜치) 정리

## 임무
원격 브랜치 **전수**를 감사해 ①회수할 고립 작업 ②이미 추적 중인 것 ③잃을 내용 없이
삭제 가능한 것 ④판정 대상 아닌 것(제외)을 판정하고, 미추적 고립분에 **회수 태스크를 등재**하며 삭제 후보를
**삭제 배치에 등재**한다. **코드 이식은 이 스킬의 범위가 아니다** — 이식은 등재된 회수
태스크를 `/drive`가 실행한다.

선례 정본(방법·함정의 출처 — 새로 고안하지 말고 이 문서들을 따르라):
- `docs/reviews/unmerged_branch_verdict_2026-08-11.md` — 탐지기 결함 4종(§1)과 그 수정
- `docs/reviews/unmerged_branch_audit_full_2026-08-11.md` — 전수 감사 절차·재현 명령 전문(§1)

## 실행 절차

### 0. 전제 복구 — shallow면 판정 금지
> 세션 브리핑의 `📡 고립 브랜치` 줄(HARN-28)은 CI 야간 리포트(`harness-reports`)다 — 세션이 shallow여도
> 1차 후보 목록으로 쓸 수 있다. 단 **최대 하루 묵은 스냅샷**이므로 삭제·회수 전에는 아래 절차로 재측정한다.
> 리포트 상태 조회: `python3 scripts/harness/isolation_report.py show`

```bash
git rev-parse --is-shallow-repository   # true면 ↓ 필수 (안 하면 ahead 수치·포팅 근거 전부 오염)
git fetch --unshallow origin
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'   # --prune 없으면 유령 브랜치 잔존
```

### 1. 모집단 분리
1. 원격 브랜치 전수 목록 (`git for-each-ref refs/remotes/origin`) — `harness-claims`·`harness-reports`는 제외
   (하네스 소유 데이터 브랜치, 작업 브랜치 아님)
2. 열린 PR 목록 (GitHub MCP `list_pull_requests` — `fields`로 number·head만 요청, 전체 응답은
   토큰 상한을 넘는다) → **PR 있는 브랜치는 각 PR이 소유** — 감사 범위 밖.
   역방향도 본다: **head 브랜치가 원격에 없는 열린 PR(유령 PR)은 별도 보고**한다 — 소유 관계가
   끊긴 상태라 어느 분류에도 못 들어간다
3. **원격 claim 활성 브랜치**는 손대지 않는다 (다른 세션 작업 중). 세션 브리핑이 없으면
   `git show origin/harness-claims:claims/` 트리를 직접 조회해 활성 claim을 확보한다
4. 나머지 = **PR 미오픈 브랜치** — 이것이 감사 대상

### 2. 브랜치별 3축 측정
```bash
# ① 규모: ahead/behind + 내용 diff (diff 0파일이면 전량 흡수 → 삭제 후보)
git rev-list --left-right --count origin/main...origin/<b>
git diff --name-only origin/main...origin/<b> | wc -l

# ② 고립 done 대조 (브랜치 done vs main done — #701 선례)
for f in $(git diff --name-only origin/main...origin/<b> -- backlog/tasks/); do
  bs=$(git show origin/<b>:$f | grep -m1 '^status:'); ms=$(git show origin/main:$f 2>/dev/null | grep -m1 '^status:')
  [ "$bs" = "status: done" ] && [ "$ms" != "status: done" ] && echo "ISOLATED: $f (main=${ms:-부재})"
done

# ③ done-less 사각 보완 (HARN-31): done 표기가 없어도 src/tests/data 신규 파일이 있으면 고립 후보
git diff --name-only origin/main...origin/<b> | grep -cE '^(src|tests|data|scripts)/'
```
②만 믿으면 안 된다 — 구현을 마치고 태스크를 닫지 않은 브랜치(gdmwhk 실사례)는 ②가 0을 낸다.
③이 0이 아니면 반드시 내용을 열어 본다.
(HARN-31 착지 후) ③은 `backlog.py branches`·세션 브리핑이 고립·PR닫힘·미판정 브랜치마다 자동으로 낸다 —
`구현 신호: 신규 N파일 · 수정 M파일`(양수) / `구현 신호 없음`(0) / `판정 불가: <사유>`(측정 실패)로
세 상태가 갈린다. 위 수동 명령은 그 출력을 재현·검증할 때만 쓴다.

### 3. 추적 여부 판정
```bash
git grep -l "<브랜치 접미사>" origin/main -- backlog/tasks docs
```
- 언급 있음 → 어느 태스크/PR이 소유하는지 확인 후 **재등재 금지** (중복 구현이 이 저장소
  최다 반복 사고다 — 교수전략 카탈로그는 4차 중복 직전까지 갔다)
- 언급 0건 + 고립 내용 있음 → **미추적 고립** — 회수 태스크 등재 대상
- 단, "언급"≠"회수": 문서·백로그만 고친 커밋이 브랜치를 *언급*한 것은 흡수가 아니다
  (#785 오탐 사고 — 판정 문서 커밋이 판정 대상을 "해결됨"으로 뒤집었다). 소유 태스크가
  실재하고 그 acceptance가 해당 산출물을 다루는지까지 확인하라.

### 4. 판정의 이중 확인 (가장 중요한 축)
태스크 status 대조만으로 "부재/포팅됨"을 선언하지 않는다 — **main 코드 grep으로 교차**한다:
```bash
git show origin/main:<핵심 파일> | grep -cE '<브랜치가 추가한 핵심 심볼>'   # 0이면 진짜 부재
```
브리핑의 "이미 포팅됨" 분류도 근거 커밋을 열어 실작업 커밋인지 확인한다(40xspg가
문서 커밋을 근거로 "포팅됨" 오분류돼 2,153줄이 삭제 직전까지 갔다).

**소유 태스크가 done이어도 끝이 아니다** — 회수 태스크는 파일 단위 이식이라 done 후에도
브랜치에 잔여 diff가 남는 경우가 흔하다(실측: 40xspg 3파일·e98dw4 4파일). done 확인 후
잔여 diff를 재열거하고, **잔여분마다 후속 소유자(태스크 acceptance의 범위 명시·열린 PR)를
지목하지 못하면 삭제 후보로 내리지 말라.** 소유·삭제 권한은 태스크 acceptance 본문에만
적혀 있는 경우가 많으니(SOL-01 ②·NLP-04 ⑥ 선례) status만 보지 말고 본문을 정독한다.
잔여 정정이 인플라이트 PR에 실려 있는지도 대조한다(my18a1의 config.py 정정이 PR #783에
실려 있음을 확인하고서야 "조건부 삭제"가 성립한 선례).

### 5. 조치 (report-only가 아니면)
1. **판정 문서**: `docs/reviews/unmerged_branch_audit_<날짜>.md` — 시점 스냅샷 선언·재현 명령·
   4분류 표(회수/추적중/삭제/제외)·정직한 공백. 선행 판정 문서는 수정하지 않는다.
2. **회수 태스크 등재**: 전건 `python3 scripts/harness/backlog.py add` 경유 — 번호 손배정 금지,
   CLI 거부 시 제안 번호 채택. acceptance에 반드시 분리 기재:
   - ① 고립 실측 고정(브랜치 head SHA·재현 명령)
   - ② 이식 방식 = **파일 단위**(브랜치는 main보다 낡았으므로 통째 머지 금지 — NLP-04 선례)
     + 원 번호 재사용 금지(ID 충돌: 같은 번호가 브랜치와 main에서 다른 태스크인 사례 누적 9건)
   - ③ **집행 지점**(계약이 실제 서빙/CI 경로에서 경유되는지 — 정본화와 별항)
   - notes에 "회수 완료 전 원 브랜치 삭제 금지" 명시
3. **보안·법령 관련 고립분은 priority 1** (의사결정 우선순위 2번 — 협상 불가)
4. **block 사유만 있는 브랜치**: `backlog.py block <id> --reason`으로 main에 이관 후 삭제 후보로
5. **삭제 배치**: `.github/branch-cleanup-request.txt`에 등재 — 파일 상단 관례 준수
   (head SHA 스냅샷 주석·회수 태스크 등재 브랜치 제외 경고·직전 배치 집행 확인 `ls-remote` 잔존 0/N)
6. **MEMORY.md 결정 로그** 1건 + 커밋 + **PR 생성**(기본값). Kiki가 "pr"을 주면 auto-merge(SQUASH)까지

### 6. 검증 (report-only에서도 실행 — 읽기 전용이며 판정과 상호 확증된다)
```bash
python3 scripts/harness/backlog.py validate; echo "EXIT=$?"   # 판정은 exit code — -q/tail 금지
python3 scripts/harness/backlog.py next --n 3                 # 등재 태스크가 실제 후보로 뜨는지 (배선 확인)
```

## 함정 카탈로그 (전부 실측 사고 — 새로 겪지 말 것)
| 함정 | 결과 | 방어 |
|---|---|---|
| shallow 클론에서 판정 | ahead 657~720 부풀림·포팅 오판 | §0 unshallow 선행 |
| `--prune` 누락 | 삭제된 브랜치 유령 23건 | §0 |
| 커밋 본문 grep으로 흡수 판정 | 판정 문서가 대상을 "해결"로 뒤집음 | §3 소유 태스크 실재 확인 |
| done 대조만 신뢰 | 구현만 있는 브랜치 항구 무시 | §2-③ 내용 신호 |
| 번호 손배정 | 병렬 세션 인플라이트 번호와 충돌 | CLI add만 사용 |
| 통째 머지 | main 완료분 44k~170k줄 역행 | 파일 단위 이식 고정 |
| 부분 성공을 전체로 보고 | — | 잔존 한계는 "정직한 공백"에 명시 |
