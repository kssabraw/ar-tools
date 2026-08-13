import { ReoptimizePanel } from '../reoptimize/ReoptimizePanel'
import { localSeoAdapter } from '../reoptimize/adapters'

interface Props {
  clientId: string
  clientName?: string
  onOpenSaved: () => void
}

// Local SEO reoptimization is now the shared ReoptimizePanel driven by the Local
// SEO adapter. All prior behaviour is preserved through the adapter's capability
// flags: single/bulk URL with per-line `URL | service | area`, the shared service
// + area (LocationAutocomplete) defaults, the app / app+doc destination radio
// (GitHub + WordPress shown disabled), the 75/100 score-threshold copy, and the
// Saved-Pages linking via onOpenSaved.
export function ReoptimizeView({ clientId, clientName, onOpenSaved }: Props) {
  return <ReoptimizePanel adapter={localSeoAdapter(clientId, clientName, onOpenSaved)} />
}
