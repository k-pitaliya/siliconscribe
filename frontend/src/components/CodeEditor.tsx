import { useMemo, useState } from 'react'
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
  const extensions = useMemo(() => [StreamLanguage.define(verilog)], [])

  const value = tab === 'rtl' ? rtl : tb
  const onChange = tab === 'rtl' ? onRtlChange : onTbChange
  const placeholder =
    tab === 'rtl'
      ? '// Generated RTL will appear here. Edit freely, then hit Re-run.'
      : '// Generated testbench will appear here.'

  return (
    <div className="editor-pane glass-panel">
      <div className="tabs editor-tabs">
        <button className={`tab ${tab === 'rtl' ? 'active' : ''}`} onClick={() => setTab('rtl')}>
          <i className="fa-solid fa-code" /> {moduleName}.v
        </button>
        <button className={`tab ${tab === 'tb' ? 'active' : ''}`} onClick={() => setTab('tb')}>
          <i className="fa-solid fa-flask" /> tb_{moduleName}.sv
        </button>
      </div>
      <div className="tab-content">
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
