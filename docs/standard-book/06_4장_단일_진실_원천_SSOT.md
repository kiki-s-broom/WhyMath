# 4장. 단일 진실 원천 (SSOT)

한 줄 요약: **같은 정보는 딱 한 곳에만 원본으로 두고, 나머지는 거기서 자동으로 만들거나 참조한다.**

#### ① 증상

- 개념 노드 이름을 DB, JSON 파일, 코드 상수 **세 곳**에 적었다가 한 곳만 고쳐서 어긋남
- 문서에는 "545개 노드"라고 적혀 있는데 실제 DB에는 548개
- Flutter 앱(Dart)과 백엔드(Python)에 같은 문항 구조를 각각 손으로 정의 → 필드 하나 추가할 때 한쪽을 빠뜨림
- 성취기준 코드 표기가 파일마다 다름 (`[9수01-01]` / `9수01-01` / `M9-01-01`)
- 어느 파일이 최신인지 몰라 파일명에 `_최종`, `_최종2`, `_진짜최종`이 붙음

#### ② 근본 결함

같은 지식의 **복사본이 여러 개**이고, 복사본끼리 맞추는 일을 **사람이 손으로** 합니다. 복사본 수가 N개면 어긋날 수 있는 쌍이 N×(N−1)/2개로 늘어납니다. 3곳이면 3쌍, 5곳이면 10쌍입니다.

#### ③ 업계 표준

『실용주의 프로그래머』(1999)의 **DRY 원칙**(Don't Repeat Yourself)이 원조입니다. 요지는 "시스템 안의 모든 지식은 하나의 명확하고 권위 있는 표현만 가져야 한다"입니다. 흔히 "코드 중복 금지"로 오해하지만, 원래 뜻은 **지식의 중복 금지**입니다. 코드 모양이 비슷한 것은 괜찮고, 같은 사실이 두 곳에 따로 적힌 것이 문제입니다.

| 기법 | 방법 | 대표 도구 |
|---|---|---|
| 스키마 우선 코드 생성 | 데이터 구조를 스키마 파일 하나로 정의 → 각 언어 코드를 자동 생성 | JSON Schema → Python: `datamodel-code-generator` / Dart: `quicktype`; API 전체는 OpenAPI |
| 참조 | 복사 대신 원본을 가리킴 | DB 외래키, 설정 파일 include |
| 생성 문서 | 문서 속 숫자·표를 원본에서 자동 계산해 채움 | 스크립트로 README 통계 갱신 |
| 파생물 표시 | 자동 생성 파일 맨 위에 "직접 수정 금지" 표식 | `# 자동 생성 — 원본: schemas/item.schema.json` |
| 신선도 검사 | CI에서 재생성해 보고 커밋된 것과 다르면 실패 | `git diff --exit-code` |

#### ④ 원전

- Andrew Hunt·David Thomas, 『실용주의 프로그래머』 20주년 기념판(2019), 9항목 "DRY—중복의 해악"
- JSON Schema 명세 (json-schema.org, Draft 2020-12)

#### ⑤ WhyMath 적용 — 데이터 종류별 원본 결정표

핵심 판단 기준은 이것입니다. **사람이 검토하고 변경 이력(diff)을 봐야 하는 콘텐츠는 git 안의 텍스트 파일이 원본**이고 DB는 그것을 적재한 사본입니다. **학습자가 만들어 내는 데이터는 DB가 원본**입니다. 이 구분을 섞으면 "DB에서 직접 고친 개념 노드"와 "파일에서 고친 개념 노드"가 충돌합니다.

| 데이터 | 원본(SSOT) | 파생물 | 금지 사항 |
|---|---|---|---|
| 성취기준 | 교육부 고시 원문 (2022 개정, 고시 번호·판 명시) | 추출 엑셀 → 적재 테이블 | 원본 버전 표기 없이 추출본만 보관 |
| 개념 그래프 545노드·선수 관계 | git의 YAML/JSON 파일 | PostgreSQL `concept_nodes` 적재본 | DB에서 직접 수정 |
| 오개념 400항목·op-code 8종 | git의 YAML 파일 | DB 적재본, 앱 번들 | 코드 안에 op-code 문자열 하드코딩 |
| 문항 데이터 구조 | `schemas/item.schema.json` 한 개 | Python 모델, Dart 모델 (자동 생성) | 각 언어에서 손으로 정의 |
| 학습자 응답·BKT 상태 | PostgreSQL | 분석용 내보내기 | 파일로 복사해 수정 후 되돌려 넣기 |
| 저작권 허용 기준 | 「MathScope 저작권 종합가이드 v2.0」 | 게시 게이트의 허용 등급 목록 | 코드에 등급을 따로 정의하고 가이드와 대조 안 함 |
| EOS 기능 목록 382항목 | `WhyMath_EOS_2026_12월출시_기능재배치.xlsx` | TODO·이슈 | 이슈 트래커와 엑셀을 각각 원본으로 운영 |
| 실행 순서 | `pipeline.yaml` (1장) | README의 순서 설명 | README에만 순서 기록 |

> **엑셀이 원본일 때의 주의**
>
> 엑셀(.xlsx)은 git에서 변경 내용(diff)을 볼 수 없습니다. 기능 목록처럼 자주 바뀌고 이력이 중요한 원본은 **CSV나 YAML로 옮기고 엑셀은 보기용 파생물로 만드는 것**이 업계 관행입니다. 당장 옮기기 어렵다면 최소한 원본이 엑셀이라는 사실과 파일 위치를 CONTEXT 문서에 한 줄로 명시하세요.

**신선도 검사 (Bash)**

```text
#!/usr/bin/env bash
# scripts/check_generated.sh — 파생 코드가 원본 스키마와 일치하는지 검사 (CI에서 실행)
set -euo pipefail    # 오류·미정의 변수·파이프 실패 시 즉시 중단

# 1) 원본(스키마)에서 Python 모델을 다시 생성
datamodel-codegen \
  --input schemas/item.schema.json \
  --input-file-type jsonschema \
  --output backend/models/item.py

# 2) 커밋된 파일과 다르면 실패 → "스키마만 고치고 재생성을 안 했다"를 잡아냄
if ! git diff --exit-code backend/models/item.py; then
  echo "❌ 파생 코드가 원본과 어긋납니다. 재생성 후 함께 커밋하세요."
  exit 1
fi
echo "✅ 파생 코드 최신 상태"
```

**문서 숫자 검사 (pytest)**

```python
# tests/test_docs_numbers.py — 문서의 숫자가 실제와 같은지 검사
import re
import yaml

def test_concept_count_matches_docs():
    with open("content/concept_graph.yaml", encoding="utf-8") as f:
        actual = len(yaml.safe_load(f)["nodes"])           # 원본에서 센 실제 개수
    with open("README.md", encoding="utf-8") as f:
        m = re.search(r"개념 노드\s*(\d+)개", f.read())      # 문서에 적힌 숫자
    assert m, "README에 '개념 노드 N개' 표기가 없음"
    assert int(m.group(1)) == actual, f"문서 {m.group(1)}개 ≠ 실제 {actual}개"
```

#### ⑥ 자동 검사와 목표 강도

| 장치 | 강도 |
|---|---|
| 자동 생성 파일 신선도 검사 (CI) | L5 |
| 문서 숫자 검사 테스트 (CI) | L5 |
| 적재 스크립트만 DB 콘텐츠 테이블에 쓰기 권한 보유 (앱·수동 접속 계정은 읽기 전용) | L5 (DB에서 직접 수정 원천 차단) |
| 성취기준 코드 형식 정규식 검사 `^\[\d{1,2}[가-힣]+\d{2}-\d{2}\]$` (예시 — 실제 형식은 교육과정 원문 기준으로 확정) | L5 |
