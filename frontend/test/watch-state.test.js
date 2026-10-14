import test from 'node:test'
import assert from 'node:assert/strict'
import { growthLabel, reviewPayload } from '../src/watch-state.js'

test('growth distinguishes missing baseline, zero, gain and loss', () => {
  assert.equal(growthLabel(null), '积累中')
  assert.equal(growthLabel({ delta: 0 }), '0')
  assert.equal(growthLabel({ delta: 1200 }), '+1,200')
  assert.equal(growthLabel({ delta: -12 }), '-12')
})

test('review keeps plain text and sends optional rating as null', () => {
  assert.deepEqual(reviewPayload({ review_status: 'reviewing', rating: '', notes: '<b>笔记</b>' }), {
    review_status: 'reviewing', rating: null, notes: '<b>笔记</b>',
  })
  assert.equal(reviewPayload({ review_status: 'reviewed', rating: '5', notes: '' }).rating, 5)
  assert.throws(() => reviewPayload({ review_status: 'wrong', rating: '', notes: '' }))
  for (const rating of ['0', '6', '2.5', 'NaN']) {
    assert.throws(() => reviewPayload({ review_status: 'pending', rating, notes: '' }))
  }
})
