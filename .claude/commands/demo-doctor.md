---
description: 실기기 시연 트러블슈팅 닥터 — Windows/PowerShell 데모 기동~실기기 구동까지 실측된 전 문제·해법 카탈로그로 즉시 진단
argument-hint: "[에러 메시지 또는 증상] (인자 없으면 골든 패스 점검)"
---

# /demo-doctor — 실기기 시연 트러블슈팅

## 임무
S1 실기기 시연(백엔드 기동 → 앱 빌드 → 실기기 구동)에서 발생하는 문제를,
**2026-07-09~10 Kiki의 Windows(Phaiakes9)에서 실측·해결된 전 사례 카탈로그**로 즉시 진단한다.
새로 디버깅하지 말고 **먼저 아래 표에서 증상을 매칭**하라 — 전부 한 번씩 실제로 겪고 고친 것들이다.

## 사용법
1. 사용자가 에러/증상을 주면 → 아래 카탈로그에서 매칭 → 해법 제시. 대부분의 수정은 이미
   브랜치에 착지돼 있으므로 **1차 처방은 항상 `git pull` 후 재시도**다.
2. 인자가 없으면 → §골든 패스를 순서대로 점검한다.
3. 카탈로그에 없는 새 문제면 → 진단 후 **이 파일에 행을 추가**하고 커밋한다(카탈로그는 살아있는 문서).

## 대원칙 (이 여정에서 배운 것)
- **Windows는 PowerShell 네이티브로**: WSL bash는 Docker 미연동·경로 혼선. `.ps1` 스크립트를 쓴다.
- **자리표시 `<...>`는 치는 게 아니라 실제 값으로 바꾼다**: PowerShell은 `<`를 예약어로 거부하고,
  flutter run은 구문 오류를 낸다. 스크립트가 출력한 **값이 채워진 명령을 한 줄 통째로** 복사한다.
- **버전은 고정한다**: Flutter는 FVM 3.24.5(`.fvmrc`), Python은 3.12, Gradle 8.7/AGP 8.3.2.
  "최신"이 끌어오는 비호환 조합이 이 여정 실패의 절반이었다.
- **환경변수 잔재를 의심한다**: PowerShell env는 스크립트가 끝나도 창에 살아남는다.
  이전 실행의 값이 새 실행에 새어들 수 있다(데모 스크립트는 이제 항상 덮어씀).

## 골든 패스 (전 과정 요약 · 상세는 scripts/demo/README.md §A)
```powershell
# [백엔드 — 리포 루트] Docker Desktop 실행 중 + Ollama 가동 상태에서
git pull
cd src\backend ; python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -e ".[dev]" ; cd ..\..
.\scripts\demo\run_demo.ps1        # → 마지막 상자의 flutter run 명령 복사·이 창 유지

# [앱 — src\mobile] 기기 USB 연결(개발자 모드·USB 디버깅) + 같은 WiFi
$env:PATH = "$env:LOCALAPPDATA\Pub\Cache\bin;$env:PATH"   # fvm PATH(새 창마다)
fvm flutter pub get
fvm dart run build_runner build --delete-conflicting-outputs
fvm flutter run --dart-define=API_URL=http://<출력된 IP>:8000 --dart-define=DEMO_TOKEN=<출력된 토큰>
```

## 문제 카탈로그 (증상 → 원인 → 해법 · 전부 실측)

### A. PowerShell / 환경
| 증상 | 원인 | 해법 |
|---|---|---|
| `uv` 용어가 인식되지 않습니다 | pip가 uv를 Python3.13 사용자 폴더에 설치·PATH 밖 | **uv 불필요** — conda base가 3.12면 `python -m venv .venv` |
| `source` 용어가 인식되지 않습니다 | 리눅스 명령 | Windows는 `.\.venv\Scripts\Activate.ps1` (bin 아님·Scripts) |
| `Activate.ps1` 실행 차단 | 실행 정책 | `Set-ExecutionPolicy -Scope Process -Bypass` 후 재시도 |
| `.venv` 삭제 시 "액세스 거부" | 활성 venv/편집기가 파일 잠금 | **새 PowerShell 창**에서 `Remove-Item -Recurse -Force .venv` |
| `.ps1` 파싱 오류(한글 깨짐·"종결자가 없습니다") | PS 5.1이 BOM 없는 .ps1을 CP949로 읽음 | 수정 완료(UTF-8 BOM + `.gitattributes *.ps1 eol=crlf`) → `git pull` |
| 고친 설정이 적용 안 되고 같은 오류 재발 | 이전 실행의 env 잔재가 같은 창에 잔존 | 수정 완료(스크립트가 항상 덮어씀·오버라이드는 `WHYMATH_DEMO_DATABASE_URL` 전용) → `git pull` |
| `'<' 연산자는 예약되어 있습니다` | 자리표시 `<...>`를 그대로 입력 | 실제 값으로 교체·URL은 따옴표(`--evidence "https://..."`) |
| `.\scripts\demo\run_demo.ps1` 용어가 인식되지 않습니다 | **리포 루트가 아닌 폴더**에서 실행(중첩 폴더 `Desktop\__AI\WhyMath\WhyMath` 혼동) | `cd C:\Users\kiki\Desktop\__AI\WhyMath\WhyMath` 후 재실행. `dir`로 `scripts`·`src`·`docker-compose.demo.yml`이 보이면 정위치 |

### B. Docker / Postgres / alembic
| 증상 | 원인 | 해법 |
|---|---|---|
| `docker could not be found in WSL` | WSL 배포판에 Docker 미연동 | **PowerShell 네이티브**에서 `.ps1` 실행 |
| `Bind for 0.0.0.0:5432 failed: port is already allocated` | 로컬 PostgreSQL이 5432 점유 | 수정 완료(데모는 호스트 **55432**) → `git pull` |
| `CREATE EXTENSION vector` 실패 | 순정 postgres:16엔 pgvector 없음 | 수정 완료(`pgvector/pgvector:pg16`) → `git pull` |
| `UnicodeDecodeError: 'cp949' codec ...` (alembic) | Alembic이 ini를 OS 로케일로 읽음(하드코딩·우회 불가) | 수정 완료(alembic.ini ASCII화) → `git pull` |
| `ConnectionError: unexpected connection_lost()` (alembic/asyncpg) | Windows asyncpg SSL 협상 버그 | 수정 완료(데모 URL `?ssl=disable`) → `git pull` |
| **W1** · `ConnectionRefusedError [WinError 1225]` 또는 `bind: An attempt was made to access a socket in a way forbidden by its access permissions` — 컨테이너는 `Up`이고 `pg_isready`도 통과하는데 호스트에서만 못 붙음 | **Windows Hyper-V/WinNAT의 동적 포트 제외 범위**가 그 포트를 삼켰다(2026-09-08 실측: `5368~5467`이 5433을 포함). 컨테이너 문제가 아니다 — 아무도 안 쓰는 5434로 `docker run -p`를 해도 같은 오류가 난다 | §W1 절차 |

#### §W1 — 호스트 포트를 Windows가 예약해 Docker가 게시하지 못할 때

> **먼저 진단부터.** 이 증상은 `docker ps`로는 정상으로 보인다 — `Ports` 칸이 화살표 없이
> `5432/tcp`만 나오는 것이 유일한 단서이고, 그마저 놓치기 쉽다. 그래서 판정은 도구에 맡긴다.

```powershell
# [Windows PowerShell · Phaiakes9]
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = (Resolve-Path "src\backend").Path
& src\backend\.venv\Scripts\python.exe -m whymath_backend.ops.db_host_reachability
"EXIT=$LASTEXITCODE"
```

판정(`exit 0` 도달 가능 / `1` 도달 불가 / `2` 측정 불가)과 상태별 대책이 함께 출력된다.
`NOT_PUBLISHED`(설정은 있는데 게시가 성립하지 않음)면 아래로 간다.

> **`UNKNOWN`(exit 2)은 고장 판정이 아니다.** Docker Desktop이 꺼져 있으면 `docker inspect`가
> `npipe:////./pipe/dockerDesktopLinuxEngine`에 붙지 못해 설정·실현 두 신호가 **모름**이 되고
> 도구는 3상태 규율대로 `UNKNOWN`을 낸다(2026-09-12 실측). 아래 ②단계는 Docker Desktop을
> *끈 상태*에서 도는 절차이므로 그 구간의 `UNKNOWN`은 **정상**이다 — 최종 판정은 ③에서 Docker를
> 다시 켠 뒤에 한다.

```powershell
# [Windows PowerShell · Phaiakes9] — 예약 구간에 그 포트가 있는지 확인
netsh interface ipv4 show excludedportrange protocol=tcp
```

포트를 포함하는 구간이 보이면 **영구 조치**를 한다. `winnat`을 내렸다 올리면 동적 예약이
반납되고, 그 틈에 포트를 *관리 포트 제외*로 등록하면 다음에 Hyper-V가 그 대역을 다시 잡을 때
건너뛴다(지정 예약은 동적 할당에서만 빼는 것이라 명시적 bind는 그대로 된다).

> **창**: **창 A 그대로** — 아래 블록이 UAC로 스스로 승격한다(관리자 창을 사람이 여는 단계를
> 없앴다 · 아래 「스스로 승격한다」 참조). **선행**: Docker Desktop 종료(트레이 → Quit).
> **영향**: `winnat`은 이 PC의 NAT 전반이라 내렸다 올리는 몇 초간 WSL·Docker 네트워크가 끊긴다.

```powershell
# [Windows PowerShell · Phaiakes9 · 창 A · 일반 권한에서 실행 — UAC 승인 팝업이 뜬다]
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Script = Join-Path $env:TEMP "winnat_reserve_5433.ps1"
Set-Content -Path $Script -Encoding UTF8 -Value @'
Start-Transcript -Path (Join-Path $env:TEMP "winnat_reserve_5433.log") -Force
$Admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
"IS_ADMIN=$Admin"
$Docker = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
"DOCKER_DESKTOP_RUNNING=" + [bool]$Docker
if ($Admin -and -not $Docker) {
  net stop winnat
  "STOP_EXIT=$LASTEXITCODE"
  netsh int ipv4 add excludedportrange protocol=tcp startport=5433 numberofports=1 store=persistent
  $Reserve = $LASTEXITCODE
  "RESERVE_PERSISTENT_EXIT=$Reserve"
  if ($Reserve -ne 0) {
    netsh int ipv4 add excludedportrange protocol=tcp startport=5433 numberofports=1
    "RESERVE_ACTIVE_FALLBACK_EXIT=$LASTEXITCODE"
  }
  net start winnat
  "START_EXIT=$LASTEXITCODE"
  netsh interface ipv4 show excludedportrange protocol=tcp
}
Stop-Transcript
'@
$Ready = [bool](Select-String -Path $Script -Pattern "excludedportrange" -Quiet)
"SCRIPT_READY=$Ready"
if ($Ready) { Start-Process powershell -Verb RunAs -ArgumentList "-NoExit","-ExecutionPolicy","Bypass","-File","`"$Script`"" }
```

**스스로 승격한다 (2026-09-12 실측 보강)**: 이전 판은 "관리자 권한 PowerShell 새 창을 여세요"를
산문으로 지시하고 블록은 `IS_ADMIN` 가드만 뒀다. 라이브에서 그 단계가 **생략돼** 블록이 일반
창에서 돌았고 `IS_ADMIN=False`로 **아무것도 하지 않았다** — 가드는 설계대로 작동했지만 절차는
공전했고 왕복이 1회 늘었다. 사람이 창을 여는 단계 자체가 실패 지점이므로 블록이 `-Verb RunAs`로
승격을 가져간다. `-NoExit`이라 승격된 창이 열린 채 남아 출력을 읽을 수 있고, `Start-Transcript`가
같은 내용을 `%TEMP%\winnat_reserve_5433.log`에 남긴다.

**자가검증**: 승격된 창(또는 위 로그 파일)에서 `IS_ADMIN=True` · `DOCKER_DESKTOP_RUNNING=False` ·
`STOP_EXIT`·`START_EXIT`가 0 · `RESERVE_PERSISTENT_EXIT=0` · 마지막 표에 `5433  5433  *`(관리
지정)이 보이고 그 포트를 삼키던 구간이 사라짐. 조건이 안 맞으면 스크립트는 **아무것도 하지
않는다**(의도). 창 A에서 로그만 다시 읽으려면:

```powershell
# [Windows PowerShell · Phaiakes9 · 창 A]
Get-Content (Join-Path $env:TEMP "winnat_reserve_5433.log")
```

**`store=persistent`가 핵심이다 (2026-09-12 보강)**: 이 절의 존재 이유가 "재부팅·WSL 재시작마다
재발한다"를 끝내는 것인데, `store` 없이 등록한 제외는 **active 저장소에만 들어가 재부팅에서
사라진다** — 그러면 이 절차 자체가 아래 「주의」가 경계하는 *운*과 같아진다. 이 netsh 빌드가
`store=persistent`를 받는지는 **미측정**이므로 블록이 거부(비0 종료)를 감지해 인자 없는 형태로
폴백한다. `RESERVE_ACTIVE_FALLBACK_EXIT` 줄이 출력됐다면 **영구 조치가 아니라 임시 조치**이며,
다음 재부팅 뒤 `netsh interface ipv4 show excludedportrange protocol=tcp`로 `5433`이 남아 있는지
반드시 재확인한다.

Docker Desktop 재실행 후 `docker restart whymath-pg` → 위 진단 CLI를 다시 돌려 `exit 0` 확인.

**주의 — 재시작만으로 붙는 수가 있다(그리고 그것은 해결이 아니다)**: 동적 예약은 스스로
반납되기도 해서, Docker Desktop 재기동만으로 포트가 열릴 수 있다. 2026-09-09에 실제로 그랬다.
그 상태는 **운이고 재부팅·WSL 재시작마다 재발한다** — 관리 지정 예약을 넣기 전까지 해결로
치지 않는다.

⛔ 어떤 경우에도 `docker system prune --volumes`·`docker volume prune`은 실행하지 않는다 —
prod DB 볼륨을 날릴 수 있다.

### C. Flutter / 빌드
| 증상 | 원인 | 해법 |
|---|---|---|
| `intl 0.20.2 is required ... version solving failed` | intl 좁은 핀 vs 최신 Flutter | 수정 완료(`>=0.19.0 <0.21.0`) → `git pull` |
| build_runner 실패(`retrofit_generator ... Parser`) | Flutter 최신판이 비호환 패키지 조합을 끌어옴 | **FVM 3.24.5 고정**: `fvm install 3.24.5`·`fvm use 3.24.5` 후 모든 명령에 `fvm` 접두 |
| `fvm` 용어가 인식되지 않습니다 | pub-global bin이 PATH 밖 | `$env:PATH = "$env:LOCALAPPDATA\Pub\Cache\bin;$env:PATH"` (주석 아님·실행) |
| Gradle `Unsupported class file major version` 류 | Gradle 8.3은 Java 21 미지원 | 수정 완료(Gradle 8.7 + AGP 8.3.2) → `git pull` |
| `Could not get unknown property 'flutter'` (speech_to_text) | 플러그인이 Flutter 3.27+ 전용 gradle 패턴 | 수정 완료(미사용 음성 플러그인 2종 제거) → `git pull` + `fvm flutter pub get` |
| `No supported devices connected` | ①구버전 체크아웃(android/ 부재) ②실기기 미연결 | ①`git pull` ②개발자 모드(빌드번호 7연타)→USB 디버깅→연결 팝업 승인→`fvm flutter devices` 확인 |
| 기기 목록엔 뜨는데 설치 실패(Xiaomi) | MIUI 추가 보안 | 개발자 옵션 → **"USB를 통해 설치"** 허용 + "USB 디버깅(보안 설정)" |
| compileSdk 35/NDK 버전 경고 | 플러그인 권고 | **경고일 뿐·빌드 성공** — 무시 |

### D. 실행 / 앱
| 증상 | 원인 | 해법 |
|---|---|---|
| 앱은 떴는데 "문제를 불러오지 못했어요" | ①`API_URL=` 부분 복사 유실(`--dart-define==http://`) ②방화벽 ③토큰 만료 ④**서버 재기동으로 서명 키 로테이션**(구 토큰 재사용) | ①명령 한 줄 통째 재복사 ②첫 실행 방화벽 팝업 "개인 네트워크 허용"·`ipconfig`로 LAN IP 확인 ③24h 지났으면 `run_demo.ps1` 재실행 ④`run_demo.ps1`을 재실행할 때마다 `WHYMATH_JWT_SECRET_KEY`가 매번 새 랜덤값 — **이전 실행의 토큰은 24h 안 지났어도 즉시 무효**(서명 자체가 안 맞음). 대화·터미널을 위로 스크롤해 예전 명령을 재사용하지 말고, **항상 가장 최근 `run_demo.ps1` 출력**에서 토큰을 복사 |
| 온보딩에 노랑/검정 줄무늬 | RenderFlex overflow(키보드 시) | 수정 완료(스크롤 강등) → `git pull` 재빌드 |
| "수식으로 입력"이 밋밋한 텍스트창 | MathLive ESM이 WebView file:// CORS 차단(textarea 폴백) | 수정 완료(IIFE 재번들 3단 폴백) → `git pull` 재빌드 |
| 코치가 같은 질문 반복·답변 무반영 | **설계된 S1 범위** — 학생-대면 코치는 결정론 Polya 비계(LLM 미호출·Ollama 무관) | 버그 아님. LLM 튜터링 승격은 S1-11(실측 후). 시연은 코치 2~3턴 후 풀이 제출→검증 신호로 진행 |
| "이 문제 같이 읽어볼까?"가 계속 반복(문장으로 답해도) | UNDERSTAND 단계 전이는 **자기 언어 재진술**만 인정 — 길이 20자↑ **+** 마침표·물음표·쉼표 중 1개 이상 필수(`l4/polya/transitions.py::_RESTATE_MIN_LEN`). 수식·짧은 단답은 조건 미충족 | 실제 문장으로 답한다: "주어진 건 ...이고, 구할 건 ...이야." 처럼 20자 이상 + 마침표 포함 |
| 풀이를 제출해도 **검증 카드("스스로 검산해볼까?" 등)가 안 뜸** | 카드는 "풀이 제출 자체"가 아니라 **실제 계산 오류를 감지했을 때만** 뜬다(`api/coach.py::_build_response_payload` — `solution_coaching`은 `arithmetic_error`가 True일 때만 채워짐, 정답이 맞으면 `None`이라 카드 자체가 안 뜬다). 실측: 오타로 파싱 불가한 수식(`\cdot` 등)이나 완전히 맞는 풀이는 카드 미출력 | **일부러 순수 숫자 오류를 한 줄 포함**해 제출한다 — 예: `4 / 2 = 3`(SymPy가 즉시 거짓으로 판정·`l3/pregenerate/validator.py::SymPyArithmeticValidator`). "풀이 단계" 텍스트칸에 직접 타이핑(MathLive 아님)이 가장 안정적. 뜨면: 코치 말풍선 옆에 "계산을 한 단계씩 다시 짚어보면서..." 발화 + **색이 다른 카드형 박스**("스스로 검산해볼까?") = 이게 완주 신호(게이트 ① 판정선) |

## 참조
- 전체 런북: `scripts/demo/README.md` (§A Windows 경로·함정표)
- 시연 대본: `docs/architecture/s1_e2e_demo_script.md`
- 실측 기록: `MEMORY.md` 2026-07-09~10 결정 로그
- 정리: `.\scripts\demo\stop_demo.ps1` · 게이트: `python scripts\harness\backlog.py gates clear G-kiki-device-demo --as kiki --evidence "https://..." --no-base "시연 녹화 링크 — 판정 근거가 커밋·PR이 아니라 실기기 시연 영상이다"`
