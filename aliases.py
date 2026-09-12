"""한국어 질문 -> 영어 문서를 잇는 질의 확장 표.

문서 12건 중 9건이 영어 README, 3건이 한국어다. BM25는 어휘 일치만 보므로
"초해상도"로는 "super-resolution"이 절대 걸리지 않는다. 실제로 확장 없이
평가하면 한국어 질문의 Recall@3이 무너진다(README.md의 실험 D 참고).

임베딩 대신 손으로 쓴 표를 고른 이유: 항목이 40개뿐이고, 무엇이 왜 걸렸는지
한 줄로 설명되며, 모델·차원 선택에 시간을 쓰지 않아도 된다. 확장은 질의
쪽에만 적용한다(문서 색인은 건드리지 않는다).
"""

ALIASES: dict[str, list[str]] = {
    # 도메인
    "초해상도": ["super", "resolution", "sr", "upscale", "upscaler"],
    "해상도": ["resolution"],
    "중요도": ["importance"],
    "복원": ["restoration", "reconstruction", "reconstruct", "restore"],
    "재구성": ["reconstruction", "reconstruct"],
    "압축": ["compression", "compress", "jpeg", "codec"],
    "분류": ["classification", "classifier", "classify"],
    "탐지": ["detection", "detect", "detector"],
    "검출": ["detection", "detect"],
    "딥페이크": ["deepfake", "diffusion", "genimage", "ai-generated"],
    "생성기": ["generator", "generators"],
    "일반화": ["generalization", "generalisation", "transfer"],
    "위치": ["localization", "location", "position"],
    "격자": ["grid", "cell"],
    "속성": ["attribute", "par", "attributes"],
    "인식": ["recognition", "recognize"],
    "변조": ["modulation", "bpsk", "qpsk", "qam"],
    "부호": ["coding", "code", "encoder", "convolutional"],
    "복호": ["decoding", "decoder", "viterbi"],
    "페이딩": ["fading", "rayleigh"],
    "파일럿": ["pilot", "pilots"],
    "심도": ["depth"],
    "깊이": ["depth"],
    "서브밴드": ["subband", "subbands"],
    # 방법·연산
    "양자화": ["quantization", "quantize", "quantized", "q1.15", "int16"],
    "고정소수점": ["fixed", "point", "fixed-point", "q1.15"],
    "가중치": ["weight", "weights"],
    "은닉": ["hidden"],
    "룩업": ["lut", "lookup"],
    "잡음": ["noise", "noisy", "gaussian", "impulse"],
    "필터": ["filter", "filters", "filtering"],
    "중앙값": ["median"],
    "양방향": ["bilateral"],
    "보간": ["interpolation", "interpolate", "bilinear", "bicubic"],
    "기울기": ["gradient"],
    "패치": ["patch", "patches"],
    "선택": ["selection", "select"],
    "무작위": ["random"],
    "마스크": ["mask", "masks"],
    "대역폭": ["bandwidth", "budget"],
    "전송": ["transmission", "transmit", "transmitted"],
    "예산": ["budget"],
    "채널": ["channel", "channels"],
    "추정": ["estimation", "estimate"],
    "학습": ["train", "training", "trained"],
    "정확도": ["accuracy", "acc"],
    "손실": ["loss", "degradation"],
    "성능": ["performance"],
    "엣지": ["edge", "jetson"],
    "카메라": ["camera", "rtsp"],
    "색": ["color", "colour"],
    "소매": ["sleeve"],
    "성별": ["gender"],
    "사람": ["person", "pedestrian"],
    "헤더": ["header"],
    "표": ["table", "lut"],
    "단어": ["word", "words"],
    "글자": ["char", "character", "letter"],
}


def expand(tokens: list[str]) -> list[str]:
    """토큰 리스트에 별칭을 덧붙인다. 원래 토큰은 그대로 둔다.

    한글은 2-gram으로 토큰화되므로 "초해상도"는 [초해, 해상, 상도]로 들어온다.
    그래서 3글자 이상 키는 키의 2-gram이 전부 들어 있는지로 판정한다.
    """
    tset = set(tokens)
    extra: list[str] = []
    for key, vals in ALIASES.items():
        if len(key) <= 2:
            hit = key in tset
        else:
            hit = all(key[i:i + 2] in tset for i in range(len(key) - 1))
        if hit:
            extra.extend(vals)
    return tokens + extra
