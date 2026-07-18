import type { PropsWithChildren } from 'react'
import { DeliveryProvider } from './context/DeliveryContext'
import './styles/global.scss'

export default function App({ children }: PropsWithChildren) {
  return <DeliveryProvider>{children}</DeliveryProvider>
}
