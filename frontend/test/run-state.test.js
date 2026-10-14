import test from 'node:test'
import assert from 'node:assert/strict'
import { runCompleted } from '../src/run-state.js'

test('refreshes for a fast scheduled run that finishes between polls', () => {
  assert.equal(runCompleted({ id: 1, status: 'success' }, { id: 2, status: 'success' }), true)
})
test('refreshes after a manual request whose first poll has no run record', () => {
  assert.equal(runCompleted(null, null), false)
  assert.equal(runCompleted(null, { id: 1, status: 'success' }), true)
})
test('refreshes once when a running record finishes, but not for unchanged or absent records', () => {
  const completed = { id: 1, status: 'partial', finished_at: '2026-10-12T10:00:00Z' }
  assert.equal(runCompleted({ id: 1, status: 'running' }, completed), true)
  assert.equal(runCompleted(completed, { ...completed }), false)
  assert.equal(runCompleted(completed, { id: 2, status: 'running' }), false)
  assert.equal(runCompleted({ id: 2, status: 'running' }, null), false)
})
