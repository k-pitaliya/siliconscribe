import { useEffect, useRef, useState } from 'react'
import PromptPanel from './components/PromptPanel'
import CodeEditor from './components/CodeEditor'
import ResultsPanel from './components/ResultsPanel'
import AgentChat, { type ChatMessage } from './components/AgentChat'
import { getStatus, getModels, streamDesign, reSimulate } from './api'
import type {
  IterationRecord,
  LintInfo,
  ModelInfo,
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
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    getStatus()
      .then((s) => setProvider(s))
      .catch(() => setProvider(null))
    getModels()
      .then((m) => {
        setModels(m.models)
        setSelectedModel(m.current ?? m.models[0]?.id ?? '')
        if (m.offline) setProvider((prev) => prev ?? { provider: 'offline', offline: true })
      })
      .catch(() => setModels([]))
  }, [])

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
