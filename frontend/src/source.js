export function sourceForPath(path) { return path.replace(/\/$/, '') === '/trending' ? 'trending' : 'search' }
export function sourceApiPath(path, source, date) {
  if (path.startsWith('/repositories/')) return '/api' + path + ('?' + new URLSearchParams({ source, date }))
  return '/api' + path + (path.includes('?') ? '&' : '?') + 'source=' + source
}
