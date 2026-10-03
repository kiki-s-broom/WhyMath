"""merge_rules.py — 추가분 규칙을 constitution/rules.yaml의 'rules:' 목록 끝에 안전하게 넣는다.

원본: Kiki 헌법 v1.1 갱신 꾸러미(2026-09-26). 로컬 패치는 UPSTREAM.md에 기록했다.

**사람(Kiki)이** 저장소 최상위에서 실행한다 (헌법 제11조: rules.yaml은 사람만 수정한다 —
AI 세션은 .claude/hooks/guard_constitution.py가 constitution/ 편집을 막는다):
    python scripts/constitution/merge_rules.py <추가분.yaml>            ← 미리보기
    python scripts/constitution/merge_rules.py <추가분.yaml> --apply    ← 실제 반영(백업 후 저장)
    ... --apply --bump-stage-note   ← 머리말 '이식 단계 (1~5)'를 '(1~6)'으로 함께 고침

왜 이 도구가 필요한가:
  rules.yaml은 'rules:' 목록 뒤에 'sources:'(원본 등록부)가 이어지는 구조다. 추가분을 파일
  '맨 끝'에 붙여 넣으면 YAML 오류 없이 규칙들이 sources 목록으로 흡수되어, 규칙은 하나도
  늘지 않고 위헌 심사에는 가짜 '원본 없음' 위반이 수십 건 생긴다(꾸러미 제작 중 재현).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

# whymath 패치(CONST-12): 파이프에서 stdout·stderr 는 로캘 인코딩(한국어 Windows = cp949)이라
# 한글이 cp949 로 나가고(⛔ 는 인코딩 불가 → UnicodeEncodeError) 읽는 쪽(채택 도우미)이 UTF-8 로
# 해독하다 실패한다(PR #1447 실측). PyYAML import 실패 메시지도 같은 경로라 그 앞에서 재구성한다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # 재구성 불가한 스트림은 그대로 둔다
        pass

try:
    import yaml  # PyYAML (위헌 심사 audit.py와 같은 의존성)
except ImportError:
    sys.exit("⛔ PyYAML이 필요합니다: python -m pip install pyyaml")

RULES = Path("constitution/rules.yaml")
BACKUP = Path("rules.yaml.bak")  # 백업은 constitution/ 밖에 둔다 (헌법 폴더를 어지럽히지 않게)
TOP_KEY = re.compile(r"^[A-Za-z_][\w-]*:")  # 들여쓰기 없는 최상위 키 (예: sources:)
STAGE_NOTE_OLD = "이식 단계 (1~5)"
STAGE_NOTE_NEW = "이식 단계 (1~6)"


def load(path: Path) -> tuple[str, dict]:
    try:
        text = path.read_text(encoding="utf-8")
        return text, yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as e:
        sys.exit(f"⛔ 읽기 실패 ({path}): {type(e).__name__}: {e}")


def insertion_index(lines: list[str]) -> int:
    """'rules:' 뒤 첫 최상위 키의 줄 번호. 그 키 바로 위의 주석·빈 줄은 그 키의 것으로 본다."""
    start = next((i for i, line in enumerate(lines) if line.startswith("rules:")), None)
    if start is None:
        sys.exit("⛔ rules.yaml에서 'rules:' 줄을 찾을 수 없음")
    idx = next((i for i in range(start + 1, len(lines)) if TOP_KEY.match(lines[i])), len(lines))
    while idx - 1 > start and (
        not lines[idx - 1].strip() or lines[idx - 1].lstrip().startswith("#")
    ):
        idx -= 1
    return idx


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print("사용법: python scripts/constitution/merge_rules.py <추가분.yaml> [--apply]")
        return 1
    base_text, base = load(RULES)
    add_text, add = load(Path(args[0]))
    old_ids = [r["id"] for r in base.get("rules") or []]
    new_ids = [r["id"] for r in add.get("rules") or []]
    if not new_ids:
        print("⛔ 추가분 파일에 rules: 목록이 없음")
        return 1
    dup = sorted(set(old_ids) & set(new_ids))
    if dup:
        print(f"⛔ 이미 등록된 규칙 ID {len(dup)}개 (예: {dup[:3]}) — 이미 병합했는지 확인하세요")
        return 1

    # whymath 패치(CONST-02): 줄끝이 CRLF이거나 'rules:' 뒤에 공백이 있으면 원본의
    # split("\nrules:\n")가 IndexError로 죽었다. 줄 단위로 찾는다.
    add_lines = add_text.replace("\r\n", "\n").split("\n")
    rules_at = next((i for i, line in enumerate(add_lines) if line.rstrip() == "rules:"), None)
    if rules_at is None:
        print("⛔ 추가분 파일에서 'rules:' 줄을 찾을 수 없음")
        return 1
    block = "\n".join(add_lines[rules_at + 1 :]).rstrip("\n")  # 'rules:' 다음 줄부터 (주석 보존)
    lines = base_text.splitlines(keepends=True)
    at = insertion_index(lines)
    head = "".join(lines[:at]).rstrip("\n")
    tail = "".join(lines[at:])
    merged_text = f"{head}\n\n{block}\n\n{tail}" if tail else f"{head}\n\n{block}\n"
    if "--bump-stage-note" in sys.argv:
        merged_text = merged_text.replace(STAGE_NOTE_OLD, STAGE_NOTE_NEW, 1)

    # 결과 검증: 규칙은 정확히 늘고, 원본 등록부(sources)와 나머지 키는 그대로여야 한다
    merged = yaml.safe_load(merged_text)
    same_rest = all(merged.get(k) == v for k, v in base.items() if k != "rules")
    if [r["id"] for r in merged["rules"]] != old_ids + new_ids or not same_rest:
        print("⛔ 병합 결과 검증 실패 — rules.yaml을 바꾸지 않았습니다")
        return 1

    print(
        f"미리보기: 규칙 {len(old_ids)}개 → {len(old_ids) + len(new_ids)}개, "
        f"{at + 1}번째 줄 위치에 삽입, sources 등 나머지 항목 변화 없음"
    )
    if "--apply" not in sys.argv:
        print("반영하려면 --apply 를 붙여 다시 실행하세요.")
        return 0
    # whymath 패치(CONST-02): AI 세션(Claude Code 셸은 CLAUDECODE 를 켠다)에서는 반영을 거부한다.
    # 가드 훅은 명령 문자열만 보므로 '스크립트가 constitution/ 에 쓰는' 경로는 못 본다 — 제9조의
    # 이중 방어를 스크립트 쪽에 둔다. 미리보기는 읽기 전용이라 막지 않는다.
    if os.environ.get("CLAUDECODE"):
        print("⛔ AI 세션(CLAUDECODE)에서는 --apply 를 실행할 수 없다 — 헌법 제9조·제11조")
        return 3
    shutil.copy2(RULES, BACKUP)
    RULES.write_text(merged_text, encoding="utf-8")
    print(f"✅ 반영 완료 (백업: {BACKUP}). 이어서: python scripts/constitution/audit.py --no-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
