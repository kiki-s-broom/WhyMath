# PB-25 판정 — 게이팅·청사진 후보 fetch 상한 3,000

판정 기준: main `f212a276` · 측정일 2026-10-26 · 태스크 `PB-25`

## 결론

**prod에서는 지금 절단이 일어나지 않는다 — 완료 조건 ①에 따라 코드 변경 없이 닫는다.** prod `problem`은
1,703건으로 상한 3,000 아래다. 다만 상한을 넘는 순간(전 은행 적재) 학생 후보의 약 80%가 고정적으로 빠지므로,
그 전에 풀어야 할 두 문제를 후속 태스크로 분리했다(아래 「후속」).

## 측정

### ① prod 실측 (Kiki 머신 · docker `whymath-pg` · 읽기 전용 · 2026-10-26)

- `problem` 1,703건. 은행 접두(`slug`의 마지막 `-` 앞)별 전체 건수와 상위 3,000건 안 건수가 **전부 같다** — 절단 없음
- 들어 있는 것: `wm-misc-eval-mc` 1,080 · `wm-skel` 184 · 자체 생성(`wm-arseq`·`wm-calc-*`·`wm-exp`·`wm-log`·`wm-trig*` 등) 435 · `wm-quad-*` 4
- 문제은행 39개 중 나머지(2026-08-09 회수 배치·P3 은행 등)는 **prod에 적재돼 있지 않다**. 코퍼스 전체 건수는
  `docs/data/corpus_facts.md`의 `problem_bank.total`
- `created_at`·`updated_at`이 **전 행 NULL**이다(아래 ②)

### ② 로컬 재현 — 전 은행 적재 시 (PostgreSQL 16 · `populate --all` · 원자 백본 선적재)

- 전 은행을 적재하면 후보 조회(`api/gating.py` `_fetch_candidates`)가 상위 3,000건만 넘기고 나머지는 학생 6개 모드
  (`/retake`·`/suneung`·`/school-progress`·`/thinking`·`/metacognition`·`/gifted`)와 청사진 조립에서 한 번도 후보가 되지 않는다.
  절단 경고 로그가 매 요청 `truncated=11742`로 난다
- 적재 시각이 NULL이라 정렬 `created_at desc`가 무의미하고 동률을 `problem_id`(무작위 UUID)가 가른다 — 은행이 통째로
  빠지기보다 **모든 은행에서 약 80%가 고정적으로 빠진다**(39개 중 1개 은행은 0건 진입). 주석이 말하는 "최근 적재분 우선"은
  지금 성립하지 않는다
- 지연(로컬 · 5회 중앙값): 후보 조회 상한 3,000 → 0.99초 · 무제한(전량) → 3.95초 · 성취기준 주입까지(`_fetch_candidates_with_standards`)
  전량 4.9~6.2초. 게이팅 자체(메모리)는 전량에서도 2~42ms. 전량 얕은 복사 0.54초. 신선도 조회(건수·최대 수정시각) 13ms
- 따라서 **상한만 올리는 처분은 요청당 4~6초**라 쓸 수 없다. 남는 선택지는 ⓐ 후보 캐시(전량을 한 번 읽어 두고 바뀔 때만 다시)
  ⓑ SQL 사전 축소(과목·단원 키)다. ⓐ는 "게이팅이 단일 진실 게이트"라는 설계 규칙(`api/gating.py` 사전 필터 금지 주석)을
  지키지만 **내린 문항이 캐시 수명만큼 계속 나갈 수 있다**(저작권 — 의사결정 우선순위 2번). ⓑ는 그 규칙의 개정이 필요하다

### ③ 부수 발견

- `api/me.py` `_BLUEPRINT_CANDIDATE_FETCH_LIMIT = 3000`은 **정의만 있고 쓰이지 않는다** — 청사진은 `api/gating.py`의
  `_fetch_candidates`를 그대로 재사용한다
- `created_at`·`updated_at` NULL의 원인: 테이블 기본값은 `now()`인데 적재가 schema의 `created_at=None`을 명시적으로 넣어
  기본값을 덮는다(`db/models/problem.py` server_default · `schema/problem.py` 기본 `None`). 정렬·신선도 신호가 둘 다 죽어 있다
- ④ 절단 경고 로그가 prod·데모에서 실제로 났는지: prod가 상한 아래라 **나지 않았을 것**으로 판단한다(1,703 < 3,000).
  로그 파일 자체는 확인하지 못했다

## 후속

- `PB-26` — 문제 적재가 `created_at`·`updated_at`을 NULL로 덮어씀(정렬·신선도 신호 사망) — 적재 수정 + 기존 행 복원
- `PB-27` — 전 은행 prod 적재 전에 후보 조회 설계 결정(캐시 ⓐ 대 SQL 사전 축소 ⓑ · Kiki 판단) + 미사용 상수 정리 +
  전량 적재 런북(LIC-03)에 선행 조건 표기
