import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'
import { parse, compileScript } from '@vue/compiler-sfc'

const dom = new JSDOM('<div id="app"></div>', { url: 'http://localhost/crawler-watch/attention' })
for (const key of ['window', 'document', 'Element', 'HTMLElement', 'SVGElement', 'Node']) globalThis[key] = dom.window[key]
const { createApp, nextTick } = await import('vue')
const filename = new URL('../src/Attention.vue', import.meta.url)
const { descriptor } = parse(await readFile(filename, 'utf8'))
let source = compileScript(descriptor, { id: 'attention-test', inlineTemplate: true }).content
source = source.replace(/from (["'])([^"']+)\1/g, (_, quote, name) => `from ${JSON.stringify(name.startsWith('.') ? new URL(name, filename).href : import.meta.resolve(name))}`)
const { default: Attention } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
const settle = async () => { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
const response = data => ({ ok: true, json: async () => data })
const profile = { project_id: 1, full_name: 'o/r', usage_status: 'evaluating', version: '', scenario: '', capabilities: [] }
const item = { id: 1, project_id: 1, full_name: 'o/r', title: '<img src=x>', url: 'javascript:alert(1)', analysis: { status: 'stale', category: 'bug', priority: 'high', summary: '<script>bad</script>', impact: '待确认', action: '查看来源', evidence_ids: ['issue:1'] }, evidence: [{ id: 'issue:1', title: '原始报告', excerpt: '<img src=x>', url: 'https://github.com/o/r/issues/1', state: 'closed', author_role: 'CONTRIBUTOR' }], related_events: [] }
const data = { items: [item], total: 1, profiles: [profile], analysis_enabled: true, running: false, projects: [], jobs: [], alerts: [] }

test('attention keeps analysis unverified, escapes evidence and blocks unsafe URLs', async () => {
  globalThis.fetch = async () => response(data)
  const app = createApp(Attention); app.mount('#app')
  try {
    await settle()
    assert.match(document.body.textContent, /模型解读.*未验证/)
    assert.match(document.body.textContent, /未填写版本.*影响未知/)
    assert.match(document.body.textContent, /分析已过期/)
    assert.equal(document.querySelector('article img, article script'), null)
    assert.equal(document.querySelector('a[href^="javascript:"]'), null)
    assert.match(document.body.textContent, /原始报告/)
  } finally { app.unmount() }
})

test('profile save uses PUT, preserves form on failure, and loads bounded validation results', async () => {
  let saved, fail = true
  globalThis.fetch = async (url, options) => {
    if (url.includes('/profiles/')) {
      saved = { method: options.method, body: JSON.parse(options.body) }
      return fail ? { ok: false, status: 503, json: async () => ({ detail: '保存失败' }) } : response({ ...profile, ...saved.body })
    }
    if (url.includes('/validations')) return response({ items: [{ id: 2, version: 'v2', suite: 'smoke', status: 'failed', metrics: { success: 0 }, evidence: { error: '<img src=x>' } }], comparison: { baseline_version: 'v1', candidate_version: 'v2', regression: true, summary: '固定任务失败' } })
    return response(data)
  }
  const app = createApp(Attention); app.mount('#app')
  try {
    await settle()
    const select = document.querySelector('#profile-project'); select.value = '1'; select.dispatchEvent(new dom.window.Event('change', { bubbles: true })); await settle()
    const version = document.querySelector('#profile-version'); version.value = 'v2'; version.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
    document.querySelector('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })); await settle()
    assert.equal(saved.method, 'PUT'); assert.equal(saved.body.version, 'v2')
    assert.match(document.body.textContent, /保存失败/); assert.equal(version.value, 'v2')
    assert.match(document.body.textContent, /固定任务/); assert.match(document.body.textContent, /回归/)
    assert.equal(document.querySelector('.validation-results img'), null)
    fail = false
    document.querySelector('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })); await settle()
    assert.match(document.body.textContent, /档案已保存/)
  } finally { app.unmount() }
})

test('automatic checks show regression without model analysis and distinguish execution errors', async () => {
  let retried = false
  globalThis.fetch = async (url, options) => {
    if (url.endsWith('/retry')) { retried = options.method === 'POST'; return response({ status: 'queued' }) }
    if (url.includes('/validation-jobs')) return response({
      projects: [{ project_id: 1, full_name: 'owner/project', functional_status: 'not_configured', latest: [] }],
      alerts: [{ job_id: 1, full_name: 'owner/project', suite: 'source-smoke-v1', baseline_version: 'v1', candidate_version: 'v2', summary: '仅源码基础检查出现退化' }],
      jobs: [{ id: 2, full_name: 'owner/project', version: 'v3', suite: 'source-smoke-v1', status: 'error', attempts: 3, error: 'TimeoutError', source_url: 'javascript:alert(1)', result: {} }]
    })
    return response({ ...data, items: [], analysis_enabled: false })
  }
  const app = createApp(Attention); app.mount('#app')
  try {
    await settle()
    const section = document.querySelector('[aria-label="自动版本测试"]')
    assert.match(section.textContent, /源码基础检查回归/)
    assert.match(section.textContent, /功能实测待配置/)
    assert.match(section.textContent, /执行错误/)
    assert.equal(section.querySelector('a[href^="javascript:"]'), null)
    Array.from(section.querySelectorAll('button')).find(b => b.textContent === '重新排队').click()
    await settle()
    assert.equal(retried, true)
  } finally { app.unmount() }
})
