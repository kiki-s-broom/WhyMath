"""골든 패스 LLM 호출 경로 — 옛 `whymath_backend.l3.providers`의 OpenRouter 경로 복사본(S20A 2일째).

옛 프로바이더 패키지를 import하면 `providers/__init__.py`가 프로바이더 4종(anthropic·deepseek·
ollama·openrouter)과 composite를 한꺼번에 불러 옛 모듈 13개가 따라온다. 골든은 OpenRouter 좌석
하나만 쓰므로 그 경로만 복사했다(HARVEST.md "복사: 의존 과다" · Kiki 결정 2026-11-17 선택지 B).

라우터 판정(`whymath_backend.l3.router.Router.route`)과 설정(`whymath_backend.config`)은 계속 옛
것을 쓴다 — LLM 호출은 라우터를 거치고, 모델 이름·허용 공급사·키는 옛 설정과 같이 움직인다. 옛
코드와 같은 동작은 `tests/golden/characterization/test_s20a_llm_*.py`가 고정한다.
"""
