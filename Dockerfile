# 온전(穩全) — Hugging Face Spaces (Docker SDK)
# HF는 이제 Streamlit 네이티브 SDK를 안 받으므로 Docker로 Streamlit을 구동한다.
FROM python:3.12-slim

# 차트 한글 폰트 (matplotlib NanumGothic)
RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces는 uid 1000 비루트 유저로 실행 — 쓰기 가능한 HOME 필요
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    MPLCONFIGDIR=/home/user/.cache/matplotlib \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .

# HF Spaces Docker 기본 포트 7860. iframe 임베드 위해 CORS/XSRF 완화.
EXPOSE 7860
CMD ["streamlit", "run", "app.py", \
     "--server.port=7860", "--server.address=0.0.0.0", \
     "--server.headless=true", "--server.enableCORS=false", \
     "--server.enableXsrfProtection=false"]
