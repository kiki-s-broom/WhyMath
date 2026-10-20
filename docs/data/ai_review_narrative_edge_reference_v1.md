# AI 검수 결과 — 서술형 낱말 매칭 참고 엣지 스테이징 183건 (KG-11 ②)

> **검수 방식**: **AI 검수** 2인 블라인드(검수자 A·B, pedagogy 서브에이전트 · 2026-10-08 Kiki 결정의 적용 · 선례 S4-60·KG-10).
> 인간 수기검수가 아님을 명시한다. 두 검수자는 서로의 결과를 모른 채 전건(183행)을 판정했다. 모델ID는 기재하지 않는다.
> **마커**: `검수:AI 2026-10-20`. 판정 기준 커밋: main `3e9774ff` · 정본 `721fe6ff…`(엣지 2,231).
> **합의 규칙(사전 고정 · 설계 문서 §3)**: 승격 = 둘 다 approve 또는 같은 코드로 replace · 반려 = 둘 다 reject · 그 밖 = 보류.
> **기계 게이트(사전 고정)**: 합의 승인율의 Wilson 95% 단측 하한 ≥ 0.80일 때만 승격. 미만이면 개별 승인분도 승격하지 않는다.
> 기계 판독 사본: `ai_review_narrative_edge_reference_v1.json`(행별 A/B 판정·대체 코드·근거) · 승격 원장 `data/corpus/atom_graph_v1/narrative_edge_promotion_v1.json`.

## 종합 — **게이트 FAIL · 승격 0건**

| 축 | 값 |
|---|---|
| 스테이징 후보 | 183 |
| A 판정 | approve 90 · replace 6 · reject 87 · hold 0 |
| B 판정 | approve 104 · replace 3 · reject 76 · hold 0 |
| 합의 | **승인 87 · 교체 3 · 반려 73 · 보류 20** |
| 합의 승인율 | 49.2% (90/183) |
| Wilson 95% 하한 | **0.4316** (floor 0.8) |
| 판정 | **gate_pass = False** → 승격 엣지 0건 (원장 `edges` 비움) |

읽는 법: 낱말 매칭은 KG-10 싱크 규칙(표본 승인 2/34)보다 훨씬 낫지만, 절반은 여전히 직접 선수가 아니다. 두 검수자가 독립적으로 같은 체계적 오류를 지목했다 — ① **동음이의**(합동·연결·증명·기저·평면·완전성·기호·특이점·분리 — 같은 낱말이 과정마다 다른 개념) ② **전이 조상**(대학 과정 내부가 C→P→R 순서 체인이라 개념 선수가 형식상 전이로 떨어짐) ③ **과정 간 중복 원자**(ANAL2-P02 vs CALC2-P07 등)로 상위→하위 과정 역방향 엣지 ④ **원자 부재**(노름공간·경로·선택공리·k차 적률·그래프 연결성 — 소단원 안에 해당 개념 원자가 없어 엉뚱한 단일 원자로 강제 해소). 즉 낱말 매칭의 실패는 매칭 알고리즘보다 **원자 저작의 공백과 과정 경계 가드 부재**에서 온다.

처분: 합의 승인 90건(승인 87 + 교체 3)은 승격하지 않고 승격 원장 `rows`에 판정으로만 남긴다(사전 고정 규칙 — 결과를 보고 규칙을 바꾸지 않는다). 이 90건과 체계적 오류 4종은 후속 태스크 `KG-12`의 입력이다.

## 행별 판정

| # | from → to | A | B | 합의 |
|---|---|---|---|---|
| E001 | `AALG1-C01` → `ATOPO-C01` | approve | approve | 승인 |
| E002 | `AALG1-C01` → `CRYP-C04` | reject | reject | 반려 |
| E003 | `AALG1-C01` → `CRYP-C05` | reject | reject | 반려 |
| E004 | `AALG1-C01` → `TOPO2-C08` | approve | approve | 승인 |
| E005 | `AALG1-C02` → `AALG1-C05` | approve | approve | 승인 |
| E006 | `AALG1-C02` → `GALOIS-C05` | approve | approve | 승인 |
| E007 | `AALG1-C02` → `GALOIS-C06` | reject | reject | 반려 |
| E008 | `AALG1-C03` → `AALG1-C04` | reject | approve | 보류 |
| E009 | `AALG1-C03` → `AALG1-P02` | reject | reject | 반려 |
| E010 | `AALG1-C05` → `AALG1-C07` | approve | approve | 승인 |
| E011 | `AALG1-C06` → `AALG1-C14` | approve | approve | 승인 |
| E012 | `AALG1-C07` → `AALG1-C09` | reject | reject | 반려 |
| E013 | `AALG1-C07` → `AALG1-C10` | reject | reject | 반려 |
| E014 | `AALG2-C01` → `AALG2-C03` | approve | approve | 승인 |
| E015 | `AALG2-C01` → `AALG2-C05` | approve | approve | 승인 |
| E016 | `AALG2-C01` → `AALG2-C06` | reject | reject | 반려 |
| E017 | `AALG2-C01` → `AALG2-C07` | reject | reject | 반려 |
| E018 | `AALG2-C03` → `AGEO-C07` | approve | approve | 승인 |
| E019 | `AGEO-C01` → `AGEO-C03` | approve | approve | 승인 |
| E020 | `ANAL1-C01` → `ANAL1-C02` | reject | approve | 보류 |
| E021 | `ANAL1-C01` → `FANAL-P01` | replace(ANAL1-P01) | approve | 보류 |
| E022 | `ANAL1-C01` → `RANAL-C01` | approve | approve | 승인 |
| E023 | `ANAL1-C02` → `TOPO2-C06` | reject | reject | 반려 |
| E024 | `ANAL1-C04` → `ANAL1-C05` | reject | approve | 보류 |
| E025 | `ANAL1-C04` → `ANAL1-C06` | approve | approve | 승인 |
| E026 | `ANAL1-C04` → `ANAL1-C07` | reject | reject | 반려 |
| E027 | `ANAL1-C04` → `ANAL2-C06` | approve | approve | 승인 |
| E028 | `ANAL1-C04` → `FANAL-C04` | reject | reject | 반려 |
| E029 | `ANAL1-C04` → `PROB-C10` | reject | reject | 반려 |
| E030 | `ANAL1-C08` → `ANAL1-C09` | reject | approve | 보류 |
| E031 | `ANAL1-C11` → `ANAL1-C15` | approve | approve | 승인 |
| E032 | `ANAL1-P01` → `ANAL2-C07` | approve | approve | 승인 |
| E033 | `ANAL2-C06` → `RANAL-C07` | approve | approve | 승인 |
| E034 | `ANAL2-C07` → `ANAL2-C08` | reject | approve | 보류 |
| E035 | `ANAL2-P01` → `CALC1-P23` | reject | reject | 반려 |
| E036 | `ANAL2-P02` → `CALC2-C16` | reject | reject | 반려 |
| E037 | `ANAL2-P02` → `CALC2-P08` | reject | reject | 반려 |
| E038 | `ANAL2-P02` → `CALC2-P10` | reject | reject | 반려 |
| E039 | `ANAL2-P02` → `CXAN-C02` | approve | approve | 승인 |
| E040 | `ANAL2-P02` → `DGEO-C05` | approve | approve | 승인 |
| E041 | `ANAL2-P02` → `FINM-C08` | approve | approve | 승인 |
| E042 | `ANAL2-P02` → `ODE-C02` | approve | approve | 승인 |
| E043 | `ANAL2-P02` → `ODE-P03` | reject | reject | 반려 |
| E044 | `ANAL2-P02` → `PDE-C01` | approve | approve | 승인 |
| E045 | `ATOPO-C05` → `ATOPO-C06` | reject | approve | 보류 |
| E046 | `ATOPO-C06` → `ATOPO-P01` | approve | approve | 승인 |
| E047 | `CALC1-C11` → `ANAL2-C02` | approve | approve | 승인 |
| E048 | `CALC1-C11` → `CALC1-P24` | approve | approve | 승인 |
| E049 | `CALC1-C17` → `ANAL2-R01` | replace(CALC1-R08) | replace(CALC1-R08) | 교체 |
| E050 | `CALC1-C21` → `CALC1-P18` | reject | reject | 반려 |
| E051 | `CALC1-C22` → `CALC1-P18` | approve | approve | 승인 |
| E052 | `CALC1-C22` → `CALC2-C03` | approve | approve | 승인 |
| E053 | `CALC1-C22` → `CALC2-C20` | approve | approve | 승인 |
| E054 | `CALC1-C25` → `ANAL2-C09` | replace(CALC1-P23) | approve | 보류 |
| E055 | `CALC1-C25` → `COMB-C02` | approve | reject | 보류 |
| E056 | `CALC1-C25` → `ODE-P08` | replace(CALC1-P23) | replace(CALC1-P23) | 교체 |
| E057 | `CALC1-C26` → `CALC1-C27` | reject | reject | 반려 |
| E058 | `CALC1-P06` → `CALC1-P08` | reject | reject | 반려 |
| E059 | `CALC1-P06` → `CALC1-P19` | approve | approve | 승인 |
| E060 | `CALC1-P08` → `CALC1-P15` | approve | approve | 승인 |
| E061 | `CALC1-P08` → `CALC2-P01` | approve | approve | 승인 |
| E062 | `CALC1-P08` → `CALC2-P08` | approve | approve | 승인 |
| E063 | `CALC1-P15` → `CALC1-P20` | approve | approve | 승인 |
| E064 | `CALC1-P21` → `ODE-P06` | approve | approve | 승인 |
| E065 | `CALC2-C07` → `CALC2-C21` | approve | approve | 승인 |
| E066 | `CALC2-C07` → `COMB-R02` | reject | reject | 반려 |
| E067 | `CALC2-C07` → `DGEO-C04` | reject | reject | 반려 |
| E068 | `CALC2-C09` → `CALC2-C12` | reject | reject | 반려 |
| E069 | `CALC2-C09` → `DGEO-C01` | reject | reject | 반려 |
| E070 | `CALC2-C09` → `MFLD-C03` | reject | approve | 보류 |
| E071 | `CALC2-C09` → `MFLD-C06` | reject | reject | 반려 |
| E072 | `CALC2-C10` → `DGEO-C01` | approve | approve | 승인 |
| E073 | `CALC2-C12` → `DGEO-C04` | reject | reject | 반려 |
| E074 | `CALC2-C12` → `DGEO-C11` | reject | reject | 반려 |
| E075 | `CALC2-C13` → `ANAL2-P02` | reject | reject | 반려 |
| E076 | `CALC2-C13` → `CALC2-P07` | reject | reject | 반려 |
| E077 | `CALC2-C17` → `CALC2-C22` | approve | approve | 승인 |
| E078 | `CALC2-C17` → `CALC2-P12` | approve | approve | 승인 |
| E079 | `CALC2-C17` → `CALC2-P15` | approve | approve | 승인 |
| E080 | `CALC2-C17` → `CALC2-R06` | reject | approve | 보류 |
| E081 | `COMB-C03` → `COMB-C04` | reject | approve | 보류 |
| E082 | `COMB-C04` → `COMB-C06` | reject | reject | 반려 |
| E083 | `COMB-R01` → `COMB-C09` | reject | reject | 반려 |
| E084 | `CRYP-C06` → `CRYP-C10` | approve | approve | 승인 |
| E085 | `CXAN-C01` → `CXAN-C04` | approve | approve | 승인 |
| E086 | `CXAN-C01` → `CXAN-C06` | reject | reject | 반려 |
| E087 | `CXAN-C03` → `CXAN-C05` | approve | approve | 승인 |
| E088 | `CXAN-C04` → `CXAN-C06` | approve | approve | 승인 |
| E089 | `CXAN-C10` → `CXAN-C12` | approve | approve | 승인 |
| E090 | `CXAN-C10` → `CXAN-P01` | reject | approve | 보류 |
| E091 | `CXAN-C12` → `ODE-C05` | reject | reject | 반려 |
| E092 | `DGEO-C01` → `DGEO-C03` | approve | approve | 승인 |
| E093 | `DGEO-C05` → `DGEO-C07` | approve | approve | 승인 |
| E094 | `DGEO-C06` → `DGEO-C11` | approve | approve | 승인 |
| E095 | `DGEO-C08` → `DGEO-C10` | approve | approve | 승인 |
| E096 | `DGEO-C08` → `DGEO-C12` | approve | approve | 승인 |
| E097 | `FANAL-C01` → `CALC2-C10` | reject | reject | 반려 |
| E098 | `FANAL-C01` → `FANAL-C07` | approve | reject | 보류 |
| E099 | `FANAL-C01` → `FANAL-C08` | approve | approve | 승인 |
| E100 | `FANAL-C01` → `FANAL-P01` | approve | reject | 보류 |
| E101 | `FANAL-C01` → `LINA2-P02` | reject | reject | 반려 |
| E102 | `FANAL-C01` → `RANAL-C09` | reject | reject | 반려 |
| E103 | `FANAL-C01` → `RANAL-C10` | approve | approve | 승인 |
| E104 | `LINA1-C03` → `LINA1-P12` | approve | approve | 승인 |
| E105 | `LINA1-C05` → `LINA1-P05` | reject | approve | 보류 |
| E106 | `LINA1-C10` → `LINA2-C02` | approve | approve | 승인 |
| E107 | `LINA1-C10` → `ODE-P04` | approve | approve | 승인 |
| E108 | `LINA1-C12` → `LINA1-C13` | reject | approve | 보류 |
| E109 | `LINA1-C12` → `LINA1-C16` | approve | approve | 승인 |
| E110 | `LINA1-C12` → `LINA2-C05` | approve | approve | 승인 |
| E111 | `LINA1-C12` → `TOPO1-C07` | reject | reject | 반려 |
| E112 | `LINA1-C13` → `AALG2-C10` | approve | approve | 승인 |
| E113 | `LINA1-C13` → `FANAL-C02` | approve | approve | 승인 |
| E114 | `LINA1-C13` → `LINA1-C17` | approve | approve | 승인 |
| E115 | `LINA1-C14` → `LINA1-C17` | approve | approve | 승인 |
| E116 | `LINA1-C15` → `LINA1-C17` | approve | approve | 승인 |
| E117 | `LINA1-P01` → `LINA1-P06` | approve | approve | 승인 |
| E118 | `LINA1-P01` → `NUMER-C11` | approve | approve | 승인 |
| E119 | `LINA1-P02` → `LINA1-R02` | reject | reject | 반려 |
| E120 | `LINA2-C02` → `LINA2-C08` | approve | approve | 승인 |
| E121 | `LINA2-C06` → `LINA2-R01` | approve | approve | 승인 |
| E122 | `LINA2-C09` → `GALOIS-C03` | reject | reject | 반려 |
| E123 | `LINA2-C10` → `AALG1-P02` | reject | reject | 반려 |
| E124 | `LINA2-C10` → `AALG1-P03` | reject | reject | 반려 |
| E125 | `LINA2-C10` → `AALG2-C04` | reject | reject | 반려 |
| E126 | `LINA2-C10` → `CRYP-C03` | reject | reject | 반려 |
| E127 | `LINA2-C10` → `NUMT1-C01` | reject | reject | 반려 |
| E128 | `LINA2-C10` → `NUMT1-C06` | reject | reject | 반려 |
| E129 | `LINA2-C10` → `NUMT1-C07` | reject | reject | 반려 |
| E130 | `LINA2-C10` → `NUMT1-P02` | reject | reject | 반려 |
| E131 | `LINA2-C10` → `NUMT1-P04` | reject | reject | 반려 |
| E132 | `LINA2-C10` → `NUMT2-C01` | reject | reject | 반려 |
| E133 | `LINA2-C10` → `NUMT2-C07` | reject | reject | 반려 |
| E134 | `LINA2-C10` → `NUMT2-P01` | reject | reject | 반려 |
| E135 | `LINA2-P01` → `LINA2-C03` | approve | approve | 승인 |
| E136 | `LINA2-P01` → `LINA2-C09` | approve | approve | 승인 |
| E137 | `MLOG-C01` → `SETLOG-C01` | reject | reject | 반려 |
| E138 | `MLOG-C02` → `ODE-P03` | reject | reject | 반려 |
| E139 | `MSTAT-C01` → `MSTAT-C03` | approve | approve | 승인 |
| E140 | `NUMER-C01` → `NUMER-C03` | reject | reject | 반려 |
| E141 | `NUMER-C01` → `NUMER-C11` | reject | reject | 반려 |
| E142 | `NUMER-C06` → `NUMER-C12` | approve | approve | 승인 |
| E143 | `NUMER-C06` → `NUMER-C13` | reject | reject | 반려 |
| E144 | `NUMER-C07` → `NUMER-C08` | reject | approve | 보류 |
| E145 | `NUMT2-P01` → `MLOG-C03` | reject | reject | 반려 |
| E146 | `ODE-C01` → `PDE-C07` | reject | reject | 반려 |
| E147 | `ODE-C04` → `ODE-P06` | approve | approve | 승인 |
| E148 | `PDE-C01` → `PDE-C04` | approve | approve | 승인 |
| E149 | `PROB-C09` → `MSTAT-P02` | approve | approve | 승인 |
| E150 | `RANAL-C02` → `RANAL-C04` | reject | reject | 반려 |
| E151 | `RANAL-C02` → `RANAL-C06` | reject | reject | 반려 |
| E152 | `RANAL-C05` → `RANAL-C11` | approve | approve | 승인 |
| E153 | `SET-C01` → `SET-C03` | approve | approve | 승인 |
| E154 | `SET-C04` → `SET-C08` | approve | approve | 승인 |
| E155 | `SET-C07` → `RANAL-C02` | approve | approve | 승인 |
| E156 | `SETLOG-C04` → `MLOG-C02` | reject | reject | 반려 |
| E157 | `SETLOG-C04` → `MLOG-C03` | reject | reject | 반려 |
| E158 | `SETLOG-C04` → `MLOG-C07` | reject | reject | 반려 |
| E159 | `SETLOG-C04` → `MLOG-C08` | reject | reject | 반려 |
| E160 | `SETLOG-C09` → `SETLOG-C11` | approve | approve | 승인 |
| E161 | `SETLOG-C10` → `FANAL-C08` | reject | reject | 반려 |
| E162 | `SETLOG-C11` → `SET-C05` | reject | reject | 반려 |
| E163 | `SETLOG-C11` → `SETLOG-C15` | approve | approve | 승인 |
| E164 | `SETLOG-C11` → `SETLOG-C16` | reject | reject | 반려 |
| E165 | `SETLOG-C11` → `SETLOG-P12` | reject | approve | 보류 |
| E166 | `SETLOG-C11` → `TOPO1-C05` | approve | approve | 승인 |
| E167 | `SETLOG-C13` → `AALG1-C05` | replace(SETLOG-C14) | replace(SETLOG-C14) | 교체 |
| E168 | `SETLOG-C13` → `SETLOG-R05` | reject | reject | 반려 |
| E169 | `SETLOG-C13` → `TOPO1-R02` | replace(SETLOG-C14) | approve | 보류 |
| E170 | `SETLOG-P08` → `SETLOG-C18` | approve | approve | 승인 |
| E171 | `SETLOG-P10` → `TOPO1-C07` | approve | approve | 승인 |
| E172 | `SETLOG-R01` → `SETLOG-R02` | approve | approve | 승인 |
| E173 | `TOPO1-C01` → `AGEO-C02` | approve | approve | 승인 |
| E174 | `TOPO1-C07` → `TOPO1-C12` | approve | approve | 승인 |
| E175 | `TOPO1-C08` → `COMB-C04` | reject | reject | 반려 |
| E176 | `TOPO1-C08` → `COMB-C05` | reject | reject | 반려 |
| E177 | `TOPO1-C08` → `COMB-C07` | reject | reject | 반려 |
| E178 | `TOPO1-C09` → `ATOPO-C03` | reject | reject | 반려 |
| E179 | `TOPO1-C09` → `TOPO2-C07` | approve | approve | 승인 |
| E180 | `TOPO1-C10` → `TOPO1-C12` | approve | approve | 승인 |
| E181 | `TOPO2-C01` → `TOPO1-C08` | reject | reject | 반려 |
| E182 | `TOPO2-C01` → `TOPO2-C04` | approve | approve | 승인 |
| E183 | `TOPO2-C07` → `ATOPO-C01` | approve | approve | 승인 |

## 부록 A — 검수자 A 소견(원문)

## ② 낱말 매칭 규칙에 대한 소견

1. **동음이의 폭주**: '합동'(행렬 합동 vs mod 합동) 12건, '연결'·'평면'·'기저'·'완전성'·'기호'·'분리'·'변수분리'·'최소다항식' 등 낱말만 같고 개념이 다른 후보가 약 30건이다. 낱말 매칭은 *같은 과목군(대수/해석/위상)* 안에서만 허용하거나, 출발·도착의 `subject_area`/`unit`이 다르면 자동 보류시키는 필터가 필요하다.
2. **담지 원자 오선택**: 서술 낱말이 소단원 *이름*(편미분·수렴·기저)인데 매칭된 원자는 그 소단원의 *오개념 명제*(「상한은 최댓값이 아닐 수 있다」·「멱급수 끝점은 따로 확인」)라서 핵심명제가 도착 원자와 어긋나는 경우가 많다. 소단원에 C·P·R이 함께 있으면 도착 원자의 인지축(절차엔 절차·표상엔 표상)에 맞춰 고르는 규칙을 두면 replace 6건(E021·E049·E054·E056·E167·E169)은 자동으로 잡힌다.
3. **기존 체인의 R/P 이웃이 선수로 깔려 있어 개념 원자가 '전이'로 떨어지는 패턴**: 과목 내부 기존 엣지는 C→P→R 순서 체인이라 「균등수렴→균등수렴의 성질」(E034) 같은 명백한 개념 선수가 같은 소단원 R/P 원자를 거친 중복으로 판정된다(E008·E020·E024·E030·E034·E045·E057·E081·E108·E144 10건). 규율상 reject했으나, 체인의 R/P→다음 소단원 엣지를 순서 엣지로 강등하면 이 10건은 approve로 뒤집혀야 한다.
4. **타 과목 중복 원자**: 편미분(ANAL2-P02 vs CALC2-P07)·곡률(CALC2-C12 vs DGEO-C03)·수렴반경(ANAL2-P01 vs CALC1-C25)처럼 같은 개념이 과목마다 원자로 있어 낱말 매칭이 *다른 과목의* 원자를 선수로 끌어온다(E036·E037·E073·E035). 도착 과목 안에 같은 이름의 원자가 있으면 그쪽을 우선하도록 해야 한다.
5. **수준 역방향**: 상위 과목(FANAL·MLOG·ANAL2·TOPO2) 원자가 하위 과목(CALC2·SETLOG·CALC1·TOPO1)의 선수로 매칭된 건이 5건(E035·E097·E101·E137·E181)이다. 과목 선후 순서를 매칭 전에 검사해야 한다.

## 부록 B — 검수자 B 소견(원문)

## ② 낱말 매칭 규칙에 대한 소견

1. **동음이의 체계 오류**가 가장 큼 — "합동"(행렬 합동 vs 수론 합동) 12건, "연결"(위상 vs 그래프) 3건, "증명" 4건, "기저"·"평면"·"완전성"·"기호"·"특이점"·"분리"·"최소다항식" 각 1~2건. 낱말이 과정(코드 접두) 경계를 넘어 해소될 때는 원 서술의 과정 범위 안에서만 해소하거나 사람 확인을 강제해야 한다.
2. **단일 원자 소단원으로의 강제 해소** — 소단원에 원자가 하나뿐이면 그 원자의 *핵심명제*가 아닌 *소단원 주제*가 선수인 경우가 많다(FANAL-C01이 "노름" 전반을, ANAL1-C04가 모든 "수렴"을, SET-C07이 "선택공리"를, PROB-C09가 "적률"을 대표). 핵심명제와 주제가 다른 원자(노름공간 정의·경로 정의·선택공리·그래프 연결성·k차 적률)는 사실상 **원자 부재**이며 신설 후보로 기록해 두는 편이 낫다.
3. **과정 간 중복 원자**(ANAL2-P02 vs CALC2-P07 편미분, CALC2-C12 vs DGEO-C03 곡률, LINA1-P02 vs 10공수1-04-02-1 행렬곱, ANAL2-C09 vs CALC1-P23 항별 미분)에 낱말이 아무 쪽에나 붙어 수준 역전(해석학→미적분, 함수해석→선형대수, 수리논리→집합논리) 엣지가 생긴다. 개념마다 정본 원자 하나를 정하고 선수는 정본으로만 걸어야 한다.
4. **기존 선수가 순서 사슬**이라 "도착 원자의 기존 선수" 정보가 중복 판정에 거의 쓸모없다(CRYP-C03 RSA→C04 이산로그, FANAL-C11 스펙트럼→P01 작용소 노름 등). 전이 판정은 사슬 도달성(from→…→to 존재 여부)이 아니라 "중간 원자가 개념적으로 from의 내용을 전달하는가"로 해야 하며, 표상(R) 원자를 거치는 경로는 전이로 보지 않았다.
5. 상위 과정→하위 과정 방향(FANAL→CALC2, MLOG→SETLOG, ANAL2→CALC1, TOPO2→TOPO1)이 걸러지지 않는다 — 과정 수준 순서 가드(코드 접두별 수준표)를 매칭 단계에 두면 reject 중 약 10건을 기계로 걸러낼 수 있다.
