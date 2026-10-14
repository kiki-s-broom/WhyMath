# PED-26 — 교수전략 카탈로그 회수 정합 (gdmwhk · uqyg79 ↔ main)

> **회수 이식 안내 (PED-45 · 2026-10-14).** 이 문서는 고립 브랜치 `claude/nice-cray-mbg1mq`(head `dbe2e79c`, PR 미개설)에 있던
> 정합 결과를 `PED-45`가 `main 24d8607d` 위에서 재검증하며 이식한 것이다. **§1~§6은 원 세션의 서술**(판정 기준 `main 8a5ea4d1`)이며
> 본문을 고치지 않았다 — 그 안의 "이 PR"은 원 세션의 (열리지 않은) PR을 뜻한다. **§7이 이식 시점의 재검증**이고 둘이 어긋나면 §7이 현행이다.

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


---

## 7. 회수 이식 기록 (PED-45) — `main 24d8607d` 위 재검증

> **판정 기준: `main 24d8607d`(2026-10-13).** §1~§6은 원 세션의 서술이고 판정 기준이 `main 8a5ea4d1`이다. 두 시점이 어긋나는 곳은 이 §7이 현행이다.
> 이식 출처 = `origin/claude/nice-cray-mbg1mq` head `dbe2e79c`(ahead 2). 분기점 `8a5ea4d1` 이후 main이 99커밋 앞서 있었다(태스크 등재 시점의 65보다 더 벌어졌다).
> 이 클론은 shallow여서 분기점을 찾으려 히스토리를 `--deepen=120`으로 늘렸다.

### 7.1 이식 방식 — 패치 재적용이 아니라 main 위 재실행

| 항목 | 결과 |
|---|---|
| 개명 대상 확인 | main `docs/architecture/`에 `04e_*`가 **두 개**(`04e_misconception_remediation_design.md` · `04e_pedagogy_strategy_catalog.md`)이고 `04g_*`는 없었다. 개명 대상은 후자다 |
| 브랜치 변경의 성격 검증 | 브랜치 54파일 중 약칭 치환은 **41파일 118줄이 전부 순수 `04e→04g` 치환**이다(줄 단위 비교로 확인). 나머지는 카탈로그 개명·병합본, 문서 부기 2건, 신규 테스트, 대장·MEMORY·이 문서다 |
| main 위 치환 재실행 | 같은 41파일에서 **118줄이 전부 정확히 일치**해 치환됐다. 그 41파일 안에 남은 `04e` 참조는 0건 |
| 브랜치 결과와 대조 | 파일별 (제거 줄, 추가 줄) 쌍을 비교해 **불일치 0건**. 분기점 이후 main에서 바뀐 4파일(`api/coach.py`·`config.py`·`analogy_generator.py`·`test_analogy_demand.py`)도 같은 줄이 그대로 일치했다 |
| **브랜치가 알 수 없던 신규 1줄** | `tests/backend/l4/test_polya_prompts.py:107`의 `` `grade_to_band`(04e §4 — 13~14=N수는 '고등') ``. 분기점 이후 S4-62(`95890c2f`, [#1522](https://github.com/kiki-s-broom/WhyMath/pull/1522))가 들여온 줄이다. `grade_to_band` 정본은 카탈로그 §4("후보 필터의 grade 신호")이므로 `04g §4`로 치환했다. 패치를 그대로 재적용했다면 이 줄이 `04e`로 남아 **오개념 문서의 §4를 가리키는 오인용**이 됐다 |
| 보존한 참조 | 오개념 문서를 가리키는 `04e` 약칭은 그대로 둔다(코드·테스트·문서 17파일 — `db/models/misconception_relation.py`·`alembic` 2건·`test_coach_ocr_solution_diagnosis.py`의 `04e §9-D1`·`misconception_module_gap_review*.md` 등). 역사 기록(`MEMORY.md`·`backlog/`·`docs/reviews/`)은 당시 번호 그대로이며, 거기서 `04e_pedagogy_strategy_catalog`는 지금의 `04g` 문서다 |
| 카탈로그 문서 | main의 `04e_pedagogy_strategy_catalog.md`는 분기점 이후 **불변**이라(그 문서를 건드린 main 커밋 0건) 브랜치의 `04g` 병합본(§10·§11·§12·부록)을 그대로 쓸 수 있었다 |
| 문서 부기 2건 | `pedagogy-designer.md` 정본 관계 부기·`00_overview.md` 인덱스 줄 — 두 파일 모두 삽입 자리가 main에서 그대로여서 브랜치와 **같은 줄**이 들어갔다(추가 줄 대조 동일) |
| 이식하지 않은 것 | 코드·코퍼스 로직(§1 결론 그대로 0건) · 브랜치의 `backlog/events/*.ndjson`(그 세션의 사건 기록) · `PED-43`(빈 acceptance 오등재로 브랜치에서 취소된 번호) · 브랜치의 대장 변경(태스크 4건 등재·`PED-26`의 `review` 전환) — 승계 4건은 이미 main에 있고(§7.3), `PED-26`은 `todo`로 두고 처분 기록(acceptance ⑥)만 append했다(§7.5) |

### 7.2 집행 지점 — 접두 중복 차단 테스트 (acceptance ③)

`tests/infra/test_architecture_doc_numbers.py`(4건)는 CI의 `infra-contracts` 잡이 `python3 -m pytest tests/infra -q`(디렉터리 수집)로 돌리고, 같은 잡의 ruff·black이 `tests/infra`를 본다. 워크플로 `jobs:` 키 20개를 열거해 이 변경이 닿는 잡을 골랐다 — §7.7.

**결함 주입 5종**(순수 Python 하네스 · 주입 전 기준선 초록 단언 · 적용 실재 단언 · 원복 바이트 동일 sha256 단언):

| # | 주입한 상태 | 결과 |
|---|---|---|
| M1 | 같은 접두의 문서를 하나 더 만든다(미등재 중복) | RED — `test_no_unlisted_duplicate_prefix` |
| M2 | 카탈로그를 `04e_` 이름으로 되돌려 이중 점유를 재현 | RED — 위 + `test_strategy_catalog_is_not_squatting_on_04e` |
| M3 | 03c 유예 만료일을 과거로 | RED — `test_known_duplicates_are_real_and_not_expired` |
| M4 | 03c 중복을 해소(한쪽을 유일 접두로 개명) | RED — 같은 테스트(낡은 예외 탐지) |
| M5 | 스캔 경로를 낡게 해 0건으로 | RED — `test_scan_finds_numbered_docs` |

5종 전건 검출. M5에서 다른 두 테스트도 같이 RED가 된 것은 스캔이 0건이면 그 둘의 전제도 무너지기 때문이다(5종 모두 의도한 테스트가 포함된 RED).

### 7.3 승계 태스크 4건 — 이미 main에 복원돼 있다

| 태스크 | main 상태 | 브랜치 원문과의 대조 |
|---|---|---|
| `ARCH-72-architecture-doc-prefix-03c-dedup` | todo | title·acceptance·paths 동일 · `depends_on`만 다름 |
| `HARN-304-reject-empty-acceptance-and-notes` | todo | 전 필드 동일 |
| `PED-44-coach-runtime-pedagogy-axis-convergence` | todo | title·acceptance·paths 동일 · `depends_on`만 다름 |
| `REND-05-unrendered-strategy-adapters` | todo | title·acceptance·paths 동일 · `depends_on`만 다름 |

`depends_on`의 차이는 stray-code 17회차가 "이 태스크(PED-45)가 선행"이라고 붙인 것이다. 대장 변경은 이식할 것이 없다. `PED-43`은 복원하지 않는다.
이 문서가 가리키는 `ARCH-72`(03c 유예의 소유 태스크)는 이제 main에 실재하므로 가드의 `_KNOWN_DUPLICATES` 참조가 허공을 가리키지 않는다.

### 7.4 카탈로그 후보 필터 "작동한 비율" 재측정 (acceptance ③)

현행 main(`24d8607d`)에서 §4의 재현 스크립트를 OFF/ON으로 다시 돌렸다. 합성 격자 7,680점 — **운영 분포가 아니다.**

| 관측 | 재측정 값 |
|---|---|
| OFF(기본): 규칙표 원판정과 다른 건수 | **0 / 7,632** (필터 축 신호가 있는 지점 기준 · 비트동일) |
| ON: 판정이 실제로 바뀐 건수 | **2,350 (30.8%)** |
| ON: 폴백 로그 | `CATALOG_FILTER_EMPTY` 2,160 · `CATALOG_FILTER_EXHAUSTED` 1,090 (**합 3,250 = 42.6%**) |
| ON: `select()` 출력 분포 | SOCRATIC 2,960 · WORKED_EXAMPLE 2,180 · ANALOGY 1,675 · PROBLEM_BASED 690 · DIRECT 175 (등록 5종 밖 0) |
| 학년 축 | 학교급 4종 모두 좁힘 **0**(5/5 유지) |
| 난이도 축 | `상`·`중` 좁힘 0, `하`만 5→3종(ANALOGY·DIRECT·SOCRATIC) |
| `k_type` 축 | CONCEPT 4 · PROCEDURE 2 · MODELING 2 · STOCHASTIC 1 · PROOF 1 · **SPATIAL 0 · REPRESENT 0** |
| 공집합 원인 | SPATIAL·REPRESENT를 가리키는 카탈로그 전략은 `VISUALIZATION` 하나이고 그 렌더 어댑터가 미등록이다. 카탈로그 10종 중 미등록은 INTERLEAVING·RETRIEVAL·SELF_EXPLANATION·SPACING·VISUALIZATION 5종 |

**수치가 §4와 같다는 점에 대해.** 이 값은 §4에서 옮긴 것이 아니라 현행 main에서 다시 실행해 얻었다. 같은 값이 나온 것은 이 격자 위에서 `select()`의 결과가 분기점 이후 달라지지 않았다는 뜻이다(이 PR의 치환은 주석·docstring뿐이라 값에 영향이 없다).
분모 표기: 격자는 7,680점이고 그중 학생 신호 48점 × 세 축 전부 None인 48점은 필터가 발동하지 않아 불일치가 자명하게 0이다. 그래서 위 표는 발동 가능 7,632점을 분모로 적었다(§4는 격자 전체 7,680을 적었다). 불일치 건수 0은 둘 다 같다.

> 함의는 §4 그대로다: GA 플래그를 켜기 전에 ① 학년 축을 변별하도록 카탈로그 서술을 손볼지 축을 뺄지 ② 폴백 42.6%가 운영에서도 나오는지 `reason_code`로 관측할지 판단이 필요하다. 이 PR의 범위 밖이다.

### 7.5 소유 태스크 `PED-26` acceptance 재대조 (acceptance ④)

판정 기준 `main 24d8607d`. `PED-26`의 현재 acceptance는 ①~⑤(⑤는 (a)~(e))다.

| 항목 | 판정 | 근거 |
|---|---|---|
| ① 대조 실측 | **이행** | §1(원 세션)·§7.6(현행 재열거) |
| ② gdmwhk 파일 단위 이식 | **의도적 제외** | 이식 0건이 정답 — 현행에서도 gdmwhk에만 있는 줄은 옛 시그니처·옛 판정 문면뿐이다(§7.6). 문서 병합은 ⑤(b)로 이행 |
| ③ PED-22·23 처분 | **stale** | 둘 다 main에서 done(#831·#834) |
| ④ 집행 지점(OFF 비트동일·ON 작동 비율) | **이행** | §7.4 재측정 + 전체 스위트(§7.8) |
| ⑤(a) 처분 기록 의무 | **이행** | §3(7건) — 승계 태스크 4건은 §7.3대로 main에 실재 |
| ⑤(b) 04f→병합·번호 이중 점유 해소 | **이행** | `04g` 병합본(§10·§12·부록) + 번호 정리(§7.1). `mode_guard` 판정 뒤집기는 폐기 |
| ⑤(c) 소액 문서 | **이행(일부 stale)** | `pedagogy-designer.md` 부기·`00_overview.md` 인덱스 줄이 이번에 착지. `llm-architect`·`ml-engineer`의 부기는 `PED-25`가 이미 반영 |
| ⑤(d) PED-24 잔존 확인 | **stale** | PED-24 done(#835) |
| ⑤(e) 코드 이식 금지 | **준수** | 코드 이식 0건 |

**판정: `PED-26`은 닫을 수 있다.** 미이행 acceptance가 없다(제외·stale 사유가 위에 있다). 단 닫는 순서가 정해져 있다 — `PED-26.depends_on`에 `PED-45`가 붙어 있으므로 **이 PR이 머지돼 `PED-45`가 done이 된 뒤** `PED-26`을 `backlog.py done`(증적 = 이 PR)으로 닫는다. `PED-26`의 원격 claim(2026-10-08T05:57Z)은 TTL 초과이며 해제(`claims reap`)는 그 태스크를 닫는 세션이 dry-run으로 확인한 뒤 진행한다.
`PED-26`의 `paths`에 남은 `04f_pedagogy_strategy_catalog.md`는 옛 번호다(현행은 `04g`). 이 PR에서 대장을 손편집하지 않았다 — 닫을 때 정리한다.

### 7.6 gdmwhk · uqyg79 잔여 diff 재열거

`--depth=1`로 가져온 두 브랜치(gdmwhk `2915bf4e` · uqyg79 `5dc040b3`)를 **이 PR이 반영된 트리**와 파일 단위로 비교했다. 대상 경로 = 카탈로그 코퍼스·`l3/pedagogy`·`l4/pedagogy`·카탈로그 스키마·관련 테스트·`docs/architecture`·`.claude/agents`.

| 브랜치 | 브랜치에만 있는 파일 | 판정 |
|---|---|---|
| gdmwhk | **1건** — `docs/architecture/04f_pedagogy_strategy_catalog.md` | 내용은 `04g`에 병합됐다(번호만 main의 `04f` boundaries와 충돌). 잔여 아님 |
| uqyg79 | **2건** — `l4/pedagogy/signal_assembly.py` · `tests/backend/l4/pedagogy/test_signal_assembly.py` | §3 #6: 로직 제외(main `_build_signals`가 우세) · 좌석 경계만 `PED-44 ②` |

gdmwhk와 main의 **내용 차이**(카탈로그 코드·코퍼스·테스트 경로, 같은 경로에 두 판이 있는 14파일)를 "gdmwhk에만 있는 줄이 main에 없는가"로 다시 셌다:

- **옛 시그니처·옛 문면**: `review.py`·`slot_generator.py`·테스트 3종의 `review_slot`·`verify_slot_payload`·`build_slot_rows`는 **main에 같은 이름으로 존재**하고 main이 후행 리팩터(동치 판정기 주입)를 거쳤다. `prompt_assembler.py`·`runtime_selector.py`·`strategy_registry.py`·`_provenance.json`의 차이는 PED-18 시기 문면이 main에서 PED-22/23 문면으로 갱신된 것이다.
- **회귀 대상(이식 금지)**: `mode_guard.py`·`l4/pedagogy/__init__.py`의 "by-design 미배선" 옛 판정(PED-23이 배선으로 역전) · `adaptive/effectiveness.py`의 `k_type=str(outcome.k_type)`(enum 맹글링 — PED-25가 정정).
- 따라서 **gdmwhk·uqyg79가 main에 없는 실질을 가진 곳은 없다.** 삭제 후보 판정은 새 `stray-code` 감사로 넘긴다. 삭제는 되돌릴 수 없어 이 PR이 하지 않는다.

> 한계(명시): 두 브랜치는 얕게 가져와 파일 트리만 비교했다. 커밋 계보는 보지 못했다. "줄 단위" 비교는 `04e|04f|04g`와 `PED-숫자`를 정규화한 뒤 정확히 일치하는 줄을 센 것이라 공백·줄바꿈 차이는 별도 판정하지 않았다.

### 7.7 CI 잡 대조 — 이 변경이 닿는 잡

워크플로 `jobs:` 키 20개를 열거했다(`changes`는 경로 판정 게이트이며 검증 잡이 아니다). 이 변경은 `src/backend` 주석·docstring, `tests/backend`, `tests/infra`(신규 테스트), `docs/`, `data/corpus/pedagogy_strategies_v1`(주석), `.claude/agents`를 건드린다.

| 잡 | 닿는가 | 근거 |
|---|---|---|
| `backend` | **닿음** | `src/backend`·`tests/backend` 변경 |
| `infra-contracts` | **닿음** | `tests/infra` 신규 테스트 · 문서 수치/귀속 테스트가 이 잡에 산다 |
| `harness-integrity` | **닿음** | `docs/`·`backlog/`·`MEMORY.md` 변경 + `tests/harness` |
| `policy-guard` | **닿음** | 모든 PR에 도는 금기 패턴·`cp949_guard`·충돌 마커 |
| `declared-unwired-audit` | 닿음(전수 재현) | 선언≠배선 감사는 소스 변경에 반응 |
| `data-pipeline` | **닿음** | `data/corpus/pedagogy_strategies_v1`(주석) 변경이 `corpus` 플래그를 켜 QA 파이프라인 게이트 스텝도 돈다 |
| `corpus-authoring` | **닿음** | 경로 필터가 깨운다(`data/corpus/` 변경) |
| `infra-shell`·`declared-unwired-audit` | 닿음(상시) | 상시 잡 |
| `backend-migrations` | 닿음 · **로컬 재현 불가** | 경로 필터가 깨운다(`src/backend/`). 실 PG 서비스 컨테이너가 필요하다. 마이그레이션 변경은 0건이고 alembic의 `04e` 참조는 **보존**했다 |
| `docker-build` | 닿음 · **로컬 재현 불가** | 경로 필터가 깨운다(`src/backend/`). docker 빌드·기동 스텝이 필요하다 |
| `mobile`·`web`·`webapp`·`concept-reach-guard`·`data-pipeline-*`·`constraints-freshness` | 안 닿음 | 경로 비접촉 |
| `e2e-nightly`·`backend-serial-nightly` | 안 닿음 | 스케줄 전용 |

> **정정(2026-10-14).** 이 표의 첫 판은 `data-pipeline`·`corpus-authoring`·`docker-build`를 "경로 비접촉"으로 적었다. PR 생성 훅(HARN-209)이 경로 필터가 깨우는 잡 목록을 보여 줘서 틀렸음이 드러났고, 닿는 잡 판정을 "무엇을 검사하는지"가 아니라 내가 떠올린 경로로 했던 탓이다. 재현 가능한 두 잡은 이후 실제로 돌렸다(§7.8).

### 7.8 검증 결과

판정 기준: 코드 변경 커밋 `948a0436`(별도 워크트리 재생) · 문서·대장 포함 커밋 `e4eda2b1`(CI 미러). 환경은 Python 3.12 venv이고 의존은 CI 제약 파일(`infra/ci/constraints-py312.txt`)로 고정했다. 판정은 종료 코드와 로그의 판정 줄을 함께 읽었다.

| CI 잡 | 재현 방법 | 결과 |
|---|---|---|
| `backend` | `ci.yml`의 `run:` 25스텝을 YAML에서 읽어 순서대로 재생(스냅샷 워크트리) | 전 스텝 exit 0 — ruff · black · `mypy --strict` · `lint-imports` · pytest **19955 passed · 684 skipped · 1 xfailed**(29분 49초) · 총 커버리지 86.42% · 계층별 바닥선 PASS · 게이트 CLI 16종 · `tests/constitution` |
| `infra-contracts` | `ci_mirror.py run` | 통과 — `pytest tests/infra` 656초(신규 가드 4건 포함) · ruff · black · 게이트 4종 |
| `infra-shell` · `policy-guard` · `declared-unwired-audit` | `ci_mirror.py run` | 통과 |
| `harness-integrity` | `ci_mirror.py run` | 통과 — `validate`·`audit-deps`·`rules lint`·`jit check`·위헌 심사 래칫·헌법 가드 4종·관측 리포트·ruff·black·`pytest tests/harness` 803초 |
| `data-pipeline` | `ci_mirror.py run` + `qa_pipeline`을 직접 실행 | ruff · black · `mypy --strict` · pytest 통과. 미러가 평가하지 않은 `qa_pipeline` 게이트 스텝(`corpus` 플래그 조건)은 같은 명령(`python -m whymath_backend.harness.qa_pipeline --json …`)을 직접 돌려 exit 0 |
| `corpus-authoring` | `ci_mirror.py run` | 통과 — `corpus_authoring` 마커 전량 1230초 |

**첫 미러 시도의 실패는 검사 실패가 아니었다.** 처음 `ci_mirror.py run`은 venv에 `pip`이 없어 설치 스텝이 죽었고 뒤 스텝 30건이 전부 미실행이었다. `pip`을 넣고 다시 돌린 것이 위 결과다. 미실행은 통과가 아니므로 첫 시도는 증거로 쓰지 않았다.

**돌리지 못한 것 — CI를 최종 판정으로 넘긴다.**
- `backend-migrations`(실 PG 서비스 필요) · `docker-build`(docker 빌드·기동 필요): 이 환경에서 재현 불가. 마이그레이션 변경 0건, Dockerfile·compose 변경 0건.
- `qa_pipeline`의 `defect_report_intake` 축은 로컬에 DB가 없어 `ConnectionRefusedError`로 측정하지 못했다고 스스로 밝히며 종료했다(exit 0). 이 축의 값은 이 PR이 확인한 것이 아니다.
- 로컬 `mobile`·`web`·`webapp` 잡은 경로 비접촉이라 돌리지 않았다.
- `backend` 전체 스위트는 문서·대장 커밋(`e4eda2b1`) **이전** 스냅샷(`948a0436`)에서 돌렸다. 그 뒤 변경은 문서·대장뿐이며, 그것을 읽는 테스트는 `infra-contracts`·`harness-integrity` 미러(`e4eda2b1`)가 덮는다. 이 정합 문서의 §7.7·§7.8 보정 커밋은 위 미러 이후의 문서 변경이라 CI가 최종 판정한다.
