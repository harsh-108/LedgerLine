import { Component, type ReactNode } from "react";

// Keeps one broken page from blanking the whole app, and shows what failed.
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidUpdate(prev: { resetKey?: string }) { if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="card">
        <h2>This page hit a problem</h2>
        <p className="secondary" style={{ lineHeight: 1.6 }}>The rest of the app still works. If you report this, include the message below.</p>
        <pre className="log">{this.state.error.message}</pre>
        <button className="btn" style={{ marginTop: 12 }} onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}
