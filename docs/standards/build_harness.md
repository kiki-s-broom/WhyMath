# 빌드 하네스 (Build Harness) — 작업일정 관리·순차 조율 표준

> **정본**: `backlog/` + `scripts/harness/` | **채택**: 2026-07-08 결정로그 | **버전**: 1.6 (2026-09-22 HARN-124 — `gates amend` 신설: 등재된 게이트의 **제목·독촉 주기 정정 경로**. 종전에는 `--title`·`--remind-after-days`가 `add` 전용이라 틀린 게이트 문면을 고칠 CLI가 0이었고(손편집 금지), 그 제목은 매 세션 브리핑에 노출돼 그대로 틀린 조작을 부른다. 실효값 덮어쓰기 + 옛 값 `corrections[]` append이며 status는 건드리지 않는다(waive와 구분 — waive는 대기 태스크를 해금한다). §7a 표 2행·치트시트 추가. 이전 1.5: 2026-09-11 HARN-92 — `gates show <id>` 신설: 사람에게 게이트를 서술할 때 title(등재 시점 질문·append 전용이라 미갱신)만 인용해 이미 뒤집힌 결정을 재안내하던 사고 재발방지. status별 근거(cleared→evidence, waived→notes, pending→"없음")를 title보다 먼저 전문 출력. 이전 1.4: 2026-09-07 HARN-74 — gates clear·waive 직후 부착 blocked 태스크·산문 참조 출력 + brief/status의 '해소된 게이트를 기다리는 blocked' 줄 · §3d 절 추가. 이전 1.3: 2026-09-07 HARN-67 — amend 정정 경로 3축(depends 제거·gate 탈착·notes 치환)·취소 선행 판정 규칙·§7a 정정 경로 표. 이전 1.2: 2026-08-10 통합점검 — gates add 반영·테스트 수 실측 정정. 1.1 이후 §4 삭제 403 런북(2026-08-06 HARN-16)이 버전 표기 없이 추가돼 있었다)
>
> 이 문서의 "빌드 하네스"는 프로젝트 *구축을 관리하는* 레이어다.
> `src/backend`의 WH-1(튜터링)·WH-S(솔버)는 **제품 런타임 하네스**로 완전히 별개다.

---

## 1. 무엇이 바뀌었나 (구 하네스 → 신 하네스)

| | 구 (2026-07-08 이전) | 신 |
|---|---|---|
| 작업일정 | 사람이 편집하는 마크다운에 분산 (stale) | `backlog/` 기계가독 단일 진실 원천 |
| 다음 작업 | 세션마다 사람이 지시·Claude가 재추론 | `next`가 결정적으로 계산 |
| 세션 시작 | 수동 `/status` | SessionStart 훅이 브리핑 자동 주입 |
| 상태 갱신 | 자율 (자주 누락) | Stop 훅이 미갱신 종료 차단 |
| 사람 대기 | ROADMAP 산문에 묻힘 | `gates.yaml` 대장 + 경과일 리마인드 |
| 순차 진행 | 없음 | `/drive` 주도 모드 루프 |
| 과목 범위 | 수학 암묵 | 다과목 개방 스키마 (E축: 물리~영어, 지구과학 배치 결정 대기) |

## 2. 단일 진실 원천 — `backlog/`

```
backlog/tracks.yaml           트랙 3종 + stage_order (S0~S5 → E1~E6)
backlog/gates.yaml            사람 게이트 대장 (Kiki 수동 대기 추적)
backlog/tasks/<id>.yaml       태스크당 1파일 — 병렬 세션 충돌 원천 차단
backlog/events/<actor>.ndjson append-only 감사 로그 — **세션(=브랜치)당 1샤드** (HARN-46)
backlog/events.ndjson         레거시 단일 대장 — 읽기 전용 역사 (신규 기록 없음)
backlog/policy.yaml           조율 정책 — 겹침·ad-hoc 감지 강제 수준 (off|warn|block)
```

> **이벤트 샤딩 경위(HARN-46 · 2026-08-31)**: 원래 단일 `events.ndjson`에 모든 세션이
> append하고 `merge=union`이 충돌을 흡수한다고 믿었다. 그러나 union은 **로컬 git에서만**
> 작동하고 **GitHub의 mergeability 판정은 저장소 merge driver를 적용하지 않는다** — 그래서
> main에 어떤 PR이 착지하든 이 파일을 만진 열린 PR은 전부 충돌(dirty)이 됐다(PR #931이
> CI green 4회를 확보하고도 머지가 반복 지연된 실측 사고 —
> `docs/reviews/pr931_merge_block_root_cause_2026-08-31.md`). 대책은 tasks/의
> 태스크당-1파일과 동형: **세션당 1샤드**로 나눠 두 브랜치가 같은 파일을 동시에 append하는
> 상황 자체를 없앤다. 소비자는 반드시 `store.event_paths()`(레거시+샤드 합집합)로 읽는다 —
> 한쪽만 읽으면 무손실이 아니다. 계약 동결 = `tests/harness/test_event_ledger_sharding.py`.

- **태스크 상태는 CLI로만 변경한다**: `python3 scripts/harness/backlog.py <cmd>`.
  직접 편집하면 PostToolUse 훅이 무결성을 검증한다 (깨지면 차단).
- ROADMAP.md·MEMORY.md는 **서사(왜)** 담당으로 존속 — 수치·순서·다음 작업의 정본은 backlog다.
- 병렬 세션: 태스크당 1파일 + `session` claim 필드 + **이벤트 세션 샤드**로
  "1 세션 = 1 도메인 = 1 브랜치 = 1 태스크"가 파일 수준에서 강제된다
  (`docs/standards/parallel_sessions.md` 연계).
- **태스크 `paths` 필드 (v1.1)**: 태스크가 만질 파일 범위를 glob으로 선언한다
  (예: `src/backend/api/**`). `start` 프리플라이트·check-edit 훅이 이 선언으로
  **교집합 작업**을 사전 감지한다. 디렉토리는 `src/backend/` 또는
  `src/backend/**` 형태로 — 와일드카드 없는 리터럴은 단일 파일로 해석된다.
  기존 태스크의 paths 부재는 위반이 아니나, 신규 태스크는 `add --path` 선언을 관례화한다.
- **태스크 `eos_priority` 필드 (v1.2 · HARN-55)**: EOS 12월 검증 등급 `P0|P1|P2|P3`.
  계획서 100의 Rule 1·3·4를 **CLI 거부**로 집행하는 축이며, 산문 규칙이 집행 지점 0으로
  떠 있던 상태(전환계획 준수 감사 A1 "높음")를 해소한다.
  - **Rule 1·3 (등급 필수)** — `add --eos-priority` 미지정은 **exit 1**. 거부 메시지가
    판정 질문("이 기능이 없으면 12월 31일 EOS 검증의 폐쇄루프가 깨지는가?")을 출력한다.
    등급을 고르려면 12월 검증 관여 여부를 판정할 수밖에 없다 — 그것이 이 게이트의 목적이다.
  - **Rule 4 (One In → One Out)** — 비종결 P0가 `policy.eos_p0_budget`(기본 50 ·
    계획서 §7 "Release P0 ≤ 50")에 닿으면 P0 신규 등재는 `--swap-out <기존 P0 id>`를
    요구하고, 그 태스크를 **P1로 강등**한다. 예산 여유 구간의 `--swap-out`은 거부한다
    (P0를 오히려 줄이므로).
  - **백필 경로** — 기존 태스크는 `amend <id> --eos-priority <등급> --reason "..."`.
    대장 손편집은 금지다. amend는 예산을 강제하지 **않는다**: amend는 *분류*이고, 분류
    결과가 예산을 넘는다면 그것은 우회가 아니라 보고해야 할 사실이다(여기서 막으면
    사람이 등급을 낮춰 적어 예산을 맞추게 된다 — 측정의 자기기만).
  - **그랜드파더와 그 만료** — 도입 시점의 기존 태스크는 `null`이 허용된다. 만료는 날짜가
    아니라 **기계**다: 게이트 `G-eos-verification-relevance-triage`가 cleared/waived가 되는
    순간(= 관여도 분류의 근거가 생긴 순간) 비종결 미지정이 `validate` 위반이 된다.
    종결(done·cancelled) 태스크는 면제 — 끝난 일에 등급을 소급하는 것은 분류가 아니라
    장부 청소다. 계약 동결 = `tests/harness/test_eos_priority_enforcement.py`(16건).

## 2c. 사고 대장 — 회차를 산문이 아니라 데이터로 센다 (HARN-118)

`backlog/incidents.ndjson` 한 줄이 사고 1건이다. 태스크·게이트와 같은 `backlog/` 대장이며
같은 규칙을 받는다 — **손편집 금지**(`validate`·`check-edit` 훅이 스키마를 검사한다), 등재는
CLI로만.

### 왜 필요했나

이 저장소는 같은 유형의 실패를 반복하면서 회차를 *산문으로* 셌다("동일 유형 3회차",
"미병합 고립 4회차"). 그 결과 **문서마다 회차가 다르다** — 병렬 중복 구현은 CLAUDE.md가
2회차, MEMORY 2026-09-01이 6회차, 실제 발생은 7회다
(`docs/reviews/recurring_failure_taxonomy_2026-09-20.md` §2.7 실측). 회차를 셀 수 없으면
"2회차부터 코드로 막는다"는 규칙도 집행할 수 없다.

### 계약 3가지

| 축 | 규칙 | 집행 지점 |
|---|---|---|
| 회차 계수 | `nth`는 **저장하지 않는다** — `compute_nth`가 같은 `series_id` 안에서 (date, 파일 위치) 순으로 계산한다. 저장하면 진실 원천이 둘이 되고, 과거 사고를 뒤늦게 등재할 때 조용히 어긋난다 | `incidents.compute_nth` |
| 2회차 코드 착지 | 같은 계열 2회차 이상은 `fix_form`이 `code`·`task`·`rule+code`·`rule+task` 중 하나여야 하고 `fix_ref`(테스트 경로·태스크 ID)가 있어야 한다. 산문(`rule`)뿐이거나 `none`/`unknown`이면 **exit 1** | `incidents.repeat_settlement_error` · `incident add` |
| 모른다 ≠ 1회차 | `series_id`가 비면 `nth`는 `None`이다. 0도 1도 아니다 — 미배정을 "첫 발생"으로 접으면 2회차 강제가 통째로 무력해진다 | 위와 같음 |

### 시드와 계열 배정의 정직한 한계

시드 676건은 `docs/data/recurring_failure_ledger_2026-09-20/incidents.jsonl`에서 왔고
**전건 `reviewed: false`**(사람 검수 전)다. `series_id`는 시드의 회차 문자열을 키워드 표
(`incidents.SERIES_KEYWORDS`)로 정규화한 *파생값*이며 원문은 `series_raw`에 그대로 남는다
(`series_source: seed_keyword`). "반복 실수 9회차" 같은 **통산 카운터 표기는 일부러 미배정**
으로 둔다 — 서로 다른 사고에 같은 번호가 붙으므로 계열 키가 될 수 없고, 억지로 묶으면
회차가 거짓이 된다.

그래서 `incident report`의 계열 표 회차는 **대장 레코드를 센 것**이고, 보고서 §2.7의 회차는
*문서가 스스로 센 것*이라 같은 계열에서도 숫자가 다를 수 있다. 그 불일치가 이 대장을 만든
이유이므로 한쪽을 다른 쪽에 맞추지 않는다.

### 주간 지표 배선 (정본화 ≠ 집행)

`incident report --json`의 세 수치(`total`·`max_series_nth`·`rule_only_ratio`)가
`metrics/weekly.json`의 **`harness` 블록**으로 들어간다. EOS-51 §6이 동결한 기술 KPI 6종과는
별개 블록이다 — 6종은 콘텐츠 제작 KPI이고 이 3종은 공정 자신의 건강 지표라, 섞으면 어느
분모로 읽어야 하는지 알 수 없게 된다.

- **정본화**: `ops/weekly_metrics_report.py`의 `--incidents-summary`
- **집행 지점**: `.github/workflows/weekly-metrics.yml`의 선행 스텝이 매주 하네스 집계를 돌려
  JSON을 건넨다 (백엔드는 `scripts/harness`를 임포트하지 않는다 — 하네스는 의존성 0 단독
  실행이고 백엔드는 import-linter 계약 아래 있다)
- **배선 동결**: `tests/infra/test_incident_metrics_wiring.py` — 스텝 부재·경로 불일치·순서
  역전·`continue-on-error`를 결함 주입으로 각각 검출한다
- 요약을 못 받으면 3종은 **`measured=false` + 사유**다. 0으로 채우지 않는다

## 2d. 규칙 인덱스 — 무엇이 이 규칙을 집행하는가 (HARN-121 ④)

`backlog/rules.ndjson` 한 줄이 규칙 1건이다. 정본은 이 데이터이고
`docs/standards/rule_index.md`는 **렌더 결과**다(손편집하면 `rules render --check`가 red).

### 왜 필요했나

반복 실패 676건 실측에서 개별 사고의 44%는 코드로 상환됐는데, *일반화된 규칙*으로
올라간 것들은 **56%가 산문뿐**이었다(`docs/reviews/recurring_failure_taxonomy_2026-09-20.md`
§2.6). 산문 규칙에는 집행 지점이 없으므로 **막고 있는지를 검증할 수 없다** — 그래서 같은
유형이 재발할 때마다 글이 한 단락 늘고, 그 글을 다음 세션이 통째로 읽는다.

### 규칙의 네 종류 (origin)

`grep -c '❌'`로 세면 59건인데 인덱스는 85건이다. 차이는 종류에 있다.

| origin | 건수 | 형태 | 집행 요구 |
|---|---:|---|---|
| `incident` | 28 | `- ❌ **제목** — 본문` | **요구한다** (코드 또는 태스크) |
| `extension` | 16 | `  - **확장 — 축 (날짜)**` | 요구한다 (부모 규칙을 갖는다) |
| `guidance` | 10 | 「Kiki 개인 선호」 절의 `- **제목**` | 요구한다 |
| `founding` | 31 | `- ❌ 평문` | **요구하지 않는다** (`status: policy`) |

`founding`(창건 원칙 — "단순 사진→답 풀이 앱 금지", "미성년자 PII 외부 공유 금지")을
인덱스에서 빼지 않는 이유: 빼면 누가 ❌ 항목을 새로 추가했을 때 **인덱스 밖으로 빠져나가고**,
그러면 전수 검사(L1)가 공허해진다. 대신 `policy`로 "집행 코드를 요구하지 않는다"를 *명시*한다
— 빈칸으로 두면 "미측정"인지 "해당 없음"인지 구별할 수 없다(모른다 ≠ 아니다).

`guidance`가 별도인 이유: 「Kiki 개인 선호」 절의 규칙은 `❌` 없이 `- **제목**` 형태라
❌만 보는 파서는 통째로 놓친다. 그런데 그 절이 **E 분류(Kiki 런북 결함) 규칙 13건**이
사는 곳이고, 사고 34건으로 규칙이 가장 많이 붙은 분류다. 전역으로 `- **...**`를 잡으면
기술 스택·문서 인덱스 목록까지 규칙이 되어 오탐이 쏟아지므로 **절로 한정**한다.

### 린트 6검사 (`backlog.py rules lint`)

| 검사 | 무엇을 보는가 | 주입 → RED |
|---|---|---|
| **L1** | CLAUDE.md의 모든 규칙 ↔ 인덱스가 **양방향** 1:1 | 인덱스에 없는 ❌ 1줄 / 헌법에 없는 인덱스 행 |
| **L2** | 유예 대상이 아닌 신규 항목의 `status: prose` 거부 | 새 규칙을 산문으로 등재 |
| **L3** | 대장 참조 없는 새 `사고 경위:` 단락 거부 | 단락 1건 |
| **L4** | `enforced_by`의 파일이 실재하고 태스크 ID가 대장에 있는가 | 없는 경로·없는 태스크 |
| **L5** | 산문뿐인 규칙 수가 기준선(`PROSE_BASELINE`)을 넘지 않는가 | 산문 1건 추가 |
| **L6** | 파싱 0건은 통과가 아니라 실패 | 빈 CLAUDE.md·빈 대장 |

L4가 이 인덱스를 장식이 아니게 만드는 자리다. `enforced_by`에 적어 놓기만 하고 그 파일이
없으면 인덱스가 거짓말을 하게 되는데, 이 저장소가 반복해 겪은 것이 정확히 그 부류다
(정본화 ≠ 집행).

### 유예는 두 축이고 서로 독립이다

| 필드 | 축 | 검사 |
|---|---|---|
| `grandfathered` | 대책이 **산문뿐**인 빚 | L2·L5 |
| `narrative_grandfathered` | 동결 이전 **사고 경위 단락** 보유 | L3 |

한 필드로 묶으면 *코드로 상환된 규칙이 자기 사고 경위 단락 때문에 L3에 걸린다* — 첫 구현이
정확히 그랬고, `enforced_by`를 채우는 순간 멀쩡한 규칙 18건이 위반이 됐다.

### 래칫 (만료 없는 유예 금지의 현실적 형태)

동결 시점에 이미 산문뿐인 규칙이 **29건**이다. 즉시 위반으로 만들면 대장 전체가 red가 되고
(사람이 린트를 끈다), 영원히 허용하면 "만료 없는 유예"가 된다. 그래서 `grandfathered: true`로
싣고 **건수가 늘지 않는 것만** 강제한다. `rules.PROSE_BASELINE`은 **줄어드는 방향으로만**
고친다 — 늘리는 커밋은 빚을 키우는 것이고 그것이 이 래칫이 막으려는 동작이다.

### CLAUDE.md 본문은 건드리지 않는다

인덱스는 **규칙 제목 문자열**로 헌법과 대응한다(2026-09-21 Kiki 승인). 본문에 `{R-014}`
같은 ID 앵커를 박는 쪽이 견고하지만 그것은 헌법 75줄을 고치는 변경이라 별도 승인이 필요하다.
제목을 고치면 L1이 red를 내는데, 그것은 *고칠 수 있는* red다(인덱스의 `title`을 같이 고친다)
— 조용히 어긋나는 것보다 낫다.

### 집행 지점

- CI `harness-integrity` 잡의 "규칙 인덱스 린트" 스텝이 `rules lint` + `rules render --check`를 돈다
- 그 배선의 실재는 `tests/infra/test_rule_index_lint_wiring.py`가 결함 주입으로 동결한다
  (스텝 삭제·렌더 대조 누락·`continue-on-error`·잡 이동을 각각 검출)
- 판정 로직의 변별력은 `tests/harness/test_rule_index.py` 56건이 L1~L6 주입·대조군 쌍으로 고정한다

## 3. 순차 조율 규칙 (selector)

착수 가능 = `todo` ∧ 의존성 전부 done ∧ 게이트 전부 cleared/waived
∧ owner=claude ∧ 트랙 entry_gate 통과 ∧ 미claim.
정렬 = (stage 순서, priority, −해금 후속 수, id) — **결정적**.

- **owner=claude는 *자동 착수 후보*의 조건**이다(next/status/brief). 사람-소유
  태스크(owner=kiki/partner)는 자동 후보에 절대 오르지 않지만, **소유자 본인이
  `start <id> --as <owner>` / `done <id> --as <owner> --artifact ...`로 직접
  기입할 수 있다**(HARN-06 — 2026-07-16 S1-14 사례에서 사람 태스크의 CLI 완료
  경로 부재가 실측된 설계 공백의 해소). `--as`가 태스크 owner와 불일치하면 거부,
  deps·게이트·claim·증적 검사는 사람 기입에도 동일 적용(우회 아님), 이벤트에
  `as_owner`가 남아 claude 기입과 구분된다.

- **E축 하드락**: subject-expansion 트랙은 `G-s5-subject-expansion` 통과 전
  알고리즘 수준에서 후보 제외 — "수학 완성 전 어떤 과목도 착수하지 않는다"
  (subject_expansion_e_axis_v1.md 불변 전제)가 코드로 강제된다.
- 후보 0 + 사람 게이트만 잔존 → `/drive`는 정지하고 Kiki 행동 목록을 보고한다.

## 3b. 원격 claim — 병렬 세션 실시간 조율 (v1.1)

로컬 `session` claim은 각 세션 worktree의 backlog 사본에만 기록되어 merge 전까지
서로 보이지 않는다(TOCTOU 레이스). **원격 claim**이 이 구멍을 막는다:

- `start`가 origin의 **`harness-claims` 브랜치**에 `claims/<task-id>.json`을 추가하는
  커밋을 push한다. push는 `--force-with-lease=refs/heads/harness-claims:<base>`의
  **CAS 원자성** — 그 사이 남이 브랜치를 갱신했으면 서버가 거부하므로, 두 세션이 동시에
  같은 태스크를 start해도 정확히 한쪽만 성공한다.
- **네임스페이스가 `refs/claims/*`에서 바뀐 이유(HARN-09)**: 이 실행 환경의 git 프록시가
  그 네임스페이스 push를 403 거부해 CAS가 *한 번도 성공한 적이 없었다*. 2026-07-28 실측으로
  `refs/heads/*` 커밋 push는 성공함을 확인하고 이전했다. **태스크당 브랜치가 아니라 단일
  브랜치**인 것은 같은 프록시가 ref *삭제*도 거부하기 때문이다 — 태스크당 브랜치면 해제가
  불가능해 브랜치가 영구 누적된다. 단일 브랜치면 해제가 "파일을 지우는 커밋"이라 삭제가 불요다.
  이 삭제-403의 변별 실측(create-push exit 0 vs delete-push HTTP 403)과 Kiki 위임 명령 블록은
  `parallel_sessions.md` §4 정리 「컨테이너 세션은 원격 브랜치를 삭제할 수 없다」 참조(HARN-16).
- **lease 거부 ≠ 태스크 점유**: lease 거부는 "그 사이 누군가 브랜치를 갱신했다"(대개 다른
  태스크의 claim)는 뜻이라 재fetch 후 재시도한다. 태스크 점유는 오직 브랜치 트리를 읽어
  판정한다 — 이 분리가 "남의 claim"과 "동시 갱신"을 혼동하지 않게 한다.
- claim 파일에 메타(JSON: branch·UTC ts)가 담긴다 — conflict 시 상대 세션이 즉시 식별된다.
  메타가 파손돼 홀더를 특정할 수 없어도 **conflict로 친다**(조용한 탈취 금지, 복구는 `--force`).
- 트리는 `git mktree`로 만든다 — 인덱스를 쓰지 않으므로 개발자의 스테이징·작업 트리를
  건드릴 수 없다(구조적 차단).
- **conflict만 차단**(신호가 확정적) — offline/권한 오류는 경고 + 이벤트 로그 후
  로컬 claim으로 진행한다(fail-open — 훅·CLI가 개발을 볼모로 잡지 않는다).
- `done`/`block`이 claim을 해제한다. 세션이 죽어 claim이 남으면 `claims reap`이
  **4중 기준**(TTL 초과 · 태스크 이미 done/cancelled · 태스크 미존재 ·
  **홀더 브랜치가 origin에 부재**)으로 청소한다 (기본 dry-run, 실삭제는 `--apply`).
  `reap`은 **(목록, 조회상태, 경고목록)** 을 돌려준다 — 조회 실패를 "stale 없음"으로
  위장하면 CI 교차검증이 공전한다(HARN-09 실측 사례).
- **홀더 브랜치 부재(`branch_gone`·HARN-26)**: 컨테이너 세션은 원격 브랜치를 스스로
  지우지 못하므로(HARN-16), 홀더 브랜치가 없다는 것은 그 세션의 작업이 원격에 도달한
  적조차 없다는 뜻이다 — TTL 72시간을 기다릴 이유가 없는 확정 신호다.
  단 `start`와 첫 push 사이에는 브랜치가 없는 **정상 구간**이 있으므로
  `policy.claim_branch_grace_hours`(기본 24h) 이내는 `branch_gone_recent`로 분류해
  삭제하지 않고 경고만 낸다(`task_missing_recent`와 같은 규칙).
  - grace를 TTL과 같게 두면 안 된다 — 실측(events.ndjson start→done/block 199건)에서
    **72h 초과 세션이 0건**이라, grace=72h면 `branch_gone`이 잡는 집합이 `ttl`이 잡는
    집합의 부분집합이 되어 탐지력을 1건도 추가하지 못한다. 24h 오탐 상한은 2.0%.
  - 유예가 이론이 아님을 보여준 실측: 2026-08-11 03:00Z에 "홀더 브랜치 없음"이던
    claim 3건 중 2건이 40분 뒤 정상 push됐다(살아 있는 세션이었다). 유예 없이 집행했다면
    CAS가 막아둔 중복 착수를 직접 열어줬을 것이다.
  - 원격 브랜치 조회가 실패하면 이 기준만 **보류**한다(빈 집합을 "브랜치 전멸"로 읽으면
    대장을 통째로 지운다). 보류 사실은 경고 목록에 실린다 — 침묵하지 않는다.
- **집행 지점(HARN-27)**: `.github/workflows/harness-audit.yml`이 main push·야간·수동
  트리거에서 `claims reap --auto`를 돌린다. `--auto`는 삭제를 켜되 사유를
  `remote_claims.AUTO_REAP_REASONS`(= `task_done`·`branch_gone`)로 좁힌다.
  - **왜 별도 워크플로인가**: `on:`에 `pull_request`가 아예 없어 "PR에서는 지우지 않는다"가
    조건문이 아니라 **구조적 불가능**이 된다. ci.yml의 `harness-integrity`에는 `if:` 가드가
    없어 PR에서도 돌고, 거기에 `contents: write`를 붙이면 PR 검증 경로가 쓰기 권한을 갖는다.
  - **왜 안전 집합이 코드에 있는가**: 사유를 워크플로 인자(`--reasons ttl,...`)로 두면
    YAML을 고쳐 범위를 넓힐 수 있고 파이썬 테스트가 그것을 동결하지 못한다.
    `ttl`(살아 있는 장기 세션일 수 있다)·`task_missing`(CI 러너는 main만 보므로 다른
    브랜치 등재 태스크를 구조적으로 "없음"으로 본다 — HARN-15 맹점)은 제외한다.
  - ci.yml의 dry-run 스텝은 **유지**한다 — PR마다 도는 관측 채널이고, 자동 집행에서
    제외된 사유(사람 판단 필요분)를 드러내는 유일한 화면이다.
- `next`/`brief`(SessionStart)가 원격 claim을 조회해 다른 세션의 작업을
  후보 제외·브리핑 노출한다.

### 3b-1. 읽기측 교차 세션 탐지 — CAS가 막힌 환경의 폴백 (HARN-07)

**사고(2026-07-27)**: 이 실행 환경의 git 프록시는 `refs/claims/*` push를 **HTTP 403**으로
거부했다. 즉 CAS claim은 "가끔 실패"가 아니라 *한 번도 성공한 적이 없었고*, fail-open이
모든 `start`를 통과시켜 중복 방지가 상시 무력이었다 — 두 세션이 OPS-07을 병렬 구현해
한쪽(테스트 735줄 포함)을 폐기했다. `events.ndjson`에 `claim_remote_unavailable`
(status=error) 45건이 그 흔적이다.

**2회차(2026-07-27, OPS-12)**: 같은 원인으로 또 났다. 읽기측 폴백이 이미 있었지만 그 폴백은
*push된* 브랜치만 보므로, 내 `start`(07:03:21)와 상대 `start`(07:06:21) 사이 3분 창을 막지
못했다 — **양쪽 다 `error+readscan_ok`** 를 받고 진행했다. 설계된 한계대로 동작했으나 한계
자체가 사고를 허용한 것이다. **규칙만으로 2회차를 못 막았다**는 것이 HARN-09(네임스페이스
이전으로 CAS 복구)의 등재 근거다 — 반복 실수는 규칙이 아니라 코드로 상환한다.

**HARN-09 이후**: CAS가 1선이고 이 읽기측 경로는 CAS가 offline/error일 때만 도는 **2선**이다.
아래 설명은 그 2선 동작이다.

**대응**: 쓰기(CAS)는 못 고치지만 **읽기는 된다**(`git fetch` 전체 브랜치 ~5초 실측).
`start`는 CAS가 `offline`/`error`를 반환한 경우에만 읽기측 탐지로 폴백한다:

1. `git fetch origin '+refs/heads/*:refs/remotes/origin/*'` (타임아웃 90초)
2. 원격 브랜치들의 `backlog/tasks/<id>.yaml`을 읽어 `status: in_progress` +
   `session:`이 **내 세션과 다른** 것을 찾는다 (최근 커밋순 최대 300개 브랜치)
3. 발견 시 **착수 거부** — 어느 브랜치·어느 세션인지 명시하고, 우회 경로
   (`--no-remote` 또는 상대 태스크 done/block)를 함께 안내한다

**이것은 CAS의 대체가 아니라 *부분* 방어다** (과장 금지 — 코드·CLI 메시지에도 매번 명시):

- 상대 세션이 **브랜치를 push한 뒤에만** 보인다. push 전 로컬에서 작업 중인 세션은
  이 방법으로 **절대** 잡히지 않는다.
- **원자성이 없다** — 두 세션이 동시에 스캔하면 둘 다 "충돌 없음"을 볼 수 있다.

그러므로 **CAS 경로는 제거하지 않는다** — 프록시 정책이 다른 환경(로컬 개발·다른 러너)
에서는 CAS가 작동하며 원자성은 그쪽이 우월하다. 읽기측은 CAS 실패 시에만 돈다
(CAS 성공 시 fetch 비용 0 — `test_CAS_성공이면_읽기측_탐지를_호출하지_않는다`가 동결).

**폴백 자체가 실패하면**(fetch 불가 등) fail-open하되 **"중복 착수 보호가 전혀 없습니다"**를
명시적으로 경고하고 `claim_readside_unavailable` 이벤트를 남긴다 — 침묵 실패 금지.
탐지 성립 시에는 `claim_readside_conflict` 이벤트가 남아 측정 가능하다.

### 3b-2. stale 홀더 처리 — 과탐이 만들던 영구 차단의 해소 (HARN-08)

**문제**: 머지·폐기된 브랜치에 남은 `in_progress`를 읽기측이 활성 claim으로 오인해
그 태스크를 **영구 차단**했다. 우회는 보호를 통째로 끄는 `--no-remote`뿐이었다.
2026-07-27 실측에서 과탐 5건이 관측됐다(ARCH-13·MOB-01·OPS-07·PED-01·S2-02).

> **조상 검사는 쓸 수 없다** — 이 저장소는 SQUASH 머지라 머지된 브랜치도 트렁크의
> 조상이 아니다. 5건 전부 `git merge-base --is-ancestor`가 False로 실측됐다.

판별은 다음 2규칙 + 태스크 단위 우회 1개다:

| 규칙 | 내용 | 근거 |
|---|---|---|
| **A. 트렁크 권위** | 트렁크(`origin/HEAD`)의 사본이 `done`/`cancelled`면 **홀더 전부 무시** | 작업이 이미 착륙했다 — 다른 브랜치의 `in_progress`는 역사적 잔재. `done`/`cancelled`는 종결 상태라 CLI로 되돌릴 수 없다 |
| **B. 트렁크는 세션이 아니다** | 트렁크 ref 자신은 홀더 후보에서 제외 | claim의 의미는 "어떤 *세션*이 그 브랜치에서 작업 중"이다. 트렁크의 `in_progress`는 활성 claim이 아니라 **대장 위생 실패**(done 미기입 머지 — OPS-07이 그 사례) |
| **C. 세분 우회** | `start <id> --ignore-remote-claim` — **그 태스크의 읽기측 판정만** 무시 | `--no-remote`(보호 전체 포기)와 구분. 무엇을 포기하는지 경고 출력 + `claim_readside_ignored` 이벤트. **CAS conflict는 무시되지 않는다**(확정 신호) |

- **기본 브랜치명은 하드코딩하지 않고, 원격 권위를 먼저 묻는다** —
  `git ls-remote --symref origin HEAD`(실측 0.3초) → 실패 시 로컬 캐시
  `git symbolic-ref refs/remotes/origin/HEAD` → 그래도 실패면 `main` 폴백.
  **순서가 안전장치다**: 로컬 `origin/HEAD`는 clone 시점 스냅샷이라 stale일 수 있고,
  2026-07-27 종단 실측에서 실제로 **세션 브랜치를 가리키는 클론**이 나왔다 — 그 값을
  1순위로 믿었다면 규칙 A가 남의 세션 브랜치를 '트렁크 권위'로 삼아 보호를 조용히
  껐을 것이다(미탐). 폴백까지 틀리면 규칙 A 신호가 '없음'이 되어 과탐 상태로 되돌아갈
  뿐이며, 해소 경로는 `ScanResult.trunk_source`·`start` stderr에 매번 표기된다.
- **나이(최종 커밋 경과일) 휴리스틱은 의도적으로 넣지 않았다** — 실측 5건이 A+B로 전부
  해소되며, 나이 컷오프는 느리게 진행하는 실 세션을 오탐 해제할 위험(거짓 음성)만 더한다.
- **걸러낸 홀더는 버리지 않는다** — `ScanResult.skipped`(사유별)에 남고 `start`가 stderr로
  요약하며 `claim_readside_stale_skipped` 이벤트로 적재된다. "보호가 안 걸렸다"와
  "보호를 스스로 껐다"가 구분돼야 하기 때문이다.
- 실환경 검증(2026-07-27): 진짜 origin 대상으로 과탐 5건 → 0건(규칙 A 4건·규칙 B 1건).
  같은 실행에서 살아 있는 claim(HARN-08 본인 브랜치)은 **여전히 홀더로 탐지**되고
  `start`가 exit 1로 거부한다 — 보호가 과잉 무력화되지 않았음을 같은 회계로 확인했다.
- 변별력 실측: 규칙 A 제거·규칙 A 과잉적용·규칙 B 제거·트렁크 해소 순서 되돌림·규칙 C 경고
  삭제 5종 돌연변이가 각각 5·5·3·2·1건의 테스트 FAIL로 검출됨
  (`tests/harness/test_remote_claims.py`·`test_cli.py`).

### 3b-3. 미머지 브랜치 5분류 — 고립과 지연의 분리 (HARN-47·HARN-78)

브리핑의 미머지 브랜치 목록은 **행동이 다른 다섯 부류**를 구분한다. 한 덩어리로 부르면
경고가 습관화되고, 습관화된 경고는 보호가 아니다(CLAUDE.md 「상시 실패하는 fail-open
보호를 '보호 있음'으로 신뢰 금지」).

| 분류 | 판정 근거 | 필요한 행동 |
|---|---|---|
| `isolated` | ahead>0 · 포팅 근거 없음 · **`refs/pull/*/head`에 tip 없음** | 회수(PR 생성) 또는 삭제. **브리핑 줄이 유일한 존재 증거다** |
| `pr_filed` | tip이 `refs/pull/<N>/head`와 일치 · **열림 확인됐거나 상태 미확인** | 없음(열림 확인) — 처분은 그 PR에서. 브리핑은 번호만 건넨다 |
| `pr_closed` | tip이 `refs/pull/<N>/head`와 일치 · **GitHub API로 closed+미머지 확인** | `isolated`와 동급 — 재작업 또는 폐기 판단 필요. "처분은 해당 PR에서"가 막다른 길이다 |
| `ported` | trunk 커밋이 브랜치를 인용하며 코드를 옮김 | 원본 정리만 |
| `active` | 원격 claim 맵에 존재 | 없음 — 진행 중인 정상 작업 |

**`pr_closed`가 왜 필요한가** (2026-09-07 실측, HARN-78): `pr_filed`는 "PR로 노출된 적이
있다"만 답하는 오프라인 git 판정이라 열림·닫힘을 구분하지 못했다. 그 결과 **닫혔지만
머지되지 않은 PR**(예: PR #967·#802·#675 유형)이 열린 PR과 똑같이 "처분은 그 PR에서 —
개입 불요"로 조용히 묻혔다 — 닫힌 PR은 아무도 다시 열어보지 않으므로 이것은 사실상
`isolated`(회수·삭제 판단이 방치된 상태)인데 `pr_filed`의 "결정 불요" 딱지를 달고 있었다
("결정 불요 위장" 계열 3번째 사례).

**왜 이 분리가 생겼나** (2026-08-31 실측): 브리핑이 18건을 전부 "Kiki 결정 필요"로
부르고 있었는데, 그중 11건은 **이미 PR이 열려 있고 처분 라벨까지 붙어 있었다**. 경고의
61%가 이미 결정된 것을 다시 결정하라고 요구했고, 진짜 고립 7건이 그 소음에 24일간
묻혀 있었다.

**PR 판정은 오프라인 git만 쓴다** — `git ls-remote origin "refs/pull/*/head"`는 토큰·API
권한 없이 읽힌다. 판정을 외부 관측 인프라에 의존시키지 않는다는 이중 회계 원칙과 같은
방향이다. tip sha는 이미 도는 `for-each-ref`에 얹어 받으므로 브랜치당 추가 git 호출은 0.

**`active` 판정에는 원격 claim 맵이 필요하다.** 두 진입점(`cmd_brief`·`cmd_branches`)이
모두 `active_branches=frozenset(remote_claimed.values())`를 넘겨야 이 분류가 실제로 난다.
CI 진입점이 이걸 빠뜨리면 **지금 누가 작업 중인 브랜치가 "🔴 회수 또는 삭제 필요"로
경고된다** — 삭제를 유도하는 오경보이자, 이 표가 4분류라고 말하면서 CI 경로는 3분류만
낼 수 있는 상태다. 두 진입점의 배선을 각각 테스트가 붙든다
(`test_cli.py::TestStaleBranchClassificationWiring`). claim 조회 자체가 실패하면 그 사실을
출력에 남긴다 — `active`가 조용히 `isolated`로 오분류되는 것을 막기 위함이다.

**조회 실패는 "PR 없음"이 아니다.** 실패하면 그 브랜치는 `unresolved`(고립 여부 미판정)로
남고 `pr_lookup_ok=False`가 서며, `pr_lookup_error`에 **예외 타입명을 포함한 사유**가
실린다(무타입 경고는 타임아웃·git 미설치·권한 오류를 같은 글자로 보이게 만든다). 실패를 고립으로 읽으면 인프라가 죽은 순간 열린 PR 전부가
"삭제 필요"로 승격된다 — 삭제를 유도하는 오경보다.

**열림/닫힘은 오프라인 git만으로는 판정하지 않는다.** `refs/pull/<N>/merge`가 열린
PR에만 생긴다는 통설을 실측에서 폐기했다(열린 PR 14건 중 merge ref 보유 8건, 이미
머지된 PR도 head만 잔존). 성공/실패에 같은 값을 내는 검사는 검증이 아니라 위장이므로,
오프라인 git이 답할 수 있는 질문("PR로 노출된 적이 있는가")만 오프라인으로 답한다.

**열림/닫힘 자체는 GitHub API로 선택적으로 정밀화한다** (HARN-78 — `_fetch_pr_states`,
`scripts/harness/remote_claims.py`). `pr_filed` 후보로 분류된 PR 번호만, 스캔당 1회
배치로 조회한다(브랜치당 호출 아님). 이 조회는 **`GITHUB_TOKEN`/`GH_TOKEN`이 있을
때만** 시도한다 — 미인증 요청은 IP당 60req/h로 공유 러너에서 상시 소진 상태이므로,
없으면 아예 호출하지 않는다(CLAUDE.md 2026-09-01 main red 실측과 같은 함정 회피).
조회 결과 `closed`+미머지면 `pr_closed`로, `open`이거나 `closed`+머지면 `pr_filed`로
남는다(closed+머지는 실질적으로 이미 착지했으므로 `pr_filed`의 "처분 불요"가 맞다 —
정직한 미세분류 갭으로 남겨 둔다). **조회가 실패하거나 토큰이 없으면** "상태 미확인"으로
표시하고 `pr_filed`로 남긴다 — CLAUDE.md "모른다 ≠ 아니다" 원칙에 따라 실패를 열림도
닫힘도 아닌 별도 상태로 보여준다(`pr_state_lookup_ok=False`·`pr_state_lookup_error`에
예외 타입명 포함).

**집행 지점**(정본화와 별항): SessionStart 훅 + **CI `harness-integrity` 잡**
(`backlog.py branches`). 이 스캔은 HARN-13 이후 줄곧 SessionStart 전용이었다 — 대화형
세션 밖에서는 실행 0회였다. CI 배선에는 `fetch-depth: 0`이 필수다(기본 shallow면 가드에
걸려 매 실행 "판정 보류"가 되어 초록인 채 상시 무력이 된다). 배선 실재성은
`tests/infra/test_stale_branch_scan_ci_wiring.py`가 기계로 동결한다.

### 3b-4. 차단 홀드의 교차 세션 해제 — 정본 경로가 없는 동안의 수동 절차 (HARN-134)

**증상**: `blocked` 태스크를 이어받으려는 세션이 `start`에서 거부당한다.

> `❌ <id> 착수 거부 — 다른 세션이 **차단**해 둔 태스크 (세션: <홀더 브랜치>, <시각>)`
> `해소는 차단 사유를 없앤 뒤 unblock <id> — claims release --force는 차단 우회이므로 쓰지 않는다`

안내대로 `unblock`을 실행해도 **로컬만 `todo`가 되고 원격 홀드는 남는다.** 그래서 `start`가
계속 거부하고, 대장(blocked)과 로컬(todo)이 갈라진 무증상 분기 상태가 된다.

**원인**: `cmd_unblock`이 `_release_remote_claim(root, task.id, prev_session)`을 호출하는데
`prev_session`은 `task.session`이고 **`cmd_block`이 그것을 비운다**. 따라서 항상
`store.current_branch(root)`로 폴백하고, 그 값은 *지금 세션의* 브랜치다. 홀더 브랜치와
다르면 `remote_claims.release()`가 `force` 없이는 거부한다. 즉 **차단을 건 세션이 그대로
살아 있을 때만** `unblock`이 원격까지 걷는다.

그런데 차단 사유는 대부분 *외부 입력 대기*(사람 첨부·게이트·타 PR 착지)이고, 그 해소는
거의 항상 **다음 세션**이 한다. 보호가 실제로 작동하는 경우가 오히려 드문 쪽이다.

> `HARN-48` ④가 "unblock이 홀드를 해제"를 요구했고 구현도 있으나, 같은 세션 경로만
> 덮었다. `HARN-134`가 그 미이행 축의 승계다(수정 전까지 아래 절차가 유일한 해제 수단).

**`--force`는 우회가 아니라 사람 소유 액션이다 — 단, 세 조건을 모두 확인한 뒤에만.**
CLI가 `--force`를 금지어로 안내하는 이유는 *살아 있는 차단을 탈취*하는 것을 막기 위함이다.
아래 셋이 모두 참이면 탈취가 아니라 **청소**이며, 판정 주체는 세션이 아니라 사람이다.

| # | 확인할 것 | 확인 방법 |
|---|---|---|
| ① | 차단 사유가 실제로 해소됐는가 | 태스크 `notes`·`acceptance`의 해제 조건을 읽고 사람이 판정한다. 세션이 스스로 "해소됐다"고 선언하는 것으로는 부족하다 |
| ② | 홀더 세션이 끝났는가 | 홀더 브랜치의 작업이 트렁크에 있는가(`git merge-base --is-ancestor <tip> origin/main`) 또는 브랜치가 사라졌는가(`git ls-remote origin refs/heads/<브랜치>`가 0줄). **SQUASH 머지 저장소이므로 조상 검사가 False여도 머지됐을 수 있다** — 그럴 땐 커밋 메시지·PR로 확인한다(3b-2 규칙 A와 같은 함정) |
| ③ | 그 태스크를 다른 세션이 잡고 있지 않은가 | `backlog.py claims list`에 그 id가 **`kind=block`으로만** 있고 진행 중 claim이 아닌지 |

셋 중 하나라도 아니면 해제하지 않는다. 특히 ①이 아니면 그것이 바로 CLI가 막으려는 상황이다.

**수동 절차** (Kiki 머신 · Windows PowerShell · 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`)

쓰기 블록이므로 **스스로 선행 조건을 재검사해 거부**한다(CLAUDE.md v0.2.26). 태스크 id는
`Read-Host`로 **블록이 멈춰서 묻는다** — 자리표시자를 두면 통째로 붙여넣을 때 치환 없이
그대로 실행되기 때문이다(CLAUDE.md v0.2.12). 세션이 id를 이미 아는 경우에는 그 줄을
채워서 보내되, 자리표시자 형태로는 보내지 않는다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Py = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
$TaskId = (Read-Host "해제할 태스크 full-id")
$Held = ((& $Py scripts\harness\backlog.py claims list | Select-String $TaskId) -ne $null)
$HasCli = (Test-Path ".\scripts\harness\backlog.py")
if ($Held -and $HasCli) { & $Py scripts\harness\backlog.py claims release $TaskId --force } else { "WRITE_REFUSED=True — 홀드있음=$Held CLI있음=$HasCli" }
$After = ((& $Py scripts\harness\backlog.py claims list | Select-String $TaskId) -ne $null)
"RELEASED=$(-not $After)"
```

성공 판정은 마지막 줄 `RELEASED=True` 하나다. `WRITE_REFUSED=True`면 이유가 같은 줄에 찍힌다.

**함정 3가지**(전부 2026-09-22 실측):

1. **`git fetch`는 작업 트리를 바꾸지 않는다** — `origin/main`에 태스크 YAML이 있어도
   체크아웃이 다른 브랜치면 로컬 파일은 없다. 가드 조건에 *태스크 파일 존재*를 넣으면
   정상 상태에서 거부한다. `claims release`는 **그 파일을 읽지 않으므로** 선행 조건이 아니다.
2. **출력이 cp949로 깨져 보인다** — 판정 문자열이 ASCII(태스크 id)라 매칭에는 영향이 없다.
   위 블록 2행의 `OutputEncoding` 설정이 표시를 고친다.
3. **로컬 `unblock`을 먼저 돌려 두면** 로컬은 `todo`·대장은 `blocked`인 분기 상태가 된다.
   해제 후 `backlog.py status`로 두 값이 다시 맞는지 확인한다.

## 3b-1. 중복 방어의 두 축 — 같은 *이름* vs 같은 *문제* (HARN-51)

번호 충돌 가드(HARN-10/15)가 막는 것은 **같은 식별자**를 두 세션이 배정하는 것이다.
2026-08-31~09-01 동종 6건 중 **5건이 이 축**이었고 CLI가 전건 실거부했다.

나머지 1건은 달랐다. `HARN-45`와 `HARN-48`이 같은 뿌리(차단이 교차 세션 보호를 지운다)를
**서로 다른 이름으로** 각자 구현했고, ID가 다르므로 번호 가드·claim 대장·원격 파일 스캔
**어디에도 걸리지 않았다**. 발견 경로는 기계가 아니라 상대 세션이 자기 YAML에 중복을
스스로 적어 둔 것이었다 — 그것이 없었으면 한쪽 구현이 통째로 폐기됐을 것이다(실제로 폐기됐다).

- **신호** = 공유어를 문서빈도의 역수(IDF)로 가중한 점수. 결정적이었던 것은 `차단`·`block`
  같은 일반어가 아니라 `cmd_block`·`_release_remote_claim`처럼 **저장소 안에서 드문 식별자**다.
  **IDF는 백로그 자신에서 산출**하므로 임베딩·외부 모델·네트워크가 없다.
- **대조 범위** = 로컬 in-flight **+ 원격 브랜치 사본**. 로컬만 보면 이 사고를 재현조차 못 한다
  (`HARN-48`은 별도 브랜치에 있었다). 원격 읽기는 `fetch=False` 계약을 승계해 **네트워크 0**이고,
  로컬에 이미 있는 ID는 읽기 *앞*에서 걸러 `git cat-file --batch` 1회로 끝낸다.
- **차단하지 않는다** — 유사도에 정답은 없다. 후보가 없으면 아무것도 출력하지 않고, 원격
  조회가 실패하면 침묵 대신 **판정 불가**라고 말한다(실패를 '중복 없음'과 같은 색으로 두지 않는다).
- **실측(2026-09-01 · 485건)**: 표적 검출 1위(0.1365 vs 잡음 0.0733) · 평균 후보 0.86건 ·
  최대 3건 · 완전 침묵 53%. 한계까지 포함한 정본은 `scripts/harness/similar.py` 모듈 docstring.

## 3c. 조율 정책 — 단계적 강제 (warn → block)

`backlog/policy.yaml`의 rule 3종 (전부 warn으로 시작 — "측정 없는 도입 없음"):

| rule | 감지 대상 | 감지 지점 |
|---|---|---|
| `path_overlap` | 태스크 간 파일 범위 교집합 | `start` 프리플라이트 · check-edit 훅 |
| `scope_drift` | 내 claim 태스크의 선언 paths 밖 편집 | check-edit 훅 |
| `adhoc_edit` | claim 없이 코드 도메인(src/·infra/) 편집 | check-edit 훅 |

- warn = stderr 1줄 + `events.ndjson`에 `policy_warn` 적재 (측정) / block = 거부(exit 1·2).
- **승격 기준**: 2주 또는 30세션 관찰 후 (a) 실제 충돌 예방 사례 ≥1 또는 정탐률 ≥50%
  (b) 오탐으로 인한 개발 중단 0건 → 해당 rule만 block 승격.
  승격 = policy.yaml 1줄 수정 + MEMORY.md 결정로그 + `policy_promote` 이벤트.
- 측정 요약: `backlog.py policy report --days 14`.
- 겹침 판정은 보수적 2단 근사(실파일 교집합 + 정적 프리픽스 포함 — `pathscope.py`).
  과탐이 미탐보다 안전하다는 원칙. 원격 claim conflict는 단계적 도입의 예외로
  **즉시 차단**(신호가 확정적이므로).

## 3d. 의존 선언의 두 종류 — 하드 부착 vs 소프트 분류 (HARN-52 · HARN-53)

`selector.py`는 **`depends_on`만** 본다. notes에 "선행: X 착지 후"라고 적어도 스케줄러는
모르므로, 등재자가 "막아 뒀다"고 믿는 동안 그 태스크는 다른 세션에 착수 후보로 노출된다.
그래서 `audit-deps`(CI `harness-integrity`)가 **notes의 선행 어구 ↔ `depends_on`** 을 대조한다.

문제는 어구가 잡혔다고 언제나 하드 의존인 것은 아니라는 점이다. HARN-53이 레거시 6건을
전수 분류한 결과 **하드 부착이 옳은 것은 0건**이었고, 다섯 가지 서로 다른 이유로 전부 하드가
아니었다. 그때 남는 선택지는 셋뿐이다 — ⓐ notes를 고쳐 어구를 피한다(자연어를 게이트에
맞추는 꼬리-개-흔들기) ⓑ 틀린 하드 의존을 붙인다(영구 오차단) ⓒ **왜 하드가 아닌지를
코드로 분류한다**. 저장소는 ⓒ를 택했다.

### 어느 쪽인지 판정하는 법

| 상황 | 처리 | 수단 |
|---|---|---|
| 진짜로 X가 끝나야 시작할 수 있다 | **하드 부착** | `backlog.py amend <id> --depends <full-id> --reason '...'` |
| 방향이 반대다(내가 X의 선행) | 소프트 `REVERSED` + **상대 쪽에 부착** | `SOFT_DECLARED` + `amend X --depends <나>` |
| A 또는 B 택일 | 소프트 `DISJUNCTIVE` | `depends_on`은 AND라 표현 불가 — 하나가 done이 될 때 남은 쪽을 부착 |
| 후행 스테이지 의존(E축 등) | 소프트 `STAGE_BLOCKED` | `validate`가 로드맵 순서 위반으로 거부한다 · 제외는 `status=blocked`가 담당 |
| 이미 끝난 과거 사실 서술 | 소프트 `HISTORICAL` | 앞으로의 순서 제약이 아니다 |
| 창(60자)이 잡은 ID가 선행이 아님 | 소프트 `MISREAD_REF` | 진짜 선행이 따로 있으면 그쪽을 부착 |
| 선행이 **cancel**됐다 | **결정 불가 → 차단 유지 + 경고**(해소 아님 — HARN-67 ②) | 오등재면 `amend <id> --remove-depends <full-id> --reason '...'` · 취소가 틀렸으면 복원(HARN-69 · main 기준 todo) |

### 소프트 분류가 옵트아웃이 되지 않는 이유

유예(`LEGACY_EXEMPT`)와 다르다 — 유예는 "아직 안 고쳤다"라서 **만료**가 필요하고, 소프트는
"고칠 것이 없다"라는 **판정**이라 만료가 없다. 만료가 없으니 느슨해질 여지를
`find_soft_declaration_violations`가 대신 막는다:

1. 사유 **코드**는 고정 집합에서만 — 자유 서술로 "소프트니까"가 불가능하다
2. 근거 문장이 비었거나 40자 미만이면 위반 — 코드만 찍고 넘어갈 수 없다
3. 같은 쌍이 `depends_on`에도 있으면 위반 — 하드로 걸어 놓고 소프트라 적는 모순
4. 대상·참조가 백로그에 없으면 위반 — 허구가 된 분류
5. 같은 쌍이 유예에도 있으면 위반 — "고칠 것 없음"과 "아직 안 고침"은 동시에 참일 수 없다
6. **인용구**(`quotes`)가 없거나 notes에 없으면 위반 — 아래 "발생 위치 결속"
7. `DISJUNCTIVE`·`STAGE_BLOCKED`인데 태스크가 착수 후보에서 빠지지 않으면 위반 — 아래 "제외 강제"

### 발생 위치 결속 — 쌍이 아니라 *그 문장*을 분류한다

쌍(태스크, 참조)만으로 억제하면 **그 두 태스크 사이의 앞으로 모든 문장**이 함께 묻힌다. notes는
append 전용이라 나중에 진짜 선행 선언("X 착지 후 착수")이 추가돼도 스캐너와 `amend` 가드가
똑같이 green을 낸다. 그래서 분류마다 **어느 문장을 분류했는지**를 인용구로 적고, 그 인용구
구간 안에 있는 참조 토큰만 억제한다 — 분류되지 않은 새 문장은 정상적으로 잡힌다.

결속 기준은 *참조 토큰의 위치*다(어구 위치나 창 포함이 아니라). 창은 어구 좌우 60자라 옆
문장을 삼키고, 어구 기준으로 묶으면 한 어구가 잡은 *다른* 참조까지 함께 억제되기 때문이다 —
둘 다 실측으로 확인하고 좁혔다.

### 제외 강제 — 분류만 하고 막지 않으면 경고만 없앤 것이다

`DISJUNCTIVE`·`STAGE_BLOCKED`는 "*그 참조에 대해서는* `depends_on`으로 순서를 강제할 수 없다"는
뜻이다. 그러면 스케줄러 제외를 **다른 수단**이 담당해야 한다. 계약이 요구하는 것은 **결과**
(착수 후보에서 빠질 것)이지 특정 수단이 아니다 — `status=blocked`도, *다른* 참조를 하드로
부착하는 것도 유효하다. 수단을 하나로 못박으면 옳은 해법을 위반으로 만든다.

실측 배경 두 가지: `EOS-50`이 택일 선행 둘 다 미완인데 `todo`라서 착수 후보 111건에 들어
있었고(분류가 유일한 경고를 없앤 상태), 그 뒤 병렬 세션이 택일의 한쪽인 `EOS-49`를
`depends_on`에 부착해 막았다(PR #994) — 계약이 `blocked`만 인정했다면 그 옳은 해법이 위반이
됐을 것이다.

그리고 **보이지 않게 쌓이지 않는다**: `audit-deps --all`이 소프트 전건을 코드·근거와 함께
출력하고, green 줄에도 건수가 찍힌다.

### 취소된 선행은 해소가 아니다 — 차단은 유지하되 보이게 한다 (HARN-67 ②)

`selector`는 `depends_on`의 선행이 **done**일 때만 해소로 친다. 선행이 `cancelled`면 그 태스크는
기다려도 영원히 풀리지 않는데, 취소가 "불필요해서"인지 "잘못 등재돼서"인지 기계는 모른다
(모른다 ≠ 아니다). 해소로 간주하면 오등재 태스크의 후속이 조용히 착수돼 trunk에 없는 파일을
대상으로 작업하게 되므로 **차단은 유지**한다. 대신 조용한 차단만은 금지다(침묵 실패 금지):

- `next` — `--json`·후보 유무와 무관하게 **매번** stderr에 `⚠ 후보 제외 <id> — 취소된 선행 <dep>에
  차단됨 · 정정: …`를 낸다(제외 사유 코드 `deps_cancelled` — 일반 `deps`와 구별).
- `status`·`brief`·`validate` — `취소된 선행에 차단된 태스크 N건: id(←dep) …` 한 줄(0건이면 침묵).
  brief는 훅이 stderr를 버리므로 stdout에 싣는다. validate는 **red로 만들지 않는다**(대장은 정합하다).
- `cancel` — 취소 시점에 그 태스크를 선행으로 가진 미종결(todo/blocked/in_progress/review)
  태스크를 세어 `⚠ 이 취소로 N건이 차단된다: …`를 낸다. 취소를 막지는 않는다.

정정은 두 갈래다 — 선행이 오등재였으면 후속에서 `amend --remove-depends`로 뗀다(HARN-67 ③),
취소 자체가 틀렸으면 복원한다(HARN-69 — main 기준 todo). (사고 경위 2026-09-05: EOS-94 cancel →
EOS-96이 후보에서 무경고 소실 → 정정 경로가 없어 EOS-97로 재등재. 번호 2개·왕복 1회 소모)

### 게이트 해소는 태스크를 풀지 않는다 — clear·waive 직후 알리고, brief가 매 세션 되묻는다 (HARN-74)

`gates clear`·`waive`는 게이트 status만 바꾼다 — 그 게이트를 `requires_gates`로 건 **blocked** 태스크는
그대로 blocked다(차단 사유가 게이트뿐인지 기계는 모르므로 자동 unblock하지 않는다 · 모른다 ≠ 아니다).
종전에는 `✔ 게이트 → cleared` 한 줄뿐이라 그 사실을 아무도 못 봤다(2026-09-06 실측: ADMIN-02·CUR-17·
CUR-18이 게이트 해소 뒤 5일 이상 방치·`/status`가 Kiki 대기로 오보고). 이제 두 시점·세 화면에서 보인다:

- **해소 시점** — `gates clear|waive` 직후 `· 부착 blocked 태스크 N건` + 각 줄에
  `python3 scripts/harness/backlog.py unblock <id>` 명령(남은 pending 게이트가 있으면 `# (다른 게이트 대기:
  G-x)` 병기 — unblock해도 후보가 되지 않는 이유를 미리 알린다). **0건도 `0건`으로 명시**한다 — 결과 보고에서
  침묵은 "검사 안 함"과 같은 화면이다. 이어서 `· 산문 참조(requires_gates 미부착) N건` — notes에만 게이트
  ID를 적은 blocked 태스크(CUR-17·CUR-18 형태). 기계는 의도를 모르므로 명령 대신 `amend <id> --gate <G>`(부착)와
  `unblock <id>`(해제) 두 갈래를 안내한다. 부분 문자열(`G-x` ⊂ `G-x-y`)은 참조가 아니다. 이벤트에
  `blocked_attached`·`blocked_notes_ref`가 남는다(화면은 휘발되지만 대장은 남는다).
- **다음 세션** — `brief`(stdout)·`status`(`--json`은 `gate_stale_blocked`)가 `해소된 게이트를 기다리는 blocked
  태스크 N건: id(←G) … — 확인: backlog.py unblock <id>` 한 줄을 낸다(0건이면 침묵 — 요약 화면의 규약). clear
  화면을 놓쳐도 다음 세션이 본다(집행 지점 별항 — 정본화≠집행).
- 계산은 `selector.gate_dependent_tasks`·`gate_attached_blocked`·`gate_notes_referenced_blocked`·
  `stale_gate_blocked` 한 곳이며 보드(`board.gate_dependents`)도 같은 헬퍼를 쓴다 — 두 화면이 다른 사실을
  말하지 않는다. 계약 동결 = `tests/harness/test_gate_clear_reminder.py`(뮤테이션 3종 RED 실측 포함).

### 되먹임 주의 — 정정 사유가 새 위반을 만든다

`--reason`은 notes에 append되고 notes는 이 스캐너의 입력이다. 그래서 *"…'선행'이라 선언한
방향을 부착한다"* 같은 **사유 인용**이 그 문장 안의 태스크 ID를 새 선언으로 만든다(HARN-53
실측 2건). 기록된 뒤의 정정은 `--notes-replace`(HARN-67 ⑥) 한 경로뿐이므로 **쓰기 전에**
거부한다 — 사유에서 선행 어구와 태스크 ID가 한 문장에 오지 않게 쓴다. 같은 되먹임이
`--remove-depends`·`--notes-replace` 축에도 있다(notes에 "선행: X"가 남은 채 X를 떼면 미집행
선언이 된다) — 그때는 같은 호출에서 `--notes-replace`로 어구를 함께 고친다(거부 메시지가 안내).
같은 이유로 amend는 제거한 의존 ID·치환 원문을 notes에 **인용하지 않고 이벤트 대장에만** 남긴다
(실측: `depends_on -T7-01: 오등재 선행 제거` 한 줄이 그 자체로 새 선언이 되어 amend가 자기 가드에
거부됐다).

가드가 붙은 곳은 `amend`와 `block` 둘이다. `done`·`cancel`도 사유를 notes에 append하지만
그 명령들은 태스크를 스캐너가 건너뛰는 상태(`done`·`cancelled`)로 바꾸므로 위반을 만들 수
없다. 판정 대상은 **이 명령이 새로 만든** 위반뿐이다 — 기존 위반까지 막으면 위반 하나가
대장에 있는 동안 그 태스크의 모든 정정이 봉쇄되어, 게이트가 자기 정정 경로를 막는다.

---

## 4. 일상 워크플로우

```
세션 시작   → (자동) SessionStart 브리핑: 현재 스테이지·next 3·게이트 리마인드·해소된 게이트를 기다리는 blocked(HARN-74)
주도 진행   → /drive              # 순차 루프 (기본 3태스크, 사람 게이트에서 정지)
단건 작업   → /implement <id>     # start → 구현 → PR 생성 → done --artifact
새 계획     → /plan <주제>        # 산출물 = backlog add 태스크 등록
사람 게이트 → /gates              # clear는 evidence 필수
상세 상태   → /status
세션 종료   → (자동) Stop 훅: claim 태스크 미갱신이면 차단
```

## 4b. 작업 보드 — 한 화면 가시화 (`board.py`)

`status`·`brief`가 *터미널 요약*(next 3건 + 게이트)이라면, 보드는 **전수 가시화**다.
"무엇을 했고 · 무엇을 하는 중이며 · 무엇이 예정인가"를 한 화면에서 본다.

```bash
python3 scripts/harness/board.py            # work/board.html 생성 (+ 터미널 요약 동시 출력)
python3 scripts/harness/board.py --text     # HTML 없이 터미널 요약만
python3 scripts/harness/board.py --json     # 페이로드 JSON (다른 도구가 소비)
python3 scripts/harness/board.py --no-remote   # 미머지 완료 스캔 생략 (배너로 판정 불가 표기)
python3 scripts/harness/board.py --out docs/reviews/board_2026-08-31.html   # 스냅샷 보관용
```

산출물은 **자기완결 HTML 1파일**이다 — 외부 CDN·폰트·서버 요청이 없어 오프라인에서도
열리고, 그대로 첨부·공유할 수 있다. 5열 칸반:

| 열 | 무엇인가 | 판정 근거 |
|---|---|---|
| 진행 중 | 세션이 claim해 작업 중 (`in_progress`·`review`) | `status` + `session` |
| 다음 착수 | 의존성·게이트 전부 해소 — 바로 시작 가능 | `selector.classify_todo` = None |
| 대기 | 등재됐으나 선행 조건 미해소 (사유 라벨 표시) | `selector.Exclusion.reason` |
| 차단 | `blocked` — 노트의 최신 `[차단 …]` 문단을 카드에 발췌 | `status` + `notes` |
| 완료 | 증적 확인된 종결 — 최근 갱신 우선 | `status == done` |

여기에 스테이지 진행률·사람 게이트·`validate` 경고가 같은 화면에 얹히고, 검색어·스테이지·
레이어·트랙·과목으로 즉시 필터된다.

**게이트 카드는 클릭하면 펼쳐진다**(네이티브 `details/summary` — 키보드 접근 가능). 접힌
상태는 id·제목·경과일(리마인드 초과면 붉은 테두리)만, 펼치면 넷을 더 보여준다:
- **메타** — 종류·담당·요청일·리마인드 임계·상태
- **이 게이트가 막고 있는 것** — `requires_gates`로 건 태스크 목록에 더해, **트랙
  `entry_gate`로 잠긴 경우 그 트랙의 미완 건수**를 함께 센다. 트랙 잠금은 태스크 쪽에
  아무 표시도 남기지 않으므로, 이걸 세지 않으면 E축 하드락이 "아무것도 안 막는 게이트"로
  보인다(실측: `G-s5-subject-expansion`이 미완 15건을 잠근다). 단 이 목록은 **의존 관계**
  이지 "현재 차단"이 아니다 — 해소된 게이트를 아직 `requires_gates`에 달고 있는 태스크가
  실재하고(`G-eos-g0-verification-design-freeze` ↔ `EOS-56`) `selector.unmet_gates`는 그
  태스크를 착수 가능으로 본다. 화면 문구는 `blocks_now`(게이트가 pending인가)로 갈린다:
  대기면 "막고 있는 것", 해소면 "전제로 걸었던 것(지금은 차단하지 않는다)".
- **상세 노트** — 발췌가 아니라 **원문 그대로**(줄바꿈 보존·스크롤). 게이트 노트에는 실행
  런북이 들어 있다(`G-operator-seat-first-grant` 2,736자) — 요약하면 그게 사라진다
- **해소 명령** — `backlog.py gates clear <id> --as <담당자> --evidence "<근거>"` 그대로 복사 가능
  (보드가 게이트의 담당자를 플래그에 실어 준다 — 복사한 사람이 곧 기록되는 주체다).
  **사람이 본인 게이트를 직접 닫을 때는 `--as kiki`를 붙인다**(HARN-60) — 붙이면 대장에
  `cleared_by: kiki`가, 생략하면 `cleared_by: claude`(에이전트 중계)가 남는다. 생략을
  거부하지 않는 이유: 에이전트 중계는 정당한 운영 형태이고(Kiki가 자기 머신에서 실행 →
  출력 전달 → 세션이 기입), 막으면 CLI를 우회한 YAML 손편집으로 밀려나 아무 기록도 안
  남는다. 목표는 금지가 아니라 **사후 증명 가능성**이다

해소된 게이트(cleared·waived)는 기본 접힌 별도 그룹에서 근거(evidence)와 함께 열람한다 —
기본 화면은 행동이 필요한 대기 게이트만 보여 준다.

**계약 3건** (`tests/harness/test_board.py`가 동결):
1. **판정 무복제** — 열 배치는 `selector.classify_todo`, 진행률은 `report.stage_progress`를
   그대로 호출한다. 보드가 자기만의 "착수 가능" 판정을 갖는 순간 이중 진실원천이 된다.
2. **무손실** — 열에 배치된 건수 + 취소 건수 = 전체 건수. 어떤 태스크도 조용히 사라지지
   않는다(보드는 요약이 아니라 전수 투영이다).
3. **미머지 완료분 재조정** — `remote_claims.scan_remote_done`(fetch 없음·네트워크 0)으로
   *다른 브랜치에서 이미 done인* 태스크를 "다음 착수"에서 빼 대기 열로 옮기고 사유를
   붙인다. `next`가 같은 이유로 후보에서 제외하는 축이며(HARN-11), 이것이 없으면 **끝난
   작업이 예정으로 보여 중복 구현을 부른다**(도입 시 실측 15건). 스캔이 실패하거나
   `--no-remote`로 건너뛰면 **빈 결과를 "완료분 없음"으로 위장하지 않고** 보드 상단에
   "판정 불가(<사유>)" 배너를 띄운다 — 측정 실패는 통과와 같은 색이면 안 된다.

보드는 **읽기 전용**이다 — `backlog/`를 일절 쓰지 않으며, 상태 변경 창구는 `backlog.py`
CLI 단독이라는 규약이 그대로 유지된다. 기본 출력 경로 `work/`는 gitignore 대상이라
생성물이 저장소를 오염시키지 않는다(스냅샷을 남기려면 `--out`으로 명시 경로를 준다).

## 5. 다과목 확장과의 관계 (비침투 원칙)

백로그의 `subject` 필드는 **빌드 관리 메타데이터**다. 런타임 `Subject` enum·
개념 그래프·문항 스키마를 일절 만지지 않는다 (subject_pack_spec_v1.md
"Subject enum ADD VALUE 금지"와 무충돌). 새 과목 추가 = `models.SUBJECTS` 1줄
+ 태스크 시딩. 문명의 어떤 교육 영역이든 — 대학 수학·물리·화학·생물·지구과학·
경제·역사·세계사·국어·영어 — 같은 스키마로 일정 관리된다. 착수 *순서*는
E축 정본 문서가 결정하며, 하네스는 그 순서를 게이트로 집행할 뿐 날조하지 않는다.

## 6. 아키텍처 감시 (infra-debt 트랙)

`ARCH-NN-playbook-audit` 반복 태스크가 플레이북 불변식(2대 철칙·8대 구조 원칙·
7대 붕괴 연쇄)·7계층 경계·이중 truth source를 정기 점검한다.
- 점검 기준: `docs/standards/build_checkpoint_questions.md` ·
  `docs/standards/playbook_part_review_questions.md`
- 감사 완료 시 다음 회차를 `backlog.py add`로 즉시 재생성한다 (감시 공백 금지).
- 위반 발견 = 상환 태스크 등록 (감사가 백로그를 먹여 살린다).

## 7. CLI 요약

```bash
python3 scripts/harness/backlog.py status          # 진행률·게이트·다음 후보 한 화면
python3 scripts/harness/backlog.py next --n 3      # 착수 가능 후보 + 선정 사유
python3 scripts/harness/backlog.py start <id>      # claim (규칙 위반 시 거부)
python3 scripts/harness/backlog.py start <id> --ignore-remote-claim  # 이 태스크의 읽기측 판정만 무시(stale 확인 후·HARN-08)
python3 scripts/harness/backlog.py start <id> --no-remote            # 원격 보호 전체 생략(오프라인·긴급)
python3 scripts/harness/backlog.py done <id> --artifact "<PR 번호를 담은 증적>"   # 증적·PR 참조 필수
python3 scripts/harness/backlog.py done <id> --artifact "<커밋>" --no-pr ci-red   # 예외 4종만(HARN-23)
python3 scripts/harness/backlog.py start|done <id> --as kiki ...  # 사람-소유 태스크의 소유자 본인 기입(HARN-06)
python3 scripts/harness/backlog.py block <id> --reason "..." / unblock <id>
                    # block은 원격 대장에 kind=block 홀드를 **게시**한다(HARN-42/48) —
                    # 머지 없이 병렬 세션의 start가 즉시 거부된다. unblock이 그 홀드를 걷는다
python3 scripts/harness/backlog.py gates list|add|amend|clear|waive|show   # add = 게이트 등재 CLI(HARN-18) — gates.yaml 손편집 금지
python3 scripts/harness/backlog.py gates amend <G-id> --reason "..." [--title "<새 제목>"] [--remind-after-days <N>]
                    # 등재된 게이트의 **문면·독촉 주기 정정**(HARN-124). 종전에는 --title·--remind-after-days가
                    # add 전용이라 한 번 등재된 게이트가 틀려도 고칠 CLI가 0이었다(손편집은 금지이므로 수단 자체가 없었다).
                    # 실효값은 그 자리에 덮어쓰고 **옛 값과 사유는 corrections[]에 append**한다 — 읽는 쪽(브리핑·
                    # gates list·show)을 한 곳도 고치지 않아야 "정정했는데 화면은 옛 문면"이 구조적으로 불가능해진다.
                    # waive와 다르다: waive는 status를 바꿔 대기 태스크를 **해금**하므로 '요건은 살아 있고 시점만
                    # 미뤘다'를 표현할 수 없다. amend는 status·evidence를 건드리지 않는다.
                    # 거부 4종(게이트 부재·--reason 누락·정정 대상 누락·무변경)은 전부 exit 1 + gates.yaml 바이트 동일.
python3 scripts/harness/backlog.py gates show <id>   # 사람에게 게이트를 서술할 때는 반드시 이 경로를 거친다(HARN-92) —
                    # title은 등재 시점 질문이라 status가 cleared/waived로 바뀌어도 갱신되지 않는다(append 전용·HARN-76).
                    # `gates list`는 title과 status만 보여줄 뿐 근거는 안 보인다 — title만 옮겨 적으면 이미 뒤집힌
                    # 질문을 다시 묻게 된다(2026-09-07~08 실측: G-merge-queue-or-strict-relax가 cleared·재판정됐는데
                    # title 그대로 재안내해 왕복 1회 낭비). show는 status별 근거를 title보다 먼저, 전문(절단 없음)으로
                    # 낸다 — cleared는 evidence, waived는 notes(waive 사유는 evidence가 아니라 notes에 저장된다),
                    # pending은 "없음(아직 결정 전)"을 명시한다(모른다 ≠ 아니다).
python3 scripts/harness/backlog.py gates clear <id> --as kiki --evidence "..."  # 사람이 본인 게이트를 닫을 때 주체 명시(HARN-60)
# clear·waive 직후 그 게이트를 기다리던 blocked 태스크(unblock 명령)·산문 참조가 출력된다 — 0건도 명시 (HARN-74 · §3d)
# evidence에는 판정 기준(커밋 해시·PR 참조)이 있어야 한다 — 없으면 exit 1 (HARN-68).
# 판정은 시점에 종속되므로 "무엇을 봤나"가 아니라 "언제의 트리로 봤나"가 근거다.
python3 scripts/harness/backlog.py gates clear <id> --as kiki --evidence "main 3b007e23 기준 확인"
# 커밋과 무관한 근거(환경 생성·서명·외부 등록)는 탈출구 — 사유가 대장·이벤트에 남는다
python3 scripts/harness/backlog.py gates clear <id> --as kiki --evidence "..." --no-base "저장소 밖 설정 작업"
python3 scripts/harness/backlog.py amend <id> --reason "..." [--acceptance "정정 항"] [--gate <G-id>] [--track <트랙>] [--eos-priority P0|P1|P2|P3]
                                                   [--depends <full-id>] [--remove-depends <full-id>] [--remove-gate <G-id>] [--notes-replace "구문자" "신문자"]
                                                   # 등재된 태스크의 정정 CLI(HARN-24) — tasks/*.yaml 손편집 금지
                                                   # --remove-depends/--remove-gate/--notes-replace = 정정 경로 3축(HARN-67 · §7a) — 없는 것 제거·미부착 탈착·
                                                   #   구문자 0회/2회+ 치환은 exit 1 + 파일 무변경. 원문·제거 ID는 이벤트에만 남는다
                                                   # --eos-priority = 기존 태스크 등급 백필의 유일한 합법 경로(HARN-55)
python3 scripts/harness/backlog.py add --id ... --title ... --eos-priority P0|P1|P2|P3 --path "src/backend/**"  # /plan 산출물
#   ↑ --eos-priority는 **필수**다 — 미지정은 exit 1 (계획서 100 Rule 1·3 집행 지점 · HARN-55).
#     P0가 예산(policy.eos_p0_budget)에 닿았으면 --swap-out <기존 P0 id>로 교환한다(Rule 4)
#   ↑ add는 등재 후 두 가지를 **고지**한다(차단 아님): 가시성(HARN-43)·의미 중복 후보(HARN-51)
python3 scripts/harness/backlog.py validate        # 무결성 전수 검증 (태스크·게이트·트랙 + 사고 대장 스키마)
python3 scripts/harness/backlog.py rules lint               # 규칙 인덱스 린트 L1~L6 — 위반 시 exit 1 (§2d)
python3 scripts/harness/backlog.py rules report             # 유래·상태 분포 + 갚아야 할 빚(산문뿐) 목록
python3 scripts/harness/backlog.py rules render [--check]   # 대장 → docs/standards/rule_index.md (--check = 어긋남만 검사)
                    # 새 규칙을 CLAUDE.md에 쓰면 L1이 먼저 막는다(인덱스 미등재) →
                    # 산문으로 등재하면 L2·L5가 막는다 → 집행 참조를 붙이면 통과.
                    # rules.ndjson 손편집 금지 · rule_index.md는 렌더 결과다
python3 scripts/harness/backlog.py incident report          # 사고 대장 표 5종 (§2c)
python3 scripts/harness/backlog.py incident report --json   # 주간 지표(metrics/weekly.json harness 블록) 입력
python3 scripts/harness/backlog.py incident series [<계열>]  # 계열 목록 또는 한 계열의 회차 전개
python3 scripts/harness/backlog.py incident add --title "..." --cat B --series <계열> \
        --fix-form code --fix-ref "tests/...::test_..." --who-caught bot --damage-class false_pass
                    # 같은 계열 2회차 이상인데 fix_form이 rule/none/unknown이면 **exit 1** —
                    # 산문 규칙은 집행 지점이 없어 막고 있는지 검증할 수 없다(HARN-118 ②).
                    # 거부 사유는 계열·회차와 함께 stderr에 남는다. 1회차는 산문도 허용된다
                    # (계열인 줄 모르는 시점이므로). incidents.ndjson 손편집 금지
python3 scripts/harness/backlog.py claims list --verbose   # 원격 claim 현황 (누가 무엇을)
python3 scripts/harness/backlog.py claims release <id> [--force]  # claim 해제 (남의 것은 --force)
python3 scripts/harness/backlog.py claims reap [--apply]   # stale claim 청소 (기본 dry-run)
python3 scripts/harness/backlog.py claims reap --auto      # 무인 집행 — 확정 사유만 (CI 전용)
python3 scripts/harness/backlog.py branches         # 미머지 브랜치 — 고립/PR제출 분리 (HARN-47)
python3 scripts/harness/backlog.py overlap <id>    # 착수 전 겹침 진단
python3 scripts/harness/backlog.py policy show|report      # 정책 값·warn 측정 리포트
python3 scripts/harness/board.py                   # 작업 보드 HTML (work/board.html)
```

### 7a. 정정 경로 표 — 대장 손편집 없이 고칠 수 있는 것 (HARN-57·59·67)

대장 손편집 금지 원칙은 **정정 경로가 CLI에 있을 때만** 지켜진다. 고칠 수 없는 위반을 지적하는
게이트는 사람이 게이트를 끄게 만들고(HARN-52 등재 사유와 동형), 정정 경로가 없는 필드는
`cancel`+재등재로만 고쳐져 번호가 소모된다(EOS-94·96·MP-01·EOS-98 — 2026-09-05/06 실측 4건).
**판정 기준: main `6b38d21c`(2026-09-07 #1021 착지 후)** — 상태 열은 그 시점의 착지 여부이며 브랜치·PR은 세지 않았다.

| 정정 대상 | CLI | 상태(main 기준) |
|---|---|---|
| done 증적(artifact) — PR이 done *이후*에 열린 경우 | `amend <id> --artifact <PR/커밋> --reason '...'` — append만(증적 삭제는 위조 표면) · PR 참조가 들어오면 `--no-pr` 보류를 자동 해소 | HARN-57 ①② · main 착지(#1021) |
| title 정정(옛 처방이 next에 노출되는 것을 막는다) | `amend <id> --title <제목> --reason '...'` — 교체·이전 값 notes 기록 | HARN-57 ⑤ · main 착지(#1021) |
| paths(작업 범위 — 넓은 glob 좁히기) | `amend <id> --path <glob> [--path ...] --reason '...'` — 지정 목록이 새 paths 전체·이전 값 notes 기록 | HARN-57 ④/HARN-59 · main 착지(#1021) |
| depends_on 제거 | `amend <id> --remove-depends <full-id> --reason '...'` | HARN-67 ③ |
| requires_gates 탈착(오부착) | `amend <id> --remove-gate <G-id> --reason '...'` — 게이트 status 불변 | HARN-67 ⑤ |
| notes 어구 치환 | `amend <id> --notes-replace "구문자" "신문자" --reason '...'` — 구문자 정확히 1회 | HARN-67 ⑥ |
| **게이트 제목 정정** | `gates amend <G-id> --title '<새 제목>' --reason '...'` — 실효값 덮어쓰기 + 옛 값 `corrections[]` append | HARN-124 ① |
| **게이트 독촉 주기 정정** | `gates amend <G-id> --remind-after-days <N> --reason '...'` — status 불변(waive와 구분) | HARN-124 ⑤ |
| cancelled 복원 | (미구현) | HARN-69 · **todo(미착지)** |
| **ID 개명(rename)** | **미구현 — 의도적** | 태스크 미등재(상위 세션 결정) |

**rename을 열지 않는 이유(HARN-67 ⑦ 검토)**: ① 태스크 ID는 파일명·이벤트 대장·원격 claim ref·
타 태스크의 `depends_on`·커밋 메시지·문서 인용에 퍼져 있어 개명은 **전역 치환 + 원격 claim 재게시**가
된다 — 한 곳이라도 빠지면 계보가 끊긴다(그 자체가 새 정정 경로 부재를 만든다). ② 개명이 필요한
사고는 전부 **등재 시점 번호 충돌**이었고(EOS-98 ↔ #994), 그것은 `backlog.py add`의 원격 claim까지
보는 충돌 검사(HARN-10)와 미사용 번호 제안(HARN-73)이 예방한다 — 사후 개명보다 사전 거부가 싸다.
③ 충돌이 이미 난 뒤의 정정은 `cancel`+재등재로 **번호 하나**를 태우는 것이 전역 치환의 실패
표면보다 싸다. 후속 태스크 등재 여부는 상위 세션이 결정한다.

테스트: `uv run --with pytest --with pyyaml pytest tests/harness` (2026-08-10 실측 251건 —
문서 수치는 스냅샷이며 정확 수는 pytest 수집이 정본. CI `harness-integrity` 잡이
`pytest tests/harness -q`로 무작위 순서 포함 실행 — CI의 `-q`는 화면 축약일 뿐 판정이
exit code이므로 "출력 억제·잘라내기 판정 금지" 금기(CLAUDE.md 2026-08-09)의 위반이 아니라
준수 사례다. 사람이 손으로 재현할 때는 `-q` 없이 돌리고 exit code를 병기할 것).

## 8. 금기

- ❌ backlog 상태를 마크다운 산문에만 기록하고 CLI 갱신 생략
- ❌ **`get_status`로 CI 상태를 판정하기 (HARN-30)** — MCP `pull_request_read method=get_status`(= commit status API)는 이 저장소에서 **항상 `total_count: 0`**을 낸다. 이 저장소는 commit status가 아니라 **check runs**를 쓰기 때문이며, 체크런 16건이 확실한 PR에서도 0이 나온다(2026-08-11·2026-08-31 두 차례 실측). 이걸 판정에 쓰면 "CI가 안 돌았다"는 오판을 낳는다. **대신 쓸 신호**: `GET /repos/{repo}/commits/{sha}/check-runs` · `GET /actions/runs?head_sha=<sha>` · MCP `pull_request_read method=get_check_runs`. 열린 PR 전수 점검은 `python3 scripts/ops/pr_delivery_audit.py <owner/repo>`(체크런 0건 ↔ green 미머지를 처방과 함께 구분·exit 1=주의 필요).
- ❌ **"미머지 PR"을 한 덩어리로 보기 (HARN-30)** — **트리거 미발화**(체크런 0건 → *깨워야* 한다)와 **조건 충족 미머지**(→ *사람 결정* 대기)는 처방이 정반대다. 전자는 **무증상**이라 아무도 보지 않으면 조용히 방치된다(실측: `pr_delivery_audit` 첫 실행에서 열린 PR 13건 중 미발화 5건·조건충족 미머지 7건). 깨우는 방법은 **`origin/main` 재병합 push**이며, 빈 커밋·PR 재개폐는 이 저장소가 금지한 경로다.
- ❌ **머지 전에 *전체* CI를 기다리기 (HARN-32)** — 머지를 막는 것은 전체 CI가 아니라 브랜치 보호가 지정한 **필수 체크 6종**뿐이다. 이 저장소의 최장 잡 `backend — lint·type·test`(~30분)는 **필수 목록에 없다**(2026-08-31 API 실측 — `GET /repos/{repo}/rules/branches/main`). 실측 중앙값: 필수 완주 **6.5분** vs 전체 완주 **28.6분**. main은 **40.7분**마다 전진하고 규칙이 `strict_required_status_checks_policy: true`(머지 시점 up-to-date 요구)이므로 **대기 시간이 곧 패배 확률**이다 — 필수만 대기 ≈16%, 전체 대기 ≈70%. 판정은 `python3 scripts/ops/pr_merge_readiness.py <owner/repo> <pr>`(exit 0=지금 머지), 재측정은 `scripts/analysis/measure_merge_gate_latency.py`. (사고 경위: 2026-08-31 PR #916이 전체 CI를 6회 기다려 머지 시도 3회가 전부 base 전진으로 실패했다. 그 지연 창에서 차단 2건이 무력화됐다 — HARN-48 참조)
- ❌ **차단·게이트 같은 보호 조치를 "대장에 썼으니 발효했다"고 보기 (HARN-48)** — 태스크 YAML은 **main에 머지돼야** 병렬 세션에 보인다. 이 저장소의 머지 지연은 CI(~30분)와 base 전진 경합(HARN-32)으로 시간 단위이며, 그 창 전체가 보호 공백이다. **대장 조치의 실효 시점은 조치 시점이 아니라 머지 시점**이다. 머지 없이 즉시 전파되는 채널은 `harness-claims` 브랜치뿐이므로 차단은 그 채널에 게시한다(`block`이 자동 수행). 게시가 실패하면 CLI가 "이 차단은 로컬에만 있다"를 경고한다 — 그 경고를 봤으면 보호가 없는 것이다. (사고 경위: 2026-08-31 `CUR-11` — block 00:28:07 → 13분 뒤 타 세션 claim 00:41:24 → 그 세션이 구현·머지 완료(#920). 차단은 대장에 실재했고 `next`에서도 사라졌으나 아무것도 막지 못했다)
- ❌ **태스크 정정을 문서에만 착지시키고 acceptance에 반영하지 않기 (HARN-24)** — "문서가 소유자"라는 우회는 착수 세션이 그 문서를 읽을 때만 성립한다. 태스크 YAML은 *반드시* 읽히지만 참조 문서는 선택이다. 정정은 `amend`로 acceptance에 도달시킨다. (사고 경위: ADMIN-02의 범위 축소 정정이 `operations_platform_gap_review.md`에만 있고 acceptance에 없어, 그 정정을 조상으로 가진 세션이 stale acceptance ②를 그대로 집행해 `subscription_*` 3컬럼까지 드롭 — 커밋 b3a58b02)
- ❌ 증적(artifact) 없는 done
- ❌ **PR 참조 없는 done** — 산출물이 있으면 요청 없이 PR을 여는 것이 기본값이다(CLAUDE.md "완료·병합"). 증적에 `#12`·`.../pull/12`가 없으면 CLI가 exit 1로 거부하며, 예외는 `--no-pr {investigation|incomplete|ci-red|kiki-hold}`로만 통과한다(HARN-23). 스쿼시 머지 커밋의 `(#758)` 관례는 그대로 통과 — 기존 증적 표기를 바꿀 필요 없다
- ❌ evidence 없는 게이트 clear
- ❌ E축 게이트 우회 착수 (waive는 Kiki 전용 결정)
- ❌ ROADMAP "현재 위치"를 backlog와 어긋나게 단독 편집
- ❌ 원격 claim conflict를 무시하고 착수 (남의 claim 강제 해제는 `claims release --force` — 상대 세션 확인 후)
- ❌ 홀더 브랜치 생존 확인 없이 `--ignore-remote-claim` 사용 — 확인 명령(`git log -1 --format='%cr %h %s' origin/<branch>`)은 거부 메시지에 동봉된다. 살아 있는 세션이면 그 순간부터 중복 구현이다
- ❌ 과탐 1건 때문에 `--no-remote`로 보호 전체 끄기 — 태스크 단위 우회(`--ignore-remote-claim`)가 있다
- ❌ 측정(policy report) 없이 warn→block 승격, 또는 결정로그 없는 승격
- ❌ **산출물을 검수하는 게이트를 그 산출물을 *만드는* 태스크에 걸기 (2026-09-06 등재)** — `requires_gates`는 `done` 조건이 아니라 **착수 조건**이다(`selector.py:6` — 후보 = 게이트 전부 cleared/waived). 회차 산출물을 사람이 검수해야 clear되는 게이트를 회차 태스크에 걸면 *회차 전엔 검수할 것이 없고 검수 전엔 회차를 못 시작하는* 교착이 된다. 검수 게이트는 **그 산출물을 소비하는 후속 태스크**에 건다(선행 태스크 = 산출, 후속 태스크 = `depends_on` 선행 + `requires_gates` 검수). 오부착은 `amend <id> --remove-gate <G-id> --reason '...'`로 뗀다(HARN-67 ⑤ — 그 전에는 `amend`가 부착 전용이라 `cancel`+재등재로만 고칠 수 있었고 번호가 소모됐다). 탈착 경로가 생겼어도 등재 전에 `next --n 500 --json`으로 노출 여부를 확인하는 편이 싸다. (사고 경위: 2026-09-06 `MP-01`에 `G-eos-first-run-canary-review`를 걸어 교착 → `MP-02`(회차)·`MP-03`(골든 승격·게이트+의존)로 분리 재등재. 정정 경로 부재로 인한 번호 소모 3회차 — EOS-94·96·MP-01)
- ❌ **제안기의 "00~99 모두 소진" 문구를 실측 없이 사실로 등재하기 (2026-09-06 등재 · 같은 날 정정)** — `TASK_ID_RE`(`models.py:109`)는 정확히 2자리만 허용하고 `_next_free_number`는 3자리를 날조하지 않고 `None`을 내 `add`가 거부한다(HARN-21) — 여기까지는 맞다. 그러나 그 거부 문구가 말하는 "소진"은 **최대+1 방향만 본 결과**였고, 실측(모든 ref 이력 전수 · HARN-73)은 EOS 번호 **사용 59·미사용 40**(01~05·07~27·29~31·33~43)이었다. 대응은 새 접두가 아니라 **하위 미사용 번호 재사용**이다(Kiki 결정 A · `G-eos-task-prefix-exhausted` clear · 제안기가 하위 폴백을 하도록 HARN-73이 고쳤다). 3자리 손제작 금지는 그대로다. `MP`(#1000)는 소진 대응이 아니라 *회차 축* 접두로만 남는다 — EOS 축 태스크는 계속 `EOS-nn`을 쓴다. (사고 경위: 2026-09-06 PR #1000이 CLI 문구와 `ls | max` 추론만으로 "현재 소진된 접두: EOS"를 이 절에 등재했고, 같은 날 타 세션(#1001)도 같은 문구로 결정 게이트를 열었다 — **두 세션이 같은 도구 출력을 실측 없이 사실로 옮겼다**. "환경 사실의 추론 등재 금지"(CLAUDE.md)의 *도구 출력* 축: 도구가 내는 판정 문구도 환경 사실이 아니라 도구의 주장이다)
