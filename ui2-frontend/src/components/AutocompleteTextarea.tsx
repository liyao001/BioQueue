import React, { useCallback, useMemo, useRef, useState } from 'react'
import { Box, Portal, Textarea } from '@chakra-ui/react'

export default function AutocompleteTextarea({ value, onChange, rows = 6, placeholder, tokens }: {
  value: string
  onChange: (v: string) => void
  rows?: number
  placeholder?: string
  tokens: string[]
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null)
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<string[]>([])
  const [active, setActive] = useState(0)
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null)

  const sortedTokens = useMemo(() => Array.from(new Set(tokens)).sort((a, b) => a.localeCompare(b)), [tokens])

  const updateSuggestions = useCallback(() => {
    const el = ref.current
    if (!el) { setOpen(false); return }
    const caret = el.selectionStart || 0
    const head = value.slice(0, caret)
    const m = head.match(/\{\{([A-Za-z0-9_]*)$/)
    if (m) {
      const q = (m[1] || '').toLowerCase()
      const list = sortedTokens.filter(t => t.toLowerCase().startsWith(q)).slice(0, 30)
      setItems(list)
      setActive(0)
      try {
        const rect = el.getBoundingClientRect()
        const style = window.getComputedStyle(el)
        const mirror = document.createElement('div')
        mirror.style.position = 'absolute'
        mirror.style.visibility = 'hidden'
        mirror.style.whiteSpace = 'pre-wrap'
        mirror.style.wordWrap = 'break-word'
        mirror.style.fontFamily = style.fontFamily
        mirror.style.fontSize = style.fontSize
        mirror.style.lineHeight = style.lineHeight
        mirror.style.padding = style.padding
        mirror.style.border = style.border as string
        mirror.style.boxSizing = style.boxSizing as string
        mirror.style.width = `${el.clientWidth}px`
        mirror.style.left = `${rect.left + window.scrollX}px`
        mirror.style.top = `${rect.top + window.scrollY}px`
        const before = document.createTextNode(head)
        const marker = document.createElement('span')
        marker.textContent = '\u200b'
        mirror.appendChild(before)
        mirror.appendChild(marker)
        document.body.appendChild(mirror)
        const markerRect = marker.getBoundingClientRect()
        const caretLeft = markerRect.left
        const caretTop = markerRect.top
        document.body.removeChild(mirror)
        const lineHeight = parseFloat(style.lineHeight || '16') || 16
        setAnchor({ left: caretLeft, top: caretTop + lineHeight })
      } catch {
        const r = el.getBoundingClientRect()
        setAnchor({ left: r.left, top: r.bottom })
      }
      setOpen(list.length > 0)
    } else {
      setOpen(false)
    }
  }, [value, sortedTokens])

  const insertToken = useCallback((token: string) => {
    const el = ref.current
    if (!el) return
    const caret = el.selectionStart || 0
    const head = value.slice(0, caret)
    const tail = value.slice(caret)
    const m = head.match(/\{\{([A-Za-z0-9_]*)$/)
    if (!m) return
    const start = caret - (m[1] ? m[1].length : 0) - 2
    const next = head.slice(0, start) + `{{${token}}}` + tail
    onChange(next)
    setOpen(false)
    setTimeout(() => {
      if (ref.current) {
        const pos = start + token.length + 4
        ref.current.selectionStart = pos
        ref.current.selectionEnd = pos
        ref.current.focus()
      }
    }, 0)
  }, [onChange, value])

  return (
    <Box position="relative">
      <Textarea
        ref={ref}
        value={value}
        onChange={(e)=>{ onChange(e.target.value); updateSuggestions() }}
        onKeyUp={updateSuggestions}
        onClick={updateSuggestions}
        onFocus={updateSuggestions}
        onBlur={()=>{ setTimeout(()=>setOpen(false), 100) }}
        onKeyDown={(e)=>{
          if (!open || items.length===0) return
          if (e.key === 'ArrowDown') { e.preventDefault(); setActive(prev => Math.min(items.length-1, prev+1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(prev => Math.max(0, prev-1)) }
          else if (e.key === 'Enter') { e.preventDefault(); insertToken(items[active] || items[0]) }
          else if (e.key === 'Escape') { setOpen(false) }
        }}
        rows={rows}
        placeholder={placeholder}
        fontFamily="mono"
      />
      {open && (
        <Portal>
          <Box position="fixed" zIndex={1400} bg="white" borderWidth="1px" borderColor="gray.200" rounded="md" maxH="220px" overflowY="auto" boxShadow="md" minW="220px" style={{ left: `${anchor?.left ?? 0}px`, top: `${anchor?.top ?? 0}px` }}>
            {items.map((it, idx) => (
              <Box
                key={it}
                px={2}
                py={1}
                fontSize="sm"
                bg={idx===active? 'gray.100' : 'white'}
                _hover={{ bg: 'gray.100', cursor: 'pointer' }}
                onMouseEnter={()=>setActive(idx)}
                onMouseDown={(e)=>{ e.preventDefault(); insertToken(it) }}
              >
                {`{{${it}}}`}
              </Box>
            ))}
            {items.length === 0 && (
              <Box px={2} py={1} fontSize="sm" opacity={0.7}>no matches</Box>
            )}
          </Box>
        </Portal>
      )}
    </Box>
  )
}



