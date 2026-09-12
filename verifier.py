"""답에 쓰인 수치가 도구 출력에 실제로 있었는지 대조한다.

측정에서 나온 실패 하나가 계기다. DB가 `baseline=28.15`를 돌려줬는데 모델은
"무작위 선택은 31.55"라고 답했다. 31.55는 어떤 도구 출력에도 없는 수다.
모델이 무엇을 받았는지 하네스가 이미 들고 있으므로(Trace), 대조는 코드가 할 수 있다.

이건 정답 여부를 판정하지 않는다. **근거 없는 수치를 지목할 뿐이다.**
답이 "약 3.4dB 개선"처럼 계산 결과를 적으면 그 수는 도구 출력에 없는 게
정상이므로, 도구가 준 수들의 사칙연산으로 설명되는지도 함께 본다.
"""
from __future__ import annotations

import itertools
import re

# 1,234.5 / 0.885 / 31.57 / 1e-3 / 5.60e8 형태
# 경계에 \w를 쓰면 안 된다 — 파이썬 \w는 한글도 포함해서 "0.912였습니다"의
# 숫자가 통째로 매칭되지 않는다(실제로 검증기가 아무것도 못 잡았다).
# ASCII 영숫자와 마침표만 경계에서 배제한다.
_EDGE = r"0-9A-Za-z_."
_NUM = re.compile(
    rf"(?<![{_EDGE}])-?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?(?![{_EDGE}])"
)

# 근거로 요구할 필요가 없는 수: 연도, 작은 정수(순번·개수), 백분율 표기 등
_TRIVIAL_MAX = 100


def numbers(text: str) -> list[str]:
    """텍스트에서 수치 토큰을 원문 그대로 뽑는다."""
    return [m.group(0) for m in _NUM.finditer(text)]


def _as_float(tok: str) -> float | None:
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def _derivable(target: float, pool: list[float], tol: float = 0.02) -> bool:
    """도구가 준 수 두 개의 사칙연산으로 설명되는가 (차이·합·비율)."""
    for a, b in itertools.permutations(pool, 2):
        for cand in (a - b, a + b, a / b if b else None, a * b):
            if cand is not None and abs(cand - target) <= tol:
                return True
    return False


def unsupported_numbers(answer: str, tool_outputs: list[str]) -> list[str]:
    """답에는 있는데 도구 출력에 없고, 계산으로도 설명되지 않는 수를 돌려준다."""
    haystack = "\n".join(tool_outputs)
    pool = [v for v in (_as_float(t) for t in numbers(haystack)) if v is not None]

    bad: list[str] = []
    for tok in numbers(answer):
        val = _as_float(tok)
        if val is None or abs(val) <= _TRIVIAL_MAX and float(val).is_integer():
            continue                      # 연도·순번·개수 같은 작은 정수는 넘긴다
        if tok in haystack:
            continue                      # 원문 그대로 옮긴 경우
        if any(abs(val - p) < 1e-9 for p in pool):
            continue                      # 표기만 다르고 같은 값
        if _derivable(val, pool):
            continue                      # 도구가 준 수로 계산되는 값
        if tok not in bad:
            bad.append(tok)
    return bad


def warning(bad: list[str]) -> str:
    return (
        "경고: 다음 수치는 도구 출력에 없고 도구가 준 값으로 계산되지도 않습니다: "
        + ", ".join(bad)
        + ". 도구가 돌려준 값을 다시 확인하고, 확인되지 않으면 그 수치를 빼고 답하세요."
    )
