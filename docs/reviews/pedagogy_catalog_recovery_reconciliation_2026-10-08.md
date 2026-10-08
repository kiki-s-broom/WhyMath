# PED-26 — 교수전략 카탈로그 회수 정합 (gdmwhk · uqyg79 ↔ main)

> **시점 스냅샷 선언.** 판정 기준 = `main 8a5ea4d1`(2026-10-08) · gdmwhk head `2915bf4e` · uqyg79 head `5dc040b3`.
> 이후의 브랜치·PR·태스크 변화는 반영하지 않는다. **미머지 근거는 적지 않았다** — 아래 "main에 있다"는 전부 `main` 트리에서
> 확인한 것이고, 이 PR이 만드는 것(04g 문서·`REND-05`·`PED-44`·`ARCH-72`·`HARN-304`)은 머지 전까지 "착지"가 아니다.
>
> **방법의 한계(명시).** 이 세션의 클론은 shallow이고 두 브랜치는 `--depth=1`로 가져왔다. 그래서 **파일 트리(내용) 비교만** 했고
> 커밋 계보·ahead 수치는 확인하지 못했다. GitHub 조회로 확인한 사실은 둘: gdmwhk는 PR이 한 번도 열린 적 없고, uqyg79의
> PR [#675](https://github.com/kiki-s-broom/WhyMath/pull/675)는 **머지되지 않고 닫혔다.**

---

## 0. 결론

1. **코드·코퍼스·테스트 이식은 0건이다.** gdmwhk가 가진 카탈로그 자산(스키마·레지스트리·YAML 10종·후보 필터·전략 카드)은 전부 main에 이미 있고,
   main이 **더 새롭다**(`PED-22`~`PED-25`가 2026-08-15에 착지, 이후 후행 갱신). 오히려 gdmwhk판을 채택하면 회귀 2종(아래 §1.1)이 생긴다.
2. gdmwhk만 가진 **판정 축**(어댑터 갭 재판정·해제 조건 2행·재현 부록)은 `docs/architecture/04g_pedagogy_strategy_catalog.md`에 **병합**했다.
3. `04e` 문서번호 이중 점유를 **04e → 04g**로 해소했다(04e는 먼저 쓰인 오개념 교정 설계가 유지). 같은 검사에서 `03c`도 중복임을 찾아 `ARCH-72`로 분리했다.
4. main에 대응이 없던 두 갈래를 **승계 등재**했다: `REND-05`(Kiki 2026-08-11 결정) · `PED-44`(coach 실행용 축).
5. acceptance ③("PED-22·23 처분 판정")과 ⑤(d)("PED-24 잔존 확인")는 **stale**이다 — `PED-22`~`PED-25`는 모두 main에서 done(PR #831·#834·#835·#832).

---

## 1. 파일 단위 대조 (acceptance ①)

### 1.1 gdmwhk(`2915bf4e`) ↔ main — 카탈로그 관련 27파일

`git diff main origin/claude/whymath-pedagogy-review-gdmwhk -- <카탈로그 경로>`의 27파일을 줄 단위로 읽어 분류했다.

| 분류 | 파일 | 차이의 실체 | 처분 |
|---|---|---|---|
| 번호·참조만 다름 | `data/corpus/pedagogy_strategies_v1/` YAML 10 + `_provenance.json` (11) | 문서 참조 `04e→04f`, 태스크 번호 `PED-06→PED-18`. 내용 동일 | 이식 불요 |
| 번호·참조만 다름 | `schema/pedagogy_strategy.py` · `l4/pedagogy/strategy_registry.py` · `runtime_selector.py` · `prompt_assembler.py` · `tests/.../test_strategy_registry.py` (5) | 같음 — 문서·태스크 번호 문면만 | 이식 불요 |
| **main이 후행 우세 — 채택하면 회귀** | `l4/pedagogy/mode_guard.py` · `l4/pedagogy/__init__.py` | gdmwhk는 옛 "by-design 미배선" 판정 문면이고 `fallback_reply_for`가 없다. main은 `PED-23`이 옵트인 배선(`harness/wh1_primary.py`)으로 **판정을 역전**했다 | **이식 금지** |
| **main이 후행 우세 — 채택하면 회귀** | `l4/pedagogy/adaptive/effectiveness.py` | gdmwhk는 `k_type=str(outcome.k_type)` — PG enum 경유 행에서 `"KnowledgeType.CONCEPT"`로 맹글링되는 결함. main은 `KnowledgeType(...).value`로 정정(`PED-25`) | **이식 금지** |
| gdmwhk에 부재 | `l4/pedagogy/age_band_explanation.py` · `tests/.../test_age_band_explanation.py` · `tests/.../test_mode_guard_fallback.py` (3) | main에만 있는 후속 산출 | 해당 없음 |
| 문서 — 번호 충돌 | `docs/architecture/04f_pedagogy_module_boundaries.md` | gdmwhk는 04f를 **카탈로그**에 썼는데 main의 04f는 이 문서가 점유 | 번호 정리(§5) |
| 문서 — 병합 대상 | gdmwhk `04f_pedagogy_strategy_catalog.md` ↔ main `04e_…`(현 04g) | 병합 3건만 gdmwhk 고유(§2) | **병합 완료** |
| 문서 — main 우세 | `docs/architecture/00_overview.md` · `.claude/agents/llm-architect.md` · `ml-engineer.md` (3) | gdmwhk는 낡은 판: 오개념 "30개" 표기·ARCH-66 일시중단 공지·`MasteryState` 미구현 부기가 없다 | 이식 금지(덮어쓰면 회귀) |

합계 11 + 5 + 2(mode_guard·`__init__`) + 1(effectiveness) + 3(gdmwhk 부재) + 1(04f boundaries) + 1(카탈로그 문서) + 3(개요·에이전트 2) = **27**.

**"main에 없는 파일" 전수**(대상 경로 = 카탈로그 코퍼스·`l3/pedagogy`·`l4/pedagogy`·카탈로그 스키마·관련 테스트·카탈로그 문서, gdmwhk 쪽 103파일 기준): gdmwhk **0건**. 즉 gdmwhk의 카탈로그 자산은 단 한 파일도 main에서 빠져 있지 않다.

### 1.2 uqyg79(`5dc040b3`, PR #675 닫힘·미머지) ↔ main

대상 경로 97파일 중 **main에 없는 파일은 2건**: `l4/pedagogy/signal_assembly.py`(60줄)와 `tests/backend/l4/pedagogy/test_signal_assembly.py`(119줄). 나머지는 `PED-22`·`PED-24`·`PED-25`가
이식했거나 main이 후행 갱신했다. 이 2건이 `PED-08 ①`의 산출이며 처분은 §3 #6.

### 1.3 main의 회수 증적

| 태스크 | 상태 | 증적 |
|---|---|---|
| `PED-22` 카탈로그 정본 | done | PR #831 · 로컬 전체 스위트 10,092 passed |
| `PED-23` 소비 배선 | done | PR #834 · 10,146 passed · gate3 봉인 개정 사유 PR 본문 명시 |
| `PED-24` 생성기·`diag_item` | done | PR #835 · 10,187 passed · 결함주입 강등전 exit 0/1 |
| `PED-25` 소액 정정 | done | PR #832 · 10,054 passed · OPS-15 격리 가드 2종은 의도적 제외(명시) |

---

## 2. acceptance 항목별 판정

| 항목 | 판정 | 근거 |
|---|---|---|
| ① 대조 실측 | **이행** | §1 |
| ② gdmwhk 이식 | **이식 0건이 정답** | §1.1 — main이 상위집합. 문서 병합은 ⑤(b)로 이행. 브랜치 태스크는 §3 처분 |
| ③ PED-22·23 처분 | **stale** | 이미 done(§1.3). 판정할 대상이 없다 |
| ④ 집행 지점 | **이행** | §4 (OFF 비트동일 0/7680 · ON 작동 비율 실측) + 전체 스위트(§6) |
| ⑤(a) 처분 기록 | **이행** | §3 |
| ⑤(b) 04f 병합 | **이행** | 04g에 §10 어댑터 갭 재판정 · §12 2행 · 부록 · 번호 이중 점유 해소. mode_guard 판정 뒤집기는 **폐기**(PED-23이 재역전) |
| ⑤(c) 소액 문서 | **일부 stale** | `llm-architect`·`ml-engineer`의 `MasteryState` 미구현 부기는 `PED-25`(2026-08-15)가 이미 main에 반영. **실제 부재였던 것은 `pedagogy-designer` 정본 관계 부기와 `00_overview` 인덱스 줄** → 이번에 착지 |
| ⑤(d) PED-24 잔존 | **stale** | PED-24 done(#835) |
| ⑤(e) 코드 이식 금지 | **준수** | 회귀 3종 중 mode_guard·k_type 2종은 본 세션이 직접 재확인(§1.1). **"secret 폴백"은 재현하지 못했다** — 이식 대상이 아니라 추적하지 않는다 |

---

## 3. 처분 기록 (acceptance ⑤(a))

출처 번호(PED-0x·PED-1x·PED-2x)는 main에서 **무관한 done 태스크와 겹친다**(예: main `PED-08` = 성장 증거 서빙 경계 집행, `PED-13` = 결손 복구 리드타임 지표). 아래 "main 위치"가 유일한 정본이다.

| # | 출처 | 내용 | 처분 | main 위치 / 사유 |
|---|---|---|---|---|
| 1 | gdmwhk `PED-18` | 카탈로그 자산 + 후보 필터 소비 배선 | **제외 — main 착지** | `PED-22`·`PED-23` done |
| 2 | gdmwhk `PED-19` | 비유·예시 생성기 + 결함주입 강등전 | **제외 — main 착지** | `PED-24` done. main `l3/pedagogy/`는 5파일 + `explanation_*`까지 상위집합(gdmwhk는 생성기 0파일) |
| 3 | gdmwhk `PED-20` | 형성평가 `diag_item` 슬롯 투영 | **제외 — main 착지** | `PED-24` done (`diag_item_projector.py`) |
| 4 | gdmwhk `PED-21` | coach 실행용 축 수렴 | **승계** | **`PED-44`** (아래 #7과 합침) |
| 5 | gdmwhk `REND-05` | 미구현 렌더 어댑터 5종 | **승계(같은 번호)** | **`REND-05`** — Kiki 2026-08-11 결정("진짜 갭")이 main의 결정 로그에 없었으므로 04g §10 재판정 행과 MEMORY에 옮김. 현행 코드(`_ADAPTER_FACTORIES`, EOS-89)에 맞춰 문면 갱신 |
| 6 | uqyg79 `PED-08 ①` | 신호 조립 공용 좌석 `signal_assembly.py` | **제외(로직)** · 경계는 `PED-44 ②`로 | 로직은 main `api/study.py::_build_signals`(get_state 기반 리팩터)가 우세 — 복사 이식 금지. 유실된 것은 "조립을 어느 계층이 소유하는가"라는 좌석 경계뿐 |
| 7 | uqyg79 `PED-08 ②` · `PED-13` | coach `decide()` 소비 + 개념그래프 code→원자 code 해석 다리 | **승계** | **`PED-44`** — 2026-08-03 분석(두 ID 공간 불일치)을 acceptance ①에 보존하되 **재실측 선행**을 못박았다(아래) |

**#7의 재실측 단서.** uqyg79 분석은 "coach는 `Concept.code`(`math.<area>.<slug>`) 공간, study는 원자 backbone code 공간이라 직접 조인 불가, crosswalk는 오프라인 유틸"이었다. 그 뒤 main에
`concept_content.atom_codes`(`l1/concept_content/resolve.py::find_k12_contents_by_atom`)와 `Concept.aliases` 좌석이 생겼다. 단 `concept_content`의 PK는 구 437 코드(`N1`·`A1`…)이지
`Concept.code`가 아니어서 **다리가 닫혔는지는 이 세션이 검증하지 못했다.** 그래서 `PED-44`는 "해석 성공률을 먼저 실측하고 낮을 때만 resolver 설계"로 시작한다.

---

## 4. 집행 지점 실측 (acceptance ④)

`pedagogy_catalog_filter_enabled`(기본 **False**)를 OFF/ON으로 바꿔 `runtime_selector.select()`를 합성 격자에 돌렸다.
격자 = 학생 신호 48(숙달 4 × 직전정오 3 × 오개념 2 × 턴 2) × 학년 5 × `k_type` 8 × 난이도 4 = **7,680**. **합성 격자이므로 운영 트래픽 분포가 아니다** — 아래 비율은
"카탈로그 × 규칙표가 구조적으로 만드는 값"이지 서비스 지표가 아니다.

| 관측 | 값 |
|---|---|
| **OFF(기본)**: 규칙표 원판정과 다른 건수 | **0 / 7,680** (비트동일) |
| ON: 필터 축 신호가 전무한 지점의 원판정 불일치 | **0** |
| ON: 필터가 발동할 수 있는 지점 | 7,632 |
| ON: 그중 **판정이 실제로 바뀐 비율** | **2,350 (30.8%)** |
| ON: 폴백 로그 | `CATALOG_FILTER_EMPTY` 2,160 · `CATALOG_FILTER_EXHAUSTED` 1,090 (**합 3,250 = 42.6%**) |
| ON: `select()` 출력 | SOCRATIC 2,960 · WORKED_EXAMPLE 2,180 · ANALOGY 1,675 · PROBLEM_BASED 690 · DIRECT 175 — **등록 5종 밖 0** |

**축별로 보면 필터의 실효는 거의 `k_type` 하나다** (등록 5종에 대한 단일 축 좁힘):

| 축 | 결과 |
|---|---|
| **학년(grade_band)** | **좁힘 0** — 카탈로그 10종 전부가 4개 학교급 모두를 적합으로 서술한다. 프로덕션에서 유일하게 배선된 필터 축(`_build_signals`)이 **효과가 없다** |
| 난이도 | `상`·`중`은 좁힘 0, `하`만 3종(ANALOGY·DIRECT·SOCRATIC)으로 좁힘. 상/중/하 생산자는 프로덕션에 없다(`select()` docstring) |
| `k_type` | CONCEPT 4종 · PROCEDURE 2종 · MODELING 2종 · STOCHASTIC 1종 · PROOF 1종 · **SPATIAL 공집합 · REPRESENT 공집합** |

SPATIAL·REPRESENT가 공집합인 이유는 그 지식유형을 가리키는 카탈로그 전략이 **VISUALIZATION(렌더 어댑터 미등록) 하나뿐**이기 때문이다. 즉 필터를 켜도 이 두 유형에서는 항상 원판정으로 폴백한다.
이 관측은 `REND-05` 완료 판정 항목 ⑦로 붙였다 — 어댑터 갭이 단지 "고를 수 없는 전략 5개"가 아니라 **필터의 작동 범위를 깎고 있다**는 근거다.

**함의(권고, 결정 아님).** GA 플래그를 켜기 전에 ① 학년 축을 카탈로그가 실제로 변별하도록 서술을 손볼지, 축을 빼서 "작동 안 하는 필터"라는 착시를 없앨지 ② 폴백 42.6%가 운영에서도 나오는지 `reason_code`로 먼저 관측할지 판단이 필요하다.

<details><summary>재현 스크립트 (읽기 전용 · DB 불요 · 백엔드 설치된 환경의 <code>src/backend</code>에서 실행)</summary>

```bash
python -I - <<'PY'
import dataclasses, itertools, logging, os
from collections import Counter
os.environ["WHYMATH_PEDAGOGY_CATALOG_FILTER_ENABLED"] = "true"
from whymath_backend.config import get_settings
get_settings.cache_clear()
from whymath_backend.l3.render.registry import registered_strategies
from whymath_backend.l4.models import PolyaStage
from whymath_backend.l4.pedagogy import runtime_selector as rs
assert get_settings().pedagogy_catalog_filter_enabled is True   # 토글이 실제로 적용됐는지 단언

reasons = Counter()
class H(logging.Handler):
    def emit(self, r):
        for c in (rs.REASON_CATALOG_FILTER_EMPTY, rs.REASON_CATALOG_FILTER_EXHAUSTED, rs.REASON_CATALOG_UNAVAILABLE):
            if c in r.getMessage(): reasons[c] += 1
lg = logging.getLogger("whymath.l4.runtime_selector"); lg.addHandler(H()); lg.setLevel(logging.INFO)

grid = [rs.StudentSignals(mastery_level=m, last_attempt_correct=c, misconception_ids=mi, turn_count=t,
                          polya_stage=PolyaStage.UNDERSTAND)
        for m, c, mi, t in itertools.product([None, "초보", "발전 중", "숙달"], [None, False, True], [(), ("m1",)], [0, 6])]
bands = [None, "초등", "중학", "고등", "대학"]
ktypes = [None, "CONCEPT", "PROCEDURE", "MODELING", "STOCHASTIC", "PROOF", "SPATIAL", "REPRESENT"]
diffs = [None, "상", "중", "하"]
reg = registered_strategies(); on = changed = 0
for s0 in grid:
    base = rs._rule_table(s0, reg) or rs._FALLBACK_STRATEGY
    for b, k, d in itertools.product(bands, ktypes, diffs):
        if b is None and k is None and d is None: continue
        on += 1; changed += rs.select(dataclasses.replace(s0, grade_band=b), k_type=k, difficulty=d) != base
print("발동 가능", on, "판정 변경", changed, f"({changed/on*100:.1f}%)", "폴백", dict(reasons))
PY
```

OFF 쪽은 같은 격자에서 `WHYMATH_PEDAGOGY_CATALOG_FILTER_ENABLED=false`로 바꾸고(`get_settings.cache_clear()` 후) `select() != base` 건수가 0인지 센다.
</details>

---

## 5. 부수 발견 (이 세션이 찾은 것)

| 발견 | 처리 |
|---|---|
| `04e` 접두를 **두 문서**가 씀 — `04e_misconception_remediation_design.md`(2026-08-03 작성)와 교수전략 카탈로그(2026-08-15 main 착지). 코드·테스트가 `04e §N`으로 약칭 인용해 **어느 문서의 절인지 결정 불가** | **해소**: 카탈로그를 04g로. 약칭 118곳(41파일)을 순수 치환(줄 단위 대조 0건 이탈) + 오개념 문서를 가리키는 `test_coach_ocr_solution_diagnosis.py`의 `04e §9-D1`은 **보존** |
| `03c` 접두도 중복 — `03c_cloud_tier_transition_v2.md` ↔ `03c_content_strategy_cache.md` | `ARCH-72` 분리 등재(클라우드 티어 문서는 개정이 활발해 병렬 충돌 회피). `tests/infra/test_architecture_doc_numbers.py`가 만료일(2026-12-31)이 있는 유예로 감시 |
| 접두 중복은 어떤 검사에도 안 걸렸다(파일명이 달라서) | 신규 테스트가 차단. **뮤테이션 5종 전건 검출**(미등재 중복 주입·04e 이중 점유 재현·만료일 과거·03c 예외 낡음·스캔 0건) — 주입 적용 단언·바이트 동일 원복 포함 |
| `backlog.py add`가 **빈 acceptance·notes를 거부하지 않는다** — 이 세션에서 셸 인자 파일 경로를 잘못 써 `PED-43`이 빈 acceptance 5항으로 저장됨. 대장은 append 전용이라 빈 항을 지울 수 없다 | `PED-43` 취소 → `PED-44`로 재등재(번호 1개 소비). 대책 = `HARN-304`(입구 검증). 이 사실은 "쓴 뒤 읽어서 확인"으로 발견했다 |

---

## 6. 검증 상태와 하지 않은 것

- **전체 backend 스위트**: 아래 "결과" 참조(커밋 `14887260` 스냅샷 워크트리에서 실행 — 실행 중 작업 트리 변경에 오염되지 않게 분리).
- **삭제하지 않았다**: `gdmwhk`·`uqyg79` 브랜치. 이 PR이 머지돼 §3 처분이 main에 착지한 **뒤에** 삭제 가능하다(`stray-code` 절차). 삭제는 되돌릴 수 없어 사람 판단으로 남긴다.
- **코드 이식 0건**이라 런타임 동작은 바뀌지 않는다. 변경은 주석·docstring의 문서번호, 코퍼스 주석, 문서, 대장, 테스트 1건이다.
- **하지 않은 것**: `03c` 해소 · `REND-05` 구현 · `PED-44` 구현 · 학년 축 서술 보정(§4 함의).

### 결과

CI 잡 목록(`ci.yml` 잡 20개)을 먼저 전수 열거한 뒤 이 변경이 닿는 잡을 골라 CI 명령 그대로 재현했다. 판정은 종료 코드와 로그의 판정 줄을 함께 읽었다.

| CI 잡 | 재현한 스텝 | 결과 |
|---|---|---|
| `backend` | ruff · black(`--line-length 100`) · `mypy --strict`(740파일) · `lint-imports`(4 kept) | 전건 exit 0 |
| `backend` | `pytest -m "not corpus_authoring" -n auto --dist loadfile --cov … --cov-fail-under=70` | **16,779 passed · 584 skipped · 1 xfailed** (17분 36초) · 커버리지 90.73% · exit 0 |
| `backend` | 계층별 커버리지 게이트 | api 96.8 · l1 89.7 · l2 96.5 · l3 94.8 · l4 96.2 — 전 계층 PASS |
| `backend` | 게이트 CLI 16종(결함주입 강등전·`analogy_fidelity`·`pedagogy_pack_fidelity`·`provenance_audit` 등) + `tests/constitution`(39) | 전건 exit 0 |
| `infra-contracts` | ruff · black · `pytest tests/infra`(신규 가드 포함) | **2,682 passed · 1 skipped** · exit 0 |
| `harness-integrity` | `validate`·`audit-deps`·`rules lint/render --check`·`jit check`·위헌 심사 래칫·헌법 가드 4종 · ruff · black · `pytest tests/harness` | **2,006 passed · 3 skipped** · 전건 exit 0 |
| `policy-guard` | 금기 패턴 grep 3종 · `cp949_guard` · 충돌 마커 · 저작권 원본 바이너리 | 위반 0건 |
| `declared-unwired-audit` | 선언≠배선 감사 · 백필 드리프트 2종(레포 루트에서) | 전건 exit 0 |

**로컬에서 돌리지 못한 잡과 근거 — CI를 최종 판정으로 넘긴다.**
- `backend-migrations`(실 PG 서비스 필요): 마이그레이션 변경 0건이지만 `backend` 플래그라 CI에서는 돈다.
- `data-pipeline`: `src/data-pipeline` 변경 0건. 코퍼스 주석만 바뀌어 `corpus` 플래그로 CI에서는 돌 수 있다.
- `mobile`·`web`·`webapp`·`concept-reach-guard`·`docker-build`·`infra-shell`·`data-pipeline-*`: 변경 경로 비접촉. `corpus-authoring`·`e2e-nightly`·`backend-serial-nightly`: 스케줄/작성 전용.
- `harness-integrity`의 원격 관측 스텝(ADR 번호 충돌·claim 교차·고립 브랜치·EOS 단원 구조 리포트): 원격 전 브랜치 fetch가 필요하거나 관측 전용(경고)이라 생략.
- 로컬은 Python 3.13이고 CI는 3.12다.
- 재측정 주의: 위 전체 스위트는 문서 2건(이 문서의 결과 절·MEMORY 항목)이 추가되기 **전** 스냅샷이다. 그 뒤 편집은 문서뿐이라, MEMORY·문서를 읽는 테스트(`tests/infra/test_cp949_guard.py` 등)와 `cp949_guard`만 다시 돌렸다.
