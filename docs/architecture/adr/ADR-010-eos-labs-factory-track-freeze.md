# ADR-010 — EOS-LABS Factory 트랙(`C:\EOS-LABS`, doldori7/eos-* 5개 저장소)을 동결하고 참고자료로만 둔다

- **상태:** **Accepted** (Kiki 2026-10-19, 선택지 (가) — 감리 정본 D8·D9)
- **결정일:** 2026-10-19 (저장소 등록 2026-10-23 · `ARCH-104`)
- **대상:** `C:\EOS-LABS` = `doldori7/eos-labs-factory`·`eos-orchestrator`·`eos-lab-contracts`·`eos-whymath-governance`·`P001-math-error-lab` + 로컬 전용 `eos-math-internal`·`eos-math-contracts`
- **관련:** 감리 재정정보고서 2026-10-19 · `HARN-206`(저장소가 EOS-LABS를 "참고 프로그램"으로 언급한 유일한 곳) · 1차 감리 결함 #12·#14·#16·#17·#20·#27·#28·#29(B 트랙 전용) · `docs/strategy/internal_verification_period_policy_2026-12-31.md` 규칙 1·2 · [ADR-007](./ADR-007-eos-g2-disposition.md)

---

## 맥락 (사실만 — 판정 기준 main `0523e19e`, 2026-10-23 재대조)

- 코드베이스가 둘이다. (A) 실제 제품 `kiki-s-broom/WhyMath`(Python 3.12 · FastAPI · PostgreSQL 16 · Flutter). (B) "EOS Micro-Application Factory 버전" `C:\EOS-LABS`(Orchestrator Python/SQLite, 계약 Node+ajv, Factory PowerShell, 앱 Next.js 16+Prisma+mathjs). (B)는 저장소 밖(Kiki 머신)에 있어 이 저장소에서 열람할 수 없다.
- 1차 감리(10/18)는 (B)만 열람했고 결함 30건 중 11건이 (A)에 대해 틀렸다(감리 재정정보고서).
- (A)는 자체 EOS 전환 선언(`docs/strategy/eos_transition_declaration_2026-08-30.md`)과 G0~G5·`G-internal-completion-2026-12-31`을 가지며 G0을 통과했다. **(A) 저장소가 (B)를 언급하는 곳은 `backlog/tasks/HARN-206-work-graph-desktop-app.yaml` notes 1곳뿐이다**(2026-10-23 `git grep -i` 재실측: `EOS-LABS`·`eos-orchestrator`·`eos-lab-contracts`·`eos-whymath-governance`·`eos-math-internal`·`eos-math-contracts`·`eos-work-graph`·`P001-math-error-lab` 전부 합쳐 이 1건 — 이 ADR 파일 제외).
- 2026-10-19 같은 날 저장소 안에서도 10/8 문서를 정본으로 인용한 작업(`ARCH-103` — `eos/compiler/` TypeScript — 47개 파일 추가분 합계 약 2,750줄(lockfile·fixture·yaml 포함, `eos/compiler/src`만은 약 465줄), 브랜치 `claude/eos-compiler-pack-check` 헤드 `d7c8a365`, 원격에 실재)이 생겼다. 비정본 표식이 저장소에 없어서 생긴 일이다. Kiki D8=(가)로 보류했다.
- (B)의 앱 원격 `P001-math-error-lab`은 2026-10-03 상태에서 멈춰 있고 10/5 대응표의 폐쇄루프 코드(`composition.ts`)는 미푸시다. (B)의 거버넌스는 (A) 헌법의 이식본이며 95/95 unverified다(감리 열람 기록 — 저장소 밖).
- 개발자 1인, 12/31까지 약 260h(`eos_transition_declaration` :117의 주 25h 상한 × 약 10.4주).

## 결정

1. 2026-12-31까지 (B)에 커밋·푸시·이슈 생성을 하지 않는다. `C:\EOS-LABS`는 삭제하지 않는다.
2. 감리·이행계획·ADR·엑셀·Claude Doc은 (A) 단독 기준으로 다시 만든다(재감리보고서 2026-10-19).
3. (B)에서 (A)로 옮길 가치가 있는 부품(Manifest v2 스키마, admission 24 스키마, `dependency_boundary.mjs` 발상)은 **목록만** 작성하고 이식은 2027-01 이후 새 ADR로 정한다.
4. 설계 문서 10/8·10/5·대응표 가운데 (B)를 서술한 부분과, 저장소 결정과 충돌하는 계획서 500·600은 **적용하지 않는다** — 그 처분은 아래 **부록 A**가 문서별로 기록한다. (A) 정본 순서는 `internal_verification_period_policy_2026-12-31.md` 규칙 1이 정한다: `gates.yaml` > ADR-007 및 후속 ADR > EOS 전환 선언 > 설계 문서 100·200·400. 500·600·10/8·10/5 문서는 적용하지 않는다.

## 대안과 기각 이유

- **(나) 병행 개발**: 기각. 1인이 두 코드베이스를 유지하면서 (A)의 G2~G5를 통과할 수 없다.
- **(다) 즉시 흡수**: 기각(연기). 이식이 12월 일정을 잠식한다.

## 결과

- 1차 감리 결함 #12(git.exe 절대경로)·#14·#16·#17은 해결하지 않고 기록만 남긴다.
- 1차 감리 WP-02~05(대상 `eos-math-internal`·`composition.ts`·`output-envelope`)는 폐기된다.
- `ARCH-103`(`eos/compiler/`)은 머지하지 않고 브랜치를 참고로 보존한다(D8=(가)). 재검토는 2027-01, [ADR-008](./ADR-008-optional-tier-minimum-set-and-fallback.md)(선택층 최소집합) 결과와 함께.

## 중단 규칙 (되돌림 조건)

- (A)가 12/31 내부 완성 판정에서 "미완"이 나고 그 원인이 (B)가 이미 해결한 문제일 때 새 ADR로 재논의한다.

---

## 부록 A — 설계 문서 트랙·처분표 (감리 W-07 · `ARCH-104` ②)

> **판정 기준: main `0523e19e`(2026-10-22)**. 아래 "저장소 안/밖"은 추측이 아니라 실측이다: `git ls-files`에 해당 문서 파일이 없고(파일명에 `500`·`600`·`계획서`·`phase`·`small`·`pack`이 든 문서 전수 확인), `git grep -I`로 전 저장소를 훑어도 `계획서 500`·`계획서 600`·`1,000 users`·`공식 출시`·`Small App`·`Pack Installer`·`Capability Pack`·`Domain Pack`·`eos check`가 **0건**이다. `MAP01`~`MAP23` 문서도 없다(`MAP` 번호 계열 0건). 원문은 Kiki 머신·감리 세션에만 있다.
> 원문을 **복제하지 않는다** — 문서명·트랙·충돌 지점·처분만 적는다. 문서 내용 인용은 감리 열람 기록(`감리 정본 05_증거/증거D`, 저장소 밖)에서 온 것이다.

| 문서 | 위치 | 트랙 | 저장소 결정과의 충돌 지점 | 처분 |
|---|---|---|---|---|
| 계획서 500 (Phase 4 · Beta·QA·성능) | **저장소 밖** | WhyMath 계획서 계열이나 **미채택**(인용 0회) | Beta 코호트·"100/500/1,000 users 동시" 부하 목표. 저장소는 학생 참여 과정 전부를 12/31 이후로 미뤘다(`ARCH-66` ⑥ · 게이트 `G-student-work-after-internal-completion`) | **적용 안 함**(정본 순서 규칙 1). 2027 범위 참고자료. 저장소 안에 표식을 붙일 파일이 없다 |
| 계획서 600 (Phase 5 · Release Candidate·Launch) | **저장소 밖** | WhyMath 계획서 계열이나 **미채택** | "12/31 = Math EOS v1.0 **공식 출시**". 저장소는 **12/31 = 내부 검증 판정일**이다(`eos_transition_declaration` §0-2 · 게이트 `G-internal-completion-2026-12-31`) | **적용 안 함**. 12/31의 뜻은 선언 §0-2가 단독 정본 |
| 10/8 이상적 아키텍처 (Small App Pack · DSL · Compiler) | **저장소 밖** | **EOS-LABS(B) 트랙** — TypeScript 모노레포·pnpm·Turborepo·XState·pg-boss 전제 | 저장소는 Python/FastAPI/Alembic(리비전 116)/Flutter이고 `src/eos/`·루트 `eos/` 신설을 2026-08-25 결정으로 보류했다. "7계층"이라는 같은 말이 전혀 다른 분해(10/8: Constitution~App · 저장소 `00_overview.md`: L1 데이터~L7 커뮤니티)를 가리킨다. 개념 545·오개념 400+55+108·PR 850/1,500은 실측(437·843·#1698 계열)과 다르다(감리 W-26) | **적용 안 함**. (B) 서술이므로 이 ADR 결정 4로 동결. 수치는 저장소 코퍼스 실측이 정본 |
| 10/5 검토 (Small App Pack · DSL · Compiler 검토) | **저장소 밖** | EOS-LABS(B) 트랙 | 10/8과 같음. 10/5↔10/8이 서로 상반되는 결정 6건(설치기 vs Compiler · Nx vs Turborepo · Prisma vs Atlas · Pact/OPA · Pack SemVer · Adapter 수)을 가졌는데, 저장소는 6건 모두 **해당 없음 또는 다른 답**(import-linter · Alembic · 콘텐츠 버전은 `44_eos_version_management.md` · Adapter는 ADR-004)을 이미 가졌다 | **적용 안 함**. 부품 이식은 결정 3(목록만 · 2027-01 새 ADR) |
| 10/5 대응표 (MAP01~MAP23) | **저장소 밖** | EOS-LABS(B) 트랙 **전체** — M00~M14 단계, `createP001MathProvider`, server-local-test principal, Stryker 등 `P001-math-error-lab` 요소 | 저장소에 M-단계·P001·Stryker가 0건이라 대조 대상 자체가 아니다 | **적용 안 함**. 대조 불요 |

**저장소 안에서 같은 말을 하는 문서** (표식 대상): `docs/strategy/phase3_math_eos_completion_plan_source.md`(계획서 400 전사본)의 로드맵 표(:53-54)가 "Phase 4 Beta·QA·성능 안정화 / Phase 5 출시 — Math EOS v1.0"과 제목 "12월 말 출시 계획"을 담는다 — 500·600과 같은 출시 프레임이다. 이 문서는 저장소가 **채택**한 입력(`P3-*` 태스크로 변환됨)이라 폐기가 아니라 머리말 표식을 붙였다(전사 본문 무수정). 같은 입력에서 파생된 `phase3_math_eos_completion_instruction_set.md`("Not Now List(12월 출시 이후로 보냄)")·`..._backlog_crosswalk.md`("v1.0(12월 출시) 이후 첫 계획 세션", 게이트 `G-not-now-v1-release-recheck`)도 "12월 출시" 어휘를 쓰지만, 이는 범위 이월 목록의 표현이지 Beta·공식 출시 약속이 아니다. 전사 원본(194KB)과 게이트 문면을 바꾸지 않기 위해 표식을 더하지 않았고, 12/31의 뜻은 선언 §0-2가 단독 정본이다(잔여 어휘 — 2027-01 정리 후보).

**참고 — 이 표에 넣지 않은 것**: 계획서 100·200·300은 저장소가 채택(100·200) 또는 참고 강등(300, 2026-09-03 Kiki)했고 이미 ADR 매핑표(`README.md`)·갭 리뷰 문서가 소화했다. `docs/standard-book/06_4장_...SSOT.md`:46의 `WhyMath_EOS_2026_12월출시_기능재배치.xlsx`는 파일명 언급 1줄(예시 표)이며 저장소 안에 없다 — 표식 불요, 12/31의 뜻은 선언 §0-2가 정한다.
