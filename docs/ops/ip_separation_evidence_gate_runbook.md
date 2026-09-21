# 런북 — `G-eos-ip-separation-evidence` 해소

> **대상 게이트**: `G-eos-ip-separation-evidence` (kind=human · assignee=kiki · 2026-08-30 등재 · remind 14d)
> **작성**: 2026-09-07 · `MGMT-05-ip-separation-evidence-pack`
> **판정 기준**: main `79b0cc4d` (PR #1041 squash 머지 · 2026-09-07)
> 기계 도구·템플릿·이 런북 모두 **main에 있다** — 별도 브랜치 체크아웃 불요.

---

## 1. 과제 명칭

**겸직 IP 귀속 분리 증빙 3종 확보** — ①커밋 신원·시각 기계 증거 생성 ②재직사 자산·데이터
무사용 확인서 작성·서명 ③신설 법인 IP 양도 예정 기록 작성·서명.

## 2. 목적

12/31까지 만드는 산출물 **전체의 귀속**이 이 증빙에 걸려 있다. 투자 실사에서 반드시 나오는
질문("재직 중에 만든 것 아닌가", "회사 자산을 쓰지 않았다는 근거가 있나", "법인으로 옮길
계획은 언제부터였나")에 **그때 가서 답을 만들면 이미 늦다**. 자기확인 문서의 증명력은
작성 시점에 달려 있고, 분쟁 후 소급 작성한 문서는 거의 쓸모가 없기 때문이다.

이 게이트는 **변호사 자문과 무관하게 지금 확보 가능한** 사실 기록만 다룬다. 법적 판단
(업무상저작물·직무발명·겸업금지)은 자문 대상이며 여기서 결론내지 않는다 — 전환 설계서
§6-3이 이 항목만 자문 대기에서 떼어내 게이트로 등재한 이유다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 소유 | 소요 |
|---|---|---|---|
| ① | 브랜치 체크아웃 후 증거 생성기 실행 → `.ip_evidence\`에 리포트 2종 + 원자료 1종 | 기계 | 1~2분 |
| ② | 리포트를 읽고 §4 성공 기준 대조 | Kiki | 5분 |
| ③ | 확인서 템플릿을 복사해 기입·서명 | **Kiki** | 30~40분 |
| ④ | 양도 예정 기록 템플릿을 복사해 기입·서명 | **Kiki** | 15~20분 |
| ⑤ | 3종을 저장소 **밖** 한 폴더에 보관 + 시점 고정(자기 이메일 발송 등) | Kiki | 5분 |
| ⑥ | 게이트 clear | Kiki | 1분 |

③④가 이 과제의 본체다. ①은 그 입력을 만들 뿐이고, 기계가 대신할 수 있는 것은 거기까지다 —
확인서의 서명은 본인의 의사표시라 애초에 대체 대상이 아니다.

**예상 출력(①)** — 2026-09-07 실측 기준(모든 ref 45개 전수):
`STATUS=ok` · `COMMITS=2621` · `FULL=1` · `PERSON_AUTHORED=1132` · `FOREIGN=0` ·
오프셋 분포 `+00:00` 1433 / `+09:00` 1002 / `-04:00` 186 · 업무시간 비율 0.348.
(2026-09-08 Kiki 머신 실측 · ref 129개 전수) 숫자는 이력이 자라면 달라진다 —
**비교할 것은 `FULL=1`과 `FOREIGN=0`이다.**

## 4. 성공 기준

**①의 성공/실패**는 화면 문구가 아니라 **exit code**로 본다.

| EXIT | 뜻 | 다음 행동 |
|---|---|---|
| `0` | 수집 성공 · 선언 밖 신원 **없음** | ③으로 진행 |
| `1` | 수집 성공 · **혼입 신원 발견** | 리포트 §5의 커밋 해시를 확인한다. 재직사 계정이면 ③ 전에 상의가 먼저다 |
| `2` | **수집 실패** (shallow 클론·git 오류·신원 미선언 등) | 리포트를 증빙으로 쓰지 않는다. 화면의 사유를 그대로 전달 |

> `2`는 "이상 없음"이 아니다. 잘린 이력에서 나온 "혼입 0건"은 잘린 부분에 대해 아무 말도
> 하지 않으며, 그것을 확인서에 첨부하면 그대로 거짓 진술이 된다.

**리포트를 읽는 방법**: 위 블록의 3)은 `--summary-from`으로 도구 자신에게 리포트를
읽힌다. **PowerShell의 `ConvertFrom-Json`을 쓰지 않는다** — 이 창의 JSON 파서는
객체 키를 대소문자 무시로 다뤄 `Claude <noreply@anthropic.com>`과
`claude <noreply@anthropic.com>`을 중복 키로 거부한다(2026-09-08 실측 ·
`DuplicateKeysInJsonString`). 키는 커밋한 사람의 이름·이메일이라 우리가 통제할 수
없으므로 **파서를 바꾸는 것이 유일한 해결**이다. 요약 모드의 exit code는
`0`=읽었고 조건 충족 · `1`=읽었으나 미충족(`CLEAR_BLOCKERS`가 사유) ·
`2`=**읽기 자체가 불가**(값을 한 줄도 내지 않는다).

**혼입(`FOREIGN` ≥ 1)은 `CLEAR_READY=0`으로 막힌다.** 생성 명령이 `EXIT=1`을 낸
리포트로 게이트가 닫히면 재직사 계정이 이력에 있는 채로 "귀속 분리 확보"가
선언되기 때문이다. 혼입이 **본인의 다른 계정**이어서 오분류인 경우, 해소는
게이트를 통과시키는 것이 아니라 그 주소를 실행 블록 ①의 `--identity`에 한 줄
추가하고 다시 재는 것이다(1~2분). 재직사 계정이라면 ③ 확인서 작성 **전에**
상의가 먼저다.

**exit code와 함께 반드시 볼 것 — `FULL=1`**. 범위를 좁혀 돌리면(`--rev`·`--since`)
`EXIT=0`이 나와도 그것은 *그 범위 안에서만* 참이다. `FULL=0`인 리포트를 "이력 전체에서
혼입 없음"의 근거로 쓰면 안 되며, 실행 블록 ③이 이 조건을 검사해 clear를 거부한다.

**신원 선언 확인**(위 §실행 블록 ①의 "반드시 확인할 것"): `kiki@whymath.local`이 본인의
로컬 git 설정 주소가 맞는지 확인했는가. 이 확인 없이 `EXIT=0`을 성공으로 읽으면, 선언으로
가린 신원이 검증된 것처럼 보인다.

**놀라지 않아도 되는 것 2가지**:

1. 리포트 §2에 `+09:00`이 아닌 오프셋(`-04:00`·`+00:00`)이 **1400건 넘게** 찍힌다.
   클라우드 세션 컨테이너와 하네스 봇이 만든 커밋이며 **재직사 장비를 뜻하지 않는다**.
   확인서 §2-1의 세 번째 항목이 이 사실을 적는 자리다 — 감추지 말고 그대로 적는다.
2. 리포트 §3의 시각 분포는 **사람이 저작한 커밋만**(약 1021건) 센다. 하네스 봇의 장부
   커밋 932건이 섞이면 "개인 시간에 작업했는가"라는 질문에 봇의 실행 시각이 답하기
   때문이다. 전체 스캔분 수치도 같은 절에 병기되므로 감춰지지 않는다.

**③④의 성공 기준**: 두 문서의 모든 체크 항목에 표시가 있고, "일부"로 표시한 항목마다
사유가 적혀 있고, 서명일과 서명이 들어가 있을 것. **빈칸이 남은 문서는 미완성이 아니라
위험**이다 — 실사에서 빈칸은 "확인하지 않았다"로 읽힌다.

## 5. 실행 환경

- **머신**: Phaiakes9 = Kiki의 작업 PC 그 자체 (별도 접속·SSH 불요)
- **시스템**: Windows PowerShell
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: 인터넷 연결(브랜치 fetch). Docker·Ollama·백엔드 서버는 **불요**
- **주의**: 이 저장소 클론이 shallow면 exit 2가 난다. 그 경우 화면 안내대로
  `git fetch --unshallow origin` 후 재실행한다

## 6. 창 구분

**새 PowerShell 창 1개**로 충분하다. 장기 점유 프로세스가 없어 실행 후에도 계속 써도 된다.
창을 나눌 필요가 없다.

---

## 실행 블록 ① — 증거 생성 (통째로 복사-붙여넣기)

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 — 별도 접속 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 0) main 최신화. 도구는 PR #1041(79b0cc4d)로 **main에 착지**했으므로 별도
#    브랜치 체크아웃이 필요 없다.
git checkout main
git pull origin main

# 0-a) 선행 자가검증 — 스크립트가 실제로 있는가 (없으면 아래가 전부 무의미하다)
$ToolOk = Test-Path scripts\ops\ip_separation_evidence.py
"TOOL_OK=$ToolOk"

# 1) 파이프 인코딩 고정 — 리포트가 한글이고 이 창의 로케일은 cp949다.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 1-a) 모든 원격 브랜치를 받아 둔다 — 도구는 이 클론이 가진 ref만 볼 수 있다.
#      **fetch 성공을 확인한다**: 실패해도 오래된 원격 추적 ref는 그대로 남아
#      스캔이 성공하고 FULL=True까지 나온다 — 누락된 커밋이 "전수 증거"가 된다.
#      `--all`은 "모든 원격을 대상으로"라는 뜻일 뿐 성공·최신성을 보증하지 않는다.
git fetch --all --quiet
$FetchOk = ($LASTEXITCODE -eq 0)
"FETCH_OK=$FetchOk"

# 1-b) shallow면 도구가 exit 2를 낸다. 미리 보고 넘어간다.
git rev-parse --is-shallow-repository

# 2) 증거 생성. 산출물은 .ip_evidence\ (gitignore 대상 — 커밋되지 않는다)
#    신원 2개를 선언한다 — 두 번째는 아래 "확인할 것"을 반드시 읽을 것.
if ($ToolOk -and $FetchOk) {
  python scripts\ops\ip_separation_evidence.py `
      --identity rollrock.ki@gmail.com `
      --identity kiki@whymath.local `
      --out .ip_evidence `
      --jsonl .ip_evidence\commits.jsonl
  $Code = $LASTEXITCODE
  "EXIT=$Code  (0=혼입없음 · 1=혼입발견 · 2=수집실패)"
} elseif (-not $FetchOk) {
  "중단: git fetch --all 이 실패했다 — 오래된 ref로 측정하면 전수가 아니다."
  "  네트워크·인증을 확인하고 1-a)부터 다시 실행할 것."
} else {
  "중단: 도구 파일이 없다 — 0)의 git pull 출력을 확인할 것(main 최신화 실패)"
}

# 3) 자가검증 — 파일이 실제로 생겼는가 + 상태가 ok인가 + 전수를 봤는가
#    **PowerShell의 ConvertFrom-Json을 쓰지 않는다.** 이 창의 파서는 JSON 객체
#    키를 대소문자 무시로 다뤄 'Claude <…>'와 'claude <…>'를 중복으로 거부한다
#    (2026-09-08 실측). 리포트를 읽는 일은 도구 자신에게 시킨다.
# 3-a) 선검사 — **이 체크아웃의 도구가 --summary-from을 아는가**.
#      모르면 브랜치가 낡은 것이지 리포트가 깨진 것이 아니다. 이 검사가 없으면
#      argparse의 인자 오류도 exit 2를 내므로 "읽기 실패"와 구분되지 않는다
#      (2026-09-08 실측: 미머지 상태의 main에서 실행돼 왕복 1회 소모).
$HasSummary = [bool](python scripts\ops\ip_separation_evidence.py --help 2>&1 |
                     Select-String -SimpleMatch -- "--summary-from")
"HAS_SUMMARY_FROM=$HasSummary"

if ($HasSummary) {
  python scripts\ops\ip_separation_evidence.py `
      --summary-from .ip_evidence\ip_separation_evidence.json
  "SUMMARY_EXIT=$LASTEXITCODE  (0=읽었고 조건 충족 · 1=읽었으나 미충족 · 2=읽기 실패)"
} else {
  "중단: 이 체크아웃의 도구에 --summary-from이 없다 — 0)의 최신화가 안 됐거나"
  "      이 기능이 아직 머지되지 않은 것이다. 리포트 문제가 아니다."
}
```

### ⚠ 반드시 확인할 것 — 왜 신원을 2개 선언하는가

2026-09-07 전수 실측(모든 ref 2297건)에서 **커밋 신원 2개가 추가로 발견**됐다.
초판 도구는 `HEAD`만 훑어서 이 둘을 통째로 못 봤다(2297건 중 1018건만 스캔).

| 발견된 신원 | 건수 | 정체 | 처리 |
|---|---|---|---|
| `whymath-harness <harness@whymath.invalid>` | 932 | 빌드 하네스 봇. 전부 `origin/harness-claims`(claim 대장 orphan 브랜치)에만 있고 트리는 `claims/` 하나뿐 — 소스가 아니라 기계 장부 | 도구 신원으로 **기본 분류**(코드에 고정). 숨기지 않는다 — 리포트 §1 표에 건수와 함께 실린다 |
| `kiki <kiki@whymath.local>` | 30 author·30 committer·63 coauthor | **로컬 git 설정으로 만들어진 주소로 보인다** — 커밋 시각이 전부 KST(+09:00)이고 내용도 정상 개발분(EOS-204·MISC-12~16 등, PR #882 참조) | 위 블록이 `--identity`로 선언한다. **본인 주소가 맞는지 확인하는 것은 본인 몫이다** |

**`kiki@whymath.local`이 본인 것이 아니라면**: 위 블록에서 두 번째
`--identity kiki@whymath.local` 줄을 지우고 다시 돌린다. 그러면 그 30건이 혼입
신호로 뜨고, 그 커밋들이 무엇인지 확인한 뒤 확인서 §2-2에 사실대로 적는다.

**여기서 나온 `HEAD=` 값을 메모한다.** 확인서 §1과 양도기록 §1의 "기준 커밋"에 그대로
옮겨 적을 값이다.

---

## 사람 작업 ②③④ — 확인서·양도 예정 기록

### 실행 블록 ② — 작성용 사본 만들기

```powershell
# [실행 시스템] Windows PowerShell — 같은 창에서 이어서
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 저장소 **밖** 보관 폴더를 만들고 템플릿을 복사한다.
# 저장소 안에 두지 않는 이유: 재직사명·서명이 들어가는 문서다.
$Vault = "$env:USERPROFILE\Documents\WhyMath-IP"
New-Item -ItemType Directory -Force -Path $Vault | Out-Null
Copy-Item docs\legal\templates\no_employer_assets_declaration_ko.md `
          "$Vault\재직사자산무사용확인서.md" -Force
Copy-Item docs\legal\templates\ip_assignment_intent_record_ko.md `
          "$Vault\IP양도예정기록.md" -Force
Copy-Item .ip_evidence\ip_separation_evidence.md "$Vault\" -Force
Copy-Item .ip_evidence\ip_separation_evidence.json "$Vault\" -Force
Copy-Item .ip_evidence\commits.jsonl "$Vault\" -Force

# 자가검증 — 5개 파일이 다 왔는가
"VAULT=$Vault"
(Get-ChildItem $Vault | Measure-Object).Count.ToString() + "개 파일"
Get-ChildItem $Vault | Select-Object -ExpandProperty Name
explorer $Vault
```

### 기입할 때 지킬 것 3가지

1. **사실만 적는다.** 근무시간 중 작업이 있었으면 있었다고 적고 사유를 함께 적는다.
   리포트 §3의 업무시간 비율과 기재가 어긋나면 실사에서 가장 먼저 질문받는다.
   *수치를 보고 기재를 맞추는 것이 아니라, 사실을 적고 수치를 설명한다.*
2. **맨 윗줄 마커를 바꾼다** — 두 문서의 첫 줄 `template`을 `signed`로. 실수로 저장소에
   커밋되면 CI 가드(`tests/infra/test_ip_separation_evidence.py`)가 그 마커로 잡아낸다.
3. **빈칸을 남기지 않는다.** 해당 없으면 "해당 없음", 미정이면 "미정"이라고 적는다.
   빈칸은 "확인하지 않았다"로 읽힌다.

### 서명 후 — 시점 고정

서명한 두 문서를 스캔하거나 PDF로 저장한 뒤 **자기 자신에게 이메일로 발송**한다.
메일 서버의 수신 시각이 "이 문서가 그날 존재했다"의 제3자 기록이 된다. 클라우드
드라이브 업로드도 같은 역할을 한다.

---

## 실행 블록 ③ — 게이트 clear

> 위 ③④⑤(서명·보관·시점 고정)를 **마친 뒤에** 실행한다. 이 블록은 서명 완료 여부를
> 물어보고 멈추며, 답하지 않으면 아무것도 하지 않는다.

```powershell
# [실행 시스템] Windows PowerShell — 같은 창에서 이어서
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 판정 기준(커밋)과 실측치를 블록이 스스로 찾는다 — 손으로 옮겨 적지 않는다.
# 리포트는 **도구가 읽는다**(--summary-from). PowerShell의 ConvertFrom-Json은
# 대소문자만 다른 신원 키를 중복으로 거부하므로 여기서 쓰지 않는다.
$Base = (git rev-parse HEAD)
$Vault = "$env:USERPROFILE\Documents\WhyMath-IP"
$Today = (Get-Date -Format "yyyy-MM-dd")

# 요약을 KEY=VALUE로 받아 해시테이블로 만든다. 파싱 실패 시 값이 한 줄도
# 나오지 않으므로 $S는 비고, 아래 조건은 그대로 거짓이 된다.
# 도구 능력 선검사 — 없으면 argparse 오류(exit 2)가 "읽기 실패"로 오독된다.
$HasSummary = [bool](python scripts\ops\ip_separation_evidence.py --help 2>&1 |
                     Select-String -SimpleMatch -- "--summary-from")
$Lines = if ($HasSummary) {
  & python scripts\ops\ip_separation_evidence.py `
      --summary-from .ip_evidence\ip_separation_evidence.json `
      --expect-head $Base
} else { @() }
$SummaryExit = if ($HasSummary) { $LASTEXITCODE } else { 2 }
"HAS_SUMMARY_FROM=$HasSummary"
$S = @{}
foreach ($L in $Lines) { if ($L -match '^([A-Z_]+)=(.*)$') { $S[$Matches[1]] = $Matches[2] } }
$Lines                       # 화면에 그대로 남긴다 — 무엇을 근거로 닫는지 보이게
"SUMMARY_EXIT=$SummaryExit"

"기준 커밋: $Base"
"보관 폴더: $Vault"

# 서명 완료를 직접 확인한다. 붙여넣기 실행이어도 이 줄에서 멈춘다.
$Ack = Read-Host "확인서·양도예정 기록 2종에 서명하고 보관까지 마쳤으면 '서명완료' 를 입력"

# 기계 조건 판정은 도구의 exit code로 한다 — 화면 문자열이 아니다.
# 0 = 읽었고 status=ok · 커밋>0 · 전수 · 리포트가 이 커밋을 잰 것.
# exit code만 보지 않는 이유: `python`을 못 찾으면 PowerShell은 예외를 내고
# $LASTEXITCODE는 **직전 명령(git)의 0이 그대로 남는다** — 출력이 한 줄도
# 없는데 "성공"으로 읽힌다. 그래서 도구가 실제로 낸 값 2개를 함께 본다
# (간접 신호를 성공 판정으로 쓰지 않는다).
$EvidenceOk = ($SummaryExit -eq 0) -and ($S['SUMMARY_OK'] -eq '1') -and ($S['CLEAR_READY'] -eq '1')

if ($Ack -eq "서명완료" -and $EvidenceOk) {
  python scripts\harness\backlog.py gates clear G-eos-ip-separation-evidence --as kiki `
    --evidence "$Today Kiki 서명. 판정 기준: $Base (MGMT-05 PR). ①기계 증거 = scripts/ops/ip_separation_evidence.py 실행 결과 — $($S['SCOPE']) $($S['COMMITS'])건(사람 저작 $($S['PERSON_AUTHORED'])건), 선언 밖 신원 $($S['FOREIGN'])종, 평일 09-18시 KST 커밋 비율 $($S['WORK_HOURS_RATIO']). ②재직사 자산·데이터 무사용 확인서 자체 작성·서명 완료. ③신설 법인 IP 양도 예정 기록 작성·서명 완료. 3종 모두 저장소 밖 보관($Vault) + 자기발송으로 시점 고정. 저장소에는 빈 템플릿(docs/legal/templates/)만 추적한다. 법적 판단(업무상저작물·직무발명·겸업금지)은 미착수 — 확인서 §5가 자문 질문 목록으로 승계."
  "EXIT=$LASTEXITCODE  (0=clear 성공 · 1=거부)"
} elseif (-not $EvidenceOk) {
  "중단: 기계 증거가 유효하지 않다 — clear하지 않는다."
  "  SUMMARY_EXIT=$SummaryExit  (2=리포트를 읽지 못함 · 1=조건 미충족)"
  "  CLEAR_BLOCKERS=$($S['CLEAR_BLOCKERS'])"
  "  실행 블록 ①을 다시 돌려 EXIT=0 또는 1, STATUS=ok, FULL=1을 확인할 것."
} else {
  "중단: 서명 전에는 clear하지 않는다. 입력값='$Ack'"
}
```

> **이 블록에는 손으로 채울 자리가 하나도 없다** — 커밋 해시·실측치·날짜·보관 경로를
> 전부 블록이 스스로 찾는다. 붙여넣기 실행에서 자리표시자는 치환되지 않고 그대로
> 인자가 되기 때문이다(2026-09-06 PATH-04 런북 사고).

**clear 후**: `python scripts\harness\backlog.py gates list`로 상태가 `cleared`인지 확인하고,
변경된 `backlog/` 파일을 커밋·푸시한다(대장은 저장소가 정본이다).

---

## 이 게이트가 **해결하지 않는** 것

| 축 | 상태 |
|---|---|
| 업무상저작물(저작권법 §9) 해당 여부 | 미판단 — 변호사 |
| 직무발명(발명진흥법 §10) 해당 여부 | 미판단 — 변호사 |
| 겸업금지·경업금지 조항의 유효 범위 | 미판단 — 변호사 |
| AI 생성물의 저작권 귀속 | 미판단 — 변호사 |
| 재직사 겸직 신고 의무 이행 | 미확인 — 내규 확인 필요 |

이 다섯 줄이 `MGMT-01`·`MGMT-02`(변호사 자문 보류분)와 같은 대기열에 있다. 게이트를
clear해도 이것들은 그대로 남으며, 확인서 §5가 자문 시작 시점의 질문 목록으로 그대로
넘어간다. **게이트 clear는 "사실 기록을 확보했다"이지 "법적으로 안전하다"가 아니다.**
