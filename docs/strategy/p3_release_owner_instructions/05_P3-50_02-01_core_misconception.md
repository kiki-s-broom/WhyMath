# [05] P3-50 — 02-01 오개념 사슬 복구 (핵심 오개념 교체 결정 → 집행)

| 구분 | 내용 |
|---|---|
| 순서 | 05 / 10 |
| 막는 곳 | Release 축 Gate B ⑦ — 02-01 |
| 작성 시점 상태 | 판정 회수 PR #1855 머지(`2a694f71`). 결정 게이트 `G-p350-02-01-core-and-route` pending(2026-11-06 요청) — Q1 핵심 오개념(가: M0075·M0080 → M0669 교체, 권고) · Q2 보강 경로(A: 정직한 재귀속 + 새 객관식 문항, 권고) · Q3 M0669용 kebab 별건 신설. Q1은 `G-p359-m0672-shadow-disposition`(pending)과 묶인다. 태스크는 `in_progress`(회수 세션 claim) |
| 시작 조건 | G-p350 cleared(Q1이 '다'면 G-p359도) |
| 완료 판정 | phase3_coverage에서 02-01 충족 |
| 규모 | 중~대 — Q1 가 · Q2 A면 명세 변경 + kebab 신설(카탈로그·크로스링크 서명) + 새 은행(n≥200) + 감사 |

**붙이는 법**: 새 세션 첫 메시지로 아래 블록 전체를 그대로 붙여넣는다. 게이트가 pending이면 블록은 결정 요청만 다시 보여 주고 끝난다.

---

## 붙여넣을 지시문 (복사 범위: 아래 블록 전체)

```text
[WhyMath 소유 태스크 공통 프리앰블 — 이번 세션 전체에 적용]

너는 WhyMath 저장소(kiki-s-broom/WhyMath)에서 통합 게이트 `G-p3-w3-release-merged`(Week 3 + Phase 3 Release 통합 판정)의
FAIL을 해소하는 소유 태스크 하나를 맡는 엔지니어다. 이번 세션은 맨 아래 [이번 세션 항목] 하나만 다룬다.

[배경]
- P3-17 통합 판정(2026-11-05 · 판정 기준 main 036286a1 · docs/reviews/p3_17_week3_release_judgment_2026-11-05.md)은 FAIL이었다.
  독립 검토(docs/reviews/p3_17_verdict_review_2026-11-06.md · PR #1854로 main에 들어온다 — 미머지면 그 PR 브랜치에서 읽는다)는
  결론에 동의하고 재판정을 11/29로 제안했다.
- 성공 기준 Q1은 Kiki 결정(2026-11-06)으로 학생 수 조건이 삭제됐다. 새 Q1 = "개발자가 학생별 데이터를 직접 만지지 않고,
  AI가 학습 루프 전 과정을 검토·점검해 문제를 분석·해결한 기록으로 학습이 돌아감을 보일 수 있는가". 반영 PR은 #1854다.
- 이 지시문은 main 2a694f71(2026-11-06) 기준으로 썼다. 그 뒤 상태가 바뀌었을 수 있다 — 아래 0단계의 실측이 정본이다.

[0단계 — 착수 전 상태 확인 (대장·git 조회만 · 대상 코드는 아직 열지 않는다)]
1. `git fetch origin main` 후 `git log origin/main -1 --oneline`. 이 해시가 이번 세션의 판정 기준이다.
2. 대상 태스크 상태를 main 대장에서 읽는다(`python3 scripts/harness/backlog.py status` 또는
   `git show origin/main:backlog/tasks/<파일>`). 이미 done이면 아무것도 바꾸지 말고 "이미 완료 — 증적 <PR>"만 보고하고 끝낸다.
3. 다른 세션의 claim: `python3 scripts/harness/backlog.py claims list --verbose`. 대상에 남의 claim이나 대장 session이 있으면
   그 브랜치의 마지막 커밋 시각(`git ls-remote origin <브랜치>` → fetch → `git log -1 --format=%cI FETCH_HEAD`)과 열린 PR
   (`gh api -X GET search/issues -f q='repo:kiki-s-broom/WhyMath is:pr is:open head:<브랜치>'`)을 본다.
   - 24시간 안에 커밋이 있거나 PR이 열려 있으면: 착수하지 않는다. 근거를 보고하고 끝낸다.
   - 72시간 넘게 커밋이 없고 열린 PR도 없거나 원격 브랜치가 사라졌으면: stale이다. 근거(마지막 커밋 시각·PR 0건)를 보고에 적고
     `python3 scripts/harness/backlog.py unblock <id>`(claim·session 해제) → `start <id>`로 인수한다. 원격 claim 때문에 start가
     거부되면 stale을 확인한 뒤에만 `start <id> --ignore-remote-claim`을 쓴다.
   - 그 사이(24~72시간)면: 착수하지 말고 사용자에게 인수 여부를 묻는다.
4. 항목의 [착수 조건]을 main에서 확인한다. 조건이 안 되면 착수하지 않고, 무엇이 막는지와 누가 풀어야 하는지
   (Kiki 결정이면 선택지 표와 권고까지)를 보고하고 끝낸다. 이것은 실패가 아니라 정상 종료다(PR 예외 ① 조사 전용).

[착수 규율]
- 대장 조회 다음의 첫 행위는 `python3 scripts/harness/backlog.py start <태스크ID>`다. claim 전에 대상 코드를 열거나 쓰지 않는다.
- 결정 대기나 단계 완료로 세션을 끝낼 때 태스크가 아직 done이 아니면 `unblock <id>`로 claim을 놓는다. 주인 없는 in_progress를
  남기지 않는다(P3-44가 2026-10-17부터 사라진 세션의 in_progress로 남아 있던 선례).
- 코드 작업 전에 그 작업이 닿는 규칙을 `constitution/rules.yaml`에서 확인한다. `constitution/` 폴더는 읽기만 한다.
- 판정 근거는 main 실측이다. 보고와 판정 문서 상단에 `판정 기준: main <해시>`를 적는다. 미머지 브랜치를 근거로 조건을 닫지 않는다.
- 부재를 단정하기 전에 ①역할 기반 재검색 ②호출측 역추적 ③그래도 0건이면 "내가 찾은 방법으로는 0건"이라고 범위를 밝힌다.
- 새 태스크는 `backlog.py add`로만 등재한다(번호를 눈으로 고르지 않는다). 대장 YAML을 손으로 고치지 않는다 — `amend`·`gates amend`를
  쓴다. 백틱이 든 한국어 산문을 CLI 인자로 넘길 때는 인용 heredoc(<<'EOF')으로 파일에 쓰고 "$(cat 파일)"로 넘긴 뒤,
  대장을 다시 읽어 내용이 보존됐는지 대조한다.

[범위 규율 — Phase 3]
- EOS Core 신규 Entity / 대규모 DB 스키마 변경 / 새 AI Agent / 새 Subject Adapter / 대규모 UI 구조 변경은 원칙적으로 금지다
  (예외는 Release Blocker뿐). 이번 항목이 그것을 요구하는 것처럼 읽히면 구현하지 말고 결정 요청으로 바꾼다.
- 대표 과정(미적분Ⅰ 미분 10개 개념) 밖의 콘텐츠를 채우지 않는다. 발견한 별건은 `backlog.py add`로 등재만 한다.

[아키텍처·콘텐츠 규율]
- LLM은 학습 상태를 바꾸지 않는다. 모든 LLM 호출은 라우터(l3/router.py) 경유 + Langfuse 추적이다. 학생에게 가는 LLM 응답은
  PRM 또는 도구 검증을 통과해야 한다. 수학 동치·정답 검증은 SymPy 단일 권위 경로만 쓴다.
- 오개념을 LLM 초기 context에 preload하지 않는다. 콘텐츠는 데이터다 — 소스 코드에 하드코딩하지 않는다.
- 동결 명세(data/corpus/phase3_scope_v1/scope_spec.yaml)·오개념 코퍼스·크로스링크 서명(검수:kiki)은 Kiki 결정 없이 바꾸거나
  대신 서명하지 않는다.
- 승인된 문항 은행은 제자리 수정하지 않는다. 감사받은 바이트 = 승격할 바이트다. 라벨만 바꿔 지표를 올리는 재연결은 금지다 —
  선택지 값이 그 오개념 절차로 실제로 나오는지 SymPy로 확인한다.

[결정 규율]
- decision 게이트는 Kiki 몫이다. 에이전트가 `gates clear --as kiki`로 대행하지 않는다.
- 결정이 필요하면 선택지 2~4개, 선택지별 영향(어느 게이트 축이 언제 풀리는가·비용·학생 안전·되돌리기), 권고 1개를 문서로 만든다.
  게이트가 없으면 `gates add <G-id> --kind decision --assignee kiki --title "..." --no-inputs "..."`로 등재하고
  `amend <태스크> --gate <G-id> --reason "..."`로 붙인다. 이미 있으면 `gates amend <G-id> --note "..."`로 근거만 보강한다. 그리고 멈춘다.
- 사용자에게 결정을 물을 때는 채팅에 선택지 표와 권고를 그대로 보여 준다. 문서 링크만 주지 않는다.

[검증 규율]
- 새 가드·테스트·계측기는 막으려는 상태를 실제로 주입해 RED를 확인한 뒤에만 "보호된다"고 말한다. 주입이 실제로 적용됐는지
  (mutated != original), 원복이 바이트 동일한지를 단언한다. 대조군(정상 입력)이 GREEN인지도 함께 본다.
- 판정은 exit code로 한다. `-q`나 `| tail`로 출력을 자르지 않는다. 래퍼는 검사 명령의 종료 코드를 그대로 돌려준다.
- 백엔드 소스·테스트를 건드렸으면 전체 스위트를 돌린다. 못 돌렸으면 "전체는 확인하지 못했다"고 적는다.
- 푸시 전에 `python3 scripts/harness/ci_mirror.py run`을 돌린다(변경이 닿는 CI 잡을 자동 선택한다). exit 0만 통과다 —
  3(미실행 검사 있음)·4(실행 중 작업 트리 변경)는 통과가 아니다. 검증이 도는 동안 작업 트리를 바꾸지 않는다.
- 측정 실패를 0건 통과로 위장하지 않는다. 표본 0·분모 0은 "측정 불가"로 적는다.

[Kiki PC 실행이 필요할 때 — 운영 DB·Ollama]
- 명령 블록 앞에 6항목 브리핑(과제 명칭·목적·절차와 예상 시간·성공 기준과 실패 시 대처·실행 환경·창 구분)을 준다.
  Windows PowerShell 기준이고, 작업 장소는 C:\Users\kiki\Desktop\__AI\WhyMath다. 운영 DB는 docker whymath-pg(127.0.0.1:5433)다.
- 공유 클론의 브랜치를 옮기지 않는다. `git worktree add --detach <별도 폴더> <커밋>`에서 실행하고 HEAD를 기대 해시와 대조한다.
  실행기는 `python -m pip`·`python -m pytest`처럼 부른다. 블록이 쓰는 모듈·인자·파일이 그 커밋에 실재하는지 먼저 확인한다.
- 블록에 자리표시자를 하나도 두지 않는다(세션이 채우거나, 블록이 스스로 찾거나, Read-Host로 묻는다). 쓰기 블록은 선행 판정값을
  블록 안에서 다시 계산해 단일 `if (...) { ... } else { "WRITE_REFUSED=True — 이유" }`로 스스로 거부한다. elseif 체인을 쓰지 않는다.

[채팅 형식]
- 사용자에게 보내는 메시지의 코드 펜스는 실행용 전용이며 언어 태그(bash·powershell 등)를 붙인다. 커밋 해시·식별자는 인라인 백틱,
  명령 결과는 요약 문장 + 인용문으로 쓴다.

[산출 규율]
- 커밋이 있으면 PR을 연다. 예외는 조사 전용 / 미완·게이트 대기 / CI red / Kiki 보류뿐이며, 예외로 끝내면 어느 것인지 1줄로 말한다.
  main 머지는 사용자가 "pr"이라고 하거나 Kiki가 판단할 때만 한다.
- 완료는 `python3 scripts/harness/backlog.py done <id> --artifact <PR 번호> --artifact <머지 커밋>`이다. 소유 태스크는 decision 게이트
  `G-p3-w3-release-merged`의 입력이라 CLI가 판정 인계를 요구한다. 판정을 내리지 말고
  `--no-verdict "판정 무관: <무엇>을 재판정 입력으로 넘긴다"`로 인계한다(재판정 회차 파일 10번만 예외).
- 완료 보고에 `python scripts/constitution/audit_ratchet.py`의 종료 코드와 차단 건수를 넣는다.
- 세션 끝에 다음 5줄을 보고한다: ①완료 판정(충족/미충족 · 근거 커밋) ②PR 링크 ③남긴 것과 이유
  ④Kiki께 넘길 결정·행동(선택지 포함) ⑤재판정에 넘길 실측값(명령 · exit code · 값 · 판정 기준 해시).

[이번 세션 항목 — P3-50 02-01 오개념 사슬 복구]

대상 태스크: P3-50-calc-02-01-misconception-chain-restore (또는 아래 (2)에서 찾거나 등재하는 집행 태스크)

입력: docs/reviews/p3_50_02_01_chain_restore_2026-10-18.md(§4 귀속 판정 · §5 보강을 안 한 이유 · §6 겹침 · §7 결정 요청 ·
상단 회수 이식 주석) · 태스크 acceptance 정정(2026-10-18).

분기:
(1) G-p350이 pending → 착수하지 않는다. 채팅으로 Kiki께 Q1·Q2·Q3을 선택지 표와 권고(문서 §7 — Q1 가 · Q2 A · Q3 별건 신설)로
    다시 보여 준다. 함께 적을 것: Q1이 G-p359(M0672가 같은 kebab의 M0075에 가려지는 현상의 처분)와 묶인다는 점, P3-52의 G-p345
    (02-09 처분)에서 (다) 명세 교체를 택하면 같은 scope_spec.yaml 변경이므로 한 PR로 묶으면 측정·감사 왕복이 줄어든다는 점.
    회수 세션 claim이 stale이면 `unblock`으로 놓아 둔다. 끝낸다.
(2) G-p350이 cleared →
  - 집행 대상 정하기: 이 게이트는 P3-50을 입력(gate.depends_on)으로 두므로 회수 세션이 P3-50을 done(판정 인계)하고 집행을 승계
    태스크로 넘겼을 수 있다. main 대장에서 G-p350을 requires_gates로 둔 태스크를 찾는다. 있으면 그것이 대상이다. 없고 P3-50이 아직
    열려 있으면 P3-50이 대상이다. P3-50이 done이면 `add`로 집행 태스크를 등재(requires_gates G-p350 · depends P3-50)해 claim한다.
  - Kiki 선택대로 집행한다:
    · Q1 가 → scope_spec.yaml core_misconceptions의 02-01 교체는 명세 변경 PR로 한다. 게이트 evidence(Kiki 결정)를 PR 본문에 인용하고,
      코퍼스 쪽 변경과 같은 PR에 넣는다(따로 내면 측정이 거부된다 — 문서 §4).
    · Q3 별건 → M0669용 kebab 신설은 별도 태스크로 `add`한다. 크로스링크 서명은 Kiki 몫이므로 서명이 필요한 항목은 게이트로 분리한다.
    · Q2 A → 새 객관식 문항은 새 은행(승인 단위 n≥200) 경로로 한다. P3-44 보강 은행(4개념 × 60 = 240으로 결정됨)과 섞지 않는다.
      raw M-id 직접 기입은 금지다(P3-57이 규명한 계측-서빙 불일치를 재생산한다). 선택지 값이 M0669 절차로 실제로 나오는지 SymPy로 확인한다.
      은행·감사·승격은 P3-44와 같은 S1~S5 절차를 따르고 한 세션에 한 단계만 한다.
  - 완료: `python -m whymath_backend.l1.standards.phase3_coverage --json`을 전후 같은 명령으로 내고 02-01 칸 충족을 보인다.
    `done <대상> --artifact <PR> --artifact <머지 커밋> --no-verdict "판정 무관: ⑦ 02-01 실측(main <해시>)을 재판정 입력으로 넘긴다"`.
```

---

## 세션 종료 후 체크 (Kiki용)

- [ ] (1)이었다면 Q1·Q2·Q3 선택지 표와 권고가 왔는가 → **Kiki 결정 필요**(G-p350, 필요 시 G-p359)
- [ ] (2)였다면 집행 대상 태스크를 어떻게 정했는가(기존 승계 / P3-50 / 신규 등재)
- [ ] 명세 변경이 있었다면 PR 본문에 Kiki 결정 인용이 있는가
- [ ] `phase3_coverage` 전후 값과 exit code
- [ ] PR 링크가 있는가
