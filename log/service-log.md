# 서비스 로그

검색 대상, 측정 결과, 설계 판단, 서버 설정, 한계를 정리한다. README에는 동작과 사용 방법만 둔다.

## 1. 검색 대상과 DB

- **대상.** `donghyeoni` 계정의 공개 레포 중 포크와 이 레포(`readme-rag-eval`)를 뺀 14개다. `scripts/fetch_docs.py`가
  GitHub API로 레포 목록과 메타데이터(`data/repos.json`)를 받고, 각 README를 `docs/<repo>.md`로 저장한다.
- **문서 검색.** 청크 117개 / 13개 레포다. `Algorithm-training`은 README가 한 줄이라 청크가 없다.
- **DB.** `build_db.py`가 만든다.
  - `repos` 14행: GitHub 메타데이터(언어, 설명, topic, 생성일, 마지막 푸시일)와, README 첫 12줄에 있는 날짜 범위(`YYYY.MM.DD –
    YYYY.MM.DD`) 중 가장 이른 시작과 가장 늦은 끝으로 정한 `started`, `ended`, `duration_days`. 기간이 적힌 레포는 5개다.
  - `cells` 729행: 모든 README의 마크다운 표를 칸 단위로 저장한다. 표 위 제목(`section`), 행의 첫 칸(`row_label`),
    열 이름(`col`), 칸 원문(`value`), 원문의 첫 숫자(`number`)다. 숫자를 읽은 칸은 586개다. 칸 안의 `\|`는 구분자로 보지 않고, 유니코드 마이너스(−)는 앞에 글자나
    닫는 괄호가 없을 때 음수 부호로 읽는다.

```sql
repos(name, language, description, topics, created, pushed, started, ended, duration_days)
cells(repo, section, table_no, row_no, row_label, col, value, number)
```

## 2. 측정 (Qwen2.5-14B)

- **문항.** 새로 만든 50개(`eval/questions.jsonl`)다. DB로 답하는 `d1`–`d25`와 문서로 답하는 `s1`–`s25`이고, 46문항에
  정답 레포가 있다. `eval/verify_labels.py`로 확인한 라벨 근거 실패는 0건이다.
- **설정.** 빈 결과 폴백, 검색어 섞기, 표 펴기, 수치 검증기를 모두 켠 상태다. 시스템 프롬프트 v2, 질의 확장 on,
  컨텍스트 8192 토큰이다.
- **서빙.** vLLM 0.19.1로 GPU 1·2·3번에 같은 설정의 서버를 하나씩 띄우고, 도구 구성 A·B·C를 한 서버씩 맡겨 동시에
  돌렸다.

| 조건 | 도구 | Recall@3 | 정답률 | DB 문항 (25) | 문서 문항 (25) | 도구 선택 | 평균 호출 | 에러율 | 지연 |
|---|---|---|---|---|---|---|---|---|---|
| C | 둘 다 | 0.457 | **0.480** | 14 | 10 | 0.840 | 1.2 | 0.103 | 8.6s |
| A | 검색만 | 0.761 | 0.460 | 8 | 15 | (1.000) | 0.8 | 0.050 | 8.1s |
| B | SQL만 | -- | 0.280 | 14 | 0 | (1.000) | 1.4 | 0.265 | 11.7s |

| 조건 | 생성 실패 | 도구 선택 실패 | 도구 구성 한계 | 도구 미사용 | 검색 실패 | 루프 미종료 | 하네스 에러 |
|---|---|---|---|---|---|---|---|
| C | 18 | 6 | 0 | 0 | 0 | 1 | 1 |
| A | 9 | 0 | 4 | 13 | 1 | 0 | 0 |
| B | 10 | 0 | 20 | 4 | 0 | 2 | 0 |

A·B는 고를 도구가 하나뿐이라 도구 선택 정확도가 항상 1.000이다. C의 하네스 에러 1건(`d6`)은 컨텍스트 초과(400)로 답을
받지 못한 문항이고, 이 문항의 토큰과 지연은 0으로 집계됐다. 50문항 토큰은 C 입력 181,408 / 출력 10,383, A 132,021 /
9,876, B 162,424 / 14,411이다. 결과 파일은 `results/agent_{A,B,C}_14b.csv`, `results/summary_14b_{A,B,C}.md`다.

**검색기 단독 Recall.** 정답 레포가 있는 46문항에서 한→영 질의 확장을 켜고 끈 결과다(`results/retrieval.md`).

| 질의 확장 | Recall@1 | Recall@3 | Recall@5 |
|---|---|---|---|
| off | 0.630 | 0.761 | 0.891 |
| **on** | **0.783** | **0.891** | **0.935** |

## 3. 파일 구성

| 파일 | 역할 |
|---|---|
| [`scripts/fetch_docs.py`](../scripts/fetch_docs.py) | 계정의 공개 레포 목록·메타데이터와 README 수집 (`--user`) |
| [`build_db.py`](../build_db.py) | `repos`(메타데이터 + README 기간)와 `cells`(README 표의 칸) 적재 |
| [`retriever.py`](../retriever.py) | 마크다운 헤딩 단위 청킹 + BM25. 한글 2-gram 토큰화 |
| [`aliases.py`](../aliases.py) | 한국어 질문 → 영어 용어를 잇는 질의 확장표 (58항목) |
| [`tools.py`](../tools.py) | `search_docs` / `query_db` 구현과 도구 스키마 |
| [`backends.py`](../backends.py) | Anthropic API와 OpenAI 호환(vLLM)을 한 인터페이스 뒤에 |
| [`agent.py`](../agent.py) | `stop_reason`을 보며 직접 도는 도구 호출 루프 |
| [`verifier.py`](../verifier.py) | 답의 수치가 도구 출력에 있는지 대조 |
| [`eval/`](../eval/) | 라벨 50문항, 측정·비교·라벨검증 스크립트 |
| [`scripts/serve_vllm.py`](../scripts/serve_vllm.py) | JupyterHub 커널로 온프레미스 GPU에 vLLM 기동 |

## 4. 설계 판단

**도구를 문서 검색과 SQL로 나눈 이유.** 서술형 질문("왜 이 필터를 골랐나")에는 문단이, 집계 질문("PSNR이
30dB를 넘는 프로젝트를 전부")에는 정렬 가능한 행이 필요하다. 도구 구성 A(검색만) / B(SQL만) / C(둘 다)를 같은
50문항에 돌려 비교했다(2절).

**README 표를 칸 단위로 저장하는 이유.** README마다 표 형식과 지표 이름이 달라, 지표 이름·조건·값으로 나누는 파서는
조용히 틀린다. 그래서 표를 해석하지 않고 칸 그대로 저장한다. 지표를 찾는 일은 `section`, `row_label`, `col`에 대한 `LIKE`로 모델이 한다.

**한글 토큰화를 2-gram으로 한 이유.** 형태소 분석기는 외부 의존성과 설치 실패 지점을 늘린다. 2-gram은 추가 설치
없이 동작하고, `PSNR`·`Q1.15` 같은 짧은 기술 용어를 쪼개지 않는다.

**한→영 질의 확장을 붙인 이유.** 검색 대상 README에 영어 문서와 영어 용어가 섞여 있고, BM25는 어휘 일치만 본다.
"초해상도"로는 "super-resolution"이 걸리지 않는다. 임베딩 대신 손으로 쓴 표를 고른 이유는 항목 수가 적고, 무엇이
왜 걸렸는지 한 줄로 설명되기 때문이다.

**LLM이 생성한 SQL을 막는 방법.** 두 겹이다.

1. `SELECT`로 시작하지 않거나 쓰기 키워드(`insert|update|delete|drop|...`)가 보이면 거절하고, 세미콜론으로 문을
   이어 붙이는 것도 막는다.
2. 연결 자체를 읽기 전용으로 연다 — `sqlite3.connect("file:meta.db?mode=ro", uri=True)`.

1번은 통과하지만 의도와 다른 SELECT(예: `UNION`으로 상수 행 붙이기)는 여전히 가능해서, 연결 수준에서 한 겹 더
둔다.

**루프를 직접 쓴 이유.** SDK의 `tool_runner`가 루프를 대신 돌려주지만, 측정하려는 대상(어떤 도구를 먼저
불렀나, 몇 번 불렀나, 도구가 몇 번 실패했나)이 루프 안에 있다. 직접 들고 있어야 `Trace`로 뽑을 수 있다.
루프에서 지키는 규칙은 세 가지다.

1. `tool_result`의 `tool_use_id`는 해당 `tool_use`의 `id`와 같아야 한다.
2. 한 응답에 `tool_use`가 여러 개 오면 모든 `tool_result`를 하나의 메시지에 담는다. OpenAI 호환 쪽은 반대로
   도구마다 `role: "tool"` 메시지를 따로 보낸다 — `backends.py`가 이 차이를 흡수한다.
3. 실패한 도구도 결과를 빼먹지 않고 돌려준다. Anthropic 형식은 `is_error`를 붙이고, OpenAI 호환 형식에는 이
   필드가 없어 `ERROR:`로 시작하는 결과 문자열만 보낸다.

**`docs/*.md`를 저장소에 넣지 않는 이유.** 원본이 각 레포에 공개돼 있어 사본을 두면 두 곳이 갈라진다.
`scripts/fetch_docs.py`로 받는다.

## 5. 온프레미스 GPU 서버 설정

사내 GPU 서버(L40S ×4, JupyterHub만 열려 있고 SSH는 없음)에 vLLM을 올렸다. `scripts/serve_vllm.py`가
JupyterHub 커널 WebSocket으로 원격 명령을 보낸다.

- 공용 파이썬(`/opt/tljh/user`)은 다른 사용자가 함께 쓰므로, 홈에 venv를 따로 만들어 설치했다.
- 비어 있던 GPU 1·2·3번에 서버를 하나씩 띄웠다. 8001번 포트는 다른 서비스가 쓰고 있어 8000, 8002, 8003번을 썼다.

**vLLM 버전.** `pip install vllm`으로 최신판(0.29.0)을 깔면 `torch 2.13.0+cu130`이 따라오는데, 이 서버
드라이버는 `570.211.01`(CUDA 12.8)이라 엔진이 뜨지 않는다:

```
RuntimeError: The NVIDIA driver on your system is too old (found version 12080)
```

vLLM 휠은 파일명에 CUDA 버전이 없어서, 각 vLLM이 고정한 torch의 PyPI 기본 CUDA로 거꾸로 판별했다.

| vLLM | 고정 torch | torch의 PyPI 기본 CUDA | 이 드라이버에서 |
|---|---|---|---|
| 0.27 ~ 0.29 | 2.13.0 | cu130 | X |
| 0.20 ~ 0.26 | 2.11.0 | cu13x | X |
| **0.17 ~ 0.19** | **2.10.0** | **`nvidia-cuda-runtime-cu12==12.8.90`** | **O** |

그래서 `vllm==0.19.1`로 고정했다. `torch`만 cu128로 내리는 방법은 vLLM의 컴파일된 확장이 CUDA 13으로 빌드돼
있어(`libcudart.so.13`을 찾음) 동작하지 않는다. 제자리 다운그레이드는 이전 설치의 `nvidia-*-cu13` 패키지가
남아 섞이므로 venv를 새로 만들었다. 드라이버는 공용 서버라 건드리지 않았다.

## 6. 한계

- 문서 14건, 질문 50개다.
- `must_include` 문자열 일치로 채점한다. 필요한 문자열이 모두 들어 있으면, 답에 틀린 항목이 더 있어도 정답이 된다.
  `eval/verify_labels.py`는 라벨이 원문에 있는지와 약한 라벨만 검사한다.
- 질문을 직접 썼다.
- Qwen2.5-14B 한 모델로만 측정했다.
- 질의 확장표는 손으로 썼고, 레포가 바뀌면 손봐야 한다.
