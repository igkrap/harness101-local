export type AsyncFeedbackProps = { error?: string; succeeded?: boolean; successText?: string };
export function AsyncFeedback({ error, succeeded, successText }: AsyncFeedbackProps) {
  return <>
    {error && <div role="alert">{error}</div>}
    {succeeded && successText && <div role="status">{successText}</div>}
  </>;
}
