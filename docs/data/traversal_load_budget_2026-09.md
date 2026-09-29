# 개념 그래프 traversal 성능 예산 실부하 측정 (S4-01 슬라이스 2)

> **판정 기준: main `6c880b67`** · 정본 `data/corpus/atom_graph_v1/graph.json` sha256
> `1821d31c2614dc1b882b3f9b734736f1f4183e1097105675102c3541363b979f` (슬라이스 1과 같은 스냅샷).
> **판정: PASS** — 전 앵커 2,683 × 탐색 형태 3종 × 동시성 1·8에서 시간 예산 초과 0 · 결과 불일치 0.

- 태스크: `S4-01-math-k12-complete` (슬라이스 2 — acceptance 남은 범위 ⒟)
- 판정 CLI: `src/backend/whymath_backend/harness/traversal_load_probe.py`
- 테스트: `tests/backend/harness/test_traversal_load_probe.py` (판정 로직 · 결함 주입)
- CI 배선: `backend-migrations` 잡 마지막 3스텝(DB 재생성 → 원자 백본 적재 → 판정) ·
  배선 동결 `tests/infra/test_traversal_load_probe_wiring.py`
- 후속(이 슬라이스에서 고치지 않은 것): `REC-13-unbudgeted-prerequisite-routes-time-budget`

---

## 1. 무엇을 판정했나

acceptance 원문 "traversal 성능 예산 실부하 통과"는 실행 단위가 없었다. 예산 가드
(`l2/recommendation_policy.py`의 `ConceptGraphBudget` — 깊이 ≤ 2 · 노드 ≤ 20 · 시간 2.0초)는
코드로 있었지만, **전 그래프 규모에서 그 가드가 얼마나 여유를 두고 버티는지는 측정된 적이 없었다.**
이 슬라이스는 그것을 CLI 종료 코드로 판정되는 형태로 바꾼다.

측정 대상은 서빙 경로에서 `concept_edge`를 읽는 탐색 형태 **전부**다(2026-09-28 전수 조사 —
요청마다 전체 그래프를 읽는 경로는 0건이었다).

| 형태 | 서빙 경로 | 깊이 | 노드 상한 | 시간 예산 |
|---|---|---|---|---|
| `policy_prerequisites` | `/v1/me/next-problem` 정책 | 2 | 20 | 2.0초 (`_within_budget`) |
| `policy_successors` | 같은 정책의 직접 후행 | 1 | 20 | 2.0초 |
| `route_prerequisites_depth5` | `/v1/me/weak-concepts/{id}/*` · 진단 캡처 · 코치 | 최대 5 | 64 | **없음** (2.0초를 참조 기준으로만 사용) |

판정 규칙(종료 코드):

- **exit 0** — 전 앵커 × 전 형태 × 전 동시성에서 시간 예산 초과 0 · 시간 초과·예외 0 ·
  **DB 결과 집합이 `graph.json` 구조 계산과 앵커마다 일치**
- **exit 1** — 위반 1건 이상
- **exit 2** — 측정 불성립(DB 개념 0건 · 코퍼스↔DB 개념 또는 엣지 드리프트 · 접속 실패 · 입력 오류)

결과 집합 대조가 이 도구의 변별력이다. 지연만 재면 "빈 결과를 빨리 돌려주는" 회귀(엣지 적재
누락, 조인 조건 오류)도 통과한다. DB와 무관한 순수 계산과 앵커마다 대조하므로 탐색이
**빠르다**와 **옳다**를 같이 판정한다.

**표본이 아니라 전수다.** 모집단(DB의 전 개념) 전체를 재므로 비율에 Wilson 경계를 씌우지 않는다.
판정 대상 비율(초과·불일치)은 전부 0건 기준이다.

## 2. 구조 전수 계산 (DB 불요)

`--structural-only`로 재현한다. "원시 행"은 재귀 CTE가 만들어 내는 행 수 = 길이가 깊이 이하인
경로 수다(CTE가 `UNION ALL`이라 diamond에서 같은 선수가 경로 수만큼 중복된다). "선수"는 중복 제거
후 개수다.

| 깊이 | 원시 행 최대 (앵커) | 선수 최대 (앵커) | 선수 0 앵커 | 20 초과 앵커 | 64 초과 앵커 |
|---|---|---|---|---|---|
| 1 | 4 (`10공수1-02-06-2`) | 4 | 915 | 0 | 0 |
| 2 | 12 (`12대수01-06-1`) | 11 | 915 | **0** | 0 |
| 5 | 114 (`10공수2-03-05-1`) | 55 | 915 | 131 | **0** |

직접 후행: 최대 7 (`12미적Ⅰ-02-04-1`) · 20 초과 0.

**"작동한 비율"(CLAUDE.md 원칙)을 정직하게 적는다:**

- 정책 노드 예산(20)은 현재 규모에서 **한 번도 발동하지 않는다** — 깊이 2의 최대가 11이다.
  가드는 있지만 지금은 여유가 약 1.8배이며 잘라 내는 일이 없다.
- 라우트 노드 상한(64)도 발동하지 않는다 — 깊이 5의 최대가 55다(여유 약 1.16배, **가장 얇은 여유**).
- 전 앵커의 34.1%(915/2,683)는 선수가 0이다. 이 앵커들에서는 선수 탐색이 빈 결과를 정상으로 낸다
  — 판정의 결과 대조는 이 경우에도 "기대 0건 = 결과 0건"으로 일치를 확인한다.

### 2.1 제안 엣지 24건 병합 시 (S4-60 병합 판단 입력)

`--structural-only --extra-edges data/corpus/atom_graph_v1/cross_band_edges_university_v1.json`:

| 깊이 | 선수 최대 | 20 초과 앵커 | 64 초과 앵커 |
|---|---|---|---|
| 2 | 11 (변화 없음) | 0 (변화 없음) | 0 |
| 5 | 55 (변화 없음) | 131 → **137** (+6) | 0 |

24건 병합은 정책 예산(깊이 2)에 영향이 없고, 깊이 5 라우트에서 20노드를 넘는 앵커가 6개 늘 뿐
64 상한에는 닿지 않는다. **부하 관점에서 병합을 막을 사유는 없다** — 병합 여부는 여전히
교육적 타당성 게이트(`G-s401-uni-boundary-edge-review`)가 판정한다.

## 3. 실 PG 측정

환경: 이 세션 컨테이너(Intel Xeon 2.10GHz 4코어) · PostgreSQL 16.13 + pgvector · 마이그레이션
head 적용 후 `l1.atom_graph.populate`로 원자 백본 전량 적재(개념 2,683 · 엣지 2,210). CI 러너는
다른 하드웨어이므로 **절대 지연값은 환경마다 다르다** — 판정은 서빙 코드가 정한 2.0초 예산만 쓴다.

| 형태 | 동시성 | p50 | p99 | 최대 | 예산 초과 | 불일치 |
|---|---|---|---|---|---|---|
| policy_prerequisites | 1 | 2.5ms | 4.8ms | 113ms | 0 | 0 |
| policy_prerequisites | 8 | 14.3ms | 119ms | 169ms | 0 | 0 |
| policy_successors | 1 | 1.1ms | 2.9ms | 10ms | 0 | 0 |
| policy_successors | 8 | 6.9ms | 10.9ms | 28ms | 0 | 0 |
| route_prerequisites_depth5 | 1 | 2.5ms | 5.2ms | 39ms | 0 | 0 |
| route_prerequisites_depth5 | 8 | 15.8ms | 127ms | 174ms | 0 | 0 |

최악 지연 174ms · 예산 2,000ms · **여유 11.5배**. 탐색 전 CLI 판정 소요 약 34초.

추가 탐색 측정(판정 CLI 밖, 참고): 깊이 5 선수 탐색을 동시 32요청으로 돌리면 p99 269ms ·
최대 500ms였다. 한 프로세스의 이벤트 루프 경합이 포함된 값이며 여전히 2.0초 안이다.

## 4. 판정 도구의 변별력 증명

**단위 수준 — 뮤테이션 14종 전건 RED + 정상 대조군 GREEN** (적용 확인 · 원복 sha256 동일 단언):
불일치 판정 제거 · 예산 초과 판정 제거 · 샘플 수 판정 제거 · 예산 단위 오류(초↔밀리초) · 개수 판정
제거 · 기대 밖 원소 판정 제거 · 엣지 드리프트 판정 제거 · 깊이별 dedup(`UNION` 의미로 오변경) ·
시간 초과 미계상 · 노드 예산 미적용 · 개념 0건 판정 제거 · 엣지 쌍 dedup 제거 · 중복 결과 판정 제거 ·
예외 판정 제거.

1차 실행에서 "기대 밖 원소 판정 제거"가 **살아남았다** — 픽스처 `["A","B","Z"]`가 개수 판정에도
걸려 그 절을 단독으로 밟지 않았다. 개수는 맞고 원소만 틀린 반례 `["A","Z"]`를 추가해 RED로 바꿨다.

**실 PG 수준 — 결함 주입 2종** (이 세션의 일회용 DB에서 주입 후 원복):

| 주입 | 기대 | 실측 |
|---|---|---|
| 엣지 1건 삭제 | exit 2 (엣지 드리프트) | exit 2 · "DB 2209 · 코퍼스 2210" |
| 엣지 1건의 후행 끝점을 다른 개념으로 교체(개수 불변) | exit 1 (결과 불일치) | exit 1 · 불일치 정책 6 · 후행 1 · 깊이 5 13 |
| 원복 후 재측정 | exit 0 | exit 0 |

## 5. 이 슬라이스가 닫지 않는 것 (정직 고지)

- **예산 밖 경로에 예산을 거는 일** — `/v1/me/weak-concepts/*` 선수 탐색(깊이 최대 5)과 코치·진단
  캡처 경로에는 시간 예산이 없고, `GET /v1/concepts/{id}/edges`에는 행 상한이 없다. 현재 규모에서
  실측상 안전하다는 것(위 §3)과 예산이 걸려 있다는 것은 다른 주장이다. 재귀 CTE가 `UNION ALL`이라
  그래프가 조밀해지면 SQL이 모든 경로를 만든 뒤에야 파이썬 상한이 적용된다. → `REC-13`
- **LLM 컨텍스트용 subgraph** — 서빙 경로에 개념 그래프를 LLM에 넣는 탐색은 현재 없다
  (`harness/wh1_llm_policy.py`는 그래프 탐색 없이 컨텍스트 노드 수만 20으로 자른다). 그런 경로가
  생기면 이 판정 CLI에 형태를 추가해야 한다.
- **S4-01의 다른 남은 범위** ⒜ 대학 과목 간 32개 고립 사슬 ⒝ 대학 문항 0 ⒞ K-12 0문 4과목·초3~4
  ⒠ 나머지 26개 대학 과목의 경계 진입 — 이 슬라이스와 무관하게 그대로 남는다. 다만 ⒜·⒠와 S4-60
  병합이 그래프 밀도를 올리는 방향이므로, 이후 저작분은 `--structural-only --extra-edges`로 병합 전
  부하를 먼저 확인할 수 있다.

## 6. 재현

```bash
# 저장소 루트 · WHYMATH_DATABASE_URL 설정된 실 PG (마이그레이션 head)
python -m whymath_backend.l1.atom_graph.populate --graph data/corpus/atom_graph_v1/graph.json
python -m whymath_backend.harness.traversal_load_probe --graph data/corpus/atom_graph_v1/graph.json --concurrency 1,8 --out traversal_load_report.json
# DB 없이 구조 계산만 (제안 엣지 겹치기)
python -m whymath_backend.harness.traversal_load_probe --structural-only --extra-edges data/corpus/atom_graph_v1/cross_band_edges_university_v1.json
```
