"""검색 대상 README 12건을 GitHub에서 내려받아 docs/<repo>.md로 저장한다.

README 원본은 각 레포에 이미 공개돼 있으므로 이 저장소에는 사본을 두지 않는다
(.gitignore의 docs/*.md). 대신 이 스크립트로 언제든 같은 상태를 만든다.

    gh auth login          # 한 번만
    python scripts/fetch_docs.py

gh가 없으면 각 레포의 README.md를 직접 docs/<repo>.md로 저장해도 된다.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

USER = "donghyeoni"

# 평가에 쓴 12건. 목록을 고정해 두는 이유는 레포가 늘어도 측정 대상이
# 바뀌지 않게 하기 위해서다(수치를 비교할 수 있어야 한다).
REPOS = [
    "Algorithm-training",
    "vanilla-rnn-fpga-quantization",
    "yopar-attribute-recognition",
    "agv-grid-localization",
    "tre-deepfake-detection",
    "depth16-rgb-mapping",
    "digital-modulation-ber",
    "robust-image-classification",
    "jpeg-dct-compression",
    "yopar-edge-service",
    "gaps-uav-restoration",
    "rasr-region-adaptive-sr",
]

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    DOCS.mkdir(exist_ok=True)
    failed = []
    for repo in REPOS:
        out = subprocess.run(
            ["gh", "api", f"repos/{USER}/{repo}/readme",
             "-H", "Accept: application/vnd.github.raw"],
            capture_output=True,
        )
        if out.returncode != 0:
            failed.append(repo)
            print(f"{repo:<32} FAILED: {out.stderr.decode(errors='replace')[:80]}")
            continue
        path = DOCS / f"{repo}.md"
        path.write_bytes(out.stdout)
        print(f"{repo:<32} {len(out.stdout):>7,} bytes")

    print(f"\n{len(REPOS) - len(failed)}/{len(REPOS)}개 저장 -> {DOCS}")
    if failed:
        print(f"실패: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
