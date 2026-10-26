"""L3 교수법 콘텐츠 파이프라인 — 발주서(work_order)→콘텐츠 슬롯 생성·예심·검수.

컴파일러(`l1.pedagogy.unit_compiler`)가 낸 *발주서*를 소비해 `pedagogy_content_slot` 행을
만들고(생성), 기계 점수를 매기고(예심), 기계 게이트로 승격/반려(검수)하는 계층이다.

PED-24(04g §6·§7.2 — 구 PED-09/PED-10 회수)로 LLM 생성·투영 경로가 열렸다:
`analogy_generator`(개념-grain 비유 — `concept_content.metaphor` 채움)·`example_generator`
(목표-grain 실생활 예시 — 슬롯 채움)·`analogy_checker`(결함 4축 규칙 검출)·`analogy_demand`
(발주 수요 실측 CLI)·`diag_item_projector`(atom_probe → diag_item 슬롯 투영·LLM 0). 검수
상태기계(prescreen→review)는 두 생성기·투영기가 재사용한다(새 상태기계 없음).

7계층: L3 콘텐츠 생성·검증. 컴파일러(L1)가 슬롯을 *만들지 않고* 발주서만 내는 경계를 지켜,
생성 이후 단계를 이 계층이 소비처로 받는다(역방향 의존 금지).
"""
