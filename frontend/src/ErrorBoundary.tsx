import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props { children: ReactNode; label?: string }
interface State { error: Error | null }

/** A rendering error in one panel must not blank the whole app (self-review finding). */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Panel failed to render', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="notice caution" role="alert">
          <p>{this.props.label ?? 'This panel'} could not be shown: {this.state.error.message}</p>
          <button type="button" className="btn" onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      )
    }
    return this.props.children
  }
}
