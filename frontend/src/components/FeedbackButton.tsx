import { useRef, useState } from 'react'
import { Check } from 'lucide-react'

/**
 * A button that briefly turns green with a check + confirmation label after
 * it's clicked, so the user gets clear feedback that an action (copy,
 * download, …) fired. `baseStyle` is the button's normal style; the "done"
 * state overlays a green treatment on top of it for ~1.5s.
 */
export function FeedbackButton({
  children,
  doneLabel,
  onAction,
  baseStyle,
  durationMs = 1500,
}: {
  children: React.ReactNode
  doneLabel: string
  onAction: () => void
  baseStyle: React.CSSProperties
  durationMs?: number
}) {
  const [done, setDone] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  return (
    <button
      onClick={() => {
        onAction()
        setDone(true)
        clearTimeout(timer.current)
        timer.current = setTimeout(() => setDone(false), durationMs)
      }}
      style={{ ...baseStyle, ...(done ? doneStyle : {}) }}
    >
      {done ? (
        <>
          <Check size={13} /> {doneLabel}
        </>
      ) : (
        children
      )}
    </button>
  )
}

const doneStyle: React.CSSProperties = {
  color: '#16a34a',
  borderColor: '#bbf7d0',
  background: '#f0fdf4',
}
