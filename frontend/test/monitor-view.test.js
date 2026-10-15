import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'
import { parse, compileScript } from '@vue/compiler-sfc'

const dom = new JSDOM('<div id="app"></div>', { url: 'http://localhost/crawler-watch/updates' })
for (const key of ['window', 'document', 'Element', 'HTMLElement', 'SVGElement', 'Node']) globalThis[key] = dom.window[key]
const { createApp, nextTick } = await import('vue')
const filename = new URL('../src/Monitor.vue', import.meta.url)
const { descriptor } = parse(await readFile(filename, 'utf8'))
let source = compileScript(descriptor, { id: 'monitor-test', inlineTemplate: true }).content
source = source.replace(/from (["'])([^"']+)\1/g, (_, quote, name) => `from ${JSON.stringify(name.startsWith('.') ? new URL(name, filename).href : import.meta.resolve(name))}`)
const { default: Monitor } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
const settle = async () => { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
const response = data => ({ ok: true, json: async () => data })
const event = { id: 1, full_name: 'o/r', kind: 'issue', title: '<img src=x onerror=alert(1)>', body: '<script>alert(1)</script>',
  status: 'closed', labels: ['bug'], unread: true, changed_at: '2026-10-15T01:00:00Z', source_at: '2026-10-15T00:00:00Z',
  url: 'https://github.com/o/r/issues/1', history: [] }
const status = { schedule_enabled: true, run: null, projects: [{ id: 1, full_name: 'o/r', checked_at: null, issue_page: 2, last_error: '等待续传' }] }

test('monitor displays unverified closed reports safely and handles concurrent read conflict', async () => {
  let readBody, unread = true, conflict = true
  globalThis.fetch = async (url, options) => {
    if (url.endsWith('/monitor')) return response(status)
    if (url.endsWith('/read')) {
      readBody = JSON.parse(options.body)
      if (conflict) return { ok: false, status: 409, json: async () => ({ detail: '动态已有新变化' }) }
      unread = false
      return response({ status: 'read' })
    }
    return response({ items: [{ ...event, unread }], total: 1, unread_count: unread ? 1 : 0 })
  }
  const app = createApp(Monitor)
  app.mount('#app')
  try {
    await settle()
    assert.match(document.body.textContent, /已关闭（不代表已修复）/)
    assert.match(document.body.textContent, /未验证/)
    assert.equal(document.querySelector('.monitor-event script'), null)
    assert.equal(document.querySelector('.monitor-event img'), null)
    document.querySelector('.mark-read').click()
    await settle()
    assert.match(document.body.textContent, /动态已有新变化/)
    assert.deepEqual(readBody, { changed_at: event.changed_at })
    conflict = false
    document.querySelector('.mark-read').click()
    await settle()
    assert.equal(document.querySelector('.mark-read'), null)
  } finally { app.unmount() }
})

test('late filter response cannot overwrite current event list', async () => {
  let old, recent
  globalThis.fetch = async url => {
    if (url.endsWith('/monitor')) return response(status)
    return new Promise(resolve => { if (url.includes('kind=release')) recent = resolve; else old = resolve })
  }
  const app = createApp(Monitor)
  app.mount('#app')
  try {
    await settle()
    const select = document.querySelector('#event-kind')
    select.value = 'release'; select.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
    await settle()
    recent(response({ items: [{ ...event, title: 'current release' }], total: 1, unread_count: 0 }))
    await settle()
    old(response({ items: [{ ...event, title: 'stale issue' }], total: 1, unread_count: 0 }))
    await settle()
    assert.match(document.body.textContent, /current release/)
    assert.doesNotMatch(document.body.textContent, /stale issue/)
  } finally { app.unmount() }
})
