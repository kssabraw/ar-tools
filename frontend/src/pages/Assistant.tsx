import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { SerMastrChat } from '../components/SerMastrChat'
import type { ClientListItem } from '../lib/types'

// Dedicated SerMaStr page. The chat used to live on the Home dashboard as a card;
// here it gets the full content area so the message field can be much larger.
export function Assistant() {
  const { data: clients = [] } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
  })

  return (
    <div style={{ padding: 32, height: '100%', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', maxWidth: 1000, margin: '0 auto' }}>
      <SerMastrChat exampleClient={clients[0]?.name} fullPage />
    </div>
  )
}
