import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { Bold, Italic, List, ListOrdered, RemoveFormatting } from 'lucide-react'

// A dependency-free WYSIWYG built on a single `contentEditable` div. Pasting
// rich content into it keeps the source markup (headings, lists, bold), which
// is exactly what the reoptimizer wants — the value is exposed as an HTML
// string via `onChange`. The toolbar uses `document.execCommand` (deprecated but
// universally supported and needs no library) for a few inline formats.
//
// The editor is UNCONTROLLED for the caret's sake: React never rewrites its
// innerHTML while the user is typing (that would reset the cursor). It only
// syncs from `value` when the prop changes and the editor isn't focused — so a
// programmatic clear (value → '') still empties it.

interface Props {
  value: string
  onChange: (html: string) => void
  disabled?: boolean
  placeholder?: string
}

export function PasteEditor({ value, onChange, disabled, placeholder }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [empty, setEmpty] = useState(!value)
  const [focused, setFocused] = useState(false)

  // Sync external value → editor when it changes and we're not the source of
  // the change (avoids clobbering the caret mid-edit).
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (document.activeElement === el) return
    const next = value ?? ''
    if (el.innerHTML !== next) {
      el.innerHTML = next
      setEmpty(!el.textContent?.trim())
    }
  }, [value])

  const emit = () => {
    const el = ref.current
    if (!el) return
    const hasText = Boolean(el.textContent?.trim())
    setEmpty(!hasText)
    // Report empty as '' rather than leftover <br>/<div> chrome the browser
    // leaves behind, so downstream "is there content?" checks are honest.
    onChange(hasText ? el.innerHTML : '')
  }

  const exec = (command: string) => {
    if (disabled) return
    ref.current?.focus()
    try {
      document.execCommand(command, false)
    } catch {
      /* execCommand can throw in exotic states — ignore, the edit still stands */
    }
    emit()
  }

  return (
    <div>
      <div style={toolbarStyle}>
        <ToolBtn label="Bold" onClick={() => exec('bold')} disabled={disabled}><Bold size={14} /></ToolBtn>
        <ToolBtn label="Italic" onClick={() => exec('italic')} disabled={disabled}><Italic size={14} /></ToolBtn>
        <span style={dividerStyle} />
        <ToolBtn label="Bulleted list" onClick={() => exec('insertUnorderedList')} disabled={disabled}><List size={14} /></ToolBtn>
        <ToolBtn label="Numbered list" onClick={() => exec('insertOrderedList')} disabled={disabled}><ListOrdered size={14} /></ToolBtn>
        <span style={dividerStyle} />
        <ToolBtn label="Clear formatting" onClick={() => exec('removeFormat')} disabled={disabled}><RemoveFormatting size={14} /></ToolBtn>
      </div>
      <div style={{ position: 'relative' }}>
        <div
          ref={ref}
          role="textbox"
          aria-multiline="true"
          contentEditable={!disabled}
          suppressContentEditableWarning
          onInput={emit}
          onBlur={() => { setFocused(false); emit() }}
          onFocus={() => setFocused(true)}
          style={{
            ...editorStyle,
            background: disabled ? '#f8fafc' : '#fff',
            color: disabled ? '#94a3b8' : '#0f172a',
            cursor: disabled ? 'not-allowed' : 'text',
          }}
        />
        {empty && !focused && (
          <div style={placeholderStyle}>{placeholder ?? 'Paste the page content here…'}</div>
        )}
      </div>
    </div>
  )
}

function ToolBtn({ children, label, onClick, disabled }: { children: React.ReactNode; label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      // Keep focus in the editor so execCommand applies to the current selection.
      onMouseDown={e => e.preventDefault()}
      onClick={onClick}
      disabled={disabled}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        width: 30, height: 28, borderRadius: 6, border: '1px solid transparent',
        background: 'transparent', color: disabled ? '#cbd5e1' : '#475569',
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      {children}
    </button>
  )
}

const toolbarStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 2,
  border: '1px solid #e2e8f0', borderBottom: 'none',
  borderRadius: '8px 8px 0 0', padding: 4, background: '#f8fafc',
}
const dividerStyle: CSSProperties = { width: 1, height: 18, background: '#e2e8f0', margin: '0 4px' }
const editorStyle: CSSProperties = {
  minHeight: 180, maxHeight: 420, overflowY: 'auto',
  border: '1px solid #e2e8f0', borderRadius: '0 0 8px 8px',
  padding: '10px 12px', fontSize: 14, lineHeight: 1.6, outline: 'none',
}
const placeholderStyle: CSSProperties = {
  position: 'absolute', top: 10, left: 12, fontSize: 14, color: '#94a3b8', pointerEvents: 'none',
}
