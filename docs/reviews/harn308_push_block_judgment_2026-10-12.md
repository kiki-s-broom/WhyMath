# HARN-308 판정 — 푸시 직전 고지를 차단으로 (상시 잡 미러가 없으면 푸시를 거부한다)

> 판정 기준: main `f34d7b76` (2026-10-12). 이 문서의 수치는 그 시점 main과 GitHub Actions 이력(2026-09-21 이후 PR 실행
> 916건)에서 실측했다. 구현은 같은 PR(브랜치 `claude/affectionate-heisenberg-w66ymg`)에 있고 미머지 근거는 쓰지 않았다.
> 앞선 판정 = `harn209_push_time_mirror_notice_judgment_2026-10-08.md` (고지 전용으로 시작했고, §6에 재평가 조건을 두었다).

## 1. 풀려는 문제

HARN-209 푸시 직전 고지는 "막지 않는 알림"이다. 2026-10-09 P3-03(PR #1512)에서 이것이 두 번 뚫렸다.

- 세션이 고지(미러 결과가 다른 커밋의 것 · 상시 6잡)를 보고도 푸시했다.
- 고지는 같은 (트리거·HEAD·사유)를 **한 번만** 알린다 — 재시도는 설계상 아예 침묵한다. 습관화가 아니라 구조다.
- 두 번째 푸시(`9daddd6b`)가 로컬에서 한 번도 돌리지 않은 상시 잡 `infra-contracts`(헌법 R3-01 가드)에서 red가 됐다.
- 사고 대장 `ci-local-repro-gap` 계열 9회차. 5·6회차 `HARN-173`, 7·8회차 `HARN-164`, 4회차 이후 고지 `HARN-209`.
  도구(미러)·게이트(`done`)·고지(푸시)를 차례로 세웠지만 푸시 시점에는 **막는 것이 없었다.**

## 2. 구현 (무엇을 막고, 무엇을 막지 않는가)

푸시(`git push`)만 막는다. PR 생성은 고지 전용으로 남는다 — 푸시가 이미 이 게이트를 지나왔다.

| 판정 | 조건 | 결과 |
|---|---|---|
| 허용 | 대장 기록만 바뀐 푸시(면제 A) · 브랜치 변경 없음 · 평가 대상이 아닌 푸시 형태(dry-run·삭제·태그만·`git -C`·HEAD 아닌 refspec) | 통과 |
| 허용 | 측정 불가(`unavailable`) · 훅 평가 중 예외 | 통과 — **훅 자신의 고장이 모든 푸시를 막으면 사람이 훅을 끈다.** 예외 타입명은 stderr·로그에 남는다 |
| 차단 | 미러 결과 없음 · 다른 커밋의 결과 · 형식 불량·오염(`tainted`) · 실패 · 같은 명령이 만드는 새 커밋 | 종료 코드 2 + 이유 + 다음 명령 |
| 차단 | 결과는 통과(미실행 포함·면제 B 포함)인데 **필수 상시 잡 중 돈 증거가 없는 잡**이 있음 | 종료 코드 2 (`mirror_missing_jobs`) |
| 우회 | 차단 상태 + 현재 세션 대장에 사유 있는 `push_mirror_waiver`가 이 HEAD(또는 같은 기여)에 있음 | 통과(`waived`) — 통과했다는 사실도 모델에게 알린다 |

- **필수 상시 잡** = 필터와 무관하게 매 PR에서 도는 잡 중 로컬 재현이 가능한 것 — `ci_mirror run`의 자동 선택과 같은 정본
  (`classify_jobs`)에서 읽는다. 현재 5개: `infra-contracts`·`infra-shell`·`policy-guard`·`harness-integrity`·`declared-unwired-audit`
  (`changes` 필터 계산 잡은 미러가 대신 읽으므로 제외). 경로 필터 잡(backend 등)은 요구하지 않는다 — 전체 백엔드 스위트는 한 번에 수십 분이다.
- **"돌았다"의 증거**: 결과에 그 이름의 잡이 있고 · 종료 코드 0 · 통과한 스텝이 1개 이상. 스텝이 전부 환경 전제·미실행인 기록은 돈 것이 아니다.
- **차단은 중복 억제를 따르지 않는다.** 이것이 P3-03 두 번째 푸시를 여는 열쇠였다. 로그에는 매번 남는다.
- **종료 코드 2 + stderr**: 이유는 stderr에만 간다(exit 2에서 stdout은 무시된다). 한국어 Windows(cp949)에서 깨지지 않게 **UTF-8 바이트로** 쓴다.
  `permissionDecision`·`updatedInput`은 여전히 쓰지 않는다.
- **우회**: `python3 scripts/harness/push_mirror_notice.py waive --reason '<사유>'`. 사유가 비었거나 공백뿐이면 거부(무사유 없음) ·
  이벤트 대장에 `push_mirror_waiver`를 **쓴 뒤에만** 게이트가 열린다(게이트가 대장을 읽는다) · 현재 세션(브랜치) 샤드만 읽는다 ·
  이 HEAD의 내용에만 유효(트렁크 대비 기여가 blob까지 같으면 같은 내용 — 우회한 푸시 뒤 `done` 대장 커밋이 다시 막히지 않게) ·
  지금 차단 대상이 아닌 HEAD·이미 우회된 HEAD·아직 없는 커밋에는 기록을 거부한다(쓸모없는 이벤트가 감시 신호를 흐리지 않게).
- **미리 보기**: `push_mirror_notice.py gate` — 푸시 없이 차단 여부를 본다(차단이면 종료 코드 1).

## 3. 실패 고정 (acceptance ①)

구현 전 코드에서 `tests/harness/test_push_mirror_block.py::TestP303Reproduction::test_push_with_a_stale_mirror_result_is_refused`가
`assert 0 == 2`로 RED였다 — 훅이 종료 코드 0과 `additionalContext` 고지만 내고 푸시가 진행됐다(P3-03 첫 푸시 경로 그대로).
`test_second_attempt_of_the_same_push_is_refused_again`이 두 번째 푸시 경로(중복 억제)를 고정한다.

## 4. 운영 비용 판정 (acceptance ④)

### 4-1. 비용 실측 — 상시 5잡 미러 (이 컨테이너, 4 vCPU, `--allow-empty`, 2026-10-12)

| 잡 | 소요 | 지배 스텝 |
|---|---:|---|
| `infra-contracts` | 544초 (9.1분) | `pytest tests/infra` 519초 |
| `harness-integrity` | 802초 (13.4분) | 하네스 테스트 652초 · 설치 95초 |
| `declared-unwired-audit` | 32초 | 선언≠배선 정적 감사 23초 |
| `policy-guard` | 6초 | |
| `infra-shell` | 1초 | |
| **합계 (잡이 순차 실행)** | **1,385초 (23.1분)** | 종료 코드 0 · `tainted: false` |

- 한계(정직): 측정 첫 8분 동안 같은 컨테이너에서 제 테스트·린트 실행이 겹쳤다 — 상한에 가까운 값이다. CI는 잡이 병렬이고 러너가
  더 빠르다(워크플로 주석 실측: `harness-integrity` 약 5분 · `infra-contracts` 상한 10분).
- 첫 시도는 19초 만에 실패했다 — 시스템(Debian) 패키지 PyYAML·pip를 `pip`가 지우지 못해 설치 스텝이 깨졌다.
  **이 컨테이너에서는 venv를 만들고 `--prepend-path <venv>/bin`을 줘야 미러가 돈다.** 차단 문구가 `--prepend-path`를 안내한다.

### 4-2. 효과 실측 — 상시 잡이 실제로 red가 된 빈도

GitHub Actions `ci.yml` `pull_request` 실행 916건(2026-09-21 이후 · 잘림 없음 · 서로 다른 head_branch 218개):
success 652 · cancelled 233 · failure 31. failure 31건 중 **상시 잡 red 7건**(`infra-contracts` 4 · `harness-integrity` 3 ·
나머지 3개 상시 잡 0) · backend만 red 23 · 잡 미식별 1. 상시 잡 red가 있던 브랜치는 **4개(1.8%)** — 그중 하나(`docs-p3-00a-verification`)는
문서 브랜치였다. (재실행은 최신 attempt만 보이고 이전 attempt의 failure는 세지 않았다 · head_branch와 PR은 1:1이 아닐 수 있다.)

### 4-3. 판정

단순 기대값은 불리하다: 푸시당 기대 이득 ≈ 1.8% × 약 25분(P3-03 1건 실측) ≈ **0.5분**, 비용은 코드 푸시당 최대 23분 — **약 50배**.
전량 강제를 "공짜"라고 말할 수 없다. 그럼에도 전량 요구를 유지한다. 근거 네 가지:

1. **한계 비용이 작다.** `/drive` 4단계가 이미 "`ci_mirror.py run`이 검증 범위를 대신한다"를 의무로 둔다(HARN-109·119). 따르는 세션은 이 미러를 어차피
   푸시 전에 돌리므로 이 차단이 더하는 비용은 0이다. 비용을 지는 쪽은 4단계를 건너뛴 세션뿐이고, 그것이 정확히 P3-03이다.
2. **내용당 한 번이다.** 대장 기록만 바뀐 푸시(면제 A)와 미러 뒤 같은 기여만 더한 푸시(면제 B, 우회 포함)는 추가 비용이 없다.
3. **축소안은 근거가 없다 — 안전하게 정할 수 없다.** acceptance가 제안한 "변경 경로가 닿는 상시 잡만" 축소안을 조사했다.
   상시 잡이 읽는 최상위 경로를 `tests/infra`·`tests/harness`·`scripts`·`tools`·`conftest.py`·워크플로에서 참조 파일 수로 세면
   `src/mobile` 14 · `src/web` 9 · `src/data-pipeline` 13 · `data` 192 · `docs` 155 · `infra` 104 · `scripts` 235 — **빠지는 경로가 없다.**
   "이 경로는 상시 잡이 안 읽는다"는 면제를 세울 수 없고, 세우면 원 사고 형태(EOS-24: 경로 필터에 안 닿는다고 안전하다고 읽은 것)를 그대로
   면제한다. 4-2의 문서 브랜치 red가 반례다. 한편 비용 지배 잡(`infra-contracts`·`harness-integrity`)이 곧 red가 난 잡의 전부이므로
   "싼 잡만 요구"하는 축소도 이득이 없다(싼 3잡은 합쳐 40초이고 red 0건).
4. **출구가 있다.** 로컬에서 재현할 수 없는 환경은 `waive`로 사유와 함께 통과한다 — 비용이 과한 날의 탈출구가 게이트를 끄는 것이 아니라 대장에 남는다.

**이 판정이 뒤집히는 조건(재평가)**: 이 PR 착지 후 2주 안에 (a) 코드 푸시 중 차단 비율이 30%를 넘거나 (b) 우회 이벤트가 차단의 절반을 넘으면 비용이 습관화를
부른 것이므로 잡 단위가 아니라 **스텝 단위 미러**(필요한 스텝만 재현) 또는 **병렬 미러**를 별건으로 설계한다. 임계값은 관측 전 가정이다(30%는 HARN-209 §6과 같은 값).
측정 입력 = `.claude/logs/push_mirror_notices.jsonl`(`blocked`·`gate`·`gate_code`·`missing_jobs`) + 대장의 `push_mirror_waiver` 이벤트.

## 5. 한계 (정직)

- GitHub API로 직접 커밋하는 도구(`push_files` 등)·`git -C`·`--dry-run`·HEAD 아닌 refspec은 평가하지 않아 막지도 않는다.
- 평가가 실패하면(예외) 막지 않는다 — 훅 고장이 모든 푸시를 막는 쪽이 더 나쁘다는 판정이다. 대신 예외 타입명을 stderr·로그에 남긴다.
- 필수 상시 잡 목록을 못 읽으면(`required_error`) 그 축만 건너뛴다(결과 존재·실패 축은 그대로). 상시 잡이 0건으로 읽히면 읽기 실패로 센다.
- 우회는 같은 세션이 스스로 연다 — 사람의 승인이 아니다. 막는 것은 **무사유·기록 없는 통과**이고, 남용은 위 재평가 조건(b)으로 감시한다.
- `git pull`/`merge` 뒤 푸시는 병합 결과를 미리 알 수 없어 현재 HEAD로 판정한다(HARN-209 한계 그대로).

## 6. 검증

- 신규 `tests/harness/test_push_mirror_block.py` 49건(등록된 훅 명령 문자열을 그대로 실행 · 종료 코드로 판정 · 대조군 포함) +
  기존 `test_push_mirror_notice*.py` 107건을 새 계약에 맞게 정정. 정정한 것은 옛 계약("훅은 절대 막지 않는다"·"단일 잡 결과 = 통과")을
  동결한 6건뿐이다 — 고지 JSON 형태·중복 억제·cp949는 고지 전용으로 남은 PR 생성 경로로 옮겨 검증을 잃지 않았다.
- **뮤테이션 29종 전건 RED** (훅 5 · 판정·우회·CLI 24; 적용 실재 `count==1`·`mutated != original`, 원복 sha256 동일을 하네스가 단언).
  **첫 회차에 2종이 살아남았다.** M17(우회 사유 공백 허용): 빈 문자열이 호출측 `if reason`의 거짓 판정에 가려져 같은 결과였다 — 조회 함수를
  직접 부르는 반례를 추가. M26(이미-우회 거부 제거): 뒤의 `not blocked` 거부가 같은 종료 코드를 내 메시지만 달랐다 — 거부 이유 문구를 단언.
  둘 다 "다른 절이 우연히 같은 결과를 내는" 형태였고 절을 직접 밟는 입력으로 RED를 확인했다.
- CI 명령 그대로 `ruff check scripts tests/harness tools` · `black --check --line-length 100 scripts tests/harness tools` 종료 코드 0.
