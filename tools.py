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
        "metrics.name에 있는 값은 이게 전부다: PSNR, accuracy, MSE, EbNo, "
        "coding_gain, pilot_penalty, match_rate, clip_rate, saturation_rate. "
        "**여기 없는 수치(파라미터 수, 데이터셋 장수, BER, 표 엔트리 수 등)는 "
        "DB에 없고 문서에만 있으므로 search_docs를 써야 한다.** "
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
                flatten: bool = True, question: str | None = None) -> str:
    """모델이 정한 검색어로 찾는다.

    `question`(원 질문)이 있으면 검색어에 합쳐서 던진다. 모델이 줄여 쓴 검색어가
    원문보다 못 찾는 경우가 실제로 있었다 — 검색 실패 4건 중 3건이 질문 원문으로는
    상위 3개 안에 들어왔다. 검색기는 결정적이므로 이건 모델이 아니라 질의어 문제다.
    """
    k = k or 5
    r = retriever(expand_query)
    hits = r.search(query, k=k)
    if question and question.strip() != query.strip():
        # 두 검색어를 이어 붙이면 서로를 밀어낸다(실측: s11이 오히려 떨어졌다).
        # 따로 돌려 번갈아 섞으면 각 검색어의 1위가 반드시 살아남는다.
        merged, seen = [], set()
        for a, b in zip(hits, r.search(question, k=k)):
            for h in (a, b):
                key = (h["repo"], h["title"])
                if key not in seen:
                    seen.add(key)
                    merged.append(h)
        hits = merged[:k]
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


def _inventory(con: sqlite3.Connection) -> dict:
    """DB에 실제로 무엇이 있는지. 없는 것을 묻고 있음을 모델이 알아채게 한다."""
    return {
        "metrics.name에 실제로 있는 값": [
            r[0] for r in con.execute("SELECT DISTINCT name FROM metrics ORDER BY name")],
        "repos.name": [r[0] for r in con.execute("SELECT name FROM repos ORDER BY name")],
    }


def _fallback(con: sqlite3.Connection, sql: str, cols: list[str]) -> dict:
    """조건을 벗긴 결과를 대신 돌려준다.

    metrics는 63행뿐이라 통째로 줘도 부담이 없다. 모델이 WHERE를 잘못 써서
    헛돈 경우가 대부분이고, 자료는 늘 손 닿는 곳에 있었다(실측: db 오답 9건
    전부 레포 전체를 긁으면 답이 그 안에 있었다).
    """
    known = [r[0] for r in con.execute("SELECT name FROM repos")]
    hit = [r for r in known if r.lower() in sql.lower()]
    if hit:
        marks = ",".join("?" * len(hit))
        cur = con.execute(
            f"SELECT repo, name, condition, baseline, value, unit "
            f"FROM metrics WHERE repo IN ({marks}) ORDER BY repo, name", hit)
        scope = f"{', '.join(hit)} 의 모든 metrics 행"
    else:
        cur = con.execute(
            "SELECT repo, name, condition, baseline, value, unit "
            "FROM metrics ORDER BY repo, name")
        scope = "metrics 전체"
    return {
        "columns": cols, "rows": [],
        "note": (f"요청한 조건으로는 0행이라, 조건을 벗기고 {scope}을 대신 붙였습니다. "
                 f"아래 fallback_rows에서 직접 고르세요. 여기에도 없으면 그 수치는 "
                 f"DB가 아니라 문서에 있는 것이므로 search_docs를 쓰세요."),
        "fallback_columns": [d[0] for d in cur.description],
        "fallback_rows": cur.fetchall(),
        "db에_있는_것": _inventory(con),
    }


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
            # 빈 결과에 "다시 조회하라"고 적어 보냈더니 14B조차 그 문장을 읽고
            # "결과가 없습니다"로 끝냈다(실측). 지시로는 안 된다는 뜻이라,
            # 이번엔 하네스가 직접 조건을 벗겨 다시 조회하고 그 자료를 붙인다.
            return json.dumps(_fallback(con, stripped, cols), ensure_ascii=False)
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
