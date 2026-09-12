"""마크다운 청킹 + BM25 검색.

한국어/영어가 섞인 README를 대상으로 하므로 토큰화를 직접 정의한다.
영문·숫자는 소문자 단어, 한글은 2-gram. 형태소 분석기를 쓰지 않은 이유는
외부 의존성 없이 재현 가능하고, 짧은 기술 용어에서 재현율이 떨어지지
않기 때문이다(README.md의 "설계 판단" 참고).
"""
from __future__ import annotations

import glob
import os
import re

from rank_bm25 import BM25Okapi

from aliases import expand

MIN_CHUNK_CHARS = 30


def chunk_md(path: str) -> list[dict]:
    """헤딩(### 이하) 단위로 자르고, 짧은 절은 버린다."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    repo = os.path.splitext(os.path.basename(path))[0]
    parts: list[tuple[str, str]] = []
    cur: list[str] = []
    title = repo
    in_fence = False
    for line in text.splitlines():
        # ```bash 블록 안의 `# 주석`은 헤딩이 아니다. 이걸 빼먹으면 사용법
        # 코드블록의 주석 한 줄이 통째로 청크 제목이 된다.
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            cur.append(line)
            continue
        if not in_fence and re.match(r"^#{1,3} ", line):
            if cur:
                parts.append((title, "\n".join(cur).strip()))
            title, cur = line.lstrip("# ").strip(), []
        else:
            cur.append(line)
    if cur:
        parts.append((title, "\n".join(cur).strip()))
    return [
        {"repo": repo, "title": t, "text": b}
        for t, b in parts
        if len(b) > MIN_CHUNK_CHARS
    ]


def tokenize(s: str) -> list[str]:
    s = s.lower()
    words = re.findall(r"[a-z0-9][a-z0-9._+-]*", s)
    hangul = re.findall(r"[가-힣]+", s)
    bigrams = [h[i:i + 2] for h in hangul for i in range(max(len(h) - 1, 1))]
    return words + bigrams


class Retriever:
    """BM25 검색기.

    expand_query=False로 만들면 한->영 질의 확장을 끈다. 확장이 실제로
    이득인지 평가에서 끄고 켜 보기 위한 스위치다.
    """

    def __init__(self, docs_dir: str = "docs", expand_query: bool = True):
        self.expand_query = expand_query
        paths = sorted(glob.glob(os.path.join(docs_dir, "*.md")))
        if not paths:
            raise FileNotFoundError(f"{docs_dir}/*.md 가 없다")
        self.chunks = [c for p in paths for c in chunk_md(p)]
        # 청크에는 레포명과 제목도 검색어로 걸리게 넣는다. 본문만 색인하면
        # "rasr" 같은 레포 이름으로 찾을 수 없다.
        self.bm25 = BM25Okapi(
            [tokenize(f"{c['repo']} {c['title']} {c['text']}") for c in self.chunks]
        )

    def search(self, query: str, k: int = 5) -> list[dict]:
        q = tokenize(query)
        if self.expand_query:
            q = expand(q)
        scores = self.bm25.get_scores(q)
        idx = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        return [
            dict(self.chunks[i], score=round(float(scores[i]), 3))
            for i in idx
        ]


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    r = Retriever()
    print(f"{len(r.chunks)} chunks from {len(set(c['repo'] for c in r.chunks))} repos")
    q = " ".join(sys.argv[1:]) or "초해상도 중요도 맵"
    for h in r.search(q, k=5):
        print(f"  {h['score']:8.3f}  {h['repo']:<32} {h['title'][:50]}")
