# 와이매스 개념 콘텐츠·학습경로 코퍼스 v1 — 데이터 카드

> **요약**: 2026-06-20 업로드한 두 신규 데이터셋 — ① 개념별 **7계층 본문**(L1_HOOK~L5_META·437개념·
> JSON `fac16e6f…`)과 ② **7주체 S1~S7 학습경로**(Path xlsx `f4ee650b…`·677행)을 *적재 가능한 자산*으로
> 만들기 위한 데이터 카드. 둘 다 **와이매스 자체 저작**(라이선스 안전). 수집 청사진은
> `external_corpus_ingestion_v1.md` §3·§4·Phase C.
>
> **현황(2026-06-20)**: *설계 전용*. store·마이그레이션·로더는 승인 후 별도 슬라이스.

---

## A. 7계층 본문 (L1_HOOK~L5_META)

### A.1 출처·규모
| 항목 | 값 |
|---|---|
| 형태 | 7계층 본문 JSON(개념 437) |
| sha256(앞 16) | `fcf6d333a419a222` |
| 저작 | 와이매스 자체 저작(본문·은유·암기카드·깊이본문) |
| 추출 산출물 | `data/corpus/concept_content_v1/concept_content_437.jsonl` |

### A.2 스키마 (개념별 layer)
| Layer | 키 | 적재 |
|---|---|---|
| `L1_HOOK` | 도입·은유 | ✅ 본문 store |
| `L2_CONCEPT` | 핵심개념정리·학습목표·암기카드·깊이본문_gemini | ✅ 본문 store |
| `L3_VISUAL` | spec·status(전부 **미구축**) | 후속(05 선언적 시각화 명세) |
| `L4_PRACTICE` | 자체문항_output_v3(개념체크·대표예제·적용문제·심화문제)·AIHub문항수·AIHub문항·함정포인트 | **문제뱅크(Phase D)로 분리** |
| `L5_META` | S1_진입임계·S4_시드문항·S5_출구·S7_간격복습·오개념 | 임계→§B 경로·오개념→오개념 카탈로그 |

> 본 콘텐츠 store는 **본문(L1·L2)만** 적재한다. 문항(L4)·오개념(L5)·시각화(L3)는 각각 문제뱅크·
> 오개념 카탈로그·시각화 명세로 분리(단일 책임).

### A.3 라이선스·안전
- 본문 전체 **자체 저작** → redaction 불요(`concept_node.description` redaction과 대비 — 그쪽은 근접복제
  우려, 본 본문은 자체 작성). 단 *교과서 표현 paraphrase* 표본 검수(CLAUDE.md 교과서 변호사 검토 전제).

---

## B. 7주체 S1~S7 학습경로

### B.1 출처·규모
| 항목 | 값 |
|---|---|
| 형태 | 7주체 경로 xlsx(8시트) |
| sha256(앞 16) | `f4ee650b734ac854` |
| 저작 | 와이매스 자체 저작(교수학 경로 설계) |
| 규모 | 전체요약 **677**행 · 트랙 7(초119·중60·고기본34·고일반93·고진로127·재수130·영재114) |
| 추출 산출물 | ⏳ **계획(미적재)** — `data/corpus/learning_paths_v1/learning_paths.jsonl` |

> ⚠️ **2026-08-03 정정**: 자매 데이터셋 §A(7계층 본문)는 `data/corpus/concept_content_v1/content.json`과
> 적재기(`l1/concept_content/populate.py`)까지 **실재 착지**했는데, 이 §B는 코퍼스 파일·store·로더가
> **전부 미존재**다. 같은 표 형식으로 나란히 적혀 있어 실재로 오독되던 것을 ⏳ 표기로 분리한다.
> 원본 Path xlsx도 저장소에 없다(Kiki 소유). 추적은 `PATH-04-learning-path-corpus-ingestion`이
> 소유한다 — 근거: `docs/architecture/learning_path_module_gap_review.md` §3 D2·§6 8회차.

### B.2 스키마 (행 = 한 소단원의 페르소나별 경로)
| 단계 | 의미 | L2/L4 소비 |
|---|---|---|
| S1 진단게이트 | 진입 임계 | **L2 mastery 게이트** |
| S2 개념형성 | EIS(Bruner) 표상 도입 | L4 교수학 |
| S3 유도연습 | 안내된 연습 | L4 |
| S4 적응숙련(오개념·시드) | 오개념 교정·시드문항 | L4 + 오개념 카탈로그 |
| S5 숙달게이트 | 출구 임계 | **L2 mastery 게이트** |
| S6 확장전이 | 전이 과제 | L4 |
| S7 간격복습 | 간격 반복 일정 | L2 망각곡선 |
| (메타) | 주체·과목·단원·소단원·`concept_id`·성취기준·이론틀(EIS)·S4 시드문항수·대상특화 | |

### B.3 store 설계(제안)
- `learning_path`(`concept_code`×`persona`·S1~S7 JSONB 또는 7열)·`이론틀`·`S4_시드문항수`·`대상특화`.
- **페르소나↔트랙 직교**(v2 §5-6): `Persona`(A~E·시장 세그먼트) ⟂ 트랙(초·중·고3트랙·재수·영재·교육과정
  레벨). 둘 다 유지·혼동 금지.

### B.4 라이선스·안전
- 경로 설계 전체 **자체 저작** → 안전. 성취기준·concept_id 참조는 구조 메타.

---

## C. 공통 불변식 (적재 검증)
- 본문: 437개념 전건 `concept_code` 해소(고아 0).
- 경로: 전체요약 677행의 `concept_id` 전건 해소·트랙 7 합계 일치(119+60+34+93+127+130+114=677).
- S1 진단/S5 숙달 임계가 L2 mastery 게이트 파라미터로 해석 가능(타입·범위 검증).
- `L3_VISUAL.status=미구축` 명시적 보존(가짜 spec 날조 0).

---

**버전**: v1 (설계 전용) | **최종 수정**: 2026-06-20 | 관련: `external_corpus_ingestion_v1.md`·
`misconception_catalog_v1.md`·`concept_graph_dataset_v1.md`
