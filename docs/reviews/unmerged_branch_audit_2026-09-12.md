# 미머지 브랜치 전수 감사 11회차 — 2026-09-12

> **판정 기준: main `8201d018`** (unshallow — 이 세션이 시작 시 `git fetch --unshallow origin` 실행,
> `git rev-list --count HEAD` 44 → 1109). 이 문서는 그 시점의 스냅샷이며, 선행 판정 문서
> (10회차 `_2026-09-10.md`)는 수정하지 않는다.

## 0. 계기

Kiki의 "백로그등재" 지시에 따라 `/stray-code` 스킬을 실행했다. SessionStart 하네스 브리핑이
직접 열거한 **고립 브랜치 11건 + PR 닫힘(미머지) 3건 = 14건**을 감사 모집단으로 삼았다.

## 1. 방법 — 재검증, 신규 조사 아님

이 저장소는 이미 2026-09-10에 동일 절차로 이 14건 중 **13건**을 감사했다(10회차 문서).
14번째(`ops-50-51-52-moe-rocm-followup`)는 그날 아직 PR #860이 열려 있어 감사 범위 밖이었고,
오늘 그 PR을 superseded 판정으로 종료하면서 처음 고립 상태가 됐다.

이번 회차는 서브에이전트(워크트리 격리·읽기 전용)에 위임해 13건 전부를 `git rev-list
--left-right --count`·`git diff --name-only`로 **독립 재실측**했다 — 결과는 10회차 표와
파일 diff 건수·src 파일 건수가 **완전히 일치**했다(main이 이틀간 전진한 커밋 수만 증가,
브랜치 쪽은 신규 커밋 0). 즉 10회차의 교차검증(main grep 기반 코드 실재 확인 포함)이 여전히
유효하다. 14번째 브랜치는 처음부터 전체 절차(내용 해시 대조·소유 태스크 notes 대조)를 새로
수행했다(§3).

## 2. 판정 표 (14건)

| # | 브랜치 | ahead/behind | diff(src) | 판정 | 소유/근거 |
|---|---|---|---|---|---|
| 1 | `whymath-service-operations-review-5t5lmv` | 339/6 | 33(17) | 추적중 | OPS-40(todo) |
| 2 | `remaining-track-34zvse` | 334/16 | 33(23) | 추적중 | CUR-08(done·PR #810)+CUR-07/HARN-80(todo 잔여) |
| 3 | `whymath-data-platform-design-t608mk` | 339/1 | 7(0) | 추적중 | OPS-41(todo — MEMORY ClickHouse 결정 유일 사본) |
| 4 | `whymath-pedagogy-review-gdmwhk` | 343/1 | 31(21) | 추적중 | PED-26(todo·코드 잔여 0, 문서 정리만 남음) |
| 5 | `subject-problems-theory-check-7n9n72` | 343/34 | 83(49) | 추적중 | ASM-06(blocked)·MISC-01/02/03/05/06·PB-02·PED-14·S3-33/34·HARN-79(todo) |
| 6 | `whymath-issues-review-k20m0w` | 355/45 | 133(95) | 추적중 | **MOB-18(in_progress)**+SEC-24/SEC-30/PB-14/HARN-25(todo) |
| 7 | `whymath-constitution-rules-check-azdnov` | 343/1 | 5(0) | 추적중 | OPS-41(todo) |
| 8 | `whymath-coding-architecture-iws58k` | 349/1 | 16(1) | 추적중 | ARCH-30(todo) |
| 9 | `whymath-mvp-plan-architecture-trjg5x` | 396/81 | 233(188) | 추적중 | PB-06(done·PR #795)+**PB-13(in_progress·claim: claude/stray-code-qkv4xt)**+PB-14/PATH-03/ADMIN-02(todo) |
| 10 | `whymath-ai-recommendation-review-q8tvcx` | 408/3 | 11(2) | 추적중 | HARN-15/SEC-32(done)+OPS-38/OPS-67(todo) |
| 11 | `openrouter-setup-guide-e98dw4` | 430/13 | 37(27) | 추적중 | NLP-04/S3-28/VIZ-06/S4-59/S3-32(done)+VIZ-11(todo) |
| 12 | `ops-50-51-52-moe-rocm-followup`(PR #860 오늘 종료) | 258/6 | 39 | **삭제 가능(신규)** | 아래 §3 |
| 13 | `whymath-curriculum-design-6eejrv`(PR #802 닫힘) | 307/9 | 6(3) | 추적중 | PB-08(todo·잔여 0) |
| 14 | `whymath-pedagogy-review-uqyg79`(PR #675 닫힘) | 424/38 | 76(51) | 추적중 | PED-26(gdmwhk와 동일 좌석·잔여 0) |

**신규 회수 태스크 등재 0건** — 14건 중 13건은 이미 소유 태스크가 브랜치를 head SHA·파일 단위로
명시하고 있어 중복 등재 대상이 아니다(추론이 아니라 각 태스크 acceptance 본문을 직접 읽어 확인 —
스킬 §3의 "언급≠회수" 함정을 피하기 위해 소유 태스크가 실제로 그 산출물의 범위를 다루는지까지
대조했다). 1건(#12)만 순수 흡수 확인 후 삭제 배치로 넘어간다.

## 3. `ops-50-51-52-moe-rocm-followup` 상세 (신규 판정)

head SHA `167b5dd0`. `git diff --name-status origin/main...origin/<b>`는 39건을 보고하지만
(main이 분기 이후 대부분의 같은 파일을 독립적으로 더 발전시켰으므로), 병합 기준점(merge-base)
대비 **브랜치가 추가한 줄만** 추출해 main 현재본에 존재하는지 대조했다:

- LIC-01 rights 모듈 9개 파일 — **바이트 동일**(main에 그대로 존재)
- `quality_tier_moe_accuracy_battle.py` — main이 더 신판(PR #854의 JSON schema 강화·프롬프트
  제약 반영), 브랜치는 구판이라 브랜치 쪽에 있고 main에 없는 것은 없음
- LIC-01 alembic 마이그레이션 — revision-id 헤더만 다르고 본문(~300줄) 동일(체인이 분기 후
  독립 진화한 정상 흔적)
- 나머지 파일들 — 브랜치 고유 추가줄 259개 중 **256개가 main에 그대로 존재**, 3개는 black
  재포맷 줄바꿈 차이일 뿐 내용 손실 아님
- `OPS-52.yaml`(done) notes가 "이 세션이 PR #860 diff에서 결과 서술·doc 갱신을 추가로
  PR #1090으로 포팅했다"고 명시. `OPS-51.yaml`(done, 후속 PR #876가 더 완전한 5프리셋
  재측정으로 대체). `LIC-01.yaml`은 status: in_progress이나 코드는 위 해시 대조로 이미 착지
  확인.

**판정: main 부재 0건 — 삭제 가능.** `.github/branch-cleanup-request.txt` 10차 배치에 등재했다.

## 4. 직전 배치 집행 확인 — 미실행 (범위 밖)

이번 회차는 `ls-remote`로 누적 22건(9차까지)의 잔존 여부를 재확인하지 않았다 — Kiki의
요청 범위는 "이번 브리핑이 지목한 14건의 등재 여부 판단"이었고, 과거 배치 집행 확인은
`branch-cleanup.yml` 워크플로 자체가 매 main 머지마다 수행한다. 필요하면 별도 회차에서 확인한다.

## 5. 정직한 공백

- 서브에이전트에 위임한 조사라 이 문서를 쓴 세션이 모든 git 명령을 직접 눈으로 재확인하지는
  않았다 — 다만 13건 중 다수는 10회차 문서와 파일 diff 건수·src 건수가 정확히 일치함을
  세션이 직접 대조했고(§1), 신규 1건(#12)의 해시 대조 방법론은 서브에이전트 보고서 원문을
  검토해 스킬의 "main 코드 grep으로 교차 확인" 요구를 실제로 충족했는지 확인했다.
- `whymath-issues-review-k20m0w`(MOB-18)와 `whymath-mvp-plan-architecture-trjg5x`(PB-13)는
  각각 다른 세션이 **지금 in_progress로 작업 중**일 수 있다 — 이 문서는 그 작업에 개입하지 않는다.
- 12건 미해결 브랜치의 실제 회수 실행(파일 단위 이식)은 이 감사의 범위가 아니다 — 각 소유
  태스크가 `/drive`로 실행될 때 진행된다.

## 6. 검증

```bash
python3 scripts/harness/backlog.py validate --quiet; echo "EXIT=$?"   # 0
python3 scripts/harness/backlog.py next --n 3                          # 등재 변경 없음 확인용 — 신규 태스크 없음
```
