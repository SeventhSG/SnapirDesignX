/**
 * A crash in the renderer used to unmount everything and leave a white window
 * with nothing to act on. This catches it and says what happened, so the app
 * fails loudly instead of silently.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props { children: ReactNode }
interface State { error: Error | null; stack: string }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, stack: "" };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ stack: info.componentStack ?? "" });
    console.error("Snapir renderer crashed:", error, info);
  }

  render() {
    const { error, stack } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="crash">
        <h2>Something in the interface stopped working</h2>
        <p>The geometry and your survey files are untouched. Reload to carry on.</p>
        <pre>{String(error.message || error)}{stack ? `\n${stack.trim()}` : ""}</pre>
        <div className="crashacts">
          <button className="btn" onClick={() => location.reload()}>Reload</button>
          <button className="btn q"
                  onClick={() => this.setState({ error: null, stack: "" })}>
            Try to continue
          </button>
        </div>
      </div>
    );
  }
}
