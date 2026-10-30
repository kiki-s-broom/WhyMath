# P3-44 새 문항 틀 설계 — 공통 브리프 (서브에이전트용)

저장소: `/home/user/WhyMath` (브랜치 `claude/gracious-noether-ikmlwq`). 먼저 읽을 것: `CLAUDE.md`(길다 — 「절대 금기」의 AI·신뢰, 「검증 권위」만 읽어도 된다),
`docs/reviews/p3_44_graph_connectivity_root_cause_2026-10-16.md`(이 설계의 입력. 특히 §3·§4·§5).

## 배경 (3줄)
Graph Connectivity 지표는 개념마다 "핵심 오개념에 닿는 문항이 있는가"를 잰다. 문항이 사슬에 들어가려면 (a) 검수 approved (b) 해당 개념 PRIMARY
(c) 개념 스킬을 행사하는 문제유형 (d) 오답 보기(`distractor_map`)가 핵심 오개념에 도달 — 4조건 전부. 코드: `src/backend/whymath_backend/l1/standards/phase3_coverage.py`
`_facts`·`_reached_misconceptions`. 문제유형→스킬 표와 개념별 스킬은 그 문서 §3·진단 출력 참고(문제유형 17종, 개념 스킬은 아래 개념별 지시에 적었다).
승인된 기존 504건 은행(`data/corpus/problem_bank_p3_calculus1_diff_v0`)은 **내용이 승인에 결속**돼 있어 고칠 수 없다. 그래서 **새 코퍼스에 새 문항 틀을 추가**하는 경로로 간다(Kiki 결정).

## 가장 중요한 원칙 — 정직한 도출
오답 보기에 핵심 오개념 id(M-id)를 붙이려면, **그 선택지 값이 그 오개념의 잘못된 절차에서 실제로 계산돼 나와야 한다.** 라벨만 바꾸면 지표만 오르고 내용은 거짓이다
(이 프로젝트가 가장 경계하는 것). 기존 은행의 02-05·02-10 스킬 연결 오답 보기 행이 이 이유로 재라벨 불가였다. 그러므로:
- 틀마다 **정답 절차**와 **오개념 절차**를 식으로 적고, 선택지 값이 후자의 산출임을 **SymPy로 확인**한다(문항 인스턴스마다).
- 오개념 상황이 **문면에서 실제로 발생**해야 한다(예: "접점을 따로 구하지 않는다"가 성립하려면 접점이 문면에 주어지지 않아야 한다).
- **"이 개념에는 정직한 틀이 없다"도 가치 있는 결과다.** 억지로 맞추지 말고 그 이유를 쓴다. 가능하면 대안(다른 슬롯·유형)을 제시한다.
- 해당 오개념 설명(`data/corpus/misconceptions_v1/misconceptions.json`의 `canonical_statement`·`student_wrong_thinking`·`distractor_rule`·`correction_point`)을 직접 읽고 그 문장에 근거한다. 내 가설에 기대지 말고 독립 판단한다.

## 하지 않는 것
- **저장소 파일을 수정하지 않는다**(코드·코퍼스·문서·대장 전부). 모든 산출물은 스크래치패드 `/tmp/claude-0/-home-user-WhyMath/c9728b1a-00a3-53ec-bb27-ce50280c886f/scratchpad/` 아래에만 쓴다.
- LLM으로 문항을 쓰지 않는다 — 결정론 생성·SymPy(저장소는 LLM 0)가 전제다.
- 02-09(M0677)는 범위 밖이다.
- 교과서·평가원·EBS 문항 본문을 쓰지 않는다(자체 동등문제만).

## 알아야 할 코드 (읽고 정확히 따른다)
- 틀 정의 뼈대: `src/backend/whymath_backend/l3/equivalent/p3_diff_skeleton_base.py` — `Frame(frame_id, params, build)`, `DiffItem`(question_text·answer_text·explanation·conditions(Tier1 검산 조건)·answer_map·problem_type_code·choices·distractors=((선지 인덱스, id),...)),
  `ChoiceEntry`/`build_choices`(선지 4개·정답 1개), `round_robin_items`, `probe_of`(우회로 판정기 표본), `P3DiffSlotGenerator`(슬롯 1개 담당, `items()`가 슬롯의 오개념 연결 집합 균일을 강제).
- 같은 개념의 기존 생성기: `p3_diff_<개념>_skeleton_generator.py` (같은 디렉터리). 틀 문체·해설 문장·검산 조건 형식·`params` 구성을 **그대로 따르면** 감사에서 덜 걸린다.
- 우회로 판정기(생성 시점 가드, 위반이 하나라도 있으면 빌드가 멈춘다): `p3_diff_shortcut_guard.py` — 규칙 ID 목록이 파일 앞 docstring에 있다. 새 틀이 걸릴 규칙을 **미리 찾아** 보고한다.
  특히 `_misconception_rules`(M-link-procedure·M-link-undescribed)가 M-id 연결을 어떻게 검사하는지 정확히 읽고, 새 연결이 규칙을 통과하는지/규칙을 확장해야 하는지 판단한다. (`_UNDESCRIBED_MISCONCEPTIONS` 는 M0677 만)
- 승인 이력·감사 결함 부류(문장·표기·해설·태그 품질, 정답 오류는 0건): `docs/data/p3_calculus1_diff_audit/README.md`, `docs/data/p3_fill_audit/README.md`. 지난 결함 부류를 새 틀이 되풀이하지 않게 한다
  (예: 미분 없이 선수 계산으로 풀리는 우회로(bad_tag), 해설 형식, `<=` 대신 `≤`, 선지 `sqrt` 표기 금지, "발문에 없는 기호" 등).
- 슬롯 6종(대표·기본·응용·오개념 유발·진단·숙련도 확인)과 계약: `docs/standards/problem_metadata_contract.md` §3 — 오개념 유발 슬롯은 문항 자체 연결이 필수, 나머지 5슬롯은 오답 보기가 없어도 된다.
  `items()`는 슬롯 안 문항의 오개념 연결 집합이 균일(오개념 유발 = 정확히 {id}, 나머지 = 공집합)해야 통과시킨다 — 이 제약 안에서 설계한다.
- 근사 중복 기준: `src/backend/whymath_backend/l1/standards/phase3_stem_fold.py`(문면 골격). 기존 은행(`problem_bank_p3_calculus1_diff_v0`·`problem_bank_p3_fill_v0`)의 문면·검산 조건과 **겹치지 않는지** 확인한다.

## 산출물 (개념당)
1. `design_<개념코드>.md` (스크래치패드): 틀 후보별로 — 발문 틀 / 정답 절차(식) / 오개념 절차(식)와 선택지 산출 공식 / 문제유형 코드와 그것이 개념 스킬과 겹치는 근거(`ptype.*`→스킬 표, 거짓 유형 금지) / 검산 조건(Tier1) 형식 / 걸리는 우회로 규칙 / 슬롯 배정.
2. `proto_<개념코드>.py` (스크래치패드): **저장소 코드를 import해** 틀을 실제로 만들어 보는 프로토타입 — 가능한 한 `Frame`/`DiffItem`/`build_choices`/`probe_of`/`shortcut_violations`를 써서 인스턴스 ≥40건을 만들고 아래를 단언·출력:
   정답이 SymPy로 옳음 · 오개념 선택지 값 == 오개념 절차 산출 · 오개념 선택지 ≠ 정답 · 선택지 4개가 서로 다름 · 우회로 판정기 위반 0건 · 기존 두 은행과 문면/검산 조건 중복 0건.
   실행해서 **실제 출력**을 확인한다(실행하지 않은 스크립트를 보고하지 않는다). 파이썬은 `cd /home/user/WhyMath/src/backend && python3 <스크립트>`로 돌린다(의존 설치 완료).
3. 변별력: 오개념 절차 값과 **다른 값**(예: 무관한 오답)을 같은 id로 라벨한 주입을 하나 만들어, 당신의 단언이 그것을 **잡는지** 확인한다(단언이 항상 통과하는 위장이 아님을 증명).
4. 용량: 틀별로 서로 다른 인스턴스가 최대 몇 건 나오는지(파라미터 공간), 서로 다른 문면 골격 수.
5. 위험: 감사 판정자가 결함으로 볼 만한 지점(해석 갈림·표기·우회로)과, 당신이 **확인하지 못한 것**.

## 보고 형식 (최종 응답)
600단어 이내. ① 결론 한 줄(정직한 틀이 있다/없다/부분) ② 추천 틀 목록과 용량 ③ 판정기 규칙 확장이 필요한지 ④ 프로토타입 실행 결과 요약(건수·단언·변별 주입 결과) ⑤ 확인하지 못한 것. 파일 경로를 함께 적는다.
