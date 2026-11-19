import { useEffect, useRef, useState } from 'react'
import { Download, FolderOpen, Monitor, Moon, RotateCw, Square, Sun, TriangleExclamationPoint, X } from 'lucide-react'
import PromptPanel from './components/PromptPanel'
import CodeEditor from './components/CodeEditor'
import ErrorBoundary from './ErrorBoundary'
import ResultsPanel, { type Tab } from './components/ResultsPanel'
import AgentChat, { type ChatMessage } from './components/AgentChat'
import { useTheme } from './theme'
import SpecReview from './components/SpecReview'
import { getModels, parseSpec, streamDesign, reSimulate, exportUVM, listProjects, deleteProject, getProject } from './api'
import type {
  IterationRecord,
  LintInfo,
  ModelInfo,
  ProjectSummary,
  ProviderInfo,
  RTLDesignSpec,
  RunResponse,
  Schematic,
  SecondOpinion,
  SimulationResult,
  StrengthReport,
  SynthesisInfo,
  TimingReport,
  Waveform,
} from './types'

/** localStorage that never throws (private windows, blocked storage). */
function readStored(key: string): string | null {
  try { return window.localStorage.getItem(key) } catch { return null }
}
function writeStored(key: string, value: string): void {
  try { window.localStorage.setItem(key, value) } catch { /* the choice just is not remembered */ }
}

export default function App() {
  const [provider, setProvider] = useState<{ provider: string; offline: boolean } | null>(null)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [selectedThinking, setSelectedThinking] = useState<string>('')
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [paidHidden, setPaidHidden] = useState(0)
  const [includePaid, setIncludePaid] = useState<boolean>(() => readStored('ss-include-paid') === 'true')
  const [refreshingModels, setRefreshingModels] = useState(false)
  const [usedModel, setUsedModel] = useState<string | null>(null)
  const [testbenchModel, setTestbenchModel] = useState<string>(() => readStored('ss-tb-model') ?? '')
  const [reviewSpec, setReviewSpec] = useState<boolean>(() => readStored('ss-review-spec') === 'true')
  const [pendingSpec, setPendingSpec] = useState<{ prompt: string; freq: number; spec: RTLDesignSpec } | null>(null)
  const [parsingSpec, setParsingSpec] = useState(false)
  const [usedTbModel, setUsedTbModel] = useState<string | null>(null)
  const [secondOpinion, setSecondOpinion] = useState<SecondOpinion | null>(null)
  const [usedSpec, setUsedSpec] = useState<RTLDesignSpec | null>(null)
  const selectedModelRef = useRef('')
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
  const [passDisputed, setPassDisputed] = useState('')
  const [serverUnreachable, setServerUnreachable] = useState(false)
  const exportingRef = useRef(false)
  const loadSeq = useRef(0) // only the LATEST project load may write state (self-review: a slow older load overwrote a newer one)
  const [synthesis, setSynthesis] = useState<SynthesisInfo | null>(null)
  const [strength, setStrength] = useState<StrengthReport | null>(null)
  const [timing, setTiming] = useState<TimingReport | null>(null)
  const [lintInfo, setLintInfo] = useState<LintInfo | null>(null)
  const [fallbackNotice, setFallbackNotice] = useState<string>('')
  const [verificationWarning, setVerificationWarning] = useState<string>('')

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [tabRequest, setTabRequest] = useState<{ tab: Tab; seq: number } | null>(null)
  const showTab = (tab: Tab) => setTabRequest((prev) => ({ tab, seq: (prev?.seq ?? 0) + 1 }))
  const currentTab = useRef<Tab>('design')
  const { choice: theme, cycle: cycleTheme } = useTheme()
  const projectsRef = useRef<HTMLDivElement>(null)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [showProjects, setShowProjects] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const lastNoticeRef = useRef<string>('')

  selectedModelRef.current = selectedModel

  // Reads the model menu (OpenCode's list and Cloudflare). The current choice is kept when it is still offered; on first
  // load the last remembered choice is restored if it is offered; otherwise the server's default model is used.
  function loadModels(refresh = false) {
    if (refresh) setRefreshingModels(true)
    // /api/models already carries provider + offline state; getStatus() would
    // fetch the same endpoint a second time and could overwrite a newer result.
    return getModels({ includePaid, refresh })
      .then((m) => {
        setServerUnreachable(false)
        setModels(m.models)
        setProviders(m.providers ?? [])
        setTestbenchModel((prev) => (prev && m.models.some((x) => x.id === prev) ? prev : ''))
        setPaidHidden(m.paid_hidden ?? 0)
        const offered = (id: string | null | undefined) => !!id && m.models.some((x) => x.id === id)
        const pick = [selectedModelRef.current, readStored('ss-model')].find(offered) ?? m.current ?? m.models[0]?.id ?? ''
        setSelectedModel(pick)
        // Default thinking level for a model that has variants (middle one), none otherwise
        const levels = m.models.find((x) => x.id === pick)?.thinking_levels ?? []
        setSelectedThinking(levels.length > 0 ? (levels[Math.floor(levels.length / 2)] || levels[0]) : '')
        // Always sync provider from models (live zen or offline) — fixes Vercel getStatus HTML vs /api/models Live mismatch
        if (m.offline) {
          setProvider({ provider: 'offline', offline: true })
        } else {
          setProvider({ provider: m.current || 'zen', offline: false })
        }
      })
      .catch(() => {
        // Backend unreachable (e.g., Vercel frontend without Render backend) → show offline demo fallback
        // The server could not be reached. Say so (it is not a mode), and offer a retry instead of a dead "offline" UI.
        setServerUnreachable(true)
        setModels([])
        setSelectedModel('')
        setProvider(null)
      })
      .finally(() => setRefreshingModels(false))
  }

  useEffect(() => { loadModels() }, [includePaid]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { refreshProjects() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  /** The user picked a model in the menu: use it, remember it, and set a sensible thinking level for it. */
  function chooseModel(id: string) {
    setSelectedModel(id)
    writeStored('ss-model', id)
    const m = models.find((x) => x.id === id)
    if (m?.thinking_levels && m.thinking_levels.length > 0) {
      setSelectedThinking(m.thinking_levels[Math.floor(m.thinking_levels.length / 2)] || m.thinking_levels[0])
    } else {
      setSelectedThinking('')
    }
  }

  useEffect(() => {
    if (!showProjects) return undefined
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setShowProjects(false) }
    const onDown = (e: MouseEvent) => {
      if (projectsRef.current && !projectsRef.current.contains(e.target as Node)) setShowProjects(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onDown)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('mousedown', onDown) }
  }, [showProjects])

  async function refreshProjects() {
    try {
      const r = await listProjects(20, 0)
      setProjects(r.projects)
    } catch {
      /* ignore */
    }
  }

  const pushMsg = (m: ChatMessage) => setMessages((prev) => [...prev, { ...m, at: Date.now() }])

  // When model changes, update thinking level to valid for that model
  const activeModelForThinking = models.find(m => m.id === selectedModel)
  const availableThinking = activeModelForThinking?.thinking_levels || []

  /** Generate. With "review the specification" on, parse first and let the user read and edit it before anything is built. */
  async function handleGenerate(prompt: string, freq: number) {
    if (running || parsingSpec) return
    if (reviewSpec && !(provider?.offline ?? false)) {
      setParsingSpec(true)
      setMessages([])
      pushMsg({ role: 'user', text: prompt })
      try {
        const thinking = availableThinking.includes(selectedThinking) ? selectedThinking : undefined
        const spec = await parseSpec(prompt, selectedModel || undefined, thinking)
        setPendingSpec({ prompt, freq, spec })
      } catch (err) {
        pushMsg({ role: 'ai', text: `Could not read the specification: ${(err as Error).message}`, stage: 'error' })
      } finally {
        setParsingSpec(false)
      }
      return
    }
    await startRun(prompt, freq)
  }

  async function startRun(prompt: string, freq: number, confirmedSpec?: RTLDesignSpec) {
    if (running) return
    loadSeq.current += 1 // a project load still in flight must not overwrite this run
    setPendingSpec(null)
    setRunning(true)
    setRtl('') // the previous run's code, explanation and id must not mix with this run (self-review finding)
    setTb('')
    setExplanation('')
    setDesignId('')
    setPassDisputed('')
    setResult(null)
    setWaveform(null)
    setSchematic(null)
    setHistory([])
    setIterations(0)
    setSynthesis(null)
    setStrength(null)
    setTiming(null)
    setUsedModel(null)
    setUsedTbModel(null)
    setSecondOpinion(null)
    setUsedSpec(null)
    setLintInfo(null)
    setFallbackNotice('')
    setVerificationWarning('')
    lastNoticeRef.current = ''
    setMessages([]) // the timeline shows this run only
    pushMsg({ role: 'user', text: prompt })
    showTab('design')

    const ctrl = new AbortController()
    abortRef.current = ctrl

    // Only send thinking level if model actually supports it (real, not fake)
    const thinkingToSend = availableThinking.includes(selectedThinking) ? selectedThinking : undefined

    try {
      await streamDesign(
        {
          prompt,
          target_frequency_mhz: freq,
          self_correct: true,
          max_iterations: 5,
          timeout_seconds: 30,
          model: selectedModel || undefined,
          testbench_model: testbenchModel || undefined,
          spec: confirmedSpec,
          reasoning_effort: thinkingToSend,
        },
        (e) => {
          if (e.message && ['start', 'intent', 'rtl', 'testbench', 'explanation', 'simulate', 'fixing', 'fix', 'lint', 'synthesis', 'strength', 'timing', 'second_opinion', 'done', 'error'].includes(e.stage)) {
            pushMsg({ role: 'ai', text: e.message, stage: e.stage, status: e.status, diagnosis: e.diagnosis })
          }
          if (e.fallback_notice && e.fallback_notice !== lastNoticeRef.current) {
            lastNoticeRef.current = e.fallback_notice
            setFallbackNotice(e.fallback_notice)
            pushMsg({ role: 'ai', text: e.fallback_notice, stage: 'intent' })
          }
          if (e.rtl_spec) { setModuleName(e.rtl_spec.module_name); setUsedSpec(e.rtl_spec) }
          if (e.second_opinion) setSecondOpinion(e.second_opinion)
          if (e.rtl_code) setRtl(e.rtl_code)
          if (e.testbench_code) setTb(e.testbench_code)
          if (e.explanation) setExplanation(e.explanation)
          if (e.result) setResult(e.result)
          if (e.synthesis) setSynthesis(e.synthesis)
          if (e.strength) setStrength(e.strength)
          if (e.timing) setTiming(e.timing)
          if (e.stage === 'fix' && (e.rtl_code || e.testbench_code)) setLintInfo(null) // the old lint described the old code
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
            setStrength(r.strength ?? null)
            setTiming(r.timing ?? null)
            setUsedModel(r.model ?? null)
            setUsedTbModel(r.independent_testbench ? (r.testbench_model ?? null) : null)
            setSecondOpinion(r.second_opinion ?? null)
            setUsedSpec(r.rtl_spec)
            if (r.fallback_notice) setFallbackNotice(r.fallback_notice)
            setVerificationWarning(r.verification_warning ?? '')
            setPassDisputed(r.pass_disputed ?? '')
            refreshProjects()
            showTab('results')
          }
        },
        ctrl.signal,
      )
    } catch (err) {
      const e = err as Error
      if (e.name === 'AbortError') {
        pushMsg({ role: 'ai', text: 'Run cancelled.', stage: 'error' })
      } else if (/\b50[24]\b/.test(e.message.slice(0, 40)) || e.message.includes('waking up')) {
        pushMsg({ role: 'ai', text: 'The server did not answer in time (a hosted server may be starting up). This run is lost; press Generate again in a moment.', stage: 'error' })
      } else if (e.message.includes('Failed to fetch') || e.message.includes('NetworkError')) {
        pushMsg({ role: 'ai', text: 'Cannot reach the SiliconScribe server, so this run is lost. Check that the server is running, then press Generate again.', stage: 'error' })
      } else {
        pushMsg({ role: 'ai', text: `Error: ${e.message}`, stage: 'error' })
      }
    } finally {
      setRunning(false)
      if (abortRef.current === ctrl) abortRef.current = null
    }
  }

  function handleCancel() {
    abortRef.current?.abort()
  }

  async function handleReRun() {
    if (!rtl || !tb || running) return
    setRunning(true)
    const ctrl = new AbortController() // so Stop works during a re-run too (self-review finding)
    abortRef.current = ctrl
    pushMsg({ role: 'user', text: 'Re-running edited code…' })
    try {
      const { waveform: freshWaveform, ...res } = await reSimulate(designId || 'edit', rtl, tb, ctrl.signal)
      // The verdict, the waveform and the test cases all come from THIS run. Leaving the old
      // waveform, repair timeline or warning on screen would show them next to a new PASS/FAIL.
      setResult(res)
      setWaveform(freshWaveform ?? null)
      setHistory([])
      setIterations(0)
      setStrength(null) // scored the previous code, not what was just re-run
      setTiming(null) // timed the previous code
      setUsedModel(null) // the edited code is not what the model wrote
      setUsedTbModel(null)
      setSecondOpinion(null) // it judged the previous code
      setSynthesis(null) // synthesised the previous code
      setLintInfo(null)
      setPassDisputed('')
      setVerificationWarning('Re-run of edited code: only the simulation was repeated. Strength, synthesis, timing and the second opinion were not recomputed for this code.')
      // From the editor, show the new verdict; anywhere else (waveform, test cases) stay where the user is looking.
      if (currentTab.current === 'design') showTab('results')
      pushMsg({
        role: 'ai',
        stage: 'simulate',
        status: res.status,
        text:
          res.status === 'PASS'
            ? `Simulation passed: ${res.pass_count} of ${res.test_count} checks.`
            : `Simulation ${res.status}: ${res.fail_count} of ${res.test_count} checks failed.`,
      })
    } catch (err) {
      const e = err as Error
      pushMsg({ role: 'ai', text: e.name === 'AbortError' ? 'Re-run cancelled.' : `Error: ${e.message}`, stage: 'error' })
    } finally {
      setRunning(false)
      if (abortRef.current === ctrl) abortRef.current = null
    }
  }

  async function handleUVMExport() {
    if (running || !moduleName || exportingRef.current) return // one export at a time (a double click made two model calls)
    exportingRef.current = true
    const prompt = `Design a UVM testbench for ${moduleName}`
    pushMsg({ role: 'user', text: `Exporting UVM bundle for ${moduleName}…` })
    try {
      const thinkingToSend = availableThinking.includes(selectedThinking) ? selectedThinking : undefined
      const resp = await exportUVM(prompt, moduleName, selectedModel || undefined, thinkingToSend)
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
    } finally {
      exportingRef.current = false
    }
  }

  async function handleLoadProject(id: string) {
    if (running) return // loading mid-run would be overwritten by the next streamed event
    const seq = ++loadSeq.current
    try {
      const proj = await getProject(id)
      if (seq !== loadSeq.current) return // a newer load (or a new run) started meanwhile
      setRtl(proj.rtl_code)
      setTb(proj.testbench_code)
      setModuleName(proj.rtl_spec.module_name)
      setResult(proj.result)
      setWaveform(proj.waveform)
      setSchematic(proj.schematic)
      setHistory(proj.iteration_history)
      setIterations(proj.iterations ?? (proj.iteration_history.length > 0 ? Math.max(...proj.iteration_history.map((h) => h.iteration)) : 0))
      setLintInfo(null) // lint is not saved with a project; the previous run's lint must not show next to it
      setPassDisputed(proj.pass_disputed ?? '')
      setDesignId(proj.design_id)
      setExplanation(proj.explanation)
      setSynthesis(proj.synthesis ?? null)
      setStrength(proj.strength ?? null)
      setTiming(proj.timing ?? null)
      setUsedModel(proj.model ?? null)
      setUsedTbModel(proj.independent_testbench ? (proj.testbench_model ?? null) : null)
      setSecondOpinion(proj.second_opinion ?? null)
      setUsedSpec(proj.rtl_spec)
      setFallbackNotice(proj.fallback_notice ?? '')
      setVerificationWarning(proj.verification_warning ?? '')
      pushMsg({ role: 'ai', text: `Loaded project ${proj.rtl_spec.module_name}`, stage: 'done', status: proj.status })
      setShowProjects(false)
      showTab('results')
    } catch (err) {
      if (seq !== loadSeq.current) return
      pushMsg({ role: 'ai', text: `Load failed: ${(err as Error).message}`, stage: 'error' })
    }
  }

  async function handleDeleteProject(id: string) {
    const name = projects.find((p) => p.design_id === id)?.module_name ?? 'this project'
    if (!window.confirm(`Delete ${name}? This cannot be undone.`)) return
    try {
      await deleteProject(id)
      setProjects(prev => prev.filter(p => p.design_id !== id))
      pushMsg({ role: 'ai', text: `Deleted project ${id}` })
    } catch (err) {
      pushMsg({ role: 'ai', text: `Delete failed: ${(err as Error).message}`, stage: 'error' })
    }
  }

  const statusKind = provider?.offline ? 'offline' : fallbackNotice ? 'fallback' : 'live'
  const ThemeIcon = theme === 'light' ? Sun : theme === 'dark' ? Moon : Monitor

  const design = !rtl && !running ? (
    <Welcome projects={projects} onLoad={handleLoadProject} />
  ) : (
    <CodeEditor rtl={rtl} tb={tb} onRtlChange={setRtl} onTbChange={setTb} moduleName={moduleName} />
  )

  return (
    <div className="app-container">
      <header className="topbar">
        <h1 className="brand">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#17191c" />
            <path d="M5 20h5l3-8 4 12 3-8h7" fill="none" stroke="#f2c230" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>SiliconScribe</span>
        </h1>
        {serverUnreachable && (
          <span className="status unreachable" data-testid="provider-badge" role="status">
            <span className="dot" aria-hidden="true" />
            Server not reachable
            <button type="button" className="btn btn-ghost" onClick={() => loadModels(true)}>Retry</button>
          </span>
        )}
        {provider && (
          <span className={`status ${statusKind}`} data-testid="provider-badge" role="status">
            <span className="dot" aria-hidden="true" />
            {/* The model the NEXT run will use (the user's choice), not just the server's default. */}
            {provider.offline ? 'Offline demo' : fallbackNotice ? 'Demo fallback · not AI-generated' : `Live · ${selectedModel || provider.provider}`}
          </span>
        )}
        <span className="spacer" />
        <div className="top-actions">
          <div className="menu-anchor" ref={projectsRef}>
            <button className="btn" onClick={() => setShowProjects((v) => !v)} aria-expanded={showProjects} aria-haspopup="dialog">
              <FolderOpen size={15} aria-hidden="true" /> <span className="label">Projects</span>
              <span className="tab-badge">{projects.length}</span>
            </button>
            {showProjects && (
              <div className="projects-menu" role="dialog" aria-label="Recent projects">
                <div className="menu-head">
                  <h2 className="drawer-title">Recent projects</h2>
                  <button className="btn btn-ghost btn-icon" onClick={() => setShowProjects(false)} aria-label="Close projects">
                    <X size={16} aria-hidden="true" />
                  </button>
                </div>
                {projects.length === 0 ? (
                  <div className="empty-state">No projects yet. Generated designs are saved here.</div>
                ) : (
                  <ul className="project-list">
                    {projects.map((p) => (
                      <li key={p.design_id} className="project-row">
                        <div className="project-main">
                          <div className="project-name">
                            {p.module_name} <span className={`pill ${p.status.toLowerCase()}`}>{p.status}</span>
                            {p.demo && <span className="pill demo" title="Built-in demo result, not generated by an AI model">demo</span>}
                          </div>
                          <div className="project-sub" title={p.prompt}>{p.prompt}</div>
                          <div className="project-meta muted">
                            {p.created_at ? new Date(p.created_at * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : ''}
                            {p.model && !p.demo ? ` · ${p.model}` : ''}
                          </div>
                        </div>
                        <button className="btn" onClick={() => handleLoadProject(p.design_id)}>Open</button>
                        <button className="btn btn-danger" onClick={() => handleDeleteProject(p.design_id)} aria-label={`Delete ${p.module_name}`}>Delete</button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
          <button className="btn" onClick={handleUVMExport} disabled={!rtl || running} aria-label="Export UVM bundle">
            <Download size={15} aria-hidden="true" /> <span className="label">Export UVM</span>
          </button>
          {running ? (
            <button className="btn btn-danger" onClick={handleCancel} aria-label="Stop generation">
              <Square size={13} aria-hidden="true" /> <span className="label">Stop</span>
            </button>
          ) : (
            <button className="btn" onClick={handleReRun} disabled={!rtl} aria-label="Re-run simulation with edited code">
              <RotateCw size={15} aria-hidden="true" /> <span className="label">Re-run</span>
            </button>
          )}
          <button className="btn btn-ghost btn-icon" onClick={cycleTheme} aria-label={`Theme: ${theme}. Change theme`} title={`Theme: ${theme}`}>
            <ThemeIcon size={16} aria-hidden="true" />
          </button>
        </div>
      </header>

      {fallbackNotice ? (
        <div className="degraded-banner" role="alert" data-testid="degraded-banner">
          <TriangleExclamationPoint size={16} aria-hidden="true" />
          <span><strong>Degraded mode:</strong> {fallbackNotice}</span>
        </div>
      ) : <div />}

      <div className="workspace">
        <aside className="sidebar" aria-label="Design input and run">
          <PromptPanel
            onGenerate={handleGenerate}
            running={running || parsingSpec}
            models={models}
            selectedModel={selectedModel}
            onModelChange={chooseModel}
            providers={providers}
            paidHidden={paidHidden}
            includePaid={includePaid}
            onIncludePaidChange={(v) => { setIncludePaid(v); writeStored('ss-include-paid', String(v)) }}
            onRefreshModels={() => { void loadModels(true) }}
            refreshingModels={refreshingModels}
            testbenchModel={testbenchModel}
            onTestbenchModelChange={(id) => { setTestbenchModel(id); writeStored('ss-tb-model', id) }}
            reviewSpec={reviewSpec}
            onReviewSpecChange={(v) => { setReviewSpec(v); writeStored('ss-review-spec', String(v)) }}
            selectedThinking={selectedThinking}
            onThinkingChange={setSelectedThinking}
            offline={provider?.offline ?? false}
          >
            {(messages.length > 0 || running) && <AgentChat messages={messages} running={running} explanation={explanation} />}
          </PromptPanel>
        </aside>

        {pendingSpec ? (
          <main className="main-pane results-pane spec-pane" aria-label="Workspace">
          <SpecReview
            key={`${pendingSpec.prompt}-${pendingSpec.spec.module_name}`}
            spec={pendingSpec.spec}
            busy={running}
            onCancel={() => setPendingSpec(null)}
            onConfirm={(confirmed) => { const p = pendingSpec; setPendingSpec(null); void startRun(p.prompt, p.freq, confirmed) }}
          />
          </main>
        ) : (
          <ErrorBoundary key={designId || 'none'} label="The results panel">
          <ResultsPanel
            design={design}
            tabRequest={tabRequest}
            onTabChange={(t) => { currentTab.current = t }}
            result={result}
            waveform={waveform}
            schematic={schematic}
            history={history}
            iterations={iterations}
            synthesis={synthesis}
            strength={strength}
            timing={timing}
            model={usedModel}
            testbenchModel={usedTbModel}
            secondOpinion={secondOpinion}
            spec={usedSpec}
            lint={lintInfo}
            degraded={!!fallbackNotice}
            warning={verificationWarning}
            disputed={passDisputed}
          />
          </ErrorBoundary>
        )}
      </div>
    </div>
  )
}

/** First visit: say what the tool does in three steps and offer recent work. */
function Welcome({ projects, onLoad }: { projects: ProjectSummary[]; onLoad: (id: string) => void }) {
  return (
    <div className="welcome">
      <div className="welcome-inner">
        <h2>Describe a block. Get Verilog and the evidence to judge it.</h2>
        <p>Write what the hardware should do in plain English. SiliconScribe writes the Verilog and a self-checking testbench, runs both in a real simulator, tries to repair failures, and shows how far the result can be trusted.</p>
        <ol className="flow">
          <li><span><b>Specification.</b> Your description becomes ports, widths and behaviour.</span></li>
          <li><span><b>RTL and testbench.</b> The testbench is written from the specification, never from the RTL.</span></li>
          <li><span><b>Simulate and report.</b> Every check is counted and every failing check is listed. The testbench itself is tested by injecting bugs.</span></li>
        </ol>
        <p className="muted welcome-time">A live run takes about 3 to 13 minutes: model calls for the specification, RTL and testbench, then simulation, synthesis and timing. Stop cancels it.</p>
        {projects.length > 0 && (
          <div className="type-chips" aria-label="Recent projects">
            <span className="muted" style={{ fontSize: 13, marginRight: 4 }}>Recent:</span>
            {projects.slice(0, 4).map((p) => (
              <button key={p.design_id} className="chip" onClick={() => onLoad(p.design_id)}>{p.module_name}</button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
