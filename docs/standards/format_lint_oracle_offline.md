# 포맷·린트 오라클 확보 절차 — pypi가 막힌 환경 (HARN-110)

> **한 줄 요약**: pypi가 503이거나 오프라인이라 `black`을 설치할 수 없을 때, **추측으로 포맷을 고치지 않고**
> GitHub 소스로 실물 black을 조립해 CI와 같은 판정을 먼저 재현한다. 조립한 도구가 CI와 같은 버전인지는
> **정합 확인**(§4)이 증명하며, 그 스텝을 건너뛰면 절차는 없는 것과 같다.

**판정 기준**: main `9308cf4c` (2026-09-29). 이 문서가 다루는 CI 명령은 `.github/workflows/ci.yml`의
`data-pipeline`·`backend`·`infra-contracts`·`harness-integrity` 4개 잡에서 읽었다.

**이 문서의 실측 범위 (2026-09-29 · 이 문서를 쓴 세션)** — 무엇을 확인했고 무엇을 못 했는지 구분해 둔다.

| 항목 | 상태 | 근거 |
|---|---|---|
| 의존성 6종을 GitHub 태그에서 받는 것(§3 표의 저장소·태그) | 실측함 | 6개 모두 `git clone` 성공 |
| 스텁 2종을 만들고 `python3 -m black --version` 실행 | 실측함 | 출력 `26.5.1 (compiled: no)` |
| 한글이 표시 폭 2로 계산되는 원리(§5) | 실측함 | `black/strings.py`의 `str_width`·`char_width` 소스 읽기 + 표준 라이브러리 `unicodedata` |
| 조립한 black으로 CI 명령을 돌려 **차이 0건** 확인(§4) | **이번 세션 미실측** | 자동 모드 권한 분류기가 외부 코드 실행으로 거부(§7). 아래 「사고 기록」의 수치는 2026-09-18 세션의 기록이다 |
| ruff 대안(§6) | 확인된 대안 없음 | Rust 바이너리라 같은 방법이 통하지 않는다 |

## 1. 언제 이 절차를 쓰는가

**먼저 pypi가 정말 막혔는지 확인한다.** 이 환경의 pypi 도달성은 세션마다 다르다 — 2026-09-18 세션은 상시 503이었고
2026-09-29 세션은 응답했다.

```bash
# pypi 도달 확인 — 버전 목록이 나오면 이 문서의 절차는 불필요하다(pip 설치가 우선)
python3 -m pip index versions black
```

목록이 나오면 `python3 -m pip install "black==<§2에서 고른 버전>"`이 가장 단순하다. 이 문서는 목록이 안 나오거나
503·타임아웃일 때의 절차다. **어느 쪽이든 §4 정합 확인은 똑같이 필수다.**

## 2. 어떤 버전을 받을까 — 추측하지 않는다

핀 범위는 `src/backend/pyproject.toml`의 dev extra에 있다: `black>=24.10.0,<27`. 상한만 있고 하한이 낮으므로
**CI가 새로 설치하면 그 범위 안의 최신 정식 버전이 잡힌다.** 그래서 손에 익은 옛 버전(예: 25.9.0)이 아니라 최신을 고른다.

```bash
# 정식 릴리스 태그만 골라 버전순으로 정렬해 마지막 줄이 최신이다(--refs로 ^{} 중복 제거)
git ls-remote --tags --refs https://github.com/psf/black | sed 's|.*refs/tags/||' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -3
```

- 실측(2026-09-29): 최신 정식 태그는 `26.5.1`이었다. 이 값은 시간이 지나면 바뀐다 — **문서의 값을 복사하지 말고 위 명령을 다시 돌린다.**
- CI 로그에 `black, <버전>`이 찍혀 있으면 그 값이 정본이다. 로그와 조립 결과가 다르면 로그를 따른다.
- 선택한 버전이 요구하는 의존성 하한은 그 태그의 `pyproject.toml`의 `dependencies`에서 읽는다(26.5.1 기준: `pathspec>=1.0.0`, `pytokens~=0.4.0`). **`pytokens`는 `~=0.4.0`이라 0.5 계열을 받으면 안 된다.**

## 3. 조립 — GitHub 소스를 `PYTHONPATH`로 묶는다

black은 순수 파이썬이고 실행 의존성이 6종이다. 모두 순수 파이썬이라 설치 없이 소스 디렉터리를 `PYTHONPATH`에 걸면 돈다.

| 패키지 | GitHub 저장소 | 태그 형식 | 소스 위치(저장소 안) |
|---|---|---|---|
| black | `psf/black` | `26.5.1` | `src/` |
| click | `pallets/click` | `8.5.0` | `src/` |
| packaging | `pypa/packaging` | `26.3` | `src/` |
| pathspec | `cpburnz/python-pathspec` | **`v1.1.1`** (앞에 `v`) | 저장소 루트 |
| platformdirs | `tox-dev/platformdirs` | `4.12.1` | `src/` |
| mypy_extensions | `python/mypy_extensions` | `1.1.0` | 저장소 루트(`mypy_extensions.py` 한 파일) |
| pytokens | `tusharsadhwani/pytokens` | `0.4.1` | `src/` |

**저장소 이름을 추측하지 않는다** — 두 곳에서 실제로 틀렸다(2026-09-29 실측).
- pathspec은 `cpburn`**`z`**다. `cpburnett/…`로 쓰면 저장소가 없어 `could not read Username`(인증 요구)로 실패한다 — "없는 저장소"가 이 오류 문구로 나온다.
- platformdirs는 `tox-dev/platformdirs`다. `platformdirs/platformdirs`는 오래된 다른 저장소라 `v2.0.0a1` 같은 엉뚱한 태그만 보인다.
- 저장소 주소를 모르면 pypi JSON에서 읽는다: `curl -sS https://pypi.org/pypi/<패키지>/json` → `info.project_urls`. (pypi 본체가 503이면 이것도 안 되므로 위 표를 쓴다.)

```bash
# 작업 디렉터리 — 저장소 밖에 둔다(저장소에 커밋될 일이 없도록)
W=/tmp/oracle && rm -rf "$W" && mkdir -p "$W" && cd "$W"

# 태그를 얕게 받는다. -c advice.detachedHead=false 는 detached HEAD 안내문 소음을 없앤다
clone() { git -c advice.detachedHead=false clone -q --depth 1 --branch "$2" "https://github.com/$1.git" "$3"; }
clone psf/black 26.5.1 black-src
clone pallets/click 8.5.0 click-src
clone pypa/packaging 26.3 packaging-src
clone cpburnz/python-pathspec v1.1.1 pathspec-src
clone tox-dev/platformdirs 4.12.1 platformdirs-src
clone python/mypy_extensions 1.1.0 mypy_extensions-src
clone tusharsadhwani/pytokens 0.4.1 pytokens-src

# 빌드 때 생성되는 파일 2종(스텁) — 없으면 import 단계에서 실패한다
printf 'version = "26.5.1"\n' > black-src/src/_black_version.py
printf '__version__ = version = "4.12.1"\n__version_tuple__ = version_tuple = (4, 12, 1)\n' > platformdirs-src/src/platformdirs/version.py

export PYTHONPATH="$W/black-src/src:$W/click-src/src:$W/packaging-src/src:$W/pathspec-src:$W/platformdirs-src/src:$W/mypy_extensions-src:$W/pytokens-src/src"
python3 -m black --version
```

스텁 2종이 필요한 이유(모두 소스에서 확인):
- `_black_version.py` — `black/__init__.py`가 `from _black_version import version`을 한다. 저장소에는 타입 스텁 `_black_version.pyi`만 있고 실물은 빌드(hatch-vcs)가 만든다. **`version` 값은 §2에서 고른 태그와 같아야 한다.**
- `platformdirs/version.py` — `platformdirs/__init__.py`가 `from .version import __version__`과 `__version_tuple__`을 import한다. 이것도 빌드(hatch-vcs)가 만드는 파일이다.

성공하면 `python3 -m black --version`이 **`26.5.1 (compiled: no)`**처럼 출력한다(`compiled: no`는 mypyc 컴파일 없이 순수 파이썬으로 돈다는 뜻이며 판정 결과에는 영향이 없다).

Python 3.10을 쓰면 `tomli`·`typing-extensions`도 필요하다(`python_version<'3.11'` 조건). 이 저장소의 CI는 3.12이고 CCR 컨테이너는 3.11이라 해당 없다.

## 4. 정합 확인 — 필수 스텝 (건너뛰면 절차 전체가 무효)

조립한 black이 **CI와 같은 판정을 내는지**를 먼저 증명한 뒤에만 그 도구로 파일을 고친다. 방법은 CI 명령을 **그대로**
기존 파일에 돌려 **차이가 0건**인지 보는 것이다. 기존 파일은 이미 CI를 통과한 상태이므로, 오라클이 정확하다면 손댈 파일이 없어야 한다.

`--line-length 100`을 **반드시 명시**한다. 경로를 둘 이상 주면 black이 설정을 찾는 기준이 달라져 기본값 88로 폴백할 수 있다(`ci.yml`의 해당 주석 참조).
작업 디렉터리도 잡마다 다르다 — CI 명령을 복사할 때 `cd`를 함께 옮긴다.

```bash
# 저장소 루트에서 — infra-contracts 잡
python3 -m black --check --line-length 100 tests/infra infra conftest.py > /tmp/oracle_infra.log 2>&1; echo "INFRA_EXIT=$?"
# 저장소 루트에서 — harness-integrity 잡
python3 -m black --check --line-length 100 scripts tests/harness tools > /tmp/oracle_harness.log 2>&1; echo "HARNESS_EXIT=$?"
# src/backend 에서 — backend 잡
cd src/backend && python3 -m black --check --line-length 100 . ../../tests/backend > /tmp/oracle_backend.log 2>&1; echo "BACKEND_EXIT=$?"; cd ../..
# src/data-pipeline 에서 — data-pipeline 잡
cd src/data-pipeline && python3 -m black --check --line-length 100 . ../../tests/data_pipeline > /tmp/oracle_dp.log 2>&1; echo "DP_EXIT=$?"; cd ../..
```

(CI의 `backend`·`data-pipeline` 잡은 `black`을 직접 부르지만, 조립한 도구는 실행 파일이 없어서 **`python3 -m black`으로만** 돈다. 인자와 경로는 `ci.yml`과 글자까지 같아야 한다.)

**판정은 종료 코드로 한다.** 조용한 옵션(`-q`)이나 `| tail`로 출력을 자르지 않는다 — 실패해도 성공과 같은 화면이 나온다. 로그는 파일로 받아 두고 나중에 읽는다.

| 결과 | 뜻 | 다음 행동 |
|---|---|---|
| 모든 `*_EXIT=0` (`would reformat` 0건) | 오라클이 CI와 같다 | 이 도구로 새·수정 파일을 `black --line-length 100`으로 고친 뒤 같은 `--check`를 다시 돌린다 |
| 하나라도 `1` (기존 파일을 고치겠다고 함) | **CI와 다른 버전이다** | 이 도구로 고치지 않는다. §2로 돌아가 다른 버전을 고른다 |

- 로그의 `would reformat <파일>` 목록이 **내가 건드리지 않은 파일**을 포함하면 버전 불일치의 증거다.
- 기존 파일에서 차이가 0건이어도 **버전이 같다는 뜻은 아니다**(스타일이 안 바뀐 두 버전일 수 있다). 그러나 CI와 같은 판정을 내린다는 뜻이고, 우리가 필요한 것은 그것이다.

### 사고 기록 (2026-09-18 · EOS-106 Week 1 Gate 판정 세션 — 이 문서를 만든 계기)

> 이 절의 수치는 **그 세션의 기록**이며 이번 세션이 재측정한 값이 아니다.

- 조립해 처음 돌린 black **25.9.0**은 기존 11파일을 재포맷하려 했다 → CI와 다른 버전. 그 도구로 고쳤으면 3회차 CI red였다.
- 다시 조립한 **26.5.1**은 CI 로그와 글자까지 일치했다. 즉 이 스텝이 실제로 CI red 1회를 막았다.
- 같은 세션에서 추측 기반 수정으로 CI red 2회가 났다. black 스텝이 7번째라 뒤 20개 스텝이 `skipped`가 되어 검증 표면 전체가 미실행이었다.

## 5. Black은 문자 수가 아니라 표시 폭으로 잰다

사람이 손으로 센 "100자 이내"는 Black의 판정과 어긋난다. Black은 줄 길이를 **글자 수(`len`)가 아니라 터미널·에디터에 표시되는 폭**으로 잰다.

- 근거: `black/strings.py`의 `str_width`는 ASCII만 있는 줄이면 `len`을 쓰고(빠른 경로), 아니면 글자마다 `char_width`를 더한다. `char_width`는 Unicode **East Asian Width** 표로 전각 문자를 **2**, 반각을 **1**로 센다.
- 실측(2026-09-29, 표준 라이브러리 `unicodedata`): 한글 `가`는 East Asian Width `W`(폭 2)이고 영문 `a`는 `Na`(폭 1)다. `"# 한글 주석입니다 한글 주석입니다"`는 **19자인데 폭은 33**이다.
- 이 저장소는 한국어 주석·문자열이 많아서 이 차이가 자주 판정을 가른다. **"조각이 95자니까 한 줄에 들어간다"는 계산은 한글이 섞이면 틀린다** — 2026-09-18 사고의 2회차 원인이 정확히 이것이었다.
- 폭이 애매한 문자(`—`·`·`처럼 East Asian Width가 `A`인 것)를 Black이 몇으로 세는지는 이 문서가 확인하지 못했다. 그래서 규칙은 **손으로 계산하지 말고 오라클에 물어라**(`black --diff`)다.

```bash
# 어떻게 다시 쓰일지를 diff로 미리 본다 — 파일은 바꾸지 않는다
python3 -m black --diff --line-length 100 <파일>
```

## 6. ruff — 같은 방법이 통하지 않는다

ruff는 Rust로 만든 **컴파일된 바이너리**라 소스 디렉터리를 `PYTHONPATH`에 거는 방식으로 돌릴 수 없다(파이썬 패키지가 아니다).

- **확인된 대안: 없음.**
- 미검증 후보로 GitHub Releases의 미리 빌드된 바이너리가 있으나, 이 환경에서 도달 여부·실행 허용 여부를 **확인하지 못했다**. 후보일 뿐 절차가 아니다(외부 바이너리 실행은 §7의 승인 문제도 있다).
- 그러므로 pypi가 막힌 상태에서 ruff는 **로컬에서 돌리지 못한다.** 이 경우 PR 본문에 **"ruff 미실행 — CI가 판정"**이라고 명시한다. 로컬 black 통과를 ruff 통과로 읽지 않는다.
- 규칙 종류는 `select = ["E", "F", "I", "N", "B", "W"]`(루트 `pyproject.toml`)다. 직접 확인할 수 있는 것은 import 정렬(`I`)·미사용 import(`F`)·줄 길이(`E`, tests는 `E501` 면제) 정도의 눈 점검뿐이며, 그것은 판정이 아니라 추정이다.

## 7. 실행 승인 — 조립물은 외부 코드다

§3의 소스는 GitHub에서 받은 **외부 코드**이고 §4는 그것을 실행한다. 사람이 손으로 진행하는 세션에서는 문제가 없지만, **자동 모드 권한 분류기가 있는 세션에서는 실행이 거부될 수 있다.**

- 실측(2026-09-29): `PYTHONPATH`에 조립물을 걸고 `black --check`를 돌리는 명령이 분류기에서 `Code from External` 사유로 거부됐다. 같은 조립물의 `python3 -m black --version`은 직전 호출에서 실행됐다 — 즉 **같은 조립물이라도 호출에 따라 판정이 갈릴 수 있다.**
- **거부는 장애물이 아니라 판정이다.** 다른 도구·다른 경로(pip 설치, 스크립트로 감싸기 등)로 같은 결과를 우회하지 않는다(CLAUDE.md 「거부(deny)의 우회 금지」).
- 거부되면: ① 거기까지 끝낸 것과 못 한 것을 그대로 보고하고 ② 사람이 실행할 수 있게 §3·§4 명령을 넘기거나 사용자가 해당 명령에 대한 Bash 허용 규칙을 추가하게 한다 ③ **§4를 못 돌렸으면 그 도구로 파일을 고치지 않는다.**

## 8. 오라클을 확보하지 못했을 때

정합 확인(§4)을 통과한 오라클이 없으면 **추측으로 포맷을 고치지 않는다.**

- 새 파일은 짧은 줄로 쓰고(한글 섞인 줄은 폭 기준으로 넉넉히 짧게), 함수 호출 인자를 한 줄에 억지로 넣지 않는다 — 그래도 판정이 아니라 추정이다.
- PR 본문에 **"black 미실행(오라클 미확보) — CI가 판정"**을 명시한다. 침묵은 통과 주장으로 읽힌다.
- CI가 red면 **로그의 `would reformat` 차이를 그대로 적용**한다. 로그가 정본이며, 수정 후 같은 CI 명령이 같은 파일에 차이를 내지 않는지 확인한다.

## 9. 이 문서의 동결

이 절차가 4축(조립·버전 특정·정합 확인·표시 폭)과 ruff 한계를 계속 담는지는 `tests/infra/test_format_oracle_doc.py`가 검사한다.
그 테스트는 §4의 CI 명령이 `ci.yml`의 실제 `black --check` 명령과 어긋나면 red가 되고, §2의 핀 범위가 `pyproject.toml`과 어긋나도 red가 된다.
