<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

document.title = '项目动态 · 开源观察'
const items = ref([]), projects = ref([]), run = ref(null), total = ref(0), unreadCount = ref(0)
const project = ref(''), kind = ref('all'), unread = ref(false), offset = ref(0)
const loading = ref(false), error = ref(''), statusError = ref(''), notice = ref('')
const scheduleEnabled = ref(false), cooldown = ref(null), starting = ref(false), reading = ref(null)
const running = computed(() => starting.value || run.value?.status === 'running')
const labels = { published: '正式版本已发布', prerelease: '预发布版本', open: 'Issue 开放中', closed: '已关闭（不代表已修复）' }
const runLabels = { running: '检查中', success: '检查完成', partial: '部分完成', interrupted: '检查中断' }
const time = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未完成'
const controllers = new Set()
let eventController, requestId = 0, timer, disposed = false, polling = false
async function api(path, body, controller = new AbortController()) {
  controllers.add(controller)
  try {
    const response = await fetch('/api/watch' + path, { signal: controller.signal,
      ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`)
    return data
  } finally { controllers.delete(controller) }
}
async function loadEvents(background = false) {
  if (disposed || (background && loading.value)) return
  const id = ++requestId
  eventController?.abort(); eventController = new AbortController()
  if (!background) loading.value = true
  error.value = ''
  const params = new URLSearchParams({ kind: kind.value, unread: unread.value, limit: 20, offset: offset.value })
  if (project.value) params.set('project_id', project.value)
  try {
    const data = await api('/events?' + params, undefined, eventController)
    if (disposed || id !== requestId) return
    items.value = data.items; total.value = data.total; unreadCount.value = data.unread_count
    if (offset.value && !data.items.length && data.total <= offset.value) {
      offset.value = Math.max(0, Math.floor((data.total - 1) / 20) * 20)
      await loadEvents()
    }
  } catch (e) { if (id === requestId && e.name !== 'AbortError') error.value = e.message }
  finally { if (id === requestId) loading.value = false }
}
async function loadStatus() {
  try {
    const data = await api('/monitor')
    if (disposed) return
    projects.value = data.projects; run.value = data.run
    scheduleEnabled.value = data.schedule_enabled; cooldown.value = data.cooldown_until; statusError.value = ''
  } catch (e) { if (e.name !== 'AbortError') statusError.value = e.message }
}
async function poll() {
  if (disposed || polling) return
  polling = true
  try { await Promise.all([loadStatus(), loadEvents(true)]) } finally { polling = false }
}
async function refresh() {
  starting.value = true; notice.value = ''
  try { await api('/monitor/refresh', {}); notice.value = '动态检查已启动，结果会自动刷新。'; await loadStatus() }
  catch (e) { if (e.name !== 'AbortError') notice.value = e.message }
  finally { starting.value = false }
}
async function markRead(item) {
  if (reading.value !== null) return
  reading.value = item.id; notice.value = ''
  try { await api(`/events/${item.id}/read`, { changed_at: item.changed_at }); await loadEvents(true) }
  catch (e) { if (e.name !== 'AbortError') { notice.value = e.message; await loadEvents(true) } }
  finally { reading.value = null }
}
function page(delta) { offset.value += delta; loadEvents() }
watch([project, kind, unread], () => { offset.value = 0; loadEvents() })
onMounted(() => { loadEvents(); loadStatus(); timer = setInterval(poll, 15000) })
onUnmounted(() => { disposed = true; ++requestId; clearInterval(timer); controllers.forEach(c => c.abort()) })
</script>

<template>
  <header class="masthead">
    <div class="topbar shell"><a class="brand" href="/"><span class="brand-icon">⌘</span> 开源观察</a><nav class="source-nav" aria-label="观察导航"><a href="/trending">每日 Trending</a><a href="/stars">Star 总榜</a><a href="/crawler-watch">采集项目观察</a><a href="/crawler-watch/updates" aria-current="page">项目动态</a><a href="/crawler-watch/attention">需要关注</a></nav></div>
    <div class="hero shell"><div><p class="eyebrow">PROJECT UPDATES · 功能与问题</p><h1>了解新能力，<span>跟进新问题。</span></h1><p class="hero-copy">关注项目的版本发布和 Issue 变化，以原文证据为依据，持续保存状态。</p></div></div>
  </header>
  <main class="shell monitor-main">
    <section class="monitor-intro">
      <div><h2>关注项目动态 <span>{{ unreadCount }} 条未读</span></h2><p>在<a href="/crawler-watch">采集项目观察</a>中点击「关注」开启监测。首次记录为历史基线，后续变化标为未读。</p></div>
      <button class="primary" :disabled="running || !projects.length" @click="refresh">{{ running ? '检查中…' : '立即检查动态' }}</button>
    </section>
    <div class="run-info" aria-live="polite"><span>{{ scheduleEnabled ? '自动检查已启用 · 每 6 小时' : '自动检查未启用 · 可手动检查' }} · 关注 {{ projects.length }} 个项目<br>{{ run ? runLabels[run.status] || run.status : '尚无动态检查记录' }}<template v-if="run"> · 成功 {{ run.success_count }} / 未完成 {{ run.failure_count }} · {{ time(run.finished_at) }}</template></span><span>{{ statusError || run?.error }}<template v-if="cooldown"> · 限流冷却至 {{ time(cooldown) }}</template></span></div>
    <p v-if="notice" class="monitor-notice" role="status">{{ notice }}</p>
    <section class="toolbar" aria-label="动态筛选">
      <label>项目<select v-model="project"><option value="">全部关注项目</option><option v-for="p in projects" :key="p.id" :value="String(p.id)">{{ p.full_name }}</option></select></label>
      <label for="event-kind">动态类型<select id="event-kind" v-model="kind"><option value="all">全部类型</option><option value="release">版本与功能说明</option><option value="issue">问题与需求（Issue）</option></select></label>
      <label class="unread-filter"><input v-model="unread" type="checkbox">只看未读变化</label>
      <button @click="loadEvents()">刷新列表</button>
    </section>
    <p v-if="error" class="monitor-notice" role="alert">加载失败：{{ error }} <button @click="loadEvents()">重试</button></p>
    <div v-if="loading" class="empty" role="status">正在加载动态…</div>
    <div v-else-if="!items.length && !error" class="empty"><h3>{{ unread ? '暂无未读变化' : '暂无匹配的动态' }}</h3><p>{{ projects.length ? '可点击「立即检查动态」。首次同步的历史内容不会标为未读。' : '先去采集项目观察关注你关心的项目。' }}</p></div>
    <section v-else-if="!loading" class="monitor-events" aria-label="动态列表">
      <article v-for="item in items" :key="item.id" class="monitor-event" :class="{ unread: item.unread }">
        <div class="event-meta"><span>{{ item.full_name }}</span><span>{{ item.kind === 'release' ? 'Release' : 'Issue' }} · {{ labels[item.status] }} · 未验证</span><strong v-if="item.unread">未读变化</strong></div>
        <h3><a :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.title }} ↗</a></h3>
        <p class="event-excerpt">{{ item.body ? item.body.slice(0, 260) + (item.body.length > 260 ? '…' : '') : '来源未提供说明正文。' }}</p>
        <div v-if="item.labels.length" class="event-labels"><span v-for="label in item.labels" :key="label">{{ label }}</span></div>
        <p class="event-time">来源时间 {{ time(item.source_at) }} · 本地变化记录 {{ time(item.changed_at) }}</p>
        <details><summary>查看来源原文与变化记录</summary><p class="monitor-disclaimer">{{ item.kind === 'release' ? '发布说明来自项目作者，功能尚未经过实际运行验证。' : 'Issue 可能是问题报告、需求或讨论；关闭状态不等于修复已发布。' }}</p><pre>{{ item.body || '无正文' }}</pre><h4>最近 20 次变化</h4><ul><li v-for="(entry, index) in item.history" :key="index">{{ time(entry.at) }} · {{ labels[entry.status] }} · {{ entry.change === 'baseline' ? '历史基线' : '观察到变化' }} · {{ entry.title }}</li></ul></details>
        <button v-if="item.unread" class="mark-read" :disabled="reading !== null" @click="markRead(item)">{{ reading === item.id ? '保存中…' : '标为已读' }}</button>
      </article>
    </section>
    <div class="monitor-pagination"><button :disabled="offset === 0 || loading" @click="page(-20)">上一页</button><span>共 {{ total }} 条 · 第 {{ Math.floor(offset / 20) + 1 }} 页</span><button :disabled="offset + 20 >= total || loading" @click="page(20)">下一页</button></div>
    <details class="monitor-health"><summary>项目检查状态（{{ projects.length }}）</summary><ul><li v-for="p in projects" :key="p.id"><strong>{{ p.full_name }}</strong> · 完整同步 {{ time(p.checked_at) }} · Release {{ time(p.releases_checked_at) }}<span v-if="p.last_error"> · {{ p.last_error }}（Issue 待检查第 {{ p.issue_page }} 页）</span></li></ul></details>
    <p class="coverage-note">Release 检查最近 30 条；Issue 首次回溯最近 30 天更新记录，随后增量同步，每项目每轮最多 3 页，未完成时保留进度。隐藏或取消关注后停止检查，已保存历史保留。已读状态由此部署共享。此页记录来源变化，不自动推断维护者确认、修复版本或实际测评结果。</p>
    <footer><span>开源观察 / Project Updates</span><a href="/crawler-watch">管理关注项目 ↗</a></footer>
  </main>
</template>

<style scoped>
.monitor-main{padding-top:28px}.monitor-intro{display:flex;align-items:center;justify-content:space-between;gap:20px}.monitor-intro h2{font-size:23px}.monitor-intro h2 span{font-size:13px;color:#258f91;margin-left:12px}.monitor-intro p{font-size:13px;color:#637686;line-height:1.8}.monitor-intro button{white-space:nowrap}.monitor-notice{background:#e5f3f0;border-left:3px solid #258f91;padding:14px;overflow-wrap:anywhere;font-size:13px}.monitor-events{display:grid;gap:16px}.monitor-event{background:white;border:1px solid #dce5e9;border-radius:10px;padding:24px;overflow-wrap:anywhere}.monitor-event.unread{border-left:4px solid #258f91}.event-meta{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:#62788a}.event-meta strong{color:#258f91}.monitor-event h3{font-size:18px;margin:14px 0}.monitor-event a{color:#194657}.event-excerpt{font-size:13px;line-height:1.8;white-space:pre-wrap}.event-labels{display:flex;gap:6px;flex-wrap:wrap}.event-labels span{font-size:11px;padding:4px 8px;background:#edf4f4;border-radius:5px}.event-time{font-size:11px;color:#687e8c}.monitor-event summary,.monitor-health summary{cursor:pointer;font-size:13px;padding:10px 0}.monitor-event pre{font:inherit;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;padding:16px;background:#f4f7f8;max-height:440px;overflow:auto}.monitor-disclaimer{font-size:12px;color:#976326;line-height:1.8}.monitor-event ul,.monitor-health ul{font-size:12px;line-height:2;padding-left:20px}.mark-read{margin-top:16px}.monitor-pagination{display:flex;gap:18px;align-items:center;justify-content:center;padding:24px;font-size:12px}.monitor-health{padding:12px 20px;background:#eaf0f2;border-radius:8px}.toolbar .unread-filter{display:flex;flex-direction:row;align-items:center;gap:8px}.unread-filter input{width:auto}.toolbar select{max-width:360px}.run-info{white-space:pre-line;overflow-wrap:anywhere}@media(max-width:700px){.monitor-intro{align-items:flex-start;flex-direction:column}.monitor-event{padding:16px}.toolbar select{max-width:100%}.monitor-intro h2 span{display:block;margin:8px 0}.event-meta{gap:6px}.source-nav{flex-wrap:wrap}}
</style>
