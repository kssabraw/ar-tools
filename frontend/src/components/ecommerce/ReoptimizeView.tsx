import { ReoptimizePanel } from '../reoptimize/ReoptimizePanel'
import { ecommerceAdapter } from '../reoptimize/adapters'
import type { EcommercePageType } from './types'

interface Props {
  clientId: string
  clientName?: string
  pageType: EcommercePageType
  onOpenSaved: () => void
}

// Ecommerce reoptimization is now the shared ReoptimizePanel driven by the
// Ecommerce adapter. Prior behaviour is preserved through capability flags:
// Paste-URLs vs Discover-from-site, the optional Notes textarea, the optional
// keyword default, the Stop button (adapter.cancel → cancelJobs), and the
// publish-to-Doc checkbox. The product/collection page type stays owned by the
// parent page and is threaded down via the `pageType` prop.
export function ReoptimizeView({ clientId, clientName, pageType, onOpenSaved }: Props) {
  return (
    <ReoptimizePanel
      adapter={ecommerceAdapter(clientId, clientName, onOpenSaved)}
      pageType={pageType}
    />
  )
}
