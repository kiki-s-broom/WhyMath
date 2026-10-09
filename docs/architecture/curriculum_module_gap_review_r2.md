# 교육과정 관리(Curriculum Foundation) 모듈 — 외부 EOS 틀 대조 **2차 재점검(r2)** (2026-08-11)

> **범위**: v1(`curriculum_module_gap_review.md`, 2026-08-03)과 **동일한 외부 참고 문서**
> (『0단계: 교육과정 관리』 ①교육과정 데이터베이스 ②단원 구조 관리 ③성취기준 관리
> ④학습목표(Objective) 관리 ⑤선수학습 관계 그래프 — WhyMath 전용이 아닌 일반적 EOS
> (Education Operating System) 틀, Kiki 제공 docx)을 **v1 이후 착지분이 만든 새 지형**과
> 다시 대조한 기록.
> **성격**: 처음부터의 재대조가 아니라 **델타 재점검**이다. v1의 판정 — 특히 §2 의도적
> 미채택 6건 — 은 전건 유효하므로 **승계하고 재판정하지 않는다**. 다루는 것은 ⑴ v1이 설계한
> 것이 구현된 뒤 **남은 실공백**, ⑵ v1 이후 변화로 **stale해진 칸**, 그리고 ⑶ v1이 **판정
> 자체를 부여하지 않고 넘어간 축**(제출 docx 마지막 문단)뿐이다.
> **v1 이후 상태**: v1이 설계한 3건이 **선언상 모두 done**이다 — `CUR-01`(착지 확인) ·
> `CUR-02`(착지 확인) · `CUR-03`(**done이나 산출물이 main에 없음** — 이것이 D5다).
> 그 사이 `ASM-05`(수요측 성취기준 도달 관측)와 `PED-16`(교수법 선언≠집행 감사)이 착지해
> 교육과정 축의 지형을 바꿨다.
>
> **결론 4줄**:
> 1. **최대 갭 = 성취기준 런타임 조인 축이 이원화된 채 옛 축 소비자 2곳이 남았다.**
>    `api/gating.py:149-151`이 구 4단계 조인(`concept_standard_link`→`achievement_standard`)을
>    **"재연결 후 0행"**으로 판정하고 원자 축으로 갈아탔는데, `api/coach.py:919-920`과
>    `l2/target_progress.py:102-107`은 **여전히 구 축**을 쓴다. 둘 다 graceful 폴백이라
>    실패가 `None`/`0%`로 흡수된다. 성취기준의 **유일한 학생 대면 표면**
>    `GET /v1/me/target-progress`에서 이는 "도달 0%"가 아니라 **조인 실패의 위장**이다 → **D4**.
> 2. **두 번째 갭 = `CUR-03`이 done인데 착지하지 않았다.** artifact `98a34695`는 `origin/main`의
>    조상이 아니고 `data/corpus/achievement_criteria_v1/`는 작업 트리에 없다. 게다가 `CUR-03`
>    acceptance ④가 약속한 후속 태스크(스키마 확장)가 백로그에 **없다** → **D5**.
> 3. **세 번째 갭 = 선수 그래프가 학교급 경계를 거의 넘지 않는다.** 2,210엣지 중 경계 통과
>    **20건**(초→중 9 · 중→고 11 · **고→대 0**). MVP 페르소나 A가 바로 "중학교 결손을 가진
>    고3"인데 그 복구 경로가 그래프에 없다. v1 §1 모듈5의 "✅ 초과"는 **내부 밀도만 보고
>    경계 밀도를 안 본** 판정이었다 → **D6**.
> 4. **v1 스코프 누락 1건 정정** — 제출 docx의 **마지막 문단**(EOS 관점 추가 5종: 개념 Ontology
>    관리·개념–성취기준 매핑·용어 사전·교육 메타데이터 관리·버전/변경 이력 관리)에 v1은
>    판정을 부여하지 않았다(전수 grep 0건, §0-②). r2가 §1B에서 메운다.

관련 정본: `curriculum_module_gap_review.md`(v1 — 이 문서의 모체, 판정 근거의 원본) ·
`gamification_module_gap_review_r2.md`·`operations_module_gap_review_r2.md`(r2 처리 선례) ·
`01_data_foundation.md`(L1 데이터 기반) · `docs/data/achievement_standards_v1.md`(성취기준 895건 정본) ·
`concept_node_layering_decision.md`(9계층 ADR) · `learning_path_module_gap_review.md`(PATH 축 경계) ·
`ai_content_generation_gap_review_2.md`(반복 실수 8회차) · `MEMORY.md` 결정 로그
(2026-08-03 v1 · 2026-08-03~08 `CUR-01`~`CUR-03` · 2026-08-10 `ASM-05`).

---

## §0. 재점검 사유 — 왜 v1을 덮어쓰지 않고 r2를 새로 쓰는가

### ① 동일 문서 재제출임을 구조로 확정한다 (추론 아님)

제출 docx와 v1 §1이 대조한 구성이 **모듈 ID·개수까지 일치**한다:

| 축 | 제출 docx | v1 §1 대조 기록 |
|---|---|---|
| 모듈 수·ID | 5모듈, ID 1~5 (교육과정DB/단원구조/성취기준/학습목표/선수학습그래프) | 동일 5모듈, 같은 순서 |
| 모듈 1 관리 항목 | 8 (버전·국가·학교급·과목·학년·학기·적용년도·폐기여부) | 8행 표 |
| 모듈 2 필요 기능 | 6 (Drag&Drop·이동·병합·분리·Tree·Graph) + 주요기능란의 계층구성·버전비교 | 8행 표 |
| 모듈 3 관리 정보 | 9 (코드·설명·관련단원·난이도·중요도·키워드·개념태그·평가유형·AI임베딩) | 9행 + 외부틀 밖 1행(성취수준) = 10행 |
| 모듈 4 메타데이터 | 7 (행동동사·Bloom·난이도·선수학습·평가방법·교수전략추천·AI생성Prompt) | 7행 + 세분화 2행 = 9행 |
| 모듈 5 | 관계 6종 + AI 기능 5종 | 6행 + 5행 = 11행 |

따라서 이것은 새 요구가 아니라 **재제출**이며, 새 판정이 아니라 **델타**가 답이다.

### ② 그러나 제출 docx의 **마지막 문단은 v1이 판정하지 않았다** (스코프 누락)

docx는 5모듈 뒤에 두 블록을 더 갖는다: ⑴ "WhyMath에서의 역할" 흐름도(하류 소비자 **7종** 열거 —
AI 교수전략/콘텐츠/문제/평가 생성·AI 튜터·AI 오개념 분석·AI 학습경로 추천) ⑵ 마지막 문단
("이 5개만으로는 다소 부족하며, **개념(Ontology) 관리, 개념-성취기준 매핑, 용어 사전, 교육
메타데이터 관리, 버전 및 변경 이력 관리**를 추가하면…").

v1 전문(457행)에 이 둘의 흔적이 **없다**. 실측(2026-08-11):

```
$ for w in "Ontology" "온톨로지" "용어 사전" "변경 이력" "메타데이터 관리" \
           "AI 교수전략" "AI 문제 생성" "AI 평가 생성" "AI 학습경로 추천"; do
    grep -c "$w" docs/architecture/curriculum_module_gap_review.md; done
0 0 0 0 0 0 0 0 0
```

v1 §0은 흐름도를 `"… → 선수학습 그래프 → AI 엔진들"`로 **축약**해 옮겼고, 그 과정에서 7소비자
열거와 마지막 문단이 함께 탈락했다. 이는 v1 판정의 *오류*가 아니라 *미도달*이다 — 잘못 판정한
것이 아니라 판정 대상에 넣지 않았다. **§1B가 이를 메운다.**

### ③ v1을 in-place 수정하지 않는 이유

`operations_module_gap_review_r2.md` §0이 확립하고 `gamification_module_gap_review_r2.md`가
승계한 처리를 그대로 따른다. v1은 이미 완료된 `CUR-01`·`CUR-02`·`CUR-03`의 `notes`가 **판정
근거로 지목하는 원본**이다(3건 모두 `notes`에 `curriculum_module_gap_review.md §3 D1/D2/D3`을
명시). 원본을 고치면 완료 태스크의 근거가 사후 변조된다. **정정은 r2가 보유한다**(§정정).

### ④ v1 이후 지형 (델타의 출발점)

| 변화 | 실측 |
|---|---|
| `CUR-01` 착지 | `harness/curriculum_revision_crosswalk_report.py` + `tests/backend/harness/test_curriculum_revision_crosswalk_report.py` 실재 |
| `CUR-02` 착지 | `harness/objective_coverage.py` + 테스트 실재 |
| `CUR-03` **미착지** | done·artifact `98a34695`이나 main 조상 아님 · `data/corpus/achievement_criteria_v1/` 부재 → **D5** |
| `ASM-05` 신규 착지 | `harness/standard_attainment_report.py` — **수요측** 성취기준 도달 관측. 조인 축이 `Concept.code → AtomNode.code → AtomNode.standard_codes`(**원자 축**, `:10`) |
| `PED-16` 신규 판정 | `unit_spec` 테이블 reader 0 — `objective_coverage`조차 `.unit.yaml` 직접 glob으로 테이블을 우회 |

**`ASM-05`의 착지가 D4를 드러낸 결정적 사건이다.** 같은 질문("학생이 성취기준에 도달했는가")을
재는 두 코드가 **서로 다른 축**으로 존재하게 됐고, 둘을 대조하면 축 분열이 수치로 증명된다.

---

## §1. 델타 대조 — v1 §1에서 **바뀐 칸만**

판정 기호는 v1과 동일: ✅ 충족·초과 / △ 부분(부품은 있는데 배선·데이터 없음) / ⚠️ 진짜 갭 → D /
🚫 의도적 미채택 → v1 §2 승계. **아래에 없는 칸은 v1 판정이 그대로 유효하다.**

| 모듈·항목 | v1 판정 (2026-08-03) | r2 판정 (2026-08-11) | 사유 |
|---|---|---|---|
| 모듈 3 — 관련 단원 연결 | ✅ (`ConceptStandardLink` 443건 + `atom_node.standard_codes` 역방향) | **⚠️ → D4** | 443건은 **적재돼 있으나 런타임 조인이 갈렸다**. `gating.py`는 원자 축으로 이동했고 `coach.py`·`target_progress.py`만 구 축에 남았다 |
| 모듈 3 — 코드·설명 | ✅ **초과** (895건) | ✅ **초과 (단, 2022 축에 한함)** | 실측: 링크 443건이 **전량 2022 개정**. 2015 개정 460건은 링크 0·소비자 0 → §4 신규 공백 ⑧ |
| 모듈 3 — 성취수준(A~E)·평가기준 | ⚠️ → D3 (저장소 0건) | **⚠️ → D5** (여전히 0건) | `CUR-03` done인데 산출물이 main에 없다 — 갭의 *내용*이 아니라 *형태*가 바뀌었다(0건 → "해소됐다고 기록된 0건") |
| 모듈 4 — Objective 데이터 | ⚠️ → D2 (895건 중 1건·0.1%) | **계측기 착지 · 계측값 불변** | `objective_coverage.py`는 돌지만 `units_v1/`은 여전히 소단원 1·목표 4. 새 D 아님 → §5-⑥ 발화조건 재판정 |
| 모듈 5 — `prerequisite` | ✅ **초과** (2,210엣지 + 위상정렬) | **⚠️ → D6** (정밀화) | 내부 밀도는 유효하나 **경계 밀도가 미판정**이었다. 학교급 경계 통과 20/2,210 |
| (횡단) 관리·편집 인터페이스 | 🚫 §2-⑥ (CLI populate 단방향) | 🚫 **승계** | 변화 없음. 재론하지 않는다 |

---

## §1B. 제출 docx 마지막 문단 — "EOS 관점 추가 5종" 판정 (**v1 미판정 축**)

| # | 추가 제안 | 판정 | 근거 |
|---|---|---|---|
| ㉮ | **개념(Ontology) 관리** | ✅ **충족·초과** | 원자 백본 2,683노드 + 개념 축 437노드가 적재돼 있고, 노드 계층 설계는 9계층 ADR(`concept_node_layering_decision.md`)로 정본화됐다. 외부 틀은 "온톨로지를 추가하라"고 권하지만 WhyMath는 **온톨로지가 루트이고 교육과정이 Overlay**다(v1 §0-② 방향 전도). 추가할 것이 아니라 이미 축의 중심이다 |
| ㉯ | **개념–성취기준 매핑** | ⚠️ **D4로 흡수** | 스키마(`ConceptStandardLink`)·데이터(443건)·역방향(`atom_node.standard_codes`) 모두 있다. 문제는 존재가 아니라 **런타임 조인 축이 둘로 갈렸다**는 것 → 별도 D를 세우지 않고 D4가 처리 |
| ㉰ | **용어 사전(Glossary)** | 🚫 **중복 등재 배제 + 승계 부기** | ⑴ `docs/architecture/glossary.md`는 **개발자 용어집**(L계층·S단계·Phase 축)이지 학생 수학 용어 사전이 아니다. ⑵ 학생 표기 축은 **`NS-03`(done, 표기 커버리지 하네스)**가 이미 소유한다. ⑶ `Concept.aliases`는 레거시 키 조인용(`concept.py:81-84` "옛 키 별칭")이지 동의어 사전이 아니다. 세 축 모두 주인이 있으므로 새 태스크를 만들지 않는다 |
| ㉱ | **교육 메타데이터 관리** | ✅ (일부 △ — v1 §4-④ 승계) | `CurriculumEntry` 31필드가 정본이며 `entry_id` PK + `UNIQUE(concept_id, country_code, subject)`로 적재 중. 단 `notation_local`·`notation_variants`는 `curriculum_loader.py:46-50`이 **"소스에 신호 없음·날조 금지"**로 명시 미매핑 — v1 §4-④와 같은 가족이므로 승계하고 재론하지 않는다 |
| ㉲ | **버전 및 변경 이력 관리** | △ **정직한 공백** (신규 ⑨) | 버전 *보존*은 있다(`UnitSpec` 복합 PK `(unit_id, unit_version)`). 없는 것은 **변경 이력(audit trail)** — 성취기준·개념이 언제 누구에 의해 무엇으로 바뀌었는지 기록하는 축이 0이다. 다만 현행은 **YAML=소스·DB=산출물 단방향 populate**라 변경 주체가 git 커밋이고, git이 사실상 이력을 보유한다. DB 이력 테이블을 지금 만들면 이중 진실 원천이 된다 → §5-③(폐기여부/종료일)과 **같은 트리거**(2028 개정 시행)에 묶는다 |

**7소비자 흐름도(docx "WhyMath에서의 역할")에 대한 판정**: 열거된 7종 중 **AI 튜터·AI 오개념
분석·AI 학습경로 추천**은 교육과정 신호를 실제로 소비한다(각각 `api/coach.py`·
`l4/misconception/crosslink_standard_signal.py`·`l2/learning_path.py`). **AI 문제 생성·AI 평가
생성**도 소비한다(`l3` 골격 생성기 12종이 `spec.achievement_standard_codes`를 사용,
`api/me.py` 청사진 조립이 성취기준×난이도 축). 즉 틀이 그리는 하류 소비 구조는 **이미 성립해
있다** — 갭이 아니다. 다만 그 중 `api/coach.py`가 D4의 옛 축 소비자라는 점이 이 대조에서 드러났다.

---

## §2. v1 미채택 6건 — **전건 승계 · 재판정 없음**

제출 docx는 v1 때와 같은 제안을 반복한다(모듈1의 "학기", 모듈2의 "Drag & Drop·단원 이동/병합/분리",
모듈5의 "related·similar·contains·equivalent"). v1 §2가 이미 판정했고 근거는 변하지 않았다.

| # | 문서 제안 | v1 판정 | r2 |
|---|---|---|---|
| ① | 학기(semester) 축 재도입 | **영구 불채택** (마이그레이션 `20260630_1200`으로 이미 드롭) | 승계 |
| ② | `related`/`similar`를 traversal 관계로 | **영구 불채택** (CLAUDE.md 명문 금지 — 관계 폭발 1순위) | 승계 |
| ③ | `contains` 엣지 신설 | **영구 불채택** (`parent_code` 컬럼과 이중 표현) | 승계 |
| ④ | `equivalent` 엣지 신설 | **영구 불채택** (SymPy `canonicalize`가 유일 권위) | 승계 |
| ⑤ | 다국가 풀스케일 | 조건부 유보(Phase 3) | 승계 — 발화조건 §5-① 불변 |
| ⑥ | 사람 편집 GUI(Tree Drag&Drop·이동/병합/분리) | 조건부 유보 | 승계 — 발화조건 §5-② 불변 |

**재론하지 않는다.** 같은 제안이 두 번 왔다는 사실 자체는 판정을 바꾸는 근거가 아니다.

---

## §3. 진짜 갭 설계 — D4 · D5 · D6

번호는 v1의 D1~D3에 이어 계속한다.

---

### D4 — 성취기준 런타임 조인 축 이원화 → 학생 대면 표면이 구조적 0% (최우선 · `CUR-04`)

**문제.** `S2-03`(문항↔개념 원자 재연결) 이후 성취기준 조인 축이 갈렸다.
`api/gating.py:149-151`이 이를 직접 기록한다:

> "구 4단계 조인(`concept_standard_link` → `achievement_standard` — 구 437 code 공간·**재연결 후
> 0행**)을 원자 축으로 교체했다."

즉 **구 축이 0행이라는 사실은 이미 저장소에 적혀 있다.** 그런데 같은 조인을 쓰는 소비자 2곳이
남았다:

| 소비자 | 위치 | 조인 | 실패 시 거동 |
|---|---|---|---|
| 코치 프롬프트 개인화 | `api/coach.py:917-923` (`_standard_code_for`) | `ConceptStandardLink.concept_code == Concept.code` → `AchievementStandard.official_code` | `graceful None` (docstring `:906-907`이 명시) |
| 학생 목표 진행률 | `l2/target_progress.py:102-107` | 동일 키 공간 조인 | `coverage_observed=0` → `coverage_percent=0.0` |

**결정적 단서 — 옛 축 소비자의 docstring이 이미 stale하다.** `coach.py:906-907`은 이 조인을
정당화하며 *"L6 게이팅의 **동일 조인 관례와 정합**"*이라고 적는다. 그런데 그 L6 게이팅이
바로 **이 조인을 버린 쪽**이다(`gating.py:149-151`). 즉 코드가 근거로 삼은 정합 대상이
이미 이동했는데 주석은 그대로다 — 이주 미완이 문서 층위에도 남아 있다는 증거이고,
"두 소비처가 의도적으로 구 축에 남은 것이 아니라 **잊혔다**"는 판정의 근거다.

**왜 지금까지 안 드러났는가.** 세 겹의 위장이 겹쳤다.
⑴ `coach.py`의 `None`은 "성취기준 연결 미적재"라는 **정당한 경우와 구분되지 않는다** —
docstring이 스스로 *"성취기준 연결 미적재 어느 단계든 graceful None(폴백)"*이라 적어 두어,
항상 None인 상태가 설계된 동작처럼 읽힌다.
⑵ `target_progress.py`는 **0으로 나누기를 정직하게 방어**한다(`:118-120`: 스코프 0건이면
`coverage_percent=None`으로 "스코프 없음"과 "0% 커버"를 구분). 이 정직함이 역설적으로
`coverage_scope > 0`인 정상 경로를 신뢰하게 만든다 — 분모는 살아 있고 분자만 죽었는데,
그 조합이 **"측정은 됐고 결과가 0%"**로 보인다.
⑶ v1 §1 모듈3이 `ConceptStandardLink` **443건이라는 적재 사실**만 보고 ✅를 줬다. 적재량은
조인 성립을 뜻하지 않는다.

**핵심 판단.** 이것은 커버리지가 낮은 문제가 아니라 **측정 실패가 미달로 위장된** 문제다.
CLAUDE.md가 세 곳에서 금지한다 — "침묵 실패 금지"(예외를 삼키는 관측성 코드) ·
"인프라가 죽으면 '측정 실패'가 보여야지 '0건 통과/미달'로 위장되면 안 된다" ·
"작동 신호 없는 알고리즘 부착 금지 — 정상 응답 200은 알고리즘이 일했다는 증거가 아니다".
그리고 이것은 **학생이 보는 화면**이다(`GET /v1/me/target-progress`는 성취기준 축의 유일한
학생 대면 표면). 의사결정 우선순위 1번(학생 안전·웰빙 — 부정확)에 직접 걸린다.

**정합 설계 (신규 스키마 0 · 마이그레이션 0).** 이미 저장소에 정답이 두 개 있다:
- `api/gating.py::_fetch_achievement_codes` — 원자 축 단일 IN 쿼리(N+1 0), 배열 평탄화 관례 포함
- `harness/standard_attainment_report.py:10` — `Concept.code → AtomNode.code → AtomNode.standard_codes`

두 소비처를 이 축으로 정렬하고, 조인이 0행일 때 **조용히 폴백하지 않고 계수한다**(`작동한 비율`
원칙 — 응답 또는 로그가 "조인이 몇 건 성립했는가"를 말해야 한다).

**dead code 금지 충족.** 새 컬럼·새 테이블을 만들지 않는다. 오히려 구 축 의존을 걷어내
`ConceptStandardLink`의 실사용처를 명확히 한다 — 걷어낸 뒤 소비자가 0이 되면 그 사실이
드러나는 것 자체가 산출물이다(테이블 거취는 별도 판단, 이 태스크 범위 밖).

**변별력 (핵심).** 같은 데이터에서 **두 측정이 일치하는지** 대조한다:
`GET /v1/me/target-progress`의 `standard_coverage_percent` ↔
`harness/standard_attainment_report.py`의 도달 집계. 현행은 **API=0% · 리포트>0%로 갈려야
하고**, 수정 후 **일치해야 한다**. 두 값이 수정 전후 모두 같으면 그 검사는 위장이다
(CLAUDE.md "변별력 없는 검증 스텝 금지").

**acceptance 후보**
1. **현행 실측 고정**: `coach.py::_standard_code_for`와 `l2/target_progress.py`의 구 축 조인이
   실제 데이터에서 0행임을 재현한다(**주장 확인 또는 반증** — 반증되면 범위 재조정).
   `gating.py:149-151`의 "재연결 후 0행" 기록이 두 소비처에도 성립하는지가 판정 대상이다.
2. **정합 설계 본체**: 두 소비처를 원자 축(`AtomNode.standard_codes`)으로 정렬한다.
   `gating.py::_fetch_achievement_codes`·`standard_attainment_report`의 조인 패턴 재사용,
   신규 스키마·마이그레이션 0, N+1 0 유지.
3. **CI 배선 실재 확인**: 신규 테스트가 기존 backend 잡에서 실제로 실행되는지 확인한다
   (OPS-03·OPS-10 — "저장소에 존재함"과 "돌아감"은 다르다).
4. **변별력**: `/v1/me/target-progress`와 `standard_attainment_report`를 같은 fixture에서 대조해
   수정 전 불일치·수정 후 일치를 테스트로 동결한다. 양쪽에서 같은 값이 나오는 fixture만으로
   검증하면 위장이다.
5. **범위 밖 명시**: `ConceptStandardLink` 테이블의 거취(드롭·보존) 결정과 2015 개정 460건의
   링크 보강은 이 태스크에 포함하지 않는다(§4-⑧에 발화조건 기록).

**의존**: 없음(즉시 착수). **태스크**: 신설 — `CUR-04-standard-join-axis-unification`.

---

### D5 — `CUR-03` 완료 선언 ≠ 착지 + 약속된 후속 태스크 미등재 (`CUR-05`)

**문제.** `backlog/tasks/CUR-03-achievement-level-data-intake.yaml`은
`status: done` · `artifacts: [98a34695]` · `updated: 2026-08-08`이다. 실측(2026-08-11):

```
$ git merge-base --is-ancestor 98a34695 origin/main ; echo "EXIT=$?"
EXIT=1                                  # main의 조상이 아님
$ git branch -a --contains 98a34695
  remotes/origin/claude/human-bottleneck-tasks-6dszy0
  remotes/origin/merge/human-bottleneck-6dszy0
$ ls data/corpus/ | grep -c achievement_criteria
0                                       # 작업 트리에 부재
```

즉 **v1 §3 D3이 지적한 "성취수준·평가기준 저장소 전체 0건"은 main 기준으로 여전히 0건**이다.
바뀐 것은 데이터가 아니라 **대장의 기록**뿐이다. 이것이 D3보다 나쁜 이유는, 0건이라는 사실이
이제 `status: done`에 가려 **보이지 않게 됐다**는 점이다.

**두 번째 결손.** `CUR-03` acceptance ④는 이렇게 약속했다:

> "④ 범위 밖 명시: 반입 후 `AchievementStandard` 스키마 확장(신규 컬럼·마이그레이션)은 이
> 태스크에 포함하지 않는다 — **별도 후속 태스크로 분리 등재한다**(데이터가 스키마보다 먼저)"

백로그 239건 전수에서 그 후속 태스크는 **없다**. `docs/standards/unmerged_done_triage_2026-08-08.md`
에도 `CUR-03`은 등재돼 있지 않다 — 미머지 done을 잡는 기존 장치가 이 건을 놓쳤다.

**왜 지금까지 안 드러났는가.** `CUR-01`·`CUR-02`가 정상 착지했고 셋이 같은 `CUR-` 축에 묶여
있어서, 축 단위로 보면 "교육과정 태스크 3건 완료"로 읽힌다. 그리고 done 판정의 증적은
**커밋 SHA의 존재**이지 **그 SHA가 trunk에 있는지**가 아니었다.

**단발이 아니라 계통이다 (판정 정직화).** `CUR-03`만의 사고가 아니다 — 같은 날
`backlog.py next`가 미머지 완료를 이유로 후보에서 제외한 태스크가 **17건**이다
(`ADMIN-01/02/03`·`ASM-06`·`MISC-01/02/03/05/06`·`MOB-11`·`PATH-03`·`PB-02/04`·`S3-28`·
`S3-32`·`S4-09`·`S4-22`). 즉 미머지 done은 이 저장소의 **상시 상태**이고, 하네스는 그것을
*탐지는* 한다. `CUR-03`이 특별한 이유는 두 가지다: ⑴ 탐지 목록에 **뜨지 않는다**(YAML이
`done`이라 후보 계산 자체에서 빠지므로 "미머지 done"으로 경고될 기회가 없다 — 위 17건은
전부 아직 `todo`/`in_progress`라서 잡힌 것이다) ⑵ 산출물이 **코드가 아니라 데이터**라 어떤
테스트도 그 부재를 보지 못한다. **따라서 D5는 `CUR-03` 1건의 회수를 요구하되, 원인은
"done 처리된 태스크는 미머지 탐지의 사각"이라는 구조에 있다** — 그 구조적 대응은
`HARN-11/12`·`unmerged_done_triage` 축의 소관이므로 여기서 새 태스크를 만들지 않고
이 판정을 기록으로 남긴다.

**핵심 판단.** CLAUDE.md **"정본화를 집행으로 착각한 완료 선언 금지"**의 데이터 축 변형이다.
그 규칙이 "계약을 서빙 코드가 실제로 부르는가"를 묻는다면, 이 건은 **"반입한 데이터가 실제로
trunk에 있는가"**를 묻는다. 동시에 **"만료 없는 유예·제외 금지"**(미머지 완료분을 전제로 한
유예는 만료·재확인 지점을 동반해야 한다)에도 걸린다 — 여기엔 재확인 지점이 없었다.

**정합 설계.** ⑴ 원본 커밋에서 `data/corpus/achievement_criteria_v1/`(3,579행 JSON) + 데이터
카드 + `licensing_safety.md` 2행을 main 경로로 회수한다. ⑵ acceptance ④가 약속한 스키마 확장
후속을 **이 태스크의 acceptance에 등재 의무로 박는다** — 또 약속만 남지 않도록.
⑶ 회수 시점에 원본 브랜치의 claim 상태를 확인한다(2026-08-11 현재
`claude/subject-problems-theory-check-7n9n72`가 `S3-34`로 claim 중 — 그 브랜치를 조작하지 않고
커밋 내용만 가져온다).

**dead code 금지 충족.** 데이터가 먼저 착지하고 스키마는 그 다음이다(`CUR-03` 원설계의
"데이터가 스키마보다 먼저" 원칙 승계). 스키마 확장을 이 태스크에서 하지 않는 이유가 그것이다.

**변별력.** 회수 전 `git merge-base --is-ancestor <sha> origin/main`이 **exit 1**,
회수 후 데이터 파일이 main 경로에 존재하고 라이선스 카드가 동반됨을 확인한다.
`ls`의 화면 출력이 아니라 **exit code로 판정**한다(CLAUDE.md "검사 명령의 출력을 억제하거나
잘라서 판정 금지").

**acceptance 후보**
1. **현행 실측 고정**: `98a34695`가 `origin/main` 조상이 아니고 `data/corpus/achievement_criteria_v1/`
   가 부재함을 exit code로 재현한다(주장 확인 또는 반증). 원본 브랜치의 현재 claim 상태도 함께 확인한다.
2. **정합 설계 본체**: 코퍼스 + 데이터 카드 + 라이선스 등재 2행을 main 경로로 회수한다.
   KICE 보고서 라이선스는 NCIC와 다를 수 있으므로 카드의 라이선스 표기를 재확인한다
   (`CUR-03` acceptance ③ 승계).
3. **약속 이행 강제**: `AchievementStandard` 스키마 확장 후속 태스크를 `backlog.py add`로
   **이 태스크 완료 전에** 등재한다. 등재하지 않으면 done 불가 — `CUR-03`이 약속만 남긴 재발을 막는다.
4. **변별력**: 회수 전 exit 1 / 회수 후 파일 존재 + 카드 동반을 확인한다. 성공·실패 양쪽에서
   같은 신호를 내는 검사(예: 브랜치 목록 출력만 보기)는 쓰지 않는다.
5. **범위 밖 명시**: 스키마 확장 구현·성취수준 데이터의 런타임 노출은 포함하지 않는다(후속 태스크 소관).

**의존**: 없음. **태스크**: 신설 — `CUR-05-achievement-criteria-corpus-recovery`.

---

### D6 — 학교급 경계 선수 연결 20건 → 페르소나 A의 결손 복구가 구조적으로 불가 (`CUR-06`)

**문제.** 원자 백본 2,683노드·2,210엣지는 전량 `prerequisite`이지만, **양끝점의 학교급이 다른
엣지는 20건**뿐이다. 실측(2026-08-11, `data/corpus/atom_graph_v1/graph.json` 양끝점
`school_level` 집계):

| 엣지 | 건수 |
|---|---|
| 초등 → 초등 | 529 |
| 중학 → 중학 | 240 |
| 고등 → 고등 | 940 |
| 대학 → 대학 | 481 |
| **초등 → 중학** | **9** |
| **중학 → 고등** | **11** |
| **고등 → 대학** | **0** |
| 같은 학교급 내부 합계 | 2,190 (99.1%) |
| **경계 통과 합계** | **20 (0.9%)** |

**20이라는 수는 이중으로 확인된다.** 코퍼스 엣지는 소스 저작 시점의 경계 표시 필드
`school_link`(bool)를 갖는데, 그 값이 `true`인 엣지가 **정확히 20건**이고 위의 양끝점 유도
집합과 **불일치가 0**이다(`flag only: 0 · endpoint only: 0 · both: 20`). 즉 "경계 연결이 20건"은
내가 유도한 해석이 아니라 **소스 자신이 그렇게 표시한 사실**이다.

(별개로 `relation_subtype` 라벨은 `학년간 8`·`학교급간(추정) 8`로 합 16이라 20과 어긋난다.
이는 주관 분류 축이 `school_link`와 정렬돼 있지 않다는 **코퍼스 내부의 사소한 라벨 불일치**이고,
경계 판정의 권위는 `school_link`+양끝점(둘이 일치)에 둔다.)

**왜 이것이 갭인가.** MVP 타깃 페르소나 A는 **일반고 고3**이고, 이 앱의 핵심 약속은 "성취기준
기반 정밀 진단 + 결손 복구"다. `l2/prerequisite_recommendation.py::recommend_prerequisite_gaps`는
재귀 CTE로 선수를 거슬러 올라가지만, 고등 노드에서 출발한 traversal이 중학으로 넘어갈 수 있는
문이 **11개**다. 즉 "중학교에서 무너진 고3"의 결손을 그래프가 **표현할 수 없다**. 알고리즘이
아니라 데이터의 위상 문제다.

**왜 지금까지 안 드러났는가.** v1 §1 모듈5는 "2,210건 적재 + 재귀 CTE + Kahn 위상정렬"을 보고
✅ 초과를 줬다. 그 셋은 전부 사실이다 — **내부 밀도**가 충분하기 때문에 어떤 단원 안에서든
traversal은 잘 돈다. 경계 밀도는 총량에 묻혀 보이지 않았다(20/2,210 = 0.9%).
`PATH-01`이 실측한 "기본값에서 96.4%가 `tiebreak_only`"도 같은 층위의 신호였지만, 그 리포트는
*순서화 실효성*을 재지 *연결 위상*을 재지 않는다.

**핵심 판단 — 관측이 먼저다.** 엣지를 지금 만들면 안 된다. 소스에 없는 선수관계를 채우는 것은
**교수학 날조**이고(CLAUDE.md — 신호 없이 관계를 채우지 않는다), 관계 폭발의 시작점이다.
따라서 이 태스크는 **경계 연결 밀도를 재는 계측기**까지만 만든다.

**중복 회피 (전수 확인).**
- `PATH-03`(YAML상 todo이나 실제로는 **미머지 done** — `backlog.py next`가
  `claude/whymath-mvp-plan-architecture-trjg5x`에서 완료를 탐지) — *전이* 순서 제약.
  학생의 **막힌 선수 집합 내부** 순서 축이고 `l2/learning_path.py`만 건드린다. 축이 다르다.
- `S4-01`(todo, pri 1, `data-pipeline`) — "수학 K-12 완성 — 초·중 확장 + 대학과정 연결".
  경계 연결은 **본래 이 태스크 소관**이다. 그런데 acceptance가
  `"초·중·고+대학 4축 활성 + traversal 성능 예산 실부하 통과"` **한 줄**이라, 네 학교급의
  노드가 모두 존재하기만 하면 충족으로 읽힐 수 있다 — 현행이 정확히 그 상태다(노드는 4축 다
  있고 연결이 20건). **acceptance가 갭을 통과시키는 구조**다.
  → 따라서 **엣지 생성·적재는 이 태스크 범위 밖(= `S4-01` 소관)**으로 명시하고, 이 태스크는
  계측기 + `S4-01` acceptance 정밀화만 한다. 새 태스크로 `S4-01`을 대체하지 않는다.

**정합 설계 (신규 스키마 0).** `harness/learning_path_orderability_report.py`(PATH-01 산출)와
`data_pipeline/graph_analytics/analytics.py`의 집계 패턴을 재사용해, 학교급·학년 경계별 엣지
밀도와 **"고등 노드에서 중학 노드로 도달 가능한 비율"**을 빌드타임 리포트로 낸다.
**게이트가 아니다** — 밀도가 0이어도 exit 1을 내지 않는다(교육과정 축 리포트 전체의 공통 규약:
"커버율에 임계를 걸어 CI를 빨갛게 만드는 순간 저작 우선순위 입력이라는 용도가 파괴된다").

**변별력.** 경계 엣지를 fixture에서 1건 추가·제거했을 때 도달 가능 비율이 실제로 움직이는지
확인한다. 총 엣지 수만 세는 지표는 경계 1건 변화에 반응하지 않으므로 위장이다.

**acceptance 후보**
1. **현행 실측 고정**: 학교급 경계 통과 엣지 20건(초→중 9·중→고 11·고→대 0)과 같은 학교급 내부
   2,190건을 재현한다(주장 확인 또는 반증). **소스 플래그 `school_link=true` 20건과 양끝점 유도
   집합이 불일치 0으로 일치**함을 함께 고정한다(이중 확인). 부수적으로 `relation_subtype`
   라벨 합(학년간 8+학교급간(추정) 8=16)이 20과 어긋나는 코퍼스 내부 라벨 불일치도 기록한다 —
   판정 권위는 `school_link`+양끝점에 둔다.
2. **정합 설계 본체**: 경계 연결 밀도 + "고등 출발 → 중학 도달 가능 비율" 리포트를 `harness/`에
   추가한다(`learning_path_orderability_report`·`graph_analytics` 패턴 재사용, 신규 스키마 0, 게이트 아님).
3. **CI 배선 실재 확인**: 신규 워크플로 없이 기존 harness 잡에 편입되는지 확인한다.
4. **변별력**: fixture에서 경계 엣지 1건을 넣고 빼서 도달 비율이 움직이는지 확인한다.
   총 엣지 수만 세는 지표로는 검증하지 않는다.
5. **범위 밖 명시 + `S4-01` 정밀화**: 경계 엣지의 **생성·적재는 하지 않는다**(신호 없는 관계 =
   교수학 날조). 대신 `S4-01` acceptance에 "경계 연결 밀도"를 명시 항목으로 추가해, 노드 4축
   존재만으로 충족 판정되지 않게 한다.

**의존**: 없음. **태스크**: 신설 — `CUR-06-cross-school-prerequisite-connectivity`.

**착지 (2026-10-08 · `CUR-06`)**: `harness/cross_school_connectivity_report.py` — 학교급 쌍별 밀도 ·
학년군 경계 · `school_link` 이중 확인 · 하향 도달 비율(≤1·2·5홉·무제한)을 낸다(게이트 아님·exit 0/2).
실측: 경계 20/2,210(0.9%)은 그대로 재현됐고, 플래그 20건과 양끝점 유도 20건은 불일치 0(both 20)이다.
**고등 925노드 중 중학에 닿는 노드는 ≤5홉 123(13.3%)·무제한 387(41.8%)**, 대학 1,069노드는 어떤 하위
학교급에도 0(고→대 경계 0이므로)이다. 이 리포트는 병합된 정본 `graph.json`만 읽으므로 S4-01의
제안 파일(고→대 24건 · 과목 간 129건)은 정본 반영 전까지 수치에 들어가지 않는다. 관측 스텝은
`harness-integrity` 잡에 편입(신규 잡 0)했고 `S4-01` acceptance에 "경계 연결 밀도" 항을 추가했다.

---

### 페이퍼 갭 — `PREREQUISITE` 외 5종 관계 미적재 (**v1 §3 판정 승계 · 태스크 신설 없음**)

`EdgeType`의 `COMPOSED_OF`/`ANALOGOUS_TO`/`EXTENDS`/`CONTRASTS`/`TRIGGERS_DISTRACTOR` 5종은
어휘만 선언돼 있고 적재기가 `prerequisite`이 아니면 skip한다. v1이 "소스 코퍼스에 신호 자체가
없다 → 신호 없이 채우면 교수학 날조"로 판정했고 **근거는 변하지 않았다**(실측 재확인: 2,210엣지
전량 `relation: "prerequisite"`). 발화 조건 v1 §5-④ 유지.

### §3 등재 요약

| 태스크 | 설계 | track | stage | priority | 근거 |
|---|---|---|---|---|---|
| `CUR-04-standard-join-axis-unification` | D4 | infra-debt | S3 | **1** | 학생 대면 표면의 침묵 실패. 축 통일 대상은 2곳, 정답 패턴이 이미 저장소에 2개 존재. 테이블 거취는 범위 밖 |
| `CUR-05-achievement-criteria-corpus-recovery` | D5 | infra-debt | S1 | 2 | done↔미착륙 불일치 + 약속된 후속 태스크 미등재. 스키마 확장은 범위 밖(후속 등재는 의무) |
| `CUR-06-cross-school-prerequisite-connectivity` | D6 | math-completion | S4 | 3 | 경계 연결 0.9% 관측. 엣지 생성은 범위 밖(`S4-01` 소관·acceptance 정밀화만) |

태스크는 전건 `backlog.py add` CLI 경유로 등재한다(ID 손편집 0 · 번호 충돌은 CLI가 로컬+원격
양쪽 검사 — HARN-10·HARN-15). `--path` 선언으로 겹침 검사를 켰다.

---

## §4. 정직한 공백 — 지금 하지 않는 것

v1 §4의 7종(①단원 순서·이동/병합/분리 ②Tree/Graph 뷰어 ③적용년도 종료일·폐기여부
④성취기준 난이도·중요도·키워드·평가유형·임베딩 ⑤학습목표 자동 생성 ⑥Bloom을 `LearningObjective`에
부착 ⑦행동동사→k_type 매핑 사전)은 **전건 승계**한다. 근거가 변한 것이 없다.

r2에서 추가하는 공백 2종:

⑧ **2015 개정 460건의 거취** — 실측: 링크 443건이 전량 2022 개정이고 **2015 개정 460건은 링크
   0건**(2022는 미링크 0건). `l2/target_progress.py:34-35`도 스코프를 `"2022 개정" × "고등학교"`로
   고정한다. 즉 2015 460행은 **적재돼 있으나 아무도 읽지 않는다.**
   지금 링크를 채우지 않는 이유: `docs/data/curriculum_2022_revision.md`가 "핵심 K-12 학년 9개 중
   7개가 2022 적용 → 백본은 반드시 2022 우선"으로 확정했고, 2015를 필요로 하는 페르소나
   C(검정고시·N수)는 **v1.5 범위**다. 지금 460건을 링크하면 쓰이지 않는 매핑을 저작하는 것이 된다.
   지금 지우지도 않는 이유: 페르소나 C 착수 시 재수집 비용이 크고, 적재 자체는 무해하다
   (읽는 코드가 없으므로 오염 경로 없음). **발화 조건은 §5-⑦.**

⑨ **변경 이력(audit trail) 테이블** — §1B-㉲. 현행은 YAML=소스·DB=산출물 단방향이라 변경 주체가
   git 커밋이고 git이 사실상 이력을 보유한다. DB 이력 테이블을 지금 만들면 **이중 진실 원천**이
   된다. **발화 조건은 §5-③에 통합**(폐기여부/종료일과 같은 트리거).

---

## §5. 유보 항목의 발화 조건 — 재판정

v1 §5의 6건 중 **상태가 실측으로 바뀐 것만** 재판정한다. 나머지는 그대로다.

| # | 유보 항목 | v1 발화 조건 | r2 재판정 |
|---|---|---|---|
| ① | 다국가 풀스케일 | 한국 외 2개국 실사용 신호 | **불변** — 신호 없음 |
| ② | 단원 관리 GUI | `CUR-01`·`CUR-02` 관측 결과 수작업 신호 실측 | **불변** — 두 리포트 착지했으나 수작업 오류·보정 빈도 신호 0 |
| ③ | 폐기여부/종료일 필드 | 2028 개정 시행으로 실제 superseded 발생 | **불변 + §4-⑨(변경 이력) 통합** — 같은 트리거를 공유한다 |
| ④ | `PREREQUISITE` 외 5종 적재 | 소스 신호 실측 | **불변** — 2,210엣지 전량 prerequisite 재확인 |
| ⑤ | 성취기준 메타 파생 | 난이도 스케일 통합 이후 파생 | **불변** |
| ⑥ | **학습목표 자동 생성** | "`CUR-02` 관측이 커버리지 확대 필요를 수치로 보여주고, **사람 검수 워크플로(리뷰 큐)가 먼저 설계된 뒤**" | **앞 조건 충족 · 뒤 조건 미충족 → 계속 유보.** `CUR-02` 착지 후 8일이 지났고 `units_v1/`은 여전히 소단원 1·목표 4(0.11% 불변)이므로 "확대 필요"는 수치로 드러났다. 그러나 리뷰 큐 설계는 0건이다. **순서를 바꾸지 않는다** — v1이 명시한 순서를 여기서 뒤집으면 "입력 없는 파이프라인"이 된다 |
| ⑦ | **(신규) 2015 개정 460건 링크 보강** | — | 페르소나 C(검정고시·N수, v1.5)가 로드맵에 진입하거나, 2015 이수 코호트의 실사용 신호가 실측되면. **수요가 먼저다** — 지금 저작하면 읽는 코드가 없는 매핑이 된다 |

**⑥에 대한 부기**: 이 재판정 자체가 `CUR-02`가 계측기로서 제 역할을 했다는 증거다 —
발화 조건의 절반이 수치로 판정 가능해졌다. 나머지 절반(리뷰 큐)이 없다는 사실도 함께 드러났다.

---

## §6. 반복 실수 — 10회차 (재발방지 등재)

`ai_content_generation_gap_review_2.md` §4가 8회차, `gamification_module_gap_review_r2.md` §7이
9회차를 등재했다. r2에서 **10회차**가 나온다.

| 회차 | 사례 | 형태 |
|---|---|---|
| 1 | `tests/infra` 199건이 어떤 잡도 실행하지 않음(OPS-03) | 만들고 **CI에 배선 안 함** |
| 2 | 전 시각화 스택 학생 도달 0회(VIZ-01) | 만들고 **적재 안 함** |
| 3 | OCR 전 파이프라인 비활성(NLP-01) | 만들고 **배포에 넣지 않음** |
| 4 | `POST /v1/me/attempts` 클라 호출 0회(REC D1) | 만들고 **입력을 잇지 않음** |
| 5 | 개인화 가중 기본 off(REC D1) | 만들고 **켜지 않음** |
| 6 | `select_probe` 후보 공급원 0(REC D2) | 만들고 **공급원을 잇지 않음** |
| 7 | `LearningObjective` 완비 + 실데이터 1건(v1 D2) | 만들고 **분해하지 않음** |
| 8 | 교수법 콘텐츠 슬롯 파이프라인 호출자 0(PED-06) | 만들고 **켜는 스위치가 없음** |
| 9 | 성장의 증거가 클라 상태까지 도달했는데 렌더 0(게임화 r2 D6) | 만들고 **마지막 한 겹을 안 그림** |
| **10** | **성취기준 조인 축을 원자 축으로 갈아탔는데 소비자 2곳이 옛 축에 남음(D4)** | **이었다가 끊었는데 끊긴 걸 아무도 안 봄** |

**10회차가 1~9회차와 다른 점.** 앞의 아홉은 전부 **한 번도 이어진 적이 없다** — 만들었고,
잇지 않았다. 10회차는 **한때 정상 작동했던 경로가 이주 중에 끊긴 것**이다. 이 차이가 탐지를
어렵게 만든다:

- 1~9회차는 "호출자 0" · "적재 0" · "렌더 0"처럼 **셀 수 있는 0**이 있었다. 정적 스캔으로
  잡힌다(`concept_reach_report.py`가 그 장치다).
- 10회차는 **호출자도 있고 응답도 200이고 값도 나온다.** 값이 `None`/`0%`일 뿐이고, 그
  `None`/`0%`는 **정당한 경우와 문자열 하나 다르지 않다.** 정적 스캔으로는 안 잡힌다 —
  같은 질문을 재는 **두 번째 측정**(ASM-05)이 다른 축으로 착지한 뒤에야 대조가 가능해졌다.

**재발방지 방향** (D4 acceptance에 반영): 축 이주는 "새 축을 만들었다"가 아니라
**"옛 축 소비자가 0이 됐다"**로 완료를 판정해야 한다. 그리고 조인 기반 지표는 `작동한 비율`
원칙에 따라 **조인 성립 건수를 함께 보고**해야 한다 — 0%가 "도달 실패"인지 "조인 실패"인지
응답 자체가 구분할 수 있어야 한다.

---

## §정정 — v1 stale 4곳 (이번 대조에서 실측으로 발견)

| 위치 | v1 기술 | 실측 (2026-08-11) |
|---|---|---|
| v1 §1 모듈3 "관련 단원 연결" | `ConceptStandardLink`(443건, FK CASCADE) + `atom_node.standard_codes`(역방향) → **✅** | 443건은 적재 사실일 뿐 조인 성립이 아니다. `gating.py:149-151`이 구 축을 "재연결 후 0행"으로 판정했고 `coach.py`·`target_progress.py`만 남았다 → **⚠️ D4** |
| v1 §1 모듈3 "코드·설명" | "**✅ 초과** — 895건" | 초과 충족은 **2022 축에 한한다**. 링크 443건 전량 2022(직접 402·재매핑 41), **2015 개정 460건은 링크 0·소비자 0** → §4-⑧ |
| v1 §1 모듈5 "`prerequisite`" | "**✅ 초과** — 2,210건 + 재귀 CTE + Kahn 위상정렬" | 내부 밀도는 유효. **경계 밀도가 미판정**이었다 — 학교급 경계 통과 20/2,210(0.9%), 고→대 0 → **⚠️ D6** |
| v1 §3 D3 / 부록 "성취수준 0건" | `CUR-03`으로 해소 예정 | `CUR-03` done인데 **main 기준 여전히 0건** — artifact가 main 조상 아님·코퍼스 부재 → **⚠️ D5** |

**병렬 세션 claim 겹침 확인**: 위 4곳은 전부 이 문서(`curriculum_module_gap_review_r2.md`) 안에
정정을 보유하며 v1 파일을 수정하지 않는다. 신설 3태스크의 `--path`(`api/**`·`l2/**`·`harness/**`·
`data/corpus/**`)는 2026-08-11 현재 다른 세션이 claim한 태스크
(`HARN-20`·`MISC-04`·`PATH-04`·`QUAL-02`·`QUAL-04`·`S3-34`)의 범위와 겹치지 않는다.
단 `CUR-05`가 회수 대상으로 지목한 커밋이 `claude/subject-problems-theory-check-7n9n72`(S3-34
claim 중)에 있으므로, **회수 착수 시점에 claim 상태를 재확인**하도록 acceptance ①에 넣었다.

---

## §범위 밖 부기 — 조용히 버리지 않는 관측 1건

이번 대조 중 `/v1/gating/*` 6개 라우트(`school-progress`·`retake`·`suneung`·`thinking`·
`metacognition`·`gifted`)의 핸들러 시그니처에 인증 의존성이 없음을 관측했다. 문항 메타를
반환하는 표면이므로 확인 가치가 있으나, **교육과정 축이 아니라 SEC 축**이다.
`account_security_gap_review.md` 소관으로 넘기고 이 문서에서는 태스크를 만들지 않는다
(중복 등재 금지). 여기 적는 이유는 관측을 침묵으로 버리지 않기 위해서다.

---

## §측정 한계 — 이 문서가 확인하지 못한 것 (정직 회계)

이 대조는 **코퍼스 파일 직접 파싱 + 소스 코드 독해**로 수행했다. 실행 환경에 백엔드 의존성
(`pydantic` 등)이 없어 **harness 리포트 실행·pytest·DB 조회를 하지 못했다.** 따라서:

- D4의 "구 축 조인이 실제 DB에서 0행"은 ⑴ `gating.py:149-151`의 **저장소 자체 판정 기록**과
  ⑵ 두 소비처가 같은 키 공간을 쓴다는 **코드 독해**에 근거한 **주장**이다. DB 대조 실측은
  `CUR-04` acceptance ①(주장 확인 또는 **반증** — 반증되면 범위 재조정)이 수행한다.
- D6의 엣지 집계와 §4-⑧의 링크 집계는 **코퍼스 JSON 직접 파싱 실측**이므로 이 한계에 해당하지
  않는다(부록 재현 명령 참조).
- D5는 `git` 명령 exit code 실측이므로 해당하지 않는다.

전체 스위트를 돌리지 못했으므로 **"회귀 없음"을 주장하지 않는다** — 이 PR은 문서·백로그만
변경하며 코드 변경이 0이다.

### 부기 — 이 PR 자체가 침묵 실패를 한 번 재현했다 (2026-08-11 관측)

이 문서를 담은 PR #772에서 **CI가 발화하지 않았다.** auto-merge(SQUASH)를 걸어둔 채 22분 뒤
확인하니 통합 상태가 `state: "pending"` · `total_count: 0`이었고, `ci.yml`을 브랜치로 필터링한
실행 이력도 `total_count: 0`이었다. 같은 시간창(08-10T14:38~08-11T01:36)에 **다른 11개
브랜치는 정상 실행**됐고 `ci.yml`의 트리거(`pull_request: branches: [main]`)에는 paths 필터가
없으므로, 워크플로 정의가 아니라 **GitHub이 이 PR의 이벤트에 run을 만들지 않은** 단발 누락이다.

이 상태의 성질이 이 문서의 주제와 정확히 같다 — **실패가 아니라 "영원한 대기"라서 아무 알림이
없다.** 웹훅은 CI 성공을 안 보내주고, 실패도 아니니 경고도 없으며, "auto-merge를 걸었다"는
사실은 머지의 증거가 아니다(§6 10회차가 지적한 *간접 신호를 완료 근거로 삼는* 패턴의 실사례).
재트리거(이 커밋)로 해소하며, 조치의 판정은 푸시 성공이 아니라 **run 객체가 실제로 0→1이
되는지**로 한다.

---

## 부록 — 실측 근거 (2026-08-11 실측 · 재현 명령 동봉)

### A. 성취기준·링크 개정별 분포 (M1·M2·M3)

```bash
python3 - <<'EOF'
import json, collections
s = json.load(open('data/corpus/standards_v1/standards.json'))['standards']
norm = {x['norm_id']: x['curriculum_revision'] for x in s}
L = json.load(open('data/corpus/standards_v1/concept_standard_links.json'))['links']
print("standards:", len(s), collections.Counter(x['curriculum_revision'] for x in s))
print("links:", len(L), collections.Counter((l['link_type'], norm.get(l['norm_id'])) for l in L))
linked = {l['norm_id'] for l in L}
for rev in ("2015 개정", "2022 개정"):
    print(f"unlinked {rev}:", sum(1 for x in s if x['curriculum_revision'] == rev and x['norm_id'] not in linked))
print("parent_codes nonempty:", sum(1 for x in s if x.get('parent_codes')))
EOF
```

원출력:
```
standards: 895 Counter({'2015 개정': 460, '2022 개정': 435})
links: 443 Counter({('직접', '2022 개정'): 402, ('재매핑', '2022 개정'): 41})
unlinked 2015 개정: 460
unlinked 2022 개정: 0
parent_codes nonempty: 0
```

### B. 원자 백본 학교급 경계 엣지 (M4)

```bash
python3 - <<'EOF'
import json, collections
g = json.load(open('data/corpus/atom_graph_v1/graph.json'))
nodes = {c['code']: c for c in g['concepts']}
cross = collections.Counter()
for e in g['edges']:
    cross[(nodes[e['from_code']]['school_level'], nodes[e['to_code']]['school_level'])] += 1
print("nodes", len(g['concepts']), "edges", len(g['edges']))
print("relation:", collections.Counter(e['relation'] for e in g['edges']))
print("relation_subtype:", collections.Counter(e.get('relation_subtype') for e in g['edges']))
print("school_link flag:", collections.Counter(e.get('school_link') for e in g['edges']))
print("pairs:", dict(cross))
print("same:", sum(v for (a,b),v in cross.items() if a==b), "cross:", sum(v for (a,b),v in cross.items() if a!=b))
flag = {i for i,e in enumerate(g['edges']) if e.get('school_link')}
endp = {i for i,e in enumerate(g['edges'])
        if nodes[e['from_code']]['school_level'] != nodes[e['to_code']]['school_level']}
print("flag only:", len(flag-endp), " endpoint only:", len(endp-flag), " both:", len(flag&endp))
EOF
```

원출력:
```
nodes 2683 edges 2210
relation: Counter({'prerequisite': 2210})
relation_subtype: Counter({'소단원내': 1041, '원본': 578, '소단원간': 575, '학년간': 8, '학교급간(추정)': 8})
school_link flag: Counter({False: 2190, True: 20})
pairs: {('초등','초등'):529, ('초등','중학'):9, ('중학','중학'):240, ('중학','고등'):11, ('고등','고등'):940, ('대학','대학'):481}
same: 2190  cross: 20
flag only: 0  endpoint only: 0  both: 20
```

> 엣지 키는 `from_code`/`to_code`다(`from`/`to` 아님 — 이 명령은 실행 확인을 거쳤다).
> `school_link`가 소스 자체의 경계 표시이며 양끝점 유도 집합과 완전 일치한다.

### C. `CUR-03` 미착륙 (M8)

```bash
git merge-base --is-ancestor 98a34695 origin/main ; echo "EXIT=$?"   # → EXIT=1
git branch -a --contains 98a34695
#   remotes/origin/claude/human-bottleneck-tasks-6dszy0
#   remotes/origin/merge/human-bottleneck-6dszy0
ls data/corpus/ | grep -c achievement_criteria ; echo "EXIT=$?"      # → 0 / EXIT=1
```

`backlog/tasks/CUR-03-achievement-level-data-intake.yaml` — `status: done` ·
`artifacts: [98a34695]` · `updated: 2026-08-08` · acceptance ④가 후속 태스크 분리 등재를 약속.
백로그 239건 전수에 해당 후속 없음. `docs/standards/unmerged_done_triage_2026-08-08.md`에
`CUR-03` 미등재.

### D. 조인 축 이원화 (M5·M6)

- `src/backend/whymath_backend/api/gating.py:149-151` — 구 4단계 조인 "재연결 후 0행" 판정 기록,
  원자 축(`AtomNode.standard_codes`) 전환. 조인 구현 `:176-180`.
- `src/backend/whymath_backend/api/coach.py:917-923` — `ConceptStandardLink.concept_code == Concept.code`
  → `AchievementStandard.official_code`(조인 `:919-920`). 폴백 명시 `:906-907`, **같은 줄이
  "L6 게이팅의 동일 조인 관례와 정합"이라 적는데 그 L6 게이팅이 이 조인을 버린 쪽이다**(stale 주석).
  호출처 `:1851`(코칭 결정)·`:2177`(대화 턴).
- `src/backend/whymath_backend/l2/target_progress.py:34-35` — 스코프 상수
  `"2022 개정"` × `"고등학교"`. 분자 조인 `:102-107`. 0 방어 `:118-120`. 응답 필드 `:53`·`:127`.
- `src/backend/whymath_backend/harness/standard_attainment_report.py:10` — 원자 축 조인 경로
  `Concept.code → AtomNode.code → AtomNode.standard_codes` (ASM-05 산출).

### E. 학습목표 커버리지 불변 (M7)

`data/corpus/units_v1/_provenance.json` — `{"units": 1, "objectives": 4}`,
`"E2E 확인용 단일 소단원"`. v1 시점과 동일. 디렉터리 내용도 동일
(`quadratic_maxmin.unit.yaml` + `_provenance.json` 2파일).

### F. `CUR-01`·`CUR-02` 착지 확인 (M9)

```
src/backend/whymath_backend/harness/curriculum_revision_crosswalk_report.py
src/backend/whymath_backend/harness/objective_coverage.py
tests/backend/harness/test_curriculum_revision_crosswalk_report.py
tests/backend/harness/test_objective_coverage.py
```

### G. v1 스코프 누락 증명 (§0-②)

```bash
for w in "Ontology" "온톨로지" "용어 사전" "변경 이력" "메타데이터 관리" \
         "AI 교수전략" "AI 문제 생성" "AI 평가 생성" "AI 학습경로 추천"; do
  grep -c "$w" docs/architecture/curriculum_module_gap_review.md
done
# → 0 0 0 0 0 0 0 0 0
```

---

## §후속 — 2026-08-23 EOS 『2_단원 구조 관리』 추가 검토 수용

> **사건**: Kiki가 EOS(Education Operating System) 지향 교육앱을 위한 『2_단원 구조 관리』 설계안(116항)을 제출하고 검토를 요청. v1·r2가 이미 5모듈(교육과정DB·단원구조·성취기준·학습목표·선수학습그래프)을 대조했으나, 이번 문서는 *단원 구조*에 대한 심화·확장 설계안이므로 별도 수용 결정을 남긴다.
>
> **결론**: WhyMath 정본과 충돌하지 않는 범위 내에서 3가지 후속 가설만 채택하고, 제안서의 Curriculum 중심 1급 UnitNode 구조는 도입하지 않는다. 태스크 `CUR-09-eos-unit-structure-review-adoption` 등재.

### ① 정렬점(수용)

| 제안서 원칙 | WhyMath 정본 | 정렬 판단 |
|---|---|---|
| Unit Tree와 Knowledge Graph 분리 | `atom_node.parent_code`로 계층, `EdgeType.PREREQUISITE`로 선수 관계 분리 | ✅ 동일 |
| Unit ≠ Concept | `Concept`에서 교육과정/학년/과목 제거, `CurriculumEntry`로 Overlay | ✅ 동일 |
| Sequence ≠ Prerequisite | **현재 미구현** — `db/models/`에 sequence 컬럼 0개 | ⚠️ 후속 가설 |
| coverage_weight(성취기준-단원 N:M 비율) | `CurriculumEntry`·`ConceptStandardLink`에 비율 컬럼 없음 | ⚠️ 후속 가설 |
| PostgreSQL = authoritative source | pgvector 사용, Neo4j runtime 미도입 | ✅ 동일 |
| Published Unit 삭제 금지/deprecation | `UnitSpec.status`에 `SUPERSEDED` 포함 | ✅ 동일 |

### ② 의도적 미채택/범위 밖

1. **Curriculum → Subject → Course → UnitNode 1급 트리** — WhyMath는 `Concept`가 영속 원본이고 Unit은 atom_node 백본의 파생 뷰이므로 UnitNode를 독립 Aggregate로 두지 않는다(`CLAUDE.md` 원칙 ⑤, v1 §0-②).
2. **Graph DB(Neo4j) 도입** — runtime 연결은 확정적으로 미도입. Unit Graph는 PostgreSQL `unit_edge` 테이블로 projection(`AGENTS.md` 기술 스택).
3. **Drag & Drop CMS / 단원 이동·병합·분리** — 콘텐츠 파이프라인이 "YAML=소스, DB=산출물, 단방향 populate"로 통일돼 있고, 수작업 신호가 실측되지 않아 GUI를 도입하지 않는다(r2 §2-⑥·§5-②).
4. **관계 타입 12종 전면 채택** — `RELATED_TO`/`OVERLAPS_WITH` 등은 traversal 금지, `equivalent`는 SymPy가 유일 권위. MVP에서는 `PREREQUISITE` + `PARENT_OF`만 유지(r2 §2-②·§2-④).
5. **다국가 UnitAlignment 즉시 구축** — `CurriculumEntry`가 다국 매트릭스 셀이나 데이터는 Phase 1에서 KR+US+IMO 3축만(`curriculum_entry.schema.yaml`, r2 §2-⑤).

### ③ 수용 후속 3가지

1. **Sequence/Prerequisite 분리** — 공식 커리큘럼 순서를 담는 `sequence_order`/`order_index`와 선수학습 의존성 `PREREQUISITE`를 분리. 현재 `db/models/` 전체에 순서 컬럼이 0개(r2 §4-①).
2. **Unit ↔ Concept 역할 enum 도입 가설** — `CORE`/`SUPPORTING`/`PREREQUISITE`/`EXTENSION`/`ENRICHMENT`/`REVIEW` 역할을 `unit_concept` 매핑에 추가 검토. 현재 `LearningObjective.k_type`은 *목표/문제 생성 유형* 축이므로 개념 역할 축과는 별개.
3. **coverage_weight 도입 가설** — 성취기준이 여러 단원/개념에 걸쳐 있을 때 비율(0.3+0.5+0.2)을 저장. `CurriculumEntry`·`ConceptStandardLink`에 비율 필드 추가 가능성을 관측 리포트로 먼저 정합.

### ④ 실행물

- **태스크 등재**: `backlog/tasks/CUR-09-eos-unit-structure-review-adoption.yaml`
  - track: `infra-debt`
  - stage: `S3`
  - priority: `2`
  - 범위: 현행 실측 고정 + 3가지 가설 관측 리포트 + CI 배선 확인
  - 범위 밖: 스키마/마이그레이션 변경, Graph DB, CMS GUI, 다국가 즉시 확장
- **MEMORY.md 결정 로그**: 2026-08-23 항목 추가(별도 커밋).

### ⑤ cross-ref

- `docs/architecture/curriculum_module_gap_review.md`(v1) §0-② — Concept 원본·Curriculum Overlay 원칙
- `docs/architecture/curriculum_module_gap_review_r2.md` §2 — 의도적 미채택 6건
- `backlog/tasks/CUR-01-curriculum-revision-vocabulary-consistency.yaml` — 교육과정 개정 표기 3어휘 분열
- `backlog/tasks/CUR-02-objective-coverage-observability.yaml` — 학습목표 커버리지 관측
- `backlog/tasks/CUR-04-standard-join-axis-unification.yaml` — 성취기준 조인 축 이원화 해소
- `schemas/v1.1/curriculum_entry.schema.yaml` — 다국 매트릭스 셀 설계
