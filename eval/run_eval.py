"""20문항 평가.

두 가지를 따로 잰다.

1. 검색기 단독 (--retrieval-only) — LLM 없이 Recall@k만. 질의 확장 같은
   검색기 쪽 변경을 API 비용 없이 바로 확인한다.
2. 에이전트 전체 — 도구 구성 A/B/C별로 정답률, 도구 선택 정확도,
   평균 호출 횟수, 도구 에러율, 그리고 틀린 질문의 유형 분류.

실패 유형을 나누는 이유는 고치는 곳이 서로 다르기 때문이다.
검색 실패는 검색기, 도구 선택 실패는 도구 description, 생성 실패는 프롬프트.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent import SYSTEM_VARIANTS, Trace, ask     # noqa: E402
from backends import make_backend                 # noqa: E402
from retriever import Retriever                   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = Path(__file__).resolve().parent / "questions.jsonl"
RESULTS = ROOT / "results"

EXPECTED_TOOL = {"docs": "search_docs", "db": "query_db"}


def load_questions() -> list[dict]:
    with open(QUESTIONS, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def hits(answer: str, must: list[str]) -> tuple[bool, list[str]]:
    """must_include 문자열이 전부 들어갔는가. 없으면 어떤 게 빠졌는지도 준다."""
    missing = [m for m in must if m.lower() not in answer.lower()]
    return (not missing), missing


# --------------------------------------------------------------------------
# 1. 검색기 단독
# --------------------------------------------------------------------------
def eval_retrieval(qs: list[dict], k: int = 3, expand: bool = True) -> dict:
    r = Retriever(docs_dir=str(ROOT / "docs"), expand_query=expand)
    labelled = [q for q in qs if q["gold_repo"]]
    rows, hit = [], 0
    for q in labelled:
        top = []
        for h in r.search(q["q"], k=k * 3):        # 청크 단위이므로 넉넉히 뽑고
            if h["repo"] not in top:               # 레포 단위로 접어서 상위 k개
                top.append(h["repo"])
            if len(top) >= k:
                break
        ok = q["gold_repo"] in top
        hit += ok
        rows.append({"id": q["id"], "route": q["route"], "gold": q["gold_repo"],
                     "top_repos": "|".join(top), "hit": int(ok)})
    return {"n": len(labelled), "recall_at_k": hit / len(labelled), "rows": rows}


# --------------------------------------------------------------------------
# 2. 에이전트 전체
# --------------------------------------------------------------------------
def classify_failure(q: dict, tr: Trace, toolset: str) -> str:
    """틀린 질문의 원인을 하나로 정한다. 순서가 곧 우선순위다."""
    if tr.stop_reason == "max_turns":
        return "루프 미종료"
    expected = EXPECTED_TOOL[q["route"]]
    available = {"A": {"search_docs"}, "B": {"query_db"}, "C": {"search_docs", "query_db"}}[toolset]
    if not tr.calls:
        return "도구 미사용"
    # 쓸 수 있는 도구가 애초에 하나뿐인 A/B에서는 도구 선택을 탓할 수 없다
    if expected in available and tr.first_tool != expected:
        return "도구 선택 실패"
    # 검색기가 아예 없는 B 조건에서는 "검색 실패"라고 부를 수 없다.
    # 그 경우는 도구 구성 자체가 답을 못 내는 것이라 아래 분기로 내려보낸다.
    if expected == "search_docs" and q["gold_repo"] and "search_docs" in available:
        if q["gold_repo"] not in tr.retrieved_repos(top=3):
            return "검색 실패"
    if expected not in available:
        return "도구 구성 한계"
    if tr.n_errors and tr.n_errors == tr.n_calls:
        return "도구 실패"
    return "생성 실패"


def eval_agent(qs: list[dict], backend_spec: str, toolset: str,
               expand: bool = True, limit: int | None = None,
               system: str = "v2") -> dict:
    backend = make_backend(backend_spec)
    rows = []
    for q in qs[:limit]:
        try:
            answer, tr = ask(q["q"], backend, toolset=toolset, expand_query=expand,
                             system=SYSTEM_VARIANTS[system])
        except Exception as e:                      # 한 문항이 터져도 평가는 계속
            answer, tr = f"HARNESS_ERROR: {type(e).__name__}: {e}", Trace()
            tr.stop_reason = "harness_error"
        ok, missing = hits(answer, q["must_include"])
        expected = EXPECTED_TOOL[q["route"]]
        available = {"A": {"search_docs"}, "B": {"query_db"},
                     "C": {"search_docs", "query_db"}}[toolset]
        rows.append({
            "id": q["id"], "route": q["route"], "gold": q["gold_repo"] or "",
            "correct": int(ok), "missing": "|".join(missing),
            "first_tool": tr.first_tool or "",
            "tool_ok": int(tr.first_tool == expected) if expected in available else "",
            "n_calls": tr.n_calls, "n_errors": tr.n_errors, "turns": tr.turns,
            "retrieved": "|".join(tr.retrieved_repos(top=3)),
            "recall3": (int(q["gold_repo"] in tr.retrieved_repos(top=3))
                        if (q["gold_repo"] and "search_docs" in available) else ""),
            "recovered": tr.recovered_calls, "verifier": tr.verifier_hits,
            "in_tok": tr.input_tokens, "out_tok": tr.output_tokens,
            "latency_s": round(tr.latency_s, 2),
            "stop_reason": tr.stop_reason,
            "failure": "" if ok else classify_failure(q, tr, toolset),
            "answer": answer.replace("\n", " ")[:600],
        })
        mark = "o" if ok else "X"
        print(f"  [{mark}] {q['id']:<4} {q['route']:<4} "
              f"first={rows[-1]['first_tool']:<12} calls={tr.n_calls} "
              f"{tr.latency_s:5.1f}s  {q['q'][:34]}")

    n = len(rows)
    tool_rows = [r for r in rows if r["tool_ok"] != ""]
    rec_rows = [r for r in rows if r["recall3"] != ""]
    fails: dict[str, int] = {}
    for r in rows:
        if r["failure"]:
            fails[r["failure"]] = fails.get(r["failure"], 0) + 1
    return {
        "toolset": toolset, "backend": backend.name, "expand": expand, "n": n,
        "accuracy": sum(r["correct"] for r in rows) / n,
        "tool_acc": (sum(r["tool_ok"] for r in tool_rows) / len(tool_rows)) if tool_rows else None,
        "recall3": (sum(r["recall3"] for r in rec_rows) / len(rec_rows)) if rec_rows else None,
        "avg_calls": sum(r["n_calls"] for r in rows) / n,
        "err_rate": (sum(r["n_errors"] for r in rows) / max(sum(r["n_calls"] for r in rows), 1)),
        "avg_latency": sum(r["latency_s"] for r in rows) / n,
        "recovered": sum(r["recovered"] for r in rows),
        "verifier": sum(r["verifier"] for r in rows),
        "in_tok": sum(r["in_tok"] for r in rows),
        "out_tok": sum(r["out_tok"] for r in rows),
        "failures": fails,
        "rows": rows,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def fmt(x, nd=3):
    return "--" if x is None else f"{x:.{nd}f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="anthropic",
                    help="anthropic | anthropic:<model> | vllm:<base_url>")
    ap.add_argument("--toolsets", default="C", help="쉼표로: A,B,C")
    ap.add_argument("--retrieval-only", action="store_true",
                    help="LLM 없이 검색기 Recall만 측정 (질의 확장 on/off 비교 포함)")
    ap.add_argument("--no-expand", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--system", default="v2", choices=list(SYSTEM_VARIANTS),
                    help="시스템 프롬프트 판본 (v0는 도구 호출이 사라지는 판본)")
    ap.add_argument("--tag", default="", help="결과 파일 이름에 붙일 꼬리표")
    a = ap.parse_args()

    qs = load_questions()
    RESULTS.mkdir(exist_ok=True)
    tag = f"_{a.tag}" if a.tag else ""

    if a.retrieval_only:
        lines = ["# 검색기 단독 Recall (LLM 없음)", "",
                 "| 질의 확장 | k=1 | k=3 | k=5 |", "|---|---|---|---|"]
        for expand in (True, False):
            cells = []
            for k in (1, 3, 5):
                res = eval_retrieval(qs, k=k, expand=expand)
                cells.append(fmt(res["recall_at_k"]))
                if k == 3:
                    write_csv(RESULTS / f"retrieval_expand-{int(expand)}.csv", res["rows"])
            lines.append(f"| {'on' if expand else 'off'} | " + " | ".join(cells) + " |")
            print(f"expand={expand}: " + " ".join(cells))
        lines += ["", f"라벨이 붙은 질문 {eval_retrieval(qs)['n']}개 기준 "
                      "(gold_repo가 있는 문항만)."]
        (RESULTS / "retrieval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"-> {RESULTS / 'retrieval.md'}")
        return 0

    summaries = []
    for ts in a.toolsets.split(","):
        ts = ts.strip()
        print(f"\n=== toolset {ts} / backend {a.backend} / expand={not a.no_expand} ===")
        res = eval_agent(qs, a.backend, ts, expand=not a.no_expand,
                         limit=a.limit, system=a.system)
        write_csv(RESULTS / f"agent_{ts}{tag}.csv", res["rows"])
        summaries.append(res)
        print(f"  정답률 {res['accuracy']:.3f} / 도구선택 {fmt(res['tool_acc'])} "
              f"/ Recall@3 {fmt(res['recall3'])} / 평균호출 {res['avg_calls']:.1f} "
              f"/ 에러율 {res['err_rate']:.3f} / 복구 {res['recovered']} "
              f"/ 검증기 {res['verifier']}")

    md = ["# 평가 결과", "",
          f"백엔드: `{summaries[0]['backend']}` · 문항 {summaries[0]['n']}개 · "
          f"질의 확장 {'on' if not a.no_expand else 'off'}", "",
          "| 조건 | 도구 구성 | Recall@3 | 정답률 | 도구 선택 정확도 | 평균 호출 | 도구 에러율 | 평균 지연 |",
          "|---|---|---|---|---|---|---|---|"]
    label = {"A": "검색만", "B": "SQL만", "C": "둘 다"}
    for s in summaries:
        md.append(
            f"| {s['toolset']} | {label[s['toolset']]} | {fmt(s['recall3'])} | "
            f"{fmt(s['accuracy'])} | {fmt(s['tool_acc'])} | {s['avg_calls']:.1f} | "
            f"{fmt(s['err_rate'])} | {s['avg_latency']:.1f}s |"
        )
    md += ["", "## 실패 유형", "", "| 조건 | " + " | ".join(
        sorted({k for s in summaries for k in s["failures"]})) + " |"]
    kinds = sorted({k for s in summaries for k in s["failures"]})
    md.append("|---|" + "---|" * len(kinds))
    for s in summaries:
        md.append(f"| {s['toolset']} | " +
                  " | ".join(str(s["failures"].get(k, 0)) for k in kinds) + " |")
    md += ["", "## 토큰", "", "| 조건 | 입력 | 출력 |", "|---|---|---|"]
    for s in summaries:
        md.append(f"| {s['toolset']} | {s['in_tok']:,} | {s['out_tok']:,} |")
    out = RESULTS / f"summary{tag}.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
