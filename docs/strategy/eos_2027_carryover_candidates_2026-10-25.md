# EOS 감리 이월 후보 5건 — 2027-01 첫 계획 세션 입력 (2026-10-25)

> 판정 기준: main `faf740c5` (2026-10-25). 출처 = EOS 아키텍처 감리 정본(2026-10-19) 결함 W-10·W-11·W-12·W-20·W-24와 권고 R-11.
>
> **이 문서는 게이트가 아니다.** 12/31 내부 검증 기간 방침(`internal_verification_period_policy_2026-12-31.md`) 규칙 2는 이 기간에 신규 decision 게이트를 만들지 않고, 규칙 3은 CORE/MIXED 모듈 안의 수학 상수를 건드리지 않는다고 정한다. 그래서 감리 권고 R-11("2027 이월 게이트 등재")은 새 게이트 5건이 아니라 **이 후보 목록 + 기존 게이트 `G-eos-g5`(12/27 동결 → 12/31 판정 + 2027 범위 결정)의 입력으로 연결**하는 방식으로 이행한다. 이월이 기록 없이 사라지지 않게 하는 것이 목적이다.
>
> 아래 현황은 이 문서를 쓴 시점에 `main`에서 다시 읽은 것이다. 수치가 필요한 항목은 "2027-01에 재측정"으로 남기고 감리 시점 수치를 현재값처럼 쓰지 않았다.

## 후보 5건

| # | 결함 | 지금 코드의 모습 (파일:행) | 왜 12월에 하지 않는가 | 2027 재개 시 첫 확인 |
|---|---|---|---|---|
| 1 | **W-10 `Problem.subject`는 과목 축이 아니라 수능 선택과목 축** | `db/models/problem.py:143` `subject`는 NOT NULL PG enum. `schema/enums.py:95` `Subject`는 5값(공통·미적분·확통·기하·인공지능수학)이고 docstring이 "타 과목 값 ADD VALUE 금지, 교과 축은 향후 `Problem.subject_area`로 별도 신설"이라 적는다. `Problem` 모델에 `subject_area`는 없다(grep 0건). | 스키마 마이그레이션이라 12월 동결(G5 12/27)과 충돌하고, 타 과목 문항이 12월에 적재될 일이 없다. | 트리거("물리 문항 첫 적재")가 실제로 왔는지. 왔다면 `subject_area` 신설 ADR부터. |
| 2 | **W-11 CORE 파일 안의 수학 데이터 상수** | `l3/pedagogy/slot_generator.py:129-138,158`(프롬프트 예시가 이차함수 `f(x)=x^2-4x+c`), `schema/enums.py:30,63`(`SourceType`·`ExamType`이 한국 수학 시험 어휘), `l6/suneung/scope.py`(성취기준 코드 파싱), `l4/misconception/catalog.py`(오개념 코드 상수 — 개수는 테스트가 동결). | 방침 규칙 3: 발견해도 건드리지 않고 후보로 기록만 한다. 옮기면 동결된 데이터·테스트가 함께 움직인다. | 경계 스캔(`scripts/analysis/eos_core_adapter_boundary_scan.py`)에서 해당 파일의 CORE 분류가 그대로인지, 두 번째 과목이 실제로 들어오는지. |
| 3 | **W-12 `/v1/verify`가 능력 계약을 거치지 않고 수학 모듈을 직접 호출** | `api/verify.py`가 `l3.verify_answer/verify_solution/verify_step`을 직접 호출. import-linter 계약 "EOS Core → Math Adapter 금지"의 면제 목록(`src/backend/pyproject.toml`의 `ignore_imports`, 259행·396행 부근)이 그 결합을 덮고 있다. 설명 정본은 ADR-008. | 필수층 메서드 변경은 CI 적색이고(방침 규칙 2) 코드 이행은 ARCH-67 결과 후 별도 ADR(ADR-008)이 정한다. | `ignore_imports` 줄 수를 다시 센 값과 ADR-008 "열린 쟁점"(필수 3종 대 1종)의 Kiki 선택. |
| 4 | **W-20 고지 파일 없음 + TexTeller 가중치 라이선스 미결** | 저장소에 `NOTICE*`·`THIRD_PARTY*`·`OFL*` 파일이 없다(깊이 4까지 `find`, "내가 찾은 방법으로는 0건"). KaTeX 폰트(SIL OFL 1.1)·MathLive(MIT)·mathjs 등 번들 위치와 고지 의무는 감리 증거 C 참조 — 저장소 안 위치는 2027-01에 다시 확인. TexTeller는 `docs/data/licensing_safety.md:144`에 "가중치 라이선스 배포 시 재확인"으로만 적혀 있다(기본 비활성). | 외부 배포 전에 필요한 것이고 12/31까지는 내부 검증이라 배포가 없다. 변호사 검토는 12/31 이후 재개(`G-external-counsel-restart-after-internal-completion`). | 외부 배포 일정이 잡혔는지. 잡혔다면 고지 파일 생성과 TexTeller 가중치 확인이 배포 선행 조건이다. |
| 5 | **W-24 헌법 규칙 대부분이 실제 집행 경로가 없다** | `constitution/rules.yaml`에 규칙 95건, 모두 `check` 필드를 선언한다(예: `R0-01` → `.claude/hooks/guard_constitution.py`). 감리 시점에는 이 경로가 실재하는 규칙이 16/95였고 래칫 기준선은 차단 0건이었다 — **현재 값은 2027-01에 재측정**한다. 통과는 "심사 대상이 적다"는 뜻이지 집행을 뜻하지 않는다. | 방침 규칙 2: 신규 헌법 규칙·HARN 착수 동결. 기존 규칙의 집행 경로를 채우는 일도 HARN 성격이다. | `check` 경로 실재 비율과 래칫이 실제로 막은 건수. |

## 이 목록을 어디에 연결했는가

- `backlog/gates.yaml`의 `G-eos-g5`(12/27 동결 → 12/31 판정 + 2027 범위 결정) 노트에 이 문서를 가리키는 한 줄을 남겼다. 12/31 판정 세션이 "2027 범위"를 정할 때 이 5건이 입력으로 보인다.
- 5건은 모두 **차단이 아니라 기록**이다(감리 WP-E 노트). 12/31 판정 조건(①Phase 3 ②G5 ③산출물 커밋)에 들어가지 않는다.

## 이 문서가 하지 않는 것

- 새 게이트·태스크·헌법 규칙·CLAUDE.md 규칙을 만들지 않는다.
- 재개 날짜를 정하지 않는다. 날짜는 목표이지 하한이 아니며(build_harness §3a), 순서는 내용 선행으로만 정해진다.
- 수치를 현재값처럼 단정하지 않는다. 표에서 "재측정"이라 적은 곳은 그 시점에 다시 센다.
