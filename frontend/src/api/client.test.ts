import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest } from './client'

afterEach(() => vi.unstubAllGlobals())

function mockResponse(response: Response) {
  const fetch = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('apiRequest', () => {
  it('sends cookies even if the caller specifies other credentials', async () => {
    const fetch = mockResponse(Response.json({ user_id: 'user' }))
    await expect(apiRequest('/api/auth/me', { credentials: 'omit' }))
      .resolves.toEqual({ user_id: 'user' })
    const [url, options] = fetch.mock.calls[0]
    expect(String(url)).toBe('http://localhost:8000/api/auth/me')
    expect(options.credentials).toBe('include')
    expect(options.cache).toBe('no-store')
    expect(options.headers.get('Accept')).toBe('application/json')
  })

  it('keeps JSON headers, body and abort signal', async () => {
    const fetch = mockResponse(Response.json({ ok: true }))
    const controller = new AbortController()
    const body = JSON.stringify({ user_mail: 'test@example.com' })
    await apiRequest('/api/auth_login', {
      method: 'POST', body, signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
    })
    const options = fetch.mock.calls[0][1]
    expect(options.method).toBe('POST')
    expect(options.body).toBe(body)
    expect(options.signal).toBe(controller.signal)
    expect(options.headers.get('Content-Type')).toBe('application/json')
  })

  it('leaves multipart Content-Type to the browser', async () => {
    const fetch = mockResponse(Response.json({ receipt_id: 'receipt' }))
    const body = new FormData()
    body.append('file', new Blob(['image'], { type: 'image/jpeg' }), 'receipt.jpg')
    await apiRequest('/api/receipts', { method: 'POST', body })
    expect(fetch.mock.calls[0][1].body).toBe(body)
    expect(fetch.mock.calls[0][1].headers.has('Content-Type')).toBe(false)
  })

  it('handles an empty logout response', async () => {
    mockResponse(new Response(null, { status: 204 }))
    await expect(apiRequest<void>('/api/logout', { method: 'POST' })).resolves.toBeUndefined()
  })

  it('preserves a safe provider error and correlation ID', async () => {
    mockResponse(Response.json({ detail: 'Модель недоступна', code: 'llm_unavailable' }, {
      status: 503, headers: { 'X-Correlation-ID': 'test-id' },
    }))
    await expect(apiRequest('/api/llm/reports')).rejects.toMatchObject({
      name: 'ApiError', status: 503, code: 'llm_unavailable',
      message: 'Модель недоступна', correlationId: 'test-id',
    })
  })

  it.each([
    new Response('PRIVATE proxy error', { status: 502 }),
    Response.json({ detail: [{ msg: 'invalid' }] }, { status: 422 }),
  ])('uses a readable fallback for nonstandard error bodies', async (response) => {
    mockResponse(response)
    await expect(apiRequest('/api/auth_login')).rejects.toMatchObject({
      name: 'ApiError',
      message: 'Не удалось выполнить запрос. Попробуйте ещё раз.',
    })
  })

  it.each(['https://example.org/api/auth/me', '//example.org/api/auth/me', '/api/../../secret'])
    ('rejects paths outside this API: %s', async (path) => {
      const fetch = vi.fn()
      vi.stubGlobal('fetch', fetch)
      await expect(apiRequest(path)).rejects.toThrow()
      expect(fetch).not.toHaveBeenCalled()
    })

  it('preserves cancellation', async () => {
    const error = new DOMException('Aborted', 'AbortError')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(error))
    await expect(apiRequest('/api/auth/me')).rejects.toBe(error)
  })
})
