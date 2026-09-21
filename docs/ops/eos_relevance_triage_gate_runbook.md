# 런북 — `G-eos-verification-relevance-triage` clear

> **대상 게이트**: `G-eos-verification-relevance-triage` (kind=decision · assignee=kiki · 2026-08-31 등재)
> **작성**: 2026-09-01 · main `47804941` 실측 기준
> **입력 자료**: `docs/reviews/eos_verification_relevance_triage_2026-08-31.md`(판정 **제안**본 — 확정 아님)
>
> ## ⚠️ 이 런북의 존재 이유 — 순서가 틀리면 CI가 통째로 멈춘다
>
> `HARN-55`(#955) 착지로 이 게이트는 **그랜드파더 만료의 기계 트리거**가 됐다. clear되는 순간
> `eos_priority` 미지정 비종결 태스크가 `backlog.py validate` 위반이 되고, 그 명령은
> `ci.yml`의 **`harness-integrity` 잡이 그대로 실행**한다(`ci.yml:1132`).
>
> **실측(2026-09-01 시뮬레이션)** — 백필 없이 게이트만 clear했을 때:
>
> ```
> ❌ 무결성 위반 1건:
>   · eos_priority 미지정 190건 — 그랜드파더가 만료됐다: …
> EXIT=1
> ```
>
> 즉 **먼저 clear하면 main과 열린 PR 전부가 red**가 된다. 게이트 clear는 **마지막 단계**다.
>
> **되돌릴 수 없다**: `gates`에는 `list|add|clear|waive`만 있고 **un-clear verb가 없다**.
> 대장 손편집은 금지이므로, 조기 clear의 복구 경로는 **해당 커밋 revert 하나뿐**이다.

---

## §1. 지금 무엇이 걸려 있나 (실측)

| 수치 | 값 | 확인 명령 |
|---|---|---|
| 전체 태스크 | 492 | `backlog.py validate` |
| 비종결(todo·blocked·in_progress·review) | 190 | 아래 §5 스크립트 |
| **`eos_priority` 미지정 비종결** | **190** (전건) | 〃 |
| 판정표가 커버하는 분 | **171** | 〃 |
| 판정표 미수록 신규 등재분 | **19** | 〃 |

미분류 190건의 분포: `S3` 81 · `S4` 88 · E축 15 · `S1` 1 · `S5` 5 —
트랙별 `math-completion` 94 · `infra-debt` 82 · `subject-expansion` 14.

### 판정표(제안본)의 상태

기계 추출 결과 **181행**(R 66 · N 103 · ? 12). 문서 §0의 "182건(R 66·N 103·? 13)"과 1건
차이가 나는 이유는 `CUR-11`이 그 사이 완료돼 행이 `~~**?**~~ **판정 불요**`로 바뀌었기
때문이다 — 181 + CUR-11 = 182로 정합한다.

> ⚠️ **추출 함정 (이 런북을 쓰며 실제로 걸렸다)**: 판정 셀은 R·?만 볼드(`**R**`)이고
> **N은 평문(`N`)**이다. 볼드를 요구하는 정규식은 **N 103건을 통째로 놓치면서도 조용히
> 성공한다**(78건만 잡고 exit 0). §5의 스크립트는 볼드 마커를 선택적으로 둔다. 다른 도구로
> 다시 추출한다면 **분포가 R 66 · N 103 · ? 12로 나오는지 먼저 확인**하라 — 개수 대조가
> 이 추출의 유일한 변별력이다.

판정표에 있던 10건은 그 사이 완료돼 모집단에서 빠졌다(`CUR-09`·`CUR-12`·`EOS-28`·`EOS-58`·
`HARN-24`·`HARN-30`·`HARN-32`·`HARN-38`·`S1-16`·`SEC-28`). **171 + 19 = 190**으로 맞는다.

---

## §2. Kiki가 결정할 것 — 4건 (이것만이 사람 소유다)

나머지는 전부 기계 작업이며 세션이 수행한다. **에이전트가 사람 게이트를 clear한 것이
준수 감사 A3(심각도 높음)** 이므로 최종 clear는 반드시 Kiki 본인이 실행한다.

### 결정 ① — 판정표 R/N/? 확정

`docs/reviews/eos_verification_relevance_triage_2026-08-31.md` §2를 검토하고 이동시킬 행을
지정한다. 문서 §4-1이 **가장 크게 갈릴 지점**을 스스로 지목했다:

> R 66건 중 "하네스 전제"·"회수" 축은 12월 검증에 *직접* 기여하지 않는다 — 작업의
> **보존율**에 기여한다. Kiki가 이 축을 R로 볼지 N으로 볼지가 이 표에서 가장 크게 갈릴 수 있다.

전건 승인이면 "판정표 그대로"라고만 답하면 된다.

### 결정 ② — R/N → P0~P3 매핑 규칙 (**이 런북의 핵심 결정**)

판정표는 **R/N/? 3값**이고 `eos_priority`는 **P0~P3 4값**이다. 1:1이 아니므로 규칙이 필요하다.

**세션 제안 (기본안)**:

| 판정 | 등급 | 근거 |
|---|---|---|
| R + G1~G5 **차단 조건 자체** (판정표 `축`이 게이트 코드) | **P0** | 없으면 12월 검증이 성립하지 않는다 |
| R + KPI 산출 경로·불변 계약·앵커 자산 | **P1** | 품질을 크게 높이나 우회 가능 |
| R + 하네스 전제·회수 축 | **P1** | 직접 기여가 아니라 보존율 — 결정 ①과 연동 |
| N | **P2** | 2027 Q1~Q2 (선언 §0-2 — 폐기 아님) |
| N 중 E축 타과목·장기 플랫폼 | **P3** | 장기 연구·플랫폼 |
| ? | **개별 판정** (결정 ④) | 성격이 서로 달라 한 덩어리로 처리 금지(문서 §4-2) |

> **예산 초과가 예상된다 — 그리고 그것은 우회가 아니라 보고 사항이다.** R 66건 중 P0가
> 몇이 될지에 따라 `policy.eos_p0_budget`(50)을 넘을 수 있다. `amend`는 **의도적으로 예산을
> 강제하지 않는다** — 여기서 막으면 사람이 등급을 낮춰 적어 예산을 맞추게 되기 때문이다
> (측정의 자기기만). 초과하면 그 수치를 그대로 보고하고, 예산을 올릴지 P0를 줄일지는
> 별도 결정으로 처리한다.

### 결정 ③ — 판정표 미수록 신규 19건

판정표 작성(8/31) 이후 등재된 것들이다. 세션이 각 태스크의 `title`·`notes`를 근거로 **제안
등급을 붙여 표로 제출**하고, Kiki는 이견 있는 행만 지적한다.

```
ADMIN-12  CUR-19  EOS-62  EOS-64  EOS-70  EOS-75  HARN-39  HARN-44  HARN-52
HARN-53   HARN-54 LIC-01  LIC-04  LIC-05  NLP-05  OPS-57   PB-13    PB-14   S4-59
```

### 결정 ④ — `?` 12건 개별 판정

문서 §4-2가 한 덩어리 처리를 금지했다. 성격별로:

| 군 | 태스크 | 성격 |
|---|---|---|
| 법령 | `MGMT-01` `MGMT-02` `OPS-31` `SEC-31` | 변호사 판단 — **기계 대체 금지 항목** |
| 사람 결정 | `REC-07` `S3-01` | Kiki 결정 |
| 본 게이트 대상 | `CUR-17` `CUR-18` | 이 게이트가 판정할 대상 자신 |
| KPI 접점 불확실 | `OPS-48` `OPS-50` `PED-34` | 강도 판단 필요 |

`CUR-12`는 **그 사이 done**이라 판정 대상에서 빠졌다(게이트 제목의 "CUR-11·CUR-12 착수 판정"은
둘 다 완료돼 **소멸**했다 — 아래 §4 참조).

---

## §3. 실행 순서 (이 순서를 바꾸지 말 것)

| 단계 | 조치 | 소유 | 실패 시 |
|---|---|---|---|
| 1 | 결정 ①~④ 회신 | **Kiki** | — |
| 2 | 190건 `amend --eos-priority` 일괄 적용 + PR | claude | CI가 잡는다 |
| 3 | 2의 PR 머지 | claude(`pr`) | — |
| 4 | **미분류 0건 확인** (§5 자가검증) | claude → Kiki에 출력 전달 | 0이 아니면 **4로 되돌아감** |
| 5 | 게이트 clear | **Kiki** | §6 롤백 |
| 6 | clear 후 `validate` green 확인 | Kiki | §6 롤백 |

**4를 건너뛰고 5로 가지 않는다.** 4가 이 런북 전체의 유일한 차단 지점이다.

> ⚠️ **단계 4의 "미분류 0건"은 시점 의존적이다 — 4와 5 사이를 벌리지 말 것.**
>
> 병렬 세션이 언제든 새 태스크를 main에 착지시킨다. 특히 **`HARN-55` 머지 이전에 분기한
> 브랜치**는 구버전 CLI를 들고 있어 `--eos-priority` 요구를 받지 않으며, 그 세션이 만든
> 태스크 파일에는 **`eos_priority` 필드 자체가 없다**. `add` 게이트의 구멍이 아니라
> **브랜치 시차**이고, 인플라이트 브랜치가 전부 리베이스될 때까지 계속 발생한다.
>
> 실측(2026-09-01): 단계 4에서 0건을 확인한 뒤 clear 직전에 재확인했더니 `EOS-79`가
> 미분류로 들어와 있었다(PR #958). 그대로 clear했다면 `validate`가 red가 되고
> `harness-integrity`가 main과 열린 PR 전부를 막았을 것이다.
>
> **그래서 5단계 직전에 4를 다시 돌린다** — §6-2의 `validate`가 그 역할이고, 그것이
> green일 때만 §6-3으로 간다. 만약 clear 후에 red가 나면 당황할 일이 아니다:
> 도착한 태스크에 `amend --eos-priority`를 붙이면 즉시 복구된다(revert 불요).

---

## §4. 게이트 제목의 조건 ③은 이미 소멸했다

게이트 제목은 clear 조건을 3개로 적었다:

> ①잔여 todo 151건(S3 68·S4 83)을 '12월 검증 관여/비관여'로 분류 ②비관여분 이월 표시
> ③**CUR-11·CUR-12 착수 판정**

**조건 ③은 대상이 없다** — `CUR-11`(PR #920)·`CUR-12` 모두 **done**이다(실측).
**조건 ①의 수치도 낡았다** — 151건(8/31)이 아니라 현재 **190건**이다.

clear evidence에 이 두 가지를 명시해야 한다. 게이트 제목을 고치는 것보다 evidence에 적는 편이
낫다 — 제목을 고치면 등재 시점의 판단 근거가 사라진다.

> `gates`에는 제목 수정 verb가 없다(`HARN-39-gates-title-notes-edit-cli`가 그 공백을 소유한
> 미완 태스크다). 따라서 evidence 기재가 현재 유일한 정정 경로이기도 하다.

---

## §5. 자가검증 스크립트 (단계 4의 차단 지점)

**변별력 확인 완료 (2026-09-01 실측 · 양방향)** — 이 스크립트는 실패 상태에서 실제로 실패한다:

| 상태 | 출력 | EXIT |
|---|---|---|
| 현행(미분류 190) | `미분류 비종결: 190건` + 대상 예 5건 | **1** |
| 전건 백필 시뮬 | `미분류 비종결: 0건` · `{'P0': 55, 'P1': 45, 'P2': 90}` · `P0 55건 / 예산 50건 ⚠ 초과` | **0** |

예산 초과 경고도 같은 시뮬에서 실제로 발화함을 확인했다(P0 55 > 50). 그리고 **백필 완료 +
게이트 clear** 조합에서 `backlog.py validate`가 `green · EXIT=0`으로 나오는 것까지 확인했다
— §6-4의 기대치는 추측이 아니라 실측이다.

```bash
python3 - <<'PY'
import sys, re, pathlib
sys.path.insert(0, 'scripts/harness')
import store
b, _ = store.load_backlog(pathlib.Path('.'))
TERM = {'done', 'cancelled'}
miss = sorted(t.id for t in b.tasks.values()
              if t.status not in TERM and t.eos_priority is None)
from collections import Counter
graded = [t.eos_priority for t in b.tasks.values()
          if t.status not in TERM and t.eos_priority]
print(f"미분류 비종결: {len(miss)}건")
print(f"등급 분포: {dict(sorted(Counter(graded).items()))}")
p0 = sum(1 for g in graded if g == 'P0')
print(f"P0 {p0}건 / 예산 {store.load_policy(pathlib.Path('.'))[0].eos_p0_budget}건"
      + ("  ⚠ 초과 — 보고 대상" if p0 > store.load_policy(pathlib.Path('.'))[0].eos_p0_budget else ""))
if miss:
    print("  예:", ", ".join(miss[:5]))
    sys.exit(1)
PY
echo "EXIT=$?"
```

`EXIT=0` **이어야만** 단계 5로 간다.

---

## §6. Kiki 실행 블록 (단계 5·6)

> ⚠️ 아래는 **단계 4가 `EXIT=0`을 낸 뒤에만** 실행한다. 그 전에 실행하면 CI가 red가 되고
> 되돌리려면 revert 커밋이 필요하다.

### 창 ① — Windows PowerShell (기존 창 사용 가능 · 이후 조작 자유)

**6-1. 최신 대장 받기** — `--eos-priority` CLI와 이 게이트는 최근에야 main에 착지했다.
체크아웃이 낡으면 다음 명령이 "게이트 없음"으로 거부된다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git checkout -B main origin/main
```

**6-1b. UTF-8 강제 (필수 — 건너뛰면 다음 단계가 터진다)**

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

> **실측 사고 (2026-09-01)**: 이 블록 없이 `backlog.py gates list | Select-String ...`을 돌리면
> `UnicodeEncodeError: 'cp949' codec can't encode character '\u23f3'`로 죽는다. 파이프를 걸면
> stdout이 콘솔이 아니라 파이프가 되고, Python이 **로케일 인코딩(한국어 Windows = cp949)** 으로
> 인코딩하는데 CLI 출력의 `⏳`·`—`가 cp949에 없기 때문이다. `--help`도 같은 이유로 죽는다.
>
> 이 저장소는 같은 유형을 이미 두 번 겪었다(2026-07-17 logconfig 기동 실패 · HARN-19 git 출력
> 디코딩). 정본은 `docs/ops/windows_utf8_setup.md` §2·§3이며, 위 3줄은 그 §3.1의 "현재 세션
> 즉시 적용"판이다. 영구 적용은 `setx PYTHONUTF8 1` + `setx PYTHONIOENCODING utf-8`(새 창부터).
>
> 이 환경변수는 **창 단위**다 — 창을 새로 열면 다시 설정해야 한다.

**6-2. 자가검증 — 선행 조건 3종** (실패 상태에서 실제로 실패함을 확인한 검사다)

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
python -m pip --version
python scripts/harness/backlog.py gates list | Select-String "eos-verification-relevance-triage"
python scripts/harness/backlog.py amend --help | Select-String "eos-priority"
python scripts/harness/backlog.py validate
```

> ⚠️ **세 번째 `validate`는 미분류를 보지 못한다 — 그것만으로 clear하지 말 것.**
> `_eos_priority_grandfather_errors()`는 게이트가 `cleared|waived`일 때만 위반을 낸다
> (`scripts/harness/store.py`). 즉 **clear 전에는 미분류가 몇 건이든 `validate`가 green**이다
> (실측 2026-09-01: 미분류 1건을 만들고 게이트 pending 상태에서 `validate` → `green EXIT=0`).
> 성공/실패 양쪽에서 같은 값을 내는 검사는 검증이 아니라 위장이다.
>
> **그래서 clear 직전 차단 지점은 §5의 미분류 카운트 스크립트다.** 아래 6-2b를 반드시 돌린다.

**6-2b. 미분류 0건 확인 — 이것이 clear의 유일한 차단 지점**

§5의 스크립트를 그대로 돌린다(PowerShell 히어독):

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
@'
import sys, pathlib
sys.path.insert(0, "scripts/harness")
import store
b, _ = store.load_backlog(pathlib.Path("."))
TERM = {"done", "cancelled"}
miss = sorted(t.id for t in b.tasks.values()
              if t.status not in TERM and t.eos_priority is None)
print("미분류 비종결:", len(miss), "건")
for t in miss[:10]:
    print("  +", t)
sys.exit(1 if miss else 0)
'@ | python -
Write-Host "EXIT=$LASTEXITCODE"
```

**`EXIT=0` 이어야만 6-3으로 간다.** 0이 아니면 멈추고 출력을 세션에 전달한다 — 도착한
태스크에 `amend --eos-priority`를 붙이면 해소된다.

기대: ① 게이트 행이 **보인다**(안 보이면 체크아웃이 낡은 것 — 6-1 재실행)
② `--eos-priority` 도움말이 **보인다**(안 보이면 HARN-55 미반영)
③ `validate`가 **green**(red면 clear 금지 — 세션에 알린다).

**6-3. 게이트 clear** — evidence는 §4의 두 정정(조건 ③ 소멸·수치 190)을 포함해야 한다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
python scripts/harness/backlog.py gates clear G-eos-verification-relevance-triage --as kiki --evidence "2026-09-__ Kiki 판정. ①관여도 분류: 비종결 190건 전건 eos_priority 부여 완료(판정표 171 + 신규 19). 게이트 제목의 '151건(S3 68·S4 83)'은 8/31 수치이며 현행은 190건. ②이월 표시: N 판정분을 P2/P3로 부여(폐기 아님 — 선언 §6-5). ③CUR-11·CUR-12 착수 판정: 두 태스크 모두 그 사이 done(CUR-11 PR #920) — 판정 대상 소멸. 근거 문서 docs/reviews/eos_verification_relevance_triage_2026-08-31.md(제안본) + 매핑 규칙은 docs/ops/eos_relevance_triage_gate_runbook.md §2 결정②."
```

**6-4. 사후 자가검증 — 이것이 진짜 판정이다**

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
python scripts/harness/backlog.py validate
```

기대: **green**. red가 나오면 그랜드파더 만료가 발효됐는데 백필이 덜 된 것이다 → §7.

**6-5. 커밋 → 브랜치 push (main 직접 push는 거부된다)**

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git add backlog/
git commit -m "gates: G-eos-verification-relevance-triage clear - 관여도 트리아지 확정"
git checkout -b gates/relevance-triage-clear
git push -u origin gates/relevance-triage-clear
```

그 다음 **PR을 연다**(세션에 알리면 세션이 연다). CI green 후 머지한다.

> ⚠️ **`git push origin main`은 거부된다** — 저장소 규칙이 `Changes must be made through
> a pull request`를 강제한다. 실측(2026-09-01):
> `GH013: Repository rule violations found for refs/heads/main`. 게이트 대장도 예외가 아니다.
>
> **이미 main에 커밋한 뒤 거부당했다면**: 위 블록의 `git checkout -b`가 그 커밋을 그대로
> 새 브랜치로 옮긴다(커밋이 브랜치에 붙어 있는 것이 아니라 브랜치가 커밋을 가리킨다).
> 브랜치를 만들고 push한 뒤 **로컬 main만** 되돌린다:
>
> ```powershell
> cd C:\Users\kiki\Desktop\__AI\WhyMath
> git checkout main
> git status --porcelain
> ```
>
> **`git status --porcelain`이 아무것도 출력하지 않을 때만** 다음 줄을 실행한다:
>
> ```powershell
> git reset --hard origin/main
> ```
>
> 무언가 출력되면 **멈추고 그 목록을 세션에 전달한다.** `reset --hard`는 그 변경을
> 무증상으로 지운다 — `checkout -B main origin/main`은 충돌하지 않는 로컬 편집을 그대로
> 끌고 오고, 직전 커밋은 `backlog/`만 스테이징했으므로 **다른 파일의 작업분이 남아 있을 수
> 있다.**
>
> `reset --hard`가 이 자리에서 허용되는 조건은 두 가지가 **모두** 성립할 때뿐이다:
> ①되돌릴 커밋이 이미 새 브랜치에 보존됐다 ②작업 트리가 비어 있음을 방금 눈으로 확인했다.
> ②를 가정하면 §7-1이 금지한 바로 그 형태(2026-08-10 미커밋 소실)가 된다.

---

## §7. 롤백 — clear를 되돌려야 할 때

`gates`에 **un-clear verb가 없다**. 대장 손편집도 금지다. 따라서:

### 7-1. 아직 **커밋 전**이면 (§6-4에서 red가 난 경우가 여기다)

§6-3의 clear는 작업 트리만 바꾼다 — 커밋은 §6-5다. 따라서 이 시점의 되돌리기는
**`backlog/gates.yaml` 한 파일만** 원복하는 것이다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git checkout -- backlog/gates.yaml
git status --short
```

기대: `git status --short`가 **아무것도 출력하지 않는다**(대장이 HEAD와 동일).

> ⚠️ **`git reset --hard HEAD~1`을 쓰지 말 것.** 이 시점의 clear는 커밋되지 않았으므로
> `HEAD~1`은 clear가 아니라 **직전 커밋 — 대개 이 절차가 의존하는 백필 머지분**을 지운다.
> 미커밋 변경과 커밋된 변경을 구분하지 않는 원복이 정확히 2026-08-10 사고의 형태다
> (`git checkout --`가 미커밋 구현분 +59/-6을 무증상으로 소실시켰다).
>
> 여기서 `git checkout -- backlog/gates.yaml`이 안전한 이유는 **되돌릴 대상이 그 파일
> 하나뿐이고 그 파일에 지킬 미커밋 변경이 없기 때문**이다. 다른 파일에 작업분이 있다면
> 경로를 넓히지 말고 그 파일만 지정한다.

### 7-2. 이미 **커밋했으나 푸시 전**이면

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log --oneline -1
git reset --soft HEAD~1
git checkout -- backlog/gates.yaml
git status --short
```

`git log --oneline -1`이 **clear 커밋인지 먼저 눈으로 확인**한다 — 아니면 멈추고 세션에
출력을 전달한다. `--soft`를 쓰는 이유는 `--hard`가 그 커밋 외의 미커밋 작업분까지
같이 지우기 때문이다.

### 7-3. 이미 **푸시했으면** — revert 커밋을 만든다(히스토리 재작성 금지):

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log --oneline -1
git revert --no-edit HEAD
git checkout -b gates/relevance-triage-clear-revert
git push -u origin gates/relevance-triage-clear-revert
```

그 다음 **PR을 열어 머지한다**. `git push origin main`은 여기서도 `GH013`으로 거부된다 —
§6-5와 같은 규칙이며, 되돌리기라고 예외가 되지 않는다.

여기서도 `git log --oneline -1`로 **되돌릴 커밋이 clear 커밋인지 먼저 확인**한다.

revert 후 `validate`가 green으로 돌아오는지 반드시 확인한다 — 돌아오지 않으면 clear 외의
원인이 있다는 뜻이고, 그때는 세션에 출력을 그대로 전달한다.

---

## §8. 한계 (정직한 공백)

1. **판정의 *내용*은 기계가 검사하지 못한다.** §5는 "빈 칸이 없다"만 판정한다. 어떤 태스크를
   P0로 볼지가 옳은가는 사람만 판단하며, 이 런북은 그 판단을 대신하지 않는다.
2. **shallow 클론의 사각** — 원 트리아지 문서 §4-3이 자인한 그대로다. 미머지 브랜치에서 이미
   진행 중인 태스크를 못 본다. N으로 분류한 것 중 타 세션이 완료해 둔 것이 있을 수 있다.
3. **유입은 막히지만 재고만 비운다** — `HARN-55`의 `add` 게이트가 *신규* 태스크의 미분류
   유입은 차단하나(문서 §4-4가 지적한 사각의 해소), 이 런북이 다루는 것은 그 이전 재고다.
4. **트랙 이관(§3 권고)은 이 런북 범위 밖** — 원 문서 §3은 N 판정분을 `eos-deferred` 트랙으로
   옮겨 `next`에서 기계 제외할 것을 권고했다. `amend --track`이 이제 존재하므로 집행 가능하나,
   등급 부여와는 **별개 축**이라 분리한다. 등급은 *무엇이 중요한가*를, 트랙 이관은 *무엇을
   후보에서 뺄 것인가*를 정한다 — 후자는 별도 결정·별도 PR이 맞다.
5. **P0 예산 초과 가능성을 수치로 예측하지 않았다** — R 66건의 P0/P1 분해는 결정 ②·①에
   달려 있어, 실제 값은 단계 2 실행 시 §5가 처음 산출한다.
