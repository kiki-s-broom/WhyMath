# OPS-130 — OPS-50 MoE 파싱 실패 회수 판정 (2026-10-14)

> **판정 기준: `origin/main` `24d8607d`** (2026-10-14 fetch). 이 문서의 "있다/없다"는 전부 이 커밋 기준이며,
> 이식 PR이 머지되기 전까지 아래 산출물은 main에 없다.
> 출처: `docs/reviews/unmerged_branch_audit_2026-10-12.md` §3-① (stray-code 17회차).

## 1. 무엇을 회수했나 (acceptance ①②)

| 항목 | 값 |
|---|---|
| 원 브랜치 | `origin/claude/happy-turing-kmrd5z` head `93861f63` (분기점 `30848ab4`) |
| 이식 방식 | 파일 단위. 통째 머지 금지(34커밋 낡음 — 특히 `MEMORY.md`는 브랜치 쪽은 main 대비 +6/-257줄이라 통째로 쓰면 main에 있는 257줄이 소실) |
| 충돌 판정 | 분기점 `30848ab4` ↔ `origin/main` 사이 변경 **0줄**(`git diff --stat 30848ab4 origin/main -- <3파일>` 빈 출력) → 브랜치 버전을 그대로 가져와도 main 쪽 변경을 덮지 않는다 |
| 이식한 파일 | `harness/quality_tier_moe_accuracy_battle.py`(+542/-68) · `scripts/ops/run_moe_quality_battle.ps1`(+42) · `docs/ops/amd395_local_llm_performance.md`(+19) · `data/audit/ops-50-parse-failure-reclassification.txt`(신규 18줄) · `tests/backend/harness/test_quality_tier_prompt_variants_ops50.py`(신규 · 26건 + OPS-130 보강 4건) |
| 이식하지 않은 파일 | `backlog/tasks/OPS-50.yaml`(OPS-50은 소유 태스크로 남는다) · `backlog/events/*.ndjson`(브랜치 이벤트 대장) · `MEMORY.md`(6줄만 새로 씀) |
| 번호 | 원 번호 OPS-50 미재사용 — 이 태스크는 OPS-130 |

### 이식 후 실측 (전부 이 세션에서 실행 · 종료 코드로 판정)

| 검사 | 결과 |
|---|---|
| `ruff check`(src + 신규 테스트) / `black --check --line-length 100` | exit 0 / exit 0 |
| `mypy --strict whymath_backend` | exit 0 (785 파일) |
| `lint-imports` | exit 0 (계약 4 kept) |
| `scripts/ops/check_ps_scripts.py`(CI 차단 스텝) | exit 0 · 569건 / 위반 0 · `run_moe_quality_battle.ps1` `[ok]` |
| `scripts/ops/check_provider_seat_contract.py` | exit 0 · 위반 0 |
| `scripts/ops/cp949_guard.py` | exit 0 · 위반 0 |
| 이식 테스트 + 인접 테스트(`test_quality_tier_moe_accuracy_battle`·`test_provider_accuracy_battle`·`test_authoring_traffic_surface_inventory`) | 108 passed → 보강 후 이식 테스트 30 passed |
| `provider.generate` 호출 지점 | 소스 grep 결과 실호출 **1곳**(`_evaluate_one` 루프, 522행) + docstring 1건. 브랜치의 "1곳 유지" 주장 재확인 |
| `--analyze-audit` 실행 출력 ↔ 보관 `ops-50-parse-failure-reclassification.txt` | 바이트 동일(`diff` 무출력) |

**전체 스위트는 돌리지 않았다.** 변경은 이 모듈·신규 테스트·문서·PS 스크립트에 한정되고 다른 모듈이 이 파일을 import하는지는
`grep`으로 확인했다(참조 = 테스트 3 · `check_provider_seat_contract.py` · 인벤토리 스크립트 · `.github/branch-cleanup-request.txt`).
순서 의존 오염은 부분 실행으로 볼 수 없으므로 **CI를 최종 판정으로 넘긴다.**

## 2. 집행 지점·변별력 (acceptance ③)

**수집 경로**: 신규 테스트는 `tests/backend/harness/` 아래이고 CI backend 잡이 `cd src/backend && python -m pytest`(bare 호출)로
이 경로를 수집한다. 로컬에서는 pytest 루트 가드의 안내대로 `-c src/backend/pyproject.toml --rootdir=src/backend`로 실행했다.

**뮤테이션**: 브랜치는 "13종 전건 검출"이라고 주장하지만 **13종의 목록은 어디에도 기록돼 있지 않다**(MEMORY·테스트·이벤트 대장 전수 grep 0건).
재현 불가한 주장이므로 이식 코드의 분기에서 **새로 15종**을 세우고 주입했다. 하네스는 매 주입마다 ①치환 대상이 소스에 정확히 1건인지
②`mutated != original` ③디스크 sha256이 원본과 달라졌는지 ④원복 후 sha256이 원본과 같은지를 단언한다.

| # | 주입 | 1차 | 보강 후 |
|---|---|---|---|
| M1 | 절단 판정 `>=` → `>` | RED | RED |
| M2 | 빈 응답 분류 제거 | RED | RED |
| M3 | 표지 부재 즉시멈춤 제거 | RED | RED |
| M4 | `short_reason` 상한 100 → 1000 | RED | RED |
| M5 | stage2 enum 비움 | RED | RED |
| **M6** | baseline 문항 수 검사 제거 | **생존** | RED |
| **M7** | baseline 정답지 대조 제거 | **생존** | RED |
| M8 | 분석 0건 스캔 허용 | RED | RED |
| M9 | 미분류율 상한 방향 반전 | RED | RED |
| M10 | `worst` 정책 무력화 | RED | RED |
| M11 | `reason_first` 필수키 축소 | RED | RED |
| M12 | `latex_check` 부가문 미적용 | RED | RED |
| M13 | `few_shot` 부가문 미적용 | RED | RED |
| **M14** | 후보에 변형 미전달(`main()` 배선) | **생존** | RED |
| **M15** | `stage_split` 1단계 프롬프트 키 변경 | **생존** | RED |

1차에서 **4건이 생존**했다. 원인과 처치:

- **M6**: 길이 불일치를 `zip(strict=True)`가 다른 메시지로 잡아 테스트가 통과(동치에 가까움). → 사용자에게 의도를 말하는 `재사용 불가` 메시지를 `match`로 고정.
- **M7**: 테스트 픽스처가 "slug는 같고 정답지만 다른" 감사 행을 만들지 않아 그 절을 밟지 않았다(slug 절이 먼저 터짐). → 정답지만 바꾼 행을 만드는 테스트 추가.
- **M14**: `main()`이 후보에 변형을 넘기는지 보는 테스트가 없었다(변형 6종은 `evaluate_model`을 직접 호출해 검증). → `main()` 경유로 후보=`few_shot`·기준=`None`을 단언.
- **M15**: 1단계 프롬프트의 출력 규약 문면이 미고정. → 1단계가 `defect_class`를 묻지 않고 2단계가 `has_defect`를 다시 묻지 않음을 단언.

보강 후 **15/15 RED · 생존 0 · 원복 sha256 일치**. 브랜치 주장(13/13)과 직접 비교할 수는 없다(목록 부재).
"브랜치의 13종이 모두 검출됐다"는 **이 회수가 확인한 사실이 아니다.**

## 3. 이 회수가 확인하지 못한 것 (라이브 · OPS-50이 소유)

Phaiakes9(Ollama + `qwen3:30b-a3b`)가 필요한 항목은 이 세션에서 전부 미수행이다.

- 변형 6종 각각의 **실제 파싱 실패율**(목표 16% → 5% 이하)과 그때의 오경보 상한 — 가설(출력 절단 → 근거 길이 제한)은 감사 파일 재분류로만 뒷받침되며 재측정으로 확인된 적이 없다.
- `short_reason` 등이 `num_predict=512`에서 실제로 절단을 없애는지.
- OPS-48 판정(exit 0)의 유지 여부 — 문서가 지적한 대로 기존 비교 여유는 0.0006이다.
- `run_moe_quality_battle.ps1`의 신규 파라미터가 **실제 PowerShell에서** 파이썬 CLI로 올바르게 전달되는지 — `check_ps_scripts.py`는 정적 검사이고 이 환경은 Linux라 실행하지 못했다.

## 4. OPS-50 acceptance 재대조 (acceptance ④ · 기준 main `24d8607d` + 이 PR)

| OPS-50 항 | 판정 | 근거 |
|---|---|---|
| ① 16건 결함 클래스별 재분류 | **이행(이 PR 머지 시)** | `--analyze-audit` + 보관 txt + 실데이터 고정 테스트. 결과: 미분류 16/100 · 원인 `truncated 16` · clean 10/50 · broken_latex 4/7 |
| ② 클래스별 변형 설계(a)(b)(c) · 하나씩 적용 | **설계·구현 이행 / 측정 미이행** | (a)=`stage_split` (b)=`latex_check` (c)=`few_shot` + 절단 대응 `short_reason`·`reason_first`. `--prompt-variant`가 한 번에 하나만 받음 |
| ③ 같은 seed 재평가 5% 이하 · Wilson 유지 | **미이행(라이브)** | §3 |
| ④ 확정된 튜닝의 정착 · 감사 파일 보관 | **미이행(③ 선행)** | 정착 대상이 ③에서 정해진다 |
| ⑤ A/B/C 병기 재판정 | **도구 이행 / 재판정 미이행** | 리포트 A/B/C 병기 · `--unresolved-policy worst` · `--max-unresolved-rate`. 재판정 수치는 ③ 라이브 산출 |

의도적 제외: 없음. **OPS-50은 닫지 않는다** — `todo` 유지, 이 태스크를 `depends_on`으로 이미 부착하고 있으므로 머지 후 착수 가능해진다.
다음 행동은 Kiki의 Phaiakes9 라이브 측정이며 절차는 `docs/ops/amd395_local_llm_performance.md` §6.2 "OPS-50 재측정 절차"에 있다.

## 5. 원 브랜치 처분

`claude/happy-turing-kmrd5z`는 이 PR 머지 전까지 **삭제 금지**(태스크 notes). 머지 후 삭제는 정리 배치의 몫이다.
원격 claim `OPS-50`은 TTL 초과이나 이 회수의 범위가 아니라서 `claims reap --apply`는 하지 않았다(dry-run만 확인 —
OPS-50은 삭제 대상 목록에 있다. 다음 착수 세션이 라이브 측정을 시작할 때 `start`로 새 claim을 잡으면 된다).
