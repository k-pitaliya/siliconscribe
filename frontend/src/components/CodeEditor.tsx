import { useMemo, useState, useCallback, type KeyboardEvent } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { StreamLanguage } from '@codemirror/language'
import { verilog } from '@codemirror/legacy-modes/mode/verilog'

interface Props {
  rtl: string
  tb: string
  onRtlChange: (v: string) => void
  onTbChange: (v: string) => void
  moduleName: string
}

export default function CodeEditor({ rtl, tb, onRtlChange, onTbChange, moduleName }: Props) {
  const [tab, setTab] = useState<'rtl' | 'tb'>('rtl')
  const [copied, setCopied] = useState<string | null>(null)
  const extensions = useMemo(() => [StreamLanguage.define(verilog)], [])

  // fallback when moduleName is empty before first generation
  const safeModule = (moduleName && moduleName.trim()) ? moduleName.trim() : 'design'

  const value = tab === 'rtl' ? rtl : tb
  const onChange = tab === 'rtl' ? onRtlChange : onTbChange
  const placeholder =
    tab === 'rtl'
      ? '// Generated RTL will appear here. Edit freely, then hit Re-run.'
      : '// Generated testbench will appear here.'

  const handleCopy = useCallback(async () => {
    const text = tab === 'rtl' ? rtl : tb
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopied(tab)
      setTimeout(() => setCopied(null), 1400)
    } catch {
      // fallback: create textarea
      const el = document.createElement('textarea')
      el.value = text
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
      setCopied(tab)
      setTimeout(() => setCopied(null), 1400)
    }
  }, [rtl, tb, tab])

  const onKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      setTab((prev) => (prev === 'rtl' ? 'tb' : 'rtl'))
    }
  }, [])

  return (
    <div className="editor-pane glass-panel">
      <div className="tabs editor-tabs" role="tablist" aria-label="Code editor tabs" onKeyDown={onKeyDown}>
        <button
          role="tab"
          aria-selected={tab === 'rtl'}
          aria-controls="rtl-panel"
          id="tab-rtl"
          className={`tab ${tab === 'rtl' ? 'active' : ''}`}
          onClick={() => setTab('rtl')}
        >
          <i className="fa-solid fa-code" aria-hidden="true" /> {safeModule}.v
        </button>
        <button
          role="tab"
          aria-selected={tab === 'tb'}
          aria-controls="tb-panel"
          id="tab-tb"
          className={`tab ${tab === 'tb' ? 'active' : ''}`}
          onClick={() => setTab('tb')}
        >
          <i className="fa-solid fa-flask" aria-hidden="true" /> tb_{safeModule}.sv
        </button>
        <button
          className="copy-btn"
          onClick={handleCopy}
          aria-label={tab === 'rtl' ? `Copy ${safeModule}.v to clipboard` : `Copy tb_${safeModule}.sv to clipboard`}
          disabled={!value}
          title="Copy code"
        >
          <i className={`fa-solid ${copied === tab ? 'fa-check' : 'fa-copy'}`} aria-hidden="true" />
          {copied === tab ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="tab-content" role="tabpanel" id={tab === 'rtl' ? 'rtl-panel' : 'tb-panel'} aria-labelledby={tab === 'rtl' ? 'tab-rtl' : 'tab-tb'}>
        <CodeMirror
          value={value}
          height="100%"
          theme="dark"
          extensions={extensions}
          onChange={onChange}
          placeholder={placeholder}
          basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true }}
          style={{ height: '100%', fontSize: '0.85rem' }}
        />
      </div>
    </div>
  )
}
