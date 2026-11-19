// The real SSE client (every App test mocks ../api, so this file is the only one that runs streamDesign).
// Adapted from the self-review QA report (19 Nov 2026), plus the stream fixes made in that review.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { streamDesign } from '../api'

const enc = new TextEncoder()
function sse(chunks: string[], status = 200): Response {
  const body = new ReadableStream({ start(c) { chunks.forEach((s) => c.enqueue(enc.encode(s))); c.close() } })
  return new Response(body, { status })
}
afterEach(() => vi.unstubAllGlobals())

describe('streamDesign (SSE client)', () => {
  it('re-assembles a frame split across chunks and skips a malformed one', async () => {
    const f = '{"stage":"intent","message":"m"}'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sse(['data: {"stage":"start","message":"s"}\n\nda', 'ta: ' + f.slice(0, 10), f.slice(10) + '\n\n', 'data: {oops\n\n', 'data: {"stage":"done","message":"d"}\n\n'])))
    const seen: string[] = []
    await streamDesign({ prompt: 'x' }, (e) => seen.push(e.stage))
    expect(seen).toEqual(['start', 'intent', 'done'])
  })

  it('accepts CRLF framing from a proxy', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sse(['data: {"stage":"start","message":"s"}\r\n\r\ndata: {"stage":"done","message":"d"}\r\n\r\n'])))
    const seen: string[] = []
    await streamDesign({ prompt: 'x' }, (e) => seen.push(e.stage))
    expect(seen).toEqual(['start', 'done'])
  })

  it('accepts a CRLF pair split across two chunks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sse(['data: {"stage":"start","message":"s"}\r\n\r', '\ndata: {"stage":"done","message":"d"}\r\n\r\n'])))
    const seen: string[] = []
    await streamDesign({ prompt: 'x' }, (e) => seen.push(e.stage))
    expect(seen).toEqual(['start', 'done'])
  })

  it('reports a stream that ends without done/error, but not an aborted one', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sse(['data: {"stage":"start","message":"s"}\n\n'])))
    await expect(streamDesign({ prompt: 'x' }, () => {})).rejects.toThrow(/closed before the run finished/)
    const ctrl = new AbortController(); ctrl.abort()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sse(['data: {"stage":"start","message":"s"}\n\n'])))
    await expect(streamDesign({ prompt: 'x' }, () => {}, ctrl.signal)).resolves.toBeUndefined()
  })

  it('does not apply frames that were already buffered after Stop', async () => {
    const ctrl = new AbortController()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sse(['data: {"stage":"start","message":"s"}\n\ndata: {"stage":"done","message":"d"}\n\n'])))
    const seen: string[] = []
    await streamDesign({ prompt: 'x' }, (e) => { seen.push(e.stage); if (e.stage === 'start') ctrl.abort() }, ctrl.signal)
    expect(seen).toEqual(['start'])
  })

  it('turns 502/504 into a plain message and a JSON error into its detail (also a 422 list)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('gateway', { status: 504 })))
    await expect(streamDesign({ prompt: 'x' }, () => {})).rejects.toThrow(/did not answer in time \(504\)/)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"Rate limit exceeded."}', { status: 429 })))
    await expect(streamDesign({ prompt: 'x' }, () => {})).rejects.toThrow('Rate limit exceeded.')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":[{"type":"value_error","msg":"Value error, module_name is not a Verilog identifier"}]}', { status: 422 })))
    await expect(streamDesign({ prompt: 'x' }, () => {})).rejects.toThrow(/^Value error, module_name is not a Verilog identifier$/)
  })

  it('does not swallow an exception in the consumer, and closes the stream', async () => {
    let cancelled = false
    const body = new ReadableStream({
      start(c) { c.enqueue(enc.encode('data: {"stage":"done","message":"d"}\n\n')) },   // left open by the server
      cancel() { cancelled = true },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 200 })))
    await expect(streamDesign({ prompt: 'x' }, () => { throw new Error('boom') })).rejects.toThrow('boom')
    expect(cancelled).toBe(true)
  })
})
