# S1 실기기 학습 루프 시연 — 따라하기 런북 (Phaiakes9)

> **목적**: S1 탈출 게이트 ①(`G-kiki-device-demo` — "실기기(패드)에서 1루프 15분 완주 시연 녹화")을
> Kiki가 그대로 따라 하며 촬영할 수 있게, 녹화 전 하드 블로커 3종(인증·API_URL·LLM 키)을 원커맨드로
> 해소하는 인에이블먼트 킷 사용법이다. 호스트 OS별로 **Windows(PowerShell)** 경로(§A)와
> **리눅스/WSL**(bash) 경로(§B)를 모두 제공한다. Kiki의 Phaiakes9(라이젠 AI Max+ 395)가
> Windows면 §A를 따르면 된다.
>
> **경계**: 이 킷은 녹화를 *turnkey*로 만들 뿐 **게이트를 clear하지 않는다** — 게이트는 Kiki가 실기기
> 15분 루프를 *녹화*할 때까지 PENDING이다. 대본은 `docs/architecture/s1_e2e_demo_script.md`.

---

## 큰 그림

```
[Phaiakes9]  run_demo.sh  →  PG + 서버 기동 + 데모 토큰 발급  →  "flutter run ..." 명령 출력
     │                                                                       │
     └──────────────────── 같은 WiFi(LAN) ─────────────────────────────────┘
                                      │
                               [패드(실기기)]  그 명령으로 앱 실행 → 인증된 채 부팅 → 15분 루프 녹화
```

핵심: **Phaiakes9와 패드가 같은 WiFi**에 있어야 하고, 패드는 Phaiakes9의 **LAN IP**로 접속한다(localhost 아님).

---

# §A. Windows(PowerShell) 경로 — 이 PC가 Phaiakes9인 경우 (권장)

## A-0. 전제 (한 번 확인)

```powershell
docker version                              # Docker Desktop 실행 중이어야 함(고래 아이콘)
Invoke-RestMethod http://localhost:11434/api/tags   # Ollama for Windows 가동 → 코치 라이브(없어도 루프 완주)
python --version                            # conda base가 3.12.x면 그대로 사용(아래 A-1은 python -m venv)
```
> `docker`가 PowerShell에서 안 되면 Docker Desktop이 꺼졌거나 WSL 전용 상태 — **PowerShell(네이티브)** 에서 실행하세요.

## A-1. 브랜치 + 백엔드 venv (최초 1회, 리포 루트에서)

conda base가 이미 Python 3.12.x면 **`python -m venv`** 로 만드는 게 가장 확실하다(별도 uv 설치·PATH 불필요):
```powershell
git fetch origin claude/g-kiki-device-demo-fv831n
git checkout claude/g-kiki-device-demo-fv831n

cd src\backend
python -m venv .venv                # base가 3.12 → 3.12 venv (uv 불필요)
.\.venv\Scripts\Activate.ps1        # ← 리눅스 'source .venv/bin/activate' 대응(Scripts, bin 아님)
pip install -e ".[dev]"
cd ..\..
```
> - `Activate.ps1`에서 "스크립트를 실행할 수 없습니다" 오류 → 먼저 `Set-ExecutionPolicy -Scope Process -Bypass` 후 재시도.
> - base가 3.12가 아니면 uv 사용: `pip install uv` 후 `python -m uv venv --python 3.12 .venv`(또는 `uv`가
>   PATH에 있으면 `uv venv --python 3.12 .venv`). uv는 3.12를 자동 내려받는다.

## A-2. 원커맨드 기동 (리포 루트에서)

```powershell
.\scripts\demo\run_demo.ps1
```
- 자동으로: PG(pgvector) → alembic → 문제 시드 → uvicorn(`0.0.0.0:8000`·백그라운드) → 데모 토큰 발급 →
  LAN IP·LLM 모드 + **패드에서 칠 `flutter run …` 명령** 출력. (venv는 스크립트가 자동 결선하지만 A-1 설치는 필수.)
- **처음 실행 시 Windows 방화벽 팝업**이 뜨면 Python에 **개인 네트워크 허용**(패드가 8000 포트로 붙게).
- 출력된 `flutter run …` 명령을 복사. 이 창은 서버가 백그라운드로 도는 동안 그대로 둡니다.

## A-3. 패드에서 앱 실행 (⚠️ FVM으로 Flutter 3.24.5 고정 필수)

이 프로젝트는 **Flutter 3.24.5**에 고정돼 있다(CI·`src/mobile/.fvmrc`). 최신 Flutter로 빌드하면
호환 안 되는 패키지(예: `retrofit_generator` ↔ `retrofit`)가 풀려 **build_runner가 실패**한다.
FVM으로 프로젝트만 3.24.5를 쓰게 한다(전역 Flutter는 안 건드림).

**전제: Android SDK** — 안드로이드 빌드에는 Android SDK가 필요하다. 없으면
[Android Studio](https://developer.android.com/studio) 설치(SDK 포함) 후:
```powershell
fvm flutter doctor                      # "Android toolchain"에 ✓ 떠야 함
fvm flutter doctor --android-licenses   # 라이선스 미동의 표시가 있으면 실행해 전부 y
```

**먼저 실기기(안드로이드)를 PC에 인식시킨다** — 연결 없이는 `flutter run`이
"No supported devices connected"로 거부한다(이 프로젝트는 android 전용 스캐폴딩이라
Windows/Chrome 데스크톱 타깃이 안 뜨는 것은 정상):

1. 기기에서 **설정 → 휴대전화(태블릿) 정보 → 소프트웨어 정보 → 빌드번호 7번 연타** → 개발자 모드 on
2. **설정 → 개발자 옵션 → USB 디버깅** on
3. USB 케이블로 PC에 연결 → 기기 화면의 **"USB 디버깅 허용?" 팝업 승인**
4. `fvm flutter devices` 로 기기가 목록에 뜨는지 확인 후 아래 진행

> 안드로이드 폰으로 루프를 먼저 검증해도 된다(코드 검증 목적). 단 **탈출 게이트 ① 정본 녹화는
> 패드(태블릿)** 기준. ⚠️ **아이패드는 Windows에서 빌드/설치 불가**(iOS 빌드는 macOS 전용) —
> 안드로이드 태블릿을 쓴다.

기기를 이 PC와 **같은 WiFi**에 두고 연결한 뒤:
```powershell
# FVM 설치(최초 1회) — dart는 Flutter에 포함(flutter가 되면 dart도 됨)
dart pub global activate fvm

# ⚠️ 반드시 실행(주석 아님!) — fvm 설치 직후 뜨는 경고("not on your path")를 그대로 해소한다.
# 이 줄을 건너뛰면 바로 다음 'fvm install'부터 "'fvm' 용어가 인식되지 않습니다" 오류가 난다.
# 세션 한정(이 PowerShell 창에서만 유효) — 새 창을 열면 다시 실행해야 한다.
$env:PATH = "$env:LOCALAPPDATA\Pub\Cache\bin;$env:PATH"
fvm --version   # 여기서 버전이 찍혀야 다음 단계로 진행(안 찍히면 위 PATH 줄을 다시 확인)

cd src\mobile
fvm install 3.24.5      # .fvmrc의 3.24.5 다운로드(최초 1회)
fvm use 3.24.5          # 프로젝트에 3.24.5 연결(.fvm/ 생성)

fvm flutter pub get
fvm dart run build_runner build --delete-conflicting-outputs   # ⚠️ 필수 — .g.dart 생성
# A-2에서 복사한 명령을 그대로(fvm 접두). ⚠️ 명령 전체를 한 번에 복사할 것 —
# 부분 복사로 `API_URL=`이 유실되면(`--dart-define==http://…`) 앱이 localhost로 부팅돼 서버에 안 붙는다.
fvm flutter run --dart-define=API_URL=http://<이 PC LAN IP>:8000 --dart-define=DEMO_TOKEN=<토큰>
```
> 이후로는 `src\mobile`에서 Flutter/Dart 명령 앞에 항상 **`fvm`** 을 붙인다(`fvm flutter …`·`fvm dart …`).
>
> **매번 새 창마다 PATH를 다시 치기 싫으면(영구 등록)**: 설정 → 시스템 → 정보 → 고급 시스템 설정 →
> 환경 변수 → 사용자 변수의 `Path`에 `%LOCALAPPDATA%\Pub\Cache\bin`을 추가(재부팅/새 터미널부터 적용).
> 또는 PowerShell에서: `[Environment]::SetEnvironmentVariable('Path', "$env:Path;$env:LOCALAPPDATA\Pub\Cache\bin", 'User')`.

## A-4. 녹화 → 정리 → 게이트 clear

- **④ 15분 루프 녹화**: 아래 §공통 "15분 루프 녹화" 표를 따른다(OS 무관).
- **정리·게이트 clear**:
```powershell
.\scripts\demo\stop_demo.ps1
# 녹화가 끝난 *뒤에만* 실행. <>는 치지 말고 실제 링크를 따옴표로 감싼다(PowerShell은 < 를 예약어로 거부).
# --no-base 는 필수다: 이 게이트의 근거는 영상 링크라 HARN-68 의 커밋·PR 기준 검사를 구조적으로
# 통과할 수 없다(빼면 clear 가 exit 1 로 거부된다).
python scripts\harness\backlog.py gates clear G-kiki-device-demo --as kiki --evidence "https://실제-녹화-링크" --no-base "시연 녹화 링크 — 판정 근거가 커밋·PR이 아니라 실기기 시연 영상이다"
```

## A-*. Windows 함정

| 증상 | 원인·해결 |
|---|---|
| `uv` not found | uv가 Python3.13 사용자 폴더에 깔려 PATH에 없음. **uv 대신 `python -m venv`** 사용(A-1·base가 3.12면 uv 불필요). |
| `alembic`/`uvicorn` not found | 백엔드 venv 미설치(A-1) 또는 스크립트가 venv를 못 찾음(`src\backend\.venv\Scripts`). |
| `alembic upgrade` 시 `UnicodeDecodeError: 'cp949' codec ...` | 구버전 체크아웃. Alembic이 `alembic.ini`를 OS 로케일(한국어 Windows=cp949)로 읽어 UTF-8 한글 주석을 못 읽던 버그 — `alembic.ini`를 ASCII로 고쳐 해결됨. `git pull`로 최신 받기. |
| `docker` not found | Docker Desktop 미실행 or WSL 전용. **PowerShell**에서 실행. |
| `docker compose` 시 `port is already allocated`(5432) | PC에 이미 로컬 PostgreSQL(서비스·다른 프로젝트)이 5432를 쓰고 있음. 데모는 **호스트 55432**로 고정돼 있어(`docker-compose.demo.yml`) 최신 버전을 받으면 재발하지 않는다(`git pull`). 그래도 나면: `docker compose -f docker-compose.demo.yml down` 후 재시도. |
| `alembic upgrade` 시 `ConnectionError: unexpected connection_lost()` | Windows에서 asyncpg의 SSL 협상 단계가 깨지는 알려진 문제. 데모 URL에 **`?ssl=disable`** 이 고정돼 있고, 같은 창에 남은 이전 실행의 `WHYMATH_DATABASE_URL` 잔재도 **항상 덮어써서** 재발하지 않는다(`git pull` 후 재실행). 데모 아닌 DB를 쓰려면 전용 `WHYMATH_DEMO_DATABASE_URL`로 지정. |
| `Activate.ps1` 차단 | `Set-ExecutionPolicy -Scope Process -Bypass` 후 재시도. |
| **build_runner 실패**(`retrofit_generator ... Parser` 등) | Flutter가 3.24.5보다 최신이라 비호환 패키지 조합. **FVM으로 3.24.5 고정**(A-3)·이후 `fvm flutter`/`fvm dart`로 실행. |
| Gradle 빌드 실패: `Could not get unknown property 'flutter'`(speech_to_text) | 구버전 체크아웃. speech_to_text 7.4.0이 Flutter 3.27+ 전용 gradle 패턴을 써서 3.24.5에서 빌드 불가 — 미사용 음성 패키지 2종(speech_to_text·flutter_tts)을 pubspec에서 제거해 해결됨. `git pull` 후 `fvm flutter pub get` 재실행. |
| `fvm` not found | `dart pub global activate fvm` 후 pub-global bin 미등록. `$env:PATH = "$env:LOCALAPPDATA\Pub\Cache\bin;$env:PATH"`. |
| `No supported devices connected` | 실기기 미연결 **또는 구버전 체크아웃(android/ 스캐폴딩 이전)**. `git pull` 후 A-3 기기 연결 4단계(개발자 모드→USB 디버깅→연결·팝업 승인→`fvm flutter devices`) 수행. Windows/Chrome/Edge가 "not supported"로 뜨는 건 정상(android 전용). |
| 기기는 목록에 뜨는데 설치가 안 됨(Xiaomi/샤오미) | MIUI는 추가로 **개발자 옵션 → "USB를 통해 설치" 허용**(Mi 계정 로그인 요구될 수 있음)과 **"USB 디버깅(보안 설정)"** 을 켜야 apk 설치가 진행된다. |
| 앱은 떴는데 "문제를 불러오지 못했어요" | `flutter run` 인자에서 `API_URL=`이 유실됐을 가능성(`--dart-define==http://…`) — 앱이 localhost 기본값으로 부팅됨. A-2 출력 명령을 **한 줄 통째로** 다시 복사해 실행. 방화벽·LAN IP도 확인. |
| 어제 발급한 토큰으로 401 | 데모 토큰 만료는 **24시간**. 날이 바뀌었으면 `.\scripts\demo\run_demo.ps1` 재실행으로 새 토큰 발급(출력 명령의 토큰으로 교체). |
| 패드에서 서버 못 붙음 | 첫 실행 방화벽 팝업에서 **개인 네트워크 허용**·API_URL이 이 PC Wi-Fi LAN IP인지 확인(`ipconfig`). |
| 코치 발문이 밋밋 | Ollama for Windows 미가동. Ollama 앱 실행/`ollama serve` 후 재시도(`/status`가 라이브로 바뀜). |

> **재부팅 후 서버 기동 + shadow verdict 수집**(시연 아닌 개발·측정 목적)은 별도 런북
> `infra/phaiakes9/POST_REBOOT_SERVER_SHADOW.md` 참조 — 데모 DB + INFO 로깅 런처 + shadow 배치.

---

# §B. 리눅스/WSL 경로 (bash)

## ⓪ 사전 확인 (호스트에서, 1분)

```bash
# (a) 라이브 Ollama 살아있나 — 코치 발문 품질의 전제(없어도 루프는 결정론으로 완주)
curl -s localhost:11434/api/tags | head -c 200      # 모델 목록이 나오면 OK

# (b) 도커·파이썬
docker compose version && python3.12 --version

# (c) Phaiakes9의 LAN IP(패드가 붙을 주소) — 첫 번째 값을 기억
hostname -I | awk '{print $1}'
```

> Ollama가 안 뜨면 `docs/strategy/live_cost_measurement_2026-07.md`의 개통 절차로 먼저 살린다.
> 안 살려도 루프 완주엔 지장 없다(코치 발문만 결정론 degraded로 밋밋).

---

## ① 브랜치 + 백엔드 세팅 (최초 1회, 리포 루트에서)

```bash
git fetch origin claude/g-kiki-device-demo-fv831n
git checkout claude/g-kiki-device-demo-fv831n

cd src/backend
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
cd ../..                       # 리포 루트로 복귀
```

---

## ② 원커맨드 기동 (venv 켠 상태로, 리포 루트에서)

```bash
source src/backend/.venv/bin/activate     # 아직 안 켰다면
bash scripts/demo/run_demo.sh
```

`run_demo.sh`가 자동으로 하는 6단계(= 블로커 3종 해소):

1. throwaway Postgres(`pgvector/pgvector:pg16`) 기동 + health 대기
2. `alembic upgrade head` — DB 스키마 생성
3. `seed_demo.py` — 진단 문제 적재 (`문제 적재 완료: N건` 출력)
4. `uvicorn`을 `0.0.0.0:8000`으로 백그라운드 기동 (패드가 LAN으로 접속)
5. `POST /v1/auth/demo/callback` — **데모 토큰 자동 발급** (데모 사용자 lazy upsert)
6. LAN IP·LLM 모드 출력 + **패드에서 칠 명령** 인쇄

**성공 시 마지막 상자**:
```
════════════════════════════════════════════════════════════
 flutter run \
   --dart-define=API_URL=http://<Phaiakes9 LAN IP>:8000 \
   --dart-define=DEMO_TOKEN=<긴 토큰>
════════════════════════════════════════════════════════════
```
- 이 `flutter run …` 명령을 **복사**한다.
- `LLM 모드: 라이브(Ollama)`로 뜨는지 확인(라이브면 코치 품질 최상).
- **이 터미널은 켜 둔 채로** 둔다(서버가 여기서 돈다). 새 터미널에서 다음 단계 진행.

---

## ③ 패드(실기기)에서 앱 실행

패드를 Phaiakes9와 **같은 WiFi**에 두고 USB 연결(또는 무선 디버깅).

```bash
cd src/mobile
flutter pub get
dart run build_runner build --delete-conflicting-outputs   # ⚠️ 필수 — .g.dart 생성(안 하면 컴파일 실패)
# ②에서 복사한 명령 그대로:
flutter run --dart-define=API_URL=http://<Phaiakes9 LAN IP>:8000 --dart-define=DEMO_TOKEN=<토큰>
```

앱이 **로그인 화면 없이 인증된 채 부팅** → 라우터가 자동으로 `/problem`("오늘의 문제")로 보낸다.

---

## ④ 15분 루프 녹화

패드 화면 녹화를 켜고, 고3 학생 1명이 되어 6단계를 완주한다:

| # | 단계 | 학생 조작 | 완주 신호 |
|---|---|---|---|
| ① | **온보딩** (~2분) | 철학 3페이지 스와이프 + 목표폼 → "시작하기"(또는 "건너뛰기") | `/problem` 도착 |
| ② | **진단** (~1~2분) | 조작 없음(자동 로드) | 문제 카드 렌더 |
| ③ | **문제제시** (~1분) | 발문 읽고 → **"풀이 시작"** | 채팅 화면 도착 |
| ④ | **풀이입력** (~2~3분) | 하단 **"풀이 단계"** 토글 → 입력 → **"풀이 확인"** (또는 "수식으로 입력" MathLive) | 학생 버블 표시 |
| ⑤ | **코치 멀티턴** (~5~6분·최대 병목) | 코치 발문 읽고 후속 발화 → 보내기 **2~3턴만** | 코치 버블 + 소크라테스 배지 누적 |
| ⑥ | **검증 신호** (즉시) | 없음(자동) | **CoachSignalCard**: "N단계 중 M단계 확인" 등 |

**완주 판정**: 온보딩 후 문제 카드 → "풀이 시작" → 풀이 전송 → 코치 버블 → 그 아래 CoachSignalCard
검증 신호가 뜨면 **1루프 완주**. (상세: `docs/architecture/s1_e2e_demo_script.md`)

> 팁: 코치 턴이 시간을 좌우 → **2~3턴으로 제한**. 문제 카드 1회 사전 워밍업으로 콜드스타트 대비.

---

## ⑤ 정리 & 게이트 clear

```bash
bash scripts/demo/stop_demo.sh     # uvicorn 종료 + throwaway PG(볼륨째) 제거
# 녹화 증적(링크)을 걸어 게이트 clear:
# 녹화가 끝난 뒤에만 실행 — 실제 링크를 따옴표로 감싼다.
# --no-base 는 필수다: 영상 링크는 HARN-68 의 커밋·PR 기준 검사를 통과할 수 없다.
python3 scripts/harness/backlog.py gates clear G-kiki-device-demo --as kiki --evidence "https://실제-녹화-링크" --no-base "시연 녹화 링크 — 판정 근거가 커밋·PR이 아니라 실기기 시연 영상이다"
```
게이트가 clear되면 `S1-14-exit-gate-judgement`(owner=kiki)로 3종 게이트 판정을 기록해 S1을 공식 탈출한다.

---

## 문제 해결 (함정표)

| 증상 | 원인·해결 |
|---|---|
| 패드에서 "문제를 불러오지 못했어요" | API_URL이 **Phaiakes9 LAN IP**인지(localhost 아님)·방화벽 8000 포트 확인. Phaiakes9에서 `curl http://<LAN_IP>:8000/health`가 `{"status":"ok"}`면 서버는 정상. |
| `flutter run` 컴파일 에러 | `dart run build_runner build --delete-conflicting-outputs` 안 돌림(③ 재실행). `.g.dart`는 리포 미커밋 생성물. |
| `CREATE EXTENSION vector` 실패 | compose 이미지가 `pgvector/pgvector:pg16`인지 확인(순정 postgres:16은 실패). |
| 코치 발문이 밋밋(canned) | LLM/Ollama 없음(degraded). 루프 완주엔 무방. Ollama 살리거나 Phaiakes9에서 실행하면 라이브. |
| `alembic`/`uvicorn` not found | venv 미활성. `source src/backend/.venv/bin/activate` 후 재실행. |

---

## 보안 주의

- `WHYMATH_DEMO_AUTH_ENABLED=true`는 **로컬 시연 호스트(Phaiakes9)에서만** 켠다. 이 플래그가 켜지면
  `/v1/auth/demo/callback`이 신원 검증 없이 데모 계정 토큰을 발급하므로 **prod/공개 배포에서 절대 금지**.
- 킷은 기본 OFF·실 provider(kakao/naver) 구성 시 등록 거부(이중 방어)·JWT 시크릿 매 실행 런타임 생성.
