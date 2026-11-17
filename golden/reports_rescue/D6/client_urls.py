"""RS-D6 화면→서버 주소 대조 — 클라이언트 소스의 문자열 리터럴에서 /v1/·/golden/ 주소를 모아
서버 두 개(골든 `golden.api:app` · 옛 앱 `whymath_backend.app:create_app()`)의
OpenAPI 경로와 맞춘다.

재생성(저장소 루트):
  1) cd src/backend && python -m pip install -e ".[dev]"   (라우트 표에 fastapi 필요)
  2) python3 golden/reports_rescue/D6/client_urls.py
서버는 기동하지 않는다(앱 객체의 openapi()만 부른다).
include_in_schema=False 라우트는 보이지 않는다. 메서드(GET·POST)는 비교하지 않는다.
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent

# 문자열 리터럴(작은따옴표·큰따옴표·백틱) 중 /v1/ 또는 /golden/ 이 들어 있는 것
LIT = re.compile(
    r"""'([^'\n]*?/(?:v1|golden)/[^'\n]*)'|"([^"\n]*?/(?:v1|golden)/[^"\n]*)"|`([^`\n]*?/(?:v1|golden)/[^`\n]*)`"""
)


def server_routes() -> dict[str, list[tuple[str, str, str]]]:
    """서버별 (경로, 메서드, operationId) 목록."""
    sys.path.insert(0, str(ROOT / "src/backend"))
    import golden.api as g  # noqa: E402  측정 전용 — 서버 기동 없음

    from whymath_backend.app import create_app  # noqa: E402

    out: dict[str, list[tuple[str, str, str]]] = {}
    for name, app in (("골든", g.app), ("옛앱", create_app())):
        rows = []
        for path, ops in app.openapi()["paths"].items():
            for method, op in ops.items():
                rows.append((path, method.upper(), op.get("operationId", "")))
        out[name] = rows
    return out


def normalize(raw: str) -> str:
    """보간(${..}·$x)을 {p}로, 쿼리·기본 주소를 떼어 경로만 남긴다."""
    s = re.sub(r"\$\{[^}]*\}", "{p}", raw)
    s = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]*", "{p}", s)
    m = re.search(r"/(?:v1|golden)/\S*", s)  # 공백에서 끊는다(메시지 문장 속 주소 대비)
    s = m.group(0) if m else s
    s = s.split("?")[0]
    return s.rstrip("/") or s


def seg_match(client: str, server: str) -> bool:
    """마디별 비교 — 어느 쪽이든 자리표시({..})면 아무 마디와 맞는다(클라이언트 변수가 서버의
    고정 마디, 예: /cms/{resource}/items ↔ /cms/hint/items 에 들어갈 수 있으므로)."""
    a, b = client.split("/"), server.split("/")
    if len(a) != len(b):
        return False
    ph = re.compile(r"^\{[^}]*\}$")
    return all(x == y or ph.match(x) or ph.match(y) for x, y in zip(a, b, strict=True))


def literal_score(client: str, server: str) -> int:
    return sum(
        1
        for x, y in zip(client.split("/"), server.split("/"), strict=True)
        if x == y and "{" not in x
    )


def match(norm: str, routes: list[tuple[str, str, str]]) -> tuple[str, list[str]]:
    """일치 · 접두 일치(문자열이 경로 앞부분만 담은 경우) · 서버에 없음."""
    cand = [(p, m) for p, m, _ in routes if seg_match(norm, p)]
    # 고정 마디가 가장 많이 같은 라우트만 남긴다(양쪽 자리표시 허용으로 생기는 느슨한 짝 제거)
    best = max((literal_score(norm, p) for p, _ in cand), default=0)
    exact = [f"{m} {p}" for p, m in cand if literal_score(norm, p) == best]
    if exact:
        return "일치", exact
    pre = sorted({p for p, _, _ in routes if p.startswith(norm.split("{p}")[0].rstrip("/") + "/")})
    if pre:
        return "접두 일치(뒷부분은 다른 문자열이 붙임)", pre[:3]
    return "서버에 없음(끊긴 화면 후보)", []


CONST = re.compile(
    r"""\bconst\s+([A-Z_][A-Z0-9_]*)\s*=\s*"""  # 대문자 상수 이름
    r"""["'](/(?:v1|golden)/[^"']*)["']"""  # 서버 주소 값
)
STR = re.compile(r"""["'`]([^"'`]*)["'`]""")


def composed(text: str) -> list[tuple[int, str, str]]:
    """TS: `BASE + "/a/" + f(x) + "/b"` 처럼 상수에 조각을 잇는 호출을 펼친다."""
    consts = dict(CONST.findall(text))
    found = []
    for i, line in enumerate(text.splitlines(), 1):
        for name, base in consts.items():
            m = re.search(rf"\b{name}\b\s*\+(.*)", line)
            if not m:
                continue
            path = base
            for tok in m.group(1).split("+"):
                tok = tok.strip()
                sm = STR.match(tok)
                if sm:
                    piece = sm.group(1)
                    path += piece
                    if not tok.endswith(sm.group(0)[-1]) or tok != sm.group(0):
                        break  # 문자열 뒤에 다른 인자가 이어지면 끝
                elif re.match(r"^(pageQuery|\w*[Qq]uery)\(", tok):
                    break  # 쿼리 문자열 — 경로에 넣지 않는다
                else:
                    path += "{p}"
                    if re.search(r"\)\s*[,)]", tok) and tok.count("(") < tok.count(")"):
                        break
            found.append((i, f"{name} + …", path))
    return found


def main() -> None:
    routes = server_routes()
    files = subprocess.run(
        ["git", "ls-files", "src/mobile/lib", "src/web/webapp"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    files = [f for f in files if f.endswith((".dart", ".ts", ".tsx"))]
    rows = []
    for f in files:
        for i, line in enumerate(
            (ROOT / f).read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if line.lstrip().startswith(("//", "*", "///")):
                continue  # 주석 속 주소는 호출이 아니다
            for groups in LIT.findall(line):
                raw = next(g for g in groups if g)
                norm = normalize(raw)
                target = "골든" if norm.startswith("/golden/") else "옛앱"
                verdict, hits = match(norm, routes[target])
                rows.append(
                    [
                        "Flutter" if f.endswith(".dart") else "웹",
                        f,
                        i,
                        raw,
                        norm,
                        target,
                        verdict,
                        " | ".join(hits),
                    ]
                )
    for f in files:
        if not f.endswith((".ts", ".tsx")):
            continue
        for i, raw, path in composed((ROOT / f).read_text(encoding="utf-8", errors="replace")):
            norm = normalize(path)
            verdict, hits = match(norm, routes["옛앱"])
            rows.append(["웹", f, i, raw, norm, "옛앱", verdict + " · 조합 펼침", " | ".join(hits)])
    with open(OUT / "화면_서버주소.tsv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(
            [
                "클라이언트",
                "파일",
                "줄",
                "호출 주소(원문)",
                "정규화 경로",
                "대상 서버",
                "판정",
                "일치한 서버 라우트(메서드 경로)",
            ]
        )
        w.writerows(rows)
    with open(OUT / "서버_라우트.tsv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["서버", "경로", "메서드", "operationId"])
        for name, rs in routes.items():
            w.writerows([name, p, m, o] for p, m, o in rs)


if __name__ == "__main__":
    main()
