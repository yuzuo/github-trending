export function runCompleted(previous, current) {
  return Boolean(current && current.status !== 'running' && (
    previous?.id !== current.id || previous?.status !== current.status || previous?.finished_at !== current.finished_at
  ))
}
