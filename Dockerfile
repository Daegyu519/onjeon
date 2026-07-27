# 온전(穩全) — FastAPI + Vite 단일 서버 이미지.
# 프론트(web/dist)를 빌드해 FastAPI가 API와 함께 한 프로세스로 서빙한다.
# 런타임엔 RAG/임베더(fastembed·qdrant)를 로드하지 않아 메모리가 가볍다(과거 Streamlit OOM 회피).

# 1) 프론트 빌드
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# 2) 백엔드 + 정적 서빙
FROM python:3.12-slim
RUN useradd -m -u 1000 user
# 스캔 등기부 OCR 폴백에 필요한 tesseract 바이너리+한국어 데이터.
# pytesseract(파이썬 래퍼)만으론 동작하지 않아 이미지에 바이너리가 있어야 한다.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-kor \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# 런타임 최소 의존성만 설치(pyproject의 [dev,llm]은 Streamlit·RAG·L2까지 포함해 11배 무겁다).
# 컨테이너는 app.py를 복사하지 않고 FastAPI만 띄우므로 그쪽 의존성은 쓰이지 않는다.
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
COPY src/ ./src/
COPY api/ ./api/
COPY --from=web /web/dist ./web/dist

# 시세 캐시 동봉 — 컨테이너 파일시스템은 휘발성이라 캐시가 없으면 읽기 전용 모드에서
# 화면에 데이터가 하나도 안 나온다. gzip으로 넣고 빌드 시 푼다(gzip 바이너리에 의존하지
# 않게 stdlib로 해제). 갱신: scripts/warm_cache.py 실행 후 ./deploy-hf.sh가 재생성.
COPY data/cache.db.gz ./data/cache.db.gz
RUN python -c "import gzip,shutil;shutil.copyfileobj(gzip.open('data/cache.db.gz','rb'),open('data/cache.db','wb'))" \
    && rm data/cache.db.gz

RUN mkdir -p /app/data && chown -R user /app
USER user
# ONJEON_PUBLIC_READONLY=1: 공개 배포 기본값. 시세 조회가 캐시만 읽고 외부 국토부 API를
# 호출하지 않는다 — 인증 없는 공개 경로가 외부 호출을 타면 1요청 최대 183회로 운영자의
# 실명 인증 서비스키 쿼터가 소진된다. 캐시 갱신은 scripts/warm_cache.py(로컬)가 담당.
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PORT=8000 ONJEON_PUBLIC_READONLY=1
EXPOSE 8000
# MOLIT_API_KEY는 배포 플랫폼의 시크릿/환경변수로 주입(이미지에 넣지 않음).
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
