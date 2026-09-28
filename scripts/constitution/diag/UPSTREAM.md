# scripts/constitution/diag — 진단 도구 출처 기록

출처: Kiki가 2026-09-27에 준 「260927 EOS 통합정밀진단」 묶음의 `tools/` 폴더(표준 라이브러리만 쓰는
읽기 전용 진단 도구 7종 + 예시 설정 2종). 태스크 `CONST-02`.

## 무엇을 바꿨나

- **형식만** 바꿨다: black(줄 길이 100)·미사용 import 3건 제거. 동작은 그대로다.
- 동작 동일성은 실측했다 — 원본과 벤더링본을 이 저장소 전체에 각각 돌려 `diag_integrity.json`·
  `diag_rules_scan.json`을 비교했고, 실행 시각 필드를 뺀 내용이 **완전히 같았다**(2026-09-28).
- 고치면 동작이 바뀔 수 있는 린트 4종(람다 대입·한 글자 변수명·zip strict·raise from)과 긴 주석
  줄은 루트 `pyproject.toml`의 `[tool.ruff.lint.per-file-ignores]`에서 **이 폴더에만** 허용했다.

## 이 저장소가 더한 것

| 파일 | 뜻 |
|---|---|
| `whymath_layers.json` | 모듈 경계 설정 — `src/backend/pyproject.toml`의 import-linter 계약 2개(EOS Core→Math Adapter 금지)를 옮김 |
| `whymath_layers_7layer.json` | 7계층 단방향 계약(api > l6 > l5 > l4 > l3 > l2 > l1 > schema)을 옮긴 보조 설정 |
| `../run_baseline.py` | 7종을 고정 인자로 한 번에 돌리는 러너 — 인자의 단일 원천 |

## 원본 파일 지문 (sha256)

| 파일 | sha256 |
|---|---|
| `_diagcommon.py` | `9ed8901219e3f4ef834fbe9e7523f92ea481b6a85f941afe9864c23eabe5aab3` |
| `diag_content.py` | `59bb871d6ff2650bf629f748498d58ecdb54ce502976b43068040d18d07a40ee` |
| `diag_freeze.example.json` | `df988b082680da912ba74e63597e95c92c99fd6355f2a54bd4d1c38e1c38fd35` |
| `diag_git.py` | `c58a501c47b28d4111e3f6dd63e8c257b776d4528b1dd2b09427db3f36f64c9b` |
| `diag_graph.py` | `e58b21b3ca458157199b4c57f7fc554a7415e8f31bc615fe2b12b93854667787` |
| `diag_imports.py` | `99dba32c353f4e608c11a09c708d7203cb822016ba8cff57087c567a342f5ec0` |
| `diag_integrity.py` | `bb3027c4182928de452e4fc0e87f90a9ba9ea5b2f6471b987b55ef3f0a05879a` |
| `diag_layers.example.json` | `2d42ab23efad03449115e8d0908980129f40220f3484cb88acf9edf934f0860b` |
| `diag_merge.py` | `4b87e3c9909b8d8199e6f1f598628d89eb22237b0b7ac3ff575d44203c6d1f8b` |
| `diag_rules_scan.py` | `1afe4099c12284836413ddf6e55b700fdfa2a3635099c09084b48796909437b2` |

## 재동기화 절차 (Kiki가 새 묶음을 주면)

1. 새 원본 sha256을 위 표와 비교한다. 같으면 할 일이 없다.
2. 다르면 새 원본을 이 폴더에 덮어쓴 뒤 black·미사용 import 정리만 다시 한다(동작 변경 금지).
3. 원본과 벤더링본을 같은 저장소에 돌려 결과 JSON이 같은지 확인한다(시각 필드 제외).
4. `python3 -m pytest tests/infra/test_coding_constitution_diag_tools.py`로 스모크를 확인하고 표를 갱신한다.
