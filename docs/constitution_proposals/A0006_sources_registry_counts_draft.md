# 개정 기록 A0006 — 원본 등록부의 코퍼스 건수를 사실 표 참조로 (초안)

- 상태: **초안 — 채택 전** (헌법 제11조: 개정은 사람만 한다. 이 문서는 AI가 작성한 초안이다)
- 일자: 2026-10-25 (초안 작성) · 채택일: ____ (Kiki 기입)
- 개정자: Kiki (서명란: ____)
- 선행: 없음. A0004·A0005 초안과 독립이다(`rules.yaml`의 서로 다른 줄을 고친다).
- 대상: `constitution/rules.yaml` 원본 등록부(sources)의 `version` 문구 2줄
- 태스크: `OPS-154` (코퍼스 사실 단일 원천) · 판정 기준: 브랜치 `claude/corpus-facts-single-source`(main `faf740c5` 기준)

## 사유

`OPS-154`가 코퍼스 건수를 원본 파일에서 계산하는 레지스트리(`scripts/analysis/corpus_facts.py`)와 생성
문서 `docs/data/corpus_facts.md`를 만들었다. 문서는 숫자를 손으로 적지 않고 표식으로 인용하며, 원본이
바뀌면 `sync` 한 번으로 모든 인용이 따라간다. CI(`tests/infra/test_corpus_facts.py`)가 어긋남을 막는다.

`constitution/`은 읽기 전용(제9조)이라 이 도구가 고칠 수 없고, 검출기도 범위에서 뺐다. 그런데 등록부에
손으로 적힌 건수가 이미 낡았다.

| 줄(현재 main) | 등록부 문구 | 실제(원본에서 센 값) |
|---|---|---|
| `rules.yaml` 1013 | `원자 백본 2,683노드·2,210엣지` | 2,683노드 · **2,278엣지** (KG-12 이후 · 2,210은 KG-09 이전 값) |
| `rules.yaml` 1018 | `M-id 카탈로그 843건` | 843 (지금은 맞다 — 다음 저작에서 낡는다) |

숫자만 2,278로 바꾸면 다음 정본 교정 때 같은 일이 되풀이된다. 그래서 **건수를 지우고 사실 표를 가리키게**
하는 것을 권한다. `version`이 말해야 하는 것은 "어느 판의 원본인가"이고, 건수는 그 판에서 계산되는 값이다.

## 정정안

```yaml
  - name: 개념 그래프 (노드·선수 관계)
    path: data/corpus/atom_graph_v1/graph.json
    version: "atom_graph_v1 — 원자 백본(건수 정본: docs/data/corpus_facts.md 의 atom_graph.nodes·atom_graph.edges) (legacy 437개념 concept_graph_v1 은 감사 전용 스냅샷)"
```

```yaml
  - name: 오개념 DB·오답 op-code
    path: data/corpus/misconceptions_v1/misconceptions.json
    version: "M-id 카탈로그(건수 정본: docs/data/corpus_facts.md 의 misconceptions.count) · kebab 탐지 카탈로그 67종(정본 docs/prompts/misconception_diagnosis.md) · op-code 10종(l4/misconception/distractor.py)"
```

- 바뀌는 것: 두 항목의 `version` 문자열뿐. `name`·`path`·`derived`·규칙(R*) 블록은 그대로다.
- 대안(숫자만 갱신): 1013줄의 `2,210`을 `2,278`로. 이 경우 정본이 바뀔 때마다 개정이 필요하다.
- 덧붙여 알림(이 개정 범위 밖): kebab 탐지 카탈로그 수가 문서마다 다르다(ADR-009 72 · `rules.yaml`·A0003 67 ·
  04·04e·테스트 64). 코퍼스 파일이 아니라 코드 상수라 `OPS-154` 레지스트리에 넣지 않았다.

## 채택 후 확인

`python3 scripts/analysis/corpus_facts.py check` — 등록부는 검출기 범위 밖이라 결과가 바뀌지 않는다.
`python3 scripts/constitution/audit_ratchet.py` 의 종료 코드·차단 건수가 채택 전과 같아야 한다(문자열만 변경).
