# OPS-139 — 원자 백본 정본↔prod DB 패리티 프로브 (Kiki 실행 런북)

> 태스크 **`OPS-139-atom-graph-canonical-vs-prod-edge-parity-probe`**의 실행 절차다.
>
> **이 런북은 읽기 전용이다.** DB에 쓰는 블록이 하나도 없다 — 적재(쓰기)는
> `docs/ops/skb03_atom_node_populate_runbook.md` [D]가 맡고, 이 런북은 그 **전후에 정본과 DB가
> 같은지 판정**만 한다. 그래서 자가거부 가드(쓰기 블록 전용)가 없고, 블록 사이의 판정은 사람이
> 눈으로 한다(읽기 전용 블록에서는 축 ③이 유효하다 — CLAUDE.md).
>
> **선행 조건**: OPS-139 PR이 main에 병합돼야 한다. 병합 전에는 `whymath_backend.ops.
> atom_graph_prod_parity`가 체크아웃에 없어 [C]가 `No module named`로 멈춘다(그 상태가 정상
> 신호다 — 조용히 다른 값을 내지 않는다).

---

## 1. 과제 명칭

원자 백본 패리티 판정 — 정본 `data/corpus/atom_graph_v1/graph.json`과 prod DB
(`whymath-pg`의 `concept_edge`·`concept`·`atom_node`)가 같은지 읽기 전용으로 판정한다.

## 2. 목적

정본과 DB는 **서로 다른 시점에 바뀌는 두 진실**이라 어긋남이 구조적으로 재발한다. S4-60(PR #1558)이
정본 엣지를 2,210에서 2,234로 늘렸지만 prod DB는 별도 적재 동작이 있을 때까지 2,210에 머물렀고,
그 어긋남은 감시 장치가 아니라 PR 본문의 정직한 공백 항목과 Kiki의 수작업 `count(*)`로만 드러났다.
같은 계열 선례가 SKB-03이다 — `atom_node` 적재가 어느 CLI에서도 불리지 않아 prod에 한 번도
적재된 적이 없었고, 빈 테이블이 정상 동작처럼 보였다.

이 프로브가 수작업 `count(*)`를 대체한다. 결과는 **정본을 바꾼 PR(예: S4-61의 129건 병합)의 적재
완료 증적**으로 쓰인다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 기대 출력 | 소요 |
|---|---|---|---|
| A | Docker 기동 확인 + prod DB 컨테이너 도달 | `DOCKER_OK=True` | ~10초 |
| B | 실행 입력이 main과 같은지 판정 | `PATHS_MATCH_MAIN=True` | ~10초 |
| C | 환경 주입 + **패리티 프로브 실행** (읽기 전용) | `STATUS=MATCH` · `PARITY_EXIT=0` | ~10초 |

프로브가 하는 일: 정본을 적재기와 같은 규칙(양끝 개념 부재 엣지 skip·같은 쌍은 한 행·CMS 소유
쌍 제외)으로 *적재 예정* 값으로 환산하고, DB를 `docker exec psql`로 SELECT만 읽어 ①엣지 총수
②`relation_subtype`별 수 ③정본 개념의 DB 부재 수 ④`atom_node` 총수 ⑤엣지 집합 지문(sha256)을
비교한다. **총합만 비교하지 않는다** — 총합이 같아도 분포나 집합이 다르면 DRIFT다.

## 4. 성공 기준

`STATUS=MATCH` + `PARITY_EXIT=0`이면 성공이다. 출력의 `정본 출처:` 줄에 정본 경로와 `sha256=` 앞
12자가 찍힌다 — **그 값을 그대로 전달한다**(어느 정본 기준의 판정인지의 증거다).

| `PARITY_EXIT` | `STATUS` | 뜻 | 대처 |
|---|---|---|---|
| `0` | `MATCH` | 이 시점의 DB가 이 정본과 같다 | 출력 전체를 전달 |
| `1` | `DRIFT` | 어딘가 다르다 — `DIRECTION`이 방향을 말한다 | 아래 표 |
| `2` | `UNKNOWN` | **DB 값을 못 읽었다 — 일치도 불일치도 아니다** | `사유:` 줄을 그대로 전달(Docker·컨테이너·DB 이름 점검) |
| `3` | `INPUT_ERROR` | 정본을 못 읽었거나 적재 예정 엣지가 0건 | 출력 전체를 전달(DB를 건드리지 않았다) |

`DRIFT`의 `DIRECTION`:

| 방향 | 뜻 | 다음 단계 |
|---|---|---|
| `DB<정본` | 정본에 있는데 DB에 없다 — **미적재** | 적재 게이트(`skb03_atom_node_populate_runbook.md` [D])로 넘긴다. 이 런북에서 적재하지 않는다 |
| `DB>정본` | DB에 있는데 정본에 없다 — **코퍼스에 없는 잔존 행** | `DB에만 있는 엣지` 목록을 그대로 전달. 임의 삭제 금지 |
| `혼합` | 서로에게 없는 것을 둘 다 가진다 | 두 목록을 모두 전달 |
| `총합 동일·분포/집합 불일치` | 총합은 같은데 안쪽이 다르다(상쇄) | 출력 전체 전달 |

**`UNKNOWN`을 `MATCH`로 읽지 않는다.** 종료 코드가 `2`이면 "문제 없음"이 아니라 "모른다"다.

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Docker Desktop · `whymath-pg` 컨테이너 · `src\backend\.venv`
- **DB 접속 경로**: 호스트 TCP 5433이 아니라 `docker exec`다 — OPS-72 실측에서 5433이 WinNAT 포트
  제외로 닫혀도 컨테이너는 정상이었다. 그래서 `db_host_reachability`(호스트 도달성) 점검이 필요 없다.

## 6. 창 구분

**전 단계가 새 PowerShell 창 하나에서 끝난다.** 서버를 띄우지 않으므로 점유되는 창이 없다.

---

## 실행 블록

> 자리표시자가 하나도 없다. **블록 하나씩** 붙여넣고, 각 블록 끝의 판정값을 확인한 다음에만 아래
> 블록으로 넘어간다. 세 블록 모두 읽기 전용이다.

### [A] Docker + prod DB 컨테이너 도달

```powershell
# [Windows PowerShell · Phaiakes9]
cd C:\Users\kiki\Desktop\__AI\WhyMath
docker info *> $null
"DOCKER_DAEMON_UP=" + ($LASTEXITCODE -eq 0)
docker ps --filter "name=whymath-pg" --format "{{.Names}} | {{.Status}} | {{.Ports}}"
$Probe = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT 1;"
"DOCKER_OK=" + ($LASTEXITCODE -eq 0 -and $null -ne $Probe)
```

**확인**: `DOCKER_OK=True` · `docker ps` 줄에 `whymath-pg | Up …`.

`DOCKER_OK=False`면 여기서 멈추고 출력을 전달한다 — Docker Desktop 기동과 `docker start
whymath-pg`는 `skb03_atom_node_populate_runbook.md` [A]가 단계별로 안내한다.

### [B] 실행 입력 동등성 판정

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
git fetch origin main
"MAIN_SHA=" + (git rev-parse --short origin/main)
"HEAD_SHA=" + (git rev-parse --short HEAD)
git diff --quiet origin/main -- "src/backend/whymath_backend/ops/atom_graph_prod_parity.py" "src/backend/whymath_backend/l1/atom_graph" "data/corpus/atom_graph_v1/graph.json"
$PathsMatchMain = ($LASTEXITCODE -eq 0)
"PATHS_MATCH_MAIN=$PathsMatchMain"
```

**확인**: `PATHS_MATCH_MAIN=True`.

`False`면 이 체크아웃의 정본·적재기·프로브가 main과 다르다는 뜻이라 판정이 *다른 정본*을 기준으로
나온다. 여기서 멈추고 `MAIN_SHA`·`HEAD_SHA`와 함께 전달한다. 체크아웃을 옮기지 않는 이유: Kiki
클론은 여러 세션이 공유하는 단일 작업 사본이라 미커밋 변경이 상시 있을 수 있다 — 필요한 것은
"HEAD가 main인가"가 아니라 "이 프로브가 읽는 코드·정본이 main과 같은가"뿐이다.

### [C] 환경 + 패리티 프로브 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = (Resolve-Path "src\backend").Path
$Py = "src\backend\.venv\Scripts\python.exe"
"PY_OK=" + (Test-Path $Py)
& $Py -m whymath_backend.ops.atom_graph_prod_parity
"PARITY_EXIT=$LASTEXITCODE"
"JUDGED_AGAINST_MAIN=" + (git rev-parse --short origin/main)
```

**확인**: `PY_OK=True` · `STATUS=MATCH` · `PARITY_EXIT=0`.

출력 전체(특히 `정본 출처:`·`정본 적재 예정:`·`DB 실측:`·`STATUS=` 줄과 `참고:` 줄들)를 통째로
복사해 전달한다. `JUDGED_AGAINST_MAIN`은 판정 기준 커밋이다(HARN-68).

---

## 7. 이 프로브를 부르는 곳 (집행 지점)

프로브를 만드는 것과 **누가 언제 부르는가**는 다른 문제다. 배선은 두 곳이다:

1. **적재 런북의 AFTER 블록** — `docs/ops/skb03_atom_node_populate_runbook.md` [E]가 수작업
   `count(*)`에 더해 이 프로브를 부른다.
2. **정본 `graph.json`을 바꾸는 PR** — PR 템플릿(`.github/pull_request_template.md`)의 체크리스트가
   적재 후 이 프로브 `MATCH`를 **적재 완료 증적**으로 요구한다(S4-61 병합이 첫 소비자).

두 배선 모두 `tests/infra/test_atom_graph_prod_parity_wiring.py`가 동결한다(런북이 프로브를 실제로
부르는지·PR 템플릿이 증적을 요구하는지).

## 8. 이 런북이 답하지 못하는 것 (정직 고지)

- **CI는 prod DB에 닿지 못한다.** CI가 하는 일은 판정 함수 단위 테스트(전 판정 상태 주입)·뮤테이션
  검증(절 하나를 지우면 RED가 되는지)·배선 동결 테스트까지이고, **prod 실행은 이 런북으로
  Kiki 머신에서만** 일어난다. 이 세션은 prod DB에 접속하지 못했으므로 **MATCH/DRIFT의 실측값은 이
  런북을 돌려야 나온다.**
- **MATCH는 시점 증거다.** "이 실행 시점의 DB가 이 정본과 같다"이지 "앞으로도 같다"가 아니다.
  정본이 바뀌면 다시 돌려야 한다 — 자동 감시가 아니라 **정본 변경 PR의 증적 요구**가 그 장치다.
- **CMS 소유 엣지(P3-26)는 양쪽에서 제외한다.** 건수는 `참고:` 줄에 찍힌다. CMS가 만든 정당한
  관계가 "잔존 행"으로 오판되지 않게 하려는 것이며, 그 건수가 예상보다 크면 CMS 쪽을 별도로 본다.
- **DB에만 있는 개념은 판정에 쓰지 않는다**(구 개념그래프·CMS 신규 개념일 수 있다). `참고:` 줄에
  건수만 찍는다. 정본에 없는데 DB에 남은 *개념*을 잔존으로 보려면 그 건수의 출처를 먼저 가려야 한다.
- **`relation_subtype`·집합 지문 비교는 `strength` 값을 보지 않는다.** 엣지 강도만 다른 어긋남은
  이 프로브가 못 잡는다(의도적 제외 — 적재기가 재적재 때 강도를 갱신하므로 이 프로브의 목적인
  "적재 누락" 판정과 축이 다르다).
