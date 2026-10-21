import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { Theme } from '@radix-ui/themes'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from './auth/AuthProvider'
import { SessionQueries } from './auth/SessionQueries'
import { useEffect, useState } from 'react'
import '@fontsource-variable/manrope'
import '@radix-ui/themes/styles.css'
import './styles.css'

function Root() {
  const [dark, setDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches)
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const update = () => setDark(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return (
    <Theme
      appearance={dark ? 'dark' : 'light'}
      accentColor="jade"
      grayColor="sage"
      radius="medium"
      panelBackground="solid"
    >
      <BrowserRouter>
        <AuthProvider>
          <SessionQueries>
            <App />
          </SessionQueries>
        </AuthProvider>
      </BrowserRouter>
    </Theme>
  )
}
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
