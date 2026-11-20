import { createRoot } from 'react-dom/client'
import { App } from './App'
import '@fontsource-variable/geist'
import '@fontsource-variable/geist-mono'
import '@fontsource-variable/noto-sans-sc'
import './style.css'

createRoot(document.getElementById('root')!).render(<App />)
