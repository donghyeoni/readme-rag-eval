"""JupyterHub 커널을 통해 GPU 서버에 vLLM을 띄우고 상태를 확인한다.

SSH가 열려 있지 않고 JupyterHub만 있는 온프레미스 서버를 대상으로 한다.
커널에서 nohup으로 띄우므로 커널이 죽어도 서버는 남는다.

    JUP_HOST=<서버 주소> JUP_USER=<계정> JUP_TOKEN=<토큰> \
        python scripts/serve_vllm.py gpus          # 빈 GPU 확인
        python scripts/serve_vllm.py up --gpu 1    # 1번 GPU에 띄우기
        python scripts/serve_vllm.py status
        python scripts/serve_vllm.py down
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import uuid

HOST = os.environ.get("JUP_HOST", "")
USER = os.environ.get("JUP_USER", "")
TOKEN = os.environ.get("JUP_TOKEN", "")
BASE = f"http://{HOST}/user/{USER}"

MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
# 드라이버가 상한을 정한다. 570(CUDA 12.8)에서는 torch 2.13(cu130)을 끌어오는
# vLLM 0.20+ 가 엔진 초기화에서 죽는다. torch 2.10(cu128)에 고정된 마지막 계열이
# 0.17~0.19라 0.19.1을 쓴다. 자세한 판별 근거는 README의 "버전 고르기".
VERSION = os.environ.get("VLLM_VERSION", "0.19.1")
PORT = int(os.environ.get("VLLM_PORT", "8000"))
LOG = "~/vllm_readme_rag.log"

# JupyterHub 기본 파이썬(/opt/tljh/user)은 여러 사용자가 함께 쓴다. 거기에
# vLLM을 깔면 남의 환경까지 바꾸므로 홈에 전용 venv를 따로 만든다.
VENV = "~/vllm-venv"
PY = f"{VENV}/bin/python"


def api(path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Authorization": f"token {TOKEN}", "Content-Type": "application/json"},
    )
    r = urllib.request.urlopen(req, timeout=60).read()
    return json.loads(r) if r else None


def run(code: str, timeout: float = 600) -> str:
    """커널에서 코드를 실행하고 stdout/stderr를 합쳐 돌려준다."""
    from websocket import create_connection  # websocket-client

    k = api("/api/kernels", "POST", {"name": "python3"})
    kid = k["id"]
    try:
        ws = create_connection(
            f"ws://{HOST}/user/{USER}/api/kernels/{kid}/channels",
            header=[f"Authorization: token {TOKEN}"], timeout=timeout)
        msg_id = uuid.uuid4().hex
        ws.send(json.dumps({
            "header": {"msg_id": msg_id, "username": "x", "session": uuid.uuid4().hex,
                       "msg_type": "execute_request", "version": "5.3"},
            "parent_header": {}, "metadata": {},
            "content": {"code": code, "silent": False, "store_history": False,
                        "user_expressions": {}, "allow_stdin": False,
                        "stop_on_error": True},
        }))
        out = []
        while True:
            m = json.loads(ws.recv())
            if m.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            t, c = m["msg_type"], m.get("content", {})
            if t == "stream":
                out.append(c.get("text", ""))
            elif t in ("execute_result", "display_data"):
                out.append(c.get("data", {}).get("text/plain", ""))
            elif t == "error":
                out.append("\n".join(c.get("traceback", [])))
            elif t == "status" and c.get("execution_state") == "idle":
                break
        ws.close()
        return "".join(out)
    finally:
        try:
            api(f"/api/kernels/{kid}", "DELETE")
        except Exception:
            pass


# pip/vllm 로그에는 진행 막대 등 UTF-8이 아닌 바이트가 섞인다. text=True는
# strict 디코딩이라 거기서 UnicodeDecodeError로 죽으므로 직접 replace 디코딩한다.
SH = ("import subprocess;"
      "print(subprocess.run({!r},shell=True,capture_output=True)"
      ".stdout.decode('utf-8','replace'))")


def sh(cmd: str) -> str:
    return run(SH.format(cmd))


GPUS = ("nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu "
        "--format=csv,noheader")


def cmd_gpus() -> None:
    print(sh(GPUS))
    print("-- 이 GPU를 쓰는 프로세스 --")
    print(sh("nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory "
             "--format=csv,noheader"))


def cmd_setup() -> None:
    """전용 venv에 vLLM 설치. 내려받을 게 많아 오래 걸리므로 따로 둔다."""
    # 제자리 다운그레이드는 이전 설치의 nvidia-*-cu13 패키지가 남아 섞이므로
    # venv를 지우고 새로 만든다.
    print(sh(f"rm -rf {VENV} && python -m venv {VENV} && "
             f"{PY} -m pip install -q --upgrade pip && echo 'venv 준비됨'"))
    print(sh(f"setsid nohup {PY} -m pip install 'vllm=={VERSION}' "
             f"> ~/vllm_install.log 2>&1 < /dev/null & disown; "
             f"sleep 5; ls -la ~/vllm_install.log"))
    print("진행: python scripts/serve_vllm.py setup-status")


def cmd_setup_status() -> None:
    print(sh(f"{PY} -c 'import torch,vllm;print(\"torch\",torch.__version__,"
             f"\"vllm\",vllm.__version__)' 2>&1 | tail -3"))
    # 설치 로그는 한 줄이 수만 자라 그대로 찍으면 터미널이 막힌다
    print(sh("tail -n 3 ~/vllm_install.log 2>/dev/null | cut -c1-160 "
             "|| echo 'no install log'"))
    # inst[a]ll 로 쓰면 이 명령을 돌리는 셸의 명령줄에는 "install"이 없어
    # 자기 자신이 걸리지 않는다.
    print(sh("ps -eo cmd | grep -c 'vllm-venv/bin/pip inst[a]ll'"))


def cmd_up(gpu: int) -> None:
    start = (
        f"cd ~ && CUDA_VISIBLE_DEVICES={gpu} nohup {PY} -m vllm.entrypoints.openai.api_server "
        f"--model {MODEL} --port {PORT} --host 0.0.0.0 "
        f"--max-model-len 8192 --gpu-memory-utilization 0.85 "
        f"--enable-auto-tool-choice --tool-call-parser hermes "
        f"> {LOG} 2>&1 & echo started $!"
    )
    print(sh(start))
    print(f"로그: tail -f {LOG}  (모델 내려받기 때문에 첫 기동은 몇 분 걸린다)")


def cmd_status() -> None:
    print(sh(f"curl -s -m 5 http://127.0.0.1:{PORT}/v1/models || echo 'not up yet'"))
    print(sh(f"tail -n 20 {LOG} | cut -c1-160"))


def cmd_down() -> None:
    print(sh("pkill -f 'vllm[.]entrypoints' && echo killed || echo 'not running'"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["gpus", "setup", "setup-status", "up",
                                       "status", "down", "sh"])
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--cmd", default="")
    a = ap.parse_args()

    missing = [k for k in ("JUP_HOST", "JUP_USER", "JUP_TOKEN") if not os.environ.get(k)]
    if missing:
        print(f"환경변수가 없다: {', '.join(missing)}")
        return 1

    {"gpus": cmd_gpus, "setup": cmd_setup, "setup-status": cmd_setup_status,
     "status": cmd_status, "down": cmd_down,
     "up": lambda: cmd_up(a.gpu), "sh": lambda: print(sh(a.cmd))}[a.action]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
