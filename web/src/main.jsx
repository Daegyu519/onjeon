import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// StrictMode 제거 — 개발 중 effect 이중 실행으로 시세 API가 두 번 호출되는 것 방지.
createRoot(document.getElementById('root')).render(<App />)
