"""평가 라벨이 근거 있는 값인지 기계적으로 확인한다.

라벨을 손으로 쓰면 원문에 없는 문자열을 적기 쉽고, 그러면 모델이 맞게 답해도
틀렸다고 잡힌다(= 측정이 아니라 오측정이 된다). 그래서 만들 때 한 번 대조한다.

- route=docs : must_include 문자열이 gold_repo의 README에 실제로 있는가
- route=db   : must_include 문자열이 DB 덤프(값·레포명·조건)에 있는가

통과가 정답을 보장하지는 않는다. "원문에 없는 라벨"을 걸러 낼 뿐이다.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 이미 측정·공개에 쓴 라벨은 결과를 보고 바꾸지 않는다. 바꾸면 앞선 수치와
# 비교가 끊기고, "결과를 보고 채점 기준을 고쳤다"가 되기 때문이다.
ACCEPTED = {
    "s5": "공개된 20문항 측정에 쓰인 라벨이라 사후 수정하지 않음",
}

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DB = ROOT / "meta.db"


def db_haystack() -> str:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    parts = []
    for table in ("repos", "metrics"):
        for row in con.execute(f"SELECT * FROM {table}"):
            parts.append(" ".join("" if v is None else str(v) for v in row))
    con.close()
    return "\n".join(parts)


def main(paths: list[str]) -> int:
    db_text = db_haystack().lower()
    docs = {p.stem: p.read_text(encoding="utf-8").lower() for p in DOCS.glob("*.md")}
    all_docs = "\n".join(docs.values())

    bad = 0
    seen: set[str] = set()
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            q = json.loads(line)
            if q["id"] in seen:
                print(f"  [{q['id']}] 중복 id")
                bad += 1
            seen.add(q["id"])

            if q["route"] == "docs":
                hay = docs.get(q["gold_repo"], all_docs) if q["gold_repo"] else all_docs
                where = q["gold_repo"] or "(전체 문서)"
            else:
                hay = db_text
                where = "(DB)"

            missing = [m for m in q["must_include"] if m.lower() not in hay]
            if missing:
                print(f"  [{q['id']}] {where} 에 없음: {missing}")
                bad += 1

            # 맨숫자 한두 자리는 아무 답에나 걸려서 통과해도 의미가 없다.
            # 한글 두 글자("포화", "증강")는 온전한 단어라 여기 해당하지 않는다.
            weak = [m for m in q["must_include"]
                    if m.replace(".", "").isdigit() and len(m) <= 2]
            if weak:
                # 다른 라벨이 함께 걸려 있으면 그쪽이 변별해 주므로 경고만 한다
                if len(weak) < len(q["must_include"]):
                    print(f"  [{q['id']}] 경고: 약한 라벨 {weak} (다른 라벨이 변별)")
                elif q["id"] in ACCEPTED:
                    print(f"  [{q['id']}] 약한 라벨 {weak} — {ACCEPTED[q['id']]}")
                else:
                    print(f"  [{q['id']}] 약한 라벨뿐이라 변별 불가: {weak}")
                    bad += 1
    total = len(seen)
    print(f"\n{total}문항 중 라벨 근거 확인 실패 {bad}건")
    return 1 if bad else 0


if __name__ == "__main__":
    args = sys.argv[1:] or [str(ROOT / "eval" / "questions.jsonl")]
    raise SystemExit(main(args))
