import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { Landing } from './Landing.tsx'
import { pageFor } from './routes.ts'

const Root = pageFor(window.location.pathname) === 'app' ? App : Landing

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
