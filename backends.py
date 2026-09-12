"""LLM 백엔드 2종을 같은 인터페이스 뒤에 둔다.

agent.py의 루프는 백엔드를 모른다. 그래서 API 모델과 로컬 GPU 모델을
같은 평가 스크립트로 돌려 비교할 수 있다.

중립 대화 형식(agent.py가 들고 있는 것):

    {"role": "user",      "text": "..."}
    {"role": "assistant", "text": "...", "tool_calls": [{"id","name","input"}]}
    {"role": "tool",      "results": [{"id","name","content","is_error"}]}

각 백엔드가 이걸 자기 wire 형식으로 옮긴다.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class Reply:
    """백엔드가 돌려주는 정규화된 한 턴."""
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    stop_reason: str = "end_turn"   # end_turn | tool_use | refusal | max_tokens
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0


class Backend:
    name = "base"

    def send(self, system: str, messages: list[dict], tools: list[dict]) -> Reply:
        raise NotImplementedError


# --------------------------------------------------------------------------
# 1. Anthropic API
# --------------------------------------------------------------------------
class AnthropicBackend(Backend):
    def __init__(self, model: str = "claude-opus-5", max_tokens: int = 4096):
        import anthropic  # 여기서만 import — vLLM만 쓸 때는 설치 불필요

        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.name = model

    def send(self, system, messages, tools) -> Reply:
        wire = []
        for m in messages:
            if m["role"] == "user":
                wire.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                blocks = []
                if m.get("text"):
                    blocks.append({"type": "text", "text": m["text"]})
                for tc in m.get("tool_calls", []):
                    blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["input"],
                    })
                wire.append({"role": "assistant", "content": blocks})
            else:  # tool
                # 병렬 호출이 와도 tool_result는 한 개의 user 메시지에 모아 보낸다.
                # 쪼개 보내면 모델이 병렬 호출을 그만한다.
                wire.append({"role": "user", "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r["id"],   # tool_use의 id와 정확히 일치해야 한다
                        "content": r["content"],
                        **({"is_error": True} if r.get("is_error") else {}),
                    }
                    for r in m["results"]
                ]})

        t0 = time.time()
        resp = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens,
            system=system, tools=tools, messages=wire,
        )
        dt = time.time() - t0

        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [
            {"id": b.id, "name": b.name, "input": b.input}
            for b in resp.content if b.type == "tool_use"
        ]
        return Reply(
            text=text, tool_calls=calls, stop_reason=resp.stop_reason,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            latency_s=dt,
        )


# --------------------------------------------------------------------------
# 2. OpenAI 호환 서버 (vLLM)
# --------------------------------------------------------------------------
class OpenAIToolBackend(Backend):
    """vLLM의 OpenAI 호환 /v1/chat/completions.

    의존성을 늘리지 않으려고 urllib으로 직접 친다. 도구 스키마 이름이
    Anthropic과 다르므로(input_schema -> parameters) 여기서 변환한다.
    """

    def __init__(self, base_url: str, model: str | None = None,
                 max_tokens: int = 2048, api_key: str = "EMPTY",
                 timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get("VLLM_API_KEY", api_key)
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.model = model or self._first_model()
        self.name = self.model

    def _http(self, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data,
            method="POST" if data else "GET",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{e.code} {e.read().decode(errors='replace')[:400]}") from e

    def _first_model(self) -> str:
        return self._http("/v1/models")["data"][0]["id"]

    @staticmethod
    def convert_tools(tools: list[dict]) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        } for t in tools]

    def send(self, system, messages, tools) -> Reply:
        wire: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                wire.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                msg: dict = {"role": "assistant", "content": m.get("text") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"],
                                     "arguments": json.dumps(tc["input"], ensure_ascii=False)},
                    } for tc in m["tool_calls"]]
                wire.append(msg)
            else:
                # OpenAI 형식은 tool_result를 도구별로 따로 보낸다 (Anthropic과 반대)
                for r in m["results"]:
                    wire.append({"role": "tool", "tool_call_id": r["id"],
                                 "content": r["content"]})

        t0 = time.time()
        out = self._http("/v1/chat/completions", {
            "model": self.model,
            "messages": wire,
            "tools": self.convert_tools(tools),
            "tool_choice": "auto",
            "max_tokens": self.max_tokens,
            "temperature": 0.0,
        })
        dt = time.time() - t0

        choice = out["choices"][0]
        msg = choice["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            raw = tc["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                # 작은 모델은 인자 JSON을 깨뜨리는 일이 잦다. 여기서 삼키지 말고
                # 도구 에러로 넘겨 평가에 잡히게 한다.
                args = {"__parse_error__": raw}
            calls.append({"id": tc.get("id") or f"call_{len(calls)}",
                          "name": tc["function"]["name"], "input": args})

        finish = choice.get("finish_reason") or "stop"
        stop = "tool_use" if calls else {"stop": "end_turn", "length": "max_tokens"}.get(finish, finish)
        usage = out.get("usage") or {}
        return Reply(
            text=msg.get("content") or "", tool_calls=calls, stop_reason=stop,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_s=dt,
        )


def make_backend(spec: str) -> Backend:
    """'anthropic' | 'anthropic:<model>' | 'vllm:<base_url>'"""
    if spec.startswith("vllm:"):
        return OpenAIToolBackend(spec[len("vllm:"):])
    if spec.startswith("anthropic:"):
        return AnthropicBackend(spec[len("anthropic:"):])
    if spec == "anthropic":
        return AnthropicBackend()
    raise ValueError(f"모르는 백엔드: {spec}")
