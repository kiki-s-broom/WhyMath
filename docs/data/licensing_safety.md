# 데이터 라이선스 안전선 매트릭스

> 모든 데이터 소스 활용 전 *반드시* 이 매트릭스 확인.

## 한국 자원

| 자원 | 라이선스 | 상업 OK | 가공 OK | 출처 표시 | 비고 |
|---|---|---|---|---|---|
| NCIC 성취기준 | 공공누리 1유형 | ✅ | ✅ | ✅ 필수 | Truth source |
| 공공누리 AI유형 | 공공누리 AI (2026-01) | ✅ | ✅ | ✅ | AI 학습 허용 명시 |
| AIHub 수학 데이터셋 | 영리 허용 | ✅ | ✅ | ✅ | 71859 등, 영리 명문허용 |
| 학교알리미 | 공공 | ✅ | ✅ | ✅ | PII 처리 주의 |
| 와이매스 개념그래프 데이터셋 v1 (자체작성) **[legacy_snapshot]** | 자체 저작 | ✅ | ✅ | ✅ | 403개념·교수학 주석(오개념·은유·허용표현)+성취기준/CCSS 코드. 설명·정식정의는 성취기준 본문 복제 회피로 redact·검수필요 289 (데이터 카드: `concept_graph_dataset_v1.md`). **2026-07-04 legacy_snapshot 격하** — runtime truth source=원자 백본(`atom_graph_v1.md`), 구 437은 audit·빌드타임 provenance 전용(런타임 미참조·물리 삭제 0) |
| 와이매스 외부 큐레이션 코퍼스 v3 (자체작성) | 자체 저작 | ✅ | ✅ | ✅ | 오개념 839·7계층 본문(437개념)·7주체 S1~S7 경로(677)·자체문항 4,030. 전부 자체 저작·redaction 불요. 성취기준/CCSS 코드는 구조 메타만 (데이터 카드: `misconception_catalog_v1.md`·`concept_content_corpus_v1.md`·`external_corpus_ingestion_v1.md`) |
| 와이매스 원자 백본 데이터셋 v1 (자체작성) | 자체 저작 | ✅ | ✅ | ✅ | 원자 1,837·선수엣지 3,220(초중고+대학 3축 확장)·교수학 4요소(오개념·진단문항·소크라테스·전이)·원자성. `핵심명제/성취기준내용`(K-12)은 NCIC 성취기준 본문 복제 회피로 redact(연결성취기준 코드로 다리·대학 핵심명제는 자체작성 보존)·AI 추정 메타 검수필요. ②진단문항·③소크라테스 DB 투영(`atom_probe`·Phase 3 Slice 3)은 자체/AI 작성·standard_codes 코드만·본문 슬롯 부재 (데이터 카드: `atom_graph_v1.md`·`atom_probe_v1.md`) |
| 와이매스 대학 성취기준 v1 (자체작성) | 자체 저작 | ✅ | ✅ | ✅ | 대학 성취기준 409(32과목·148단원·409소단원·소단원↔성취기준 1:1). 본문=원자노드DB 핵심명제 종합(AI 추정·검수필요)·**redaction 불요**(NCIC 공공누리 아님·K-12 본문과 분리). 코드(`CALC1-U1-S1` 등)는 대학과정 코드참조 재사용→원자DB 조인 보존 (데이터 카드: `standards_university_v1.md`) |
| 와이매스 대학 소단원 콘텐츠 v1 (자체작성) | 자체 저작 | ✅ | ✅ | ✅ | 대학 소단원 409 교수학 콘텐츠(은유·오개념·정식정의·허용표현·설명)+암기카드 409. 자체작성·AI 추정·**검수필요**·redaction 불요. **`정식정의`=학생 비노출**(내부·검수용). 콘텐츠 4종 DB 투영은 Phase 3 (데이터 카드: `concept_content_university_v1.md`) |
| 와이매스 K-12 개념 콘텐츠 v1 (자체작성) | 자체 저작 | ✅ | ✅ | ✅ | K-12 개념 437 교수학 콘텐츠(은유·오개념·정식정의·허용표현·설명)+암기카드 113. 자체작성·AI 추정·**검수필요**. **`explanation` 133건은 NCIC 성취기준 본문과 사실상 동일**(2026-09-06 전수 실측 — ≥0.90·그중 124건 완전 일치). 보유·상업 이용 제약 없음 — 교육부 고시 제2022-33호는 저작권법 §7 제1호(고시)상 비보호 + 공공누리 제1유형(출처 표시)이며 같은 본문을 `standards_v1`이 같은 근거로 895건 보유한다(아래 'NCIC 구분' 전자에 해당). 연결 성취기준 코드도 다리로 보존. 2026-09-06 이전 이 칸은 "미수록"을 주장했고 그 선언이 데이터와 모순이었다 — 집행 = 빌드 시점 실측 합성(`data_pipeline/concept_content/ncic_overlap.py`) + `tests/backend/l1/test_concept_content_license_declaration.py`. **`정식정의`=학생 비노출**(내부·검수용). 콘텐츠 4종 DB 투영은 Phase 3 (데이터 카드: `concept_content_v1.md`) |
| 와이매스 437↔원자 크로스워크 v1 (자체 유도) | 자체 저작 | ✅ | ✅ | ✅ | 구 437 개념↔신 원자 매핑 437행(프로그램적 유도 — 성취기준 코드 교집합+이름 자카드). 양측 소스 자체작성이라 **redaction 불요**(코드·이름만·성취기준 본문 미포함). 전량 `ai_estimated`·검수 전. 1:N 귀속은 `primary_atom_code` 기준(S0-2 소비) (데이터 카드: `concept_atom_crosswalk_v1.md`) |
| 와이매스 WH-S PRM 학습셋 v0 (자체 유도) | 자체 저작 | ✅ | ✅ | ✅ | PRM process-supervision 학습쌍 1,282(good 663·bad 619·620문 전수). 자체생성 코퍼스의 검증 단계 체인을 WH-S 하네스 replay로 라벨링(good=SymPy 동치 증명·bad=결정론 결함 주입 비동치 증명·ground truth 기지). 외부 본문 0·학생 PII 0·prm_score 전건 null(모델 미학습·날조 금지). **good=construction trace라 실 LLM 오류 분포와 다를 수 있음**(실탐색 라벨은 LLM 정책 후속) (데이터 카드: `whs_prm_v0/_provenance.json`·기록: `whs_production_run_2026-07.md`) |
| 와이매스 문제은행 코퍼스 6종 v0/v1 (자체 저작) | 자체 저작 | ✅ | ✅ | ✅ | 연습·평가 문항 2,613건(성취기준+구조 시그니처 결정론 생성 5종·손저작 시드 1종, 2026-08-03 갱신 — `rephrased_v0`가 발문 위생 게이트 확장으로 483→429). `rephrased_v0`만 발문 표현에 LLM 사용(수치·정답·`distractor_map`은 코드 소유). 표본 검수 5/6 PASS(`generated_v0` Wilson 상한 1.11%·`conceptual_v0` 1.33%·`misconception_mc_v0` rotation-2 1.33%·`rephrased_v0` 전수 감사 0.63%) — `killer_v0`는 코퍼스 크기(120)가 표본 게이트 min-n(200) 미만이라 게이트가 구조적으로 판정 불가(품질 실패 아님·코퍼스 확장 대기) (데이터 카드: `problem_bank_corpus_v1.md`) |
| 와이매스 문제은행 코퍼스 `probability_finite_v0` (자체 저작) | 자체 저작 | ✅ | ✅ | ✅ | 확률(유한 전수형) 동등문제 34건 — S4-13 SymPy 불가 영역 대체 검증 스택 파일럿 산출물(`harness/finite_probability_batch.py` + `l3/equivalent/finite_probability_skeleton_generator.py` 생성). 전 34건 `license=WHYMATH_GENERATED`·`source_type=자체생성`(예외 0, 실측). SymPy 불가 영역이라 대체 검증 스택(S4-13 수용 게이트)이 정확성 게이트를 대신함. 평가원·EBS·검정교과서 본문·문항·풀이·그림 복제 0. 위 6종 표에 포함되지 않은 7번째 코퍼스(2026-07-29 소급 provenance 작성) (출처: `data/corpus/problem_bank_probability_finite_v0/_provenance.json`) |
| 와이매스 문제유형 그래프 `problem_type_graph_v1` (자체작성) | 자체 저작 | ✅ | ✅ | ✅ | cognitive-action 문제유형 택소노미 — 유형 17종·계열(family) 6종·참조 스킬 25개. 평가원 기출 문항 본문 미포함(자체작성 택소노미). 결정론(동일 입력 sha256 재변환 시 byte 동일 산출) — 검증 통과(errors 0·warnings 0) (출처: `data/corpus/problem_type_graph_v1/_provenance.json`) |
| **평가원 기출 (본문·문항)** | 저작물 | ❌ | ❌ | — | **상업 영리금지** — 구조 메타만 + 자체 동등문제 대체 (아래 §정책) |
| 평가원 기출 (구조 메타) | 사실정보 | ✅ | ✅ | ✅ | 단원·코드·문항번호만 |
| **EBS 교재 (본문·문항)** | 저작물 | ❌ | ❌ | — | **상업 영리금지** — 단원 매핑 메타만 |
| EBS 메타데이터 | 사실정보 | ✅ | ✅ | ✅ | 단원·차시명만 |
| **검정 교과서 본문** | 출판사 | ❌ | ❌ | — | **절대 금지** |
| 검정 교과서 목차 | 사실정보 | ✅ | ✅ | ✅ | 단원명만 |
| **학원·인강 자료** | 사기업 | ❌ | ❌ | — | **절대 금지** |
| KMS·교육학회지 | 학술 | ⚠️ | ⚠️ | ✅ | 인용 범위 |
| **KICE 평가기준·성취수준 개발 연구 (본문 서술)** | 미확인 | ❌(보류) | ❌(보류) | — | 표지 "무단 복제를 금함" 문구만 확인·공공누리 유형 텍스트 미발견(로고 이미지일 가능성, 미확인≠부재). 확인 전까지 본문(평가기준 설명·성취수준 서술·예시 문항) 반입 보류 |
| KICE 평가기준·성취수준 구조 메타 (코드·단원 계층·등급 라벨) | 사실정보/식별자 | ✅ | ✅ | ✅ | 성취기준·평가준거 코드·단원 제목·A~E 등급 라벨만(서술 비포함) (데이터 카드: `achievement_criteria_v1.md`) |

## 글로벌 자원

| 자원 | 라이선스 | 상업 OK | 가공 OK | 출처 표시 | 비고 |
|---|---|---|---|---|---|
| CK-12 | CC BY-NC | ❌ | ✅ | ✅ | 비상업만 |
| OpenStax | CC BY 4.0 | ✅ | ✅ | ✅ | 자유 |
| Siyavula | CC BY (**명시 표기 자료 한정**) | ⚠️ 조건부 | ⚠️ 조건부 | ✅ **문구 지정** | 사이트 기본값은 **closed copyright·All rights reserved** · CC 표기가 *붙은* 자료만 재사용 가능 · 귀속 = 저자명 + `From www.everythingmaths.co.za`\|`From siyavula.com` · 상표·로고·URL·특허·디자인은 CC 대상 아님 (아래 각주) |
| LibreTexts | CC BY-SA | ⚠️ | ⚠️ | ✅ | **SA(B등급)** — AI 학습 위험(가중치 SA 전염), 서비스 콘텐츠만 |
| NRICH | 자체 | ⚠️ 협상 | ❌ | ✅ | Cambridge MMP |
| Mathigon | 비상업 | ❌ | ❌ | — | 영감만 |
| AoPS Wiki | CC BY-SA | ⚠️ | ⚠️ | ✅ | **SA(B등급)** — 학습 직접사용 위험; *사실·구조만 추출+자체생성* 우회 |
| Khan Academy | CC BY-NC-SA | ❌ | ❌ | — | **NC+SA 이중독성(C등급)** — 완전격리 |
| 3Blue1Brown | YouTube 표준 | ❌ | ❌ | — | 영감만 |
| Illustrative Math | **판(edition)별 상이** — 초판 K–12 Math(© 2019–2021)=CC BY 4.0 · **v.360**(© 2024·TK © 2025)=**CC BY-NC 4.0** | ⚠️ **초판만** | ⚠️ 초판만 | ✅ **3조건 전부** | **v.360은 상업 이용 금지**(accessim.org 배포분) — 우리는 상용 서비스라 초판(im.kendallhunt.com)만 사용 가능 · 귀속은 ①저자 표시 ②**라이선스 하이퍼링크** ③**변경 여부 표시** 3조건이며, 흔히 쓰는 한 줄 문구는 약관이 "suggested"라 부르는 **예시일 뿐 3조건을 대체하지 않는다** (아래 각주) |

> **적용 범위 단서 (LIC-05 · 2026-09-07)** — 라이선스명만 적으면 *사이트 전체가 그 라이선스*로 읽힌다.
> 아래 두 소스는 약관 원문이 범위를 한정하며, 종전 표기는 그 한정을 담지 못했다.
>
> **Siyavula** (증적 `data/licenses/snapshots/siyavula/45723a589bd0a69d.html` · sha256 `45723a58…de2b` ·
> 2026-08-31T01:36:01Z 수집 · §Copyright and Related Rights):
> - "**Some** material on the site is licensed under a Creative Commons Attribution Only License"
> - "**Only material that is clearly marked** with a Creative Commons license can be re-used without permission"
> - 귀속 요건: 저자명 + `"From www.everythingmaths.co.za"` 또는 `"From siyavula.com"`
> - CC는 **저작권만** 다루며 "does not grant any rights over trademarks, brands, Uniform Resource Locators,
>   patents, designs" — 리믹스에 로고·브랜드마크를 넣을 수 없다(귀속 요건 이행 목적 제외)
> - **사이트 기본값은 CC가 아니다**: 푸터가 "except where otherwise noted, this site is covered by a
>   **closed copyright license. All rights reserved.**"라고 선언한다. 즉 CC BY가 원칙이고 예외가 닫힌 것이
>   아니라, **닫힌 것이 원칙이고 CC BY가 예외**다 — 종전 '자유' 표기와 방향이 반대였다.
>
> **Illustrative Mathematics** (증적 `data/licenses/snapshots/illustrative-mathematics/46845eab5092f74c.html` ·
> sha256 `46845eab…b2df` · 2026-08-31T00:55:08Z 수집 · §7 License):
> - §7.1 초판 `IM® K–12 Math`(© 2019–2021 · im.kendallhunt.com) = **CC BY 4.0** — 상업 이용 명시 허용
> - §7.2 2판 `IM® TK–12 Math v.360`(© 2024 · TK © 2025 · accessim.org) = **CC BY-NC 4.0** —
>   "Commercial use of the IM v.360 curriculum materials and name … **is prohibited** without prior
>   written permission". 또 그 CC는 "governs the IM v.360 curriculum **only** and not other IM Products".
> - **귀속은 3조건이다**(2026-09-07 PR #1029 Codex P2 지적 수용 — 최초 판에서 예시 문구만 적었다):
>   "users are free to share and adapt the materials for any purpose, including commercially,
>   **with appropriate attribution to the author**, Illustrative Mathematics, **hyperlink to the
>   license**, and **indication if changes were made**". 이어지는 한 줄 문구
>   ("Based on IM® K–12 Math authored by Illustrative Mathematics and licensed under CC BY 4.0.")는
>   원문이 **"A suggested attribution"**이라 부르는 *예시*이며, 그것만 표기하면 ②하이퍼링크와
>   ③변경 표시가 빠진다. 실제 재사용·가공 시 세 조건을 모두 이행한다.
>   (일반론으로도 CC BY 4.0 §3(a)가 라이선스 링크와 변경 표시를 요구하므로, 예시 문구는 **하한이지
>   상한이 아니다** — Siyavula의 지정 문구에도 같은 원리가 적용된다.)
> - 우리는 **상용 서비스**이므로 v.360은 결정 우선순위 #2(법적 준수)상 사용 불가다. 이 구분은
>   `docs/legal/copyright_guide_v2.md`에는 이미 있었으나 **"반드시 확인"이라고 선언한 이 매트릭스에는
>   없었다** — 정본이 파생 문서보다 덜 정확한 상태였다.
>
> **③ 동일 유형 전수 재점검 — 방법과 한계**: 스냅샷 **20/20 전건**(디렉터리 20 · 본문 20건)을 두 번
> 훑었다. 1차 = 범위 한정 어구 13종(`some material`·`only material`·`clearly marked`·`unless otherwise`·
> `except where`·`not all`·`portions of` 등), 2차 = 범위 부정 어구(`does not apply`·`excluding`·
> `all rights reserved` 등)가 **라이선스명 ±300자 안에 함께 오는 경우**만. 걸린 것은 위 2건이고,
> 나머지 히트는 MIT 본문의 `substantial portions of the software`(gsm8k·math-hendrycks·prm800k)와
> 데이터셋 *내용*의 우연 일치(numinamath-tir·omnimath)로 전건 오탐이었다.
> **한계**: 어구 사전 기반이라 *다른 표현*으로 범위를 한정한 소스는 못 본다 — "내가 쓴 방법으로는 2건"이
> 정확한 진술이고 "20곳 중 2곳뿐"은 그보다 강한 주장이다.

## LLM 학습 데이터셋

| 자원 | 라이선스 | 상업 OK | 비고 |
|---|---|---|---|
| NuminaMath-CoT | Apache 2.0 | ✅ | 자유, 860k 문항 |
| PRM800K | MIT | ✅ | 단계 검증(PRM) 80만 스텝 |
| PhET 시뮬레이션 | CC BY | ✅ | 상호작용 시각화 |
| Metamath | CC0 | ✅ | 형식 증명 (퍼블릭 도메인) |
| MathNet (MIT 2026) | 확인 필요 | ⚠️ | 30,000+, 47개국 |
| OmniMath | 공개 | ✅ | 4,428 문항 |
| miniF2F | **폴더별 상이** — lean=Apache 2.0 · isabelle=Apache 2.0 · metamath=MIT · hollight=FreeBSD | ✅ | 488 Lean 문항은 **Apache 2.0**(MIT 아님) · 저장소 LICENSE 파일 부재 → README §License가 선언 원문 |
| OlymMATH | 공개 | ✅ | 올림피아드 |
| Mathlib4 | Apache 2.0 | ✅ | Lean 형식화 |
| NuminaMath-TIR | Apache 2.0 | ✅ | 72,540 도구통합추론(AIMO 우승셋) |
| GSM8K · MATH | MIT | ✅ | 표준 벤치마크·학습 |
| OpenMathInstruct-1 | NVIDIA License | ✅ | A- 상업 허용 |
| DLMF | US Gov Work | ✅ | NIST 특수함수(퍼블릭 도메인, A+) |

*전체 21종 카탈로그·레코드 수·등급: `docs/data/dataset_catalog_v4.md`.*

> **miniF2F 표기 정정 (LIC-04 · 2026-09-07)** — 종전 표기는 `MIT` 단일이었으나 실측상 불완전하다.
> 저장소에 `LICENSE` 파일이 **없고**(2026-08-30 수집 시 404), 라이선스 선언의 원문은 README의
> 폴더별 절이다: `lean`=Apache License · `isabelle`=Apache License · `metamath`=MIT ·
> `hollight`=FreeBSD. 증적 = `data/licenses/snapshots/minif2f/9b6de2b0a301c318.txt`
> (sha256 `9b6de2b0…f21a` · 2026-08-30T16:44:06Z 수집 · README §License 절 5행).
> 우리가 실제로 쓰는 488 Lean 문항은 **Apache 2.0**이므로 종전 `MIT` 표기는 *하필 우리가 쓰는
> 폴더에서* 틀렸다.
>
> **소비 판정 영향: 없음.** 네 라이선스(Apache 2.0·MIT·FreeBSD) 모두 상업 이용 허용·copyleft
> 부재·SA/NC 조건 부재라 Tier1 포함 여부와 등급 **A**는 종전과 동일하다. 다만 배포·재배포 시
> **고지 의무의 원문이 폴더마다 다르다**는 점만 새로 성립한다(Apache 2.0은 NOTICE·변경 고지,
> MIT·FreeBSD는 저작권 고지 보존).
>
> ⚠ 이 태스크(LIC-04)의 제목은 폴더를 **3종**으로 적었으나 스냅샷 실측은 **4종**이다 —
> `isabelle`(Apache License)이 빠져 있었다. 같은 오류가 문서 **4곳**에 있었고 전부 정정했다:
> 이 표 · `license_snapshot_archive.md` 14행 · `01_data_foundation.md` L1 데이터셋 표 ·
> `copyright_gradient.md` 등급 1 표. 코드측(`scripts/ops/license_snapshot_archiver.py`의
> `license_label="MIT"`와 폴더 3종 주석)은 **아직 남아 있으며 `LIC-08`이 소유한다** —
> 그 라벨은 `meta.json`에 기록되므로 스냅샷 메타 재생성 판정이 함께 걸려 문서 정정과 분리했다.
> `copyright_guide_v2.md`의 "miniF2F / PutnamBench (MIT/Apache)"는 두 벤치마크를 묶은 표기라
> 거짓이 아니므로 **의도적으로 두었다**.

## L5 OCR (검출·인식 모델)

모두 *공개 오픈소스·로컬 ONNX*만 사용한다(미성년자 프라이버시·외부 OCR 미사용, 2026-05-28 결정). **상용 SaaS이므로 AGPL-3.0 모델은 금지**(네트워크 §13 소스공개 의무 — 결정 우선순위 #2).

| 자원 | 라이선스 | 상업 OK | 용도 | 비고 |
|---|---|---|---|---|
| rapidocr-onnxruntime | Apache 2.0 | ✅ | 텍스트 검출·한국어 인식 (Phase A) | PaddleOCR PP-OCR ONNX 포팅 |
| rapid-latex-ocr | Apache 2.0 | ✅ | 수식→LaTeX 경량 인식 (Phase A) | LaTeX-OCR ONNX |
| **rapid-layout (PP 계열)** | Apache 2.0 | ✅ | **MFD 수식 영역 검출 (Phase B)** | PP-StructureV2 CDLA('Equation')·PP-DocLayout('formula') PicoDet·순수 ONNX·torch 불요 |
| **ultralytics (YOLOv8 / DocLayout-YOLO)** | **AGPL-3.0** | ❌ | (MFD 대안 — 미사용) | **금지** — 코드에서 model_type 거부(`MfdDetector`). rapid-layout PP로 대체 |
| TexTeller (OleehyO/TexTeller) | Apache 2.0 | ✅ | 고정밀 수식 인식 (Phase C·동작) | transformers·로컬·가중치 라이선스 배포 시 재확인 |
| Qwen3-VL | Apache 2.0 계열 | ✅ | 멀티모달 수식 (Phase C·동작) | 로컬·**L3 라우터 경유 필수**(직접 Ollama 금지)·VISION 패밀리 |

> MFD(수식 영역 검출)는 **rapid-layout PP 계열(Apache-2.0)**로만 구현한다. rapid-layout가 함께 번들하는 ultralytics 기반 모델 타입(`yolov8*`/`doclayout*`)은 AGPL이라 `MfdDetector.__init__`이 `RuntimeError`로 거부하고, `Settings.ocr_mfd_model_type` Literal도 PP 계열만 허용한다(이중 차단).

## 사용자 데이터

| 종류 | 활용 가능 | 조건 |
|---|---|---|
| 학생 풀이 (텍스트) | ⚠️ | 명시적 동의 |
| 학생 풀이 (이미지) | ⚠️ | 동의 + 익명화 |
| 채팅 로그 | ⚠️ | 동의 + 분리 저장 |
| 학습 통계 (집계) | ✅ | 익명화·집계만 |
| 부모 보고서 | ⚠️ | 학생 동의 (14세+) 또는 부모 동의 |

## 절대 금지 목록

1. ❌ 검정 교과서 본문·예제·풀이 복제
2. ❌ EBS 영상 자막·교재 본문 수집
3. ❌ **평가원 기출 본문·문항 복제·변형 배포** (상업 — 구조 메타데이터만 허용)
4. ❌ 학원·인강 자료 (메가스터디·시대인재·콴다·이투스 등)
5. ❌ 출판사 풀이집·문제은행 *복제*
6. ❌ 미성년자 PII 무단 수집·분석·외부 공유
7. ❌ 사용자 데이터 동의 없이 *모델 학습*

## 저작권 가이드 v2.0 — EBS·평가원·동등문제 정책 (2026-05-28)

> 출처: **저작권 종합가이드 v2.0**(2026-05-27) — 원문 `docs/legal/copyright_guide_v2.md`. 실제 데이터 백본 카탈로그 `docs/data/dataset_catalog_v4.md`(MathScope v4, 21종). 본 절은 결론 요약이며 *변호사 최종 검토 전제* (CLAUDE.md 데이터·저작권 §).

### 왜 EBS·평가원 본문을 상업적으로 못 쓰나
- 저작권법 **§32(시험문제로서의 복제)**는 입학·자격 시험 등에 타인 저작물 이용을 허용하나, **단서에 "영리 목적인 경우 제외"** — 상업 앱(WhyMath)엔 적용 불가.
- §25(학교교육 목적) 역시 *교육기관* 대상이라 상업 서비스엔 해당 없음.
- 평가원 기출·EBS 교재의 *본문·문항*은 저작물이며, 무단 복제·변형 배포는 **§136(권리침해죄)·§140(영리·상습 비친고죄 — 합의해도 검찰 직권기소)** 형사 책임 + **§125-2 법정손해배상**(영리·고의 1건당 최대 5천만 원). DB 추출은 **§93(DB제작자권)** 별도 침해. 가이드는 **2024.8 대법원(KICE 사용료 지급 의무)**로 보강.
- 결론: **상업 활용 불가**. 단, *단원명·교육과정 코드·문항번호* 등 **사실정보(구조 메타데이터)**는 인용 가능.

### 대체 전략 — 자체 생성 동등문제
- EBS·평가원 *본문 대신*, **성취기준·시그니처 패턴 기반으로 자체 생성한 동등문제**를 학생에게 노출 (킬러 30번 포함).
- 엔진: 빌드타임 사전생성 `whymath_backend/l3/pregenerate` + **SymPy 산술 검증 게이트**(거짓 등식 시드 탈락) + 후속 PRM/사람검수.
- 평가원/EBS는 *어떤 단원·코드에 대응하는가*(매핑)만 메타로 보유 → 자동 커리큘럼 정렬에 활용, 본문은 미보유.

### 법적 안전조합 (MVP 콘텐츠 백본)
- **무제한·영리허용**: NCIC 성취기준(§7 사실정보)·공공누리 AI유형(2026-01)·AIHub 수학셋.
- **LLM 학습·예시**: NuminaMath(Apache)·PRM800K(MIT)·PhET(CC BY)·Metamath(CC0)·Lean.
- 이 조합만으로 Phase 1(고3 수능) 콘텐츠를 충족하는지 — **변호사 검토 권장**.

### 등급 체계·실제 백본 (MathScope v4)
- 등급: **A+**(NCIC 성취기준·Common Core·DLMF·Metamath·PISA/TIMSS) · **A**(GSM8K·MATH·OpenStax·NuminaMath 1.5/CoT/TIR·PRM800K·OlympiadBench·miniF2F·Mathlib4·PhET 등) · **A-**(UK·ACARA·AIHub·OpenMathInstruct, 조건부) · **B=SA**(위험) · **C=NC**(영리차단) · **D=독점**(EBS·검정교과서·KMO).
- **실제 수집 백본 = A-/A/A+ 21종·약 4M 레코드, B/C/D/E 0건**(EBS·평가원·검정교과서 미포함) — `docs/data/dataset_catalog_v4.md`. 재검토 "법적 안전조합" 교정과 정합.

### SA(ShareAlike) 함정과 우회
- SA(CC BY-SA: AoPS·LibreTexts·Wikipedia·StackExchange·OpenWebMath) 자료를 **AI 학습에 직접 쓰면 모델 가중치를 SA로 공개**해야 한다는 해석 가능 → SaaS 모델 붕괴 위험. 보수적 IP 변호사는 직접 학습 비권장.
- **우회(가이드 §6.3 Tier 2)**: Feist v. Rural·대법원 2000다61664 — *사실(facts)은 저작권 보호 대상 아님*. SA·EBS·평가원에서 **수학적 사실·구조만 추출하고 표현은 Claude/Qwen3로 자체 생성** → 동등문제 전략의 일반 원리.

### AIHub 4조건 / NCIC 구분
- **AIHub**(71718·71716·71859·479·71518): 영리 명문 허용 — ① 출처표시 "한국지능정보사회진흥원 사업결과"(2차 저작물도) ② 국외반출·국외법인 별도합의 ③ **데이터셋 재판매·양도·대여 금지**(AI 모델 형태 서비스는 가능) ④ 위법 시 환수.
  - **② 국외반출의 기계적 집행 지점(EOS-59)**: 우리 클라우드 LLM 프로바이더(Anthropic 등)는 **국외 법인**이므로, AIHub 유래 자료를 클라우드 티어로 보내는 것은 별도합의 없는 *국외 이전*이다. 이 조건은 산문 규칙이 아니라 라우터가 시행한다 — `l3/data_export_policy.guard_data_export`가 `RoutingRequest.data_licenses`를 읽어 반출 불가·미확인 자료의 클라우드 승급을 **LOCAL로 강등**한다(권리 판정 정본은 `l1/rights/permission_map._AIHUB_OPEN.export=False`, 설계는 `03a_l3_router_design.md` §D.5). 호출부가 등급을 실제로 채우는지는 CI `backend` 잡의 `scripts/ops/check_routing_data_grade.py`가 강제한다.
  - **2026-09-01 실측**: `data/corpus/*/_provenance.json` 전 27개 코퍼스의 `pool`이 `whymath-original` — 현재 적재된 AIHub 유래 자료 **0건**. AIHub 자료가 저작 파이프라인 입력이 되는 시점에 `l3/data_grade_defaults.SELF_AUTHORED_CORPUS`에 `AIHUB_OPEN`을 더하면 저작 경로 전체가 자동으로 국내 전용이 된다(호출부 수정 0).
- **공공누리 AI유형**(2026-01-28): AI유형 마크 자료는 *데이터 재판매만 금지*, **학습된 모델의 상업 이용은 허용**.
- **NCIC 구분**: 성취기준 *코드·고시 본문* = §7 보호대상 아님(무제한) ↔ NCIC *해설서·연구보고서* = 공공누리 2유형(영리 차단, C등급). 혼동 금지.

## 결정 트리

```
질문: 이 자원을 사용해도 되나?

1. 한국 검정교과서 본문인가? → ❌ STOP
2. 학원·인강 자료인가? → ❌ STOP
3. 사용자 데이터인가? → 동의 절차 확인 → 조건부 ⚠️
4. 라이선스가 명시되어 있나?
   - 명시 X → ⚠️ 사용 안 함이 기본
   - CC BY → ✅ 출처 표시
   - CC BY-NC → ⚠️ 비상업만
   - CC BY-SA → ⚠️ SA 전염성 — AI 학습 직접사용 위험, 사실만 추출+자체생성
   - Apache 2.0 / MIT → ✅ 자유
   - 사기업 독자 → ⚠️ 협상 필요
5. 상업적 활용 가능한가?
   - Yes → ✅
   - No → ⚠️ 영감만, 직접 사용 X
6. 가공 가능한가?
   - Yes → ✅
   - No → ⚠️ 인용 범위 내
```

## 출처 표시 표준

### 인앱 표시
모든 콘텐츠 출처 사용자에게 보이게:
```
"이 문제는 [소스]에서 영감을 받았어요"
"풀이 참고: [성취기준 코드, EBS 수능특강 X단원]"
```

### 내부 로그
모든 콘텐츠 메타데이터에 출처 기록 (사용자 미노출이라도):
```yaml
content_id: "..."
sources:
  - type: "inspiration"
    url: "..."
    license: "..."
  - type: "direct_reference"
    url: "..."
```

## 회색 영역 (협상 가능)

다음은 *현재 사용 X*이지만 *향후 협상 가능*:

- **NRICH (Cambridge MMP)**: 학술 협력 형태로 라이선스 협상
- **EBS·평가원**: 본문·문항 상업 사용 불가(가이드 v2.0). 공식 제휴 협상 시에만 본문 가능 — 그 전까지 *자체 동등문제*로 대체
- **AoPS Korea**: 한국 진출 협력?
- **검정교과서 출판사**: B2B 영업 시 교과서 매핑 *공식 제휴*

회색 영역은 *Phase 3+* 시점, 사용자·매출 검증 후 진행.

## 약관 스냅샷 아카이브 (LIC-02)

이 매트릭스가 의존하는 외부 소스 약관은 **확인 시점 원문**을 보관한다(변경 후 소급 재구성 불가 — 저작권 K4).

- 규약·Tier1 목록(매트릭스 실측 **20곳** — 가이드 "14곳" 선언 대조 보고 포함): `docs/data/license_snapshot_archive.md`
- 스크립트: `scripts/ops/license_snapshot_archiver.py` · 보관소: `data/licenses/` (append-only 감사로그 + content-addressed 스냅샷)
- 주기 재수집(cron)은 OPS-56 축 후속 — 현재는 수동 실행(아래 분기 점검 시 함께)

## Review 주기

- 매 분기 1회 라이선스 점검
- 새 자원 추가 시 *즉시* 카드 작성
- 라이선스 변경 모니터링 (특히 NRICH·MathNet)

---

**최종 갱신**: 2026-08-30 (LIC-02 약관 스냅샷 아카이브 절 추가 — 매트릭스 본문 무변경) · 이전: 2026-05-28 (저작권 가이드 v2.0 *원문*·MathScope v4 카탈로그 반영 — EBS·평가원 영리금지·법적 안전조합·SA 함정·AIHub 4조건·동등문제 전략). 원문: `docs/legal/copyright_guide_v2.md` · `docs/data/dataset_catalog_v4.md`. 상세 MEMORY.md 2026-05-28.
