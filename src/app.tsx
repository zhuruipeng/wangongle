import type { PropsWithChildren } from 'react'
import { AuthProvider } from './context/AuthContext'
import { DeliveryProvider } from './context/DeliveryContext'
import './styles/global.scss'

export default function App({ children }: PropsWithChildren) {
  return <AuthProvider><DeliveryProvider>{children}</DeliveryProvider></AuthProvider>
}
