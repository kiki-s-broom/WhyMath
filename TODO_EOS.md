# TODO_EOS.md — EOS(Small App Pack + DSL + Compiler) 체크리스트

판정 기준: main `fa8d83d` (2026-10-19) · 설계 정본: 『EOS 멀티과목 수학앱 이상적 아키텍처 — Small App Pack + DSL + Compiler』(2026-10-08) §15 "매주 금요일 Gate 기준 대비 진행률을 체크리스트(TODO_EOS.md)에 기록"

이 파일은 사람이 매주 갱신하는 진행 체크리스트다. 태스크의 정본은 `backlog/tasks/`(대장)이며, 여기에는 대장 ID를 적어 연결한다.

## 1. 완료

| 날짜 | 항목 | 대장 ID | 증거 |
|---|---|---|---|
| 2026-10-19 | pack.yaml(eos.pack/v1) 로더·검증기 + `eos check` CLI — Compiler 파이프라인 ①(구조)·③(의미) 중 Pack 선언 부분 | ARCH-103 | `eos/compiler/` · vitest 15/15 · `tsc --noEmit` 통과 |

## 2. 설계 문서 정정 필요 (검토 2026-10-19에서 발견)

문서를 고치기 전까지 코드는 아래 결정을 따른다. 문서를 고치면 이 표의 행을 지운다.

| # | 문서 위치 | 발견 | 코드가 택한 결정 |
|---|---|---|---|
| F1 | §7 | DSL 파일 5종인데 "JSON Schema 4개"·"네 파일" | 스키마는 5개(part.yaml 포함)로 간주 |
| F2 | §7 ① vs §4 | app.yaml 예시 `answer-evaluation.v1`이 계약 9개 목록에 없음 | 9개 고정, `assessment.v1` 오기로 간주. 10번째는 ADR 필수 |
| F3 | §7 ② vs ④ | pack.yaml `kind: content`와 content.yaml 중복 | pack.yaml kind = `capability \| domain`. content는 content.yaml 전용 |
| F4 | §7 ①② | pack.yaml `apps`는 짧은 이름, app.yaml `id`는 `Pack.App` | 전체 App ID = `<pack.id>.<app>` 파생 |
| F5 | §7 ② | `subject_adapter: required`의 반대값 미정의 | `required \| none` |
| F6 | §7 ① vs §10 | app.yaml `rules` 이름 형식이 규칙 ID(`DATA-002`)와 다름 | app.yaml 검증기 착수 시 규칙 ID로 통일 |
| F7 | §4 vs §13 | `products/whymath/eos.lock`이 고정하는 대상 미기술 | 보류 |
| F8 | §12 | `PACK_REQUIRES_DOMAIN`(capability가 domain을 requires 금지)은 ARCH-004에서 추론한 규칙 | 오류로 구현하되 "추론 규칙" 주석. 문서가 부정하면 제거 |
| F9 | §5 | Small App 5~7개는 "적정 크기"이지 실패 조건이 아님 | `PACK_APPS_RANGE`는 경고(exit 0) |

## 3. 후속 작업 (대장 등록 전 — 등록하면 ID를 적는다)

- [ ] 모노레포 전환: 루트 `pnpm-workspace.yaml` + `turbo.json`, `eos/compiler`를 워크스페이스로 편입 (§13). 현재는 `eos/compiler/package.json` 단독 실행
- [ ] 루트 CI에 `eos/compiler` 잡 배선(`npm test` + `tsc --noEmit`). 미배선이면 회귀를 못 잡는다
- [ ] DSL 스키마 4종 추가: `eos.app/v1`, `eos.content/v1`, `eos.product/v1`, `eos.part/v1` (§7). app.yaml은 provides 정확히 1개·consumes 3개 이하·계약 닫힌 목록 9개
- [ ] `eos check`에 product.yaml 교차 검사: `packs`·`domain`·`content` 목록의 실재, `flags` 키가 `packs` 안에 있는가
- [ ] Content Pack 검사 4종(§5): acyclic-prerequisites · misconception→concept 실재 · copyright-tier-present · curriculum-mapped
- [ ] `eos graph`(의존성 그래프 출력), `eos packet <app>`(Context Resolver, §11)
- [ ] Constitution 기계 규칙 `rules.yaml`에 ARCH-003(선언 안 한 계약 사용 금지)·ARCH-005(compiler에서 AI SDK import 금지) 등재 + dependency-cruiser 설정
- [ ] 종이 시험(§12): 물리·화학 pack.yaml과 Adapter 5개 서명 초안을 `eos check`로 통과시켜 본다

## 4. 주간 Gate 점검 (매주 금요일)

| 주차(금) | Gate | 기준 | 진행률 | 밀림 | 범위 축소 결정 |
|---|---|---|---|---|---|
| 2026-10-24 | — | — | — | — | — |

Gate가 2주 이상 밀리면 일정을 늘리지 않고 범위를 줄인다. 줄이는 순서: Learning Pack → Constitution 기계화 개수 → Golden 세트 크기(3,000 → 1,000, 목표 정확도 99.7%).
