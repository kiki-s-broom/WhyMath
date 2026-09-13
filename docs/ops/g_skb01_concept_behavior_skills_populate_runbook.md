# G-skb01-concept-behavior-skills-populate — `concept.behavior_skills` 채우기 (Kiki 실행 런북)

> 이 문서는 게이트 **`G-skb01-concept-behavior-skills-populate`**(kiki·2026-09-12 등재)의
> 실행 절차를 다룬다. `docs/ops/g_skb01_skill_node_populate_runbook.md`(skill_node 최초 적재)의
> **후속** 런북이다 — 그 게이트는 이미 clear됐다(2026-09-12, `AFTER_COUNT=27`).
>
> **판정 기준: 이 런북이 의존하는 코드는 아직 main에 없다** — SKB-01 PR(2026-09-12, 세션
> `claude/friendly-hypatia-hlqsqf`)이 병합된 **이후에만** 실행한다. 병합 전에 실행하면
> [1단계]의 `HAS_CONCEPT_TRANSFER` 자가검증이 `False`를 내고 멈추도록 설계했다. 아래
> 명령·플래그·기본값·경로는 `whymath_backend.l1.concept_atom_crosswalk.populate.main()`과
> `transfer.CrosswalkTransferStore.update_concept_behavior_skills()`의 실제 인자 정의에서
> 확인했다(2026-09-12 hermetic 단위테스트 44건 통과로 배선 검증 — PR 머지 후 커밋 해시로
> 게이트 clear 시 갱신).
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
- 세 번째 값이 `False`면 이 런북이 기대하는 코드(SKB-01 PR)가 아직 main에 없다는 뜻 — 다음
  단계로 가지 말고 세션에 알린다.

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
