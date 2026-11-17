# 「90만 줄의 코딩 살리기」 제안 — WhyMath 백엔드 적용 검토

> **판정 기준**: main `d7466d84` · 2026-11-17
> (측정은 `a6fbe377` 트리에서 했다. 두 커밋 사이 변경 58파일 중 측정 범위 — 백엔드 패키지·`pyproject.toml`·
> `LEGACY_MANIFEST`·워크플로·`scripts`·`docs/ops`·`backlog`·`tests/backend` — 에 닿는 파일은 **0건**임을 확인했다.)
> **범위**: `src/backend/whymath_backend` (백엔드만)
> **성격**: 검토 문서. **코드는 변경하지 않았다.** 아래 수치는 전부 이 저장소에서 다시 잰 값이다.

## 0. 한 줄 결론

제안서의 4단계 뼈대(진단 → 판정 → 재연결 → 잠금)는 옳다.
그러나 **이 저장소는 이미 그 진단 장치의 대부분을 더 정교하게 갖고 있다.**
새로 들일 것은 `ledger.py`가 아니라 **진입점 축 하나**와 **계약 뮤테이션 검증**이다.
그리고 이 작업은 지금(골든 패스 3주 기간) 착수하지 말고, **3단계 S74 삭제의 입력 자료**로 쓰는 것을 권한다.

---

## 1. 제안서가 말한 것 (요약)

| 단계 | 내용 |
|---|---|
| A. 진단 | 진입점에서 import를 따라 닿는가 + 경로 테스트가 실행하는가 + 단위 테스트가 실행하는가 → **가동/대기/섬/잔해** 4등급 |
| B. 판정 | 연결 / 수리 / 재작성 / 격리 / 삭제 5처분. 자산(다시 만들기 어려운 지식)은 캐내고 접착제는 새로 만든다 |
| C. 재연결 | 경로 하나를 끝까지. 끊김 하나에 PR 하나. 연결 PR에서는 새 구현 금지 |
| D. 잠금 | 경로 게이트 · 고아 게이트 · 부품 허용 목록 · 조용한 실패 게이트 · 중복 게이트 |

제안서의 핵심 주장 3개:
1. 단위 테스트 초록불은 작동의 증거가 아니다.
2. 끊김은 겹겹이라 한 겹씩 풀어야 한다.
3. 90만 줄에서는 통독이 불가능하므로 지도(대장)를 보고 필요한 곳만 연다.

이 셋은 이 저장소에서도 유효하다. 문제는 **수단**이지 방향이 아니다.

---

## 2. 실측 (이 저장소, 2026-11-17)

### 2.1 규모

| 항목 | 값 | 측정 방법 |
|---|---:|---|
| 저장소 파이썬 | 2,706파일 914,096줄 | `git ls-files '*.py'` 전수 개행 계산 |
| 그중 tests / src / scripts | 484,370 / 345,604 / 72,982 | 동일 |
| 백엔드 패키지 | 844파일 316,469줄 | `src/backend/whymath_backend/**/*.py` |
| 백엔드 테스트 | 1,141파일 380,596줄 | `tests/backend/**/*.py` |

**테스트가 소스보다 크다**(380,596 vs 316,469). 제안서의 "잔해" 판정이 이 저장소에서 왜곡되는 구조적 이유다 —
테스트가 붙은 모듈은 아무리 서버에서 안 쓰여도 "섬"으로 살아남는다.

### 2.2 진입점 도달성 (grimp 3.15, 그래프 빌드 0.2초)

진입점은 `whymath_backend.app:create_app` 팩토리다(`app.py:990`). 모듈 전역 `app` 객체는 없다
(`AGENTS.md:102` — uvicorn `--factory`). 정적 그래프는 모듈 단위이므로 `whymath_backend.app`에서 추적했다.

| 항목 | 값 |
|---|---:|
| 그래프 모듈 | 839 |
| `app`에서 도달 | **480** |
| `app`에서 미도달 | **359** (172,697줄 · 패키지의 54.6%) |
| 골든이 미사용 (LEGACY_MANIFEST) | 722모듈 286,275줄 (grimp 교집합 718) |
| **`app` 미도달 ∩ 골든 미사용** | **359** — 미도달 전부가 여기 속한다 |
| 골든은 쓰는데 `app`이 못 닿는 모듈 | **0** |

`app` 미도달 359개의 하위 패키지 분포:

| 하위 패키지 | 모듈 | 줄 |
|---|---:|---:|
| `whymath_backend.harness` | 150 | 73,568 |
| `whymath_backend.l3` | 85 | 50,641 |
| `whymath_backend.ops` | 33 | 25,818 |
| `whymath_backend.l1` | 40 | 8,982 |
| `whymath_backend.l4` | 27 | 8,033 |
| `whymath_backend.whs` | 14 | 3,854 |
| `whymath_backend.privacy` | 4 | 933 |
| `whymath_backend.l2` | 2 | 418 |
| `whymath_backend.schema` | 3 | 353 |
| `whymath_backend.api` | 1 | 97 |
| **합계** | **359** | **172,697** |

### 2.3 그 359개는 죽은 코드인가 — 아니다

| 구분 | 모듈 |
|---|---:|
| `.github/workflows` · `scripts` · `docs/ops` · `backlog/`에 **이름이 등장** | 90 |
| 위 어디에도 이름이 등장하지 않음 | 269 |

`harness/*` 150개는 대부분 `python -m whymath_backend.harness.X` 형태의 **CLI 도구**다.
"서버가 안 부른다"는 "아무도 안 부른다"가 아니다.
269개도 **"내가 찾은 방법으로는 이름이 안 나온다"**는 뜻이지 "기능이 없다"는 뜻이 아니다
(CLAUDE.md 「식별자 부재를 기능 부재로 단정 금지」).

### 2.4 그 밖의 실측

| 항목 | 값 | 근거 |
|---|---|---|
| 경로 테스트 | **1개** — `test_student_solves_one_problem_end_to_end` (55줄) | `tests/golden/test_golden_path.py:12` |
| `tests/golden` 실행 위치 | `testpaths`에 없음. CI `golden-path` 잡에서만 실행 | `src/backend/pyproject.toml:1275` · `ci.yml:1094` |
| 백엔드 e2e 테스트 | 다수 존재하나 **대부분 기본 SKIP**(실 PG 필요) | `tests/backend/api/test_e2e_*.py` |
| import-linter 계약 | **6개** | `src/backend/pyproject.toml:225~1270` |
| 조용한 실패 후보 | BLE001 **37** · S110 **3** · E722 **0** | `ruff check --select BLE001,S110,E722 --statistics whymath_backend` |
| 백엔드 ruff select | `E, F, I, N, B, W` — `BLE`·`S` 없음 | `src/backend/pyproject.toml:194` |
| vulture | 저장소 참조 **0건** | `git grep -i vulture` |
| jscpd | 도구로 배선된 곳 **0건**. 이름은 `backlog/tasks/ARCH-47-…yaml:26`에 **검색어로 1회** 등장(부재 판정 기록) | `git grep -i jscpd` |
| `tools/` | `work-graph-desktop/`(Electron 앱) 하나뿐 — 구조 진단 도구 없음 | — |
| `whymath_backend/events/` | `.py` **0개**, `__pycache__`만 남음 | — |
| 동적 import 지점 | **8곳 / 4파일** (`importlib.import_module` 5 · `pkgutil.iter_modules` 2 · `find_spec` 1) — 4파일 모두 LEGACY_MANIFEST 안 | grep |
| 문자열 지정 모듈 로딩 | `config.py:550`·`:558`의 `sympy_isolation_preload_modules`·`sympy_isolation_warmup` | — |

---

## 3. 핵심 발견 3개

### 발견 1 — A단계 진단은 이미 있다. 더 정교하게.

`src/backend/golden/measure_unreferenced.py` (S15 · 2026-11-15)는 제안서의 A단계를 다음처럼 수행한다:

- grimp 정적 그래프 + **보정 3종**
  - ① 조상 패키지 클로저 — `import a.b.c`가 `a/__init__`·`a/b/__init__`도 실행한다는 사실을 의존으로 추가
  - ② 런타임 실측 — golden 모듈을 실제 import한 뒤 `sys.modules`에 올라온 모듈을 "사용"으로 판정
  - ③ 네임스페이스 패키지 — `__init__.py` 없는 `l1/rights/`를 파일시스템으로 재계수
- Flutter 축(`main_golden.dart` → `lib/golden/*.dart`)까지 포함
- 산출물: TSV 4종 + `measure_summary.json` + 압축 마크다운
  (`LEGACY_MANIFEST.txt`는 이 TSV들에서 파생된 대장이다 — 스크립트가 직접 쓰지는 않는다)

집행 장치도 이미 있다:
- `tests/golden/test_legacy_manifest.py` — 매니페스트 722/74 개수·계약 정확 일치·AST 직접 검사 동결
- import-linter 계약 `golden-no-legacy` — 722개 forbidden_modules
- import-linter 계약 `옛 코드는 golden을 모른다` — 역방향 금지

`ledger.py`는 이보다 **덜 정교하다**(보정 3종이 없고 Flutter 축이 없다).
그리고 `ledger.py`의 "고아 게이트"(`--baseline`)는 `LEGACY_MANIFEST` + `golden-no-legacy`와 **같은 역할**이다.

### 발견 2 — `app` 미도달은 `골든 미사용`의 부분집합이다 (예외 0건)

`app` 미도달 359모듈 ⊂ 골든 미사용 718모듈 — 예외 **0건**.

즉 제안서의 "진입점 기준 진단"은 이 저장소에서 **새로 죽은 코드를 찾아내지 못한다.**
이미 있는 718개 목록을 **359개로 좁혀 순위를 매기는** 역할만 한다.

이것은 가치가 있다 — 삭제 우선순위가 718 → 359로 줄고, 그중 150개가 `harness`라는 사실이 바로 보인다.
하지만 **"새 진단 도구"의 가치는 아니다.** 기존 도구에 축 하나를 더하는 일이다.

### 발견 3 — "가동 비중" 지표는 이 저장소에서 변별력이 없다

경로 테스트가 **1개(55줄)**이고 `tests/golden`은 기본 `pytest` 대상도 아니다.
따라서 journey coverage로 재면 백엔드 316,469줄의 거의 전부가 "대기"로 나온다.
제안서 자신도 90만 줄 구간에서 "모듈 단위 12% 가동, 실행문 3.2%"라고 적었다 — 같은 현상이다.

이 저장소에서 실제로 변별력이 있는 지표는 셋이다:
1. `app` 미도달 모듈 수 (359)
2. 그중 이름으로도 참조되지 않는 수 (269)
3. 전체 줄 수 (줄어드는 방향)

---

## 4. 채택 3건

### 채택 1 — 진입점 축을 `golden`에서 `app`으로 **추가** (새 도구 아님)

기존 `measure_unreferenced.py`는 "골든이 안 쓰는가"만 잰다. "서버가 안 닿는가"는 다른 축이고 아직 안 쟀다.
실측 결과 이 축은 359개를 골라낸다 — 그중 150개가 `harness`, 85개가 `l3`다.

**방법**: 새 파일을 만들지 않고 `measure_unreferenced.py`에 `--entry`(기본 `golden`) 축을 더한다.
`LEGACY_MANIFEST`는 그대로 두고, `--entry app` 실행 결과를 **별도 TSV**로 낸다.
정본이 둘이 되지 않게, 매니페스트를 쓰는 경로는 하나로 유지한다.

### 채택 2 — import-linter 계약 6개 **뮤테이션 검증**

제안서가 지적한 함정: `source_modules`에 적은 패키지 **안에** 금지 모듈이 들어 있으면
실제 위반이 있어도 `KEPT`로 나온다.

계약 6개의 `source_modules` × `forbidden_modules`를 대조한 결과, **정확히 그 형태인 계약이 1개 있다** —
`EOS Core → Math Adapter 금지 (baseline 있음 — EOS-69가 해소)`다. 이 계약은 `whymath_backend.l4`를
소스로 적으면서 그 **하위 5개 모듈**을 금지한다(`l4.misconception.answer_signature`·`derivative_signature`·
`wrong_form_match`·`wrong_form_shadow_harvest`·`l4.subject_adapter_math`).

> **정정(2026-11-17)**: 처음 이 문서는 `옛 코드는 golden을 모른다`(`source_modules = ["whymath_backend"]`)를
> 그 형태로 지목했으나, 그 계약의 금지 대상은 `golden`이라는 **별개 최상위 패키지**라 함정 형태가 아니다.
> 위 5건이 유일한 해당 사례다.

여기에 일부러 금지 import를 넣어 **BROKEN이 나오는지** 확인한다. 나머지 5개도 같은 방식으로 하나씩 어긴다.
**이 검증은 아직 하지 않았다** — 소스 파일을 임시로 고쳐야 하는데, 골든 규칙상 `golden/` 밖 파일은 읽기 전용이다.

이 부류의 위장 통과는 이 저장소에서 **이미 한 번 발견된 적이 있다** — 같은 파일 주석:
> "import-linter는 그래프에 없는 모듈 이름을 오류 없이 통과시킨다. `__init__.py` 없는
> `whymath_backend/l1/rights/` 4모듈은 그래프 밖이라, 같은 테스트가 golden 소스를 AST로 직접 검사한다."

CLAUDE.md 「보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지」와 정확히 같은 요구다.

### 채택 3 — 조용한 실패 **측정만** (게이트는 보류)

`ruff select`에 `BLE`·`S`가 없어 BLE001 37건·S110 3건이 현재 검사되지 않는다. E722(bare except)는 0건.
다만 골든 기간에 린트 설정을 바꾸면 기존 코드가 일괄 red가 되므로, **건수 기록까지만** 한다.

한 가지 구분: 이 저장소의 "침묵 실패 금지" 규칙은 *예외 타입명을 로그에 남기는* 것을 요구한다.
BLE001/S110은 "삼켰는가"만 보고 "타입명을 남겼는가"는 못 본다. 게이트를 만들 때는 그 축을 따로 설계해야 한다.

---

## 5. 기각 (5건 + 참고 1건)

| 항목 | 기각 이유 |
|---|---|
| `ledger.py` 도입 | `measure_unreferenced.py`와 중복 정본. 제안서 자신이 경고한 "같은 일을 하는 구현 2벌"(유형 ⑧)이 된다. 채택 1로 흡수 |
| 가림막(`permissions.deny`) | 골든 규칙(옛 코드 읽기 전용)과 역할이 겹치고, 디버깅 시 필요한 파일을 Claude가 못 읽게 된다. 이득이 불명확 |
| 90만 줄 전면 캠페인 | 2026-11-08~3주 골든 패스 규칙과 정면 충돌. "그 밖의 기능은 제안하지 않는다" 조항에 해당 |
| "가동 비중" 지표 | 경로 테스트 1개로는 변별력 없음 (발견 3) |
| "PR 1개당 500줄" 등 일정 수치 | 합성 저장소 기준. 이 저장소 실측이 아니다 |

**참고**: vulture는 저장소 참조 0건이다. jscpd는 이름이 1회 등장하지만
`backlog/tasks/ARCH-47-duplicate-implementation-code-axis-audit.yaml:26`의 **부재 판정 기록에 검색어로 적힌 것**이고,
도구로 배선된 곳은 0건이다. 그런데 그 "중복 구현 감사" 축은 **이미 `ARCH-47`(todo · priority 3)이 소유**한다 —
제안서의 "중복 게이트"를 새 후보로 세우면 이 문서가 앞에서 기각한 "같은 일을 하는 구현 2벌"이 태스크 축에서 재현된다.

---

## 6. 후속 후보 (등재하지 않음 — 원하시면 별도 진행)

| ID | 내용 | 선행 조건 | 예상 규모 |
|---|---|---|---|
| F-1 | `measure_unreferenced.py`에 `--entry app` 축 추가 → 359개 TSV 산출 | 골든 기간 종료 또는 예외 승인 | 소 |
| F-2 | import-linter 6계약 뮤테이션 검증 (계약별 1건, 총 6건) | Kiki 승인 — `golden/` 밖 파일을 일시적으로 고쳤다가 `cp`로 복원 | 소 |
| F-3 | `app` 미도달 359개 판정표 초안 (하위 패키지 단위, 자산 여부 표시) | F-1 | 중 |
| F-4 | `ruff`에 `BLE`·`S` 선택 여부 결정 + 기존 40건 처리 계획 | 골든 기간 종료 | 중 |
| F-5 | ~~jscpd 도입 여부 검토~~ — **기각**: 같은 축을 `ARCH-47`(todo · 중복 구현 감사)이 이미 소유 | — | — |

F-2는 **성격상 골든 규칙과 충돌하지 않는다** — 계약을 일시적으로 어겼다 되돌리는 검증이고,
산출물은 코드가 아니라 "계약이 실제로 막는가"라는 판정이다. 다만 `golden/` 밖 파일을 고치는 일이므로
착수 전에 승인이 필요하고, 뮤테이션 원복은
CLAUDE.md 「미커밋 작업분이 있는 트리에서 git checkout -- 로 뮤테이션 원복 금지」에 따라
**백업 cp 후 cp 복원**으로 해야 한다.

F-1·F-3의 산출물은 **삭제 실행이 아니라 S74의 입력**이다. S74에는 이미 절차가 있다
(`golden/prompts_phase3/단계14_병렬_2개/SC-단계14-S74-legacy판정-태그삭제.md`):
세 질문(① 지난 12주 golden이 import했는가 ② `LATER.md`에 필요로 적혔는가 ③ 데이터인가) →
`git tag legacy-archive-…` → 삭제 PR → `HARVEST.md`에 모듈별 사유 기록.
이 문서의 359개 표는 ①에 쓸 자료이고, ②·③은 자동화할 수 없다.
선행 조건은 1단계 **S20A**(golden의 옛 모듈 의존을 직접 10·전이 30 이하로 절단)이며
`GOLD-19`(in_progress)에 포함돼 있다.

> 문서 불일치 1건: `golden/HARVEST.md:31`은 "삭제는 3단계 S74(GOLD-17)"라고 적었지만,
> `GOLD-17`은 논리 격리 태스크(done)이고 삭제 작업이 없다. 태스크 번호 오기로 보이며,
> S74는 태스크가 아니라 3단계 프롬프트 세션이다.

---

## 7. 확인하지 못한 것 (정직한 공백)

- **런타임 도달성**: 359개는 *정적 import 그래프* 기준이다. `importlib`·문자열 로딩·엔트리포인트로
  불리는 모듈은 "미도달"로 잘못 나올 수 있다. `measure_unreferenced`의 보정 ②(런타임 실측)를
  `app` 축에도 붙이면 줄어들 것이다.
- **계약이 실제로 막는가**: 위 채택 2의 뮤테이션 검증은 **하지 않았다**. 소스 파일을 임시로 고쳐야 하는데
  골든 규칙상 `golden/` 밖은 읽기 전용이다. 이 문서가 확인한 것은 계약 **6개의 존재와 형태**이지
  계약의 **작동**이 아니다(CLAUDE.md 「가드가 *막는다*는 주장도 주입으로 검증한다」).
- **삭제 영향**: 이 문서는 아무것도 삭제하지 않았다. 359개 중 실제로 지워도 되는 것은 0개일 수 있다.
  S74 선행 조건(1단계 S20A — golden의 옛 모듈 의존을 직접 10·전이 30 이하로 줄이기)이 아직 진행 중이다
  (`GOLD-19` in_progress). 그 절단 없이 지우면 옛 진입점·옛 테스트 965파일·CI 19잡이 깨진다
  (`golden/HARVEST.md` §삭제 영향).
- **Windows 실행**: grimp·ruff 측정은 이 Windows 머신에서 했으나, `coverage` 기반 실행 기록은 재지 않았다.
- **`src/backend/README.md`가 낡았다**: `uvicorn src.main:app`을 안내하지만 `src/backend/src/`는 없다.
  이 문서의 범위 밖이지만 별도 정정 대상이다.

---

## 8. 재현 명령

```bash
# 1) 규모 — xargs wc -l은 배치마다 total을 내므로 마지막 줄만 읽으면 틀린다
python - <<'PY'
import pathlib
fs = [p for p in pathlib.Path("src/backend/whymath_backend").rglob("*.py")
      if "__pycache__" not in p.parts]
print(len(fs), sum(p.read_bytes().count(b"\n") for p in fs))
PY

# 2) 진입점 도달성 (src/backend 에서)
python - <<'PY'
import sys; sys.path.insert(0, ".")
import grimp
g = grimp.build_graph("whymath_backend")
mods = set(g.modules)
seen, stack = set(), ["whymath_backend.app"]
while stack:
    m = stack.pop()
    if m in seen or m not in mods:
        continue
    seen.add(m)
    p = m.rpartition(".")[0]
    if p:
        stack.append(p)
    stack.extend(g.find_modules_directly_imported_by(m))
print("modules", len(mods), "reachable", len(seen), "unreachable", len(mods - seen))
PY

# 3) 조용한 실패 건수 (src/backend 에서)
python -m ruff check --select BLE001,S110,E722 --statistics whymath_backend

# 4) 계약 목록
grep -n 'name = ' src/backend/pyproject.toml | sed -n '1,20p'

# 5) 동적 import 지점 (정적 그래프의 사각지대)
grep -rnE "importlib\.import_module|pkgutil\.iter_modules|find_spec" \
  src/backend/whymath_backend --include=*.py

# 6) 359 중 이름이 참조되는 수 — 범위를 넷으로 고정해야 수치가 재현된다
#    (.github/workflows · scripts · docs/ops · backlog). 셋만 보면 85/274가 나온다.
python - <<'PY'
import pathlib, subprocess, sys
sys.path.insert(0, "src/backend")
import grimp
g = grimp.build_graph("whymath_backend"); mods = set(g.modules)
seen, stack = set(), ["whymath_backend.app"]
while stack:
    m = stack.pop()
    if m in seen or m not in mods:
        continue
    seen.add(m)
    p = m.rpartition(".")[0]
    if p:
        stack.append(p)
    stack.extend(g.find_modules_directly_imported_by(m))
un = sorted(mods - seen)
repo = pathlib.Path(".")
files = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace").stdout.splitlines()
pref = (".github/workflows/", "scripts/", "docs/ops/", "backlog/")
blob = []
for rel in files:
    if rel.startswith(pref):
        try:
            blob.append((repo / rel).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
text = "\n".join(blob)
hit = [m for m in un if m in text]
print("referenced", len(hit), "not", len(un) - len(hit))
PY
```

---

*이 문서는 골든 패스 기간(2026-11-08~)의 규칙에 따라 `golden/` 안에 둔다.
`docs/rescue/`로 옮기려면 별도 승인이 필요하다.*
