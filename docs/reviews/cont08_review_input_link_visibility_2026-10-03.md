# CONT-08 — 크로스워크 역조회 콘텐츠의 검수 입력 가시성 · 택1 판정

> 판정 기준: main `5e9ce568` (CONT-06 #1427 착지 후) · 2026-10-03 · 태스크 `CONT-08-crosswalk-lookup-review-input-mapping-visibility`

## 0. 요약

- **판정: ⓐ 채택 + 승격 도구에서 집행.** 검수 입력(배치 프롬프트·감사 리포트)에 연결 원자·명칭·크로스워크
  confidence를 싣고, 승인 라벨에 연결 승인(`link_approved`)을 **별도 필드**로 받는다. 받기만 하면 아무도
  읽지 않는 장식이므로, `reviewed`를 찍는 유일한 관문 `concept_content_review_apply`가 연결 원자가 있는
  행의 `link_approved: true` 명시를 요구한다(없으면 전체 거부·exit 1).
- 스키마·마이그레이션·공급 게이트(`l4/content_supply.py`) 변경 **없음**.
- 연결 변별력은 프로브로 잰다: 같은 깨끗한 본문에 엉뚱한 원자를 붙인 행은 거절, 맞는 원자를 붙인 행은 승인.
  배치 CLI 게이트가 두 방향을 따로 집행한다.

## 1. 실측 (이 판정의 전제)

| 사실 | 측정 |
|---|---|
| 크로스워크 행 수·검수 상태 | 437행 전건 `ai_estimated`, confidence 0.5~0.9 |
| 콘텐츠 `code` ↔ 크로스워크 `concept_id` | **교집합 0건** — 콘텐츠는 `N1`형(`src_id`), 크로스워크는 `math.addition...`형. 구 437 `graph.json`의 `concept_id→source_id` 다리로 잇는다(`l1/concept_atom_crosswalk/transfer.py`) |
| 다리를 통한 연결 | 437/437 조인, 연결 원자 명칭 미상 0건 |
| 연결 원자 수 분포 | 3개 421행 · 4개 8행 · 6개 3행 · 5개 2행 · 9개 2행 등(전건 ≥1) |
| 기존 검수 입력 | 배치 프롬프트·승인 라벨 모두 연결 원자·신뢰도 **없음** |

콘텐츠 `code`로 크로스워크를 바로 찾으면 0건이라 "연결 없음"으로 읽힌다. 새 모듈은 공급 경로의 도출 규칙을 그대로
재사용하고, 테스트가 두 결과의 일치를 단언한다(`test_atom_codes_equal_the_supply_path_derivation`).

**로더를 `l1/concept_atom_crosswalk/`에 둔 이유**: 처음엔 `harness/`에 뒀는데 CI의 구 437 소비 가드
(`test_legacy_snapshot_governance` — 구 437 `graph.json`을 읽는 모듈은 화이트리스트 안에만)가 걸렸다.
가드를 확장하는 대신 이미 화이트리스트인 크로스워크 패키지로 옮겼다 — 도출 규칙(`transfer`)과 같은 자리라
응집도도 좋고, 가드는 그대로다. 새 모듈은 EOS 기능 인벤토리(`WM-E-103`·`WM-O-910`)에도 귀속했다.

## 2. 택1 판정

- **ⓐ(입력 확장 + 연결 승인 라벨 분리) — 채택.** 연결 원자·신뢰도를 검수자(LLM·사람)에게 보이고, 승인을
  콘텐츠 판정(`passed`)과 별개 축으로 받는다.
- **ⓑ(역조회 경로 한정 별도 연결 검수 상태 + `reviewed`와 AND) — 미채택.** DB 컬럼 추가·마이그레이션과
  공급 게이트(`resolve_concept_dsl`) 변경이 필요해 범위가 크다. ⓐ를 승격 도구에서 집행하면 같은 문(門)을
  스키마 변경 없이 닫는다. 연결 상태가 공급 시점에 실시간으로 필요해지면 그때 ⓑ를 재판정한다.
- **ⓒ(위험 수용) — 미채택.** 승격 이후 연결이 틀린 콘텐츠가 엉뚱한 원자 목표에 나가는 위험이 실재하고
  (CONT-06 §3), 막는 비용이 낮다.

### 2.1 구현 규칙

| 규칙 | 내용 |
|---|---|
| 연결 출처 | `l1/concept_atom_crosswalk/content_link.py` — 공급 경로와 같은 도출(`harness/concept_content_link_context.py`는 표시용 창구). 조인 실패(`concept_id` 부재·한 행에 크로스워크 중복)는 `ValueError`, 파일 부재는 `FileNotFoundError`. 빈 결과로 대체하지 않는다 |
| 검수 입력 | 프롬프트에 `연결 원자: 코드(명칭)[대표] … — 크로스워크 ai_estimated(기계 추정·미검수, confidence=…)` 한 줄. 연결이 없으면(대학·unmapped) 줄 자체가 없다 |
| 응답 축 | rubric `link_ok`(불리언) — `passed`와 별개. 콘텐츠가 맞아도 연결이 틀리면 `link_ok=false` |
| 모른다 ≠ 맞다 | 연결을 줬는데 `link_ok`를 안 답하거나 불리언이 아니면 **승인이 아니다**(`link_approved=False`, `link_answered=False`로 구별해 기록) |
| 감사 리포트 | JSONL에 `link_atoms`·`link_confidence`·`link_answered`·`link_approved`·`link_probe` 추가 |
| 승격 게이트 | 승인(`reviewed`) 라벨 중 연결이 있는 행은 `link_approved: true` 필수. 불리언만 받는다(문자열 `"true"`·숫자 `1`은 승인 아님). 위반 1건이면 전체 거부 |
| 대학 행 | 연결이 없어 해당 없음 |

## 3. 잔여 위험 (정직한 한계)

- **`link_approved`는 사람(검수자)의 확인 표시이지 기계 증명이 아니다.** 라벨을 쓰는 사람이 연결을 안 보고
  `true`를 적는 것은 코드로 막을 수 없다(서명 위조와 같은 부류). 이 변경이 하는 일은 "연결을 보이게 하고,
  명시적으로 한 번 더 말하게 하는 것"이다.
- **LLM의 `link_ok`는 보조 신호다.** 프로브 2건(엉뚱한 원자 1·맞는 원자 1)이 변별한다는 것은 rubric이
  *극단적인* 연결 오류를 거절한다는 뜻이지 미묘한 오연결(인접 원자)을 잡는다는 뜻이 아니다. 인접 원자 오연결은
  재지 않았다.
- 승격 이후 공급 시점에는 연결 승인 여부를 알 수 없다(DB에 상태가 없음 — ⓑ 미채택의 대가). 승격이 곧 연결
  승인의 기록이라는 가정에 선다.
- 이미 승격된 행은 없다(437 전건 `ai_estimated`) — 소급 정리는 해당 없음.

## 4. 변별력

### 4.1 테스트

| 파일 | 내용 |
|---|---|
| `tests/backend/harness/test_concept_content_review_batch_link.py` (신규 35건) | 로더 실 코퍼스 437 조인·공급 경로 도출과 일치·조인 실패 3종·명칭 미지어냄 · 프롬프트 연결 줄(실 코퍼스 `N1`의 원자 4개) · `link_ok` 파싱 · 무응답≠승인 · 프로브 접두사 비충돌 · 배치 CLI 4모드(correct/approve_all/reject_all/silent) |
| `tests/backend/harness/test_concept_content_review_apply.py` (+11건) | 연결 승인 없음 → 거부 · false → 거부 · true → 승격(성공 방향 대조군) · 연결 없는 행 해당 없음 · 1건 누락이 전체 거부 · 비승격 라벨 미검사 · 불리언만 인정 · 연결 로드 실패는 예외 · 승인 행 없으면 연결을 읽지 않음 · 실 코퍼스 437행 전수 · CLI exit 1 |
| 기존 테스트 | 실 코드 `N1`을 연결 승인 없이 승격하던 **5건이 새 게이트에 걸려 실패**했고(게이트가 실제로 동작한다는 첫 증거) `link_approved`를 더해 갱신했다. 서명 검사만 보려는 2건(AI 자기승인·1건 미서명)도 연결 위반이 섞이지 않게 같이 갱신. 배치 쪽은 `_VerdictProvider`에 연결 응답 모드를 더했다 |

### 4.2 뮤테이션 (스크래치 하네스 · 주입 실재 단언 `mutated != original` · 백업 `cp` 원복 + sha256 대조)

| # | 주입 | 검출한 테스트 |
|---|---|---|
| M1 | 승격 게이트의 연결 승인 검사 제거 | `test_reviewed_without_link_approval_is_refused` |
| M2 | `None`(미표기)을 승인으로 취급 | 같은 테스트 |
| M3 | 연결 로드 실패를 삼키고 빈 연결로 진행 | `test_unreadable_links_fail_loudly_instead_of_opening_the_gate` |
| M4 | 라벨의 비불리언을 truthy로 승인 | `test_label_file_accepts_only_a_real_boolean` |
| M5 | 프롬프트에서 연결 줄 제거 | `test_prompt_with_link_shows_atoms_names_primary_confidence_and_machine_estimate` |
| M6 | 무응답을 승인으로 취급 | `test_silence_is_not_approval` |
| M7 | 프로브 코드 접두사를 콘텐츠 축(`__INJECT`)과 충돌시킴 | `test_content_pass_and_link_are_independent_axes` |
| M8 | 배치 게이트의 "엉뚱한 원자 승인" 검사 제거 | `test_approving_everything_is_caught_as_missed_wrong_link` |
| M9 | 배치 게이트의 "맞는 원자 미승인" 검사 제거 | `test_rejecting_everything_is_caught_as_over_sensitive` |
| M10 | 파서가 문자열 `"true"`를 승인으로 인정 | `test_link_ok_is_taken_only_as_a_real_boolean` |
| M11 | 로더가 다리 조인 실패를 건너뜀 | `test_missing_bridge_entry_raises` |
| M12 | 로더가 명칭 없는 원자 코드를 명칭으로 지어냄 | `test_unknown_atom_name_is_left_out_not_invented` |

12/12 RED · 원복 sha256 동일.

## 5. 이 판정이 바꾼 것 / 바꾸지 않은 것

- 바꿈: 검수 배치 프롬프트·rubric·감사 리포트·게이트, 승격 도구 라벨 형식·게이트, 연결 로더 신설.
- **운영 영향**: `G-kg02` 승격 회차(Kiki 서명 대기)의 승인 라벨은 이제 K-12 행마다 `link_approved: true`를
  명시해야 한다. `KG-02` acceptance ⑦에 기록했다.
- 바꾸지 않음: 공급 게이트·DB 스키마·크로스워크 코퍼스. 라이브 LLM(Ollama)으로 `link_ok` 변별을 재지
  않았다 — 이 PR의 변별력 측정은 가짜 provider로 *집행 경로*를 시험한 것이다.
