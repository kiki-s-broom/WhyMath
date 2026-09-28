# 6장. 계약 (Contract)

한 줄 요약: **경계를 넘는 데이터의 모양과 의미를 스키마로 약속하고, 경계에서 즉시 검사해 틀린 데이터가 안쪽으로 들어오지 못하게 한다.**

#### ① 증상

- AI가 돌려준 JSON에 가끔 필드가 빠지거나 이름이 다름(`answer` 대신 `correct_answer`) → 한참 뒤 엉뚱한 곳에서 오류
- 선지가 4개인 문항이 섞여 들어와 앱 화면이 깨짐
- 백엔드에서 필드 이름을 바꿨더니 이미 설치된 앱이 멈춤
- 과목 어댑터가 코어가 기대하는 형식을 "대충" 맞춰서, 특정 경우에만 실패

#### ② 근본 결함

데이터에 대한 약속이 **암묵적**이고, **경계에서 검사하지 않습니다.** 틀린 데이터가 안쪽 깊숙이 들어온 뒤에야 터지기 때문에 원인과 증상의 거리가 멉니다. 특히 AI 출력은 같은 요청에도 모양이 흔들리므로, **가장 신뢰할 수 없는 외부 입력**으로 취급해야 합니다.

#### ③ 업계 표준

| 표준 | 핵심 아이디어 |
|---|---|
| 계약에 의한 설계 (Design by Contract) | Bertrand Meyer, Eiffel 언어(1986~). 사전조건(들어올 때 참이어야 할 것)·사후조건(나갈 때 참이어야 할 것)·불변식(항상 참)을 명시 |
| 검증하지 말고 파싱하라 (Parse, don't validate) | Alexis King, 2019. 경계에서 '검사 후 원래 데이터를 그대로 쓰기'가 아니라, 검증된 **타입으로 변환**해서 안쪽은 그 타입만 다룸 |
| 스키마 검증 | JSON Schema, Pydantic v2(Python), OpenAPI 3.1(API 전체) |
| 소비자 주도 계약 테스트 | Pact 등. 데이터를 받는 쪽(소비자)이 기대를 테스트로 적고, 보내는 쪽이 그 테스트를 통과해야 배포 |
| 호환성 규칙 | 필드 **추가**는 호환, **삭제·이름 변경·의미 변경**은 비호환 → 버전 올림 (시맨틱 버저닝의 주 버전) |

#### ④ 원전

- Bertrand Meyer, 『Object-Oriented Software Construction』(1988, 2판 1997)
- Alexis King, "Parse, don't validate" (lexi-lambda.github.io, 2019)
- Pydantic v2 공식 문서 — `model_validator`, `ConfigDict(extra="forbid")`

#### ⑤ WhyMath 적용 — 문항 계약과 AI 출력 파싱

**문항 계약 (Pydantic v2)**

```python
# eos_core/models.py — 문항 계약 (4장 SSOT: 이 모델은 schemas/item.schema.json에서 생성하거나, 역으로 스키마를 내보냄)
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Label = Literal["①", "②", "③", "④", "⑤"]

class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")          # 약속에 없는 필드가 오면 거부
    label: Label
    text: str = Field(min_length=1)
    op_code: str | None = Field(default=None, pattern=r"^OP_0[1-8]$")  # 오답 유형 (정답 선지는 없음)

class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1                     # 계약 버전 (규칙 R6-03)
    node_id: str = Field(pattern=r"^[A-Za-z0-9_\-]+$")
    stem: str = Field(min_length=5)                    # 문제 본문
    choices: list[Choice] = Field(min_length=5, max_length=5)
    answer: Label

    @model_validator(mode="after")
    def check_contract(self) -> "Item":
        labels = [c.label for c in self.choices]
        if len(set(labels)) != 5:                      # 불변식 1: 선지 번호 중복 금지
            raise ValueError("선지 번호가 중복됨")
        for c in self.choices:                         # 불변식 2: 정답엔 op_code 없음, 오답엔 필수
            if (c.label == self.answer) != (c.op_code is None):
                raise ValueError(f"{c.label}: 정답/오답과 op_code 표기가 어긋남")
        return self
```

**AI 출력 파싱 (Python)**

```python
# infra/ai_parsing.py — AI 출력은 경계에서 '파싱'한다. 실패하면 재시도, 그래도 실패면 격리
import json
import logging
from pydantic import ValidationError
from eos_core.models import Item

log = logging.getLogger("ai_parsing")
MAX_RETRY = 2   # 재시도 상한 (무한 재시도 = 무한 비용)

def parse_item(raw: str, regenerate, quarantine) -> Item | None:
    """raw: AI 원문. regenerate(오류메시지) → 새 원문. quarantine(원문, 사유) → 격리 저장."""
    for attempt in range(MAX_RETRY + 1):
        try:
            return Item.model_validate(json.loads(raw))   # 여기를 통과한 것만 안쪽으로 들어감
        except (json.JSONDecodeError, ValidationError) as e:
            log.warning("계약 위반 (시도 %d): %s", attempt + 1, e)
            if attempt == MAX_RETRY:
                quarantine(raw, str(e))                   # 버리지 않고 격리 → 오류 패턴 분석용
                return None
            raw = regenerate(f"다음 오류를 고쳐 같은 JSON 형식으로 다시 출력: {e}")
    return None
```

### Subject Contract — 코어와 과목 사이의 계약

같은 원리가 EOS 코어와 과목 어댑터 사이에도 적용됩니다. 코어는 과목에게 "개념 그래프를 이 형식으로 달라", "정답 검증기를 이 형식으로 달라"고 **포트로 요구**하고, 그 약속을 검사하는 **계약 테스트를 코어가 소유**합니다. 모든 과목은 같은 계약 테스트를 통과해야 등록됩니다. 자세한 구조는 28장에서 다룹니다.

### 호환성 테스트 — 과거 데이터로 새 스키마를 검사

스키마를 바꿀 때 가장 확실한 호환성 검사는 **과거 실제 데이터 표본**(fixtures)을 새 스키마로 읽어 보는 것입니다. 이미 배포된 앱이 보내는 데이터, 이미 DB에 있는 문항 몇십 개를 `fixtures/schema_samples/`에 두고, 스키마를 바꿀 때마다 이 표본이 모두 파싱되는지 CI에서 확인합니다(R6-02).

#### ⑥ 자동 검사와 목표 강도

| 장치 | 강도 |
|---|---|
| AI 출력 파싱 테스트: 필드 누락·추가·선지 4개·op_code 불일치 사례가 모두 거부되는지 | L5 |
| 과거 데이터 표본 호환성 테스트 | L5 |
| 모든 경계 스키마에 `schema_version` 존재 검사 | L5 |
