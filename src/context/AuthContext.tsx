import Taro from '@tarojs/taro'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react'
import { apiRequest } from '../services/api'
import { clearSession, getAccessToken, loginWithWechat, type AuthUser } from '../services/session'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export type AuthContextValue = {
  status: AuthStatus
  user: AuthUser | null
  error: string
  retry: () => Promise<void>
  setUser: (user: AuthUser) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

function readableError(error: unknown): string {
  return error instanceof Error ? error.message : '微信登录失败，请重试'
}

export function AuthProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [error, setError] = useState('')

  const authenticate = useCallback(async () => {
    setStatus('loading')
    setError('')
    try {
      let authenticatedUser: AuthUser
      if (getAccessToken()) {
        try {
          authenticatedUser = await apiRequest<AuthUser>('/api/v1/auth/me')
        } catch {
          clearSession()
          authenticatedUser = (await loginWithWechat()).user
        }
      } else {
        authenticatedUser = (await loginWithWechat()).user
      }
      setUser(authenticatedUser)
      setStatus('authenticated')
      if (!authenticatedUser.profile_complete) {
        void Taro.reLaunch({ url: '/pages/profile/index' })
      }
    } catch (authError) {
      clearSession()
      setUser(null)
      setError(readableError(authError))
      setStatus('anonymous')
    }
  }, [])

  useEffect(() => {
    void authenticate()
  }, [authenticate])

  const value = useMemo<AuthContextValue>(() => ({
    status,
    user,
    error,
    retry: authenticate,
    setUser
  }), [authenticate, error, status, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
