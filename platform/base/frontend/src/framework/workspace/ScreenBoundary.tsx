import { Component, type ReactNode } from 'react';
import { Button } from '../ui';

export class ScreenBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <div role="alert">화면을 표시하지 못했습니다.<Button label="화면 다시 열기" onClick={() => this.setState({ failed: false })} /></div>;
    return this.props.children;
  }
}
