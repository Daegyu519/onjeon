import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 개발 시 /api 요청을 FastAPI(uvicorn :8000)로 프록시 — CORS 불필요.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180, // 5173은 obsidian-galaxy 등이 선점 → 충돌 회피 전용 포트
    strictPort: true, // 점유 시 조용히 밀리지 말고 실패(예측 가능)
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
