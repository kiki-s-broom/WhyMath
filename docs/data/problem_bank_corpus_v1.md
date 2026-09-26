# 문제은행 코퍼스 (자체 저작 6종) — 데이터 카드

> **⚠️ 정정 (2026-08-11 · 문제은행 R3 §정정-1 → 커버리지 회수 시 재정정)**: 아래 요약의
> **"6종 · 전 2,613건"은 stale**이다. **현행 실측은 7종 2,638건**이다. 두 단계로 움직였다:
> ① `S4-13`이 7번째 코퍼스 `problem_bank_probability_finite_v0` **34건**을 신설(2,613 + 34 =
> 2,647) ② `QUAL-02`(PR #777·`50b43b6e`)가 실중복 **9레코드를 은퇴**(`generated_v0` 620→619 ·
> `rephrased_v0` 429→421)해 **2,647 − 9 = 2,638**. `probability_finite_v0`의 34문은
> **노출 부적격**(`review_status=pending`·`is_published=False`) 상태다. **[정정 2026-09-25]** 종전
> 문면의 해제 조건 "`S4-16` 강등전 통과"는 더 이상 없다 — `S4-16`이 2026-09-25 **기각**(Kiki · 게이트
> `G-s416-round2-live-battle`)돼 기계 게이트 경로가 닫혔고, 노출하려면 사람 검수 경로(검증 권위 서열
> ③)만 남았다. 그 검수는 **보류**(담당·일정 미정 — `docs/standards/residue_gate_demotion_battle_history.md`
> §5-4·§6). 본문(§0 표 포함)은 이력 보존을 위해 개정하지 않는다 — 정본 수치는 이 배너다.
> 근거: `docs/architecture/problem_bank_gap_review_r3.md` §부록 ·
> `docs/data/problem_duplicate_disposition_2026-08.md` · `docs/data/problem_bank_coverage_2026-08.md` §8.1.

> **요약**: 연습·평가용 문항 코퍼스 6종, 전 2,613건(2026-08-03 갱신 — `rephrased_v0`가 위생 게이트
> 확장으로 483→429건 소급 조정), **전량 자체 저작**(`source_type=자체생성`·`license=WHYMATH_GENERATED`)
> — 평가원·EBS·검정교과서 본문 복제 0. 진단문항(`atom_probe`)과는 별개 자산이며, 이 문서의 범위는
> 연습·모드별 출제용 문제은행이다.
>
> **역할 경계**: 문제은행(연습·평가) vs `atom_probe`(원자 단위 진단문항+소크라테스, 별도 데이터
> 카드 `atom_probe_v1.md`) — 후자는 진단, 전자는 연습·CAT 출제를 담당한다(`l6/__init__.py` 참조).

---

## 0. 코퍼스 6종 요약

| 코퍼스 | 건수 | 생성 방식(LLM 개입) | 생성 CLI | 표본 검수 | `_provenance.json` |
|---|---:|---|---|---|---|
| `problem_bank_v1` | 4 | 손저작 시드(계약 문서 그 자체) | — (수기 시드) | — | ✅ (2026-07-05) |
| `problem_bank_generated_v0` | 620 | 결정론 스켈레톤 15밴드(LLM 0) | `python -m whymath_backend.harness.problem_corpus_batch` | ✅ 240표본 Wilson 95% 상한 1.11% PASS | ✅ |
| `problem_bank_conceptual_v0` | 360 | 개념형(개수·판정) 객관식 15밴드(LLM 0) | `python -m whymath_backend.harness.conceptual_count_mc_batch` | ✅ rotation-1 200/360표본 Wilson 상한 1.33% PASS | ✅ |
| `problem_bank_killer_v0` | 120 | Vieta 근집계 킬러 단답형(LLM 0) | `python -m whymath_backend.harness.root_aggregate_batch` | ⚠ rotation-1 120/120 전수 결함 0건이나 min-n 200 미달로 게이트 판정 불가(구조적 미해결) | ✅ |
| `problem_bank_misconception_mc_v0` | 1,080 | 오개념 수치평가 객관식 45서브밴드(LLM 0) | `python -m whymath_backend.harness.misconception_mc_batch` | ✅ rotation-0 FAIL 63.60%→rotation-1 FAIL 7.58%→rotation-2 PASS(Wilson 상한 1.33%) | ✅ |
| `problem_bank_rephrased_v0` | 429 | generated_v0 발문만 LLM 재작성(수치·정답·distractor_map 등은 코드가 그대로 복사) | `python -m whymath_backend.harness.problem_corpus_rephrase` | ✅ 표본 3라운드 연속 FAIL(12%→5.5%→1%) 후 전수 감사(429/429) Wilson 상한 0.63% PASS | ✅ |
| **합계** | **2,613** | | | **5/6 표본 검수 완료(PASS)·1/6 구조적 미해결(killer, 코퍼스 확장 대기)** | **6/6 완료** |

`problem_bank_rephrased_v0`가 유일하게 LLM을 쓰는 축은 *발문 문장 표현*뿐이다 — 수치·정답·선지·
`distractor_map`·난이도·`slug`·`problem_id`는 원본(`generated_v0`)에서 그대로 복사돼 LLM 산출을
신뢰하지 않는다(`l3/equivalent/rephrase.py` 계약).

**표본 검수 현황(2026-08-03 갱신 — ARCH-25 S3-11 회수 시 정정)**: 갭 리뷰
(`docs/architecture/problem_bank_gap_review.md` §3 D2)가 지적한 표본 감사 공백은 S3-09(2026-07-29
720문 감사)→S3-12(계통 결함 5류 생성기 환류·rotation-1 재검수)→S3-14(rotation-2 확인 감사)→
S3-15(rephrased 근본 설계 재검토·전수 감사 전환)를 거쳐 대부분 해소됐다.
- `conceptual_v0`: rotation-1에서 PASS(결함 0·Wilson 상한 1.33%).
- `misconception_mc_v0`: rotation-0 FAIL(63.60%)→rotation-1 FAIL(7.58%)→rotation-2 PASS(결함 0·
  Wilson 상한 1.33%) — 3라운드 만에 통과.
- `rephrased_v0`: 표본 3라운드 연속 FAIL(12%→5.5%→1%, Wilson 상한이 매번 2% 임계 초과) 후 근본
  설계 재검토(S3-15)로 전수 감사(429/429)로 전환해 결함 0·Wilson 상한 0.63%로 최종 PASS.
- `killer_v0`: rotation-1에서 120/120 전수 결함 0건을 확인했으나, 코퍼스 크기(120)가 표본 게이트
  최소 표본수(min-n 200) 미만이라 **자동 게이트 자체가 판정을 낼 수 없다**(품질 실패가 아니라
  구조적 미달). 코퍼스를 ≥200건으로 확장하는 것은 별도 저작 스코프 결정이며 아직 이뤄지지
  않았다 — **PASS로 서술하지 않는다**.

상세 근거·수치: `docs/data/ai_review_batch_v0_4corpora_2026-07.md`.

---

## 1. 파이프라인 4축 (모두 실가동 — 갭 리뷰 §0 인용)

1. **스키마 3층**: `schema/problem.py`(Pydantic 정본 700+행·50+필드) → `db/models/problem.py`(ORM)
   → alembic. 저작권 validator `_METADATA_ONLY_SOURCES`(`schema/problem.py`) — 평가원·EBS·교과서
   출처는 본문 필드가 비어야만 통과.
2. **생성·검증(L3)**: `l3/equivalent/` 생성기(스켈레톤 15종·`llm_generator`) → 수용 게이트 4종
   (`acceptance.evaluate_equivalent_candidate`: 저작권·정확성 Tier1/2·위생·동등성 분류) →
   canonical signature dedup(`canonicalize.py`) + 임베딩 dedup(코사인 0.97). 독립 감사
   `retag.py`(생성자≠검증자) · 수치 반례 `counterexample_fuzz.py`(≥10,000회).
3. **적재(L1)**: `l1/problem_bank/populate.py` — JSONL → `problem`·`problem_concept` 멱등 upsert
   (slug 충돌 `ON CONFLICT DO UPDATE`). L1은 L3 게이트를 호출하지 않는다(import-linter L1→L3
   금지) — 게이트 통과는 **코퍼스 저작 계약**(각 `_provenance.json`의 `contract` 절 참조).
4. **노출(L2/L6)**: `l6/_shared.py::is_exposable()`(저작권 최종 게이트) × L6 모드 게이팅(수능·
   학교진도·RT·메타인지·사고력·영재 — `S3-10`이 `persona_fit` 축을 백필) × `GET
   /v1/me/next-problem`(IRT CAT) × BKT 약점 가중.

## 2. 노출 4단 구분 — "게이트 통과 ≠ 학생 노출"

전 배치 CLI docstring이 반복 명시하는 규약(갭 리뷰 §0):

```
① 게이트 통과(S2-a 수용 게이트)
   ↓
② 코퍼스 편입(populate.py가 problem 테이블에 적재)
   ↓
③ 노출 적격(is_exposable + 사람/AI 표본 검수)
   ↓
④ 실노출(L6 모드 게이팅 통과 → CAT 선택)
```

6종 전부 ①·②는 실측 완료(코퍼스에 존재 = 게이트 통과 계약). ③은 `generated_v0`·`conceptual_v0`·
`misconception_mc_v0`·`rephrased_v0` 4종 완료(PASS, 2026-08-03 갱신 — S3-09/S3-12/S3-14/S3-15
경유), `killer_v0`는 코퍼스 크기(120)가 표본 게이트 min-n(200) 미만이라 게이트가 구조적으로
판정을 낼 수 없어 노출 부적격 유지(코퍼스 확장 대기). ④는 `persona_fit` 백필(S3-10, 2026-07-29)로
L6 6개 모드의 페르소나 적합도 경로가 살아났으나(§4 참조), 실제 학생 트래픽은 아직 0이라 "실노출"은
코드 경로 활성화 이상의 의미는 아직 없다.

## 3. 저작권 보증 (전 6종 공통)

- **전량 자체 저작**: `source_type=자체생성` · `license=WHYMATH_GENERATED`. 평가원·EBS·검정교과서
  *본문·문항·풀이·그림* 복제 0(CLAUDE.md 절대 금기·저작권 가이드 v2.0 §32 단서).
- **성취기준 코드는 구조 메타**로만 인용(NCIC 공공누리) — 교과서·기출 *표현*은 인용하지 않는다.
- **유사도 스캔 산출물 없음** — 저작권 보증은 유사도 검사가 아니라 *생성 방식*(본문 미보유 출처
  대체·성취기준+구조 시그니처 결정론 생성)에 근거한다(`licensing_safety.md` §109-112·§125).
- 코퍼스별 세부 사유는 각 `_provenance.json`의 `copyright_rail` 절 참조.

## 4. `persona_fit` 백필과의 관계 (S3-10, 2026-07-29)

이 데이터 카드 작성 직전 슬라이스(S3-10)가 6종 전 2,667건의 `persona_fit`(전부 `{}`였음)을
결정론 규칙으로 백필했다 — 상세 실측은 `docs/data/persona_fit_backfill_report_s3_10.md`,
계산 근거는 `docs/data/persona_fit_backfill_audit/*.jsonl` 참조. 이 데이터 카드는 *코퍼스
자체*(생성·저작권·검수)를, S3-10 리포트는 *페르소나 적합도 축*을 각각 정본으로 다룬다.

## 5. 재현 명령

```bash
# 코퍼스별 재생성(레포 루트에서 실행 — 상대경로 규약)
python -m whymath_backend.harness.problem_corpus_batch              # generated_v0
python -m whymath_backend.harness.conceptual_count_mc_batch          # conceptual_v0
python -m whymath_backend.harness.root_aggregate_batch               # killer_v0
python -m whymath_backend.harness.misconception_mc_batch             # misconception_mc_v0
python -m whymath_backend.harness.problem_corpus_rephrase            # rephrased_v0(generated_v0 선행)

# DB 재적재(멱등 upsert — 코퍼스별 반복 실행)
python -m whymath_backend.l1.problem_bank.populate --problems data/corpus/problem_bank_v1/problems.jsonl
python -m whymath_backend.l1.problem_bank.populate --problems data/corpus/problem_bank_generated_v0/problems.jsonl
python -m whymath_backend.l1.problem_bank.populate --problems data/corpus/problem_bank_conceptual_v0/problems.jsonl
python -m whymath_backend.l1.problem_bank.populate --problems data/corpus/problem_bank_killer_v0/problems.jsonl
python -m whymath_backend.l1.problem_bank.populate --problems data/corpus/problem_bank_misconception_mc_v0/problems.jsonl
python -m whymath_backend.l1.problem_bank.populate --problems data/corpus/problem_bank_rephrased_v0/problems.jsonl

# 품질 회귀(코퍼스 저작 계약 봉인)
pytest tests/backend/l1/problem_bank/test_corpus_quality.py
```

## 6. 관련

- 갭 원본: `docs/architecture/problem_bank_gap_review.md`(§0 파이프라인·§3 D1~D9 갭 목록)
- 각 코퍼스 개별 provenance: `data/corpus/problem_bank_*/​_provenance.json`
- 라이선스 대장: `docs/data/licensing_safety.md`(이 코퍼스 1행 신설)
- 페르소나 적합도 백필: `docs/data/persona_fit_backfill_report_s3_10.md`
- 표본 검수(generated_v0 완료분): `docs/data/reviewer_sample_240_v0.md` · `docs/data/corpus_audit_240.jsonl`
- 잔여 4종 표본 검수(2026-08-03 갱신 — 완료): `docs/data/ai_review_batch_v0_4corpora_2026-07.md`
  (S3-09 최초 감사 → S3-12 rotation-1 환류 → S3-14 rotation-2 확인 → S3-15 rephrased 전수 감사 전환)
