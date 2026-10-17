# MISC-18 — 오개념 품질 게이트 단일 집행 (WH-1 하네스 결선) 관측·검증 기록

> **판정 기준**: `main` `198bba76` (2026-10-05). 아래 사실은 이 커밋의 소스를 AST로 센 결과이며,
> 미머지 브랜치의 내용은 근거로 쓰지 않았다.

## 1. 무엇이 문제였나

오개념 매칭 품질 게이트(`l4/misconception/match_gate.py` — top-1 신뢰도가 0.65 미만이면 후보를 비운다)는
계약이 정본화돼 있었지만, 학생에게 닿는 두 경로 중 코치(`api/coach.py`)만 불렀다. WH-1 하네스의
`MatchMisconceptionAction` 실행부는 `diagnose()`의 원시 후보를 그대로 `state.last_matches`에 넣어,
신호 2개 중 1개만 맞은 약한 부분매칭(신뢰도 0.5)으로도 가설이 서고 개입 발화까지 갔다.
"계약이 있다"와 "계약을 부른다"는 다르다 — 이 경로는 게이트 없이 도는 주경로였다.

## 2. 변경

| 파일 | 내용 |
|---|---|
| `harness/wh1_loop.py` | 매치 실행부가 `apply_match_quality_gate(raw)`를 호출. floor·threshold·ocr 인자를 넘기지 않는다(계약 기본값이 정본, `ocr_confidence`는 None이라 게이트②는 dormant). `ToolResult.match_gate_counts`(raw·kept·no_confident_match·attribution_unclear) 신설 |
| `harness/wh1_shadow.py` | shadow 관측 레코드에 `n_match_raw`·`n_match_kept`(None=구판) 추가 — 트레이스에만 있던 감소량이 서버 로그로 나간다. 수확기는 같은 모델로 파싱하므로 구판 줄도 계속 읽는다 |
| `tests/backend/harness/test_wh1_match_gate_wiring.py` | 동작 계약 15건(전제 고정·대조군·단일 원천·레코드 연결) |
| `tests/backend/harness/test_wh1_match_gate_enforcement.py` | 호출 지점 소스 스캔 동결 10건(아래 §4) |
| `tests/backend/harness/test_wh1_shadow.py` | 개인정보 허용 키 목록에 비식별 정수 2개 등록 |

## 3. 관측 — 게이트가 실제로 일하는가 (acceptance ③)

원시 `diagnose(text, top_k=카탈로그 전수)` 결과와 게이트 통과 결과를 같은 텍스트에 대해 센 값이다.

| 코퍼스 | 텍스트 | 원시 후보 있음 | 게이트 후 후보 있음 | 게이트가 비운 텍스트 |
|---|---|---|---|---|
| 정답 해설(`load_answer_explanations`) | 7,711 | 6,054 (78.5%) | 509 (6.6%) | 5,545 (원시 후보 있던 것의 91.6%) |
| 오탐 프로브(`probes._iter_fp_probes`) | 72 | 63 | 14 | 49 |
| 재현 프로브(`probes._iter_recall_probes`) | 100 | 0 | 0 | 0 |

정답 해설의 top-1 신뢰도 분포는 0.33→579건, 0.5→4,966건, 0.67→28건, 1.0→481건이다. 게이트 전에는
올바른 풀이 7,711건 중 6,054건(78.5%)에서 약한 매치가 후보로 올라왔고, floor 0.65가 그중 약한
5,545건을 비운다. **감소는 0이 아니므로 결선이 실제로 작동한다**(acceptance ③ "감소 0이면 배선 재확인"의
반대 경우).

**교차검증**: 기존 `misconception_false_positive_eval.evaluate()`의 오탐률 0.06601 × 7,711 = 509건으로,
위 "게이트 후 후보 있음 509"와 정확히 일치한다(같은 게이트·같은 코퍼스를 독립 경로로 센 값).

**한계(정직)**: 재현 프로브 100건은 원시 후보가 0건이다 — 이 프로브는 의미 매처용 패러프레이즈라
substring `diagnose`가 아예 반응하지 않는다. 그래서 "게이트가 정당한 매치까지 지우는가(과차단)"는 이
코퍼스로 잴 수 없다. 과차단 쪽 방어는 동작 테스트의 대조군(신호 2개 전부인 강한 입력은 통과)이 맡는다.
**라이브 분포는 아직 없다** — `n_match_raw/n_match_kept` 레코드는 배포 이후부터 쌓이며, 위 표는 오프라인
코퍼스 값이다.

재현:

```python
from whymath_backend.harness.misconception_false_positive_eval import load_answer_explanations
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.diagnose import diagnose
from whymath_backend.l4.misconception.match_gate import apply_match_quality_gate

texts = load_answer_explanations()
raw_n = gated_n = 0
for t in texts:
    raw = diagnose(t, top_k=len(CATALOG_BY_ID))
    raw_n += bool(raw)
    gated_n += bool(apply_match_quality_gate(raw).matches)
print(len(texts), raw_n, gated_n)  # 7711 6054 509
```

## 4. 집행 지점 지도 (acceptance ④)

`whymath_backend` 732개 파일을 AST로 스캔해 `diagnose`·`combine_diagnoses`·`combined_diagnose`·
`apply_match_quality_gate`를 *import해 호출하는* 지점을 셌다(주석·docstring 언급과 import만 하는
재수출은 제외).

- **게이트 호출자 7곳**: 학생 대면 `api/coach.py`(`_gate`)·`harness/wh1_loop.py`(`_exec`), 채널 2곳
  (`distractor_link`·`answer_signature`), 측정 3곳(오탐·앵커·명시정정 평가).
- **게이트 없는 원시 소비자 6곳**: `agreement_gate`·`probes`·`semantic_eval`(측정), `wrong_form_match`
  (shadow 비교 로깅·반환 None), `combined`(정의), `subject_adapter_math`(계약 좌석).
- **프로덕션 호출자 0 동결**: `combined_diagnose(`, `.detect_misconception(` — 둘 다 게이트 없는 원시
  출력을 돌려주므로, 연결되는 순간 게이트를 우회하는 새 경로가 된다. 연결하려면 게이트 경유 설계가 먼저다.

동결 방식은 두 방향 등록부다 — 호출자 집합과 면제 집합을 각각 이름·사유가 달린 닫힌 목록으로 두고
신규도 삭제도 red로 한다. 숫자("2곳")만 고정하면 한 곳이 빠지고 다른 곳이 느는 치환이 통과한다.

## 5. 검증 — 막으려는 상태를 실제로 주입했다

뮤테이션 28종(주입 적용·컴파일·원복 sha256 동일을 실행 전후 단언, 무변형 대조군 먼저).

- **1차 21종**(결선·호출 지점): 게이트 호출 제거, 결과 폐기, floor 덮어쓰기(0.5), 없는 OCR 신뢰도 날조,
  계수 3종 변조, floor 리터럴 추가, 호출을 `_exec` 밖 헬퍼로 이동, 관측 필드 제거, 코치 경로 게이트 제거,
  미등록 신규 소비자·호출자 6종(별칭·패키지 수준 import 포함), 죽은 등록·스캔 루트 오지정 2종 →
  **RED 기대 19건 전부 검출**, 대조군 2건(import만 하고 호출 안 함 / 이름만 같은 다른 `diagnose`)은
  의도대로 GREEN.
- **2차 7종**(shadow 레코드 연결): 집계 raw/kept 교차·emit 누락 2종·거부 결과 합산·kind 무시·상수 반환 →
  전건 검출. 처음엔 "kind가 match가 아닌 결과도 합산"이 **살아남았다** — 픽스처가 그 절의 반례(다른
  종류의 결과가 숫자를 달고 있는 경우)를 한 번도 밟지 않았기 때문이며, 반례를 픽스처에 넣어 해소했다.

## 6. 남은 한계 (범위 밖 — acceptance ⑤ 동결 또는 별도 추적)

1. **게이트 플래그 소비**: 하네스는 `attribution_unclear`·`no_confident_match`를 *기록만* 하고 반응하지
   않는다. 코치 경로는 미확인 전사(`low_quality`)·귀속 불명(`attribution_unclear`)이면 +1 지지도 −1
   반박도 만들지 않는다(`api/coach.py` 증거 적재부). 하네스 `log_evidence`가 같은 보류를 해야 하는지는
   **판정이 필요하다** — 후속 태스크 `MISC-60-harness-gate-flag-consumption-judgement`로 등재했다(① 실측 → ② 판정 → ③ 집행 순).
2. **judge 필터·반박 조건(`reject_refuted`)**: 코치는 품질 게이트 앞에 적용하지만 하네스는 아니다. judge
   기본값은 acceptance ⑤가 범위 밖으로 동결했다.
3. **게이트 값 자체**: floor 0.65와 `intervene.py`의 0.5 임계는 변경하지 않았다(⑤).
