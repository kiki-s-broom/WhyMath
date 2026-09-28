# 코딩 헌법 Kiki 런북 — 원본 등록부 정정(A0003)·이식 2단계·A0002 채택·가드 확인·정밀진단

- 태스크: `CONST-02` · 게이트: `G-const-sources-registry-adopt`(과제 A) · `G-const-a0002-adoption`(과제 B) · `G-const-diagnosis-s00-s10-run`(과제 D)
- 이식 정본: `docs/standards/coding_constitution_transplant.md` · 초안 보관소: `docs/constitution_proposals/`
- 판정 기준: 이 런북의 명령은 **CONST-02 PR이 main에 머지된 뒤**의 `origin/main`을 기준으로 한다. 블록마다 그것을 스스로 확인한다(`MAIN_HAS_TOOLS`).

## 0. 왜 Kiki님이 직접 해야 하나

코딩 헌법 제9조 ①은 "AI는 `constitution/` 폴더를 수정·삭제·이동할 수 없다"이고, 제11조는 "헌법과 rules.yaml의 개정은 사람(Kiki)만 한다"이다. 이식 세션(AI)은 이것을 지키기 위해 `constitution/`을 편집하면 막히는 가드(`.claude/hooks/guard_constitution.py`)를 설치했다. 그래서 AI가 찾은 정정은 `docs/constitution_proposals/`에 **초안**으로만 두었고, 그것을 헌법에 반영하는 일은 이 런북으로 Kiki님이 한다.

반영은 손 복사가 아니라 채택 도우미 `scripts/constitution/adopt_amendment.py`로 한다. 손으로 하면 생기는 사고 세 가지를 도우미가 막는다 — ①순서를 바꿔 A0002를 먼저 넣은 뒤 A0003 정정안을 통째로 복사하면 규칙 81건이 사라진다(도우미는 원본 등록부 절만 바꾸고 규칙이 그대로인지 확인한다) ②Windows PowerShell 5.1의 `Set-Content`는 파일 앞에 BOM을 붙이고 줄끝을 CRLF로 바꾼다(도우미는 UTF-8·LF로만 쓴다) ③개정 기록의 서명 칸이 빈 채로 남는다(도우미가 채택일·개정자를 채운다). 도우미는 AI 세션 안에서는 반영을 거부한다(exit 3).

## 순서 요약

| 과제 | 내용 | 필수 여부 | 창 | 소요 |
|---|---|---|---|---|
| A | A0003 채택(원본 등록부 정정) + 이식 단계 1 → 2 | 권장 — 위헌 심사 차단 7건을 0건으로 | 창① | 10~15분 |
| B | A0002 채택(파트 II~VII 근거 조문 5개 + 규칙 81건) | 선택 — 결정 게이트. A가 main에 머지된 뒤 | 창② (새 창) | 10분 |
| C | 헌법 가드가 이 PC(Windows)에서 실제로 막는지 확인 | 권장 — 읽기 전용 | 창③ (새 창) | 3분 |
| D | 260927 통합정밀진단 S00~S10 진행 | 게이트 — 사람 축 검증 | 별도 (Claude Code) | 9~14시간, 4~5일 분할 |

각 과제가 끝나면 블록이 출력한 `대문자_이름=값` 줄들을 통째로 복사해 세션에 전달한다. **PR 생성과 게이트 기록(`backlog.py gates clear`)은 세션이 가져간다** — Kiki님이 할 일은 반영·커밋·push까지다.

---

## 1. 과제 A — A0003 채택 + 이식 2단계

### 사전 브리핑

1. **과제 명칭**: 코딩 헌법 원본 등록부 정정(개정 A0003) 채택과 이식 단계 2 상향.
2. **목적**: 헌법 v1.0의 원본 등록부(`sources`)가 꾸러미를 만들 때의 *제안 경로*를 가리키고 있어, 이 저장소에서 위헌 심사를 돌리면 9건 중 7건이 "원본 없음"으로 차단된다. 이식 세션이 실제 정본 위치를 찾아 정정안을 만들었다(근거: `docs/constitution_proposals/A0003_sources_registry_draft.md`). 이것을 채택하면 차단이 0건이 되고, 그러면 부록 C("한 단계의 규칙이 모두 준수가 된 뒤 다음 단계로")에 따라 이식 단계를 2로 올릴 수 있다. 2단계에서 켜지는 규칙은 R0-01(AI의 헌법 수정 차단) 하나이고, 그 집행 장치(가드 훅)는 이미 설치돼 있다.
3. **구체적 절차**:
   - [A-1] 준비: 메인 클론은 건드리지 않고 옆 폴더 `WhyMath-const`에 main 기준 작업 사본을 새 브랜치로 만든다(약 30초). 여러 세션이 쓰는 메인 클론의 브랜치·미커밋 변경을 하나도 바꾸지 않기 위해서다.
   - [A-2] 미리보기: 무엇이 바뀌는지 출력하고 초안 문서를 메모장으로 연다. 아무것도 쓰지 않는다(약 10초). 초안을 읽고 동의하면 다음으로 간다.
   - [A-3a] 동의 입력: `ADOPT`를 직접 타이핑한다. 이 블록은 한 줄뿐이라 붙여넣기가 여기서 멈춘다.
   - [A-3b] 반영: 동의·준비·미리보기가 모두 True일 때만 `constitution/`의 3개 파일(`rules.yaml`·`STAGE`·새 개정 기록)을 쓴다(약 5초).
   - [A-4] 심사: 위헌 심사 전체 실행(가드 자가시험 44건 포함, 약 20~60초)과 래칫 기준선 갱신.
   - [A-5] 커밋·push: 앞 단계가 모두 성공했을 때만 커밋하고 `kiki/const-a0003-stage2` 브랜치로 올린다(약 10초).
4. **성공 기준**: `READY=True` → `PREVIEW_OK=True` → `APPLY_OK=True` · `STAGE_FILE=2` → `AUDIT_OK=True` · `BASELINE_OK=True` · `RATCHET_OK=True` → `COMMIT_EXIT=0` · `PUSH_EXIT=0`. 어느 블록이든 `…_REFUSED=True`나 `…_SKIPPED=True`가 나오면 **그 블록은 아무것도 쓰지 않은 것**이다 — 같은 줄에 무엇이 False였는지 찍히므로 그 값을 세션에 그대로 전달한다(대처 1개: `MAIN_HAS_TOOLS=False`면 CONST-02 PR이 아직 머지 전이다 — 머지 후 A-1부터 다시).
5. **실행 환경**: Phaiakes9(이 PC)의 Windows PowerShell. 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건: CONST-02 PR 머지 완료 · 백엔드 가상환경 `src\backend\.venv` 존재(PyYAML 포함). Docker·DB·서버는 필요 없다.
6. **창 구분**: **새 창 하나(창①)** 에서 A-1 → A-2 → A-3a → A-3b → A-4 → A-5를 순서대로 붙여넣는다. 앞 블록이 만든 변수(`$Ready`·`$ApplyOk` 등)를 뒤 블록이 재검사하므로 **같은 창**이어야 한다. 서버를 띄우지 않으므로 이 창은 중간에 다른 조회를 해도 된다.

### [A-1] 준비 — main 기준 작업 사본 만들기

```powershell
# [창① A-1 준비] Windows PowerShell — Phaiakes9
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git cat-file -e origin/main:scripts/constitution/adopt_amendment.py
$MainHasTools = ($LASTEXITCODE -eq 0)
"MAIN_HAS_TOOLS=$MainHasTools"
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-const"
$Br = "kiki/const-a0003-stage2"
if (Test-Path $Wt) { git worktree remove --force $Wt; git worktree prune; "OLD_WORKTREE_REMOVED=" + (-not (Test-Path $Wt)) }
if ($MainHasTools) { git worktree add -B $Br $Wt origin/main } else { "WORKTREE_SKIPPED=True — main에 CONST-02 도구가 아직 없습니다(PR 머지 전). 머지 후 이 블록을 다시 붙여넣으세요." }
"WORKTREE_HEAD=" + (git -C $Wt log -1 --oneline)
$BaseOk = ((git -C $Wt rev-parse HEAD) -eq (git rev-parse origin/main))
"BASE_MATCHES_MAIN=$BaseOk"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$PyOk = Test-Path $Py
"PY_OK=$PyOk"
& $Py -c "import yaml; print('YAML_OK=True')"
"STAGE_BEFORE=" + (Get-Content "$Wt\constitution\STAGE")
$Ready = $MainHasTools -and $BaseOk -and $PyOk
"READY=$Ready"
```

**확인**: `MAIN_HAS_TOOLS=True` · `BASE_MATCHES_MAIN=True` · `PY_OK=True` · `YAML_OK=True` · `STAGE_BEFORE=1` · `READY=True`. `OLD_WORKTREE_REMOVED=False`가 나오면 탐색기에서 `WhyMath-const` 폴더를 직접 지우고 이 블록을 다시 붙여넣는다(등록되지 않은 빈 폴더가 남으면 `worktree add`가 "이미 있다"로 실패한다).

### [A-2] 미리보기 — 아무것도 쓰지 않는다

```powershell
# [창① A-2 미리보기] Windows PowerShell — 같은 창 · 읽기 전용
& $Py "$Wt\scripts\constitution\adopt_amendment.py" A0003 --stage 2
$PreviewOk = ($LASTEXITCODE -eq 0)
"PREVIEW_OK=$PreviewOk"
& $Py "$Wt\scripts\constitution\audit.py" --no-run --sources-only
"AUDIT_BEFORE_EXIT=$LASTEXITCODE"
notepad "$Wt\docs\constitution_proposals\A0003_sources_registry_draft.md"
```

**확인**: `ADOPT_RESULT=preview` · `PREVIEW_OK=True`. 반영 계획에 `constitution/rules.yaml`(수정)·`constitution/STAGE`(수정)·`constitution/amendments/A0003_원본등록부정정.md`(신규) 3줄이 보인다. `AUDIT_BEFORE_EXIT=1`은 **정상**이다 — 지금은 원본 등록부 차단 7건이 있고, 그것을 없애는 것이 이 과제다.

메모장에 열린 초안의 「정정 내역」 표를 읽는다. 정정 경로 9건이 동의되지 않으면 여기서 멈추고 세션에 어느 줄이 문제인지 알린다(초안을 고쳐 다시 드린다). 「판단을 Kiki에게 남긴 것」 3건(정본이 두 곳 이상인 데이터)은 이번 채택과 무관하다 — 나중에 따로 결정하면 된다.

### [A-3a] 동의 입력 — 이 한 줄만 붙여넣는다

```powershell
# [창① A-3a 동의] Windows PowerShell — 같은 창 · 이 블록은 한 줄뿐이며 입력을 기다린다
$Answer = Read-Host "A0003을 채택하고 이식 단계를 2로 올리려면 ADOPT 를 입력하고 Enter"
```

`ADOPT`를 **직접 타이핑**하고 Enter를 누른다(대문자, 영어). 다른 것을 입력하면 다음 블록이 반영을 거부한다 — 그것이 의도된 동작이다.

### [A-3b] 반영 — 여기서만 헌법 파일을 바꾼다

이 블록은 A-1·A-2·A-3a의 판정값을 **스스로 재검사하고**, 하나라도 False면 아무것도 쓰지 않고 이유를 출력한다. 눈으로 확인하라는 안내에 기대지 않는 이유는, 판정값이 화면에 정확히 찍혔는데도 쓰기 블록이 그대로 붙여넣어진 사고가 이 저장소에 있었기 때문이다(출력은 흐름을 멈추지 않는다 — HARN-106).

```powershell
# [창① A-3b 반영] Windows PowerShell — 같은 창 · constitution/ 을 바꾸는 블록
$Consent = ($Answer -ceq "ADOPT")
"READY=$Ready · PREVIEW_OK=$PreviewOk · CONSENT=$Consent"
if ($Ready -and $PreviewOk -and $Consent) { & $Py "$Wt\scripts\constitution\adopt_amendment.py" A0003 --stage 2 --apply; $ApplyOk = ($LASTEXITCODE -eq 0); "APPLY_OK=$ApplyOk" } else { $ApplyOk = $false; "WRITE_REFUSED=True — READY=$Ready PREVIEW_OK=$PreviewOk CONSENT=$Consent · 셋 다 True여야 반영합니다" }
"STAGE_FILE=" + (Get-Content "$Wt\constitution\STAGE")
git -C $Wt status --short
```

**확인**: `ADOPT_RESULT=applied` · `RULES_COUNT=14` · `SOURCES_COUNT=9` · `STAGE_NOW=2` · `APPLY_OK=True` · `STAGE_FILE=2`. `git status` 줄은 `M constitution/STAGE` · `M constitution/rules.yaml` · `?? constitution/amendments/` 세 줄이다(한글 파일명은 `"…\354\233…"`처럼 따옴표 안 숫자로 보일 수 있다 — 정상).

### [A-4] 위헌 심사 + 래칫 기준선 갱신

```powershell
# [창① A-4 심사] Windows PowerShell — 같은 창 · 기준선 파일(metrics/)을 갱신하는 블록
if ($ApplyOk) { & $Py "$Wt\scripts\constitution\audit.py"; $AuditOk = ($LASTEXITCODE -eq 0); "AUDIT_OK=$AuditOk"; & $Py "$Wt\scripts\constitution\audit_ratchet.py" --update-baseline; $BaselineOk = ($LASTEXITCODE -eq 0); "BASELINE_OK=$BaselineOk"; & $Py "$Wt\scripts\constitution\audit_ratchet.py"; $RatchetOk = ($LASTEXITCODE -eq 0); "RATCHET_OK=$RatchetOk" } else { $AuditOk = $false; $BaselineOk = $false; $RatchetOk = $false; "AUDIT_SKIPPED=True — APPLY_OK=$ApplyOk · 반영이 안 됐으므로 심사하지 않습니다" }
"BASELINE_FILE=" + (Get-Content "$Wt\metrics\coding_constitution_audit_baseline.json" -TotalCount 4 | Select-Object -Last 2)
```

**확인**: 심사 표 첫머리에 `심사 항목 23개 · 차단 사유 0건`, 그리고 `| R0-01 | L5 | ✅ 통과 |` 줄(가드 자가시험 44건이 이 PC에서 전건 일치했다는 뜻). 이어서 `AUDIT_OK=True` · `✅ 기준선 갱신: 단계 1→2 · 차단 7 → 0건` · `BASELINE_OK=True` · `✅ 위헌 심사 래칫 통과 — 단계 2 · 차단 0건` · `RATCHET_OK=True`.

`R0-01`이 `⛔ 위반`이면 가드 자가시험이 이 PC에서 실패한 것이다 — 그 줄 전체를 세션에 전달한다(이 경우 A-5는 스스로 거부된다).

### [A-5] 커밋과 push

```powershell
# [창① A-5 커밋·push] Windows PowerShell — 같은 창 · 원격에 올리는 블록(되돌리려면 PR을 닫으면 된다)
$AllOk = $ApplyOk -and $AuditOk -and $BaselineOk -and $RatchetOk
"ALL_OK=$AllOk"
if ($AllOk) { git -C $Wt add constitution metrics/coding_constitution_audit_baseline.json; git -C $Wt commit -m "docs(constitution): A0003 채택 — 원본 등록부 실제 경로 정정 + 이식 2단계"; $CommitExit = $LASTEXITCODE; "COMMIT_EXIT=$CommitExit"; if ($CommitExit -eq 0) { git -C $Wt push -u origin $Br; "PUSH_EXIT=$LASTEXITCODE" } } else { "WRITE_REFUSED=True — APPLY=$ApplyOk AUDIT=$AuditOk BASELINE=$BaselineOk RATCHET=$RatchetOk · 모두 True여야 커밋합니다" }
"PUSHED_HEAD=" + (git -C $Wt log -1 --oneline)
"REMOTE_HEAD=" + (git -C $Wt rev-parse --short "origin/$Br")
"BRANCH=$Br"
```

**확인**: `ALL_OK=True` · `COMMIT_EXIT=0` · `PUSH_EXIT=0` · `PUSHED_HEAD=`의 해시와 `REMOTE_HEAD=`의 해시가 같다.

**세션에 전달**: A-1~A-5의 `대문자_이름=값` 줄 전부 + A-4의 심사 표 첫 5줄. 세션이 `kiki/const-a0003-stage2`로 PR을 열고, CI green·머지 후 게이트 `G-const-sources-registry-adopt`를 기록한다. 작업 사본 폴더 `WhyMath-const`는 과제 B에서 다시 만들므로 그대로 둬도 된다.

---

## 2. 과제 B — A0002 채택 (선택 · 결정 게이트)

### 사전 브리핑

1. **과제 명칭**: 코딩 헌법 개정 A0002 채택 — 파트 II~VII 규칙의 근거 조문 5개(제7조의2~5·제8조의2) 신설과 규칙 81건(R5~R29) 병합.
2. **목적**: 현행 헌법(v1.0)은 6축 가운데 ①흐름·②진실과 학생 보호·AI 권한만 조문으로 다룬다. A0002는 ③경계·④변경·⑤확신·⑥회복과 교육적 타당성의 조문을 만들고, 표준북 파트 II~VII의 규칙 81건을 등록부에 넣는다. **채택해도 지금 당장 차단되는 것은 없다** — 81건 중 80건은 3단계 이상 규칙이라 2단계에서는 "예정"으로만 보이고, 나머지 1건(R8-04)은 문서 수준(L2)이라 등록만 확인한다(가상 사본 실측: 채택 후 단계 2 심사 104항목·차단 0건). 대신 3단계 미리보기에서 차단 51건이 보이게 되고, 그 목록이 후속 태스크 CONST-03~08의 할 일 목록이 된다. 채택하지 않으면 그 목록은 문서(대조표)로만 존재한다.
3. **구체적 절차**: B-1 준비(과제 A와 같되 새 브랜치 `kiki/const-a0002`, A0003이 main에 있는지 확인) → B-2 미리보기(헌법 본문 변경 차이와 초안을 메모장으로 연다) → B-3a 동의 입력 → B-3b 반영(헌법 본문·개정 기록·규칙 병합) → B-4 심사·래칫 → B-5 커밋·push. 소요 약 10분.
4. **성공 기준**: `READY=True` → `PREVIEW_OK=True` → `APPLY_OK=True` · `RULES_COUNT=95` → `AUDIT_OK=True` · `RATCHET_OK=True` → `COMMIT_EXIT=0` · `PUSH_EXIT=0`. 대처 1개: `HAS_A0003_ON_MAIN=False`면 과제 A의 PR이 아직 머지 전이다 — 머지 후 B-1부터.
5. **실행 환경**: 과제 A와 같다(Phaiakes9 · Windows PowerShell · 선행 조건: 과제 A의 PR 머지).
6. **창 구분**: **새 창(창②)** 에서 시작한다. 과제 A의 창①을 그대로 쓰면 A에서 True가 된 변수(`$ApplyOk` 등)가 남아 B의 가드를 거짓으로 통과시킬 수 있다 — B-1이 변수를 초기화하지만, 창을 새로 여는 것이 가장 확실하다.

초안의 채택 체크리스트대로 **조문 문구는 Kiki님이 고쳐도 된다**. 고치려면 B-2에서 열리는 메모장의 `CONSTITUTION_v1.1_A0002_proposed.md`(헌법 본문 제안본)나 `rules_additions_v1.1.yaml`(규칙 81건)을 수정·저장한 뒤 B-2를 다시 붙여넣는다. 단 제안본은 **기존 조문을 그대로 둔 채 덧붙이기만** 해야 한다 — 기존 문구를 바꾸면 도우미가 거부한다(기존 조문 변경은 별도 개정으로 한다).

### [B-1] 준비

```powershell
# [창② B-1 준비] Windows PowerShell — Phaiakes9 · 새 창
cd C:\Users\kiki\Desktop\__AI\WhyMath
$ApplyOk = $false; $AuditOk = $false; $RatchetOk = $false; $PreviewOk = $false; $Answer = ""
git fetch origin main
git cat-file -e origin/main:scripts/constitution/adopt_amendment.py
$MainHasTools = ($LASTEXITCODE -eq 0)
"MAIN_HAS_TOOLS=$MainHasTools"
$HasA0003 = [bool]((git ls-tree --name-only origin/main constitution/amendments/) -match "A0003_")
"HAS_A0003_ON_MAIN=$HasA0003"
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-const"
$Br = "kiki/const-a0002"
if (Test-Path $Wt) { git worktree remove --force $Wt; git worktree prune; "OLD_WORKTREE_REMOVED=" + (-not (Test-Path $Wt)) }
if ($MainHasTools -and $HasA0003) { git worktree add -B $Br $Wt origin/main } else { "WORKTREE_SKIPPED=True — MAIN_HAS_TOOLS=$MainHasTools HAS_A0003_ON_MAIN=$HasA0003 · 과제 A의 PR이 머지된 뒤 다시 붙여넣으세요." }
"WORKTREE_HEAD=" + (git -C $Wt log -1 --oneline)
$BaseOk = ((git -C $Wt rev-parse HEAD) -eq (git rev-parse origin/main))
"BASE_MATCHES_MAIN=$BaseOk"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$PyOk = Test-Path $Py
"PY_OK=$PyOk"
$Ready = $MainHasTools -and $HasA0003 -and $BaseOk -and $PyOk
"READY=$Ready"
```

**확인**: `HAS_A0003_ON_MAIN=True` · `BASE_MATCHES_MAIN=True` · `PY_OK=True` · `READY=True`.

### [B-2] 미리보기 — 아무것도 쓰지 않는다

```powershell
# [창② B-2 미리보기] Windows PowerShell — 같은 창 · 읽기 전용
& $Py "$Wt\scripts\constitution\adopt_amendment.py" A0002
$PreviewOk = ($LASTEXITCODE -eq 0)
"PREVIEW_OK=$PreviewOk"
git -C $Wt diff --no-index --stat constitution/CONSTITUTION.md docs/constitution_proposals/CONSTITUTION_v1.1_A0002_proposed.md
notepad "$Wt\docs\constitution_proposals\CONSTITUTION_v1.1_A0002_proposed.md"
notepad "$Wt\docs\constitution_proposals\A0002_parts_II-VII_rules_draft.md"
```

**확인**: `미리보기: 규칙 14개 → 95개` · `ADOPT_RESULT=preview` · `PREVIEW_OK=True`. `diff --stat` 줄은 `28 insertions(+), 1 deletion(-)` 근처다(삭제 1줄은 머리말의 판 표기 `v1.0 (제정)` → `v1.1`).

### [B-3a] 동의 입력 — 이 한 줄만 붙여넣는다

```powershell
# [창② B-3a 동의] Windows PowerShell — 같은 창 · 이 블록은 한 줄뿐이며 입력을 기다린다
$Answer = Read-Host "A0002를 채택하려면 ADOPT 를 입력하고 Enter"
```

### [B-3b] 반영

```powershell
# [창② B-3b 반영] Windows PowerShell — 같은 창 · constitution/ 을 바꾸는 블록
$Consent = ($Answer -ceq "ADOPT")
"READY=$Ready · PREVIEW_OK=$PreviewOk · CONSENT=$Consent"
if ($Ready -and $PreviewOk -and $Consent) { & $Py "$Wt\scripts\constitution\adopt_amendment.py" A0002 --apply; $ApplyOk = ($LASTEXITCODE -eq 0); "APPLY_OK=$ApplyOk" } else { $ApplyOk = $false; "WRITE_REFUSED=True — READY=$Ready PREVIEW_OK=$PreviewOk CONSENT=$Consent · 셋 다 True여야 반영합니다" }
git -C $Wt status --short
```

**확인**: `✅ 반영 완료 (백업: rules.yaml.bak)` · `RULES_COUNT=95` · `STAGE_NOW=2` · `ADOPT_RESULT=applied` · `APPLY_OK=True`. 백업 `rules.yaml.bak`은 작업 사본 최상위에 남는데 git이 무시하도록 설정돼 있어 커밋되지 않는다.

### [B-4] 심사 + 래칫

```powershell
# [창② B-4 심사] Windows PowerShell — 같은 창 · 읽기 전용(기준선은 그대로)
if ($ApplyOk) { & $Py "$Wt\scripts\constitution\audit.py"; $AuditOk = ($LASTEXITCODE -eq 0); "AUDIT_OK=$AuditOk"; & $Py "$Wt\scripts\constitution\audit_ratchet.py"; $RatchetOk = ($LASTEXITCODE -eq 0); "RATCHET_OK=$RatchetOk" } else { "AUDIT_SKIPPED=True — APPLY_OK=$ApplyOk" }
& $Py "$Wt\scripts\constitution\audit.py" --no-run --stage 3
"STAGE3_PREVIEW_EXIT=$LASTEXITCODE"
```

**확인**: 첫 심사 표 첫머리 `심사 항목 104개 · 차단 사유 0건` · `AUDIT_OK=True` · `RATCHET_OK=True`. 마지막 3단계 미리보기는 표 첫머리가 `(미리보기 --stage 3)` · `차단 사유 51건` 근처이고 `STAGE3_PREVIEW_EXIT=1`이다 — **실패가 아니라 다음 단계의 할 일 목록**이다(세션이 CONST-03~08에 배분한다). 파이썬 출력을 `| Select-Object` 같은 파이프로 넘기지 않는 이유: PowerShell이 그 출력을 cp949로 다시 해독해 한글이 깨진다.

### [B-5] 커밋과 push

```powershell
# [창② B-5 커밋·push] Windows PowerShell — 같은 창 · 원격에 올리는 블록
$AllOk = $ApplyOk -and $AuditOk -and $RatchetOk
"ALL_OK=$AllOk"
if ($AllOk) { git -C $Wt add constitution; git -C $Wt commit -m "docs(constitution): A0002 채택 — 파트 II~VII 규칙 근거 조문 신설"; $CommitExit = $LASTEXITCODE; "COMMIT_EXIT=$CommitExit"; if ($CommitExit -eq 0) { git -C $Wt push -u origin $Br; "PUSH_EXIT=$LASTEXITCODE" } } else { "WRITE_REFUSED=True — APPLY=$ApplyOk AUDIT=$AuditOk RATCHET=$RatchetOk · 모두 True여야 커밋합니다" }
"PUSHED_HEAD=" + (git -C $Wt log -1 --oneline)
"REMOTE_HEAD=" + (git -C $Wt rev-parse --short "origin/$Br")
"BRANCH=$Br"
```

**세션에 전달**: B-1~B-5의 `대문자_이름=값` 줄 전부 + B-4 3단계 미리보기 표의 첫머리 3줄. 채택하지 않기로 했으면 "A0002 보류"라고만 알려 주면 세션이 게이트를 보류(waive가 아니라 재확인 지점 기록)로 처리한다.

---

## 3. 과제 C — 헌법 가드가 이 PC에서 실제로 막는지 확인

### 사전 브리핑

1. **과제 명칭**: 헌법 보호 가드 Windows 실동작 확인(읽기 전용).
2. **목적**: 가드(`.claude/hooks/guard_constitution.py`)는 Claude Code가 파일을 고치기 직전에 호출하는 훅이다. 이식 세션은 Linux 클라우드에서 만들고 검증했으므로, **Kiki님 PC(Windows·한국어 cp949 콘솔)에서도 막는지**는 아직 증명되지 않았다. 이식 중 실제로 Windows 전용 결함 2건을 찾아 고쳤다 — 한글·`—`가 섞인 명령에서 입력 해독이 실패해 **통과로 새던 것**, 자가시험이 환경변수를 비워 Windows에서 파이썬이 시작하지 못하던 것. 이 과제는 고친 결과를 이 PC에서 확인한다.
3. **구체적 절차**: 임시 폴더에 main 기준 작업 사본을 만들고(약 20초) → 가드 자가시험 44건을 가상환경 파이썬으로 실행(약 10~30초) → 훅과 같은 방식으로 `python3`에 요청을 넣어 차단(2)·통과(0)를 각각 확인한다(약 5초).
4. **성공 기준**: `SELFTEST_EXIT=0`(출력 끝 `✅ 전건 일치`) · `PYTHON3_FOUND=True` · `HOOK_BLOCK_EXIT=2` · `HOOK_ALLOW_EXIT=0`. `PYTHON3_FOUND=False`이거나 `HOOK_BLOCK_EXIT`가 2가 아니면 **이 PC의 Claude Code에서는 가드가 꺼져 있는 것과 같다** — 저장소의 다른 훅들도 모두 `python3`로 호출되므로 같은 문제다. 그 값을 세션에 전달하면 훅 호출 방식을 고치는 태스크로 처리한다.
5. **실행 환경**: Phaiakes9 · Windows PowerShell · 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath` · 선행 조건: CONST-02 PR 머지.
6. **창 구분**: **새 창(창③)**. 읽기 전용이라 이후 그 창을 계속 써도 된다.

```powershell
# [창③ C 가드 확인] Windows PowerShell — Phaiakes9 · 새 창 · 읽기 전용
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Chk = Join-Path $env:TEMP "whymath-const-guardcheck"
if (Test-Path $Chk) { git worktree remove --force $Chk; git worktree prune }
git worktree add --detach $Chk origin/main
"CHECK_HEAD=" + (git -C $Chk log -1 --oneline)
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
& $Py "$Chk\scripts\constitution\selftest_guard.py"
"SELFTEST_EXIT=$LASTEXITCODE"
$Py3 = Get-Command python3 -ErrorAction SilentlyContinue
"PYTHON3_FOUND=" + [bool]$Py3
"PYTHON3_PATH=" + $Py3.Source
$env:CLAUDE_PROJECT_DIR = $Chk
$env:CLAUDE_GUARD_LOG_DIR = Join-Path $env:TEMP "whymath-const-guardlog"
$Block = @{ tool_name = "Edit"; tool_input = @{ file_path = "constitution/STAGE" }; cwd = $Chk } | ConvertTo-Json -Compress
$Block | python3 "$Chk\.claude\hooks\guard_constitution.py"
"HOOK_BLOCK_EXIT=$LASTEXITCODE"
$Allow = @{ tool_name = "Edit"; tool_input = @{ file_path = "docs/x.md" }; cwd = $Chk } | ConvertTo-Json -Compress
$Allow | python3 "$Chk\.claude\hooks\guard_constitution.py"
"HOOK_ALLOW_EXIT=$LASTEXITCODE"
```

**확인**: `SELFTEST_EXIT=0` · `PYTHON3_FOUND=True` · `HOOK_BLOCK_EXIT=2`(바로 위에 `⛔ 코딩 헌법 제9조 ①…` 안내가 찍힌다) · `HOOK_ALLOW_EXIT=0`. `PYTHON3_PATH`가 `…\WindowsApps\python3.exe`면 Microsoft Store 바로가기일 수 있다 — 그 경우에도 `HOOK_BLOCK_EXIT=2`면 동작하는 것이고, 아니면 값을 그대로 전달한다.

---

## 4. 과제 D — 260927 통합정밀진단 S00~S10 (사람 축 검증)

### 사전 브리핑

1. **과제 명칭**: 260927 EOS 통합 정밀 진단 11단계(S00~S10) 진행.
2. **목적**: 이식의 **기계 축 검증**(CI의 위헌 심사 래칫·파이프라인 검사·가드 테스트)은 "규칙이 배선돼 있는가"를 본다. 그러나 "Phase 0~2 결과물이 헌법·코딩규칙·12/31 계획에 비춰 실제로 건전한가"는 기계가 대신할 수 없는 판정이 섞여 있다(헌법 제9조 ③: AI는 사람의 검토 게이트에서 판정을 대신 확정하지 않는다). 그 **사람 축**이 Kiki님이 준 진단 묶음이다. 이식 세션은 그중 기계로 돌릴 수 있는 부분(진단 도구 7종)을 저장소에 들여와 기준선을 미리 쟀다 — `docs/reviews/coding_diagnosis_baseline_2026-09-27.md`(BL-001~BL-018). S03 단계는 이 기준선과 비교하면 된다.
3. **구체적 절차**: 묶음의 `README_시작하기.md` 순서 그대로다(S00 → S01 → S02 → S03 → S04~S07 병렬 가능 → S08 → S09 → S10). 이 런북은 아래 블록으로 묶음이 어디 있는지 찾아 주고, 저장소 쪽 연결점 3가지만 덧붙인다: ①진단 도구는 저장소 사본 `scripts/constitution/diag/`와 일괄 러너 `scripts/constitution/run_baseline.py`로도 돌릴 수 있다 ②진단 기준의 헌법은 묶음 안 `기준/헌법/`의 사본(v1.0·초안)보다 **저장소의 `constitution/`이 우선**이다(과제 A·B를 먼저 했다면 묶음 사본은 옛 판이다) ③진단 중 Claude Code가 `constitution/`을 고치려 하면 가드가 막는다 — 진단은 읽기 전용이므로 막히는 것이 정상이다.
4. **성공 기준**: 묶음의 결과 폴더에 `S10` 통합진단서가 생긴다. 그 파일을 세션에 전달하면 세션이 게이트 `G-const-diagnosis-s00-s10-run`을 기록하고, 진단서의 작업 카드를 백로그 태스크로 옮긴다.
5. **실행 환경**: Phaiakes9 · Claude Code(코드 저장소 폴더에서 실행 + 계획 폴더를 `/add-dir`로 추가) · 예상 합계 9~14시간(하루 2~3단계씩 4~5일).
6. **창 구분**: 아래 찾기 블록은 아무 PowerShell 창에서나 된다(읽기 전용). 진단 자체는 Claude Code 창에서 단계마다 `/clear` 후 새로 시작한다.

```powershell
# [아무 창 D 찾기] Windows PowerShell — Phaiakes9 · 읽기 전용
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Pack = "C:\Users\kiki\Desktop\__AI\mathmatic\System\작업_ToEos\260927_통합정밀진단"
"PACK_AT_EXPECTED_PATH=" + (Test-Path (Join-Path $Pack "prompts\S00_준비_기준선.md"))
Get-ChildItem C:\Users\kiki\Desktop\__AI -Recurse -Filter "S00_준비_기준선.md" -ErrorAction SilentlyContinue | Select-Object -First 3 -ExpandProperty FullName
"REPO_HEAD=" + (git log -1 --oneline)
"REPO_DIRTY_FILES=" + (git status --porcelain --untracked-files=no | Measure-Object).Count
```

**확인**: `PACK_AT_EXPECTED_PATH=True`, 또는 그 아래 줄에 `…\prompts\S00_준비_기준선.md` 경로가 하나 이상 보인다(묶음이 다른 곳에 풀려 있다는 뜻 — 그 경로를 쓴다). 둘 다 없으면 받은 zip(`260927_EOS 통합정밀진단.zip`)을 README 2-1의 경로에 먼저 푼다. `REPO_DIRTY_FILES`가 0이 아니면 묶음 README 2-2대로 진단 기준점을 고정하기 위해 먼저 커밋하거나, 진단을 main 기준 별도 작업 사본에서 돌린다(여러 세션이 쓰는 메인 클론이면 후자를 권한다).

---

## 5. 이 런북이 답하지 못하는 것 (정직 고지)

- **Claude Code 런타임이 이 PC에서 훅을 실제로 호출하는지**는 과제 C로도 증명되지 않는다. C는 훅과 같은 방식(표준 입력 JSON → 종료 코드)으로 가드를 직접 실행할 뿐이다. Claude Code가 Windows에서 훅 명령을 어떤 셸(PowerShell·Git Bash)로 돌리는지, 그 셸에서 `python3`가 같은 것으로 풀리는지는 런타임 밖이다. 가드는 차단할 때마다 `.claude/logs/constitution_guard.jsonl`에 한 줄을 남기므로, 실사용 중 그 파일이 생기는지가 사후 증거가 된다.
- **A0003 정정 경로의 옳고 그름**은 도우미가 판정하지 않는다. 도우미는 "초안대로 정확히 반영됐는가"만 보장한다. 경로가 정본인지는 초안의 근거 표(1차 조사 + 독립 재검증)와 Kiki님의 읽기가 판정한다.
- **운영 DB 스탬프**(`d6e7f8a9b0c1`)와 코드 기대 스키마(`8c19e8a611e4`)는 정정안 작성 시점 값이다. 이후 마이그레이션이 추가되면 등록부의 판 표기가 낡는다 — 그것을 자동으로 잡는 장치는 아직 없다(후속 CONST-03 범위).
