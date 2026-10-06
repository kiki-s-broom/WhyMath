# docs/constitution_proposals — 코딩 헌법 개정 초안 보관소

이 폴더는 **채택 전 초안**만 둔다. 코딩 헌법(`constitution/`)은 사람(Kiki)만 수정한다(헌법 제9조·제11조).
AI 세션은 `constitution/` 을 편집할 수 없다 — `.claude/hooks/guard_constitution.py`(PreToolUse)와
`.claude/settings.json` 거부 규칙이 막는다. 그래서 AI가 찾은 정정·개정은 여기에 초안으로 두고, Kiki가
읽고 고친 뒤 `constitution/` 에 직접 반영한다.

| 파일 | 지위 | 반영 절차 |
|---|---|---|
| `A0003_sources_registry_draft.md` | 초안 — 원본 등록부 실제 경로 정정 | 런북 과제 A · 게이트 `G-const-sources-registry-adopt` |
| `rules_v1.0.1_sources_fixed.yaml` | A0003 의 정정안(규칙 14건 바이트 동일 · sources·version 만 변경) | 런북 과제 A |
| `A0002_parts_II-VII_rules_draft.md` | Kiki 업로드 원본 그대로(2026-09-26 · 파일명만 ASCII) — 조문 5개 신설안 | 런북 과제 B · 게이트 `G-const-a0002-adoption` |
| `rules_additions_v1.1.yaml` | Kiki 업로드 원본 그대로 — 규칙 81건(R5~R29) | 런북 과제 B (`merge_rules.py`) |
| `A0004_sources_registry_additions_draft.md` | 초안 — 원본 등록부 3건 추가(프로젝트 규칙·LLM 모델 핀 로컬/클라우드) · A0003 채택 후 | 채택 도우미 A0004 미지원 — 확장 선행 |
| `rules_v1.0.2_sources_additions.yaml` | A0004 의 추가분(sources 항목 3건만) | 위와 같음 |
| `A0005_r4_02_schema_model_sync_draft.md` | 초안 — R4-02 문구 개정("자동 생성"→"스키마 YAML ↔ 모델 필드 일치 검사") · 집행 `tests/constitution/test_schema_model_sync.py` | 정정분 `rules_R4-02_schema_model_sync.yaml` 의 R4-02 블록으로 교체 |
| `rules_R4-02_schema_model_sync.yaml` | A0005 의 정정분(R4-02 블록 1건) | 위와 같음 |

런북: `docs/ops/coding_constitution_kiki_runbook.md` · 이식 정본: `docs/standards/coding_constitution_transplant.md`

**주의**: `rules_additions_v1.1.yaml` 을 `constitution/rules.yaml` 맨 끝에 붙여 넣지 않는다 — YAML 오류 없이
원본 등록부(sources) 목록으로 흡수돼 규칙이 하나도 늘지 않는다. 반드시 `scripts/constitution/merge_rules.py` 를 쓴다
(심사 도구도 이 상태를 "심사 불가"로 멈춘다).
