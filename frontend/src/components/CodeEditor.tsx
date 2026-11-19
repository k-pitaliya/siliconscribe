import { useMemo, useState, useCallback, type KeyboardEvent } from 'react'
import CodeMirror, { EditorView, Prec } from '@uiw/react-codemirror'
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { Check, Copy } from 'lucide-react'
import { verilog } from '@codemirror/legacy-modes/mode/verilog'

// The stock dark theme's comment grey (3.9:1) and variable red (4.4:1) sit just under WCAG AA's 4.5:1 on
// the editor background. Lighten only those two tones; every other token colour is unchanged.
const readableTokens = HighlightStyle.define([
  { tag: tags.comment, color: '#9aa4b5' },
  { tag: tags.variableName, color: '#ee858e' },
])

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
  const extensions = useMemo(
    () => [
      StreamLanguage.define(verilog),
      // The editable area is a text box with no label of its own: name it for screen readers.
      EditorView.contentAttributes.of({
        'aria-label': tab === 'rtl' ? 'RTL source code editor' : 'Testbench source code editor',
      }),
      // The default gutter grey is 3.9:1 on the editor background; WCAG AA needs 4.5:1.
      // Highest precedence: the editor's built-in dark theme would otherwise win over these colours.
      Prec.highest(EditorView.theme({
        // The editor is one of the two dark "instrument screens": same surface in both themes.
        '&': { backgroundColor: '#0d1014' },
        '.cm-gutters': { color: '#9aa4b5', backgroundColor: '#0d1014', borderRight: '1px solid #232a31' },
        '.cm-activeLine': { backgroundColor: '#151a20' },
        '.cm-activeLineGutter': { backgroundColor: '#151a20' },
        '.cm-gutterElement': { color: '#9aa4b5' },
        '.cm-gutterElement.cm-activeLineGutter': { color: '#c5cbd6' },
        '.cm-placeholder': { color: '#a3acba' },
      })),
      Prec.highest(syntaxHighlighting(readableTokens)),
    ],
    [tab],
  )

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
    <div className="editor-pane">
      <div className="tabs editor-tabs">
       {/* The tab list holds only tabs (an ARIA requirement); the Copy button sits beside it. */}
       <div className="tablist" role="tablist" aria-label="Code editor tabs" onKeyDown={onKeyDown}>
        <button
          role="tab"
          aria-selected={tab === 'rtl'}
          aria-controls="rtl-panel"
          id="tab-rtl"
          className={`tab ${tab === 'rtl' ? 'active' : ''}`}
          onClick={() => setTab('rtl')}
        >
          {safeModule}.v
        </button>
        <button
          role="tab"
          aria-selected={tab === 'tb'}
          aria-controls="tb-panel"
          id="tab-tb"
          className={`tab ${tab === 'tb' ? 'active' : ''}`}
          onClick={() => setTab('tb')}
        >
          tb_{safeModule}.sv
        </button>
       </div>
        <button
          className="copy-btn"
          onClick={handleCopy}
          aria-label={tab === 'rtl' ? `Copy ${safeModule}.v to clipboard` : `Copy tb_${safeModule}.sv to clipboard`}
          disabled={!value}
          title="Copy code"
        >
          {copied === tab ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
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
