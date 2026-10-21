import { useState } from 'react'
import type { FormEvent } from 'react'
import { Button } from '@radix-ui/themes'
import { ReceiptIcon, ArrowRightIcon, EyeIcon, EyeSlashIcon } from '@phosphor-icons/react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { ApiError, apiJson } from '../api/client'
import { ErrorNotice } from '../components/Feedback'

export function LoginPage() {
  const { user, login } = useAuth()
  const location = useLocation()
  const [register, setRegister] = useState(false)
  const [busy, setBusy] = useState(false)
  const [visible, setVisible] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const destination =
    typeof location.state?.from === 'string' &&
    location.state.from.startsWith('/') &&
    !location.state.from.startsWith('//')
      ? location.state.from
      : '/receipts'
  if (user) return <Navigate to={destination} replace />
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setBusy(true)
    setError(null)
    try {
      if (register)
        await apiJson('/api/register_user', 'POST', {
          user_name: data.get('name'),
          user_surname: data.get('surname'),
          user_mail: data.get('email'),
          user_password: data.get('password'),
        })
      await login(String(data.get('email')), String(data.get('password')))
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? 'Неверная почта или пароль.' : e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="login-layout">
      <aside className="login-story">
        <a className="brand" href="/">
          <ReceiptIcon size={32} weight="duotone" />
          Покупки
        </a>
        <div className="login-message">
          <h1>
            Каждая покупка
            <br />
            на своём месте.
          </h1>
          <p>Сохраните чек, проверьте товары и узнайте, куда уходят деньги.</p>
          <div className="login-process">
            <span>Фото чека</span>
            <ArrowRightIcon />
            <span>Проверка</span>
            <ArrowRightIcon />
            <span>Аналитика</span>
          </div>
        </div>
        <p className="login-note">В аналитику попадают только подтверждённые вами чеки.</p>
      </aside>
      <main className="login-main">
        <div className="login-form-wrap">
          <h2>{register ? 'Создать аккаунт' : 'С возвращением'}</h2>
          <p className="muted">
            {register ? 'Начните с первого чека.' : 'Войдите, чтобы продолжить работу с чеками.'}
          </p>
          <form onSubmit={submit} className="stack" aria-label={register ? 'Регистрация' : 'Вход'}>
            <fieldset disabled={busy} className="stack">
              {register && (
                <div className="form-grid">
                  <label>
                    Имя
                    <input name="name" autoComplete="given-name" required maxLength={100} />
                  </label>
                  <label>
                    Фамилия
                    <input name="surname" autoComplete="family-name" required maxLength={100} />
                  </label>
                </div>
              )}
              <label>
                Электронная почта
                <input
                  type="email"
                  name="email"
                  autoComplete="email"
                  placeholder="you@example.ru"
                  required
                />
              </label>
              <label>
                Пароль
                <div className="password-field">
                  <input
                    type={visible ? 'text' : 'password'}
                    name="password"
                    autoComplete={register ? 'new-password' : 'current-password'}
                    minLength={register ? 12 : 1}
                    maxLength={128}
                    required
                  />
                  <button
                    className="icon-button"
                    type="button"
                    aria-label={visible ? 'Скрыть пароль' : 'Показать пароль'}
                    onClick={() => setVisible((v) => !v)}
                  >
                    {visible ? <EyeSlashIcon size={20} /> : <EyeIcon size={20} />}
                  </button>
                </div>
                {register && <small>От 12 до 128 символов.</small>}
              </label>
              {error != null && <ErrorNotice error={error} />}
              <Button size="3" type="submit" loading={busy}>
                {register ? 'Создать аккаунт' : 'Войти'}
                <ArrowRightIcon size={18} />
              </Button>
            </fieldset>
          </form>
          <p className="login-switch">
            {register ? 'Уже есть аккаунт?' : 'Первый раз здесь?'}{' '}
            <button
              type="button"
              disabled={busy}
              className="text-button"
              onClick={() => {
                setRegister((v) => !v)
                setError(null)
              }}
            >
              {register ? 'Войти' : 'Создать аккаунт'}
            </button>
          </p>
        </div>
      </main>
    </div>
  )
}
