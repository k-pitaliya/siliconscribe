import { useEffect, useRef, useState } from 'react'
import PromptPanel from './components/PromptPanel'
import CodeEditor from './components/CodeEditor'
import ResultsPanel from './components/ResultsPanel'
import AgentChat, { type ChatMessage } from './components/AgentChat'
import { getStatus, getModels, streamDesign, reSimulate, exportUVM, listProjects, deleteProject, getProject } from './api'
import type {
  IterationRecord,
  LintInfo,
  ModelInfo,
  ProjectSummary,
  RunResponse,
  Schematic,
  SimulationResult,
  SynthesisInfo,
  Waveform,
} from './types'

export default function App() {
  const [provider, setProvider] = useState<{ provider: string; offline: boolean } | null>(null)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [running, setRunning] = useState(false)

  const [rtl, setRtl] = useState('')
  const [tb, setTb] = useState('')
  const [moduleName, setModuleName] = useState('design')
  const [explanation, setExplanation] = useState('')

  const [result, setResult] = useState<SimulationResult | null>(null)
  const [waveform, setWaveform] = useState<Waveform | null>(null)
  const [schematic, setSchematic] = useState<Schematic | null>(null)
  const [history, setHistory] = useState<IterationRecord[]>([])
  const [iterations, setIterations] = useState<number>(0)
  const [designId, setDesignId] = useState<string>('')
  const [synthesis, setSynthesis] = useState<SynthesisInfo | null>(null)
  const [lintInfo, setLintInfo] = useState<LintInfo | null>(null)

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'ai',
      text: 'Ready. Describe your hardware requirement and I will generate RTL, a testbench, run simulation, and auto-fix failures.',
    },
  ])
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [showProjects, setShowProjects] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    getStatus()
      .then((s) => setProvider(s))
      .catch(() => setProvider({ provider: 'offline', offline: true }))
    getModels()
      .then((m) => {
        setModels(m.models)
        setSelectedModel(m.current ?? m.models[0]?.id ?? '')
        if (m.offline) setProvider({ provider: 'offline', offline: true })
      })
      .catch(() => {
        // Backend unreachable (e.g., Vercel frontend without Render backend) → show offline demo fallback
        setModels([{ id: 'offline', label: 'Offline Demo', note: 'Backend unavailable — offline demo', tag: 'fast' }])
        setSelectedModel('offline')
        setProvider({ provider: 'offline', offline: true })
      })
    refreshProjects()
  }, [])

  async function refreshProjects() {
    try {
      const r = await listProjects(20, 0)
      setProjects(r.projects)
    } catch {
      /* ignore */
    }
  }

  const pushMsg = (m: ChatMessage) => setMessages((prev) => [...prev, m])

  async function handleGenerate(prompt: string, freq: number) {
    if (running) return
    setRunning(true)
    setResult(null)
    setWaveform(null)
    setSchematic(null)
    setHistory([])
    setIterations(0)
    setSynthesis(null)
    setLintInfo(null)
    pushMsg({ role: 'user', text: prompt })

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      await streamDesign(
        {
          prompt,
          target_frequency_mhz: freq,
          self_correct: true,
          max_iterations: 5,
          timeout_seconds: 30,
          model: selectedModel || undefined,
        },
        (e) => {
          if (e.message && ['intent', 'rtl', 'testbench', 'explanation', 'simulate', 'fixing', 'fix', 'lint', 'synthesis', 'done', 'error'].includes(e.stage)) {
            pushMsg({ role: 'ai', text: e.message, stage: e.stage, status: e.status })
          }
          if (e.rtl_spec) setModuleName(e.rtl_spec.module_name)
          if (e.rtl_code) setRtl(e.rtl_code)
          if (e.testbench_code) setTb(e.testbench_code)
          if (e.explanation) setExplanation(e.explanation)
          if (e.result) setResult(e.result)
          if (e.synthesis) setSynthesis(e.synthesis)
          if (e.lint) setLintInfo(e.lint as LintInfo)
          if (e.stage === 'done' && e.response) {
            const r: RunResponse = e.response
            setRtl(r.rtl_code)
            setTb(r.testbench_code)
            setResult(r.result)
            setWaveform(r.waveform)
            setSchematic(r.schematic)
            setHistory(r.iteration_history)
            setIterations(r.iterations ?? (r.iteration_history.length > 0 ? Math.max(...r.iteration_history.map(h => h.iteration)) : 0))
            setDesignId(r.design_id)
            setExplanation(r.explanation)
            setModuleName(r.rtl_spec.module_name)
            if (r.synthesis) setSynthesis(r.synthesis)
            refreshProjects()
          }
        },
        ctrl.signal,
      )
    } catch (err) {
      const e = err as Error
      if (e.name === 'AbortError') {
        pushMsg({ role: 'ai', text: 'Run cancelled.', stage: 'error' })
      } else {
        pushMsg({ role: 'ai', text: `Error: ${e.message}`, stage: 'error' })
      }
    } finally {
      setRunning(false)
      abortRef.current = null
    }
  }

  function handleCancel() {
    abortRef.current?.abort()
  }

  async function handleReRun() {
    if (!rtl || !tb || running) return
    setRunning(true)
    pushMsg({ role: 'user', text: 'Re-running edited code…' })
    try {
      const res = await reSimulate(designId || 'edit', rtl, tb)
      setResult(res)
      pushMsg({
        role: 'ai',
        stage: 'simulate',
        status: res.status,
        text:
          res.status === 'PASS'
            ? `Simulation passed: ${res.pass_count}/${res.test_count} tests.`
            : `Simulation ${res.status}: ${res.fail_count}/${res.test_count} failed.`,
      })
    } catch (err) {
      pushMsg({ role: 'ai', text: `Error: ${(err as Error).message}`, stage: 'error' })
    } finally {
      setRunning(false)
    }
  }

  async function handleUVMExport() {
    if (running || !moduleName) return
    const prompt = `Design a UVM testbench for ${moduleName}`
    pushMsg({ role: 'user', text: `Exporting UVM bundle for ${moduleName}…` })
    try {
      const resp = await exportUVM(prompt, moduleName, selectedModel || undefined)
      // trigger download from base64 zip
      if (resp.zip_base64) {
        const bytes = Uint8Array.from(atob(resp.zip_base64), c => c.charCodeAt(0))
        const blob = new Blob([bytes], { type: 'application/zip' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${resp.module_name}_uvm_bundle.zip`
        document.body.appendChild(a)
        a.click()
        a.remove()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
        pushMsg({ role: 'ai', text: `UVM bundle ready: ${resp.file_count} files (Questa style, not Icarus). Zip downloaded.`, stage: 'synthesis' })
      } else {
        pushMsg({ role: 'ai', text: `UVM bundle: ${resp.file_count} files for ${resp.module_name}. ${resp.note}`, stage: 'synthesis' })
      }
    } catch (err) {
      pushMsg({ role: 'ai', text: `UVM export failed: ${(err as Error).message}`, stage: 'error' })
    }
  }

  async function handleLoadProject(id: string) {
    try {
      const proj = await getProject(id)
      setRtl(proj.rtl_code)
      setTb(proj.testbench_code)
      setModuleName(proj.rtl_spec.module_name)
      setResult(proj.result)
      setWaveform(proj.waveform)
      setSchematic(proj.schematic)
      setHistory(proj.iteration_history)
      setDesignId(proj.design_id)
      setExplanation(proj.explanation)
      setSynthesis(proj.synthesis ?? null)
      pushMsg({ role: 'ai', text: `Loaded project ${id} (${proj.rtl_spec.module_name})`, stage: 'done', status: proj.status })
      setShowProjects(false)
    } catch (err) {
      pushMsg({ role: 'ai', text: `Load failed: ${(err as Error).message}`, stage: 'error' })
    }
  }

  async function handleDeleteProject(id: string) {
    try {
      await deleteProject(id)
      setProjects(prev => prev.filter(p => p.design_id !== id))
      pushMsg({ role: 'ai', text: `Deleted project ${id}` })
    } catch (err) {
      pushMsg({ role: 'ai', text: `Delete failed: ${(err as Error).message}`, stage: 'error' })
    }
  }

  return (
    <div className="app-container">
      <header className="navbar">
        <div className="logo">
          <i className="fa-solid fa-microchip" />
          <span>SiliconScribe</span>
        </div>
        <div className="nav-actions">
          {provider && (
            <span className={`provider-badge ${provider.offline ? 'offline' : 'live'}`}>
              <i className={`fa-solid ${provider.offline ? 'fa-plug-circle-xmark' : 'fa-bolt'}`} />
              {provider.offline ? 'Offline demo' : `Live · ${provider.provider}`}
            </span>
          )}
          <button className="btn btn-secondary" onClick={() => setShowProjects(v => !v)} aria-label="Toggle projects">
            <i className="fa-solid fa-folder-open" aria-hidden="true" /> Projects ({projects.length})
          </button>
          <button className="btn btn-secondary" onClick={handleUVMExport} disabled={!rtl || running} aria-label="Export UVM bundle">
            <i className="fa-solid fa-download" aria-hidden="true" /> UVM
          </button>
          {running ? (
            <button className="btn btn-danger" onClick={handleCancel} aria-label="Stop generation">
              <i className="fa-solid fa-stop" aria-hidden="true" /> Stop
            </button>
          ) : (
            <button className="btn btn-secondary" onClick={handleReRun} disabled={!rtl} aria-label="Re-run simulation with edited code">
              <i className="fa-solid fa-rotate-right" aria-hidden="true" /> Re-run
            </button>
          )}
        </div>
      </header>

      {showProjects && (
        <div className="projects-drawer glass-panel" style={{ marginBottom: '0.75rem', padding: '1rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <h3><i className="fa-solid fa-folder-open" /> Recent Projects</h3>
            <button className="btn btn-secondary" onClick={() => setShowProjects(false)}>Close</button>
          </div>
          {projects.length === 0 ? (
            <div className="empty-state">No projects yet. Generate a design to save.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', maxHeight: '300px', overflowY: 'auto' }}>
              {projects.map(p => (
                <div key={p.design_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.04)', padding: '0.5rem 0.7rem', borderRadius: '8px' }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{p.module_name} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>· {p.design_id}</span></div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{p.prompt.slice(0, 60)} — {p.status} · {p.iterations} iter</div>
                  </div>
                  <div style={{ display: 'flex', gap: '0.3rem' }}>
                    <button className="btn btn-secondary" onClick={() => handleLoadProject(p.design_id)} style={{ padding: '0.3rem 0.6rem' }}>Load</button>
                    <button className="btn btn-danger" onClick={() => handleDeleteProject(p.design_id)} style={{ padding: '0.3rem 0.6rem' }}>Delete</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <main className="workspace">
        <PromptPanel
          onGenerate={handleGenerate}
          running={running}
          models={models}
          selectedModel={selectedModel}
          onModelChange={setSelectedModel}
          offline={provider?.offline ?? false}
        />

        <section className="center-panel">
          <CodeEditor
            rtl={rtl}
            tb={tb}
            onRtlChange={setRtl}
            onTbChange={setTb}
            moduleName={moduleName}
          />
          <ResultsPanel
            result={result}
            waveform={waveform}
            schematic={schematic}
            history={history}
            iterations={iterations}
            synthesis={synthesis}
            lint={lintInfo}
          />
        </section>

        <AgentChat messages={messages} running={running} explanation={explanation} />
      </main>
    </div>
  )
}
