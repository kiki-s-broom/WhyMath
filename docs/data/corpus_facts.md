# 코퍼스 사실 표 (생성 문서 — 손으로 고치지 않는다)

> 이 파일은 `python3 scripts/analysis/corpus_facts.py sync`가 만든다. 값은 원본 파일에서 센 것이다.
> 문서에서 이 값을 인용할 때는 숫자를 손으로 적지 말고 사실 이름으로 표식을 단다 — 표식 형식·규칙은 `scripts/analysis/corpus_facts.py` 모듈 설명(태스크 OPS-154).

| 사실 이름 | 값 | 설명 | 원본 |
|---|---:|---|---|
| `ai_quality_eval.cases` | 244 | AI 품질 평가셋 사례 | `data/corpus/ai_quality_eval_v1/eval_set.jsonl` |
| `ai_quality_eval.choice_cases` | 64 | AI 품질 평가셋 선택지 사례 | `data/corpus/ai_quality_eval_v1/eval_set.jsonl` |
| `ai_quality_eval.hint_cases` | 180 | AI 품질 평가셋 힌트 사례 | `data/corpus/ai_quality_eval_v1/eval_set.jsonl` |
| `atom_graph.atoms` | 1,823 | 원자 백본 세부개념 | `data/corpus/atom_graph_v1/graph.json` |
| `atom_graph.cross_band_edges_university` | 24 | 고→대 경계 엣지 원장 | `data/corpus/atom_graph_v1/cross_band_edges_university_v1.json` |
| `atom_graph.edges` | 2,278 | 원자 백본 선수 엣지 | `data/corpus/atom_graph_v1/graph.json` |
| `atom_graph.inter_course_edges_university` | 129 | 대학 과목간 엣지 원장 | `data/corpus/atom_graph_v1/inter_course_edges_university_v1.json` |
| `atom_graph.narrative_edges_raw` | 973 | 원자 백본 서술형 선수 원문 | `data/corpus/atom_graph_v1/graph.json` |
| `atom_graph.nodes` | 2,683 | 원자 백본 노드(세부개념+소단원+단원) | `data/corpus/atom_graph_v1/graph.json` |
| `atom_graph.sha12` | a2424fe18727 | 원자 백본 graph.json sha256 앞 12자(LF 기준) | `data/corpus/atom_graph_v1/graph.json` |
| `atom_graph.subunits` | 643 | 원자 백본 소단원 | `data/corpus/atom_graph_v1/graph.json` |
| `atom_graph.units` | 217 | 원자 백본 단원 | `data/corpus/atom_graph_v1/graph.json` |
| `atom_graph.university_atoms` | 512 | 원자 백본 대학 세부개념 | `data/corpus/atom_graph_v1/graph.json` |
| `concept_atom_crosswalk.entries` | 437 | 개념↔원자 크로스워크 항목 | `data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl` |
| `concept_atom_crosswalk.mapped` | 437 | 크로스워크 중 원자 코드가 붙은 항목 | `data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl` |
| `concept_content.k12` | 437 | K-12 개념 콘텐츠 | `data/corpus/concept_content_v1/content.json` |
| `concept_content.k12_flashcards` | 113 | K-12 개념 콘텐츠 플래시카드 | `data/corpus/concept_content_v1/content.json` |
| `concept_content.k12_subjects` | 17 | K-12 개념 콘텐츠 과목 | `data/corpus/concept_content_v1/content.json` |
| `concept_content.university` | 409 | 대학 개념 콘텐츠 | `data/corpus/concept_content_university_v1/content.json` |
| `concept_content.university_flashcards` | 409 | 대학 개념 콘텐츠 플래시카드 | `data/corpus/concept_content_university_v1/content.json` |
| `concept_content.university_subjects` | 32 | 대학 개념 콘텐츠 과목 | `data/corpus/concept_content_university_v1/content.json` |
| `concept_graph.concepts` | 437 | 구 개념 그래프 개념 | `data/corpus/concept_graph_v1/graph.json` |
| `concept_graph.edges` | 581 | 구 개념 그래프 선수 엣지 | `data/corpus/concept_graph_v1/graph.json` |
| `concept_visual_style.entries` | 127 | 개념 시각화 스타일 | `data/corpus/concept_visual_style_v1/concept_visual_style.json` |
| `formula_graph.families` | 8 | 공식 계열 | `data/corpus/formula_graph_v1/formulas.jsonl` |
| `formula_graph.formulas` | 25 | 공식 | `data/corpus/formula_graph_v1/formulas.jsonl` |
| `misconception_crosslinks.count` | 69 | 오개념 교차 연결 | `data/corpus/misconception_crosslinks_v1/crosslinks.json` |
| `misconceptions.count` | 843 | 오개념(M-id) | `data/corpus/misconceptions_v1/misconceptions.json` |
| `misconceptions.with_ccss` | 775 | 오개념 중 CCSS 코드가 있는 것 | `data/corpus/misconceptions_v1/misconceptions.json` |
| `misconceptions.with_error_type` | 738 | 오개념 중 오류 유형이 있는 것 | `data/corpus/misconceptions_v1/misconceptions.json` |
| `problem_bank.banks` | 39 | 문제은행 수 | `data/corpus/problem_bank_*/problems.jsonl` |
| `problem_bank.binomial_distribution_v0` | 300 | 문제은행 problem_bank_binomial_distribution_v0 | `data/corpus/problem_bank_binomial_distribution_v0/problems.jsonl` |
| `problem_bank.calculus1_integral_v0` | 400 | 문제은행 problem_bank_calculus1_integral_v0 | `data/corpus/problem_bank_calculus1_integral_v0/problems.jsonl` |
| `problem_bank.calculus2_trig_integral_v0` | 80 | 문제은행 problem_bank_calculus2_trig_integral_v0 | `data/corpus/problem_bank_calculus2_trig_integral_v0/problems.jsonl` |
| `problem_bank.combination_binomial_v0` | 121 | 문제은행 problem_bank_combination_binomial_v0 | `data/corpus/problem_bank_combination_binomial_v0/problems.jsonl` |
| `problem_bank.complex_number_arithmetic_v0` | 900 | 문제은행 problem_bank_complex_number_arithmetic_v0 | `data/corpus/problem_bank_complex_number_arithmetic_v0/problems.jsonl` |
| `problem_bank.conceptual_v0` | 360 | 문제은행 problem_bank_conceptual_v0 | `data/corpus/problem_bank_conceptual_v0/problems.jsonl` |
| `problem_bank.conic_section_focus_v0` | 65 | 문제은행 problem_bank_conic_section_focus_v0 | `data/corpus/problem_bank_conic_section_focus_v0/problems.jsonl` |
| `problem_bank.coordinate_geometry_v0` | 400 | 문제은행 problem_bank_coordinate_geometry_v0 | `data/corpus/problem_bank_coordinate_geometry_v0/problems.jsonl` |
| `problem_bank.discrete_ev_v0` | 200 | 문제은행 problem_bank_discrete_ev_v0 | `data/corpus/problem_bank_discrete_ev_v0/problems.jsonl` |
| `problem_bank.elementary_area_measure_v0` | 270 | 문제은행 problem_bank_elementary_area_measure_v0 | `data/corpus/problem_bank_elementary_area_measure_v0/problems.jsonl` |
| `problem_bank.elementary_division_remainder_v0` | 400 | 문제은행 problem_bank_elementary_division_remainder_v0 | `data/corpus/problem_bank_elementary_division_remainder_v0/problems.jsonl` |
| `problem_bank.elementary_gcd_lcm_v0` | 600 | 문제은행 problem_bank_elementary_gcd_lcm_v0 | `data/corpus/problem_bank_elementary_gcd_lcm_v0/problems.jsonl` |
| `problem_bank.elementary_rounding_v0` | 600 | 문제은행 problem_bank_elementary_rounding_v0 | `data/corpus/problem_bank_elementary_rounding_v0/problems.jsonl` |
| `problem_bank.elementary_v0` | 400 | 문제은행 problem_bank_elementary_v0 | `data/corpus/problem_bank_elementary_v0/problems.jsonl` |
| `problem_bank.elementary_volume_measure_v0` | 300 | 문제은행 problem_bank_elementary_volume_measure_v0 | `data/corpus/problem_bank_elementary_volume_measure_v0/problems.jsonl` |
| `problem_bank.generated_v0` | 619 | 문제은행 problem_bank_generated_v0 | `data/corpus/problem_bank_generated_v0/problems.jsonl` |
| `problem_bank.highschool_quotient_rule_v0` | 200 | 문제은행 problem_bank_highschool_quotient_rule_v0 | `data/corpus/problem_bank_highschool_quotient_rule_v0/problems.jsonl` |
| `problem_bank.killer_v0` | 120 | 문제은행 problem_bank_killer_v0 | `data/corpus/problem_bank_killer_v0/problems.jsonl` |
| `problem_bank.linear_inequality_system_v0` | 600 | 문제은행 problem_bank_linear_inequality_system_v0 | `data/corpus/problem_bank_linear_inequality_system_v0/problems.jsonl` |
| `problem_bank.matrix_ops_v0` | 320 | 문제은행 problem_bank_matrix_ops_v0 | `data/corpus/problem_bank_matrix_ops_v0/problems.jsonl` |
| `problem_bank.measurement_unit_conversion_v0` | 180 | 문제은행 problem_bank_measurement_unit_conversion_v0 | `data/corpus/problem_bank_measurement_unit_conversion_v0/problems.jsonl` |
| `problem_bank.middle_function_v0` | 200 | 문제은행 problem_bank_middle_function_v0 | `data/corpus/problem_bank_middle_function_v0/problems.jsonl` |
| `problem_bank.misconception_mc_v0` | 1,080 | 문제은행 problem_bank_misconception_mc_v0 | `data/corpus/problem_bank_misconception_mc_v0/problems.jsonl` |
| `problem_bank.p3_calculus1_diff_v0` | 504 | 문제은행 problem_bank_p3_calculus1_diff_v0 | `data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl` |
| `problem_bank.p3_fill_v0` | 204 | 문제은행 problem_bank_p3_fill_v0 | `data/corpus/problem_bank_p3_fill_v0/problems.jsonl` |
| `problem_bank.permutation_combination_v0` | 160 | 문제은행 problem_bank_permutation_combination_v0 | `data/corpus/problem_bank_permutation_combination_v0/problems.jsonl` |
| `problem_bank.polynomial_arithmetic_v0` | 1,500 | 문제은행 problem_bank_polynomial_arithmetic_v0 | `data/corpus/problem_bank_polynomial_arithmetic_v0/problems.jsonl` |
| `problem_bank.polynomial_factoring_v0` | 600 | 문제은행 problem_bank_polynomial_factoring_v0 | `data/corpus/problem_bank_polynomial_factoring_v0/problems.jsonl` |
| `problem_bank.probability_finite_v0` | 34 | 문제은행 problem_bank_probability_finite_v0 | `data/corpus/problem_bank_probability_finite_v0/problems.jsonl` |
| `problem_bank.probability_law_v0` | 724 | 문제은행 problem_bank_probability_law_v0 | `data/corpus/problem_bank_probability_law_v0/problems.jsonl` |
| `problem_bank.quad_ineq_v0` | 200 | 문제은행 problem_bank_quad_ineq_v0 | `data/corpus/problem_bank_quad_ineq_v0/problems.jsonl` |
| `problem_bank.radian_conversion_v0` | 144 | 문제은행 problem_bank_radian_conversion_v0 | `data/corpus/problem_bank_radian_conversion_v0/problems.jsonl` |
| `problem_bank.rephrased_v0` | 421 | 문제은행 problem_bank_rephrased_v0 | `data/corpus/problem_bank_rephrased_v0/problems.jsonl` |
| `problem_bank.sample_mean_distribution_v0` | 400 | 문제은행 problem_bank_sample_mean_distribution_v0 | `data/corpus/problem_bank_sample_mean_distribution_v0/problems.jsonl` |
| `problem_bank.sequence_sigma_v0` | 132 | 문제은행 problem_bank_sequence_sigma_v0 | `data/corpus/problem_bank_sequence_sigma_v0/problems.jsonl` |
| `problem_bank.total` | 14,742 | 문제은행 전체 문항 | `data/corpus/problem_bank_*/problems.jsonl` |
| `problem_bank.university_calc1_chain_quotient_v0` | 400 | 문제은행 problem_bank_university_calc1_chain_quotient_v0 | `data/corpus/problem_bank_university_calc1_chain_quotient_v0/problems.jsonl` |
| `problem_bank.university_calc1_v0` | 200 | 문제은행 problem_bank_university_calc1_v0 | `data/corpus/problem_bank_university_calc1_v0/problems.jsonl` |
| `problem_bank.v1` | 4 | 문제은행 problem_bank_v1 | `data/corpus/problem_bank_v1/problems.jsonl` |
| `problem_bank.vector_operations_v0` | 400 | 문제은행 problem_bank_vector_operations_v0 | `data/corpus/problem_bank_vector_operations_v0/problems.jsonl` |
| `problem_type_graph.families` | 6 | 문제 유형 계열 | `data/corpus/problem_type_graph_v1/problem_types.jsonl` |
| `problem_type_graph.types` | 17 | 문제 유형 | `data/corpus/problem_type_graph_v1/problem_types.jsonl` |
| `problem_variants_staging.records` | 313 | 문제 변형 대기열 | `data/corpus/problem_variants_staging_v0/problems.jsonl` |
| `skill_graph.behavior_areas` | 6 | 스킬 행동 영역 | `data/corpus/skill_graph_v1/skills.jsonl` |
| `skill_graph.families` | 16 | 스킬 계열 | `data/corpus/skill_graph_v1/skills.jsonl` |
| `skill_graph.skills` | 27 | 스킬 | `data/corpus/skill_graph_v1/skills.jsonl` |
| `standards.k12` | 895 | K-12 성취기준 | `data/corpus/standards_v1/standards.json` |
| `standards.k12_2015` | 460 | K-12 성취기준 중 2015 개정 | `data/corpus/standards_v1/standards.json` |
| `standards.k12_2022` | 435 | K-12 성취기준 중 2022 개정 | `data/corpus/standards_v1/standards.json` |
| `standards.k12_links` | 443 | K-12 개념↔성취기준 연결 | `data/corpus/standards_v1/concept_standard_links.json` |
| `standards.university` | 409 | 대학 성취기준 | `data/corpus/standards_university_v1/standards.json` |
| `standards.university_links` | 409 | 대학 개념↔성취기준 연결 | `data/corpus/standards_university_v1/concept_standard_links.json` |
| `standards.university_subjects` | 32 | 대학 성취기준 과목 | `data/corpus/standards_university_v1/standards.json` |
| `strategy_graph.families` | 4 | 풀이 전략 계열 | `data/corpus/strategy_graph_v1/strategies.jsonl` |
| `strategy_graph.strategies` | 8 | 풀이 전략 | `data/corpus/strategy_graph_v1/strategies.jsonl` |
| `units.count` | 11 | 학습 단원 정의(units_v1) | `data/corpus/units_v1/*.unit.yaml` |
| `whs_prm.bad` | 619 | PRM 라벨 bad | `data/corpus/whs_prm_v0/prm_dataset.jsonl` |
| `whs_prm.good` | 663 | PRM 라벨 good | `data/corpus/whs_prm_v0/prm_dataset.jsonl` |
| `whs_prm.problems_covered` | 620 | PRM 데이터가 덮는 문항 | `data/corpus/whs_prm_v0/prm_dataset.jsonl` |
| `whs_prm.records` | 1,282 | PRM 단계 라벨 데이터 | `data/corpus/whs_prm_v0/prm_dataset.jsonl` |
