import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, apiJson, apiRequest, resetApiSession } from '../api/client'
import type { User } from '../api/types'
import { ErrorNotice, Loading } from '../components/Feedback'

type Auth = {
  user: User | null
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}
const AuthContext = createContext<Auth | null>(null)
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setChecking(true)
    setError(null)
    apiRequest<User>('/api/auth/me', { signal: controller.signal })
      .then((next) => {
        if (!controller.signal.aborted) {
          resetApiSession()
          setUser(next)
        }
      })
      .catch((e) => {
        if (controller.signal.aborted) return
        if (e instanceof ApiError && e.status === 401) setUser(null)
        else setError(e)
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecking(false)
      })
    return () => controller.abort()
  }, [attempt])
  useEffect(() => {
    const expired = () => {
      setUser(null)
      resetApiSession()
    }
    window.addEventListener('session-expired', expired)
    return () => window.removeEventListener('session-expired', expired)
  }, [])
  if (checking)
    return (
      <div className="session-state">
        <Loading label="Проверяем сессию" />
      </div>
    )
  if (error)
    return (
      <div className="session-state">
        <h1>Не удалось проверить сессию</h1>
        <ErrorNotice error={error} retry={() => setAttempt((v) => v + 1)} />
      </div>
    )
  const login = async (email: string, password: string) => {
    const next = await apiJson<User>('/api/auth_login', 'POST', {
      user_mail: email,
      user_password: password,
    })
    resetApiSession()
    setUser(next)
  }
  const logout = async () => {
    await apiJson<void>('/api/logout', 'POST')
    setUser(null)
    resetApiSession()
  }
  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}
export function useAuth() {
  const auth = useContext(AuthContext)
  if (!auth) throw new Error('AuthProvider is required')
  return auth
}
