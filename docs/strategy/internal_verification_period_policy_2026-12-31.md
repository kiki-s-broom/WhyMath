# 12/31 내부 검증 기간 방침 (2026-10-20 ~ 12-31) — Kiki 지정 2026-10-19(D5)

> 집행: ADR-007 · G-eos-g1~g5 · backlog.py block(HARN-115·305·314) · selector EOS_DEFERRED. 이 문서는 방침이며 CLAUDE.md 산문 규칙이 아니다(등재 동결 조항 CLAUDE.md:223과 무관).
>
> 이 절은 2회차까지 CLAUDE.md에 있었으나, 독립 검토 지적(D7)에 따라 Kiki 결정 (a)로 본 문서로 이동했다. 본문은 이동 시점의 전문이며 규칙 내용은 변경하지 않는다(규칙 2의 예외 1줄만 추가).

Kiki 지정 방침(2026-10-19 D5)이며 사고 유래 산문 규칙이 아니므로 등재 동결 대상이 아니다(v0.2.31·v0.2.32 선례와 동일).

1. 코딩 헌법(constitution/)은 이 순서 밖·최상위다(기존 선언 '코딩 헌법 > CLAUDE.md > AGENTS.md' 유지). 아래는 그 다음 층의 순서다. 정본 순서: backlog/gates.yaml(저장소 게이트) > docs/architecture/adr/ADR-007(G2 개정) 및 후속 ADR > EOS 전환 선언 > 설계 문서 100·200·400. 500·600·10/8·10/5 문서는 적용하지 않는다.
2. 이 기간에 새로 만들지 않는 것: src/eos/ 또는 저장소 루트 eos/ 디렉터리(ARCH-103 claude/eos-compiler-pack-check d7c8a365 보류 — Kiki D8=(가) 2026-10-19, 2027-01 재검토), Pack·Compiler·설치기, Subject Adapter 필수층 메서드 변경(CI 적색), 신규 헌법 규칙, 신규 decision 게이트, HARN-* 착수(예외: CI가 있는 테스트를 수집하지 않는 결함 — OPS-137 류), Problem.subject enum 값 추가. 집행: eos_priority P2·P3 태스크는 selector가 기본 숨김(EOS_DEFERRED) · P1 HARN은 `backlog.py block --handover`로 2027-01-01까지 차단(작업 6) · 신규 등재는 Kiki 규율. 실수 관리 의무는 유지한다 — 시스템·반복 실수의 대책 *등재*(태스크·사고 대장)는 허용하고, *착수*만 D5 예외(CI 수집 결함) 또는 피해가 진행 중인 사고에 한해 허용한다. WP 밖 파일을 요구하면 멈추고 Kiki 승인 후 진행.
   - 이미 in_progress인 HARN 전건(2026-10-19 현재 HARN-56·HARN-210·HARN-300)은 완료까지 허용 — 이 방침은 신규 착수만 막는다. HARN-56은 타 세션 claim이므로 그 세션이 종료한다.
3. CORE/MIXED 모듈(경계 대장 BOUNDARY_MAP 기준) 안의 수학 상수(l4/misconception/catalog.py, l3/pedagogy/slot_generator.py, l6/suneung/scope.py, schema/enums.py)는 건드리지 않는다. 발견하면 2027 이월 게이트 후보로 한 줄 기록하고 멈춘다.
4. 측정 1건 = 런북 1회 실행 + 결과 파일 커밋 + MEMORY 3줄. 새 게이트를 만들어 측정을 미루지 않는다.
5. 완료는 명령 출력으로만 인정한다. "구현했다"는 보고가 아니다.
6. 작업 1건은 WP 하나 안에서만. 허용 경로 밖 파일을 고쳐야 하면 멈추고 보고한다.
