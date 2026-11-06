# P3-102 — 운영 DB 오개념 서명 결손 처분: 원자 오개념 적재 (2026-11-05)

> **판정 기준: main `036286a1`** + 미머지 PR #1843(P3-17 판정 · 이 태스크를 등재한 브랜치 `afa8592e`) + 이 PR.
> 운영 DB(Kiki 머신 `whymath-pg` · 5433) 값은 이 세션이 직접 재지 못했다. 처분 전 값은 EOS-194 §5의 Kiki 실행 기록에서
> 가져왔다(`docs/reviews/eos194_acceptance3_2026-10-31.md` §5 · 측정 기준 main `920cc624`).

## 1. 결정 (인수 조건 ①)

**Kiki 결정(2026-11-05 채팅): A안 — 원자 유래 오개념 일괄 적재.**

| 안 | 내용 | 채택 |
|---|---|---|
| A | 원자 개념마다 등록된 오개념(`ATOM:<code>`)을 `misconception_catalog`에 적재 → 문항이 개념 `code`로 서명을 상속(P3-99 경로) | **채택** |
| B | 903건 문항마다 서명 직접 저작 | 미채택(재저작·검수 비용) |
| C | 903건을 발행 범위에서 제외 | 미채택(노출 문항 대부분이 배포 없는 수정 대상에서 빠짐) |

근거: 리허설 DB(운영 모사 2,563행)에서 적재 뒤 `PUBLISHABLE` 0 → 861, 남은 118건은 전부 오개념 유발 슬롯 문항으로
규칙상 정상 거부(`docs/reviews/p3_99_atom_inheritance_rehearsal_2026-11-04.md` §3).

## 2. 무엇을 바꿨나

EOS-194 런북 [C2](`docs/ops/eos194_publish_measure_runbook.md`)의 실행 조건.

- 이전: `ATOM_MISCONCEPTION_ROWS=0` **그리고** `PUBLISHABLE=0`일 때만 실행. 운영은 `PUBLISHABLE=76`이라 11/05 실행에서 스스로
  거부했다(쓰기 0).
- 이후: `ATOM_MISCONCEPTION_ROWS=0`이면 `PUBLISHABLE` 값과 무관하게 실행. 원자 행이 이미 있으면 거부(재적재 방지 축 유지).
  백업 선행·`mis_id` 멱등 upsert·거부 시 이유 출력은 그대로다.
- 추가: 적재 전 [C] 증거를 `preflight_before_atomload.kv`로 복사한다. 다시 돌린 [C]가 `preflight_before.kv`를 덮어쓰기 때문이다.

production code 변경 0. 적재기(`l1/misconception/populate_atom.py`)·발행 게이트(`l3/problem_metadata_evidence.py`)는 손대지 않았다.

### 검증

- `tests/infra/test_p3_102_atom_load_guard.py`(신규 7건) — 실행 조건에 `PUBLISHABLE` 항 없음 · `$AtomRowsBefore -eq 0` 항 있음 ·
  백업·적재 줄이 가드 가지 안에만 있음 · 적재 후 기대 행 수가 코퍼스 정본(`atom_graph.atoms`)과 같음.
- 주입 검증: `PUBLISHABLE` 조건 부활 · 원자 행 0 조건 삭제 · 기대 행 수 어긋남 3종을 테스트 안에서 주입해 각각 RED를 확인한다
  (주입 적용 여부를 `mutated != original`로 먼저 단언). 별도로 `if ($AtomReady)`를 `if ($true)`로 바꾼 주입은 새 테스트가 RED로
  잡았다. 정적 스캐너 `scripts/ops/check_runbook_blocks.py`는 이 주입을 통과시켰는데, 적재 줄이 두 번째 변수(`$ABackupOk`)로
  가드돼 있어서다 — 스캐너 docstring의 "변수 경유" 한계에 해당하는 이미 알려진 사각이다.
- `check_runbook_blocks.py` 전체 exit 0 · `tests/infra/test_runbook_write_guard.py` 포함 57 passed.

## 3. 알아 둘 영향

- **튜터 탐색 후보가 늘어난다.** `api/coach.py`의 웜스타트(`l4/misconception/warmstart.py`)가 원자 코드로 카탈로그를 조회하므로,
  적재 뒤에는 원자 오개념도 튜터의 "의심해 볼 오개념" 후보가 된다(`wh1_primary_enabled` 기본 True). 탐색 표적 전용이고 코칭
  문맥에 미리 넣지는 않는다(reactive 유지). 원자 오개념 적재기가 원래 이 소비처를 위해 만들어졌다.
- **상속은 겨냥 보증이 아니다.** 원자마다 오개념이 1건이라 변별력이 낮다. "개념에 오개념이 등록돼 있다"는 뜻이지 그 문항이 그
  오개념을 노린다는 뜻은 아니다(P3-99 §2 알려진 한계).
- **되돌리기**: [C2]가 만든 `eos194_atomload_before.dump`로 복원한다.

## 4. Kiki 실행 순서 (인수 조건 ②)

**선행**: PR #1843 → 이 PR 순서로 main에 머지된 뒤 실행한다([B]가 `origin/main` 기준 임시 worktree를 만든다).

EOS-194 런북에서 **[A] → [B] → [C] → [C2] → [C] 다시 → [H]** 만 실행한다. 이번 목적은 재측정이라 [D]~[G](발행 측정)는
건너뛴다. 다시 돌린 [C]가 `PREFLIGHT_OK=True`를 내도 [D]로 가지 않는다.

1. **과제 명칭**: 운영 DB 원자 오개념 1,823행 적재 후 발행 가능 문항 재측정.
2. **목적**: 오개념 서명 결손 903건을 발행 가능하게 만들고, 그 효과를 숫자(`PUBLISHABLE` 전후)로 남긴다.
3. **절차**: [A] Docker 확인 → [B] 임시 worktree → [C] 적재 전 점검(`ATOM_MISCONCEPTION_ROWS=0`·`PUBLISHABLE=75` 근처 기대) →
   [C2] 백업 후 적재(수십 초) → [C] 다시(적재 후 점검) → [H] worktree 정리.
4. **성공 기준**: [C2] `ATOM_LOAD_OK=True`·`ATOM_ROWS_AFTER=1823`. 다시 돌린 [C]에서 `ATOM_MISCONCEPTION_ROWS=1823`·
   `SCAN_TRUNCATED=False`·`PUBLISHABLE`이 적재 전보다 큼. 실패 신호: [C2]가 `WRITE_REFUSED=True`면 이유 줄의 False 항목을
   그대로 전달한다.
5. **실행 환경**: Phaiakes9 · Windows PowerShell · `C:\Users\kiki\Desktop\__AI\WhyMath` · Docker Desktop과 `whymath-pg` 가동.
6. **창 구분**: 새 PowerShell 창 하나에서 [A]부터 [H]까지 같은 창으로 이어서 붙여넣는다(변수를 이어 쓴다). 서버 점유 없음.

전달할 것: 두 [C] 화면 전체(또는 `work\eos194_<sha>\preflight_before_atomload.kv`·`preflight_before.kv`)와 [C2] 화면.

## 5. 결과 (인수 조건 ②·③ — 2026-11-05 Kiki 실행)

> **판정 기준: main `0877e573`**(#1847 머지 · 바뀐 [C2]) · 운영 DB `whymath-pg`(5433) · 임시 worktree `WhyMath_wt_0877e573`
> · 증거 파일: Kiki 머신 `work\eos194_0877e573\preflight_before_atomload.kv`(처분 전) · `preflight_before.kv`(처분 후 — 다시 돌린 [C]가 덮어씀)
> · 백업 `eos194_atomload_before.dump`(약 2.22MB · `pg_restore -l` 통과)

| 값 | 처분 전 | 처분 후 |
|---|---|---|
| `ATOM_MISCONCEPTION_ROWS` | 0 | **1,823** |
| `EXPOSED_WITH_VERIFIED_HINT` · `SCANNED` · `SCAN_TRUNCATED` | 977 · 977 · False | 977 · 977 · False |
| `PUBLISHABLE` | 74 | **965** |
| `NOT_PUBLISHABLE_REASONS` | `{"misconception_signature": 903}` | `{"misconception_signature": 12}` |

[C2] 출력: `ATOM_READY=True` · `ATOM_BACKUP_OK=True` · 적재기 "atom ①오개념 적재 완료: 1823건" · `ATOM_LOAD_EXIT=0` ·
`ATOM_ROWS_AFTER=1823` · `ATOM_LOAD_OK=True`. 노출 문항(2,563)·포인터(2)·발행 판(2)은 적재 전후 같다 — 적재는 카탈로그만 바꿨다.

**판정**: 발행 게이트를 오개념 서명 결손으로 못 지나던 903건 중 891건이 풀렸다. 검사한 977건 중 965건(98.8%)이 발행 가능하다.

**정직한 단서**

- **남은 12건은 원인을 확인하지 않았다.** 리허설(P3-99)에서는 남은 118건이 전부 오개념 유발 슬롯 문항(`p3-slot:misconception_trigger`
  — 규칙상 문항 자체 서명 필요)이었다. 운영에서 12건인 것은 운영 DB의 그 슬롯 문항 중 검증 힌트를 가진 것이 적어서로 *보이지만*
  문항별 출처는 측정하지 않았다. 이 12건을 발행하려면 문항 단위 서명이 필요한지 확인해야 한다(후속 후보).
- **처분 전 값이 EOS-194 §5(PUBLISHABLE 76 · 힌트 979)와 다르다.** 같은 날 두 차례 [D]~[F](발행 측정)가 추가로 실행돼 문항 2건이
  발행되며 후보에서 빠졌다(76 → 75 → 74). 그중 1건(`06efd327-0510-5ddd-bfb9-3a34f57a6dba` · 판 `09e112be-…`)은 이 태스크
  안내 중에 [D]~[F]가 함께 붙여넣어져 생겼다 — 측정용 staff·learner 계정 2개와 시도 1건이 함께 남았다. 되돌리기 [G]는 실행하지 않았다.
- **바뀐 가드가 실제로 거부하는 것도 운영에서 봤다.** #1847 머지 전 옛 블록을 두 번 실행했을 때 `PUBLISHABLE=75`·`74`에서
  `WRITE_REFUSED=True`·`ATOM_ROWS_AFTER=0`으로 쓰기 없이 멈췄다.
- §3의 영향(튜터 웜스타트 탐색 후보에 원자 오개념 편입)이 이 시점부터 운영에서 유효하다.
