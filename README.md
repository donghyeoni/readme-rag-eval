# readme-rag-eval

내 프로젝트 README 12건을 검색하고 SQLite 메타DB에 질의해 답하는 도구 연동형 LLM 서비스다.
측정 결과, 설계 판단, 서버 설정은 [`log/service-log.md`](log/service-log.md)(이하 로그)에 있다.

## 동작

```
질문
 +-> [LLM 루프] --- tool_use ---> search_docs(query, k) --> docs/*.md 청크 BM25 상위 k개
       ^                     +--> query_db(sql)          --> SQLite (repos, metrics)
       |                                                        |
       +----------------- tool_result <-------------------------+

 최종 답변 = 텍스트 + 인용한 문단/행
```

1. 질문을 받으면 LLM이 도구를 골라 부른다.
   - `search_docs(query, k)`: `docs/*.md`를 마크다운 헤딩 단위로 자른 청크에서 BM25로 상위 k개를 찾는다.
     한국어 질문은 한→영 별칭표로 확장해 영어 README도 찾고, 모델의 검색어와 질문 원문으로 따로 찾은 결과를
     번갈아 섞는다. 표가 든 청크는 행 단위로 편 것을 함께 준다.
   - `query_db(sql)`: `repos`, `metrics` 두 테이블에 읽기 전용 SELECT를 실행한다.
2. 도구 결과를 받아 필요하면 다시 부른다. `query_db` 결과가 비면 조건을 뺀 행을 관련도 순으로 함께 돌려준다.
3. 답을 내기 전에 답의 수치가 도구 출력에 있는지 대조하고, 없으면 한 번 되묻는다(`verifier.py`).
4. 모델은 Anthropic API와 OpenAI 호환 서버(vLLM) 중 하나로 부른다(`--backend`).

## 사용 방법

```bash
pip install -r requirements.txt
python scripts/fetch_docs.py   # 검색 대상 README 12건 수집 (gh CLI 필요)
python build_db.py
```

검색기만 확인 (LLM 불필요):

```bash
python retriever.py "초해상도 중요도 맵"
python eval/run_eval.py --retrieval-only
```

질문 하나 던지기:

```bash
python agent.py "PSNR이 30dB를 넘은 프로젝트 알려줘" --backend vllm:http://localhost:8000 --trace
```

전체 평가 (도구 구성 A/B/C):

```bash
python eval/run_eval.py --backend vllm:http://localhost:8000 --toolsets A,B,C
```

온프레미스 GPU 서버(JupyterHub)에 vLLM을 올리는 경우:

```bash
export JUP_HOST=... JUP_USER=... JUP_TOKEN=...
python scripts/serve_vllm.py gpus      # 빈 GPU 확인
python scripts/serve_vllm.py setup     # 홈에 전용 venv 만들고 vLLM 설치
python scripts/serve_vllm.py up --gpu 0
python scripts/serve_vllm.py status
```
