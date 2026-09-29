"""graded 힌트 내용 — 오프라인 생성·게이트 3종·`hints` 영속·coach 서빙 reader (S4-11 · D3).

HintNode Persistence 연기(MEMORY 2026-07-08 Phase 6b)의 해제 슬라이스다. 연기 당시 적은 도입
전제 3종을 한 패키지가 함께 세운다:
  ① generation — `generator.py`(템플릿·LLM 0) + `populate.py`(오프라인 CLI·유일 실행 표면)
  ② validation — `gates.py`(level-reveals 정합 · 정답 누출 · 정서 톤 — 통과분만 verified)
  ③ serving    — `store.find_served_hint` ← `api/coach.py` 세션 생성·턴 추가 2경로

엔티티 정본은 `models.py`(Hint·HintReveals·reveal_score 정의), 영속은 `db/models/hint.py`.

이 `__init__`은 의도적으로 아무것도 re-export하지 않는다 — `gates`가 `harness`를 import하고
`harness`(→ `wh1_evaluation`)가 `models`를 import하므로, 패키지 초기화에서 하위 모듈을 끌어오면
import 순서에 따라 순환이 생긴다. 소비자는 하위 모듈을 직접 import한다.
"""
