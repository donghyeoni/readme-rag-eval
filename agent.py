"""LLM 하네스 — stop_reason을 보며 직접 도는 도구 호출 루프.

SDK의 tool_runner가 대신 돌려주기도 하지만 직접 썼다. 루프 안에서 무엇이
오가는지가 이 프로젝트에서 측정하려는 대상이기 때문이다(어떤 도구를 몇 번
불렀는가, 도구가 몇 번 실패했는가).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

from backends import Backend, Reply, make_backend
from verifier import unsupported_numbers, warning
from tools import DISPATCH, TOOLSETS

_BASE = (
    "너는 한 개발자의 프로젝트 문서를 검색해 질문에 답하는 조수다. "
    "반드시 도구로 확인한 내용만 답하고, 답 끝에 근거(레포명과 문단 제목, "
    "또는 SQL 결과 행)를 적어라."
)
_NUM = " 수치는 도구가 돌려준 값을 그대로 옮기고 반올림하거나 바꾸지 마라."

# v0가 처음 쓴 문구다. "확인되지 않으면 모른다고 답하라"가 7B 모델에서는
# **도구를 부르기 전에** 모른다고 답해도 된다는 허가로 읽혀, 도구 호출이
# 통째로 사라졌다. 측정으로 잡아낸 것이라 비교용으로 남겨 둔다
# (README의 "프롬프트 한 문장이 도구 호출을 없앤다" 참고).
SYSTEM_VARIANTS = {
    "v0": _BASE + " 도구로 확인되지 않으면 모른다고 답하라." + _NUM,
    "v2": _BASE + " 도구를 한 번도 부르지 않은 채로 모른다고 답해서는 안 된다." + _NUM,
}
SYSTEM = SYSTEM_VARIANTS["v2"]


@dataclass
class Trace:
    """한 질문을 처리하는 동안 일어난 일 전부. 평가는 이걸 읽는다."""
    calls: list[dict] = field(default_factory=list)   # {tool, input, output, is_error}
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    stop_reason: str = ""
    recovered_calls: int = 0      # 본문에서 건져낸 도구 호출 수
    verifier_hits: int = 0        # 근거 없는 수치로 되물은 횟수

    @property
    def first_tool(self) -> str | None:
        return self.calls[0]["tool"] if self.calls else None

    @property
    def n_calls(self) -> int:
        return len(self.calls)

    @property
    def n_errors(self) -> int:
        return sum(1 for c in self.calls if c["is_error"])

    def retrieved_repos(self, top: int = 3) -> list[str]:
        """search_docs가 상위 `top`개로 돌려준 레포명 (Recall@k 계산용)."""
        import json

        repos: list[str] = []
        for c in self.calls:
            if c["tool"] != "search_docs" or c["is_error"]:
                continue
            try:
                hits = json.loads(c["output"])
            except (json.JSONDecodeError, TypeError):
                continue
            for h in hits[:top]:
                if h["repo"] not in repos:
                    repos.append(h["repo"])
        return repos


def _shrink(messages: list[dict], keep: int = 700) -> bool:
    """가장 오래된 도구 결과부터 줄인다. 줄일 게 있었으면 True."""
    for m in messages:
        if m["role"] != "tool":
            continue
        for r in m["results"]:
            if len(r["content"]) > keep:
                n = len(r["content"])
                note = "...(분량 때문에 잘림. 원래 " + str(n) + "자)"
                r["content"] = r["content"][:keep] + chr(10) + note
                return True
    return False


def ask(question: str, backend: Backend, toolset: str = "C",
        max_turns: int = 6, expand_query: bool = True,
        system: str = SYSTEM, verify: bool = True) -> tuple[str, Trace]:
    tools = TOOLSETS[toolset]
    messages: list[dict] = [{"role": "user", "text": question}]
    tr = Trace()
    rechecked = False      # 되묻기는 한 번만 (무한 왕복 방지)

    for _ in range(max_turns):
        try:
            reply: Reply = backend.send(system, messages, tools)
        except RuntimeError as e:
            # 컨텍스트를 넘겨도 문항을 죽이지 않는다. 오래된 도구 결과를 줄여
            # 한 번 더 시도한다 — 실측에서 두 문항이 400으로 답변조차 못 받았다.
            if "context length" not in str(e) or not _shrink(messages):
                raise
            reply = backend.send(system, messages, tools)
        tr.turns += 1
        tr.input_tokens += reply.input_tokens
        tr.output_tokens += reply.output_tokens
        tr.latency_s += reply.latency_s
        tr.stop_reason = reply.stop_reason
        tr.recovered_calls += reply.recovered_calls

        if reply.stop_reason == "refusal":       # 항상 먼저 확인
            return "REFUSED", tr
        if not reply.tool_calls:
            # 답을 내기 전에, 쓰인 수치가 도구 출력에 실제로 있었는지 대조한다.
            # 도구가 값을 돌려줬는데도 생성 단계에서 바뀌는 일이 실제로 있었다.
            if verify and not rechecked and tr.calls:
                bad = unsupported_numbers(
                    reply.text, [c["output"] for c in tr.calls if not c["is_error"]])
                if bad:
                    tr.verifier_hits += len(bad)
                    rechecked = True
                    messages.append({"role": "assistant", "text": reply.text,
                                     "tool_calls": []})
                    messages.append({"role": "user", "text": warning(bad)})
                    continue
            return reply.text, tr

        messages.append({"role": "assistant", "text": reply.text,
                         "tool_calls": reply.tool_calls})

        results = []
        for tc in reply.tool_calls:
            args = dict(tc["input"])
            if "__parse_error__" in args:
                out, err = f"ERROR: 인자 JSON을 읽을 수 없습니다: {args['__parse_error__'][:200]}", True
            elif tc["name"] not in DISPATCH:
                out, err = f"ERROR: 없는 도구입니다: {tc['name']}", True
            else:
                if tc["name"] == "search_docs":
                    args["expand_query"] = expand_query
                    args.setdefault("question", question)
                try:
                    out = DISPATCH[tc["name"]](**args)
                    err = out.startswith("ERROR")
                except Exception as e:                  # 도구가 터져도 루프는 계속
                    out, err = f"ERROR: {type(e).__name__}: {e}", True
            tr.calls.append({"tool": tc["name"], "input": tc["input"],
                             "output": out, "is_error": err})
            # 실패한 도구도 결과를 빼먹지 말고 is_error로 돌려준다
            results.append({"id": tc["id"], "name": tc["name"],
                            "content": out, "is_error": err})

        messages.append({"role": "tool", "results": results})

    tr.stop_reason = "max_turns"
    return "MAX_TURNS", tr


def main() -> int:
    import argparse

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="*")
    ap.add_argument("--backend", default="anthropic",
                    help="anthropic | anthropic:<model> | vllm:<base_url>")
    ap.add_argument("--toolset", default="C", choices=list(TOOLSETS))
    ap.add_argument("--no-expand", action="store_true", help="한->영 질의 확장 끄기")
    ap.add_argument("--system", default="v2", choices=list(SYSTEM_VARIANTS),
                    help="시스템 프롬프트 판본")
    ap.add_argument("--trace", action="store_true", help="도구 호출 내역 출력")
    a = ap.parse_args()

    q = " ".join(a.question)
    if not q:
        ap.error("질문을 입력하세요")

    answer, tr = ask(q, make_backend(a.backend), toolset=a.toolset,
                     expand_query=not a.no_expand,
                     system=SYSTEM_VARIANTS[a.system])
    print(answer)
    print()
    print(f"-- {tr.turns}턴 / 도구 {tr.n_calls}회(에러 {tr.n_errors}) / "
          f"{tr.latency_s:.1f}s / in {tr.input_tokens} out {tr.output_tokens} tok")
    if a.trace:
        for c in tr.calls:
            print(f"   {c['tool']}({c['input']}) -> {c['output'][:160]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
