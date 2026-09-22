# S3-02 자유사용 대표측정 런북 (트리거 ③ · Kiki 실기기)

> ## ⚠️ 실행 상태: **2026-12-31 내부완성 이후로 연기 — 지금 실행하는 지시가 아니다**
>
> 2026-09-22 Kiki 지시. 측정 *도구*는 준비 완료(S3-51 · PR #1273)이고, 미루는 것은 라이브
> 회차뿐이다. 재개 판정은 게이트 `G-s302-free-use-remeasure-restart`가 소유하며(리마인드
> 100일 ≈ 2026-12-31), 종전 게이트 `G-s302-free-use-remeasure`는 같은 날 waive됐다 —
> **면제가 아니라 시점 이동**이다. 아래 절차·판정 기준은 그때 그대로 쓴다.
>
> 재개 시 먼저 볼 것: 12/31 내부완성으로 앱이 달라졌다면 사전등록 기준의 전제(2026-07-17
> 실사용 unverifiable 89% 기준선)가 여전히 유효한지 — 재개 게이트의 판정 ②가 그 축이다.

> **이 문서는 Kiki가 실기기에서 1회 수행하는 측정의 실행 절차다.** 판정 기준은
> 2026-07-28에 **사전 등록**됐고(`docs/strategy/s3_pilot_briefing.md`) 이 런북은 그것을
> 바꾸지 않는다 — 측정 *방법*만 적는다(사후 기준 이동 금지).
>
> 게이트: `G-s302-free-use-remeasure` · 선행 관측 코드: `S3-51`

---

## ① 과제 명칭

**S3-02 자유사용 대표측정** — 실기기에서 대본 없이 15~30분 자연 사용하고, 그 구간의 verify
verdict 분포를 수확해 회신한다.

## ② 목적

S3-01 파일럿(시범 학생 5~10명) 착수 트리거 4종 중 **마지막 하나**다. ①②는 2026-07-20/21에
충족됐고 ③만 남았다 — 이것이 통과하면 "출시 직전"이 되고, 동의 서류 리드타임만큼 앞당겨
모집을 시작한다.

재는 것: 2026-07-17 실사용 shadow에서 **unverifiable 89%**(n=9)였던 현상이 S3-02(등호 방정식
해집합 보존 판정) 착지 뒤 실제로 내려갔는가. 2026-07-19·20의 확인은 **합성 트래픽과 대본**
이었다 — 대본은 "되는 입력"을 고르게 되므로 대표성이 없다. 그래서 이 회차는 **대본 금지**다.

## ③ 구체적 절차

| 단계 | 창 | 내용 | 예상 |
|---|---|---|---|
| A | 창① | 저장소를 main 최신으로 맞추고 **도구가 이번 판인지** 자가검증 | 2분 |
| B | 창① | 측정 회차 시작 시각 기록 + 백엔드 기동(`run_demo.ps1`) | 3~5분 |
| C | 창② | 실기기에서 앱 실행(run_demo가 출력한 *값이 채워진* 명령 그대로) | 3분 |
| D | 패드 | **15~30분 자연 자유사용**(대본 금지·아래 §자유사용 지침) | 15~30분 |
| E | 창① | 수확 실행 → 리포트 전문 회신 | 2분 |
| F | 창① | 정리(`stop_demo.ps1`) | 1분 |

### 자유사용 지침 (D단계 — 가장 중요)

- **대본을 만들지 않는다.** "이 식을 넣어야지"라고 미리 정하지 않고, 실제 학생처럼 문제를
  받고 풀어서 제출한다. 막히면 막힌 대로 두고 코치와 대화한다.
- **풀이는 여러 단계를 한 메시지에 줄바꿈으로 묶어 제출한다**(풀이 모드·Enter=줄바꿈·전송은
  버튼). 한 줄씩 따로 보내면 매 턴이 외톨이 단계라 **구조적으로 unverifiable이 정상**이다
  (2026-07-19 실측·S3-05). 이건 대본이 아니라 앱의 입력 방식이다.
- **등호 방정식 풀이를 일부러 세지 않는다.** 몇 건이었는지는 리포트가 센다(`등호 전이 >=1 턴`).
  손으로 세면 그 자체가 자연 사용을 깨뜨린다.
- **F1 관찰만 메모한다**: *내가 맞게 쓴 단계인데 앱이 틀렸다고 한 순간*이 있으면 그때의 화면을
  캡처하거나 무슨 식을 넣었는지만 적어 둔다(1건이라도 있으면 즉시 환류 대상이다).

---

## ④ 성공 기준 (사전 등록 — 2026-07-28 고정)

판정은 서기(claude)가 회신받은 리포트로 한다. 수확 도구는 의도적으로 **판정선을 내지 않는다**
(분포만 제시).

**유효성 전제**(하나라도 미달 → 판정 무효·재측정)

| 축 | 기준 | 리포트에서 읽는 줄 |
|---|---|---|
| V1 | `parsed` >= 1 | `[파싱 회계] … parsed N` |
| V2 | verify 대상 턴 n >= 10 (권장 15~20) | `[판정 모집단 …] 모집단 n` |
| V3 | 등호 방정식 변형 턴 >= 5건 | `[전이 형태 …] 등호 전이 >=1 턴` |

**합격**(둘 다 충족)

- **P1** unverifiable <= 50% — 분모는 **판정 모집단**(`none` 제외). 기대치 10~30%대.
- **P2** unverifiable 건수 <= Wilson 단측 95% 상한표: n=10→7 · n=15→11 · n=20→15 ·
  n=25→19 · n=30→23. **P2만 통과하고 P1이 미달이면 불합격.**

**즉시 환류**(비율과 무관)

- **F1** 거짓 incorrect 1건 이상(옳은 단계를 incorrect로 판정) → S3-02의 "거짓 incorrect 0"
  위반이므로 신뢰 우선 버그 환류.
- **F2** unverifiable > 50% → 잔여 축 분석 후 후속 태스크 환류·모집 착수 금지 유지.

**흔한 오독 2가지**

1. 리포트 위쪽 `[verify verdict 분포]`의 비율은 분모에 `none`(풀이 미동봉 대화 턴)이 들어
   있어 **사전등록 비율이 아니다.** 판정은 그 아래 `[판정 모집단]` 절의 비율로 한다.
2. 구간(`--since`)을 안 주면 원장에 쌓인 **이전 회차(2026-07 합성 60제출 포함)**가 같은
   분모에 들어온다 — 그러면 이번 회차와 무관하게 통과가 나온다. 아래 블록은 구간을 자동으로
   건다.

## ⑤ 실행 환경

- **머신**: Phaiakes9(= 평소 쓰는 이 PC) · Windows PowerShell · 작업 디렉터리
  `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Docker Desktop 가동 · `src\backend\.venv` 세팅 완료 · 패드와 PC가 **같은 WiFi**
- **실기기**: 안드로이드 태블릿(USB 연결·`flutter devices`에 보이는 상태)

## ⑥ 창 구분

- **창①** = PowerShell 1개. 백엔드는 `run_demo.ps1`이 **백그라운드로** 띄우므로 이 창은 계속
  쓸 수 있다(점유되지 않는다). E·F단계도 이 창에서 한다.
- **창②** = PowerShell 1개(`src\mobile`). `flutter run`이 이 창을 점유한다 — 측정이 끝날
  때까지 이 창에서 다른 명령을 치지 않는다. `Ctrl+C`는 복사가 아니라 **앱 중단**이다.

---

## 실행 블록

### [A] 창① — 저장소 최신화 + 도구 판 자가검증

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git checkout -B main origin/main
git log -1 --oneline
```

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$HasPy = Test-Path $Py
if ($HasPy) { "TOOL_HAS_SINCE=" + [bool](& $Py -m whymath_backend.harness.wh1_shadow_harvest --help | Select-String -Pattern "--since" -Quiet) } else { "PY_MISSING=True — src\backend\.venv 미설정(README의 uv venv 절차 먼저)" }
```

> **판정**: `TOOL_HAS_SINCE=True`여야 한다. `False`면 구간 필터가 없는 옛 판이다(S3-51 미머지)
> — 그 상태로 진행하면 2026-07 합성 60제출이 분모에 섞여 **거짓 통과**가 난다. 여기서 멈추고
> claude에게 알린다. `PY_MISSING=True`면 venv부터 만든다.

### [B] 창① — 회차 시작 시각 기록 + 백엔드 기동

첫 블록은 **쓰기 블록**이라 [A]의 판정을 스스로 다시 확인하고, 불충분하면 실행을 거부한다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$StartFile = "C:\Users\kiki\Desktop\__AI\WhyMath\.freeuse_round_start.txt"
$HasPy = Test-Path $Py
$HasSince = $false
if ($HasPy) { $HasSince = [bool](& $Py -m whymath_backend.harness.wh1_shadow_harvest --help | Select-String -Pattern "--since" -Quiet) }
if ($HasPy -and $HasSince) { (Get-Date).ToUniversalTime().ToString("o") | Out-File -FilePath $StartFile -Encoding ascii; "ROUND_START=" + (Get-Content $StartFile).Trim() } else { "WRITE_REFUSED=True (py=$HasPy since=$HasSince) — [A] 판정을 먼저 통과시킨다" }
```

> **판정**: `ROUND_START=2026-…Z` 형태의 **실제 시각**이 찍혀야 한다. 이 값이 [E]의 집계 구간
> 하한이 된다. `WRITE_REFUSED=True`면 괄호 안 두 값 중 False인 쪽을 [A]에서 고친다.

이 값이 찍힌 것을 **눈으로 확인한 뒤** 백엔드를 띄운다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
.\scripts\demo\run_demo.ps1
```

> **성공 신호**: `실기기 시연 준비 완료`와 함께 `flutter run --dart-define=API_URL=…
> --dart-define=DEMO_TOKEN=…` 한 줄이 **값이 채워진 상태로** 출력된다. 서버는 백그라운드로
> 뜨므로 이 창은 계속 쓸 수 있다. 실패하면 대개 Docker Desktop 미가동이거나 venv 미설정이고,
> 메시지가 그대로 말해 준다.

### [C] 창② — 실기기 앱 실행

창②를 새로 열고 아래를 실행한 뒤, **[B]가 출력한 `flutter run …` 줄을 그대로 복사해
붙여넣는다**(토큰이 매 실행 바뀌므로 이 문서에 적어 둘 수 없다).

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\mobile
flutter devices
```

> **성공 신호**: 패드가 목록에 보이고, `flutter run` 뒤 앱이 **이미 로그인된 상태로**
> 문제 화면까지 뜬다. "문제를 불러오지 못했어요"가 뜨면 백엔드에 못 닿은 것이다 —
> `/demo-doctor` 스킬 카탈로그 D행을 먼저 본다.

### [D] 패드 — 15~30분 자유사용

위 §자유사용 지침대로. 타이머는 따로 필요 없다(리포트에 관측 시각 구간이 찍힌다).

### [E] 창① — 수확 (쓰기 블록 · 선행 조건 자가거부)

아래 블록은 **선행 조건을 스스로 다시 확인하고 불충분하면 실행을 거부한다.** 붙여넣어도
조건이 안 맞으면 `HARVEST_REFUSED`를 출력하고 아무것도 하지 않는다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$StartFile = "C:\Users\kiki\Desktop\__AI\WhyMath\.freeuse_round_start.txt"
$HasPy = Test-Path $Py
$HasStart = Test-Path $StartFile
$HasLog = Test-Path "wh1_shadow_records.log"
if ($HasPy -and $HasStart -and $HasLog) { $Since = (Get-Content $StartFile).Trim(); & $Py -m whymath_backend.harness.wh1_shadow_harvest wh1_shadow_records.log --store ..\..\wh1_shadow_ledger_realdevice.ndjson --since $Since --json ..\..\wh1_freeuse_report.json; "HARVEST_EXIT=$LASTEXITCODE" } else { "HARVEST_REFUSED=True (py=$HasPy start=$HasStart log=$HasLog)" }
```

> **회신할 것**: 위 출력 **전문**(`====` 줄부터 `HARVEST_EXIT=0`까지) + D단계에서 메모한
> F1 관찰(있으면). 리포트는 비식별이다 — 학생 원문·식·정답은 애초에 담기지 않는다.
>
> `HARVEST_REFUSED=True`가 나오면 괄호 안 세 값이 무엇이 False인지 말해 준다:
> `py=False`→venv 미설정 · `start=False`→[B] 쓰기 블록을 건너뛴 것 ·
> `log=False`→서버가 안 떴거나 트래픽이 0건(캡처 파일 미생성).

### [F] 창① — 정리

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
.\scripts\demo\stop_demo.ps1
```

창②는 `Ctrl+C`로 `flutter run`을 끝낸다.

---

## 측정이 무효가 되는 경우 (재실행 조건)

- 측정 **도중 서버를 재기동**했다 — `run_demo.ps1`은 기동 시 캡처 파일을 지운다
  (`Remove-Item $WhRecords`). 재기동이 불가피하면 **재기동 전에 [E]를 한 번 돌려** 원장에
  적재한 뒤 이어서 사용한다(원장은 중복 제거가 되므로 여러 번 돌려도 안전하다).
- V1~V3 중 하나라도 미달 — 사전등록대로 판정 무효다. 특히 V3 미달이면 리포트의
  `Σ혼합 형태 전이`를 함께 본다: 그 수가 크면 원인은 백엔드 판정이 아니라 **입력이 등식
  단계로 정렬되지 않은 것**이다(입력 UX 축·S3-05 계열).

## 이 회차가 측정하지 않는 것 (정직 범위)

- **코치 발화의 품질**은 이 측정의 대상이 아니다(S4-04 계열). 여기서 재는 것은 *검증 가능성*
  분포 하나다.
- **거짓 incorrect 0**은 기계가 세지 못한다 — 옳은 단계인지는 사람만 안다. 그래서 F1은
  Kiki의 관찰로만 들어온다(그 관찰이 곧 환류 트리거다).
