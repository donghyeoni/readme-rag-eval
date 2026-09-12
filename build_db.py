"""메타DB 생성. 수치는 README에서 손으로 옮긴다.

12개뿐이라 파싱을 자동화하지 않았다. 파서를 쓰면 표 형식이 제각각이라
디버깅에 더 오래 걸리고, 틀렸을 때 조용히 틀린다.
"""
import sqlite3

DB = "meta.db"

SCHEMA = """
DROP TABLE IF EXISTS metrics;
DROP TABLE IF EXISTS repos;
CREATE TABLE repos (
  name TEXT PRIMARY KEY, language TEXT, domain TEXT,
  started TEXT, ended TEXT, summary TEXT
);
CREATE TABLE metrics (
  repo TEXT REFERENCES repos(name),
  name TEXT,          -- PSNR / accuracy / MSE / EbNo ...
  condition TEXT,     -- 'impulse p=0.05' / '2단 재구성' ...
  baseline REAL, value REAL, unit TEXT
);
"""

# (name, language, domain, started, ended, summary)
# 날짜는 GitHub의 createdAt / updatedAt.
REPOS = [
    ("rasr-region-adaptive-sr", "Python", "super-resolution",
     "2026-08-10", "2026-08-17",
     "촬영 예산 제약 하 영역 적응형 초해상도. 3x128^2 픽셀로 512^2 복원"),
    ("gaps-uav-restoration", "Python", "image-restoration",
     "2026-07-29", "2026-08-17",
     "UAV 영상의 고전적 복원. 잡음 제거 + 대역폭 제한 재구성(NumPy 자체 구현)"),
    ("robust-image-classification", "Python", "classification",
     "2026-08-07", "2026-08-12",
     "대역폭·잡음 제약 하 영상 분류 견고성. ResNet-18, 4클래스"),
    ("tre-deepfake-detection", "Python", "deepfake-detection",
     "2026-08-13", "2026-08-17",
     "확산모델 시간적 재구성오차(TRE)로 AI 생성 영상 탐지 재검증. 결론은 음성"),
    ("depth16-rgb-mapping", "Python", "encoding",
     "2026-08-12", "2026-08-12",
     "16bit 심도 영상을 8bit RGB로 부호화하고 왕복 오차를 MSE로 측정"),
    ("jpeg-dct-compression", "Python", "compression",
     "2026-08-10", "2026-08-12",
     "서브밴드 변환 대 블록 DCT JPEG의 율-왜곡 비교. 전 과정 자체 구현"),
    ("digital-modulation-ber", "MATLAB", "communication",
     "2026-08-12", "2026-08-12",
     "BPSK~256QAM의 BER 대 Eb/No. AWGN 및 레일리, 파일럿 추정, 길쌈부호"),
    ("vanilla-rnn-fpga-quantization", "C", "quantization",
     "2026-07-30", "2026-08-26",
     "vanilla RNN을 고정소수점 int16으로 양자화해 FPGA용 C 헤더 생성"),
    ("yopar-attribute-recognition", "Python", "attribute-recognition",
     "2026-08-06", "2026-08-17",
     "인상착의 검색용 PAR 모델 학습. 성별/상의색/하의색/소매 4속성"),
    ("yopar-edge-service", "Python", "edge-service",
     "2026-08-07", "2026-08-17",
     "Jetson에서 RTSP 카메라 4대를 받아 사람 검출, 속성 인식, 서버 매칭"),
    ("agv-grid-localization", "Python", "object-localization",
     "2026-08-11", "2026-08-17",
     "AGV 작업대 사진에서 8x8 격자를 잡고 YOLOv5로 물체의 셀 위치를 보고"),
    ("Algorithm-training", "C++", "algorithm",
     "2026-07-30", "2026-09-02",
     "알고리즘 연습 문제 풀이. README가 한 줄이라 문서 검색 대상이 없다"),
]

# (repo, name, condition, baseline, value, unit)
METRICS = [
    # --- rasr-region-adaptive-sr ---
    ("rasr-region-adaptive-sr", "PSNR", "업스케일러 UUDCNN (기준 SRCNN)", 28.21, 31.10, "dB"),
    ("rasr-region-adaptive-sr", "PSNR", "업스케일러 UDUCNN", 28.21, 30.99, "dB"),
    ("rasr-region-adaptive-sr", "PSNR", "업스케일러 TransConv", 28.21, 30.78, "dB"),
    ("rasr-region-adaptive-sr", "PSNR", "2단 재구성 128-256-512, MRIMCNN (기준 무작위 선택)", 28.15, 31.57, "dB"),
    ("rasr-region-adaptive-sr", "PSNR", "2단 재구성, IMCNN (기준 무작위 선택)", 28.15, 31.53, "dB"),
    ("rasr-region-adaptive-sr", "PSNR", "2단 재구성, UUDCNN 캐스케이드만", None, 27.15, "dB"),
    # --- gaps-uav-restoration ---
    ("gaps-uav-restoration", "PSNR", "임펄스 p=0.05, median 3x3 (기준 잡음영상)", 18.20, 43.92, "dB"),
    ("gaps-uav-restoration", "PSNR", "임펄스 p=0.1, median 3x3 (기준 잡음영상)", 15.17, 39.19, "dB"),
    ("gaps-uav-restoration", "PSNR", "가우시안 std=10, bilateral C=30 (기준 잡음영상)", 28.13, 33.03, "dB"),
    ("gaps-uav-restoration", "PSNR", "가우시안 std=50, averaging 3x3 (기준 잡음영상)", 14.82, 23.39, "dB"),
    ("gaps-uav-restoration", "PSNR", "대역폭 제한 재구성 256, gradient 선택 + bicubic (기준 random+bilinear)", 28.01, 33.96, "dB"),
    ("gaps-uav-restoration", "PSNR", "대역폭 제한 재구성 512, gradient 선택 + bicubic (기준 random+bilinear)", 23.39, 26.77, "dB"),
    # --- robust-image-classification ---
    ("robust-image-classification", "accuracy", "RGB 256x256 3채널 (무잡음)", None, 0.869, ""),
    ("robust-image-classification", "accuracy", "이진화 64x64 1채널 (무잡음)", None, 0.668, ""),
    ("robust-image-classification", "accuracy", "에지맵 64x64 1채널 (무잡음)", None, 0.696, ""),
    ("robust-image-classification", "accuracy", "blur+edge 45x45 2채널 (무잡음)", None, 0.734, ""),
    ("robust-image-classification", "accuracy", "Haar 서브밴드 32x32 4채널 (무잡음)", None, 0.582, ""),
    ("robust-image-classification", "accuracy", "s&p 0.10, 복구 없음", None, 0.617, ""),
    ("robust-image-classification", "accuracy", "s&p 0.10, majority 필터", None, 0.604, ""),
    ("robust-image-classification", "accuracy", "s&p 0.10, 커스텀 픽셀 규칙", None, 0.723, ""),
    ("robust-image-classification", "accuracy", "s&p 0.10, MRF(Ising) 복원", None, 0.618, ""),
    ("robust-image-classification", "accuracy", "s&p 0.50, 커스텀 픽셀 규칙 (4클래스 우연수준)", None, 0.376, ""),
    # --- tre-deepfake-detection ---
    ("tre-deepfake-detection", "accuracy", "조건 A 잡음 재생, 8종 생성기 평균", None, 0.577, ""),
    ("tre-deepfake-detection", "accuracy", "조건 B 새 잡음 주입, 8종 평균", None, 0.501, ""),
    ("tre-deepfake-detection", "accuracy", "조건 C eta=0, 8종 평균", None, 0.605, ""),
    ("tre-deepfake-detection", "accuracy", "조건 C + 두 번째 인버터, 8종 평균", None, 0.625, ""),
    ("tre-deepfake-detection", "accuracy", "조건 C, SD 계열 3종(sdv4/sdv5/wukong)", None, 0.788, ""),
    ("tre-deepfake-detection", "accuracy", "조건 C, 비SD 5종(adm/biggan/glide/midjourney/vqdm)", None, 0.495, ""),
    ("tre-deepfake-detection", "accuracy", "leave-one-generator-out 평균", None, 0.517, ""),
    # --- depth16-rgb-mapping ---
    ("depth16-rgb-mapping", "MSE", "방법1 바이트 분할, 무손상 채널", None, 21700.0, ""),
    ("depth16-rgb-mapping", "MSE", "방법2 스펙트럼 휠, 무손상 채널", None, 638.0, ""),
    ("depth16-rgb-mapping", "MSE", "방법3 6/6/4 비트필드, 무손상 채널", None, 0.0, ""),
    ("depth16-rgb-mapping", "MSE", "제안 매핑, 무손상 채널 (기준 방법2)", 638.0, 509.0, ""),
    ("depth16-rgb-mapping", "MSE", "제안 매핑, 가우시안 std=10 (기준 방법2)", 5.60e8, 4.66e6, ""),
    ("depth16-rgb-mapping", "MSE", "제안 매핑, JPEG QP=90 (기준 방법2)", 5.37e8, 6.58e6, ""),
    # --- jpeg-dct-compression ---
    ("jpeg-dct-compression", "MSE", "블록 DCT JPEG, QP=1 (6.34 bpp)", None, 17.1, ""),
    ("jpeg-dct-compression", "MSE", "블록 DCT JPEG, QP=20 (3.15 bpp)", None, 255.5, ""),
    ("jpeg-dct-compression", "MSE", "서브밴드 균일 QP=139 (6.42 bpp)", None, 489.4, ""),
    ("jpeg-dct-compression", "MSE", "서브밴드 최적 QP SV=3.1 (5.90 bpp)", 489.4, 248.6, ""),
    ("jpeg-dct-compression", "MSE", "3단 sum/difference 변환 왕복(역변환 정확성)", None, 0.0, ""),
    # --- digital-modulation-ber ---
    ("digital-modulation-ber", "EbNo", "AWGN BER 1e-3 달성 필요 Eb/No, BPSK", None, 6.7, "dB"),
    ("digital-modulation-ber", "EbNo", "AWGN BER 1e-3 달성 필요 Eb/No, 16-QAM", None, 10.5, "dB"),
    ("digital-modulation-ber", "EbNo", "AWGN BER 1e-3 달성 필요 Eb/No, 64-QAM", None, 14.7, "dB"),
    ("digital-modulation-ber", "EbNo", "AWGN BER 1e-3 달성 필요 Eb/No, 256-QAM", None, 19.3, "dB"),
    ("digital-modulation-ber", "EbNo", "레일리 BER 1e-2 달성 필요 Eb/No, BPSK", None, 13.8, "dB"),
    ("digital-modulation-ber", "coding_gain", "QPSK AWGN, 연판정 비터비 부호화 이득", None, 3.9, "dB"),
    ("digital-modulation-ber", "coding_gain", "16-QAM AWGN, 연판정 비터비 부호화 이득", None, 4.0, "dB"),
    ("digital-modulation-ber", "pilot_penalty", "AWGN BER 1e-3, QPSK 파일럿 추정 손해", None, 0.31, "dB"),
    ("digital-modulation-ber", "pilot_penalty", "레일리 BER 1e-2, QPSK 파일럿 추정 손해", None, 0.53, "dB"),
    # --- vanilla-rnn-fpga-quantization ---
    ("vanilla-rnn-fpga-quantization", "accuracy", "합성 코퍼스 float test", None, 1.0, ""),
    ("vanilla-rnn-fpga-quantization", "accuracy", "실제 단어 리스트 float test (릴리스 가중치)", None, 0.6750, ""),
    ("vanilla-rnn-fpga-quantization", "accuracy", "실제 단어, Q1.15 정수 데이터패스", 0.6750, 0.6272, ""),
    ("vanilla-rnn-fpga-quantization", "accuracy", "실제 단어, Q4.12 정수 데이터패스", 0.6750, 0.6750, ""),
    ("vanilla-rnn-fpga-quantization", "match_rate", "float 대 Q1.15 예측 일치율", None, 0.7792, ""),
    ("vanilla-rnn-fpga-quantization", "match_rate", "float 대 Q4.12 예측 일치율", None, 1.0000, ""),
    ("vanilla-rnn-fpga-quantization", "match_rate", "tanh LUT 66엔트리(sat=4, step=256)", None, 0.9999, ""),
    ("vanilla-rnn-fpga-quantization", "clip_rate", "Q1.15에서 Wx가 [-1,1) 밖으로 나가는 비율", None, 0.3879, ""),
    ("vanilla-rnn-fpga-quantization", "saturation_rate", "Q1.15에서 tanh 입력 z의 포화율", None, 0.5539, ""),
    # --- yopar-attribute-recognition ---
    ("yopar-attribute-recognition", "accuracy", "v4 PETA+Market 4헤드, 4속성 평균 (채택)", None, 0.885, ""),
    ("yopar-attribute-recognition", "accuracy", "v5 v4+강한 증강, 4속성 평균", None, 0.835, ""),
    ("yopar-attribute-recognition", "accuracy", "v3 PETA+Market, 3속성 평균", None, 0.80, ""),
    ("yopar-attribute-recognition", "accuracy", "v2 PETA resnet50, 3속성 평균", None, 0.76, ""),
    ("yopar-attribute-recognition", "accuracy", "v1 Market resnet18, 3속성 평균", None, 0.67, ""),
]


def main() -> None:
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO repos VALUES (?,?,?,?,?,?)", REPOS)
    con.executemany("INSERT INTO metrics VALUES (?,?,?,?,?,?)", METRICS)
    con.commit()
    n_repo = con.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
    n_met = con.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    orphan = con.execute(
        "SELECT COUNT(*) FROM metrics WHERE repo NOT IN (SELECT name FROM repos)"
    ).fetchone()[0]
    con.close()
    print(f"{DB}: repos={n_repo} metrics={n_met} orphan_metrics={orphan}")


if __name__ == "__main__":
    main()
