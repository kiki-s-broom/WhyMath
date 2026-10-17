# Python 코딩 표준

## 환경
- Python 3.12+
- 패키지 관리: `uv` (pip 대체)
- 가상환경: `uv venv`
- 의존성: `pyproject.toml` — **모든 선언에 상한을 건다**(OPS-94). 상한은 "그 시점 설치·최신 중 큰 쪽의
  다음 메이저 미만"(0.x는 `<1`)으로 걸고, 올릴 때는 두 pyproject와 워크플로 직설치에서 **같은 패키지의
  상한을 함께** 올린다. 무상한 선언·상한 불일치·만료된 예외는 CI가 막는다 —
  `scripts/ops/check_dependency_upper_bounds.py`(`infra-contracts` 잡). 예외는
  `scripts/ops/dependency_upper_bound_allowlist.toml`에 사유·만료일(366일 이내)과 함께만 둔다.

## 포맷·린터
- 포맷: `black`
- 린터: `ruff` (rules: E, F, I, N, B, W)
- 타입: `mypy --strict`

## 스타일

```python
# 모든 주석은 한국어
# 함수·클래스·모듈 docstring 필수
# 타입 힌트 100%

from typing import Final
from pydantic import BaseModel

# 상수는 UPPER_SNAKE_CASE + Final
MAX_RETRY: Final[int] = 3

class Student(BaseModel):
    """학생 도메인 모델 — 모든 학생 데이터의 단일 정의"""
    id: str
    grade: int

async def get_student(student_id: str) -> Student | None:
    """학생 정보 조회. 없으면 None."""
    # 구현
    pass
```

## 비동기 우선
- I/O는 항상 `async`
- 동기/비동기 혼용 금지

## 에러 처리
- 도메인 예외는 명시적 클래스 (`StudentNotFoundError` 등)
- 외부 호출 (LLM·DB·HTTP)은 재시도 데코레이터
- `try/except`는 *최소 범위*

## 테스트
- `pytest` + `pytest-asyncio`
- 커버리지 게이트 정본 = `docs/standards/testing.md` — 집계 70% + 계층별 floor(l4=90% · l1/l2/api=80% · l3=70%). 수치의 단일 진실 원천은 `scripts/coverage/check_layer_coverage.py`의 `LAYER_FLOORS` (2026-08-10 통합점검 정정: 종전 이 자리의 "핵심 도메인 80%+"는 l4 floor 90%에 미달하는 낡은 수치였다)
- LLM 호출은 *반드시* 모킹 — 단, **SDK 표면 정합은 모킹으로 선언 금지**: 우리가 호출하는 메서드가 pin 허용 범위의 *실물* SDK에 존재하는지 실측 검증한다 (CLAUDE.md 절대 금기 · `langfuse>=2.50,<5` 선례)

## 의존성 주입
- FastAPI `Depends`
- 직접 import 대신 *주입*
- 테스트 가능성 최우선
