# import-linter 계약 6개 뮤테이션 검증 — 계약이 실제로 막는가

> **판정 기준**: main `a350b96d` · 2026-11-17 · Windows 11 · Python 3.13
> **도구**: import-linter 2.13 · grimp 3.15 (사용자 site `C:\Users\kiki\AppData\Roaming\Python\Python313`)
> **대상**: `src/backend/pyproject.toml`의 `[tool.importlinter]` 계약 전수(착수 시점 실측 6개)
> **성격**: 검증 보고. **옛 코드 영구 변경 0줄** — 주입 8건은 전부 저장소 밖 `cp` 백업 → `cp` 복원으로 되돌렸다.
> 출처: `golden/RESCUE_REVIEW.md` §6 F-2 · 태스크 `GOLD-25` · Kiki 승인 2026-11-17.

---

## 0. 한 줄 결론

**6계약 중 5계약은 실제로 막는다**(주입 7건 전부 `BROKEN` · exit 1).
**1계약은 특정 형태에서 막지 못한다** — `EOS Core → Math Adapter 금지 (baseline 있음 — EOS-69가 해소)`가
소스로 `whymath_backend.l4`(패키지)를 적으면서 그 **하위 5모듈**을 금지하는데, import-linter는
소스가 금지 대상의 **상위 패키지**인 쌍을 **건너뛴다**. 주입으로 확인했다(exit 0 · `KEPT`).

이것은 import-linter의 버그가 아니라 **문서화된 설계**이며, 따라서 **계약 문면의 문제**다.
오늘 실제 위반은 **0건**이지만 **잠재 구멍**이다 — l4의 CORE 모듈이 그 5개 중 하나를 import하면 조용히 통과한다.

---

## 1. 계약 전수 (착수 시점 실측 · `tomllib`)

`src/backend/pyproject.toml`의 `[tool.importlinter]` — `root_packages = ["whymath_backend", "golden"]`,
`include_external_packages = true`.

| # | 계약명 | 유형 | 소스 수 | 금지 수 | ignore | `as_packages` | `allow_indirect` |
|---|---|---|---:|---:|---:|---|---|
| 1 | `7계층 단방향 (L_n → L_{n-1}, 역방향 금지)` | layers | 8 | 0 | 2 | 기본값 | 기본값(false) |
| 2 | `EOS Core → Math Adapter 금지 (baseline 0 — 이미 깨끗한 구역)` | forbidden | 4 | 23 | 0 | 기본값 | true |
| 3 | `EOS Core → Math Adapter 금지 (baseline 있음 — EOS-69가 해소)` | forbidden | 27 | 23 | 20 | 기본값 | true |
| 4 | `데이터 접근 금지 (baseline 0 — 아직 DB를 모르는 구역)` | forbidden | 4 | 2 | 0 | 기본값 | true |
| 5 | `옛 코드는 golden을 모른다 (golden → whymath_backend 허용, 역방향 금지)` | forbidden | 1 | 1 | 0 | 기본값 | 기본값(false) |
| 6 | `golden은 미참조 옛 모듈을 import하지 않는다 (golden-no-legacy · LEGACY_MANIFEST 722모듈)` | forbidden | 1 | 722 | 0 | 기본값 | 기본값(false) |

`as_packages`의 "기본값"은 **True**다(`importlinter/contracts/forbidden.py:74`). 이것이 아래 §3의 원인이다.
계약 1은 `layers` 유형이라 `forbidden_modules`가 없고 `layers` 8개를 쓴다 — ①의 "금지 수 0"은 그 뜻이다.

---

## 2. 주입 결과 (계약마다 위반 1건)

주입 방식은 모든 케이스가 같다: 대상 파일 **끝에 금지 import 한 줄을 append** → `sha256` 변화 단언(주입 실재)
→ `lint-imports` 실행 → `cp` 백업으로 복원 → `sha256` 원본 일치 단언.
원복에 `git checkout --`·`git restore`·`git stash`는 **쓰지 않았다**(CLAUDE.md 금기).

| 케이스 | 계약 | 주입 위치 | 주입한 줄 | 주입 실재 | 기대 | 실제 exit | 그 계약 판정 | 복원 |
|---|---|---|---|---|---|---:|---|---|
| M1 | 1 `7계층 단방향` | `whymath_backend/schema/misconception_hypothesis.py:45` | `import whymath_backend.l1` | ✅ | BROKEN | **1** | **BROKEN** ✅ | ✅ |
| M2 | 2 `EOS baseline 0` | `whymath_backend/lang/__init__.py:18` | `import whymath_backend.l3.verify_answer` | ✅ | BROKEN | **1** | **BROKEN** ✅ | ✅ |
| M3 | 3 `EOS baseline 있음` | `whymath_backend/l4/tone_filter.py:43` | `import whymath_backend.l3.verify_answer` | ✅ | BROKEN | **1** | **BROKEN** ✅ | ✅ |
| **M3b** | **3 `EOS baseline 있음`** | **`whymath_backend/l4/tone_filter.py:43`** | **`import whymath_backend.l4.subject_adapter_math`** | **✅** | **BROKEN** | **0** | **KEPT** ❌ | ✅ |
| M4a | 4 `데이터 접근 금지` | `whymath_backend/schema/misconception_hypothesis.py:45` | `import whymath_backend.db` | ✅ | BROKEN | **1** | **BROKEN** ✅ | ✅ |
| M4b | 4 `데이터 접근 금지` | `whymath_backend/schema/misconception_hypothesis.py:45` | `import sqlalchemy` | ✅ | BROKEN | **1** | **BROKEN** ✅ | ✅ |
| M5 | 5 `옛 코드는 golden을 모른다` | `whymath_backend/schema/misconception_hypothesis.py:45` | `import golden` | ✅ | BROKEN | **1** | **BROKEN** ✅ | ✅ |
| M6 | 6 `golden-no-legacy` | `golden/problems.py:40` | `import whymath_backend.harness.agreement_gate` | ✅ | BROKEN | **1** | **BROKEN** ✅ | ✅ |

**주입 8건 중 7건이 기대대로 BROKEN, 1건(M3b)이 KEPT다.**
모든 케이스에서 `injection_applied: true` · `restored_ok: true`(sha256 원본 일치)를 단언했다.
`lint-imports` 자체가 죽은 경우는 0건이다(`crashed: false` — §6의 인코딩 함정을 피한 뒤).

### 2.1 케이스별 판정 요지

- **M1**은 `layers` 계약이라 "금지 목록에 그 이름이 있는가"를 묻는 검사가 성립하지 않는다(`target_in_forbidden: 해당 없음`).
  `schema`가 가장 아래 계층인데 `l1`을 import했으므로 위반이다. 계약이 **`whymath_backend.schema is not allowed to import whymath_backend.l1`**로 지목했다.
- **M4a·M4b**는 같은 계약의 금지 대상 2개(`whymath_backend.db` · `sqlalchemy`)를 각각 시험했다.
  `sqlalchemy`는 외부 패키지인데도 잡혔다 — 이는 `include_external_packages = true`가 실제로 먹는다는 뜻이다.
- **M6**은 `golden-no-legacy`가 **722개 금지 목록 중 하나**를 실제로 막는지 본 것이다.
  지목한 `harness.agreement_gate`가 `LEGACY_MANIFEST` 안에 있다는 것을 계약이 스스로 확인해 주었다.

---

## 3. 함정 형태 판정 — 중첩된 금지 모듈 (acceptance ③)

### 3.1 실측

M3b가 그 형태다. 계약 3은 소스에 `whymath_backend.l4`(패키지)를 넣고, 금지 목록 23개 중 5개가
**그 패키지 안에** 있다.

- `whymath_backend.l4.misconception.answer_signature`
- `whymath_backend.l4.misconception.derivative_signature`
- `whymath_backend.l4.misconception.wrong_form_match`
- `whymath_backend.l4.misconception.wrong_form_shadow_harvest`
- `whymath_backend.l4.subject_adapter_math`

`whymath_backend/l4/tone_filter.py`(l4의 CORE 모듈)에 `import whymath_backend.l4.subject_adapter_math`를 넣었더니
**exit 0 · `Contracts: 6 kept, 0 broken`**. 같은 파일에 `l3.verify_answer`(중첩 아님)를 넣은 M3는 BROKEN이었다.
**중첩 여부만이 차이**다. 따라서 함정은 실재한다.

### 3.2 원인 — import-linter의 한계인가, 계약 문면의 문제인가

**계약 문면의 문제다.** import-linter는 이 동작을 문서화된 설계로 갖고 있다.

`importlinter/contracts/forbidden.py:20-36`:

> `_modules_overlap(source_module, forbidden_module, *, as_packages)` —
> "Return whether the source and forbidden modules overlap: either they are the same module, or,
> when treated as packages, **one contains the other**. Overlapping pairs do not describe a
> forbiddable import and are skipped by the contract."

`forbidden.py:74`: `as_packages = fields.BooleanField(required=False, default=True)`
`forbidden.py:110-118`: 겹치는 쌍을 만나면 `Skipping overlapping modules {source} and {forbidden}.`를
verbose 출력에 남기고 `continue`한다.

`forbidden.py:44-48`의 클래스 docstring도 같은 취지를 적는다 — 이 설계는 `mypackage.*` 같은
**와일드카드 금지**를 소스와 겹쳐도 쓸 수 있게 하려는 것이다. 즉 **의도된 동작**이고 버그가 아니다.

### 3.3 왜 이것이 "문면의 문제"인가 — 같은 파일이 이미 그 이유를 적어 두었다

계약 3의 주석(`src/backend/pyproject.toml`, baseline 있음 계약):

> "`l3`는 통째로 넣을 수 없다(ADAPTER 모듈이 같은 계층에 산다) — CORE 배정 키만 열거한다."

**`l3`에는 정확히 이 판단을 적용했는데 `l4`에는 적용되지 않았다.** 그런데 l4에도 ADAPTER가 있다 —
경계 정본 `scripts/analysis/eos_core_adapter_boundary_scan.py`의 `BOUNDARY_MAP`이
`l4.misconception.{wrong_form_match, wrong_form_shadow_harvest, answer_signature, derivative_signature}`와
`l4.subject_adapter_math`를 **`ADAPTER`**로 배정한다. 같은 파일 주석(`:174`)은 그 의도를 명시한다:

> "CORE가 이것을 import하면 위반이 맞다 — Core는 schema.subject_adapter Protocol만 알아야 하고 구현체는 DI로만 주입된다."

즉 **계약이 막으려던 바로 그 위반**을, 중첩 스킵이 무력화한다.

### 3.4 오늘 실제 위반은 0건이다 (잠재 구멍)

l4 안에서 그 5모듈로 들어가는 **직접 엣지는 4건**이고, **4건 전부 ADAPTER→ADAPTER**다
(grimp 3.15 실측):

| # | 엣지 | 방향 | `ignore_imports`에 있음 |
|---|---|---|---|
| 1 | `misconception.answer_signature → misconception.derivative_signature` | ADAPTER→ADAPTER | 예 |
| 2 | `misconception.answer_signature → misconception.wrong_form_match` | ADAPTER→ADAPTER | 예 |
| 3 | `misconception.wrong_form_shadow_harvest → misconception.wrong_form_match` | ADAPTER→ADAPTER | **아니오** |
| 4 | `subject_adapter_math → misconception.answer_signature` | ADAPTER→ADAPTER | 예 |

**CORE→ADAPTER 엣지는 0건**이다. 그래서 계약은 지금 green이고, 그것이 옳다.
주목할 것은 **#3**이다 — ignore 목록에 없는데도 통과한다. 통과 이유가 ignore가 아니라 **중첩 스킵**이라는 것이,
이 구멍이 "지금도 실제로 작동 중"이라는 증거다.

위험은 미래에 있다: **l4에 새 CORE 모듈을 만들고 그 5개 중 하나를 import하면 계약이 조용히 통과시킨다.**
이 저장소가 반복해서 겪은 "위장 통과"의 형태다(CLAUDE.md 「보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지」).

### 3.5 이 구멍은 계약 3의 다른 소스와 계약 2에는 없다

계약 3의 소스 27개 중 `whymath_backend.l4`만 중첩 형태이고, 나머지(`api`·`l6`·`l3.*` 등)는 그 5개를
포함하지 않으므로 정상적으로 집행된다. 계약 2의 소스(`l1`·`l2`·`lang`·`schema`)도 마찬가지다.
따라서 **영향 범위는 "l4의 CORE 모듈 → l4의 ADAPTER 5모듈" 한 칸**이다.

---

## 4. 대체 집행 수단 — 주입으로 검증했다

### 4.1 제안

`as_packages`를 끄고 소스를 **CORE 모듈 단위로 열거**한다. 정본은 `BOUNDARY_MAP`이다.

`as_packages = false`로 두면 `_modules_overlap`이 **정확히 같은 모듈일 때만** True를 돌려주므로
(`forbidden.py:30-36`) 중첩 스킵이 사라진다.

### 4.2 검증 (저장소 밖 임시 config로 실행 — `pyproject.toml`은 고치지 않았다)

l4 모듈 100개 중 ADAPTER 5개를 뺀 **95개를 소스로 열거**하고, `as_packages = false`,
금지 5개, `allow_indirect_imports = true`로 계약 하나만 담은 임시 config를 만들어 돌렸다.

| 조건 | 현행 형태(`whymath_backend.l4` + `as_packages` 기본 True) | 보정 형태(95모듈 열거 + `as_packages = false`) |
|---|---|---|
| 주입 없음 | exit 0 (`KEPT`) | **exit 0** (`KEPT`) — 오탐 없음 |
| M3b 주입 | **exit 0** (`KEPT`) ❌ | **exit 1** (`BROKEN`) ✅ |

보정 형태의 BROKEN 출력은 정확히 그 엣지를 지목했다:

> `whymath_backend.l4.tone_filter is not allowed to import whymath_backend.l4.subject_adapter_math:`
> `-   whymath_backend.l4.tone_filter -> whymath_backend.l4.subject_adapter_math (l.42)`

**주입 없음에서도 exit 0**이라는 것이 중요하다 — 보정이 오탐을 만들지 않는다는 뜻이고,
이는 §3.4의 "CORE→ADAPTER 엣지 0건" 실측과 일치한다.

### 4.3 주의 — `as_packages = false`만 켜면 안 된다

소스를 `whymath_backend.l4`(패키지)로 둔 채 `as_packages = false`로 바꾸면, `_modules_overlap`이
"같은 모듈"만 보므로 **모든 하위 모듈이 검사 대상**이 된다. 그 경우 ADAPTER→ADAPTER 4건이
오탐이 되어 ignore를 4건 더 늘려야 한다. 그러면 ADAPTER끼리의 정상 협력을 허용 목록으로 고정하는 셈이라
의도와 다르다. **소스를 CORE로 한정하는 것**이 요점이다.

### 4.4 제안 (실행하지 않음 — `pyproject.toml`은 골든 밖 파일)

1. 계약 3의 소스에서 `whymath_backend.l4`를 빼고, `BOUNDARY_MAP`이 `CORE`로 배정한 l4 모듈을 열거한다.
2. 그 5개 금지를 **별도 계약**으로 분리해 `as_packages = false`를 건다(계약 3은 20개 ignore를 그대로 유지).
3. 열거가 정본과 어긋나지 않게 하는 배선 검사는 기존 `tests/infra/test_eos_boundary_contract_wiring.py` 축에 붙인다
   (이 파일이 이미 계약과 정본의 정합을 동결하고 있는지까지는 이 세션에서 확인하지 않았다 — §8).

---

## 5. 성공 방향 대조군 (acceptance ⑤)

| 시점 | 명령 | 결과 |
|---|---|---|
| 주입 전 | `lint-imports` (저장소 기본 config) | **exit 0** · `Contracts: 6 kept, 0 broken` |
| 주입 8건 전부 복원 후 | `lint-imports` (저장소 기본 config) | **exit 0** · `Contracts: 6 kept, 0 broken` |

대조군이 없으면 "8건 전부 BROKEN"이 계약이 막아서인지 그냥 원래 red여서인지 구분할 수 없다.
주입 전후 모두 green이므로, §2의 BROKEN 7건은 **주입이 만든 것**이다.

---

## 6. 도구 함정 2건 (재현 시 반드시 피해야 한다)

### 6.1 `python -m importlinter.cli lint-imports`는 **아무것도 하지 않는다**

exit 0 · 출력 0줄. `--help`도 빈 출력이다. `importlinter/cli.py`에 `if __name__ == "__main__"` 블록이 없기 때문이다.
`python -m importlinter`는 `No module named importlinter.__main__`로 실패한다.

**이것은 위장 통과다.** 이 명령을 "lint 통과"로 읽으면 검증 전체가 무효가 된다(CLAUDE.md 「변별력 없는 검증 스텝 금지」).
실제 진입점은 콘솔 스크립트다:

- `C:\Users\kiki\AppData\Roaming\Python\Python313\Scripts\lint-imports.exe`

### 6.2 `PYTHONIOENCODING=utf-8` 없이는 **crash가 exit 1**로 보고된다

한국어 Windows의 cp949 stdout에서 계약 이름의 `—`(U+2014)를 인코딩하지 못해
`UnicodeEncodeError`로 죽는다. 첫 계약만 출력하고 중간에 죽으므로 **exit 1**이 나오는데,
이것을 "BROKEN"으로 읽으면 계약이 막았다는 거짓 증거가 된다. 대책: `PYTHONIOENCODING=utf-8`을 반드시 설정한다.
(대책 없이 돌린 1회차 실행에서 실제로 이 crash를 관측했다.)

---

## 7. 재현 명령

**전제**: `src/backend`에서 실행 · `PYTHONIOENCODING=utf-8` · 주입 전 `cp` 백업은 **저장소 밖**에 둔다.

```powershell
# PowerShell · Kiki 머신 · 실행 전 브랜치 확인
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$env:PYTHONIOENCODING = "utf-8"
cd src\backend

# ① 대조군 — 6계약 green
& "$env:APPDATA\Python\Python313\Scripts\lint-imports.exe"
"EXIT=$LASTEXITCODE"
```

```powershell
# ② 함정 재현 — l4 CORE 모듈에 중첩 금지 import를 넣는다 (cp 백업 → 주입 → 실행 → cp 복원)
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$env:PYTHONIOENCODING = "utf-8"
$F = "whymath_backend\l4\tone_filter.py"
$B = "$env:TEMP\gold25_tone_filter.bak"
Copy-Item $F $B -Force
"BEFORE_SHA=" + (Get-FileHash $F -Algorithm SHA256).Hash
Add-Content $F "`nimport whymath_backend.l4.subject_adapter_math  # GOLD-25"
"AFTER_SHA=" + (Get-FileHash $F -Algorithm SHA256).Hash
& "$env:APPDATA\Python\Python313\Scripts\lint-imports.exe"
"LINT_EXIT=$LASTEXITCODE"
Copy-Item $B $F -Force
"RESTORED_SHA=" + (Get-FileHash $F -Algorithm SHA256).Hash
```

기대: `BEFORE_SHA`와 `AFTER_SHA`가 **다르고**, `LINT_EXIT=0`, `RESTORED_SHA`가 `BEFORE_SHA`와 **같다**.
`LINT_EXIT=0`이 §3의 구멍이다.

```powershell
# ③ 보정 형태 — 95개 CORE 모듈 열거 + as_packages=false (저장소 밖 임시 config)
#    소스 목록은 grimp로 뽑고 ADAPTER 5개를 뺀다. config는 $env:TEMP에 쓴다.
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$env:PYTHONIOENCODING = "utf-8"
python C:\Users\kiki\AppData\Local\Temp\gold25_fixprobe.py
```

이 하네스는 저장소 파일을 건드리지 않는다(임시 config만 쓴다). 다만 §②와 같은 방식으로
`tone_filter.py`를 잠깐 고쳤다가 `cp`로 되돌린다 — 출력의 `restored_ok`가 `true`인지 확인한다.

---

## 8. 확인하지 못한 것 (정직한 공백)

- **계약 3 외 소스의 중첩 가능성**: 계약 2·4·5·6의 소스 목록에 금지 대상의 상위 패키지가 섞여 있는지는
  이번에 형태 대조로만 봤다(§3.5). 계약이 늘거나 목록이 바뀌면 이 판정은 낡는다.
- **`tests/infra/test_eos_boundary_contract_wiring.py`의 실제 범위**: 파일 이름으로 존재를 확인했을 뿐,
  계약 소스와 `BOUNDARY_MAP`의 정합을 어디까지 동결하는지는 읽지 않았다. §4.4의 배선을 붙일 때 먼저 읽어야 한다.
- **`golden.problems`의 그래프 투영**: grimp 탐침에서 `ModuleNotPresent`가 났다. 이는 탐침이
  `root_packages` 두 개와 `include_external_packages`를 재현하지 않은 **탐침의 한계**이며, `lint-imports`는
  같은 주입(M6)을 정상적으로 BROKEN으로 판정했다. 즉 **계약의 판정은 유효**하고 탐침만 무효다.
  같은 이유로 M4b(`sqlalchemy`)·M5(`golden`)의 탐침도 `tgt_in_graph: false`를 냈다 — 둘 다 lint는 BROKEN이었다.
- **다른 import-linter 버전**: 2.13에서 측정했다. `as_packages` 기본값이 바뀌면 §3의 판정이 달라진다.
- **영구 수정**: 하지 않았다. `pyproject.toml`은 골든 밖 파일이고, Kiki 승인은 일시 주입·복원에만 해당한다.
  §4.4는 **제안**이다.

---

## 9. 옛 코드 변경 0줄 확인

주입 8건 전부 `cp` 백업 → `cp` 복원, 케이스마다 `sha256` 원본 일치를 단언했다(`restored_ok: true` 8/8).
보조 탐침(§4.2)도 같은 방식으로 복원했고 `restored_ok: true`를 확인했다.
종료 시 `git diff --stat`으로 `src/backend/whymath_backend` 변경 0건을 확인한다 — 결과는 보고에 적는다.

---

*이 문서는 골든 패스 기간(2026-11-08~)의 규칙에 따라 `golden/` 안에 둔다.*
