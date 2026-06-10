import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './index.css'

// 整個 app 的進入點：把 <App /> 這棵元件樹，掛到 index.html 裡那個 #root。
createRoot(document.getElementById('root')).render(<App />)
