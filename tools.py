"""LLM에게 주는 도구 2개.

도구를 둘로 나눈 이유는 서술형 질문("왜 이 방법을 썼나")과 집계 질문
("PSNR이 30dB를 넘는 프로젝트")이 필요로 하는 자료구조가 다르기 때문이다.
이 가설은 eval/run_eval.py의 A/B/C ablation으로 검증한다.
"""
from __future__ import annotations

import json
import re
import sqlite3

from retriever import Retriever, flatten_tables

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
        "프로젝트 README 본문을 검색해 관련 문단을 돌려준다. "
        "**이유, 방법, 설계 판단, 한계, 결론**을 묻는 질문에 쓴다. "
        "예: '왜 그 필터를 골랐나', '어떻게 구현했나', '무엇이 문제였나'. "
        "지표 이름(정확도, PSNR 등)이 질문에 나오더라도 묻는 것이 '왜'나 '어떻게'이면 "
        "이 도구를 쓴다. 단순히 값이 얼마인지, 어떤 것들이 조건을 만족하는지를 "
        "묻는다면 query_db를 쓸 것."
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
        "repos(name, language, domain, started, ended, duration_days, summary), "
        "metrics(repo, name, condition, baseline, value, unit). "
        "metrics.name은 'PSNR' | 'accuracy' | 'MSE' | 'EbNo' | 'match_rate' 등, "
        "metrics.condition은 측정 조건을 적은 한국어 자유 서술이다. "
        "**값, 목록, 순위**를 묻는 질문에 쓴다. 수치뿐 아니라 "
        "**언어, 도메인, 기간 같은 비수치 속성으로 거르는 질문도 포함**한다. "
        "예: 'PSNR이 30dB 넘는 프로젝트 전부', 'Python이 아닌 프로젝트', "
        "'가장 오래 걸린 프로젝트'. "
        "기준값 대비 개선폭을 물으면 value와 함께 **baseline 컬럼도 SELECT**할 것. "
        "기간 비교에는 started/ended를 빼지 말고 duration_days를 쓸 것 "
        "(날짜는 TEXT라 빼기가 조용히 틀린 값을 준다). "
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


def search_docs(query: str, k: int = 5, expand_query: bool = True,
                flatten: bool = True) -> str:
    hits = retriever(expand_query).search(query, k=k or 5)
    if flatten:
        # 표가 든 문단은 행 단위로 편 것을 함께 준다. 원문은 그대로 두므로
        # 모델이 어느 쪽을 봐도 되고, 행/열을 어긋나게 읽을 여지만 줄인다.
        for h in hits:
            rows = flatten_tables(h["text"])
            if rows:
                h["table_rows"] = rows
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
        if not rows:
            # 빈 결과를 그냥 넘기면 모델이 "데이터가 없다"고 단정하고 끝낸다
            # (실측 2건). 무엇을 다시 해 볼지 같이 알려 준다.
            return json.dumps({
                "columns": cols, "rows": [],
                "hint": ("조건에 맞는 행이 없습니다. 포기하지 말고 조건을 넓혀 "
                         "다시 조회하세요. condition은 자유 서술이라 정확히 일치하지 "
                         "않을 수 있으니 LIKE '%키워드%'를 쓰거나, WHERE 없이 "
                         "해당 repo의 행을 전부 본 뒤 고르는 편이 확실합니다."),
            }, ensure_ascii=False)
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
