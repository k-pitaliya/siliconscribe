import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import ErrorBoundary from '../ErrorBoundary'

function Boom({ fail }: { fail: boolean }): JSX.Element {
  if (fail) throw new Error('bad value X0')
  return <p>fine</p>
}

describe('ErrorBoundary (self-review: a render error blanked the whole app)', () => {
  it('shows the error in place of the panel, and recovers on retry', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    let fail = true
    const Wrapper = () => <Boom fail={fail} />
    render(<div><span>header stays</span><ErrorBoundary label="The results panel"><Wrapper /></ErrorBoundary></div>)
    expect(screen.getByRole('alert')).toHaveTextContent('The results panel could not be shown: bad value X0')
    expect(screen.getByText('header stays')).toBeInTheDocument()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByText('fine')).toBeInTheDocument()
  })
})
