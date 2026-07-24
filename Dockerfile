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
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY api/ ./api/
COPY --from=web /web/dist ./web/dist
RUN mkdir -p /app/data && chown -R user /app
USER user
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000
# MOLIT_API_KEY는 배포 플랫폼의 시크릿/환경변수로 주입(이미지에 넣지 않음).
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
