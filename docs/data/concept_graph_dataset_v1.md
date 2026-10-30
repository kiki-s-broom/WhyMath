# 와이매스 개념그래프 데이터셋 v1 (자체작성) — 데이터 카드

> **요약**: 한국 2022 개정 교육과정 전 범위(초등~고교 선택·고1 기본수학)를 덮는 **자체작성
> 개념그래프** 시드. <!-- fact:concept_graph.concepts -->437<!-- /fact --> 개념 · <!-- fact:concept_graph.edges -->581<!-- /fact --> 선수엣지 · 성취기준↔CCSS 코드 매핑 · <!-- fact:concept_content.k12_flashcards -->113<!-- /fact --> 암기카드 · 13
> 국제트랙(CCSS전용). 본 슬라이스(101)에서는 그중 **오개념 114건을 L4 오개념 카탈로그(22종)와
> 교차검증**하는 데 사용했다(아래 §5). 전체 적재(L1 concept_graph 파이프라인)는 후속 슬라이스 결정 사항.
>
> **2026-06-12 수정본 교체**: 사용자가 원본 입력 오류(절단된 개념명·어미 등)를 바로잡은 수정본
> xlsx로 5개 jsonl + provenance를 *전량 재생성*했다(§1 버전 이력). 개념 401→403·선수엣지
> 540→541·오개념 114→116으로 소폭 증가. §5 교차검증 수치는 *초기 업로드(06-10)* 기준의
> 슬라이스 101 산출물이며 재계산하지 않았다(아래 §5 주석 참조).
>
> **2026-06-16 v2 통합 검토(설계)**: 본 개념그래프(403·541)는 File A *통합 마스터*의 개념그래프
> 부분과 동일하다. File A의 *신규* 레이어(성취기준 895 듀얼·연결 443·`norm_id`)와, **concept_id
> 정본을 `UC.*`→`{트랙}-{영역}-{3자리}`(ELEM-GEO)로 전환**하는 마이그레이션 설계는
> `curriculum_master_v2_integration_review.md` 참조. 본 카드의 `src_id`는 그 마이그레이션에서
> `aliases`/`source_id`로 **보존**된다(추적성).

---

## 1. 출처·프로비넌스

| 항목 | 값 |
|---|---|
| 형태 | 사용자 업로드 xlsx(보완본 v2·10 시트 중 5종 사용) |
| 업로드일 | 2026-06-17 (보완본 v2) |
| 원본 sha256 | `4e5a880bc7ff41a5f67a876da9fb8125f518638c0cbea73b3377447eb79d29cd` |
| 저작 | 와이매스 자체작성(교수학 주석) + 공공 표준 *코드* 참조 |
| 추출 산출물 | `data/corpus/concept_graph_v1/*.jsonl` (5종) + `_provenance.json` |

> 원본 xlsx는 **커밋하지 않는다**(§3 redaction 대상 자유텍스트를 포함하므로). 진실 원천은
> redaction을 적용한 jsonl이다. 재추출이 필요하면 동일 sha256 원본을 사용자에게 재요청한다.

### 버전 이력

| 일자 | sha256 | 개념 | 선수엣지 | 비고 |
|---|---|---|---|---|
| 2026-06-10 | `1274533c…8488d1` | 401 | 540 | 최초 업로드 |
| 2026-06-12 | `062695ce…36f90d` | 403 | 541 | **수정본 전량 교체** — 절단 개념명·어미 복원 등 입력 오류 정정(원본 검수보고 시트 기준). 동일 redaction 정책(§3) 적용·재생성 |
| 2026-06-17 | `684cfc13…eacaf0` | (검토만) | — | **개정본 v1 — 검토 후 통합 보류**. 고1 기본수학1·2 개념 34 *스텁*(개념명+성취기준만, 교수학 본문 공란) 추가 발견 → 품질 우선(CLAUDE.md #3)으로 본문 충전 후 적재 결정. 코퍼스 미반영. |
| 2026-06-17 | `4e5a880b…d29cd` | 437 | 580 | **보완본 v2 — 전량 재생성·적재**. ⑴ **고1 공통 기본수학1·2 개념 34 추가**(`10기수1/2-*`·2022개정·성취기준 참조 무결성 OK·v1 스텁의 오개념·은유·허용표현·설명·정식정의·선수엣지(+39) **전부 충전**·`정의출처`=2022 별책8). ⑵ **기존 403 교수학 본문 보강**: `metaphor` 403건·`misconception` 403건·`accepted_expressions` 287건 전면 확충(전부 길어짐). 구조 필드(`name_ko`·`category`·`difficulty_tier`·`ccss_code`·`definition_provenance`) **변경 0**(드리프트 없음). ⑶ `std_codes` 표기 47(선택과목 하이픈+멀티구분자·코드 실체 동일). ⑷ 검수보고 시트: 고등 선택 `성취기준 문장` 절단·어미복원 정제 다수(코퍼스 미추출 필드). ⑸ 신규 concept_id `HIGH-B{AREA}-NNN`(idmap에 `[기본]` 7영역 독립 네임스페이스 추가 — 기존 403 ID **재번호화 0** 검증). redaction(설명·정식정의·intl 영문) 정책 유지. |
| 2026-06-17 | (코퍼스 후처리) | 437 | 580 | **기본수학 34 AI 검수 승격**(xlsx 무관 — 추출 후 검수 행위). 34개 `정의출처`에 `·AI 검수(수식·오개념 정합)` 마커 추가 → `review_status` reviewed(148=114+34·pending 289). 검수 내용: 수식 정확성·오개념 타당성(거짓 낙인 0)·은유·CLAUDE.md 정합 **34/34 통과**. *출처(별책8) 보존*·인간 수기검수 아닌 **AI 검수** 정직 명시. 403줄 바이트 불변(34줄만 변경). ★xlsx 재추출 시 이 마커는 재적용 필요(후처리라 정본 미반영). |
| 2026-06-17 | (코퍼스 후처리) | 437 | 581 | **선수엣지 1건 추가**(xlsx 무관 — 정본 정합). `평행이동(10기수2-01-06) ← 원의 방정식(10기수2-01-04)`. 근거: 공통수학 정본 `HK24 평행이동 ← {직선, 원}`인데 기본수학은 `← {직선}`만 → 같은 과목(기본수학2)의 원의 방정식 선수 누락 보정(580→581). *검수 중 플래그한 3건(행렬←다항식·직선←거리·평행이동←직선)은 공통수학 정본과 일치해 제거 대상 아님을 확인*. `_provenance.post_extraction`에 기록(source xlsx edges=580). |

---

## 2. 스키마 (시트 → jsonl)

| jsonl | 레코드 | 핵심 필드 |
|---|---|---|
| `concepts.jsonl` | 437 | `src_id`(G01·N1·HK01·J0105·H:…·`10기수1/2-*`), `name_ko`, `category`, `difficulty_tier`(0~24), `standard_codes`[], `ccss_code`, `metaphor`, **`misconception`**, `accepted_expressions`, `definition_provenance`, `flashcard_count`, **`behavior_skills`[]**(Phase 2b-1·concept→skill 참조) |
| `prerequisite_edges.jsonl` | 581 | `from_id`, `from_name`, `relation`(선수), `to_id`, `to_name` |
| `standard_ccss_map.jsonl` | 437 | `src_id`, `name_ko`, `standard_code_kr`, `ccss_code` |
| `flashcards.jsonl` | 113 | `grade`(A·…), `category`, `difficulty_tier`, `src_id`, `name_ko`, `front`, `back`, `mnemonic`, `exposure_condition` |
| `ccss_only_intl.jsonl` | 13 | `node_id`, `ccss_code`, `scope`, `kr_adjacent_area`, `kr_interpretation`, `kr_absence_reason` |

> **ID 체계 주의 (2026-06-16 P2a 갱신)**: 본 데이터의 `src_id`(G01·N1·HK01·J0201·H:12대수01-01
> 등)는 적재 시 정본 `concept_id`로 *재발급*된다. 정본 형식은 **`{TRACK}-{AREA}-{NNN}`**(예
> `ELEM-GEO-001`) — 기존 `UC.<domain>.<topic>.<slug>`에서 P2a에서 *전환*했다(아래 §5b.1). 추적성은
> `source_id`(=`src_id`)·`aliases`(=[옛 UC, `src_id`])로 보존된다.

### 2.1 concept→skill 매핑 `behavior_skills` (Phase 2b-1·2026-07-03)

각 개념이 학습·사용 시 exercise하는 스킬(`skill_graph_v1`의 27 skill_id·6 BehaviorArea)을 1~3개
매핑한 참조 키 배열이다. cognition 계층·본문 아님(`standard_codes` 동형 안전 배열). 빌드타임엔
`concept_node.behavior_skills`(2b-1)에도 투영되나, **런타임 skill mastery 해소(Phase 2b-2)는 런타임
`concept` 테이블의 `Concept.behavior_skills`를 조인 백킹으로 쓴다** — S0-4b 격하가 `concept_node`
(`ConceptNode`)의 런타임 read를 거버넌스로 금지했기 때문이다(문제 태깅 축인 `concept` UUID에 직접
투영·`backend_concept.py` upsert·마이그레이션 `d4e5f0a1b3c4`·concept mastery와 동일 sanctioned 축).

- **품질=`ai_estimated`(v1)**: 와이매스 자체 저작(자동 유도 아님·교수학 판단). **전문 검수 전**이라
  정직하게 v1로 표기하며, 이후 검수로 승격한다. 자동 통계 유도는 금지(교수학 날조·CLAUDE.md).
- **커버리지 404/437**(≥1 스킬)·**33 미매핑(`[]`)**: 27 스킬이 중등 대수 중심이라 초등 산술
  (자연수·덧셈·곱셈·나눗셈)·문화/탐구 등 적합 스킬이 없는 개념은 `[]`가 정직하다(전량 매핑 강요
  아님). 6 BehaviorArea 모두 사용(REPRESENT 최다·VERIFY 최소).
- **dangling 0**: 모든 참조가 정본 27 skill_id에 존재(`tests/data_pipeline/test_concept_skill_
  crosswalk.py`가 크로스코퍼스 동결). **재임베딩 0**(behavior_skills는 임베딩 안전 필드 밖).

---

## 3. 라이선스·안전 (CLAUDE.md 우선순위 #2)

자체작성 교수학 주석(오개념·은유·허용표현·암기카드)과 공공 표준 *코드*(NCIC 성취기준 코드·
CCSS 코드)는 **안전**(자체 코퍼스 + 사실정보). 단, 두 자유텍스트 컬럼은 NCIC/교과서 성취기준
*본문(statement)* 을 근접 복제했을 가능성이 있어 — `concept_graph.md` §1.1 "본문은 어느 필드에도
복제하지 않는다" — **추출 산출물에서 redact**했다:

| redact 필드 | 사유 |
|---|---|
| `concepts.description`(설명) | 성취기준 본문 근접 복제 가능성. `definition_provenance`가 "설명기반 자동파생"임을 명시 → 설명이 원천 텍스트 |
| `concepts.formal_definition`(정식정의) | 교과서 정의 근접 복제 가능성(내부·학생비노출 표기) |
| `intl.ccss_statement_en`(영문 원문) | CCSS 공식 statement — 코드만 보존, 자체 `kr_interpretation`은 유지 |

> redaction 마커: 각 레코드 `_redacted_fields`. policy-guard CI(검정교과서 출판사 패턴)는 통과하나,
> 본 redaction은 그 *너머의 정책*(성취기준 본문 비복제)을 선제 적용한 것이다.

`licensing_safety.md`(한국 자원 표)에 "와이매스 개념그래프 데이터셋 v1(자체작성)" 행으로 등록.

---

## 4. 검수 상태 (적재 전 게이트)

`definition_provenance` 분포 — **289/437이 자동생성·검수필요**(reviewed 148):

| 출처 | 개수 | 검수 상태 | 적재 가능성 |
|---|---|---|---|
| 수기 검수 | 114 | reviewed | 검수 완료 — 우선 적재 후보 |
| 2022 개정 교육과정 별책8(기본수학)·**AI 검수**(수식·오개념 정합) | 34 | reviewed | AI 검수 완료(수식·오개념·은유·CLAUDE.md 정합) — 우선 적재 후보 |
| 자동(설명기반)·검수필요 | 197 | pending | 전문가 검수 후 |
| 자동 초안·검수필요 | 90 | pending | 전문가 검수 후 |
| 신규 작성(2022 신설)·검수필요 | 2 | pending | 전문가 검수 후 |

> **검수 마커 규약(2026-06-17)**: `definition_provenance`에 `·AI 검수` 마커가 포함되면
> `review_status=reviewed`로 도출한다(`transform.py` `_review_status`). 출처 문자열(별책8 등)을
> *덮지 않고 보존*하면서 검수 완료를 표기하는 방식이다. 기본수학 34는 *인간 수기검수가 아닌*
> **AI(수식·오개념 정합) 검수**임을 라벨에 정직히 명시했다(추후 인간 사인오프 시 별도 표기 가능).
> 콘텐츠 충실화(v2 보강)와 검수 완료는 별개이며, 위 등급은 검수 행위에 근거한다.

---

## 5. 교차검증 — 오개념 114 ↔ L4 카탈로그 22 (본 슬라이스 산출)

> **주석(2026-06-12)**: 이 절의 수치(오개념 114·대응 12종)는 *초기 업로드(2026-06-10)* 기준
> 슬라이스 101 산출물이다. 수정본 교체(§1 버전 이력)로 오개념은 116건으로 늘었으나, §5.2 대응은
> *성취기준 코드* 기준이라 코드가 보존된 한 결론은 유효하다. 전면 재계산은 카탈로그가 30종으로
> 확장된 시점에 별도 슬라이스로 수행한다.

### 5.1 결론
- 데이터셋 오개념은 **각 성취기준 코드에 정착**(curriculum-anchored)되어 있어, 카탈로그
  항목의 *교육과정 근거*를 독립적으로 입증한다.
- 카탈로그 22종 중 **12종이 데이터셋 오개념과 (거의) 정확히 대응** → 카탈로그 정당성 확인.
- 데이터셋에는 카탈로그 미수록의 **고가치 수능·공통 오개념 다수**가 있어 후속 확장 후보가 풍부.

### 5.2 대응(corroboration) — 카탈로그 항목 ↔ 데이터셋 오개념

| 카탈로그 id | 데이터셋(성취기준) 오개념 | 일치 |
|---|---|---|
| `distribution-over-power` | [H:12대수01-03] (a+b)ⁿ≠aⁿ+bⁿ | ◎ |
| `sign-flip-in-inequality` | [J0211] 음수 곱할 때 부등호 방향 그대로 | ◎ |
| `square-root-positivity` | [J0107]·[H:12대수01-01] √(a²)=a (실제 \|a\|) | ◎ |
| `log-distribution` | [H:12대수01-04] log(a+b)=log a+log b | ◎ |
| `gambler-fallacy` | [H:12확통02-01] 앞면 5번→다음 뒷면 차례 | ◎ |
| `prosecutor-fallacy` | [H:12확통02-04] P(A\|B)=P(B\|A) | ◎ |
| `limit-equals-function-value` | [H:12미적Ⅰ01-01] 극한값=함숫값 단정 | ◎ |
| `term-to-zero-implies-convergence` | [H:12미적Ⅱ01-04] 일반항→0 ⇒ 급수 수렴(조화급수) | ◎ |
| `sine-distributes-over-sum` | [H:12미적Ⅱ02-02] sin(a+b)=sin a+sin b | ◎ |
| `dot-product-is-vector` | [H:12기하03-03] 내적 결과를 벡터로(실제 스칼라) | ◎ |
| `period-of-scaled-sine` | [H:12대수02-02] 주기·진폭 혼동 | ○(부분) |
| `similarity-vs-congruence` | [J0312]·[J0304] 닮음비·합동 | ○(부분) |

(◎ 정확 대응 / ○ 부분 대응 — 미대응: division-by-zero·exponent-zero·fraction-cancellation·
area-perimeter-confusion·mean-vs-median·invertibility·chain-rule·product-rule·
geometric-series는 데이터셋 114에 직접 진술이 없음 — 추가 검증·향후 출처 보강 대상.)

### 5.3 신호(signal) 정밀도 평가 → 진단 매칭 정교화 근거
데이터셋의 학생 표기 변이를 보면 카탈로그 `signals`(substring AND)의 두 약점이 드러난다:

1. **거짓음성(공백/표기 변이)**: 학생은 `a²+b²`·`a² + b²`·`a^2+b^2`를 섞어 쓴다. v1 substring은
   공백·유니코드에 민감 → 본 슬라이스에서 `_match_one`에 **NFKC+공백 정규화** 도입(해소).
2. **거짓양성(짧은 공통 토큰)**: `"0"`·`"다음"`·`"모든"` 등은 정답 풀이에도 흔히 등장.
   특히 substring은 *오류의 부재*를 탐지할 수 없어(예: division-by-zero는 "분모≠0" 확인한
   *정답* 풀이도 매칭) 구조적 한계가 있다. → 정본 해법은 **임베딩/LLM-judged 매칭**(doc §매칭
   알고리즘 4단계). 본 슬라이스는 *명백한* 한 건만 정밀화(`invertibility` `"모든"→"모든 함수"`)하고
   나머지 재설계는 pedagogy-designer 검토로 이관(추측 수정 금지).

### 5.4 카탈로그 확장 후보 (미수록·수능/공통 고가치) — 후속 슬라이스
[HK07] 판별식 D<0⇒"해 없음"(허근 무시) · [HK08] 근과 계수 부호 · [HK11] 정의역 제한 최대·최소 ·
[HK14] 연립부등식 교집합↔합집합 · [HK22] 원의 방정식 반지름² · [HK24] 평행이동 부호 ·
[HK35] 합성함수 f∘g=g∘f · [HK41] 순열↔조합 · [HK39] 합·곱의 법칙 · [J0220] ax²=bx 양변 나눠 근 손실 ·
[J0106] 0.999…<1 · [J0315] 피타고라스 비직각 적용 · [H:12미적Ⅰ02-02] 연속⇒미분가능 ·
[H:12미적Ⅰ03-01] 적분상수 +C 누락 · [H:12미적Ⅰ02-07] f′=0⇒극값(변곡점) ·
[H:12확통02-05] 배반↔독립 혼동 · [H:12확통03-07] 신뢰구간 95% 해석 오류.

> 각 항목은 성취기준 코드·반례 구조가 명확해 doc-first(정본 상세화→인코딩) 확장에 적합.

---

## 5b. 정형화·검증 상태 (L1 적재 아크 슬라이스 1 — 2026-06-12)

> **무저장소 슬라이스**: 데이터셋 → 정본 `Concept`/`ConceptEdge` 정형화 + 그래프 검증까지.
> Neo4j/pgvector 적재·드라이버·임베딩은 **이번 범위 밖**(후속 슬라이스 2~3). 모듈:
> `data_pipeline/concept_graph/{idmap,transform,validate}.py`, CLI `transform-v1`.

### 5b.1 src_id → concept_id 매핑 (`idmap.py`) — **2026-06-16 P2a 재ID**

- 데이터셋 `src_id`(N1·HK01·H:12대수01-01 …)는 정본 `concept_id` **`{TRACK}-{AREA}-{NNN}`**으로
  *재발급*된다(기존 `UC.*`에서 전환·§2 주의·`MEMORY.md` P2a). 매핑 규칙:
  - **TRACK**: 첫 `standard_code` 학년대수(2/4/6=ELEM·9=MID·10/12=HIGH·코드 없으면 `difficulty_tier`
    밴드 0~8/9~16/17~24 → ELEM/MID/HIGH·그것도 없으면 MID). RT/OLY는 예약(코퍼스엔 없음).
  - **AREA**: `category`(레벨 접두사 `[고]`/`[중]`/`[공통]` 제거 후 토픽)를 ascii 니모닉으로 매핑
    (`_TOPIC_AREA_MAP`·37 category 전수·예 `미적분`→`CALC`·`기하`→`GEO`·`분수`→`FRAC`). 미수록 category는
    **침묵 폴백 없이 KeyError**(taxonomy 누수 즉시 발견). 레벨만 다른 어간(`[중]기하`·`[고]기하`)은 AREA
    공유·TRACK 구분.
  - **NNN**: (TRACK, AREA) 그룹 안 `(int(difficulty_tier), src_id)` 정렬 3자리 순번(멱등).
- **충돌 0**: 같은 성취기준을 공유하는 개념(`F7`·`F8`·`F9` → `[6수01-06]`)도 NNN이 분리해 유일.
  실측 **403 src_id → 403 유일 concept_id(충돌 0)**·전부 `CONCEPT_ID_PATTERN` 통과. 최대 그룹
  `HIGH-CALC`=43개(3자리 순번 여유 충분).
- **추적성(P2 핵심)**: 각 개념은 `source_id = src_id`(원천)·`aliases = [옛 UC, src_id]`를 보존한다.
  옛 UC는 *이전 알고리즘*(`UC.<과목약칭>.a<영역>.<src-slug>`)을 `idmap._build_legacy_uc`가 재현해 만든다 —
  옛 키·원천 키로도 join·롤백 가능. `build_id_map`은 `{src_id: 새 ID}`, `build_alias_map`은
  `{src_id: [옛 UC, src_id]}` 반환. 매핑 테이블은 `id_map.csv`(`src_id`,`concept_id`)로 검토·인계.
- 전문가 재명명은 `overrides`(src_id→새 ID) 주입으로 가능(결정론이되 교체 가능·override도 규약·유일성 검증).
- 검증: `validate_idmap`이 `area_map_total`(미매핑 0)·`id_unique`·`alias_roundtrip`(src_id→새 ID 가역·옛 UC
  보존)를 *재ID 직전* 단언한다(P2 안전망).

### 5b.2 정형화 (`transform.py`)

| 데이터셋 | → 모델 | 비고 |
|---|---|---|
| `concepts.jsonl`(403) | `Concept`(403) | `category`→`domain`·첫 코드 학년→`grade_band_hint`·풍부필드 직결 |
| `prerequisite_edges.jsonl`(541) | `ConceptEdge`(541) | relation `선수(prereq)`→`PREREQUISITE`·끝점 `src_id`→새 ID 변환 |
| `standard_ccss_map.jsonl`(403) | — | `concept.ccss_code`로 흡수(ccss 완전 일치 검증) |
| `flashcards.jsonl`(113) | raw 패스스루 | L6 — 억지 매핑 안 함(후속) |
| `ccss_only_intl.jsonl`(13) | raw 패스스루 | 국제트랙 — 후속 |

- **풍부 필드 모델 확장**(2026-06-12 결정): `metaphor`·`accepted_expressions`·`ccss_code`·
  `misconception_text`(자유텍스트 — 카탈로그 코드 `misconception_codes`와 *별개*·코드화 후속)·
  `difficulty_tier`(0~24)·`review_status`. `name_en/ja`는 Phase 1 KR이라 Optional(None 허용·빈 문자열 금지).
- **엣지 evidence 합성**: 데이터셋 엣지엔 evidence/strength가 없는데 모델은 `evidence` 비공백·
  `strength` 필수 → `evidence="전문가 작성 개념그래프 v1"`·`evidence_source=expert_review`·`strength=0.8` 합성.
- **prerequisite 캐시**: 엣지(src=선수→dst=후행)로 각 후행 개념의 `prerequisite_concept_ids` 역채움(§2.1 조회 캐시).
- **검수 게이팅 표식**(§4): `definition_provenance`='수기 검수' → `review_status=reviewed`(114건),
  그 외 자동·검수필요 → `pending`(289건). 적재 보류 게이팅 자체는 후속 적재 슬라이스 몫.

### 5b.3 redaction 불변 (우선순위 #2)

- `description`·`formal_definition`은 **`Concept` 모델에 슬롯이 없어 구조적으로 차단**(extra='forbid') —
  정형화 코드가 *읽지도 않는다*. 전체 개념 dump·`graph.json`에 두 키 0건(테스트 단언).
- 패스스루(flashcards·intl)는 각 레코드 `_redacted_fields` 마커를 읽어 동적 제외 → intl
  `ccss_statement_en` 누수 차단(테스트가 잡은 갭 보강).

### 5b.4 검증 리포트 (`validate.py` — §5 10 invariant, 실데이터)

`transform-v1`이 정형화 직후 그래프 검증을 돌린다. **실데이터(2026-06-12 당시 403노드·541엣지) 결과: PASS** —

| 항목 | 결과 |
|---|---|
| error(fail) | **0** (prerequisite 사이클 없음) |
| warning | **0** (dangling 끝점·고립 노드·역방향 쌍·prerequisite 캐시 dangling·학년 단조성 역전 모두 0) |
| 구조 invariant(concept_id 규약·relation enum·strength 범위·evidence 비공백) | 정형화 시점(Pydantic) 강제 |
| 재ID invariant(id_conformance·id_unique·alias_roundtrip·area_map_total) | **error 0**(P2a — `validate_graph`·`validate_idmap`) |
| Neo4j 멱등성(§5 #9) | N/A — 슬라이스 2(적재) |

> Phase 1은 warning을 *통과 처리*한다(§3 — 그래프 구축을 다른 자산 일정에 막지 않음). 데이터셋이
> 매우 정제돼 실데이터엔 warning도 0이나, 각 invariant는 인위적 fail 픽스처로 *위반 탐지*를 단위 검증.

### 5b.5 산출물·게이트

- CLI: `python -m data_pipeline.concept_graph transform-v1 --corpus-dir data/corpus/concept_graph_v1 [--output-dir DIR]`.
  `--output-dir` 주면 `graph.json`(개념·엣지 + raw 패스스루·redaction 유지)·`id_map.csv`(src_id→새 ID) 저장.
- 4게이트 통과: `ruff check .`·`black --check .`·`mypy --strict data_pipeline`·`pytest --cov`(전체 89.38%·
  271 passed/1 skip). 테스트 `tests/data_pipeline/concept_graph/{test_idmap,test_transform,test_validate,test_models,test_main_cli}.py`.

---

## 5c. Neo4j 멱등 적재 상태 (L1 적재 아크 슬라이스 2 — 2026-06-12)

> **저장소 슬라이스**: 슬1 산출 `graph.json` → 실 **Neo4j 그래프 저장소에 멱등 MERGE 적재**.
> pgvector 좌석·임베딩은 **이번 범위 밖**(슬3). 모듈: `data_pipeline/concept_graph/load.py`,
> CLI `load`, 통합 `test_load_neo4j_integration.py`.

### 5c.1 적재 모델 (`load.py`)

- **순서**(멱등·`concept_graph.md` §4 단계7): ① 제약·인덱스 DDL(§2.3) ② 노드 전량 MERGE(403·pending
  포함) ③ 엣지 MERGE(541·양끝 MATCH 후). 모두 `MERGE`라 재실행해도 노드·엣지 수 불변(§5 #9).
- **노드**: `MERGE (c:Concept {concept_id}) SET c += $props` — `concept_id`는 MERGE 키(props 제외·중복
  SET 방지)·`review_status` 등 전 속성 SET. `use_enum_values=True`라 enum은 이미 문자열. None 속성은
  제거(Neo4j null 속성 미생성).
- **엣지**: `MATCH (src)…MATCH (dst)…MERGE (src)-[r:PREREQUISITE]->(dst) SET r += $props` —
  `strength`·`evidence`·`evidence_source` 적재. **reltype 주입 차단**: Cypher 관계타입은 파라미터화
  불가 → 닫힌 `Relation` enum(7종) allowlist에서만 대문자 reltype 포맷. 데이터셋은 전 엣지 `prerequisite`
  → 전부 `PREREQUISITE` 관계.
- **검수게이팅 = 403 전량 적재 + 플래그**: pending 289도 *적재*하되 `review_status='pending'` 속성으로
  표식한다(끝점이 pending인 엣지의 고아 방지). 적재 자체는 게이팅하지 않고 **조회/후속에서** 거른다.
- **드라이버 주입 seam**: `load_graph(result, driver=…)` — 단위테스트가 FAKE 드라이버를 주입해 *실 Neo4j
  없이* 발행 Cypher를 검증한다(미설치 환경에서도 import·테스트 가능). `[postgres]`처럼 `neo4j` import는
  `connect_driver` 안에서만(지연).

### 5c.2 접속·시크릿 (우선순위 #2)

- 접속 자격은 **env 전용**: `NEO4J_URI`·`NEO4J_USER`·`NEO4J_PASSWORD`. 소스는 *env 키 이름만* 참조하고
  **시크릿 리터럴은 0**(CLAUDE.md 보안). `connect_driver`가 env 누락 시 ValueError로 안내.
- `[neo4j]` optional extra(`neo4j>=5,<6`) — 메인 deps 미오염. CLI `load`는 `find_spec("neo4j")` 사전체크로
  미설치 시 `pip install -e '.[neo4j]'` 안내.

### 5c.3 redaction 불변

- `graph.json`은 슬1 정형화에서 이미 청결(description·formal_definition 슬롯 부재)이고, 로더는 *모델 dump
  키만* 적재하므로 본문이 **구조적으로 재유입 불가**. 단위테스트가 노드 props에 두 키 0건 단언.

### 5c.4 산출물·게이트

- CLI: `python -m data_pipeline.concept_graph load --graph data/concept_graph/graph.json [--database DB]`
  (접속은 NEO4J_* env). 적재 멱등(MERGE) — 재실행 안전.
- 4게이트 통과: `ruff`·`black --check`(17파일)·`mypy --strict`(17 src)·`pytest --cov`(전체 87.96%·
  **292 passed/2 skip**). 신규 테스트 `test_load.py`(20·FAKE 드라이버)·`test_load_neo4j_integration.py`.
- **통합테스트(실 Neo4j)는 기본 SKIP** — `@pytest.mark.integration`+`WHYMATH_RUN_INTEGRATION` 게이트 +
  `importorskip("neo4j")`. **CI `data-pipeline-neo4j` 잡**(`neo4j:5` 서비스 컨테이너)·**Phaiakes9**에서
  실행: 2회 적재 → 노드 403·엣지 541 불변(§5 #9)·제약 `concept_id_unique` 존재 단언.

---

## 5d. 개념 pgvector 임베딩 적재 상태 (L1 적재 아크 슬라이스 3 — 2026-06-12)

> **저장소 슬라이스(backend)**: 슬2가 개념을 Neo4j 그래프에 적재한 뒤, 개념의 *의미 임베딩*을
> **pgvector(`concept_embedding` 테이블)에 멱등 upsert**한다. 슬1·2(`data-pipeline` 패키지)와 달리
> **backend 패키지**(`src/backend`·`whymath_backend`) 소관이다(L5 서버가 다중 저장소 운영). 슬2
> Neo4j와 *동일 UC 키*라 그래프↔벡터가 한 키로 join된다(이중 store 단일 키). 슬98 결정(벡터
> DB=pgvector·Postgres 16 통합)을 개념 자산으로 확장한 두 번째 결선(첫 결선은 L4
> `misconception_embedding`·슬105 — 이 슬라이스가 그 ORM·마이그레이션·적재기를 *개념용으로 미러링*).
> 모듈: `whymath_backend/db/models/concept_embedding.py`, alembic
> `…_concept_embedding_pgvector.py`, `whymath_backend/l1/concept_graph/{embedding,populate}.py`.

### 5d.1 ORM·마이그레이션 (`concept_embedding`)

- **PK=`concept_id`(TEXT·UC)**: 슬1 idmap 발급 Universal Concept ID = 슬2 Neo4j 노드 키와 *동일
  키 공간* → 이중 store 단일 키 join. upsert가 PK 충돌로 멱등(`ON CONFLICT(concept_id) DO UPDATE`).
- **컬럼**: `embedding pgvector vector(1024)`(`config.embedding_dim` 기본·bge-m3)·`provider`·`model`·
  `dim`·`text_hash`·`updated_at`. **원문(source_text) 컬럼 부재** — 임베딩 원문은 저장하지 않고
  *표현 해시*(`text_hash`)만 둔다(redaction 방어·중복 제거·원문은 Neo4j 노드 속성에 이미 존재).
- **마이그레이션 체인**: `down_revision=d7e8f9a0b1c2`(슬105 misconception_embedding head 위). upgrade는
  `CREATE EXTENSION IF NOT EXISTS vector`(슬105가 이미 생성·재사용·자기완결 안전) + `concept_embedding`
  테이블. **downgrade는 `vector` 확장을 드롭하지 않는다** — 슬105 `misconception_embedding`이 여전히
  `vector` 컬럼을 소유하므로(확장 소유권은 *도입* 마이그레이션[슬105]에 있음). 오프라인 SQL 검증:
  `upgrade --sql`=CREATE EXTENSION+CREATE TABLE·`downgrade --sql`=DROP TABLE만·`heads`=단일 head.
- **HNSW/IVFFlat 인덱스 없음**: misconception_embedding과 동일 — 401+ 규모는 seq-scan 정합(스케일
  코퍼스는 fixed-dim + HNSW cosine 인덱스가 정석·후속·이 테이블은 *영속화 + 의미검색 groundwork*).

### 5d.2 임베딩 텍스트 — 안전 필드만 (redaction·우선순위 #2)

- **임베딩 입력 = `name_ko` + `metaphor` + `accepted_expressions`**(자체 작성 안전 필드·`". "` join).
  L4 `catalog_text`의 개념판. `concept_embedding_text(...)`는 **`description`·`formal_definition`을
  인자로 받지도 않는다**(시그니처 부재=구조적 차단). graph.json엔 본디 두 키가 없고(슬1 모델 슬롯
  부재·`_provenance.json` redacted), 있더라도 로더가 *읽지 않는다*(이중 방어). 교과서 본문 0.
- 안전 필드가 전부 빈 개념은 적재에서 제외(빈 벡터 방지).

### 5d.3 적재기·provider 재사용 (신규 seam 0)

- **입력 원천 = 슬1 산출 `graph.json`**(UC 키·정제). `load_concepts_from_graph_json`이 `concepts`
  배열에서 UC `concept_id` + 안전 필드만 읽어 `(concept_id, 표현)` 목록을 만든다(flashcards_raw·
  intl_raw 등 그래프 외 자산은 읽지 않음).
- **임베딩 provider seam 재사용**(신규 금지·CLAUDE.md 로컬 우선): 레이어-중립 `l1/embedding_provider`
  (`build_provider`·`FakeEmbeddingProvider`·local bge-m3·OpenAI — 감사 I4로 L4에서 L1로 이동·기존
  `misconception/semantic/provider` 경로는 re-export shim)·`text_hash`·`_provider_model_identity`를
  그대로 import한다(같은 임베딩 공간 규약·Fake 주입·지연 로드). `ConceptEmbeddingIndex`(sync psycopg
  lazy 엔진·upsert/search)는 `PgVectorIndex`를 개념 테이블용으로 미러링.
- **멱등 upsert**: `populate_concept_embeddings`가 표현을 배치 1회 임베딩해 UC 키로 upsert(재실행 시
  갱신). **403 전량 적재**(review_status 무관 — 임베딩은 의미검색용·게이팅은 *조회* 몫).
- 자격증명 0 하드코딩(OpenAI 키 등 env 전용·SecretStr)·로컬 provider 우선(비용).

### 5d.4 산출물·게이트

- CLI: `WHYMATH_VECTOR_STORE=pgvector python -m whymath_backend.l1.concept_graph.populate
  --graph data/concept_graph/graph.json`(env 접속·pgvector 모드 전용). 적재 멱등 — 재실행 안전.
- 4게이트 통과(`cd src/backend`): `ruff check .`·`black --check .`(149파일)·`mypy --strict
  whymath_backend`(128 src)·`pytest --cov`(전체 **96.19%**·**2408 passed/85 skip**). 신규 테스트
  `test_concept_embedding.py`(24·Fake provider·가짜 엔진)·`test_concept_embedding_integration.py`(5).
- **통합테스트(실 PG+pgvector)는 기본 SKIP** — `@pytest.mark.integration`+`WHYMATH_RUN_INTEGRATION`
  게이트 + PG 미도달 graceful skip. **CI 신규 잡 불요** — 기존 **`backend — 마이그레이션·통합 (실 PG)`
  잡**(`pgvector/pgvector:pg16` 서비스)이 `alembic upgrade head`(→`concept_embedding` 생성)·
  `downgrade base→upgrade head` 왕복 후 `pytest -m integration --ignore=l3`로 이 통합테스트를 자동
  수집·실행한다(upsert→search 라운드트립·멱등·provider/model 필터·dim 일치·UC 키). **Phaiakes9**에서도 실행.

---

## 5e. 개념 의미검색 조회 좌석 + backend search API (L1 적재 아크 슬라이스 4 — 2026-06-12)

> **조회 슬라이스(backend)**: 슬3이 개념 임베딩을 pgvector(`concept_embedding`)에 *적재*한 뒤,
> 슬4는 그 적재 임베딩을 *조회 가능*하게 만든다 — 슬3 `ConceptEmbeddingIndex.search`를 백킹
> 프리미티브로 한 **검색 좌석 + HTTP 엔드포인트**. 슬3 `search` docstring이 예고한 "조회 좌석이
> 생기면 그 타입으로 흡수한다"의 그 좌석이다. 모듈: `whymath_backend/l1/concept_graph/retrieval.py`,
> `whymath_backend/api/concepts.py`(search 엔드포인트 추가).

### 5e.1 검색 좌석 (`search_concepts`·L1 데이터 서빙)

- **흐름**: `search_concepts(query_text, *, top_k, provider, index=None, settings=None)` → ① provider로
  query_text 임베딩(1건) ② `ConceptEmbeddingIndex.search(vector, top_k)`로 코사인 상위 top_k ③
  `ConceptSearchHit(concept_id, similarity)` 랭킹 반환(유사도 내림차순). 임계값 필터 없음(순수 랭킹·
  점수 컷은 소비처 몫).
- **반환 타입 = `concept_id + similarity`만**(name_ko 등 enrichment 미포함). 사유: `concept_embedding.
  concept_id`는 **UC 키**(슬2 Neo4j 노드 키와 동일 공간)인데 backend PG `concept` 테이블은 **UUID PK
  + `code`**라 *UC 컬럼이 없다*(다른 키 공간). UC↔PG/Neo4j 메타 브리지는 *별도 설계 결정*이라 풍부
  메타 enrichment는 **후속 슬라이스**(backend↔Neo4j 결합·무거운 프로젝션 금지).
- **provider seam 재사용**(신규 0): 적재(슬3)와 *같은* `_provider_model_identity`(provider→model 규약)·
  `ConceptEmbeddingIndex`를 쓴다 — 같은 임베딩 공간 행만 봐야 적재 결과가 잡힌다. provider·index 주입
  가능(테스트 격리·Fake).
- **memory 모드 graceful**(조용한 무동작 금지): `vector_store != pgvector`면 영속 store 부재로 적재가
  불가능했으므로 **빈 리스트**를 돌려준다(예외·None 아님·embed도 생략). 호출자가 명시 신호로 표면화.

### 5e.2 HTTP 엔드포인트 (`GET /v1/concepts/search`·L5 API 표면)

- **계약**: `GET /v1/concepts/search?q=<질의>&k=<1~50>` → `{query, results:[{concept_id, similarity}],
  vector_store_enabled}`. q 필수·비공백(min_length=1)·max_length=500·k 범위 → 위반 시 422(기존 list
  엔드포인트 Query 제약 패턴 미러). 라우트는 `/{concept_id}`(UUID)보다 *먼저* 선언해 "search"가 UUID로
  파싱되지 않게 한다.
- **블로킹 격리**: 검색 좌석은 sync(블로킹 임베딩 + sync psycopg)라 `asyncio.to_thread`로 워커
  스레드에서 돌린다(이벤트 루프 보호·coach `_compute_matches` 패턴 미러).
- **노출 계약**(CLAUDE.md): *학생 직접 노출 아닌* 조회 좌석 — L2(약개념 추천)·L4(오개념↔개념 연결)·
  교사 도구가 *소비*(그 소비 로직은 후속). 반환은 UC concept_id + 코사인 점수뿐(본문 0·우열 매기기·
  정답 빠르게 등 금기 표현 0). memory 모드면 `vector_store_enabled=false` + 빈 results로 *명시* 안내.
- provider는 `build_provider`(좌석 팩토리·신규 0) 의존성으로 주입 — 테스트는 `dependency_overrides`로
  Fake 주입(라이브 0·모델 로드 0).

### 5e.3 명시적 범위 밖 (후속 슬라이스)

- **enrichment**(name_ko 외 전체 속성·Neo4j traversal): backend 메타 접근 방식(Neo4j 연결 vs PG UC
  프로젝션)이 *별도 설계 결정*이라 후속(§5e.1 키 공간 차이).
- **검수 게이팅**(reviewed 우선 노출): `review_status`가 backend에서 조회되려면 위 메타 접근 결정
  선행. 적재는 전량+플래그 완료(§5d).
- **L2/L4 결선**(약개념 추천·오개념 자동 연결): 좌석만 제공·L2/L4가 *호출*하는 건 후속(7계층 — L1은
  조회 서빙·역방향 의존 금지).

### 5e.4 산출물·게이트

- 4게이트 통과(`cd src/backend`): `ruff check .`·`black --check .`·`mypy --strict whymath_backend`·
  `pytest --cov`(70%+). 신규 테스트: `test_concept_retrieval.py`(좌석 단위·11·Fake provider+엔진)·
  `test_concepts_search.py`(엔드포인트 단위·9·TestClient+DI override)·`test_concept_retrieval_
  integration.py`(populate→search 라운드트립·실 PG 게이트).
- **통합테스트(실 PG+pgvector)는 기본 SKIP** — `@pytest.mark.integration`+`WHYMATH_RUN_INTEGRATION`
  게이트 + PG 미도달 graceful skip. **CI 신규 잡 불요** — 기존 **`backend — 마이그레이션·통합 (실 PG)`
  잡**이 `pytest -m integration --ignore=l3`로 `tests/backend/l1/`를 자동 수집·실행. **Phaiakes9**에서도 실행.

---

## 5f. 개념 메타 PG 프로젝션 + 검색 enrichment·검수 게이팅 (개념그래프 *소비* 아크 슬라이스 1 — 2026-06-12)

> **소비 슬라이스(backend)**: 적재 아크(슬1~4)가 개념을 Neo4j(슬2)·pgvector(슬3)에 UC 키로 적재했고,
> 슬4 검색은 UC concept_id+similarity만 돌려줬다(name_ko 등 enrichment는 §5e.3에서 "후속"으로 명시 —
> UC↔backend-PG 키 공간 차이가 가로막음). 소비 슬1이 그 다리를 놓는다. **확정 설계 결정(사용자 승인)**:
> 메타 브리지 = **PG 프로젝션**(backend↔Neo4j 런타임 연결 *안 함* — backend는 async-PG 단일 평면 유지).
> graph.json 개념 메타를 **UC 키 PG 테이블(`concept_node`)로 프로젝션**하고, 검색 enrichment·게이팅을
> **PG 조인**으로 한다. 모듈: `whymath_backend/db/models/concept_node.py`, alembic
> `…_concept_node_meta_projection.py`, `whymath_backend/l1/concept_graph/{node_projection,retrieval}.py`,
> `whymath_backend/api/concepts.py`(search 확장).

### 5f.1 메타 프로젝션 ORM·마이그레이션 (`concept_node`)

- **PK=`concept_id`(TEXT·UC)**: 슬2 Neo4j 노드 키·슬3 `concept_embedding.concept_id`와 *동일 키 공간*
  → 한 UC 키가 *삼중 투영*(Neo4j 그래프·pgvector 벡터·PG 메타)을 잇는다. upsert가 PK 충돌로 멱등
  (`ON CONFLICT(concept_id) DO UPDATE`). (backend PG `concept` 테이블[UUID PK+code]과는 여전히 *별개* —
  이 테이블은 UC 공간 전용 프로젝션.)
- **수록 컬럼(전부 안전)**: `name_ko`·`domain`(표시·식별)·`review_status`(게이팅 플래그·plain TEXT —
  PG native enum 미생성·graph.json use_enum_values로 이미 'reviewed'/'pending' 문자열·concept_embedding
  동형)·`standard_codes`(NCIC 코드 TEXT[])·`ccss_code`·`difficulty_tier`·`metaphor`·
  `accepted_expressions`·`updated_at`. **`description`·`formal_definition` 컬럼 부재**(redaction·우선순위
  #2 — 성취기준 본문 근접 필드를 *둘 곳 자체를 두지 않음*. graph.json 부재·로더 미독·테이블 미수록의
  삼중 방어. 슬3 임베딩 ORM이 원문 미저장한 것과 같은 규약).
- **마이그레이션 체인**: `down_revision=e8f9a0b1c2d3`(슬3 concept_embedding head 위·단일 head 유지·신
  head `f9a0b1c2d3e4`). pgvector 확장 무관(벡터 컬럼 0). upgrade=CREATE TABLE·downgrade=DROP TABLE만
  (왕복 안전·CI `downgrade base→upgrade head` 검증). 인덱스 없음(403 규모·PK로 충분·게이팅은 필터).
  오프라인 SQL 검증: `upgrade --sql`=CREATE TABLE(본문 컬럼 0 확인)·`downgrade --sql`=DROP TABLE·
  `heads`=단일 head.

### 5f.2 적재기 (`node_projection`·신규 seam 0)

- **입력 원천 = 슬1 산출 `graph.json`**(슬3과 동일). `load_concept_nodes_from_graph_json`이 `concepts`
  배열에서 **안전 메타 키만** 읽어 `ConceptNodeRecord` 목록을 만든다 — description·formal_definition은
  읽지 않고(graph.json 부재·무시) 레코드 슬롯도 없다. 슬3 임베딩 로더와 달리 *전량 적재*(빈 옵션 필드도
  적재 — enrichment·게이팅 recall). name_ko/domain/review_status 누락(오염 입력)은 NOT NULL 위반 대신
  *건너뜀*(정직·정상 graph.json은 셋 다 필수 보유).
- **sync 엔진 재사용**(신규 seam 0): 슬3 `embedding._build_sync_engine`(sync psycopg·지연 import·
  `db_disable_pool` NullPool 가드)을 그대로 import. `ConceptNodeStore.upsert`는 `INSERT ... ON
  CONFLICT(concept_id) DO UPDATE`(멱등). `populate_concept_nodes`는 provider 불요(순수 메타 upsert).
- **CLI 통합**: 슬3 `populate.py`가 *임베딩+메타 둘 다* 적재한다(같은 graph.json·동일 UC 키·한 진입점).
  `WHYMATH_VECTOR_STORE=pgvector python -m whymath_backend.l1.concept_graph.populate --graph …`. 멱등.

### 5f.3 검색 enrichment + 검수 게이팅 (`retrieval`·`api/concepts`)

- **enrichment(PG 조인)**: `search_concepts`가 pgvector 검색(슬3·UC+similarity)으로 잡은 UC들을
  `fetch_node_meta`(단일 IN 쿼리·N+1 없음·검색 좌석과 *같은 sync 엔진* 공유)로 조회해 `name_ko`·
  `domain`·`review_status`를 `ConceptSearchHit`에 붙인다. `concept_node`에 없는 UC(메타 적재 누락)는
  **None graceful**(검색 계속). 안전 필드만 SELECT(본문 컬럼 자체가 없어 흐를 경로 0).
- **게이팅(`reviewed_only: bool=False`)**: 기본 False=recall 보존(pending 개념도 노출). True면 상위 top_k
  창에서 `review_status=='reviewed'`인 hit만 남긴다(*필터*·유사도 정렬 유지). 메타가 없어 reviewed
  확인 불가인 UC는 gated 모드에서 *보수적 제외*(정직 — 확실치 않으면 노출 안 함). §5e.3이 "후속"으로
  남긴 게이팅이 여기서 *조회* 정책으로 결선(적재는 전량+플래그·슬3에서 완료).
- **HTTP 계약 확장**: `GET /v1/concepts/search?q=…&k=…&reviewed_only=<bool>` → `results[]`에 `name_ko`·
  `domain`·`review_status` 추가(미적재 UC는 null). 검색 좌석은 sync(임베딩+psycopg 검색+메타 조인)라
  `asyncio.to_thread`로 격리(이벤트 루프 보호).
- **노출 계약 유지**(CLAUDE.md): *학생 직접 노출 아닌* 조회 좌석(L2/L4·교사 도구 소비). enrich는 안전
  표시·게이팅 필드뿐 — **본문(description·formal_definition) 0**(`concept_node`에 컬럼 자체 없음)·금기
  표현 0. 키 일관성: concept_id=UC(슬2·3 동일 — 삼중 store 단일 키).

### 5f.4 산출물·게이트

- 4게이트 통과(`cd src/backend`): `ruff check .`·`black --check .`(153파일)·`mypy --strict whymath_backend`
  (131 src·이슈 0)·`pytest --cov`(전체 **96%**·**2454 passed/93 skip**). 신규 테스트:
  `test_concept_node_projection.py`(적재기 단위·22·Fake 엔진·redaction·fetch_node_meta SQL)·
  `test_concept_retrieval.py`(좌석 단위·enrich+게이팅 추가·`fetch_node_meta` 패치)·
  `test_concepts_search.py`(엔드포인트 단위·reviewed_only+enrich 응답)·`test_concept_node_projection_
  integration.py`(적재→enrich→게이팅→메타 누락 graceful·실 PG 게이트·5).
- **통합테스트(실 PG)는 기본 SKIP** — `@pytest.mark.integration`+`WHYMATH_RUN_INTEGRATION` 게이트 + PG
  미도달 graceful skip. **CI 신규 잡 불요** — 기존 **`backend — 마이그레이션·통합 (실 PG)` 잡**이
  `alembic upgrade head`(→`concept_node` 생성)·`downgrade base→upgrade head` 왕복 후 `pytest -m
  integration --ignore=l3`로 `tests/backend/l1/`를 자동 수집·실행. **Phaiakes9**에서도 실행.
- 시크릿 0(자격증명 env 전용·하드코딩 0)·멱등 적재·7계층(L1 데이터 서빙+L5 표면·L2/L4 소비 로직
  미구현 — 좌석만).

---

## 5g. 개념그래프 → backend `concept` 런타임 엔티티 브리지 (개념그래프 *소비* 아크 **브리지** 슬라이스 — 2026-06-12)

> **브리지 슬라이스(backend)**: 적재 아크(슬1~4)·소비 슬1(슬117·§5f)이 개념을 Neo4j(슬2)·pgvector
> `concept_embedding`(슬3)·`concept_node`(슬117) **세 투영에 UC 키**로 적재했으나, *런타임 개념 엔티티*
> backend `concept` 테이블(UUID PK·`code` unique)은 **비어 있고 UC와 미연결**이었다(§5f.1 주석: "backend
> PG `concept` 테이블[UUID PK+code]과는 여전히 *별개*"). 런타임 소비처 — L2 `mastery_tracking`
> (`concept_mastery_history.concept_id`=UUID)·`problem_concept`(concept_id=UUID FK)·L4 coach — 가
> backend `concept` UUID를 참조하므로 개념그래프가 런타임에서 보이지 않았다. **확정 설계 결정 A(사용자
> 승인)**: backend `concept`를 개념그래프로 적재하고 **`code`=UC**로 브리지 → 한 논리키 UC가 *사중 store*
> (Neo4j·pgvector·concept_node·backend concept)를 잇고 런타임 경로가 닫힌다: L2 mastery(UUID concept) →
> `concept.code`(UC) → concept_node/concept_embedding/Neo4j 도달. 모듈:
> `whymath_backend/l1/concept_graph/backend_concept.py`, `populate.py`(③ 투영 통합). **마이그레이션 0**
> (스키마 변경 불요 — 아래 `level` 유도).

### 5g.1 적재기 (`backend_concept`·신규 seam 0)

- **입력 원천 = 슬1 산출 `graph.json`**(슬3·슬117과 동일). `load_backend_concepts_from_graph_json`이
  `concepts` 배열에서 **`concept_id`(UC)→`code`** 브리지 키 + `name_ko` 직결 + 유도 필드를 읽어
  `BackendConceptRecord` 목록을 만든다. name_ko 누락(오염)은 NOT NULL 위반 대신 *건너뜀*. 전량(403)
  적재(review_status 무관·게이팅은 조회 몫·슬2/3/117 동형).
- **sync 엔진 재사용**(신규 seam 0): 슬3 `embedding._build_sync_engine`(슬117과 동일 좌석)을 그대로
  import. `BackendConceptStore.upsert`는 `INSERT ... ON CONFLICT(code) DO UPDATE`(멱등).
- **CLI 통합**: `populate.py`가 *임베딩+메타+런타임엔티티 셋 다* 적재한다(같은 graph.json·동일 UC 키·한
  진입점·`WHYMATH_VECTOR_STORE=pgvector`). ①②는 UC 공간 전용 투영, ③이 UC↔UUID 브리지를 놓는다.

### 5g.2 필드 매핑 (graph.json `Concept` → backend `Concept`)

| graph.json 필드 | backend `Concept` 컬럼 | 처리 | 비고 |
|---|---|---|---|
| `concept_id`(UC) | **`code`** | 직결 | **브리지 키**(UNIQUE·UC↔UUID) |
| `name_ko` | `name_ko` | 직결 | 필수 |
| `difficulty_tier`[0,24] | `intrinsic_difficulty`[1,5] | **유도**(선형 0→1.0·24→5.0·2자리) | Numeric(3,2)·schema ge=1 le=5 정합 |
| `domain`(category) | `subject` | **유도** 매핑 | 고4과목+`[공통]…`→공통(131/403)·그 외 **NULL**(272·억지 매핑 0) |
| `misconception_text` | `common_misconceptions`(JSONB) | **선택** 1원소 | 자유형 `{"misconception":…}`·correction 미작성(검수 책임)·카탈로그 `misconception_codes`와 별개 |
| *(소스 부재)* | `level`(NOT NULL enum) | **유도 `세부개념`** 고정 | graph 403은 전부 세부 개념(평면 목록·단원/소단원 위계 아님)→교수학적으로 정확·날조 0·스키마 변경 회피 |
| *(소스 부재)* | `description`·`formal_definition`·`intuitive_explanation` | **NULL 유지** | **redaction**(검수 책임·아래 §5g.3) |
| *(대응 없음·날조 0)* | `name_en`·`aliases`·`parent_concept_id`·`curriculum_version`·`grade_introduced`·`semester_introduced`·`cognitive_type`·`recommended_visual_styles`·`exam_frequency`·`weight_in_curriculum`·`embedding_id` | NULL/기본 | `is_signature_korean`=기본 False·나머지 검수 대기 |

- **미매핑 처리 사유**: ① **필수 NOT NULL `level`** = 소스에도·합당한 기본값에도 없으나 graph 노드가
  전부 세부 개념이라 `세부개념` 고정 유도가 *교수학적으로 정확*(마이그레이션·'unspecified' enum 추가
  회피). ② **`subject`** = nullable이라 깔끔히 대응하는 고4과목·공통만 매핑하고 초·중 영역·기타 고
  과목(대수·경제 수학 등 enum 부재)은 NULL(억지 매핑·날조 금지). ③ graph의 `grade_band_hint`·
  `standard_codes`·`ccss_code`·`metaphor`·`accepted_expressions`·`review_status`·
  `prerequisite_concept_ids`·`misconception_codes`·`visualization_card_keys`·`notes`는 backend
  `Concept`에 *대응 컬럼이 없다* — `concept_node`(슬117)가 그 메타를 UC 키로 이미 보관하므로, 런타임
  엔티티엔 *결선 최소 식별*(code=UC·name_ko·subject·난이도·오개념)만 적재(이중 보관 회피·후속
  consolidation 후보).

### 5g.3 redaction·멱등 (우선순위 #2)

- **redaction**: `description`·`formal_definition`·`intuitive_explanation`은 *건드리지 않는다*(NULL
  유지)·`BackendConceptRecord`에 슬롯 자체가 없다(구조적 차단)·적재기가 읽지도·채우지도 않는다(삼중
  방어). `metaphor` 같은 안전 자체작성 필드도 `intuitive_explanation`에 *욱여넣지 않는다*(검수 통과
  직관 설명용 컬럼·혼동/검수책임 회피). ON CONFLICT SET에도 본문 3컬럼이 없어 *재적재가 검수 작성한
  본문을 덮어쓰지 않는다*. graph 부재(`_provenance.json` redacted)이므로 교과서 본문 유입 경로 0.
- **멱등·UUID 보존**: `code`(UC) UNIQUE 충돌 upsert — 같은 UC 재적재는 기존 행 갱신하고 **UUID
  PK(concept_id)는 SET하지 않아 보존**(신규 행만 `gen_random_uuid()` server_default 발급). L2 mastery·
  problem_concept이 이미 그 UUID를 FK 참조 중일 수 있어 *재적재가 UUID를 바꾸면 안 된다* — 브리지
  키 안정성의 핵심. `created_at`도 SET 제외(생성시각 보존).

### 5g.4 산출물·게이트

- 4게이트 통과(`cd src/backend`·변경 파일 기준): `ruff check`(green)·`black --check`(green)·`mypy
  --strict whymath_backend`(132 src·이슈 0)·`pytest`(신규 단위 **23 passed**·new 모듈 cov **96%**).
  신규 테스트: `test_concept_backend_load.py`(적재기 단위·23·Fake 엔진·UC→code 브리지·subject 매핑·
  difficulty 스케일·redaction 미유입·ON CONFLICT(code)·PK 미-SET·멱등)·`test_concept_backend_load_
  integration.py`(적재→row·code=UC·redaction NULL·재적재 UUID 보존·**L2 mastery 결선 가능성**·실 PG
  게이트·4).
- **통합테스트(실 PG)는 기본 SKIP** — `@pytest.mark.integration`+`WHYMATH_RUN_INTEGRATION` 게이트 + PG
  미도달 graceful skip. **CI 신규 잡 불요** — 기존 **`backend — 마이그레이션·통합 (실 PG)` 잡**이
  `alembic upgrade head` 후 `tests/backend/l1/`를 자동 수집·실행. **마이그레이션 0**(단일 head
  `f9a0b1c2d3e4` 불변). **Phaiakes9**에서도 실행.
- 시크릿 0(env 전용·하드코딩 0)·멱등 적재·7계층(L1 런타임 엔티티 적재·L2/L4 소비 로직 미구현 —
  브리지만). **다음**: 약개념 추천(L2 약점 UUID→`concept.code`(UC)→그래프 메타).

---

## 5h. 약개념 추천 — L2 약점 + `concept_node` UC 메타 enrich (개념그래프 *소비* 아크 슬라이스 2 — 2026-06-12)

> **소비 슬라이스(backend·L2)**: 소비 슬1(§5f·`concept_node` 메타 프로젝션)·브리지(§5g·backend `concept`
> `code`=UC)가 *사중 store 단일 UC 키*를 닫았다. 그러나 *런타임 소비 경로*는 아직 한 단계 더 닫아야 했다 —
> L2 학습자 모델이 약점(낮은 BKT/IRT)을 식별해도 그 약점을 *그래프 메타와 함께* 돌려주는 좌석이 없었다.
> 이 슬라이스가 그 경로를 닫는다: **L2 약점 → `concept.code`(UC) → `concept_node` 안전 메타 enrich → 추천**.

### 5h.1 약개념 추천 좌석 (`l2/weak_concept_recommendation`·L2 학습자 모델)

- **재사용(신규 진단·정렬 로직 0)**: ① `l2.concept_diagnosis.compute_concept_diagnoses`(BKT 최신 숙달 +
  IRT θ 융합·agreement·*약점 먼저* 정렬·각 항목 `concept_code`=UC[orphan None])를 *그대로 입력*으로 쓴다.
  ② `l1.concept_graph.node_projection.fetch_node_meta`(UC→`concept_node` 안전 메타 단일 IN 조회)를 enrich에
  재사용 — 검색 좌석(§5e·`search_concepts`)이 쓴 *같은* 좌석.
- `WeakConceptRecommendation`(Pydantic): concept_id·concept_code(UC)·concept_name·bkt_mastery·
  irt_mastery_proxy·`weakness`(두 신호 최저·정렬·필터 기준)·agreement + **enrich** name_ko·domain·review_status.
- `recommend_weak_concepts(session, user_id, *, limit=10, mastery_threshold=0.7, reviewed_only=False,
  meta_engine=None)` 흐름: ①진단(약점 정렬 보존)→②**약점 필터**(비교 가능 신호 최저 < 임계·신호 0건 제외)→
  ③**UC dedupe enrich**(`fetch_node_meta` 단일 IN·N+1 0)→④**검수 게이팅**(`reviewed_only=True`면 reviewed만·
  메타 없으면 보수적 제외[§5f.3 규약과 일관])→⑤**상한**(정렬 보존 상위 N).
- **sync 좌석 격리**: `fetch_node_meta`는 sync 엔진(블로킹 psycopg)이고 이 함수는 async — 검색 좌석(api/
  concepts)이 sync 좌석을 `asyncio.to_thread`로 워커 스레드에 격리하는 *바로 그 패턴*을 따른다(신규 동시성 0·
  이벤트 루프 보호·p50<2s).

### 5h.2 HTTP 엔드포인트 (`GET /v1/me/weak-concepts`·L5 API 표면)

- query: `limit`(1~50·기본 10)·`threshold`(0~1·기본 0.7)·`reviewed_only`(기본 false=recall). `ConsentedUser`·
  user_id 스코핑·읽기. 응답 `list[WeakConceptRecommendation]`.
- **노출 계약**: 학생 직접 노출 아닌 *조회 좌석*(소비 슬1과 일관·L2/L4·교사 소비). enrich는 안전 표시·게이팅
  필드뿐 — **본문(description·formal_definition) 0**(`concept_node`에 컬럼 자체 없음·redaction 구조적 차단·
  추천 스키마에 슬롯 부재). 우열 매기기·정답 빠르게 등 금기 표현 0.

### 5h.3 계층·범위

- **7계층**: L2가 L1 `fetch_node_meta`를 *호출*(L_n→L_{n-1} 준수). L4 코칭·L5 노출은 부착하지 않음(역방향
  의존 회피 — 코칭은 L4·HTTP 표면은 api/me). **마이그레이션 0**(기존 테이블 조회만·스키마 변경 불요).
- **명시적 범위 밖(후속)**: 선수엣지(`concept_edge` PREREQUISITE·이미 backend PG 보유) traversal로 "막힌
  선수개념" 추천 · 풍부 메타 노출(standard_codes·difficulty_tier·`fetch_node_meta` 확장) · L4 오개념↔약개념
  결선(이 좌석 호출). **Neo4j 런타임 traversal은 여전히 미도입**(PG 단일 평면 유지).

### 5h.4 산출물·게이트

- 4게이트 통과(`cd src/backend`·py3.12): `ruff`(green)·`black --check`(155파일 green)·`mypy whymath_backend`
  (**133 src·이슈 0**)·`pytest`(**2493 passed/98 skip**·회귀 0)·신규 모듈 cov **100%**(46 stmts·14 branch·
  0 miss).
- 신규 테스트 2: `test_weak_concept_recommendation.py`(16 단위·약점 필터[임계 경계·신호 0건]·정렬 보존·
  limit·enrich[부착·미적재 None·orphan·dedupe 단일 호출]·reviewed_only 게이팅[pending/메타없음 제외·기본
  recall·게이팅 후 limit]·redaction) · `test_me_integration.py`에 `test_me_weak_concepts_enrich_and_gating_
  on_live_pg` 추가(실 PG: 약점→code[UC]→`concept_node` enrich·게이팅·limit·threshold·redaction NULL·401·
  강개념 제외·메타 미적재 graceful).
- **통합테스트(실 PG)는 기본 SKIP**(`@pytest.mark.integration`+`WHYMATH_RUN_INTEGRATION` 게이트 + PG 미도달
  graceful skip). **CI 신규 잡 불요** — 기존 **`backend — 마이그레이션·통합 (실 PG)` 잡**이 `tests/backend/
  api/`·`l2/`를 자동 수집. **마이그레이션 0**(단일 head `f9a0b1c2d3e4` 불변). **Phaiakes9**에서도 실행.
- 시크릿 0·7계층(L2 소비 좌석·L1 호출만). **다음**: 선수엣지 traversal·L4 오개념↔약개념 결선·풍부 메타 노출.

---

## 5i. 선수엣지 적재 + 막힌 선수개념 추천 (개념그래프 *소비* 선수 슬라이스 — 2026-06-12)

> **선수 슬라이스(backend·L1 적재 + L2 추천)**: 약개념 추천(§5h)이 "지금 무엇을 복습할지" 약개념을 골랐다면,
> 이 슬라이스는 그 약개념의 **선수개념(prerequisite) 중 학습자가 약한 것**을 "*먼저* 복습할 막힌 선수"로
> 돌려준다(후행 결손의 *근본 원인*이 선수 결손일 수 있음·LTHC). 두 부분: ① backend `concept_edge` **적재기
> 신규**(마이그레이션은 있었으나 적재 로직 부재·노드만 적재돼 있었음) ② 선수 traversal + mastery + enrich 좌석·API.

### 5i.1 선수엣지 적재기 (`l1/concept_graph/backend_edge`·L1·신규 seam 0)

- **현황 교정**: `concept_edge` 테이블은 마이그레이션(`1551744048aa`·2026-05-28)에 *있었으나* 적재기가 없어
  **비어 있었다**(브리지 §5g는 노드만 적재). 이 슬라이스가 엣지 투영을 채운다.
- `BackendConceptEdgeRecord`(frozen): src_code(UC·선수)·dst_code(UC·후행)·edge_type(EdgeType)·edge_strength.
  **evidence·notes·typical_gap_signal 슬롯 부재**(graph.json `evidence`는 gap_signal 의미 부정합·날조 회피·
  NULL 유지·redaction).
- `load_backend_edges_from_graph_json(path) -> (records, skips)`: `payload["edges"]`에서 `relation==
  "prerequisite"`만 `EdgeType.PREREQUISITE`로 적재(그 외 relation·self-edge·양끝 누락은 skip+메시지).
  **방향**: graph.json `src_concept_id`(선수)→`from_concept_id`, `dst_concept_id`(후행)→`to_concept_id`
  (backend EdgeType.PREREQUISITE "A를 알아야 B[A→B]" 규약과 일치).
- `BackendEdgeStore.populate`: backend `concept` 전량 `SELECT concept_id, code` 단일 조회로 **code→UUID
  맵**(N+1 0) 구축 → src/dst UC를 UUID로 해석(orphan은 skip+로그) → `INSERT ... ON CONFLICT(from_concept_id,
  to_concept_id, edge_type) DO UPDATE SET edge_strength`(**edge_id·created_at 미-SET → 재적재 멱등·edge_id
  보존**). 슬3 `_build_sync_engine` 재사용. `edge_type`은 `.value`(문자열)로 바인딩(PG enum·적재/조회 일관).
- `populate.py`에 **④ 선수엣지 적재** 추가(③ 노드 적재 *다음* — 노드가 있어야 code→UUID·FK 가능). CLI가 엣지
  적재 건수 + 로딩 skip 수 출력.

### 5i.2 막힌 선수개념 추천 좌석 (`l2/prerequisite_recommendation`·L2)

- `fetch_prerequisites(session, concept_id) -> list[PrerequisiteRow]`: **방향 traversal** — `concept_edge`에서
  `to_concept_id == concept_id AND edge_type == PREREQUISITE`인 행의 `from_concept_id`(선수)들을 `Concept`
  join으로 code(UC)·name_ko·edge_strength와 함께 조회(미측정 선수도 포함·enrich에 UC 필요·강도 desc 정렬).
  별도 함수로 분리해 단위테스트가 traversal을 패치(실 SQL 격리).
- `PrerequisiteGap`(Pydantic·11 안전 필드): concept_id·concept_code(UC)·concept_name·bkt_mastery·
  irt_mastery_proxy·weakness·agreement·domain·review_status·name_ko·**edge_strength**(선수관계 강도). **본문
  슬롯 부재**(redaction).
- `recommend_prerequisite_gaps(session, user_id, concept_id, *, mastery_threshold=0.7, reviewed_only=False,
  weak_only=True, meta_engine=None)`: ①선수 traversal→②`compute_concept_diagnoses` *한 번* 호출→
  `{concept_id: diagnosis}` 맵으로 선수 mastery lookup(없으면 None·insufficient)→③**weak_only**(기본 True·
  weakness < 임계인 막힌 선수만·미측정 제외; False면 전 선수)→④UC dedupe enrich(`fetch_node_meta` 단일 IN·
  `asyncio.to_thread` 격리)→⑤reviewed_only 게이팅. 정렬: weakness asc(root blocker 먼저)·None 뒤·tie는
  edge_strength desc.

### 5i.3 HTTP 엔드포인트·계층

- `GET /v1/me/weak-concepts/{concept_id}/prerequisites?threshold&reviewed_only&weak_only`(api/me·`ConsentedUser`·
  user_id 스코핑·읽기). 약개념 추천(`/weak-concepts`)과 합성: 클라가 약개념을 고르면 그 선수로 drill-in.
  **노출 계약**: 조회 좌석(안전 필드만·본문 0).
- **7계층**: L1 적재(`concept_edge` ORM·sync 엔진 재사용·신규 seam 0) → L2 조회(`concept_edge`·`fetch_node_meta`
  *호출*·ORM 쿼리빌더만·원시 SQL 0) → L5 표면. 역방향 의존 0. **마이그레이션 0**(테이블 기존재). Neo4j 런타임
  미도입(PG 단일 평면).

### 5i.4 산출물·게이트

- 4게이트 통과(`cd src/backend`·py3.12): `ruff`(green)·`black`(157 unchanged)·`mypy`(**135 src·이슈 0**)·
  `pytest`(**2528 passed/102 skip**·회귀 0)·신규 모듈 cov **backend_edge 96%·prerequisite_recommendation 97%**.
- 신규 테스트 2(+통합 2): `test_concept_backend_edge_load.py`(적재기 단위·파싱[prereq만·self/누락 skip]·방향·
  strength·code→UUID[orphan skip]·ON CONFLICT·edge_id 미-SET 멱등) · `test_prerequisite_recommendation.py`
  (traversal 방향·weak_only·정렬[weakness asc·strength tie]·enrich·게이팅·redaction) · `test_me_integration.py`
  (실 PG: concept_edge 적재→`/prerequisites` 왕복·방향·weak_only·enrich·게이팅·401) · `test_concept_backend_
  load_integration.py`(엣지 적재→row·방향·멱등 재적재 edge_id 보존).
- **통합테스트 기본 SKIP**(`WHYMATH_RUN_INTEGRATION` + PG 미도달 graceful). **CI 신규 잡 불요**(기존 통합 잡이
  `tests/backend/l1/`·`l2/`·`api/` 자동 수집·`alembic upgrade head`엔 concept_edge 기존재). **마이그레이션 0**.
- 시크릿 0·날조 0(evidence 미적재·비-prereq relation skip 가시화). **다음**: 다단계(transitive) 선수 traversal·
  L4 코칭 결선(`PrerequisiteGap`→"선수 복습 먼저" 결정)·비-prereq EdgeType 적재 확장·edge_strength 임계 필터.

---

## 5j. 다단계(transitive) 선수 traversal — 재귀 CTE (개념그래프 *소비* 선수 슬라이스 2 — 2026-06-12)

> **확장 슬라이스(backend·L2)**: 선수 슬라이스(§5i)가 약개념의 **1-hop 직접 선수**만 추천했다면, 이 슬라이스는
> "선수의 선수의 …"까지 따라가 **깊은 선수 체인**을 추천한다(근본 결손이 여러 단계 아래일 수 있음). backend는
> **PG 단일 평면**(Neo4j 런타임 미도입)이라 **SQLAlchemy 재귀 CTE**(`cte(recursive=True)`·Core·원시 SQL 0)로 따른다.

### 5j.1 재귀 CTE traversal (`fetch_prerequisites` 일반화)

- `fetch_prerequisites(session, concept_id, *, max_depth: int = 1)`:
  - **base**(depth=1·앵커): `to_concept_id == concept_id AND edge_type == PREREQUISITE`인 `from_concept_id`·
    `edge_strength`·`literal(1) as depth` → `.cte("prereq_traversal", recursive=True)`.
  - **recursive**(depth+1): `ConceptEdge JOIN base ON ConceptEdge.to_concept_id == base.c.concept_id`(이전 깊이
    선수를 *후행*으로 삼아 한 단계 더)·같은 edge_type·**`WHERE base.c.depth < max_depth`**(bound).
  - `base.union_all(recursive)` → `Concept` join(code·name_ko) → `ORDER BY depth asc, edge_strength desc
    nullslast, concept_id`(안정 정렬).
- **`max_depth=1` ⇒ 기존 1-hop 계약 보존**: recursive 가지의 `depth(=1) < 1 = false`라 recursive가 *전혀
  실행되지 않고* base(직접 선수)만 남는다. 통합 테스트가 실 PG에서 `max_depth=1 → 직접 선수만` 못 박음.
- **dedup(MIN depth)**: diamond(여러 경로)로 같은 선수가 여러 깊이로 나올 수 있어 Python에서 정렬(depth asc) 후
  첫 등장(=MIN depth·동률이면 강도 큰 것)만 유지. **origin C 자체는 방어적으로 제외**(DAG라 안 나오나 안전).
- **DAG 안전**: `validate.py`가 `prerequisite_cycle`을 **hard error**로 막아 데이터셋 v1은 비순환 → 재귀 자연
  종료. 그래도 `max_depth`(API 상한 5)로 방어적 bound(부분 적재·미래 데이터 대비).

### 5j.2 depth 노출·정렬·API

- `PrerequisiteRow`·`PrerequisiteGap`에 **`depth: int`** 추가(1=직접·2=선수의 선수…·MIN 거리·그래프 구조 메타·
  안전). **redaction 불변 유지**(본문 슬롯 여전히 0).
- **정렬**(`recommend_prerequisite_gaps`): `weakness asc`(root blocker 먼저)·None 뒤 → 동률 **`depth asc`**(가까운
  선수 먼저) → `edge_strength desc` → `concept_id`(결정론·4-튜플 키).
- `GET /v1/me/weak-concepts/{concept_id}/prerequisites`에 **`max_depth`**(`Query(ge=1, le=5)`·기본 1) 추가 →
  `recommend_prerequisite_gaps(..., max_depth=max_depth)`. mastery·weak_only·enrich·게이팅은 각 깊이 선수에 동일.

### 5j.3 산출물·게이트

- 4게이트 통과(`cd src/backend`·py3.12): `ruff`(green)·`black`(157)·`mypy`(**135 src·이슈 0**·sort key `tuple[float,
  int, float, str]` 정합)·`pytest`(**2533 passed/105 skip**·회귀 0). 변경 *로직 surface*(max_depth 배선·depth
  tie-break·전파·gap 조립) cov 100%·재귀 CTE *본문*은 integration 전용(실 SQL·PG 게이트·§5i 1-hop 본문과 동일 자세).
- 테스트: `test_prerequisite_recommendation.py`(수정·depth 필드셋·정렬 동률[depth>강도·같은 depth면 강도]·
  redaction)·`test_prerequisite_traversal_integration.py`(신규·실 PG: 3단계 체인 C←P1←P2←P3·max_depth=1/2/3
  경계·diamond MIN-depth·origin 제외)·`test_me_integration.py`(수정·API max_depth 케이스).
- **마이그레이션 0**(기존 `concept_edge`·`idx_concept_edge_to` 조회만). 계층 L2 조회·L5 표면·원시 SQL 0(재귀 CTE도
  Core). **다음**: L4 코칭 결선·비-prereq EdgeType 적재·edge_strength 임계 필터·깊은 체인 EXPLAIN 확인.

---

## 5k. L4 코칭 결선 — "선수 복습 먼저"(prerequisite_review) 코칭 (개념그래프 *소비* L4 슬라이스 — 2026-06-12)

> **L4 결선 슬라이스(backend·L4 결정 + L5 배선)**: 선수 슬라이스(§5i·§5j)가 약개념의 *막힌 선수*(`PrerequisiteGap`)를
> 식별했다면, 이 슬라이스는 L4가 그걸 받아 **"막힌 선수가 있으면 후행 개념을 바로 코칭하지 말고 선수 복습을 먼저
> 권한다"**는 교수학 결정을 내린다(LTHC·기초 우선·CLAUDE.md 교수학 #1·#3). **첫 L4→L2 결선**(L_n→L_{n-1} 허용).

### 5k.1 코칭 포커스 확장 (`l4/metacognitive_trigger`)

- `CoachingFocus` Literal에 **`"prerequisite_review"`** 추가(6→7종)·`_RATIONALE`/`_PROMPT`/`_SOCRATIC_BY_FOCUS` 3 dict에
  일반 템플릿 항목 추가(키 집합 == `CoachingFocus` exhaustiveness·socratic=CLARIFICATION). **`recommend_coaching`은
  무변경** — BKT/IRT만으로 이 포커스를 *반환하지 않는다*(선수 그래프 입력 필요).

### 5k.2 순수 L4 결정 (`l4/prerequisite_coaching`)

- `recommend_prerequisite_coaching(gaps: Sequence[PrerequisiteGap]) -> CoachingTrigger | None` — **순수**(DB·async 0·
  `recommend_coaching` 동형). `gaps` 비면 None(선수 코칭 안 함). 있으면 `gaps[0]`(L2 weakness asc 정렬·top blocker)로
  `focus="prerequisite_review"` 트리거 빌드. rationale(교사용)·prompt(학생용)는 **top blocker 이름으로 동적 구성**
  (표시명 `name_ko`→`concept_name`→"선수개념" 안전 fallback·복수면 "다른 막힌 선수 N개 더 있음"). socratic=CLARIFICATION.
- **L4→L2**: `PrerequisiteGap` 타입을 l2에서 import(다운워드 의존·허용). 순수 결정만(데이터 fetch는 L5).

### 5k.3 API·노출 계약

- `GET /v1/me/weak-concepts/{concept_id}/coaching?threshold&max_depth`(api/me·`ConsentedUser`·user_id 스코핑). **L5
  오케스트레이션**: ① `recommend_prerequisite_gaps(weak_only=True)` fetch → ② `recommend_prerequisite_coaching(gaps)`이
  *막힌 선수 있으면* 선수 코칭 **최우선** 반환 → ③ 없으면 `compute_concept_diagnoses`에서 이 개념 BKT/IRT 찾아
  `recommend_coaching` fallback(진단 없으면 `recommend_coaching(None, None)`→diagnose).
- **톤(우선순위 #1·#3)**: 학생 prompt는 격려·메타인지 초대("…부터 한 번 같이 떠올려 볼까?")·선수 비난 0·"정답 빠르게"/
  우열 금지·바로 정답 아님(선수 복습 *권유*). 톤 가드 테스트(`["빨리","정답","틀렸","못"]` 부재)로 못 박음.
- **redaction**: rationale/prompt에 삽입은 name_ko·concept_name(안전 표시)뿐 — 본문(description·formal_definition·
  evidence) 0(`PrerequisiteGap` 스키마에 슬롯 없음). 조회 좌석(학생 직접 노출 아님).

### 5k.4 산출물·게이트

- 4게이트 통과(`cd src/backend`·py3.12): `ruff`(green)·`black`(158)·`mypy`(**136 src·이슈 0**)·`pytest`(**2548 passed/
  106 skip**·회귀 0)·신규 `prerequisite_coaching.py` cov **100%**(17 stmts·4 branch·0 miss).
- 테스트: `test_prerequisite_coaching.py`(신규·15 순수: None·focus·동적 이름·복수 부가·weakness None·frozen·**톤 가드**·
  exhaustiveness)·`test_me_integration.py`(수정·실 PG: 막힌 선수→prerequisite_review+이름·없으면 메타인지 fallback·
  redaction·401). **마이그레이션 0**. 계층 L4 순수·L5 배선·L4→L2 타입 의존·`recommend_coaching`·`compute_concept_
  diagnoses`·`recommend_prerequisite_gaps` 무변경.
- **다음**: 비-prereq EdgeType 적재·edge_strength 임계 필터·`POST /v1/coach`에 선수 코칭 통합·다선수 동시 제시.

---

## 5l. 선수 코칭을 상호작용 코칭 흐름에 통합 (`POST /v1/coach/sessions` — 2026-06-12)

> **L5 통합 슬라이스(backend)**: L4 결선(§5k)이 진단 drill-in(`GET /v1/me/.../coaching`)에 선수 코칭을 노출했다면,
> 이 슬라이스는 *학생이 실제 푸는* 상호작용 코칭 응답(`/v1/coach/sessions`)에도 선수 차단 신호를 함께 실어준다.
>
> **데이터 현실 확인(다른 후속 후보 기각)**: 데이터셋 v1 엣지는 **541 전량 prerequisite**(2026-06-13 당시)(비-prereq relation 0)·
> strength는 transform이 `_DEFAULT_EDGE_STRENGTH` **균일 합성**(소스 미보유·변별력 0) → "비-prereq EdgeType 적재"·
> "edge_strength 임계 필터"는 v1에선 no-op이라 기각. `/v1/coach` 통합을 후속으로 선택.

### 5l.1 구현 (`api/coach.py`)

- `CoachResponse.prerequisite_coaching: CoachingTrigger | None`(기본 None) 필드 추가 — "이 문제 개념의 막힌 선수가
  있으면 선수 복습 코칭·없으면 null. Polya 결정과 *별개의 추가 신호*."
- 헬퍼 `_prerequisite_coaching_for(session, user_id, problem_id, *, mastery_threshold=0.7, max_depth=1) ->
  CoachingTrigger | None`: problem_id None→None / `get_primary_concept_id`(PRIMARY·TESTED 폴백) None→None /
  `recommend_prerequisite_gaps(weak_only=True)`→`recommend_prerequisite_coaching(gaps)`(막힌 선수 없으면 None).
- **stateful 배선**: `create_session`(body.problem_id)·`append_turns`(dialogue.problem_id)가 헬퍼 호출→응답 필드 주입.
- **stateless `/v1/coach`(`coach_decide`)는 불변** — `prerequisite_coaching` 미전달(기본 None·DB·user 미사용·계약 보존).
  `_build_response_payload`(공유 결정 계산·6-튜플)·반환·호출부 **전혀 무변경**(stateless 비트동일).

### 5l.2 계층·교수학 안전·redaction

- **계층**: L5(api/coach)가 L2 fetch(`recommend_prerequisite_gaps`) + L4 decide(`recommend_prerequisite_coaching`)
  배선 — §5k `GET /v1/me/.../coaching`과 동일 오케스트레이션. L2/L4 좌석 순수 재사용·역의존 0·**마이그레이션 0**.
- **교수학 안전**: 선수 코칭은 *별개 추가 신호*(non-override) — Polya `decision`을 대체하지 않고, 코칭 턴을 가로채
  학생 풀이를 끊지 않는다(클라/L5가 우선 제시 결정). 톤은 재사용 L4 함수가 보장(비난 0).
- **redaction**: `CoachingTrigger.rationale/prompt`엔 name_ko(안전 표시)만·본문 0(`PrerequisiteGap` 슬롯 부재).
  `expected_answer`(정답)는 이 경로 미관여.

### 5l.3 산출물·게이트

- 4게이트 통과(`cd src/backend`·py3.12): `ruff`·`black`(158)·`mypy`(**136 src·이슈 0**)·`pytest`(**2556 passed/107
  skip**·회귀 0·coach 단위 186). 신규 단위 8(`_prerequisite_coaching_for` 4분기 + 필드/배선/stateless-None)·통합 1
  (실 PG: problem→concept→막힌 선수→`/v1/coach/sessions`가 `prerequisite_coaching.focus=="prerequisite_review"`·
  없으면 None·stateless 항상 None·redaction). 커버리지 측정은 환경의 pgvector→numpy 이중임포트(C 트레이서) 제약으로
  우회(verbose 실행으로 신규 분기 전수 도달 확인·CI 실 PG 잡에서 통합 실측).
- **다음**: 커버리지 하니스 복구(pgvector 더블임포트 회피)·실 PG 통합 실행 검증·클라(Flutter) 선수 코칭 *우선 제시* UX 계약.

---

## 6. 향후 활용

1. **L1 개념그래프 적재**(대형·진행 중): src_id→UC 매핑 · 스키마 확장(CCSS·은유·허용표현) ·
   541 선수엣지→`prerequisite` 엣지 · 검수 표식(reviewed 114·pending 289)은 **슬라이스 1에서
   완료**(§5b·무저장소 transform·검증) · **Neo4j 멱등 적재는 슬라이스 2에서 완료**(§5c·403 노드·541
   엣지·MERGE 멱등·env 접속) · **개념 pgvector 임베딩 적재는 슬라이스 3에서 완료**(§5d·UC 키 이중
   store·name_ko+metaphor+accepted 임베딩·멱등 upsert·backend 패키지) · **개념 의미검색 조회 좌석 +
   backend search API는 슬라이스 4에서 완료**(§5e·`search_concepts`·`GET /v1/concepts/search`·UC
   concept_id+similarity 반환) · **메타 enrichment + 검수 게이팅은 *소비* 아크 슬라이스 1에서 완료**
   (§5f·메타 브리지=**PG 프로젝션**[backend↔Neo4j 런타임 연결 0]·`concept_node` UC 키 메타·검색이
   name_ko·domain·review_status를 PG 조인으로 enrich·`reviewed_only` 게이팅 필터·삼중 store 단일 UC 키).
   · **브리지(backend `concept` 적재·`code`=UC)는 *소비* 아크 브리지 슬라이스에서 완료**(§5g·사중 store
   단일 UC 키·런타임 경로 닫힘) · **약개념 추천(L2 약점 + `concept_node` UC 메타 enrich)은 *소비* 아크
   슬라이스 2에서 완료**(§5h·`recommend_weak_concepts`·`GET /v1/me/weak-concepts`·L2 약점→`concept.code`
   [UC]→그래프 메타·검수 게이팅·`asyncio.to_thread` 격리). **후속(소비 슬3+)**: 선수엣지(`concept_edge`
   PREREQUISITE) traversal로 막힌 선수개념 추천 · L4 결선(오개념↔약개념 자동 연결) · 풍부 메타 노출
   (standard_codes·difficulty_tier 등·Neo4j traversal은 *여전히 미도입*·필요 시 별도 결정).
2. **L4 오개념 확장**(후속): §5.4 후보를 doc-first로 카탈로그에 추가(30종+ 목표).
3. **암기카드**(L6): 113장 — `exposure_condition`("이해 마스터 후 노출")이 메타인지 정책과 정합.

---

## 6. Lifecycle — legacy_snapshot 격하 (2026-07-04·S0-4b/S0-4c)

> **상태 전환**: 이 개념그래프(구 437)는 **runtime truth source에서 격하**되어 `legacy_snapshot`
> (`readonly`·`non_runtime`·`audit_only`)이 되었다. **runtime truth source = 원자 백본**
> (`atom_graph_v1` — 데이터 카드 `atom_graph_v1.md`). 물리 삭제는 **하지 않는다**(형식 격하만·행 보존).

### 6.1 격하 근거·범위

- **선행(완료)**: `/concepts/search`→원자(`search_atoms`, S0-4a) · L2 weak/prerequisite enrich→
  `fetch_atom_node_meta`(`concept_node`→`atom_node`, S0-4d). 그 결과 **런타임(api·l2·l3·l4)의 구 437
  reader = 0**(`fetch_node_meta`·`ConceptNodeMeta`·`ConceptEmbeddingIndex`·`search_concepts`·
  `concept_node`·`concept_embedding`의 import/call 0건).
- **구 437을 읽는 곳(허용·audit/빌드타임)**: 크로스워크(`l1/concept_atom_crosswalk` — derive·transfer)·
  `l1/curriculum/populate.py`·거버넌스/통합 테스트. 이들은 코퍼스(`graph.json`)를 provenance·이전
  근거로 읽는 *빌드타임* 소비처다(런타임 경로 아님).
- **마커 위치**: 코퍼스 `_provenance.json`의 최상위 `lifecycle` 키(`status="legacy_snapshot"`·
  `non_runtime=true`·`audit_only=true`) · backend `l1/concept_graph/` 런타임성 모듈 docstring 배지
  `[LEGACY_SNAPSHOT · non_runtime · audit_only]` · Neo4j `:Concept` 적재기
  (`data_pipeline/concept_graph/load.py`) docstring 배지 `[LEGACY_SNAPSHOT · audit_only]`.

### 6.2 거버넌스 동결 (회귀 가드)

`tests/backend/l1/test_legacy_snapshot_governance.py`가 3불변식을 동결한다:
(i) 런타임 437 reader = 0(api·l2·l3·l4 정적 스캔·AST 기반), (ii) 구 437 소비 화이트리스트 =
`l1/concept_atom_crosswalk`·`l1/curriculum/populate.py`만, (iii) `_provenance.json` lifecycle
마커 존재. 신규 런타임 reader가 유입되거나 격하 표식이 지워지면 red.

> **Neo4j `:Concept`(S0-4c)**: backend는 런타임에 Neo4j를 읽지 않으므로(pgvector 단일 평면),
> `:Concept` 노드도 물리 삭제 불요·audit 전용 스냅샷이다. 런타임 그래프는 `:Atom`.
