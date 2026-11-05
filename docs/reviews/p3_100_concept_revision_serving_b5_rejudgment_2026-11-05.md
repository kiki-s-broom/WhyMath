# P3-100 개념 수정판 서빙 연결 — EOS-50 축 판정 B5 재판정

판정 기준: main `036286a1` + 이 PR(브랜치 `claude/elegant-goldberg-wtocxg`)

- 태스크: `P3-100-concept-revision-serving` (출처: P3-17 통합 판정 Gate C · 성공 기준 Q2)
- 재판정 대상: `docs/reviews/eos50_publish_gate_axis_judgment_2026-09-29.md` §1 D행·B5·§6 제8조 행
- 재판정 사유: B5가 스스로 적은 조건이 성립했다 — "`concept_version`을 서빙 경로가 읽기 시작하면(= D가 학생 노출에 닿으면) 헌법 제8조에 따라 이 판정을 다시 한다."

---

## 1. 무엇이 바뀌었나

| 항목 | 이전(EOS-50·P3-26) | 지금(P3-100) |
|---|---|---|
| 기존 개념의 판 발행 | 판 상태·발행 포인터만 움직임. 개념 행 그대로 → 학생 화면 불변 | 판 payload 11필드를 개념 행에 **투영**(`publish_gate._project_payload`) → 학생 조회(`GET /v1/concepts/{id}` 등 개념 행을 읽는 모든 경로)에 닿음 |
| 롤백(restore) | 포인터만 직전 발행본으로 | 복원된 판 payload를 개념 행에 다시 투영 |
| 폐기(deprecate) | 포인터 비움 | 그대로(투영 없음 — 개념 행은 마지막 발행 내용 유지) |
| 신규 개념 첫 발행(P3-26) | `_materialize_concept`가 필드를 직접 옮김 | 같은 `_project_payload`를 거침(첫 판과 이후 판이 다른 필드를 옮기는 어긋남 제거) |
| 투영된 행의 소유 표지 | 신규 개념만 `cms_edited_at` | 투영된 모든 행에 `cms_edited_at` — 다음 graph.json 적재가 조용히 덮지 않고 충돌로 보고(P3-25 규약) |
| 개념 삭제 판정 | 표지 있음 = CMS가 만든 개념 | 표지 **그리고** 첫 판이 `cms_create`여야 CMS가 만든 개념(`gate.is_cms_created`). 수정판이 발행된 graph.json 개념은 여전히 `file_owned`로 거부 |

서빙 코드는 바꾸지 않았다. 학생 경로는 여전히 개념 행만 읽고 `concept_version`을 직접 읽지 않는다 — 대신 **개념 행에 쓰는 길이 발행 게이트를 지나는 길 하나로 늘었다.** 결과적으로 D축(판 상태 + Publish Gate)의 결과가 학생 노출에 닿는다. B5의 전제("D는 학생 노출이 아니다")가 깨졌으므로 재판정한다.

## 2. 재판정 — 제8조(되돌릴 수 없는 결함은 L5)

질문: 검수되지 않은 개념 내용이 이 경로로 학생에게 갈 수 있는가. 갈 수 있다면 그것을 막는 장치가 자동 차단(L5)인가.

| 막아야 할 상태 | 막는 장치 | 수준 | 근거(테스트) |
|---|---|---|---|
| 승인 전 판이 학생에게 감 | 투영은 PUBLISHED 도착 전이와 RESTORE에서만 일어남. 전이표가 DRAFT→PUBLISHED 같은 간선을 거부 | L5(예외) | `test_unpublished_draft_does_not_reach_the_student` · `test_publish_from_draft_is_refused_and_nothing_changes` |
| 승인 위조·승인 뒤 payload 변조 | PUBLISH 게이트(거버넌스 완결·해시 재계산·QA 기록 결속) | L5(예외, 쓰기 전) | `test_forged_approved_status_cannot_publish` · `test_payload_tampered_after_approval_cannot_publish` |
| 발행 뒤 판 payload 변조 | DB 트리거(EOS-49 PUBLISHED 불변) | L5(DB) | `test_db_trigger_still_guards_published_payload` |
| 내려가 있던 판이 변조된 채 복원 | RESTORE 게이트 해시 재계산 | L5(예외, 쓰기 전) | `test_rollback_refuses_when_the_deprecated_payload_was_tampered` |
| 부모가 사라진 판의 투영 | `_check_can_realize`(투영 전 부모 실재·자기 참조 거부) | L5(예외, 쓰기 전) | `test_revision_with_a_vanished_parent_is_refused_before_any_write` |
| 검수된 수정이 적재에 조용히 사라짐 | 투영 행 `cms_edited_at` + 적재기 upsert 가드(충돌 보고) | L5(쓰기 거부) | 투영 표지 단언(통합 2건) + 기존 `test_cms_edit_marker.py` 집행 스캔 |

판정: **EOS-50 판정의 결론(D는 A·B·C와 다른 축이며, 미통과 발행은 경고가 아니라 차단)은 유지된다.** D가 학생 노출에 닿게 됐지만, D에서 학생 노출로 가는 길은 위 L5 장치를 전부 지난 뒤에만 열린다. 판정 문서 §6 제8조 행의 "D는 현재 학생 노출이 아니다"는 이 문서로 대체한다.

## 3. 축 경계 B1·B2는 그대로인가

- **B1(게이트는 `ReviewStatus`를 읽지도 쓰지도 않는다)**: 그대로. 투영 함수는 개념 행의 정체성·특성 11필드와 `cms_edited_at`만 쓴다. AST 동결 `test_axis_boundary_b1_gate_does_not_read_review_status` 통과.
- **B2(노출 경로는 판 상태를 읽지 않는다)**: 그대로. 학생 경로는 판 상태가 아니라 개념 행을 읽는다. `test_axis_boundary_b2_exposure_paths_do_not_read_version_status` 통과.
- 문항 노출(`review_status`·저작권)은 이 변경과 무관하다 — 개념 payload에는 본문·문항이 없다.

## 4. 남는 구멍 (정직 고지)

1. **레거시 `PATCH /v1/concepts/{id}`(CONTENT_ADMIN)는 판 없이 개념 행을 직접 고친다.** 이 변경 전에도 있던 경로이며 새로 생긴 노출이 아니다. 다만 이제 "개념 행 = 마지막 발행 판"이라는 기대가 생겼으므로, 그 경로로 고친 행은 발행본과 어긋난다(문항 쪽은 EOS-195가 같은 형태를 차단으로 처분했다). 소유 태스크 = `P3-103-legacy-concept-patch-published-drift`(③이 아래 4번의 소급 어긋남 건수 조회도 맡는다).
2. **운영자가 적재 CLI에 `--overwrite-cms-edits`를 주면** 투영된 행이 파일 내용으로 덮이고 표지가 비워진다. 그때 개념 행과 발행 포인터의 판 payload가 어긋난다. 의도된 운영자 선택이라 막지 않는다(P3-25 규약 그대로).
3. **폐기(deprecate) 뒤 개념 행은 마지막 발행 내용을 유지한다.** "발행본 없음"이 "개념이 학생에게 안 보임"을 뜻하지 않는다 — 개념 행의 노출 여부는 이 모듈의 소관이 아니다(B2).
4. 운영 DB에 판이 발행된 기존 개념이 이미 있다면, 이 변경 배포 후 **다음 발행·롤백부터** 투영된다. 이미 발행돼 있던 판을 소급 투영하지 않는다. 이 환경은 운영 DB에 접근하지 않아 그런 행의 존재는 확인하지 못했다.
