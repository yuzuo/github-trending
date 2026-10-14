<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
import { renderMarkdown } from './markdown.js'
import { runCompleted } from './run-state.js'
import { growthLabel, reviewLabels, reviewPayload } from './watch-state.js'

document.title = '采集项目观察 · 开源观察'
const items = ref([]), languages = ref([]), activeCount = ref(0), limit = ref(200)
const query = ref(''), language = ref(''), view = ref('all'), sort = ref('growth_7d')
const loading = ref(true), error = ref(''), notice = ref(''), refreshError = ref(''), repository = ref(''), adding = ref(false)
const run = ref(null), collecting = ref(false), pollError = ref(''), busyIds = reactive(new Set())
const dialog = ref(null), detail = ref(null), detailLoading = ref(false), detailError = ref(''), saveMessage = ref('')
const draft = reactive({ review_status: 'pending', rating: '', notes: '' })
const running = computed(() => collecting.value || run.value?.status === 'running')
const renderedReadme = computed(() => detail.value ? renderMarkdown(detail.value.readme_original, detail.value) : '')
const statusLabels = { running: '正在监测', success: '监测完成', partial: '部分完成', failed: '监测失败', interrupted: '监测中断' }
const number = value => value == null ? '暂无记录' : new Intl.NumberFormat('zh-CN').format(value)
const time = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '暂无记录'
const controllers = new Set()
let listController, detailController, listRequest = 0, detailRequest = 0, searchTimer, pollTimer, refreshTimer, pollBusy = false, disposed = false
async function api(path, body, method = 'GET', controller = new AbortController()) {
  controllers.add(controller)
  try {
    const response = await fetch('/api/watch' + path, { method, signal: controller.signal, ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`)
    return data
  } finally { controllers.delete(controller) }
}
async function loadItems(background = false) {
  background = background === true
  if (disposed || (background && loading.value)) return
  const request = ++listRequest
  listController?.abort(); listController = new AbortController()
  if (!background) loading.value = true
  error.value = ''
  try {
    const result = await api('/projects?' + new URLSearchParams({ q: query.value, language: language.value, view: view.value, sort: sort.value }), undefined, 'GET', listController)
    if (request !== listRequest || disposed) return
    items.value = result.items; languages.value = result.languages; activeCount.value = result.active_count; limit.value = result.limit
  } catch (e) { if (request === listRequest && e.name !== 'AbortError') { if (background) refreshError.value = `列表刷新失败：${e.message}`; else error.value = e.message } }
  finally { if (request === listRequest) loading.value = false }
}
async function refreshDetail() {
  const id = detail.value?.id
  if (!dialog.value?.open || !id || detailLoading.value || busyIds.has(id)) return
  const request = ++detailRequest
  detailController?.abort(); detailController = new AbortController()
  try {
    const result = await api('/projects/' + id, undefined, 'GET', detailController)
    if (disposed || request !== detailRequest || detail.value?.id !== id || busyIds.has(id)) return
    // Keep the editor draft independent of refreshed server observations.
    detail.value = result
  } catch (e) { if (request === detailRequest && e.name !== 'AbortError') refreshError.value = `详情刷新失败：${e.message}` }
}
async function refreshData() {
  if (disposed) return
  refreshError.value = ''
  await Promise.all([loadItems(true), refreshDetail()])
}
async function poll() {
  if (pollBusy || disposed) return
  pollBusy = true
  try {
    const previous = run.value, current = await api('/run')
    if (disposed) return
    run.value = current; pollError.value = ''
    if (runCompleted(previous, current)) await refreshData()
  } catch (e) { if (e.name !== 'AbortError') pollError.value = `任务状态暂不可用：${e.message}` }
  finally { pollBusy = false }
}
async function collect() {
  collecting.value = true; notice.value = ''
  try { await api('/refresh', {}, 'POST'); notice.value = '监测已启动，完成后自动更新列表。'; await poll() }
  catch (e) { if (e.name !== 'AbortError') { notice.value = e.message; await poll() } }
  finally { collecting.value = false }
}
async function add() {
  if (adding.value || !repository.value.trim()) return
  adding.value = true; notice.value = ''
  try { const result = await api('/projects', { repository: repository.value.trim() }, 'POST'); repository.value = ''; notice.value = `已添加 ${result.full_name}。`; await loadItems() }
  catch (e) { if (e.name !== 'AbortError') notice.value = e.message }
  finally { adding.value = false }
}
async function patch(repo, changes, review = false) {
  if (busyIds.has(repo.id)) return
  busyIds.add(repo.id); notice.value = ''; saveMessage.value = ''
  if (detail.value?.id === repo.id) cancelDetail()
  try {
    const updated = await api('/projects/' + repo.id, changes, 'PATCH')
    if (detail.value?.id === repo.id) {
      detail.value = { ...detail.value, ...updated }
      if (review) saveMessage.value = '测评记录已保存。'
    }
    notice.value = review ? '测评记录已保存。' : '项目状态已更新。'
    await loadItems()
  } catch (e) { if (e.name !== 'AbortError') { notice.value = e.message; if (detail.value?.id === repo.id) saveMessage.value = `保存失败：${e.message}` } }
  finally { busyIds.delete(repo.id) }
}
async function openDetail(id) {
  if (busyIds.has(id)) return
  const request = ++detailRequest
  detailController?.abort(); detailController = new AbortController()
  detail.value = null; detailError.value = ''; saveMessage.value = ''; detailLoading.value = true
  if (!dialog.value.open) dialog.value.showModal()
  try {
    const result = await api('/projects/' + id, undefined, 'GET', detailController)
    if (request !== detailRequest || disposed) return
    detail.value = result
    Object.assign(draft, { review_status: result.review_status, rating: result.rating ?? '', notes: result.notes || '' })
  } catch (e) { if (request === detailRequest && e.name !== 'AbortError') detailError.value = e.message }
  finally { if (request === detailRequest) detailLoading.value = false }
}
function cancelDetail() { ++detailRequest; detailController?.abort() }
function closeDetail() { cancelDetail(); dialog.value.close() }
function saveReview() {
  try { patch(detail.value, reviewPayload(draft), true) } catch (e) { saveMessage.value = e.message }
}
watch([language, view, sort], loadItems)
watch(query, () => { ++listRequest; listController?.abort(); clearTimeout(searchTimer); searchTimer = setTimeout(loadItems, 250) })
onMounted(() => { loadItems(); poll(); pollTimer = setInterval(poll, 4000); refreshTimer = setInterval(refreshData, 60000) })
onUnmounted(() => { disposed = true; ++listRequest; ++detailRequest; clearTimeout(searchTimer); clearInterval(pollTimer); clearInterval(refreshTimer); controllers.forEach(controller => controller.abort()) })
</script>

<template>
  <header class="masthead">
    <div class="topbar shell"><a class="brand" href="/"><span class="brand-icon">⌘</span> 开源观察</a><nav class="source-nav" aria-label="观察导航"><a href="/trending">每日 Trending</a><a href="/stars">Star 总榜</a><a href="/crawler-watch" aria-current="page">采集项目观察</a></nav><span class="local"><i></i> 本地知识库</span></div>
    <div class="hero shell"><div><p class="eyebrow">CRAWLER WATCH · 持续发现，认真测评</p><h1>追踪数据采集的<span>开源脉动。</span></h1><p class="hero-copy">发现爬虫与网页提取项目，记录真实 Star 变化，建立自己的测评档案。</p></div><div class="hero-note"><span>从发现，到实践。</span><strong>Discover. Watch. Review.</strong></div></div>
  </header>
  <main class="shell">
    <section class="toolbar" aria-label="项目筛选"><label class="search">搜索项目<input v-model="query" type="search" placeholder="名称或描述关键词…"></label><label>开发语言<select v-model="language"><option value="">全部语言</option><option v-for="name in languages" :key="name">{{ name }}</option></select></label><label>排序依据<select v-model="sort"><option value="growth_7d">近 7 天新增 Stars</option><option value="growth_24h">近 24 小时新增 Stars</option><option value="stars">累计 Stars</option></select></label><button class="primary collect" :disabled="running" @click="collect"><span :class="{ spin: running }">↻</span>{{ running ? '监测中…' : '立即更新' }}</button></section>
    <div class="run-info" aria-live="polite"><span><i :class="['dot', { active: running }]"></i>{{ run ? statusLabels[run.status] || run.status : '尚无监测任务' }}<template v-if="run?.finished_at"> · {{ time(run.finished_at) }}</template><template v-if="run"> · 成功 {{ run.success_count || 0 }} / 失败 {{ run.failure_count || 0 }}</template></span><span>{{ pollError || run?.error }}<template v-if="run?.retry_at"> · 可重试时间 {{ time(run.retry_at) }}</template></span></div>
    <form class="watch-add" @submit.prevent="add"><label for="repository">手动添加公开仓库</label><div><input id="repository" v-model="repository" placeholder="owner/repo 或 https://github.com/owner/repo" required :disabled="adding"><button class="primary" :disabled="adding || !repository.trim()">{{ adding ? '正在添加…' : '添加项目' }}</button></div><small>活动监测 {{ activeCount }} / {{ limit }} · 隐藏无关项目可释放名额</small></form>
    <p v-if="notice" class="watch-notice" role="status">{{ notice }}</p>
    <p v-if="refreshError" class="watch-notice" role="status">{{ refreshError }}</p>
    <div class="section-heading"><div><p class="eyebrow">YOUR RESEARCH RADAR</p><h2>采集项目观察 <span>{{ items.length }} 个项目</span></h2></div><div class="toggle watch-views" aria-label="项目视图"><button v-for="[key, label] in [['all','全部项目'],['following','我的关注'],['pending','待测评'],['hidden','已隐藏']]" :key="key" :aria-pressed="view === key" @click="view = key">{{ label }}</button></div></div>
    <div v-if="loading" class="empty" role="status"><span class="loader"></span><h3>正在加载观察项目</h3></div>
    <div v-else-if="error" class="empty error" role="alert"><h3>暂时无法加载</h3><p>{{ error }}</p><button @click="loadItems">重新加载</button></div>
    <div v-else-if="!items.length" class="empty"><div class="empty-symbol">⌘</div><h3>这里还没有匹配的项目</h3><p>调整筛选、添加仓库，或点击「立即更新」发现采集项目。</p></div>
    <section v-else class="cards" aria-label="采集项目"><article v-for="repo in items" :key="repo.id" class="repo-card">
      <div class="card-top"><span class="rank">{{ reviewLabels[repo.review_status] }}{{ repo.rating ? ` · ${repo.rating}/5` : '' }}</span><span class="star-count">☆ {{ number(repo.stars) }}</span></div>
      <button class="repo-title" :disabled="busyIds.has(repo.id)" @click="openDetail(repo.id)"><span>{{ repo.full_name.split('/')[0] }} /</span><strong>{{ repo.full_name.split('/')[1] }}</strong></button><p class="description">{{ repo.description || '这个项目暂时没有描述。' }}</p>
      <div class="watch-growth"><div><small>近 24 小时净增</small><strong>{{ growthLabel(repo.growth_24h) }}</strong></div><div><small>近 7 天净增</small><strong>{{ growthLabel(repo.growth_7d) }}</strong></div></div>
      <div class="card-tags"><span>{{ repo.language || '未识别语言' }}</span><span v-if="repo.license">{{ repo.license }}</span><span v-if="repo.stale" class="watch-warning">数据过期</span><span v-if="repo.hidden">已隐藏</span></div>
      <p v-if="repo.last_error" class="watch-warning">上次监测失败：{{ repo.last_error }}</p>
      <div class="card-bottom"><button :disabled="busyIds.has(repo.id)" :aria-pressed="repo.followed" @click="patch(repo, { followed: !repo.followed })">{{ repo.followed ? '★ 已关注' : '☆ 关注' }}</button><button :disabled="busyIds.has(repo.id)" @click="patch(repo, { hidden: !repo.hidden })">{{ repo.hidden ? '恢复监测' : '隐藏' }}</button><button :disabled="busyIds.has(repo.id)" @click="openDetail(repo.id)">详情与测评 ↗</button></div>
      <p class="snapshot-time">最近推送 {{ time(repo.pushed_at) }}<br>最近监测 {{ time(repo.fetched_at) }}</p>
    </article></section>
    <p class="coverage-note">每 6 小时监测、每天自动发现（需启用调度且服务持续运行）。净增长来自实际观测样本，缺少有效基准显示「积累中」，完整 7 天增长至少需要积累 7 天数据；首日可切换累计 Stars 排序。超过 12 小时的数据标记过期，在增长排序中后置。候选来自有限主题与关键词搜索，并非全站完整分类。隐藏后停止监测，历史与笔记保留。</p>
    <footer><span>开源观察 / Crawler Watch</span><span>真实观测 · 人工测评 · 本地保存</span></footer>
  </main>
  <dialog ref="dialog" class="detail-dialog" aria-labelledby="watch-detail-title" @cancel="cancelDetail" @click="event => { if (event.target === dialog) closeDetail() }">
    <div class="dialog-top"><span id="watch-detail-title" class="eyebrow">CRAWLER WATCH / 项目档案</span><button class="close" aria-label="关闭项目详情" @click="closeDetail">×</button></div>
    <div v-if="detailLoading" class="empty" role="status">正在加载项目详情…</div><div v-else-if="detailError" class="empty error" role="alert">{{ detailError }}</div>
    <template v-else-if="detail">
      <div class="detail-header"><h2>{{ detail.full_name }}</h2><p>{{ detail.description }}</p><a :href="'https://github.com/' + detail.full_name" target="_blank" rel="noopener noreferrer" class="github-link">在 GitHub 查看 ↗</a><div class="detail-badges"><span>{{ detail.language || '未识别语言' }}</span><span>{{ detail.license || '未标注许可证' }}</span><span>☆ {{ number(detail.stars) }} Stars</span><span v-if="detail.stale">数据过期</span><span>{{ detail.manual ? '手动添加' : '自动发现' }}</span></div><p>发现依据：{{ Array.isArray(detail.discovered_by) ? detail.discovered_by.join('、') : detail.discovered_by || '手动添加' }}</p><p>最近推送 {{ time(detail.pushed_at) }} · 最近监测 {{ time(detail.fetched_at) }}</p><p v-if="detail.last_error" class="watch-warning">上次监测失败：{{ detail.last_error }}</p>
        <dl class="watch-intervals"><div v-for="[key, label] in [['growth_24h','近 24 小时'],['growth_7d','近 7 天']]" :key="key"><dt>{{ label }}净增：{{ growthLabel(detail[key]) }}</dt><dd>{{ detail[key] ? `${time(detail[key].start)} → ${time(detail[key].end)}` : '尚无有效基准，请等待样本积累。' }}</dd></div></dl>
      </div>
      <form class="watch-review" @submit.prevent="saveReview"><h3>人工测评</h3><p>笔记为此部署共享资料；评分由你判断，不代表自动质量评估。</p><fieldset :disabled="busyIds.has(detail.id)"><div class="watch-review-fields"><label>测评状态<select v-model="draft.review_status"><option v-for="(label, key) in reviewLabels" :key="key" :value="key">{{ label }}</option></select></label><label>个人评分<select v-model="draft.rating"><option value="">未评分</option><option v-for="n in 5" :key="n" :value="n">{{ n }} 分</option></select></label></div><label>测评笔记<textarea v-model="draft.notes" rows="6" placeholder="使用场景、试用结果、限制和下一步…"></textarea></label><button class="primary">{{ busyIds.has(detail.id) ? '保存中…' : '保存测评记录' }}</button></fieldset><p role="status">{{ saveMessage }}</p></form>
      <section class="watch-history"><h3>监测历史 <small>最近 100 次成功样本</small></h3><div class="watch-table"><table v-if="detail.history?.length"><thead><tr><th scope="col">实际观测时间</th><th scope="col">累计 Stars</th></tr></thead><tbody><tr v-for="sample in detail.history" :key="sample.fetched_at"><td>{{ time(sample.fetched_at) }}</td><td>{{ number(sample.stars) }}</td></tr></tbody></table><p v-else>暂无成功监测样本。</p></div></section>
      <div class="readme-bar"><h3>README<span> · 原文</span></h3></div><article v-if="renderedReadme" class="markdown-body" v-html="renderedReadme"></article><div v-else class="empty">此项目暂未提供 README。</div>
    </template>
  </dialog>
</template>

<style scoped>
.watch-add{padding:20px 23px;background:#e9f0f2;border:1px solid #dce6e9;border-radius:10px;display:grid;gap:10px}.watch-add label{font-size:12px;font-weight:600}.watch-add>div{display:flex;gap:12px}.watch-add input{flex:1;min-width:0}.watch-add small{font-size:11px;color:#758693}.watch-add input,.watch-review select,.watch-review textarea{font:inherit;font-size:12px;padding:10px 12px;border:1px solid #d6e0e7;border-radius:6px;background:#fff;color:#24374e}.watch-notice{font-size:12px;padding:12px 16px;border-left:3px solid #258f91;background:#e5f3f0;overflow-wrap:anywhere}.watch-growth{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:14px 0;margin-bottom:15px;border-top:1px solid #edf0f4}.watch-growth div{display:flex;flex-direction:column;gap:6px}.watch-growth small{font-size:10px;color:#81909c}.watch-growth strong{font-size:18px;color:#276e70;font-variant-numeric:tabular-nums}.watch-warning{color:#a36a2e!important;font-size:11px;line-height:1.7;overflow-wrap:anywhere}.watch-review,.watch-history{padding:24px 30px;border-top:1px solid #e6ebf0}.watch-review{background:#f6f9fa}.watch-review h3,.watch-history h3{font-size:16px;margin:0 0 12px}.watch-review p,.watch-history small,.watch-history p{font-size:11px;color:#7b8c9a;line-height:1.8}.watch-review fieldset{border:0;padding:0;margin:0;min-width:0}.watch-review label{display:flex;flex-direction:column;gap:8px;font-size:12px;margin-bottom:16px}.watch-review-fields{display:flex;gap:16px}.watch-review-fields label{flex:1}.watch-review textarea{width:100%;resize:vertical;line-height:1.8}.watch-review textarea:focus-visible{outline:3px solid #00a6ba;outline-offset:3px}.watch-table{max-height:290px;overflow:auto}.watch-table table{width:100%;border-collapse:collapse;font-size:12px;text-align:left}.watch-table th,.watch-table td{padding:10px 12px;border-bottom:1px solid #e3eaf0}.watch-table th{background:#f1f5f7;position:sticky;top:0}.watch-intervals{display:grid;gap:16px;font-size:12px;border-top:1px solid #e5edf0;padding-top:20px}.watch-intervals dt{font-weight:600;color:#276e70}.watch-intervals dd{margin:7px 0 0;color:#788b99;font-size:11px}.snapshot-time{line-height:1.9}.watch-views{flex-wrap:wrap}.watch-views button{padding:7px 10px}@media(max-width:760px){.section-heading{align-items:start;gap:20px;flex-direction:column}.watch-add>div{flex-wrap:wrap}.watch-add input{flex-basis:100%}.watch-add button{width:100%}.watch-review,.watch-history{padding:22px 18px}}
</style>
