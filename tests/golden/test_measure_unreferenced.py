"""S15 측정 도구(golden.measure_unreferenced)의 순수 함수 테스트.

전체 측정(grimp 그래프 + 런타임 import)은 무겁고 저장소 상태에 따라 숫자가 바뀌므로 여기서 돌리지 않는다.
대신 결과를 좌우하는 두 규칙만 고정한다.
- ancestors: "a.b.c를 import하면 a·a.b의 __init__도 실행된다"(보정 ①의 근거)
- compact: 통째로 안 쓰는 디렉터리만 한 줄로 접고, 쓰는 파일이 섞인 디렉터리는 파일 단위로 남긴다
"""

from __future__ import annotations

from golden.measure_unreferenced import ancestors, compact, is_old


def test_ancestors_lists_every_parent_package() -> None:
    # 조상 패키지를 하나라도 빠뜨리면 db/__init__.py 같은 일괄 import가 측정에서 사라진다
    assert ancestors("whymath_backend.db.session") == ["whymath_backend", "whymath_backend.db"]
    assert ancestors("whymath_backend") == []


def test_is_old_does_not_match_prefix_lookalikes() -> None:
    # 'whymath_backend_x' 같은 이름을 옛 패키지로 세면 안 된다(접두 문자열 비교의 함정)
    assert is_old("whymath_backend")
    assert is_old("whymath_backend.l3.router")
    assert not is_old("whymath_backend_tools.x")
    assert not is_old("golden.api")


def test_compact_folds_only_fully_unused_directories() -> None:
    base = "src/backend/whymath_backend"
    unused = [
        (f"{base}/harness/a.py", 10),  # harness/ 전체가 미사용 → 한 줄로 접힘
        (f"{base}/harness/sub/b.py", 5),
        (f"{base}/l3/verifier.py", 7),  # l3/에는 쓰는 파일이 있음 → 파일 단위로 남김
        (f"{base}/l3/equivalent/c.py", 3),  # l3/equivalent/는 통째로 미사용 → 접힘
        (f"{base}/app.py", 2),  # 깊이 4의 파일 → 그대로
    ]
    used = [f"{base}/l3/router.py", f"{base}/__init__.py"]
    rows = compact(unused, used, depth=4)
    assert rows == [
        (f"{base}/app.py", 1, 2),
        (f"{base}/harness/", 2, 15),
        (f"{base}/l3/equivalent/", 1, 3),
        (f"{base}/l3/verifier.py", 1, 7),
    ]
    # 접어도 파일 수·줄 수 합계는 그대로다(목록에서 아무것도 잃지 않는다)
    assert sum(k for _, k, _ in rows) == len(unused)
    assert sum(n for *_, n in rows) == sum(n for _, n in unused)


def test_compact_never_folds_above_depth() -> None:
    # depth보다 위(whymath_backend/ 자체)는 접지 않는다 — 접으면 목록 전체가 한 줄이 된다
    base = "src/backend/whymath_backend"
    rows = compact([(f"{base}/l2/x.py", 4), (f"{base}/l4/y.py", 6)], used=[], depth=4)
    assert rows == [(f"{base}/l2/", 1, 4), (f"{base}/l4/", 1, 6)]
