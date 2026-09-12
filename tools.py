"""LLM에게 주는 도구 2개.

도구를 둘로 나눈 이유는 서술형 질문("왜 이 방법을 썼나")과 집계 질문
("PSNR이 30dB를 넘는 프로젝트")이 필요로 하는 자료구조가 다르기 때문이다.
이 가설은 eval/run_eval.py의 A/B/C ablation으로 검증한다.
"""
from __future__ import annotations

import json
import re
import sqlite3

from retriever import Retriever

DB = "meta.db"

_r: Retriever | None = None


def retriever(expand_query: bool = True) -> Retriever:
    """검색기 싱글턴. 평가에서 확장을 끄고 켜기 위해 교체할 수 있다."""
    global _r
    if _r is None or _r.expand_query != expand_query:
        _r = Retriever(expand_query=expand_query)
    return _r


SEARCH_DOCS = {
    "name": "search_docs",
    "description": (
        "프로젝트 README 본문을 검색한다. 방법, 이유, 설계 판단, 한계처럼 "
        "서술형 내용을 찾을 때 쓴다. 수치 비교, 정렬, 집계는 query_db를 쓸 것."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "검색어"},
            "k": {"type": "integer", "description": "가져올 문단 수 (기본 5)"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}

QUERY_DB = {
    "name": "query_db",
    "description": (
        "프로젝트 메타데이터에 SELECT 쿼리를 실행한다. 스키마: "
        "repos(name, language, domain, started, ended, summary), "
        "metrics(repo, name, condition, baseline, value, unit). "
        "metrics.name은 'PSNR' | 'accuracy' | 'MSE' | 'EbNo' | 'match_rate' 등, "
        "metrics.condition은 측정 조건을 적은 한국어 자유 서술이다. "
        "수치 비교, 정렬, 집계, 'X 이상인 프로젝트 전부' 같은 질문에 쓴다. "
        "SELECT만 허용된다."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "실행할 SELECT 문"},
        },
        "required": ["sql"],
        "additionalProperties": False,
    },
    "strict": True,
}

TOOLS = [SEARCH_DOCS, QUERY_DB]

# ablation용 도구 구성
TOOLSETS = {
    "A": [SEARCH_DOCS],
    "B": [QUERY_DB],
    "C": TOOLS,
}


def search_docs(query: str, k: int = 5, expand_query: bool = True) -> str:
    hits = retriever(expand_query).search(query, k=k or 5)
    return json.dumps(hits, ensure_ascii=False, indent=1)


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|replace)\b",
    re.I,
)


def query_db(sql: str) -> str:
    """LLM이 생성한 SQL을 그대로 실행하므로 두 겹으로 막는다.

    1. SELECT로 시작하지 않거나 쓰기 키워드가 보이면 거절 (화이트리스트)
    2. 그래도 뚫렸을 때를 대비해 연결 자체를 읽기 전용으로 연다 (mode=ro)

    2번이 실제 방어선이다. 1번만으로는 주석이나 CTE로 우회할 여지가 남는다.
    """
    stripped = sql.strip().rstrip(";")
    if not stripped.lower().startswith("select") or _FORBIDDEN.search(stripped):
        return "ERROR: SELECT 쿼리만 실행할 수 있습니다."
    if ";" in stripped:
        return "ERROR: 한 번에 한 개의 SELECT 문만 실행할 수 있습니다."
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.execute(stripped)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()[:50]
        return json.dumps({"columns": cols, "rows": rows}, ensure_ascii=False)
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        con.close()


DISPATCH = {"search_docs": search_docs, "query_db": query_db}


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("--- search_docs ---")
    print(search_docs("잡음 종류별로 어떤 필터를 골랐나", k=2))
    print("--- query_db (정상) ---")
    print(query_db(
        "SELECT repo, condition, value FROM metrics "
        "WHERE name='PSNR' AND value > 30 ORDER BY value DESC"
    ))
    print("--- query_db (쓰기 시도) ---")
    print(query_db("DROP TABLE repos"))
    print(query_db("SELECT 1; DELETE FROM repos"))
    print(query_db("select * from repos where name='x' union select 1,2,3,4,5,6 -- "))
