# 코딩 헌법 이식 정본 — 무엇이 어디에 들어왔고, 어떻게 집행·검증되는가 (CONST-02)

- 판정 기준: 조사·진단 = main `b8af6f26`(2026-09-26) · 이식 착지 = main `a17e92c7` 위 브랜치 `claude/ecstatic-feynman-bxxxvd` · 작성 2026-09-28
- 원자료: Kiki 제공 꾸러미 3종(2026-09-26~27) — 「WhyMath 헌법 v1.0」(헌법 11개 조·규칙 14건·원본 9건·STAGE·개정 A0001·판례 P0001·심사 도구 3종) · 「헌법 v1.1 갱신」(규칙 81건 R5~R29 · 개정 초안 A0002 · 표준북 48장) · 「260927 EOS 통합정밀진단」(11단계 프롬프트 S00~S10 · 진단 도구 7종)
- 관련 문서: 대조표 `docs/reviews/coding_constitution_crosswalk_2026-09-27.md` · 진단 기준선 `docs/reviews/coding_diagnosis_baseline_2026-09-27.md` · Kiki 런북 `docs/ops/coding_constitution_kiki_runbook.md` · 초안 보관소 `docs/constitution_proposals/README.md` · 도구 출처 `scripts/constitution/UPSTREAM.md`

## 0. 한 줄 요약과 현재 상태

코딩 헌법을 **이식 1단계**로 설치하고, 2단계 규칙(R0-01 — AI의 헌법 수정 차단)의 집행 장치까지 착지시켰다. 헌법 파일 자체는 원본과 바이트 동일하며 AI는 고칠 수 없다. 그래서 원본 등록부 정정(A0003)과 단계 상향·A0002 채택은 **초안 + 사람 전용 채택 도우미 + 런북**으로 Kiki에게 넘겼다. 기계 검증은 CI에 배선했고(위헌 심사 래칫·파이프라인 그래프 검사·가드/설치/채택 테스트), 사람 검증은 진단 S00~S10 게이트로 남겼다.

| 층 | 무엇이 들어왔나 | 위치 |
|---|---|---|
| 헌법(사람 전용) | 헌법 본문 11개 조 · 규칙 등록부 14건 · 원본 등록부 9건 · STAGE=1 · A0001 · P0001 | `constitution/` (원본 바이트 동일) |
| 해설서 | 코딩 구조 결함 표준북 48장 + 색인 | `docs/standard-book/` |
| 심사 도구 | 위헌 심사(패치 5종)·파이프라인 검사(직접 선행 모드 추가)·규칙 병합(AI 세션 반영 거부 추가) | `scripts/constitution/` |
| 저장소 신설 도구 | 래칫·가드 자가시험·채택 도우미·진단 러너 | `scripts/constitution/` |
| 보호 장치 | PreToolUse 가드 훅 + 권한 거부 3건(루트 고정) | `.claude/hooks/guard_constitution.py` · `.claude/settings.json` |
| 파이프라인 정본 | 콘텐츠 파이프라인 28노드(헌법 제4조의 "실행 순서의 유일한 원본") | `pipeline.yaml` |
| 래칫 기준선 | 단계 1 · 차단 7건(원본 등록부 제안 경로 6 + 자리표시자 판 표기 1) | `metrics/coding_constitution_audit_baseline.json` |
| 진단 도구 | 통합정밀진단 도구 7종 벤더링(동작 불변) + 일괄 러너 | `scripts/constitution/diag/` · `run_baseline.py` |
| 개정 초안 | A0003(원본 등록부 정정)·A0002(조문 5개+규칙 81건)·헌법 본문 제안본 | `docs/constitution_proposals/` |

## 1. 세 개의 "헌법"과 서열

### 1-1. 무엇이 있나

이 저장소에는 "헌법"이라 불리는 규범이 셋이다. 이름이 같아 가장 헷갈리는 지점이므로 여기서 한 번 고정한다.

| 이름 | 파일 | 다루는 것 | 누가 고치나 |
|---|---|---|---|
| **프로젝트 헌법** | `CLAUDE.md` | 절대 금기(저작권·미성년자·교수학·AI 신뢰)·7계층 아키텍처·기술 스택·워크플로·실수 관리 | AI 세션도 고칠 수 있다(규칙 인덱스 린트 `HARN-121` 통과 조건) |
| **개발 헌법(경량판)** | `docs/standards/dev_constitution.md` | 초보자 온보딩용 요약 | AI 세션 |
| **코딩 헌법** | `constitution/` | 코딩 구조 결함 규범(흐름·진실·경계·변경·확신·회복 6축 + 교육 타당성)과 그 집행 단계 | **사람(Kiki)만** — 제9조·제11조, 가드가 기계로 막는다 |

`scripts/harness/rules.py`의 `CONSTITUTION = "CLAUDE.md"`는 **프로젝트 헌법**을 가리킨다. 코딩 헌법은 그 대상이 아니다.

### 1-2. 서열 충돌과 잠정 해석

코딩 헌법 제2조 ①은 "작업 지시·CLAUDE.md·스킬·프롬프트·관행이 헌법과 충돌하면 헌법이 우선"이라고 선언한다. 반면 `CLAUDE.md`·`AGENTS.md`·`dev_constitution.md`는 "CLAUDE.md가 최우선"이라고 선언한다. 둘 다 스스로를 맨 위에 둔다. 이 모순을 누가 어떻게 푸는지는 **Kiki의 결정**이며 게이트 `G-const-precedence-declaration`이 소유한다. 선택지는 셋이다.

1. 코딩 헌법 최상위 — CLAUDE.md는 그 아래 운영 규칙
2. CLAUDE.md 최상위 — 코딩 헌법은 코딩 규범 한정 하위 규범
3. 범위 분할 — 법령·학생 안전·아키텍처·워크플로는 CLAUDE.md, 코딩 구조 결함과 `constitution/` 보호는 코딩 헌법

**결정 전 잠정 해석(이 PR이 모든 세션에 요구하는 것)**: 두 규범이 같은 행위에 다른 답을 주면 **더 엄격한 쪽**을 따른다. 어느 쪽이 더 엄격한지 판단할 수 없거나 둘을 동시에 만족할 방법이 없으면, 코딩 헌법 제2조 ②대로 **멈추고 Kiki에게 보고**한다(충돌 조문·규칙 ID 포함). 이 해석은 두 문서 어느 쪽의 서열 선언도 위반하지 않는 유일한 읽기다 — 더 엄격한 쪽을 따르면 약한 쪽의 요구도 함께 충족되기 때문이다.

### 1-3. 대응 관계

코딩 헌법의 구성 요소는 저장소의 기존 장치와 역할이 겹친다. 이번 이식은 **합치지 않고 교차 참조만** 걸었다(통합 방향은 위 서열 결정과 묶여 있다).

| 코딩 헌법 | 저장소 기존 장치 | 관계 |
|---|---|---|
| `rules.yaml` 규칙 등록부 | `backlog/rules.ndjson`(CLAUDE.md 규칙 인덱스·HARN-121) | 서로 다른 ID·상태 어휘. 코딩 헌법 규칙은 `CONST-03~08`이 집행 장치를 착지시킬 때 rules.ndjson과 교차 링크한다 |
| `precedents/` 판례 | `backlog/incidents.ndjson` 사고 대장(HARN-118) | 사고는 대장에 적는다(CLAUDE.md 산문 동결). 코딩 헌법 판례는 Kiki가 쓴다 |
| `amendments/` 개정 기록 | `MEMORY.md` 결정 로그 | 코딩 헌법 개정은 amendments/가 정본, MEMORY는 한 줄 참조 |
| `STAGE`(이식 단계 1~6) | 백로그 스테이지 `S0~E6`(`backlog/tracks.yaml`) | **다른 축** — 이름 충돌. 이 저장소에서는 전자를 "이식 단계", 후자를 "스테이지"라고만 부른다 |
| 제10조 위헌 심사 | CI 잡들·`backlog.py` 게이트 | 위헌 심사는 래칫으로 CI `harness-integrity` 잡에서 돈다(§3) |

### 1-4. 저작 모델 — 누가 헌법을 쓰나

```text
AI 세션 ─ 정정·개정 필요 발견 → docs/constitution_proposals/ 에 초안(+근거·모의 실측)
                                      │
Kiki   ─ 초안을 읽고 고침 → adopt_amendment.py / merge_rules.py 로 반영(AI 세션에서는 --apply 거부, exit 3)
                                      │
        → 커밋·push(작성자 = Kiki) → PR → CI(래칫·설치·가드 테스트) → 머지
                                      │
AI 세션 ─ 게이트 기록(backlog.py gates clear, 판정 기준 커밋 해시 포함)
```

AI가 `constitution/`을 고치려 하면 가드가 막고, 그 거부는 **우회하지 않는다**(CLAUDE.md 「거부의 우회 금지」). 막혔을 때의 정상 경로는 위 초안 흐름이다.

## 2. 이식 단계 사다리와 실측

헌법 부록 C: "한 단계의 규칙이 모두 준수가 된 뒤 다음 단계로." 단계를 올리면 그 단계의 L4·L5 규칙이 위헌 심사의 판정 대상이 된다. 아래는 모의 사본 실측이다(`audit.py --no-run --stage N`, 2026-09-28).

| 단계 | 켜지는 것 | 설치 그대로(규칙 14) | A0003 채택 후(규칙 14) | A0003+A0002 채택 후(규칙 95) |
|---|---|---|---|---|
| 1 | 원본 등록부(R4-01) | **차단 7** | 0 | 0 |
| 2 | R0-01 헌법 보호 | 7 | **0** | 0 |
| 3 | 파트 I~VII 대부분(배선 검사 시작) | 14 | 7 | **51** |
| 4 | 관측·정적 분석 등 | 15 | 8 | 70 |
| 5 | 운영·보안 심화 | 17 | 10 | 85 |
| 6 | 공개 후 데이터 규칙(A0002 부칙) | 17 | 10 | 89 |

**단계 상향 규칙(기계 집행)**: 래칫은 기준선과 심사의 단계가 다르면 판정하지 않고 측정 실패(exit 2)로 멈춘다. 단계를 올린 사람은 `audit_ratchet.py --update-baseline`으로 기준선을 옮기는데, **새 단계에서 기준선에 없던 차단이 하나라도 생기면 거부**한다(exit 1). 즉 "현재 단계 전건 준수 후 상향"이 코드로 강제된다. 채택 도우미는 한 번에 한 칸만 올린다.

**지금의 권장 경로**: A0003 채택 + 단계 2(런북 과제 A) → A0002 채택(과제 B, 선택) → 3단계는 **파트 단위로** `CONST-03`부터 집행 장치를 착지시킨 뒤(부록 C "3단계의 규칙은 한꺼번에 켜지 말고"). 3단계 51건을 한 번에 켜면 상시 red가 되고, 사람은 상시 red인 게이트를 끈다.

**만료 지점**: 헌법 부칙 ②의 경과 조치(집행 장치 없는 규칙을 "할 일 목록"으로 삼는 것)는 2026-12-31까지 유효하다. 그때까지 도달한 단계가 12/31 내부 검증 판정의 코딩 헌법 축 입력이 된다.

## 3. 집행 장치 — 무엇이 어디서 도는가

| 대상 | 장치 | 어디서 도나 | 변별력 증거 |
|---|---|---|---|
| 헌법 보호(제9조 · R0-01) | 가드 훅(Edit·Write·MultiEdit·NotebookEdit·Bash) + 권한 거부 3건(`/constitution/**` 루트 고정) | Claude Code 세션(PreToolUse) · 자가시험은 CI `harness-integrity`(R0-01 등록 run 문자열 그대로) | 자가시험 픽스처 44건(차단 28·통과 16) · 뮤테이션(보호 폴더 이름) · cp949 콘솔 회귀 · 거부 규칙 루트 고정 회귀 |
| 헌법 보호 이중 방어 | `adopt_amendment.py`·`merge_rules.py`의 `--apply`가 AI 세션(`CLAUDECODE`)에서 exit 3 | 스크립트 자신 | 채택 도우미 테스트 12건 + 뮤테이션 8종 전건 검출 |
| 위헌 심사(제10조) | `audit_ratchet.py` — 기준선 항목 집합보다 차단이 늘면 exit 1 · 심사 불가는 exit 2 | CI `harness-integrity` | 합성 등록부 변별력 시험 14건(바꿔치기·증가 갱신 거부·단계 상향 조건 포함) |
| 실행 순서(제4조 · R1-01/R1-03) | `pipeline_check.py --require copyright,backup,curriculum_review --upstream-of publish:copyright --direct-upstream-of publish:copyright` | CI `harness-integrity` | 합성 그래프로 우회 간선·순환 주입 시 red |
| 설치 무결성 | 헌법 5종 실재·STAGE 1~6·11개 조 전건·규칙 필수 필드·표준북 색인 링크 | CI `infra-contracts`(tests/infra) | 결함 주입은 합성 항목만 사용 — 헌법 개정 PR을 막지 않는다 |
| 진단 도구 | 벤더링 7종 + `run_baseline.py`(7개 실행·NUL 검사) | CI `infra-contracts`(스모크) | 원본 도구와 출력 동일 확인(벤더링 시) |

**배선 사실**: 새 스텝 3개(래칫·파이프라인 검사·가드 자가시험)는 `.github/workflows/ci.yml`의 `harness-integrity` 잡에, 테스트 5파일(`tests/infra/test_coding_constitution_*.py`)은 `infra-contracts` 잡의 `pytest tests/infra`가 수집한다. 배선 자체는 `test_coding_constitution_audit_wiring.py`가 ci.yml을 읽어 동결한다.

**테스트가 헌법 개정을 막지 않게 한 설계**: 변별력 시험은 전부 tmp의 **합성** 헌법(규칙 1~2건·원본 1~2건)으로 잰다. 초판은 설치본의 현재 상태(단계 1·차단 7건·자리표시자 판 표기)를 전제로 짜여 있어, Kiki가 A0003을 채택하는 정상 개정 PR이 테스트 때문에 red가 될 뻔했다(2026-09-28 자기 점검 발견·수정 — 모의 사본에 A0003+단계 2+A0002를 반영한 상태에서 코딩 헌법 테스트 92건 전건 통과로 확인). 사람이 헌법을 고칠 수 없게 막는 테스트는 제11조 위반이다.

## 4. 알려진 결함과 한계 (정직 고지)

**가드의 범위**
- 가드는 **명령 문자열**을 본다. 스크립트 파일 안의 쓰기·`eval`·런타임에 조합되는 경로는 보지 못한다. 그래서 헌법에 쓰는 도구(`adopt_amendment.py`·`merge_rules.py`)에는 스크립트 쪽 이중 방어(AI 세션 거부)를 넣었다. 두 번째 층은 커밋 시점 검사 R0-02("헌법이 바뀐 커밋에는 개정 기록 동반")이며 `CONST-03`이 착지시킨다.
- Claude Code 밖의 경로(사람의 `git push`·GitHub 웹 편집·다른 AI 도구)는 가드가 닿지 않는다 — 브랜치 룰셋·CODEOWNERS 축이며 `CONST-03` 범위다.
- **Windows(Kiki PC)**: 이식 중 Windows 전용 결함 2건을 찾아 고쳤다 — ①훅 입력을 로캘 인코딩(cp949)으로 읽어 한글·`—`가 섞인 명령에서 해독 실패 → **통과(fail-open)** ②자가시험이 환경변수를 비운 채 파이썬을 띄워 Windows에서 `SYSTEMROOT` 부재로 기동 실패. ①은 회귀 테스트로 동결했다. 훅 명령이 `python3`에 의존하는 것은 저장소의 모든 훅에 공통인 조건이며, 이 PC에서 실제로 풀리는지는 런북 과제 C가 실측한다.
- 같은 stdin 인코딩 형태가 기존 `git_revert_guard.py`에도 있다 — 이식 범위 밖이라 별도 태스크로 등재했다(§7).

**심사 도구(audit.py)의 판정 논리 — 3단계 설계 입력** (꾸러미 자체 검증에서 실측, `CONST-03` 소유)
- 배선 판정이 규칙의 단계가 아니라 **전역 STAGE**에 걸려 있어, 1단계 규칙 R4-01이 STAGE=3이 되는 순간 "미연결"로 바뀐다.
- 배선 판정이 워크플로 텍스트 **부분 문자열 일치**라 주석·무관 워크플로의 문자열도 "연결됨"으로 센다. 반대로 파일 단위 `pytest tests/constitution/test_x.py` 형태의 run 35건은 이 저장소 CI가 디렉터리 단위로만 돌아 **구조적으로 미연결**이 된다.
- 검사 실행이 저장소 루트 cwd·180초 타임아웃·`shell=True` 문자열 실행이다 — 백엔드 테스트는 `src/backend`의 pytest 설정이 필요하고, 전체 유닛은 20분 이상 걸리며, Windows에서 실행기 결합이 보장되지 않는다(CLAUDE.md 「실행기 단독 호출 금지」).
- 그 결과 R4-01(원본 등록부 심사)은 래칫이 CI에서 `audit.py`를 실제로 돌리는데도, 등록된 run 문자열(`python scripts/constitution/audit.py --sources-only`)이 워크플로에 없어 3단계에서 "미연결"로 나온다. 문자열을 맞추려고 주석이나 형식적 스텝을 넣지는 않았다 — 검사기를 속이는 것이기 때문이다. 판정 논리를 고치는 것이 옳다.
- L4는 "파일 없음"엔 차단, "미배선"엔 침묵, "실패"엔 경고다(비대칭). `.pre-commit-config.yaml`이 이 저장소에 없어 배선 텍스트의 절반이 항상 비어 있다.

**정정 현황 (CONST-03 P1 · 2026-10-05 · 판정 기준: `claude/dreamy-albattani-a99dad` 브랜치 · 위 5개 결함이 코드에서 어떻게 닫혔는가)**
- ⓐ 전역 STAGE 의존 → 연결 판정은 **규칙 자신의 단계**부터다(도입된 규칙은 그 순간부터 연결돼야 한다). 도입 전 규칙은 판정하지 않고 '예정'이다.
- ⓑ 부분 문자열 → 워크플로를 YAML 로 읽어 **잡 스텝의 `run` 명령 단위**로 대조한다. 주석·`echo` 인자·step name·heredoc 본문·look-alike 경로(`.pyc`)·다른 작업 디렉터리·규칙이 CI 보다 더 구체적인 인자는 연결이 아니다. CI 가 인자를 더 붙인 것은 연결이다(규칙 토큰으로 시작하면).
- ⓒ 파일 단위 pytest → CI 가 그 파일을 품은 디렉터리를 **필터 없이** 돌면 연결이다. `-k`·`-m`·`--deselect`·`--ignore`·노드 ID(`file.py::test`)로 일부만 도는 스텝은 연결이 아니다(무엇이 걸러지는지 정적으로 알 수 없다 — 모른다 ≠ 아니다).
- ⓓ 실행 설정 → 규칙이 선택 필드 `timeout_sec`(1~1800)·`cwd`(저장소 안 상대 경로)·`shell`(true 일 때만 셸)을 줄 수 있다. 형식 오류는 심사 불가(exit 2). `python`·`python3`·`pytest` 는 지금 파이썬으로 고정하고, 셸 연산자(`&&` `|` `;` `>` `<`)가 든 `run` 은 `shell: true` 없이는 **실행하지 않는다**. **이 필드들은 아직 `constitution/rules.yaml` 머리말에 설명돼 있지 않다** — AI 가 쓸 수 없으므로 CONST-03 P4 개정 초안에 담는다.
- ⓔ L4 비대칭 → 파일 없음·미연결은 L4·L5 모두 차단, 실행 실패만 L5 차단/L4 경고.
- R4-01 은 CI 가 `audit.py` 를 직접 또는 **한 단계 래퍼의 서브프로세스**로 실행하면 연결이다(래칫 → `audit.py`). 래퍼 판정은 AST — 대입·호출 인자의 문자열이 대상 경로·파일명이고 `import subprocess` 가 있을 때만이며, docstring·주석은 세지 않는다. 정적 근사라 호출 인자까지 증명하지는 않는다.

**P1 이 바꾼 판정 (`audit.py --no-run`, 정정 전 → 후)**: 단계 2 는 차단 0 → 0(래칫 exit 0 유지). 단계 3 미리보기는 차단 51 → 52 — R4-01 미연결 → 통과(위 래퍼 판정), **R1-02·R15-01 통과 → 미연결**. 후자 둘은 옛 판정이 *거짓 통과*였다: `check` 경로(`pipeline_check.py`·`pyproject.toml`)가 워크플로 텍스트 어딘가에 있으면 연결로 셌지만 CI 는 `--downstream standards` 인자로 실행하지도, `ruff check --select T20 backend` 를 실행하지도 않는다. 이 둘은 집행 장치를 착지시키는 P2·P3 의 몫이다.

**P1 이 보지 못하는 것 (정직 고지)**: 스텝의 `if:` 조건·잡의 `needs`/경로 필터로 실제로는 안 도는 경우 · 셸 변수·`$(...)` 치환 · 파이썬 스크립트가 내부에서 다른 도구를 부르는 경우(래퍼 한 단계 외). 보지 못한 것은 '연결'로 세지 않는다.

**CONST-03 P2 — 작은 규칙 4건 (2026-10-05 · 판정 기준: `claude/dreamy-albattani-a99dad` 브랜치)**
- **R0-02** — `scripts/constitution/check_amendment.py` 신설 + CI harness-integrity 스텝(등록 run 문자열과 글자까지 동일). 실제 헌법 이력 3커밋(`09501c5f`·`8a0e4678`·`116060df`)을 대조군으로 재생해 **전건 exit 0**(정상 개정을 막지 않음)을 확인했다. 뮤테이션 14종 전건 RED(처음 1종 생존 — 분기 뒤 main 이 앞서간 픽스처 부재 — 을 테스트 추가로 닫음).
- **R1-02** — 새 도구 없이 CI 스텝만 추가(`pipeline_check.py --downstream standards`, 등록 명령 그대로). P1 이 '거짓 통과'로 드러낸 미연결을 해소한다.
- **R4-03** — `tests/infra/test_docs_numbers.py` 신설: 원자 백본 노드·엣지(2,683·2,210 → CLAUDE.md·00_overview.md)·M-id(843 → 04·04c). 스캔 0건은 실패. 뮤테이션 7종 RED. **시그니처 패턴 수는 대조하지 못한다** — 저장소에 셀 원본이 없다('55+108'은 ROADMAP 설계 수치). **rules.yaml 은 이 파일을 `tests/test_docs_numbers.py`(`pytest -q …`)로 등록**해 두어 단계 3 심사는 계속 '집행 장치 없음'이다 — 경로 정정은 P4 개정 초안의 몫이다.
- **R2-04** — `scripts/constitution/review_health.py` 신설(판정 논리 + 테스트 18건·뮤테이션 15종 RED). **한계**: 실제 검토 이벤트는 Kiki 머신에만 있어 CI 가 실데이터를 판정할 수 없다. 규칙의 단계도 rules.yaml 4 ↔ 대조표 3 으로 갈린다 — P4 에서 결정한다. 맨몸 run 은 `--events` 없이 exit 2(측정 불가)라 단계 4 에서 그대로 '실행 실패'로 판정된다는 점도 P4 에서 풀어야 한다(규칙에 `run` 인자·판정 장소 축 필요).

**CONST-03 P3 — 중간 규칙 (2026-10-06 · 판정 기준: `claude/dreamy-albattani-a99dad` 브랜치, P2 머지 `a5a30dea` 위)**

단계 3 미리보기 차단 50 → 47(`audit.py --stage 3` 실행 포함 모드에서도 R1-01·R1-03·R2-02·R2-03·R3-01 통과).

- **R1-01·R1-03** — 새 장치 없음. P1 이 CI 스텝을 YAML 명령 단위로 읽게 된 뒤 기존 `콘텐츠 파이프라인 그래프 검사` 스텝이 두 규칙의 등록 명령을 포함하는 것으로 판정돼 이미 '통과'다(CONST-02 착지분).
- **R2-03** — `tests/constitution/test_gate_schema.py`(18건). 대상은 `GateRecord`(버전 전이 게이트 기록)뿐이다: 4요건 필드 존재·생략 거부·실제 `plan_transition` 경로가 *채워서* 내는가. 필드 하나씩 뺀 모델로 검사 함수의 변별을 확인한다. `bypassed`는 어떤 경로에서도 True 가 되지 않아(제9조 ②) 필드의 존재만 지키고 우회 시의 기록은 못 본다. **`ReviewTimerEvent`(우회 필드 없음)·`ReviewQueueEntry`(판정자 없음)는 대상에서 뺐다 — '게이트 기록'에 포함할지는 Kiki 판단이다.**
- **R2-02** — `tests/constitution/test_gate_independence.py`(8건). 코드 경로 불변식: `rejected_duplicate` 후보가 `needs_review`·`rejected_gate` 와 같은 길(큐 → 검수 항목 → 검수 세션 → finished)로 판정을 받는다 · 큐 입구가 status 로 거르지 않는다 · 상태 어휘 동기(`GenerationOutcome.status` ↔ `_STATUS_PRIORITY` ↔ `ACCEPTED_STATUSES`) · 보류([s])는 종결이 아니라 재개 때 다시 제시된다. **못 막는 것: 판정되지 않고 남은 보류분의 상한** — 판례 P0001 이 정확히 이 경로였다(중복 9건을 보류해 6/15만 판정). 보류 허용 여부와 '모든 후보'의 범위(라이브 큐만인가, 결정론 배치 산출물도 포함인가)는 Kiki 정책 결정이다.
- **R3-01** — `tests/test_idempotency.py`(11건). 배치를 돌리지 않고 **'두 번 실행 테스트가 있는가'를 AST 로 전수 강제**한다: `harness/*_batch.py` 36개마다 `tests/backend/harness/test_<이름>.py` 가 있고, 한 테스트 함수가 배치 진입점(`main`·`run_*`)을 두 번 이상 부르며 `==` 단언을 갖는다(테스트 *이름*은 보지 않는다). 실측으로 36개 중 **35개가 이미 충족, 1개(`concept_content_review_batch`)가 위반**이었다 — 그 배치는 행마다 `datetime.now()`를 찍어 바이트 동일이 성립하지 않아 시계 필드(timestamp·latency_ms)를 뺀 재실행 동일성 테스트를 새로 써서 닫았다(면제 아님·`EXEMPT` 0건, 면제는 만료일을 강제). **범위 밖**: `scripts/*.py` 적재·백필 CLI 8개 · `problem_corpus_accumulate`(라이브 LLM append — 설계상 두 번 돌리면 행이 늘어난다) · populate 계열 17개 — '배치 스크립트'의 정의를 넓힐지는 Kiki 정책 결정이다.
- **R4-02 — 이번 PR 에서 하지 않았다(결정 대기)**: 규칙 전제("Python·Dart 데이터 모델은 `schemas/` 의 JSON Schema 에서 자동 생성")가 이 저장소와 다르다. `schemas/v1.1/*.yaml` 은 있으나 Python 모델(`schema/problem.py` 등)은 손으로 쓴 Pydantic 이고 생성 도구(`datamodel-codegen` 등)·`scripts/check_generated.sh` 는 없다. 통과시키려면 (가) 생성기를 도입하거나 (나) 규칙 문구를 '스키마 YAML ↔ 모델 필드 일치 검사'로 바꿔야 한다 — 헌법 개정(Kiki 채택)이 필요하다.
  - **[2026-10-06 Kiki 결정: (나)안]** 규칙 문구를 개정한다. 개정 초안 `docs/constitution_proposals/A0005_r4_02_schema_model_sync_draft.md` · 정정분 `rules_R4-02_schema_model_sync.yaml` · 집행 `tests/constitution/test_schema_model_sync.py`(CI `헌법 집행 테스트` 스텝이 이미 실행). 실측: 9개 엔티티 중 일치 2·어긋남 5(동결·만료 2026-12-31)·대응 모델 없음 2. 반영(`constitution/rules.yaml`)은 Kiki 몫이라 채택 전에는 audit 의 R4-02 가 '집행 장치 없음'으로 남는다.

배선: R2-02·R2-03 은 `ci.yml` backend 잡의 `헌법 집행 테스트` 스텝(루트에서 `pytest -q tests/constitution` — `tests/constitution` 은 backend testpaths 밖이라 전체 Pytest 스텝이 보지 못한다), R3-01 은 infra-contracts 잡의 `배치 두 번 실행 테스트 전수` 스텝(백엔드 import 0). 새 디렉터리는 해당 잡의 ruff·black 대상에도 추가했다. 뮤테이션 11종(소스 변형: 게이트 기록 필드 삭제·기본값 반전·판정자 상수화·큐 입구 중복 제외·우선순위 표 삭제·보류를 종결로 계상 등) 전건 RED, R3-01 은 가짜 트리에 위반 5종(테스트 없음·한 번만 실행·비교 단언 없음·이름만 결정론·진입점 아닌 함수)을 주입해 전건 검출했다.

**헌법 본문의 오기 (Kiki 판단 — 다음 개정 때 함께 정정 권장)**
- `CONSTITUTION.md` 머리말 "AI는 읽기만 할 수 있다 (제8조)" — AI 권한 한계는 **제9조**다.
- 표준북 부록 C 본문 "3단계의 44개 규칙" — 같은 파일의 표와 `rules_additions_v1.1.yaml` 실측은 **45건**이다.

**범위가 아직 비어 있는 것**
- `pipeline.yaml` 28노드는 콘텐츠 파이프라인만 담는다. 개인정보·학습자 상태·관측·LLM 라우팅·모바일 릴리스 노드가 없어, 그 축의 규칙이 매달릴 노드가 없다(`CONST-04`·`CONST-07`에서 결정).
- 원본 등록부에 넣을지 결정이 필요한 "정본이 두 곳 이상인 데이터" 3건(규칙 등록부·LLM 모델 핀·단원 위계)은 A0003 초안의 「판단을 Kiki에게 남긴 것」에 있다.
- 백업 등 **Kiki 머신에만 실물이 있는 규칙**(R16 계열)은 CI에서 판정할 수 없다 — 규칙에 판정 장소 축(ci / kiki-machine)이 필요하다(`CONST-07`).

## 5. 검증 계획과 완성 정의

### 5-1. 이식 1~2단계(CONST-02)의 완성 정의 — 전부 종료 코드로 판정한다

| # | 판정 | 명령 · 증거 | 주체 |
|---|---|---|---|
| ① | 위헌 심사 래칫 통과 | `python3 scripts/constitution/audit_ratchet.py` exit 0 (CI `harness-integrity`) | 기계 |
| ② | 파이프라인 그래프 통과 | `pipeline_check.py --require … --direct-upstream-of publish:copyright` exit 0 (CI) | 기계 |
| ③ | 가드 양방향 일치 | `python3 scripts/constitution/selftest_guard.py` exit 0 · 가드 테스트(뮤테이션·cp949 포함) | 기계 |
| ④ | 설치·래칫·채택·진단 테스트 | `python -m pytest tests/infra -k coding_constitution` 전건 통과 (CI `infra-contracts`) | 기계 |
| ⑤ | 원본 등록부 정정 + 단계 2 | 런북 과제 A: `audit.py` exit 0 · 래칫 기준선 단계 2·차단 0 → 게이트 `G-const-sources-registry-adopt` | Kiki |
| ⑥ | Windows 실동작 | 런북 과제 C: `HOOK_BLOCK_EXIT=2` · `SELFTEST_EXIT=0` | Kiki |
| ⑦ | 사람 축 진단 | 진단 S00~S10 → S10 통합진단서 → 게이트 `G-const-diagnosis-s00-s10-run` | Kiki |
| ⑧ | 서열 결정 | 게이트 `G-const-precedence-declaration` (3택) | Kiki |

①~④는 이 PR의 CI가 판정한다. ⑤~⑧은 사람 게이트다 — 이 PR이 머지돼도 **CONST-02가 끝나는 것은 ①~④까지**이고, ⑤~⑧은 게이트가 따로 추적한다(게이트는 `CONST-02`에 의존해 이 PR 머지 후 열린다).

### 5-2. 착지 시점 실측

- 위헌 심사(저장소 현재): 심사 23항목 · 차단 7건(원본 등록부 — 기준선과 동일) · 래칫 exit 0
- 파이프라인 검사: 28노드 · 누락·순환·섬 0 · `publish`의 직접 선행에 `copyright` 있음 · exit 0
- 가드 자가시험: 44건 전건 일치 · 가드 테스트 58건 통과 · 뮤테이션(보호 폴더명·stdin 해독) 검출
- 코딩 헌법 테스트 5파일 합계 107건 통과(가드 58 · 설치 16 · 래칫·배선 15 · 채택 12 · 진단 6)
- 채택 도우미: 테스트 12건 통과 · 뮤테이션 8종(AI 거부 제거·통째 복사·규칙 불변 단언 제거·단계 건너뛰기·중복 채택·부분수열 검사 제거·서명 누락·BOM 쓰기) 전건 검출
- 미래 상태 모의: A0003+단계 2+A0002 반영 사본에서 코딩 헌법 테스트 92건 통과 · 심사 104항목 차단 0 · 래칫 exit 0 · 순서를 뒤집어(A0002→A0003) 반영해도 규칙 95건 유지
- 진단 기준선: 도구 7종 전건 exit 0 · 결과 파일 NUL 0 (상세 `coding_diagnosis_baseline_2026-09-27.md`)

### 5-3. 3단계 이후의 완성 정의

파트별로 `python3 scripts/constitution/audit.py --no-run --stage 3` 의 차단 중 **그 파트의 규칙이 0건**이 되면 그 파트의 이식이 끝난 것이다. 전 파트가 0이 되면 STAGE=3으로 올리고(래칫이 새 차단 없음을 확인), 같은 방식으로 4단계로 간다. 파트→태스크 배정은 §7.

## 6. 용어 대응 — 같은 말, 다른 뜻

| 진단 묶음·계획서의 말 | 이 저장소의 말 | 주의 |
|---|---|---|
| "MVP 개발 종료 = 12/31" | MVP 종료 = **2026-08-30**(태그 `whymath-mvp-final-2026-08-30`) · 12/31 = **내부 검증 판정일**(Go / Conditional Go / No-Go) | `docs/strategy/eos_transition_declaration_2026-08-30.md` §0. 12/31은 전환점이 아니라 전환 후 첫 판정이다 |
| Phase 0~5 (계획서 100~600, 8/27~12/31) | ROADMAP의 Phase 0~5는 **사업 단계 축**(청사진·MVP·풀 K-12…) | 이름만 같고 다른 축 |
| Gate 0 / Gate 1 / Gate 2 (계획서) | 저장소 게이트 G0~G5는 **다른 판정**(G0 검증설계 동결·G1 계측 파이프라인·G2 앵커 콘텐츠 생산) | 계획서 쪽은 "계획서 300 Gate 2"처럼 전체 표기 |
| 헌법 | `CLAUDE.md`(프로젝트 헌법) ≠ `constitution/`(코딩 헌법) | §1-1 |
| STAGE 1~6 | 백로그 스테이지 S0~E6 | 이 저장소에서 전자는 "이식 단계" |
| eos/core · eos/adapters/math (진단 도구의 경로 가정) | `src/backend/whymath_backend/**` 안 CORE/ADAPTER 동거 · 경계 = `BOUNDARY_MAP` + import-linter 계약 | 물리 이동은 의도적으로 하지 않았다(선언 §GOAL-X). 진단 도구 경계 설정은 `scripts/constitution/diag/whymath_layers*.json` |

Kiki가 말한 "Phase 2 완료"는 진단 묶음(계획서 300) 축이다. 저장소 기록(main `a0e60965` 기준, 2026-09-28): 2026-09-03 Kiki 결정으로 계획서 300의 4주 Phase 2는 "참고 문서로 강등, 폐쇄루프는 계측기"가 됐고, 계획서 300 Gate 2는 9/19·9/24·9/25 세 번 **FAIL**로 판정됐다(10조건은 충족 — 남은 미충족 1축 = 원인 미상 오답 직후 Loop 1 보정, `EOS-26` todo). Phase 3 진입 게이트 `G-p3-entry-gate2-pass`는 pending, 3차 재판정 `EOS-141`은 todo다. "Phase 2 완료"라는 기록은 대장·MEMORY에 없다. 이 이식은 그 판정을 바꾸지 않는다 — 상세는 대조표 §5.

## 7. 후속 태스크와 게이트

| ID | 무엇 | 선행 |
|---|---|---|
| `G-const-precedence-declaration` (결정) | 세 헌법의 서열 3택 | CONST-02 |
| `G-const-sources-registry-adopt` (사람) | A0003 채택 + 단계 2 — 런북 과제 A | CONST-02 |
| `G-const-a0002-adoption` (결정) | A0002 채택 여부 — 런북 과제 B | CONST-02 |
| `G-const-diagnosis-s00-s10-run` (사람) | 진단 S00~S10 — 런북 과제 D | CONST-02 |
| `CONST-03` | 3단계 파트 I(1~4장)+R0 — R0-02 커밋 시점 검사·Stop 훅 심사·audit 판정 논리 개선(§4) | CONST-02 · 원본 등록부 게이트 |
| `CONST-04` | 파트 II(5~8·28장) 경계·계약·상태·비밀값 | CONST-03 · A0002 게이트 |
| `CONST-05` | 파트 III(9~11장) 커밋 규율·마이그레이션·래칫 | CONST-03 · A0002 게이트 |
| `CONST-06` | 파트 IV(12~14장) 테스트 구조·검증 독립·정적 분석 | CONST-03 · A0002 게이트 |
| `CONST-07` | 파트 V·VI(15~19장) 관측·백업·회고·AI 작업 단위·사람 검토 | CONST-03 · A0002 게이트 |
| `CONST-08` | 파트 VII(20~29장) 교육앱 특화 | CONST-03 · A0002 게이트 |
| `CONST-09` (우선순위 1) | 학생 입력 CAS 파싱 안전 진입점 — `9^9^9` 서버 정지(진단 BL-004 · R22-03) | — |
| `CONST-10` | 기존 `git_revert_guard.py`의 stdin 로캘 해독(fail-open) — 이식 중 발견 | — |

규칙 95건 각각의 저장소 대응·판정·배정 태스크는 대조표 §3에 있다.
