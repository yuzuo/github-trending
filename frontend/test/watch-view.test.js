import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'
import { parse, compileScript } from '@vue/compiler-sfc'

const dom = new JSDOM('<div id="app"></div>', { url: 'http://localhost/crawler-watch' })
for (const key of ['window', 'document', 'Element', 'HTMLElement', 'SVGElement', 'Node']) globalThis[key] = dom.window[key]
dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true }
dom.window.HTMLDialogElement.prototype.close = function () { this.open = false }
const { createApp, nextTick } = await import('vue')
const filename = new URL('../src/Watch.vue', import.meta.url)
const { descriptor } = parse(await readFile(filename, 'utf8'))
let source = compileScript(descriptor, { id: 'watch-test', inlineTemplate: true }).content
source = source.replace(/from (["'])([^"']+)\1/g, (_, quote, name) => `from ${JSON.stringify(name.startsWith('.') ? new URL(name, filename).href : import.meta.resolve(name))}`)
const { default: Watch } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
const settle = async () => { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
const response = data => ({ ok: true, json: async () => data })
const repo = { id: 1, full_name: 'sample/crawler', description: 'Example', stars: 123, review_status: 'pending', notes: '', rating: null, followed: false, hidden: false, growth_24h: null, growth_7d: null }
const listing = item => ({ items: [item], languages: ['Python'], active_count: 1, limit: 200 })

test('watch view handles detail cancellation, sanitized README and failed review without losing draft', async () => {
  const requests = []
  let resolveDetail, patchFails = false
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options })
    if (url === '/api/watch/run') return response(null)
    if (options.method === 'PATCH') return patchFails ? { ok: false, status: 500, json: async () => ({ detail: '保存失败，请重试' }) } : response({ ...repo, ...JSON.parse(options.body) })
    if (url === '/api/watch/projects/1') return new Promise(resolve => { resolveDetail = resolve })
    return response(listing(repo))
  }
  const app = createApp(Watch)
  app.mount('#app')
  try {
    await settle()
    assert.equal(document.querySelectorAll('.watch-growth strong')[0].textContent, '积累中')
    document.querySelector('.repo-title').click()
    await settle()
    document.querySelector('.close').click()
    resolveDetail(response({ ...repo, readme_original: '# Old detail' }))
    await settle()
    assert.equal(document.querySelector('dialog').open, false)
    assert.equal(document.querySelector('.watch-review'), null)
    document.querySelector('.repo-title').click()
    await settle()
    resolveDetail(response({ ...repo, readme_original: '<img src="x" onerror="alert(1)"><script>alert(1)</script>', history: [] }))
    await settle()
    assert.equal(document.querySelector('.markdown-body script'), null)
    assert.equal(document.querySelector('.markdown-body img').hasAttribute('onerror'), false)
    const textarea = document.querySelector('textarea')
    textarea.value = '<script>my plain text note</script>'
    textarea.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
    patchFails = true
    document.querySelector('.watch-review').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }))
    await settle()
    assert.match(document.querySelector('.watch-review').textContent, /保存失败，请重试/)
    assert.equal(textarea.value, '<script>my plain text note</script>')
    patchFails = false
    document.querySelector('.watch-review').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }))
    await settle()
    assert.match(document.querySelector('.watch-review').textContent, /测评记录已保存/)
    const mutation = requests.findLast(request => request.options.method === 'PATCH')
    assert.deepEqual(JSON.parse(mutation.options.body), { review_status: 'pending', rating: null, notes: '<script>my plain text note</script>' })
    assert.equal(mutation.options.headers['Content-Type'], 'application/json')
  } finally { app.unmount() }
})

test('latest filter result wins when an older response finishes late', async () => {
  let resolveOld, resolveNew
  globalThis.fetch = async url => {
    if (url === '/api/watch/run') return response(null)
    return new Promise(resolve => { if (url.includes('view=following')) resolveNew = resolve; else resolveOld = resolve })
  }
  const app = createApp(Watch)
  app.mount('#app')
  try {
    await settle()
    Array.from(document.querySelectorAll('.watch-views button')).find(button => button.textContent === '我的关注').click()
    await settle()
    resolveNew(response(listing({ ...repo, full_name: 'new/current' })))
    await settle()
    resolveOld(response(listing({ ...repo, full_name: 'old/stale' })))
    await settle()
    assert.match(document.querySelector('.repo-title').textContent, /current/)
    assert.doesNotMatch(document.querySelector('.repo-title').textContent, /stale/)
  } finally { app.unmount() }
})

test('pending review save prevents reopening a stale editor', async () => {
  let resolvePatch, saved = { ...repo, notes: 'old note' }, detailReads = 0
  globalThis.fetch = async (url, options) => {
    if (url === '/api/watch/run') return response(null)
    if (options.method === 'PATCH') return new Promise(resolve => { resolvePatch = () => { saved = { ...saved, ...JSON.parse(options.body) }; resolve(response(saved)) } })
    if (url === '/api/watch/projects/1') { ++detailReads; return response(saved) }
    return response(listing(saved))
  }
  const app = createApp(Watch)
  app.mount('#app')
  try {
    await settle()
    document.querySelector('.repo-title').click()
    await settle()
    const textarea = document.querySelector('textarea')
    textarea.value = 'new saved note'
    textarea.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
    document.querySelector('.watch-review').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }))
    await settle()
    document.querySelector('.close').click()
    await settle()
    assert.equal(document.querySelector('.repo-title').disabled, true)
    const detailButton = Array.from(document.querySelectorAll('.card-bottom button')).find(button => button.textContent.includes('详情'))
    assert.equal(detailButton.disabled, true)
    // Dispatch bypasses native disabled-click behavior to exercise the handler guard as well.
    document.querySelector('.repo-title').dispatchEvent(new dom.window.Event('click', { bubbles: true }))
    await settle()
    assert.equal(document.querySelector('dialog').open, false)
    assert.equal(detailReads, 1)
    resolvePatch()
    await settle()
    document.querySelector('.repo-title').click()
    await settle()
    assert.equal(document.querySelector('textarea').value, 'new saved note')
  } finally { app.unmount() }
})

test('minute refresh updates list and detail freshness silently without overwriting unsaved notes', async () => {
  const originalInterval = globalThis.setInterval, ticks = new Map()
  globalThis.setInterval = (callback, delay) => { ticks.set(delay, callback); return originalInterval(callback, delay) }
  let current = { ...repo, stale: false }, task = null, listReads = 0, detailReads = 0
  globalThis.fetch = async url => {
    if (url === '/api/watch/run') return response(task)
    if (url === '/api/watch/projects/1') { ++detailReads; return response(current) }
    ++listReads; return response(listing(current))
  }
  const app = createApp(Watch)
  app.mount('#app')
  try {
    await settle()
    document.querySelector('.repo-title').click()
    await settle()
    const textarea = document.querySelector('textarea')
    textarea.value = 'unsaved local edits'
    textarea.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
    current = { ...current, stale: true, stars: 456, notes: 'server note' }
    assert.equal(typeof ticks.get(60000), 'function')
    ticks.get(60000)()
    await nextTick()
    assert.equal(document.querySelector('.loader'), null)
    await settle()
    assert.equal(listReads, 2)
    assert.equal(detailReads, 2)
    assert.match(document.querySelector('.repo-card').textContent, /数据过期/)
    assert.match(document.querySelector('.detail-badges').textContent, /456 Stars/)
    assert.match(document.querySelector('.detail-badges').textContent, /数据过期/)
    assert.equal(document.querySelector('textarea').value, 'unsaved local edits')
    await ticks.get(4000)()
    assert.equal(listReads, 2)
    current = { ...current, stars: 789 }
    task = { id: 1, status: 'success' }
    await ticks.get(4000)()
    await settle()
    assert.equal(listReads, 3)
    assert.equal(detailReads, 3)
    assert.match(document.querySelector('.detail-badges').textContent, /789 Stars/)
    assert.equal(document.querySelector('textarea').value, 'unsaved local edits')
  } finally { app.unmount(); globalThis.setInterval = originalInterval }
})
