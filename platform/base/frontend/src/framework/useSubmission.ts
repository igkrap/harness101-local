import { useRef, useState } from 'react';

export function useSubmission() {
  const busy = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [succeeded, setSucceeded] = useState(false);
  async function run(action: () => void | Promise<void>) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError('');
    setSucceeded(false);
    try {
      await action();
      setSucceeded(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '처리하지 못했습니다. 다시 시도하세요.');
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  function reset() {
    if (!busy.current) { setError(''); setSucceeded(false); }
  }
  return { pending, error, succeeded, run, reset };
}
