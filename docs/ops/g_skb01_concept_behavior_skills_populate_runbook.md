# G-skb01-concept-behavior-skills-populate — `concept.behavior_skills` 채우기 (Kiki 실행 런북)

> 이 문서는 게이트 **`G-skb01-concept-behavior-skills-populate`**(kiki·2026-09-12 등재)의
> 실행 절차를 다룬다. `docs/ops/g_skb01_skill_node_populate_runbook.md`(skill_node 최초 적재)의
> **후속** 런북이다 — 그 게이트는 이미 clear됐다(2026-09-12, `AFTER_COUNT=27`).
>
> **✅ 실행 완료 — 게이트 cleared (2026-09-14 · 판정 기준 main `b810388b`)**
> Kiki가 Phaiakes9 `whymath-pg`(5433)에서 실행했다. 실측: `BEFORE_NONEMPTY=0` →
> `POPULATE_EXIT=0` → `AFTER_NONEMPTY=1198`. CLI 출력
> `concept.behavior_skills 갱신: 1311건 (비어있지 않은 스킬 1198건·대상 1311건)`의 nonempty와
> `AFTER_NONEMPTY`가 일치해 §4 내부 정합성 자가검증을 통과했다.
> **이 문서는 이제 재실행용이 아니라 기록이다** — 같은 형태의 런북을 새로 쓸 사람은 §9를 먼저 읽는다.
>
> 부수 관측 2건(이 게이트 목표와 무관하게 드러남): `atom_node` 대상 행 부재 1311건 ·
> `concept_content` K-12 대상 행 부재 437건 → `SKB-03`·`SKB-04`로 분리 등재.
> 해소율 재측정(SKB-01 acceptance④)은 후속 게이트 `G-skb01-resolution-remeasure`로 승계.
>
> 의존 코드는 SKB-01 PR [#1141](https://github.com/kiki-s-broom/WhyMath/pull/1141)(2026-09-12
> 병합 · 커밋 `c7e21f86cda951208b6815d4e258c04b453654b5`)로 main에 착지해 있었다.
>
> main 실측(2026-09-14 · `git show origin/main:<경로>`로 확인):
> `l1/concept_atom_crosswalk/populate.py`에 `transfer_concept_behavior_skills` 2건(import 33행·
> 호출 107행), `transfer.py`에 `update_concept_behavior_skills`(295행)·
> `transfer_concept_behavior_skills`(367행) 실재.
>
> 따라서 [1단계]의 `HAS_CONCEPT_TRANSFER` 자가검증은 이제 **`True`가 정상**이다. 이 자가검증은
> 변별력을 잃지 않았다 — 의미만 바뀐다: 이전에는 "PR 미병합"을 잡았고, 지금은 "체크아웃이
> `origin/main`에 닿지 않았다"(fetch 실패·낡은 사본·다른 브랜치)를 잡는다. `False`면 그 자리에서
> 멈추고 세션에 알린다.
>
> 아래 명령·플래그·기본값·경로는 `whymath_backend.l1.concept_atom_crosswalk.populate.main()`과
> `transfer.CrosswalkTransferStore.update_concept_behavior_skills()`의 실제 인자 정의에서
> 확인했다(2026-09-12 hermetic 단위테스트 44건 통과로 배선 검증).
>
> **왜 이 게이트가 새로 필요한가**: 이전 skill_node 런북 §8("이 런북이 답하지 못하는 것")이
> 명시했듯, `concept_graph.populate` 재실행으로는 `concept.behavior_skills`를 채울 수
> 없었다 — 코드 경로 자체가 없었다. 이번에 그 코드 경로(`concept_atom_crosswalk.populate`
> CLI에 세 번째 이전 스텝 추가)를 신설했고, 이 런북은 그 신설 스텝을 prod에서 1회 실행한다.

---

## 1. 과제 명칭

`concept.behavior_skills` 채우기 — 이미 `atom_node.behavior_skills`에 채워져 있는 스킬 참조를
런타임 `concept` 테이블(2,683행)에도 같은 매핑으로 전파한다.

## 2. 목적

`EOS-63`(스킬 이벤트 소비 전환) 측정에서 "기록 100%·해소 0%"의 원인 두 가지 중 하나가
`skill_node` 미적재(이미 해소·PR #1108)였고, 나머지 하나가 `concept.behavior_skills`
전량 빈 배열(2,683/2,683)이었다. `atom_node.behavior_skills`는 이미 크로스워크로 정상
채워져 있으므로(S0-2), **같은 매핑을 재사용**해 `concept.behavior_skills`를 채우면 별도
저작·유도 없이 해소된다. 이 런북이 그 실행이다.

이 실행 후에도 `attempt_skill_event_reach_report`의 해소율 재측정(SKB-01 acceptance④)은
**별도 후속 단계**다 — 이 런북의 범위 밖이다(§8 참조).

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 예상 출력 | 소요 |
|---|---|---|---|
| ① 체크아웃 | main으로 detached 이동(지역 브랜치 무변경) | `CROSSWALK_FILE_OK=True` | ~20초 |
| ② 환경 | UTF-8 콘솔 + prod DB URL 주입 + import 확인 + 도달성 CLI | `REACH_EXIT=0` | ~15초 |
| ③ 사전 확인 | `concept` 테이블의 behavior_skills 비어있지 않은 행 수(읽기 전용) | `BEFORE_NONEMPTY=0` | ~5초 |
| ④ 적재 | `concept_atom_crosswalk.populate` 실행(atom_node·concept·concept_content 세 이전) | `POPULATE_EXIT=0` | ~15초 |
| ⑤ 사후 확인 | 적재 후 비어있지 않은 행 수 재확인(읽기 전용) | `AFTER_NONEMPTY>0` | ~5초 |

**쓰기는 ④에서만 일어난다.** 세 이전 모두 UPDATE(멱등)이므로 재실행해도 안전하다 — 대상
행이 없는 신규 행을 만들지 않고, 값이 같으면 재실행해도 결과가 바뀌지 않는다.

## 4. 성공 기준

`BEFORE_NONEMPTY=0`이고 `AFTER_NONEMPTY`가 0보다 크면 성공이다(정확한 값은 크로스워크
커버리지에 달려 있어 미리 못박지 않는다 — CLI 자신이 출력하는 "비어있지 않은 스킬 N건"과
`AFTER_NONEMPTY`가 **같은 값**이어야 한다는 것이 내부 정합성 자가검증이다).

화면에 출력되는 `BEFORE_NONEMPTY=` · `POPULATE_EXIT=` · CLI의 `concept.behavior_skills 갱신:` 줄 ·
`AFTER_NONEMPTY=` 네 가지와 마지막 `git log` 줄을 **그대로 복사해 세션에 전달**한다.

### 실패 대처

| 증상 | 뜻 | 대처 |
|---|---|---|
| `REACH_EXIT=1` | DB에 못 붙는다 | CLI가 출력하는 상태·대책을 그대로 따른다(`/demo-doctor` §W1) |
| `POPULATE_EXIT=2` | 코퍼스 파일을 못 찾음(작업 디렉터리 문제) | ①의 체크아웃이 제대로 됐는지 `git log --oneline -1`로 확인 |
| `concept 대상 행 부재` 경고가 뜸 | `atom_backend_concept` 선적재가 안 된 원자 code가 있음 | 화면에 나온 code 목록을 그대로 세션에 전달(강제 조치 금지) |
| `atom_node 대상 행 부재` 경고가 뜸 | 이전에 없던 상태 변화 — 예상 밖 | 화면 전체를 세션에 전달 |
| 그 외 예외 | 화면에 찍힌 예외 타입명·메시지를 그대로 세션에 전달 | — |

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Docker Desktop 실행 중 · `whymath-pg` 컨테이너(호스트 포트 **5433**) 가동 ·
  `src\backend\.venv` 세팅 완료
- **DB**: prod DB = docker `whymath-pg` (5433). 데모용 55432·타 프로젝트 5432와 혼동 금지.

## 6. 창 구분

**전 단계가 같은 창 하나에서 끝난다.** 서버(uvicorn)를 띄우지 않으므로 점유 창이 없다.
새 PowerShell 창 하나를 열고 아래 블록을 순서대로 붙여넣는다.

---

## 실행 블록

> 아래 블록은 **자리표시자가 하나도 없다**. 그대로 통째로 붙여넣으면 된다.

### [1단계] 체크아웃 — main으로 detached 이동(지역 브랜치 무변경)

```powershell
# [Windows PowerShell · Phaiakes9]
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Dirty = (git status --porcelain --untracked-files=no)
"TRACKED_DIRTY=" + [bool]$Dirty
if (-not $Dirty) {
  $Branch = (git rev-parse --abbrev-ref HEAD)
  "RETURN_TO=$Branch"
  git fetch origin main
  $CrosswalkRel = "src/backend/whymath_backend/l1/concept_atom_crosswalk/populate.py"
  git checkout --detach origin/main
  git log --oneline -1
  "CROSSWALK_FILE_OK=" + (Test-Path (Join-Path (Get-Location) $CrosswalkRel))
  "HAS_CONCEPT_TRANSFER=" + ((Get-Content $CrosswalkRel -Raw) -match "transfer_concept_behavior_skills")
}
```

**자가검증**: `TRACKED_DIRTY=False` · `CROSSWALK_FILE_OK=True` · **`HAS_CONCEPT_TRANSFER=True`**.
- 세 번째 값은 SKB-01 PR #1141 병합(main `c7e21f86`)으로 **이제 `True`가 정상**이다. `False`면
  체크아웃이 그 커밋에 닿지 않았다는 뜻(`git fetch origin main` 실패·낡은 사본·detached 이동
  실패) — 다음 단계로 가지 말고 바로 앞 줄의 `git log --oneline -1` 출력과 함께 세션에 알린다.
- `TRACKED_DIRTY=True`면 블록 전체가 통째로 건너뛰어진다(`if` 가드) — 추적 중인 파일에
  미커밋 변경이 있다는 뜻이므로, 강제로 진행하지 말고 세션에 알린다.

### [2단계] 환경 — UTF-8 + prod DB + 도달성 판정

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = (Resolve-Path "src\backend").Path
$Py = "src\backend\.venv\Scripts\python.exe"
"PY_OK=" + (Test-Path $Py)
& $Py -c "import whymath_backend.l1.concept_atom_crosswalk.populate; print('IMPORT_OK=True')"
"IMPORT_EXIT=$LASTEXITCODE"
& $Py -m whymath_backend.ops.db_host_reachability
"REACH_EXIT=$LASTEXITCODE"
```

**자가검증**: `PY_OK=True`·`IMPORT_OK=True`·**`REACH_EXIT=0`**.

### [3~5단계] 사전 확인 → 적재 → 사후 확인

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
"===== 3. 사전 확인 (읽기 전용) ====="
$Before = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM concept WHERE behavior_skills <> '{}';"
"BEFORE_NONEMPTY=$($Before.Trim())"
"===== 4. 적재 (여기서만 DB에 쓴다) ====="
& $Py -m whymath_backend.l1.concept_atom_crosswalk.populate
"POPULATE_EXIT=$LASTEXITCODE"
"===== 5. 사후 확인 (읽기 전용) ====="
$After = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM concept WHERE behavior_skills <> '{}';"
"AFTER_NONEMPTY=$($After.Trim())"
git log --oneline -1
```

**성공 판정**: `BEFORE_NONEMPTY=0` · `POPULATE_EXIT=0` · `AFTER_NONEMPTY`가 0보다 크고, CLI가
화면에 출력한 `concept.behavior_skills 갱신: ...(비어있지 않은 스킬 N건...)`의 N과 `AFTER_NONEMPTY`가
**일치**한다. 이 다섯 줄(`BEFORE_NONEMPTY=`·`POPULATE_EXIT=`·CLI 출력 3줄·`AFTER_NONEMPTY=`)과
마지막 `git log` 줄을 그대로 복사해 세션에 전달한다.

### 회차 후 원래 브랜치로 복귀

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
if ($Branch -and $Branch -ne "HEAD") { git checkout $Branch } else { git checkout main }
git status --short --branch
```

---

## 7. 게이트 clear 방법

**Kiki가 할 일은 위 결과 줄들을 세션에 전달하는 것까지다.** 대장 조작(`backlog.py gates clear`)은
세션이 가져간다. `--evidence`에는 판정 기준(커밋 해시)이 반드시 들어가야 한다(HARN-68).

## 8. 이 런북이 답하지 못하는 것 (정직 고지)

- **해소율(RESOLUTION) 재측정은 이 런북의 범위가 아니다.** `concept.behavior_skills`가 채워져도
  `attempt_skill_event_reach_report` 재실행(SKB-01 acceptance④)은 별도 단계다 — 채점 attempt가
  실제로 그 개념들을 평가했는지는 이 실행과 무관하다.
- **크로스워크 커버리지 자체는 이 실행으로 넓어지지 않는다** — #419가 저작한 404/437 매핑을
  그대로 전파할 뿐, 33개 미매핑 개념·크로스워크가 안 닿는 원자는 여전히 빈 배열이다.

---

## 9. 이 런북이 실전에서 드러낸 결함 3건 — 다음 런북 작성자에게

2026-09-14 실행은 **네 번의 왕복**을 썼다. 세 번은 Kiki의 조작 실수가 아니라 **런북·안내 블록 자신의
결함**이었다. 같은 형태의 prod 적재 런북(`SKB-03`·`SKB-04`가 곧 필요로 한다)을 쓸 사람은 아래를
그대로 피한다.

### ① 가드가 조용히 건너뛰면 그것은 가드가 아니다

[1단계]는 `if (-not $Dirty) { …체크아웃… }`로 감싸여 있었다. Kiki의 클론에 타 세션의 미커밋 변경
3건이 있어 **블록 전체가 건너뛰어졌고, 화면에는 `TRACKED_DIRTY=True` 한 줄 말고 아무것도 나오지
않았다.** 건너뛴 사실이 출력되지 않으니 다음 단계로 넘어가는 것이 자연스러웠다.

**규칙**: 가드에는 반드시 "건너뛰었다 + 왜 + 무엇을 하라"를 출력하는 반대 가지를 둔다. 침묵하는
`if`는 보호가 아니라 위장이다(CLAUDE.md 「변별력 없는 검증 스텝 금지」의 런북 축).

### ② 블록 간 선행 조건은 자동 가드로 잇지 말고 사람 판정 지점으로 끊는다

[2단계]가 `REACH_EXIT=2`(Docker 미가동)를 냈는데 [3~5단계]가 그대로 실행됐다. 블록마다 앞 단계
결과를 검사하는 코드가 없었기 때문이다. 다행히 DB에 붙지 못해 쓰기는 0건이었다 — **설계가 아니라
운이었다.**

그렇다고 자동 가드를 넣으면 ③의 함정에 빠진다. **답은 블록을 끊고 판정을 사람에게 넘기는 것**이다:
블록 끝에 판정값을 출력하고, 다음 블록 앞에 "이 값이 0인 것을 눈으로 확인한 다음에만 붙여넣으세요"를
한 줄로 적는다. 붙여넣기 단위가 곧 판정 단위가 된다.

### ③ PowerShell 대화형 붙여넣기에서 최상위 `if`/`elseif`/`else` 분기는 깨진다

②를 고치려고 넣은 자동 가드가 바로 실패했다:

> 「실측」 `elseif : 'elseif' 용어가 cmdlet, 함수, 스크립트 파일 또는 실행할 수 있는 프로그램 이름으로 인식되지 않습니다.`

PowerShell 프롬프트는 `if (…) { … }`가 **닫히는 순간 그 문장을 실행**한다. 그래서 다음 줄에 오는
`elseif`·`else`는 이어지는 절이 아니라 **별개의 명령**으로 해석돼 `CommandNotFoundException`이 난다.
이때 `else` 안에 있던 환경 변수 설정·`$Py` 정의가 통째로 실행되지 않고, 뒤 블록은 초기값
(`$false`)을 보고 `SKIP`한다 — 증상이 원인에서 멀다.

**규칙**: Kiki 머신 명령 블록에서 최상위 제어 흐름은 **단일 `if (…) { … }`까지만** 쓴다
(`} else {`처럼 같은 줄에 이어 붙이면 파서가 계속 읽으므로 *한 덩어리 안에서는* 동작한다 — [A] 블록이
그 예다). `elseif` 체인과, 닫힌 뒤 새 줄에서 시작하는 `else`는 쓰지 않는다. 분기가 필요하면 ②처럼
블록을 끊는다.

### ④ (보너스) 공유 클론에서 "체크아웃"보다 "동등성 판정"이 견고하다

Kiki 머신의 클론은 여러 세션이 공유하는 **단일 작업 사본**이라 미커밋 변경이 상시 존재할 수 있다.
`git checkout --detach origin/main`은 그 상태에서 위험하거나(변경을 들고 이동) 가드에 막힌다.

실제로 필요한 것은 "HEAD가 main인가"가 아니라 **"이 CLI가 읽는 코드·코퍼스가 main과 같은가"**뿐이다.
그것을 직접 판정하면 체크아웃 없이 끝난다:

```powershell
# [Windows PowerShell · Phaiakes9] — 체크아웃 대신 동등성 판정
git fetch origin main
git diff --quiet origin/main -- "src/backend/whymath_backend/l1/concept_atom_crosswalk" "data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl" "data/corpus/concept_graph_v1/graph.json" "data/corpus/concept_graph_v1/concepts.jsonl"
"PATHS_MATCH_MAIN=" + ($LASTEXITCODE -eq 0)
```

`git diff`는 작업 트리와 비교하므로 미커밋 변경까지 포함해 판정한다 — 무관한 파일이 더러워도 통과하고,
실행 입력이 다르면 막는다. 변별력이 정확히 필요한 자리에 있다. 판정 기준 해시는
`git rev-parse --short origin/main`으로 함께 남긴다(HARN-68).
