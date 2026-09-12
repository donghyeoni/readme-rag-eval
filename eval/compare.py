"""측정 결과 두 개를 같은 문항 위에서 비교한다.

정답률 차이만 보면 표본 크기에 속는다. 같은 50문항을 두 조건으로 돌렸으므로
짝지은 검정(McNemar)이 맞고, 그래야 "정말 좋아졌나"에 답할 수 있다.

    python eval/compare.py results/agent_C_prefix.csv results/agent_C_fixed.csv
    python eval/compare.py results/agent_C_fixed.csv results/agent_C_14b.csv --labels 7B 14B
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from math import comb, sqrt
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 6가지 수정을 도출한 원래 20문항. 나머지 30문항은 그 수정을 겨냥하지 않았으므로
# 사실상 홀드아웃이다.
TARGETED = {f"{p}{i}" for p in ("d", "s") for i in range(1, 11)}


def load(path: str) -> dict[str, dict]:
    with open(path, encoding="utf-8-sig") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def mcnemar(pairs: list[tuple[str, str]]) -> tuple[int, int, float]:
    """(전, 후) 정오 쌍에서 b(틀→맞), c(맞→틀), 양측 정확검정 p를 돌려준다."""
    b = sum(1 for a, x in pairs if a == "0" and x == "1")
    c = sum(1 for a, x in pairs if a == "1" and x == "0")
    n = b + c
    if n == 0:
        return b, c, 1.0
    tail = sum(comb(n, k) for k in range(min(b, c) + 1))
    return b, c, min(1.0, 2 * tail / 2 ** n)


def acc(rows: list[dict]) -> tuple[float, int, int]:
    ok = sum(int(r["correct"]) for r in rows)
    return (ok / len(rows) if rows else 0.0), ok, len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--labels", nargs=2, default=("before", "after"))
    a = ap.parse_args()

    A, B = load(a.before), load(a.after)
    ids = [i for i in B if i in A]
    la, lb = a.labels

    print(f"=== {la} → {lb} · 공통 {len(ids)}문항 ===\n")
    print(f"{'분할':<22}{la:>10}{lb:>10}{'차이':>9}   틀→맞 맞→틀      p")
    splits = [("수정이 겨냥한 20문항", lambda i: i in TARGETED),
              ("홀드아웃 30문항", lambda i: i not in TARGETED),
              ("전체", lambda i: True)]
    for label, sel in splits:
        sub = [i for i in ids if sel(i)]
        if not sub:
            continue
        pa, _, n = acc([A[i] for i in sub])
        pb, _, _ = acc([B[i] for i in sub])
        b, c, p = mcnemar([(A[i]["correct"], B[i]["correct"]) for i in sub])
        print(f"{label:<20}{pa:>10.3f}{pb:>10.3f}{pb - pa:>+9.3f}"
              f"{b:>7}{c:>6}{p:>8.3f}   (n={n})")

    se = sqrt(max(acc([B[i] for i in ids])[0] * (1 - acc([B[i] for i in ids])[0]), 1e-9) / len(ids))
    print(f"\n{lb} 전체 표준오차 ±{se:.3f} ({se * len(ids):.1f}문항)")

    print(f"\n뒤집힌 문항:")
    for i in ids:
        if A[i]["correct"] != B[i]["correct"]:
            d = "틀→맞" if B[i]["correct"] == "1" else "맞→틀"
            tag = "겨냥" if i in TARGETED else "홀드아웃"
            print(f"  {i:<5} {d}  [{tag}]  {B[i]['failure'] or '정답'}")

    print(f"\n{lb} 실패 유형:")
    for k, v in Counter(B[i]["failure"] for i in ids if B[i]["failure"]).most_common():
        print(f"  {k:<14} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
