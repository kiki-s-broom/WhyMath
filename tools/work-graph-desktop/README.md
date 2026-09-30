# WhyMath 작업 지도 — 작업 그래프 데스크톱 앱 (HARN-206)

`scripts/harness/work_graph.py --json`이 낸 작업 흐름 그래프(HARN-182)를 **독립 Windows 설치형 앱**으로
보여 주는 Electron 껍데기다. 브라우저 파일(`work/graph.html`)과 달리 여러 작업공간을 등록해 두고,
저장된 스냅샷을 먼저 보여 준 뒤 새로고침으로 다시 수집하며, 착수·게이트 해소·완료를 `backlog.py` CLI로
실행하고 그 결과를 그대로 보여 준다.

## 세 원칙

| 원칙 | 뜻 | 집행 |
|---|---|---|
| **판정 무복제** | 창의 상태·연결선·해금 수·대기 경로·집계는 페이로드(`work_graph.py --json`)를 **그대로** 그린다. 앱 안에서 selector/store 판정을 다시 만들지 않는다. git worktree·GitHub PR은 별도 어댑터로 수집해 *별도 사실*로 덧붙일 뿐이다. | `tests/e2e/renderer.spec.ts` — 창 수 = nodes 수·연결선 수 = edges 수·카드 = counts·창의 `data-state` = 페이로드 state |
| **판정 불가 무은폐** | 원격 조회 3종(완료분·claim·고립) `skipped`/`error`·Python/git/gh 부재·요청 실패·24시간 넘은 스냅샷·validate 경고는 **사유가 붙은 '확인 필요'**로 카드·상태 줄에 나온다. 빈 결과를 없음으로 위장하지 않는다. | `src/renderer/app.ts` `attentionReasons()` · `tests/unit/adapters.test.ts`(missing_tool/timeout/error 각각) · e2e "확인 필요" 테스트 |
| **쓰기는 단일 창구** | 앱은 `backlog/` 파일을 읽지도 쓰지도 않는다. 착수(`start`)·게이트 해소(`gates clear --evidence`)·완료(`done --artifact`)는 확인 대화 뒤 `python scripts/harness/backlog.py …`를 셸 없이(`spawn` 인자 배열) 실행하고 exit code·stdout·stderr를 그대로 보여 준다. 메모·창 좌표·작업공간 설정은 앱 데이터 폴더에 원자적으로 저장한다. | `tests/unit/governance.test.ts`(소스 스캔) · `tests/unit/actions.test.ts`(허용 인자만·`--as` 규칙) |

## 구조

```text
tools/work-graph-desktop/
  package.json · tsconfig.json(main/preload) · tsconfig.renderer.json · electron-builder.yml · playwright.config.ts · vitest.config.ts
  scripts/build.mjs            esbuild — main·preload·renderer 세 번들 + index.html/style.css 복사
  src/shared/types.ts          메인·프리로드·렌더러 공통 계약(페이로드 형태·어댑터 결과·API)
  src/main/main.ts             Electron 메인 — BrowserWindow(contextIsolation·sandbox on) · ipcMain.handle 화이트리스트
  src/main/collect.ts          어댑터 3종 → 스냅샷
  src/main/actions.ts          backlog.py 인자 조립·실행(허용 인자만)
  src/main/adapters/           exec(spawn+타임아웃) · python(후보 탐색) · harness(work_graph.py) · git · github(gh)
  src/main/store/              atomic(tmp→rename) · settings(작업공간) · snapshots · layouts
  src/preload/preload.ts       contextBridge로 window.workGraph 노출
  src/renderer/                index.html · style.css · app.ts(껍데기) · canvas.ts(캔버스 엔진) · api.ts(픽스처 API)
  fixtures/                    make_fixture.py(축소 규칙) · sample.json(40창·scans skipped) · sample_ok.json(scans ok)
  tests/unit/                  vitest — settings·adapters·snapshots/layouts·actions·governance
  tests/e2e/                   Playwright — renderer.spec.ts(픽스처·Chromium) · electron.spec.ts(실제 앱·xvfb)
```

앱 데이터(`app.getPath('userData')` — Windows `%APPDATA%\whymath-work-graph-desktop\`):
`settings.json`(작업공간 목록) · `snapshots/<workspaceId>.json` · `layouts/<workspaceId>.json`.
환경변수 `WORK_GRAPH_USER_DATA`로 위치를, `WORK_GRAPH_WORKSPACE`로 시작 시 자동 등록할 저장소 폴더를 줄 수 있다.

## 화면

- **왼쪽 레일**: 작업공간 목록(+추가) · 보기(전체 지도 / 지금 처리할 일 / 사람 작업 / 미머지 작업 / 목록 보기) · 연결 및 설정.
- **집계 카드 8종**: 처리 가능·진행 중·선행 대기·차단·사람 작업·게이트(사람 차례/판정 미기록/선행 대기)·미머지 브랜치·**확인 필요**.
  카드 클릭 = 필터 토글. '확인 필요'는 사유 목록을 연다.
- **상태 줄**: `저장된 스냅샷 · 2026-09-29 14:50 · 원격 조회: 완료분 ok · claim ok · 고립 skipped · work_graph.py ok · git ok · gh skipped`.
  24시간을 넘으면 `24시간 초과`가 붙는다.
- **캔버스**: HARN-182 엔진 이식 — 휠/버튼 확대축소 · 배경 끌어 이동 · 창 끌어 옮기기(좌표 저장) · 프레임 · 연결선 · 미니맵 ·
  선택 시 선행/후속 사슬 강조(나머지 흐림). 상태는 색과 텍스트 라벨을 항상 함께 쓴다. 라이트/다크 자동.
- **오른쪽 상세**: 제목·상태·사유·대기 경로·선행/후속(클릭 이동)·완료 조건·노트·내 메모·원본(태스크 YAML 열기 · PR 링크 · 확인 명령 복사)·동작 버튼.
- **키보드**: `↑`/`↓` 목록 이동 · `Enter` 선택 · `Esc` 해제 · `+`/`-` 확대축소 · `0` 전체 맞춤 · `/` 검색 · `F` 선택 창으로.

## 명령

```bash
npm ci --no-audit --no-fund
npm run build            # esbuild → dist/
npm run typecheck        # tsc(main/preload) + tsc(renderer)
npm run test             # vitest (tests/unit)
npm run e2e              # Playwright renderer 프로젝트 (Chromium · 픽스처 · file://)
npm run e2e:electron     # xvfb-run 으로 실제 앱 스모크 (WORK_GRAPH_WORKSPACE 기본값 = 저장소 루트)
npm run start            # 개발 실행 (electron .)
npm run dist:win         # electron-builder --win nsis zip --publish never → release/
npm run fixture          # 저장소 루트의 work_graph.py를 실행해 fixtures/sample*.json 재생성
```

Playwright 브라우저는 환경변수 `PLAYWRIGHT_BROWSERS_PATH`의 기설치본(이 컨테이너는 `/opt/pw-browsers`,
`@playwright/test@1.56.1`과 짝)을 쓴다 — `npx playwright install`을 돌리지 않는다.

## 빌드 산출물 (리눅스 컨테이너 실측 2026-09-29)

`npm run dist:win`을 이 컨테이너(Linux · wine 없음)에서 실행한 결과는 `docs/ops/work_graph_desktop_runbook.md`
「검증」 절에 실측값(파일명·크기·exit code)이 있다. 요약:

- `release/whymath-work-graph-desktop-0.1.0-win-x64.zip` — 무설치 zip (`win-unpacked/` 통째).
- `release/whymath-work-graph-desktop-0.1.0-setup.exe` — NSIS 설치 파일(oneClick=false · perMachine=false · 설치 폴더 변경 허용).
  electron-builder 26은 리눅스에서도 NSIS를 빌드한다(내장 makensis). 실패하면 런북에 원인을 적었다.
- **아이콘은 Electron 기본 아이콘**이다. 리눅스에서 wine 없이 빌드하려고 `win.icon`을 비워 두었다 —
  Windows에서 빌드할 때 `electron-builder.yml`의 `win.icon: build/icon.ico`를 추가하면 된다.
- **코드서명 없음** — 인증서가 없다. 설치 파일 실행 시 SmartScreen 경고가 나오면 「추가 정보 → 실행」으로 진행한다.
- Windows에서 실제 설치·실행·제거는 이 컨테이너에서 확인할 수 없다 → **미검증**. Kiki 런북으로 넘긴다.

## 보안

- `contextIsolation: true` · `sandbox: true` · `nodeIntegration: false` · `webSecurity` 기본 · CSP `default-src 'self'`.
- HTTP 서버 0 · 외부 CDN·폰트 요청 0 · 새 창·페이지 이동 차단 · 외부 링크는 `shell.openExternal`(http/https만).
- IPC는 `ipcMain.handle` 화이트리스트만. 렌더러는 `workspaceId`(`ws_` + 12 hex)로만 작업공간을 가리키고 경로·명령을 넘길 수 없다.
- 시크릿 하드코딩 0. gh 인증은 사용자의 `gh auth`를 그대로 쓴다.

## 픽스처

`fixtures/sample.json`은 실제 `work_graph.py --json --no-remote` 출력을 `fixtures/make_fixture.py`의 규칙(모듈 docstring 1~7)으로
40창·26연결선·10프레임으로 줄인 것이다. `--no-remote` 출력에는 브랜치 창이 없어 **합성 브랜치 창 1개**(`synthetic: true`)를 붙였다.
`sample_ok.json`은 같은 데이터에서 scans를 ok로 바꾼 변형이다. 브라우저에서 `dist/renderer/index.html?fixture=sample` 로 열면
Electron 없이 화면을 볼 수 있다(픽스처 모드 — 명령 실행 없음). 픽스처 두 개가 렌더러 번들에 실리므로 `app.js`가 약 740KB다.

## 알려진 한계

- 원격 조회를 켜면(`remote: true`) `work_graph.py`가 GitHub·원격 브랜치를 읽으므로 네트워크와 시간이 든다(타임아웃 120초).
- `gates amend --verdict`(판정 결과 기록)는 앱이 대신 실행하지 않는다 — 상세 패널이 명령을 안내만 한다.
- Windows 실 설치·실행·제거는 미검증(런북 §검증 참조).
