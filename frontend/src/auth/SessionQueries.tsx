import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAuth } from './AuthProvider'
import { ApiError } from '../api/client'

function DataProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: (count, error) =>
              count < 1 && (!(error instanceof ApiError) || error.status >= 500),
          },
          mutations: { retry: false },
        },
      }),
  )
  useEffect(
    () => () => {
      void client.cancelQueries()
      client.clear()
    },
    [client],
  )
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

export function SessionQueries({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  return <DataProvider key={user?.user_id ?? 'anonymous'}>{children}</DataProvider>
}
