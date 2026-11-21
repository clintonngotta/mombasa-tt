import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { startServiceWorker } from './lib/pwa'
import { queryClient } from './lib/queryClient'
import { restoreScreens, startOffline } from './lib/offline'

startServiceWorker()
// Screens saved on this device come back before the first render, so the app opens offline too.
void restoreScreens(queryClient).finally(() => {
  startOffline(queryClient)
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
