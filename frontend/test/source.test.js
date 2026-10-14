import test from 'node:test'
import assert from 'node:assert/strict'
import { sourceForPath, sourceApiPath } from '../src/source.js'

test('routes the two source pages independently and defaults the home page to Search', () => {
  assert.equal(sourceForPath('/trending'), 'trending')
  assert.equal(sourceForPath('/trending/'), 'trending')
  assert.equal(sourceForPath('/stars'), 'search')
  assert.equal(sourceForPath('/'), 'search')
})
test('scopes dates, repositories, run status and collection requests to each source', () => {
  for (const source of ['trending', 'search']) {
    for (const path of ['/dates', '/repositories?date=2026-10-12&q=a%26b&language=C%2B%2B', '/runs/latest', '/collect']) {
      const url = new URL(sourceApiPath(path, source), 'http://localhost')
      assert.equal(url.searchParams.get('source'), source)
      if (path.startsWith('/repositories')) {
        assert.equal(url.searchParams.get('q'), 'a&b')
        assert.equal(url.searchParams.get('language'), 'C++')
      }
    }
  }
})
test('uses the selected day for Trending detail snapshots', () => {
  assert.equal(sourceApiPath('/repositories/42', 'trending', '2026-10-12'), '/api/repositories/42?source=trending&date=2026-10-12')
  assert.equal(sourceApiPath('/repositories/42', 'trending', '2026-10-11'), '/api/repositories/42?source=trending&date=2026-10-11')
})
test('uses the selected day for Search detail snapshots', () => {
  assert.equal(sourceApiPath('/repositories/42', 'search', '2026-10-12'), '/api/repositories/42?source=search&date=2026-10-12')
})
