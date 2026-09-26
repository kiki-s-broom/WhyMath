# HARN-176 — main 낡음·미머지 작업 실시간 감시기 켜기 (Kiki 실행)

> 이 PC(Phaiakes9)의 WhyMath 클론이 **main보다 낡았는지**, **머지되지 않은 작업이 어디에
> 얼마나 있는지**를 한 화면에서 보고, 창을 켜 두면 **달라질 때마다 한 줄씩 알려 주는**
> 감시기(`scripts/ops/main_watch.py`)를 켜는 런북이다. 감시기는 **읽기 전용**이다 — pull·
> merge·push·삭제를 대신 하지 않고, 쓰는 것은 `git fetch`(원격 추적 ref 갱신)뿐이다.

## 1. 과제 명칭

main·미머지 실시간 감시기를 전용 폴더에 준비하고, 1회 점검 후 감시 창을 켜 둔다.

## 2. 목적

이 저장소에서 반복된 사고 세 종류를 **일어나는 순간** 보이게 한다.

- **낡은 클론에서 실행** — 2026-07-14, main에 이미 있는 스크립트가 낡은 클론에 없어 런북이
  실패했다. 감시기는 "현재 체크아웃이 origin/main보다 몇 커밋 뒤처졌는가"를 1분마다 잰다.
- **다른 세션이 브랜치를 바꿔 둠** — 2026-08-09, 공유 클론의 브랜치가 다른 세션의 런북으로
  바뀐 것을 모르고 실행했다. 감시기는 체크아웃이 바뀌는 순간 `[주의] 체크아웃 전환` 줄을 낸다.
- **머지 안 된 작업의 고립** — push 안 한 커밋, 체크가 안 도는 PR, PR 없이 방치된 원격 브랜치.
  감시기는 열린 PR의 배송 상태(HARN-30 분류·처방)와 오래된 원격 브랜치(HARN-47 분류)를 함께 본다.

결과는 화면에만 나온다(결과를 파일·DB에 남기지 않는다). 이 절차가 디스크에 쓰는 것은 [A]가
만드는 전용 폴더와 `git fetch`의 원격 추적 ref뿐이다. 판단과 조치는 Kiki가 한다.

## 3. 구체적 절차

블록 3개다. **[A]·[B]는 창 ①, [C]는 새 창 ②**에서 붙여넣는다.

- **[A] 감시기 준비** (30초~1분) — 원격을 받아 온 뒤, 감시기 코드를 **전용 폴더**
  `C:\Users\kiki\Desktop\__AI\WhyMath-watch`에 origin/main 기준으로 둔다(git worktree).
  공유 클론의 브랜치·미커밋 변경은 **하나도 건드리지 않는다** — 그래서 클론이 어느 브랜치에
  있든, 얼마나 낡았든 감시기는 늘 main의 최신 코드로 돈다. 이미 준비돼 있으면 최신으로만 옮긴다.
- **[B] 1회 점검** (10~40초) — 지금 상태를 한 번 전부 보고 종료 코드를 찍는다.
  열린 PR마다 GitHub에 체크 상태를 묻기 때문에 PR 수에 비례해 걸린다(10건이면 약 10~15초).
- **[C] 실시간 감시** (켜 두는 동안 계속) — 첫 화면에 [B]와 같은 보고서를 낸 뒤, **60초마다**
  main·체크아웃을, **5분마다** 열린 PR·원격 브랜치를 다시 본다. 달라진 것만 새 줄로 알리고,
  변화가 없으면 맨 아래 한 줄(`변화 없음 · …`)이 제자리에서 갱신된다.

## 4. 성공 기준

- **[A]**: `WATCHER_ON_MAIN=True`와 `TREE_MATCHES_MAIN=True`가 둘 다 보인다.
  `WATCHER_ON_MAIN=False`면 감시기가 아직 main에 머지되지 않은 것이다 — 머지 후 다시 붙여넣는다.
  `TREE_MATCHES_MAIN=False`면 전용 폴더가 최신으로 안 옮겨진 것이다 — 그 위 줄의 git 출력을 회신한다.
- **[B]**: 보고서 마지막 줄 `[판정] …`과 `CHECK_EXIT=` 줄이 보인다. 값의 뜻:
  - `CHECK_EXIT=0` — 이상 없음(전부 재는 데 성공했고 주의 없음)
  - `CHECK_EXIT=1` — 주의 필요 → `[주의]` 줄과 그 아래 `→` 처방을 읽는다
  - `CHECK_EXIT=2` — **재지 못한 것이 섞여 있다** → `[미측정]` 줄의 사유를 읽는다. "이상 없음"이 아니다
  - `CHECK_EXIT=3` — 사용 오류(경로 등) → 출력 전체를 회신한다

  0·1·2는 모두 **감시기 자체는 정상 동작**했다는 뜻이다. 첫 실행에서 1이 나오는 것은 자연스럽다
  (이 저장소는 대개 주의 필요 PR이 몇 건 있다).
- **[C]**: 첫 보고서 다음에 `감시 시작 — main·체크아웃은 60초마다 …` 줄이 나오고, 1분 뒤부터
  맨 아래 줄이 `[시각] 변화 없음 · main … · 주의 N`으로 갱신된다.
- **실패 시 대처 1개**: `[미측정] 원격 가져오기: 실패`가 계속 나오면 인터넷·GitHub 로그인
  문제다 — 창 ①에서 `git fetch origin`을 직접 쳐 보고 그 오류를 회신한다.

## 5. 실행 환경

- 머신: **Phaiakes9** (= 평소 쓰는 이 PC). 별도 접속 불요.
- 시스템: **Windows PowerShell**
- 작업 디렉터리: `C:\Users\kiki\Desktop\__AI\WhyMath` (감시 대상). 감시기 코드는
  `C:\Users\kiki\Desktop\__AI\WhyMath-watch`(전용 폴더 — [A]가 만든다)에서 돈다.
- 선행 조건: 인터넷 연결 · `git` · WhyMath `.venv`(없으면 시스템 `python`으로 대신한다).
  Docker·DB·서버 **불요**.
- **GitHub 토큰(선택이지만 권장)**: 열린 PR의 체크 상태를 보려면 토큰이 필요하다. `gh`에
  로그인돼 있으면 감시기가 `gh auth token`에서 **자동으로 빌려 쓴다**(값은 화면에 나오지 않고,
  감시기 프로세스가 끝나면 사라진다). 보고서 머리의 `GitHub: … · 토큰: …` 줄로 확인한다.
  토큰이 없으면 `[미측정] 열린 PR: N건 — CI·머지 상태는 못 쟀다`가 나오고 PR 목록만 보인다.
- 비용: GitHub API 호출은 5분마다 약 (열린 PR 수 × 2~3 + PR이 걸린 오래된 원격 브랜치 수 × 2 + 2)회다.
  예: 열린 PR 10건·해당 브랜치 10건이면 5분마다 약 50회 = 시간당 약 600회로, 토큰 한도(시간당
  5,000회)의 약 12%다. 줄이려면 `--slow-interval 600`(10분)을 쓴다. LLM 호출 0.

## 6. 창 구분

- **창 ① (새 PowerShell 창 또는 평소 쓰는 창)**: [A] → [B]를 차례로 붙여넣는다. 둘 다 금방 끝나며
  끝난 뒤에는 이 창을 계속 써도 된다.
- **창 ② (새 PowerShell 창 — 감시 전용)**: [C]만 붙여넣는다. **이 창은 감시기가 점유한다.
  이후 이 창에는 아무 명령도 붙여넣지 않는다.** 이 창에서 `Ctrl+C`는 복사가 아니라 **감시 중단**
  신호다(끝낼 때 쓰면 된다). 화면의 글자를 복사하려면 마우스로 선택한 뒤 오른쪽 클릭한다.

---

## [A] 감시기 준비 (창 ①)

> 전용 폴더를 쓰는 이유: Kiki 클론은 여러 세션이 함께 쓰는 단일 작업 사본이라, 감시기를
> 돌리려고 클론의 브랜치를 옮기면 다른 세션의 실행이 깨진다(2026-09-15 G-skb03 사고 유형).
> `git worktree`는 원래 클론의 브랜치·미커밋 변경을 건드리지 않고 **코드만** 따로 꺼낸다.
> 감시기가 main에 새로 고쳐지면 이 블록을 다시 붙여넣어 최신으로 옮긴다.

```powershell
# 실행 시스템: Windows PowerShell (Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Tree = "C:\Users\kiki\Desktop\__AI\WhyMath-watch"
git fetch --quiet origin
git cat-file -e "origin/main:scripts/ops/main_watch.py" 2>$null
$Ready = ($LASTEXITCODE -eq 0)
"WATCHER_ON_MAIN=$Ready"
if ($Ready) { if (Test-Path $Tree) { git -C $Tree checkout --quiet --detach origin/main } else { git worktree add --detach $Tree origin/main }; $Same = ((git -C $Tree rev-parse HEAD) -eq (git rev-parse origin/main)); "TREE_MATCHES_MAIN=$Same" } else { "TREE_MATCHES_MAIN=건너뜀 — 감시기가 아직 origin/main에 없습니다(PR 머지 전). 머지 후 이 블록을 다시 붙여넣으십시오." }
```

**`WATCHER_ON_MAIN=True`와 `TREE_MATCHES_MAIN=True`를 눈으로 확인한 다음에만 [B]를 붙여넣으십시오.**

## [B] 1회 점검 (창 ①)

```powershell
# 실행 시스템: Windows PowerShell (Phaiakes9) · 창 ① ([A]를 붙여넣은 그 창)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:PYTHONUTF8 = "1"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (Test-Path $Py) { "PY=venv" } else { $Py = "python"; "PY=system" }
$Tree = "C:\Users\kiki\Desktop\__AI\WhyMath-watch"
$Watcher = "$Tree\scripts\ops\main_watch.py"
if (Test-Path $Watcher) { & $Py $Watcher; "CHECK_EXIT=$LASTEXITCODE" } else { "CHECK_EXIT=실행 안 함 — 감시기 코드가 $Tree 에 없습니다. [A]를 먼저 붙여넣으십시오." }
```

## [C] 실시간 감시 (새 창 ② — 감시 전용)

> 이 블록은 **감시기 실행으로 끝난다.** 붙여넣은 뒤에는 이 창에 아무것도 붙여넣지 마십시오.
> 끝낼 때는 이 창에서 `Ctrl+C` — 마지막 줄에 `감시 종료(Ctrl+C)`가 나온다.

```powershell
# 실행 시스템: Windows PowerShell (Phaiakes9) · 창 ② 새 창 — 감시 전용, 이후 이 창에는 아무것도 붙여넣지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:PYTHONUTF8 = "1"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
$Tree = "C:\Users\kiki\Desktop\__AI\WhyMath-watch"
$Watcher = "$Tree\scripts\ops\main_watch.py"
if (Test-Path $Watcher) { & $Py $Watcher --watch } else { "WATCH_NOT_STARTED — 감시기 코드가 $Tree 에 없습니다. 창 ①에서 [A]를 먼저 붙여넣으십시오." }
```

---

## 화면 읽는 법

보고서의 각 줄은 `[상태] 항목: 내용` 모양이다. 상태는 네 가지다.

| 상태 | 뜻 | 할 일 |
|---|---|---|
| `[정상]` | 재는 데 성공했고 문제 없음 | 없음 |
| `[주의]` | 재는 데 성공했고 조치가 필요함 | 바로 아래 `→` 줄의 처방을 읽는다 |
| `[미측정]` | **재지 못함** — 문제 없음이 아니다 | 사유를 읽는다(네트워크·토큰·shallow 등) |
| `[생략]` | 옵션으로 끈 항목 | 없음 |

감시 중(창 ②)에는 달라진 것만 이런 줄로 나온다.

| 줄 | 무엇이 일어났나 | 할 일 |
|---|---|---|
| `[변화] origin/main 전진: 가 → 나 (새 커밋 N개)` | 새 PR이 main에 머지됨. 아래에 커밋 제목이 나온다 | 클론이 main이면 `git pull --ff-only` |
| `[주의] 현재 체크아웃: 정상 → 주의 — main @ … N커밋 뒤처짐` | 이 PC의 main이 낡았다 | 창 ①에서 `git pull --ff-only`(작업 트리 변경이 있으면 먼저 누구 것인지 확인) |
| `[주의] 체크아웃 전환: 가 → 나` | 누군가(다른 창·세션) 브랜치를 바꿨다 | 진행 중인 런북이 있으면 대상 브랜치부터 확인 |
| `[변화] PR #N 머지됨 — origin/main에 착지` | PR이 main에 들어갔다 | 없음 |
| `[주의] PR #N 상태: … → NO_CHECKS` | 체크가 안 돈다(트리거 미발화) | 처방 문구대로 — 빈 커밋·PR 재개폐는 금지 |
| `[주의] 이 PC에만 있는 커밋 …` | push 안 한 커밋이 있다 — 이 PC가 유일한 사본 | push 후 PR, 또는 버릴지 결정 |
| `[주의] 오래된 미머지 브랜치 등장 [고립] …` | PR 없이 방치된 원격 브랜치 | 세션에 "/stray-code" 또는 `backlog.py branches` 점검 요청 |
| `[시각] [미측정] …` | 이번 주기에 재지 못한 것(네트워크·로그인·`감시기 내부 오류`) | 계속되면 그 줄을 그대로 회신 — 감시는 다음 주기에 계속 돈다 |
| `[시각] 변화 없음 · …` | 아무 일 없음(맨 아래 한 줄이 제자리에서 갱신) | 없음 |

「예시」 main이 전진해 이 PC의 main이 낡아진 순간의 감시 창:

> `[14:05:12] [변화] origin/main 전진: 1a2b3c4 → 5d6e7f8 (새 커밋 1개)`
> `           5d6e7f8 feat: 예시 커밋 (#1234)`
> `[14:05:12] [주의] 현재 체크아웃: 정상 → 주의 — main @ 1a2b3c4 — origin/main보다 1커밋 뒤처짐`
>
> (해시·PR 번호는 설명용 예시값이다.)

## 자주 쓰는 옵션

기본값으로 충분하면 건드리지 않는다. 필요할 때만 [B]·[C] 블록의 `& $Py $Watcher` 뒤에 붙인다.

| 옵션 | 효과 |
|---|---|
| `--interval 120` | main 확인 주기를 120초로(최소 10) |
| `--slow-interval 600` | PR·원격 브랜치 확인 주기를 10분으로(최소 60) |
| `--skip prs` | 열린 PR을 보지 않는다(토큰이 없을 때 [미측정]을 없애려면) |
| `--skip branches` | 오래된 원격 브랜치를 보지 않는다 |
| `--no-fetch` | 원격을 새로 받지 않는다 — 30분보다 낡으면 [미측정]으로 알린다 |
| `--stale-days 7` | "오래 머지 안 됨" 기준을 7일로(기본 3일) |
| `--json` | 1회 점검 결과를 JSON으로([B] 전용) |

## 정리 (감시기를 더 쓰지 않을 때만)

감시 창(②)에서 `Ctrl+C`로 끈 뒤, 전용 폴더를 지우려면 창 ①에서 아래를 붙여넣는다.
`git worktree remove`는 그 폴더에 수정이 있으면 **거부**하므로 다른 작업을 지우지 않는다.

```powershell
# 실행 시스템: Windows PowerShell (Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Tree = "C:\Users\kiki\Desktop\__AI\WhyMath-watch"
if (Test-Path $Tree) { git worktree remove $Tree; "TREE_REMOVED=$(-not (Test-Path $Tree))" } else { "TREE_REMOVED=해당 없음 — $Tree 폴더가 이미 없습니다" }
```

## 이 감시기가 하지 않는 것 (한계)

- **고치지 않는다** — pull·merge·push·브랜치 삭제는 처방 문구로만 보인다.
- **다른 PC·세션 컨테이너는 보지 않는다** — 이 클론과 원격(GitHub)만 본다. 세션 컨테이너에만
  있고 push 안 된 커밋은 원격에 없으므로 보이지 않는다.
- **PR 머지 여부는 main 커밋 제목의 `(#번호)`로 판정한다** — 그 표기가 없는 머지는
  "목록에서 사라짐(확인 불가)"으로 나온다.
- 경계: 원격 브랜치 전수 drift·충돌은 `scripts/ops/flow_health.py`, 브랜치 처분 판정은
  `backlog.py branches`, PR 1건의 머지 시점은 `scripts/ops/pr_merge_readiness.py`가 소유한다.
