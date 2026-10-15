<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'

document.title = '需要关注 · 开源观察'
const items = ref([]), profiles = ref([]), total = ref(0), project = ref(''), category = ref('all'), includeAll = ref(false), offset = ref(0)
const loading = ref(false), error = ref(''), notice = ref(''), enabled = ref(false), running = ref(false), starting = ref(false)
const profileProject = ref(''), form = ref({ usage_status: 'evaluating', version: '', scenario: '', capabilities: '' }), saving = ref(false), profileNotice = ref('')
const validations = ref([]), comparison = ref(null), validationError = ref(''), validationLoading = ref(false)
const categories = { all: '全部分类', feature: '新功能', breaking: '破坏性变更', bug: '问题报告', fix: '修复说明', other: '其他' }
const states = { ready: '分析完成', pending: '待分析', failed: '分析失败', unconfigured: '未配置分析', stale: '分析已过期，请刷新' }
const priorities = { high: '高优先级', medium: '中优先级', low: '低优先级' }
const time = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '暂无记录'
const safeUrl = value => { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined } catch { return undefined } }
const controllers = new Set()
let requestId = 0, validationId = 0, listController, validationController, timer, disposed = false
async function api(path, method = 'GET', body, controller = new AbortController()) {
  controllers.add(controller)
  try {
    const response = await fetch('/api/watch' + path, { method, signal: controller.signal, ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`)
    return data
  } finally { controllers.delete(controller) }
}
async function load(background = false) {
  if (disposed || (background && loading.value)) return
  const id = ++requestId
  listController?.abort(); listController = new AbortController()
  if (!background) loading.value = true
  error.value = ''
  const params = new URLSearchParams({ category: category.value, include_all: includeAll.value, limit: 20, offset: offset.value })
  if (project.value) params.set('project_id', project.value)
  try {
    const data = await api('/attention?' + params, 'GET', undefined, listController)
    if (disposed || id !== requestId) return
    items.value = data.items; profiles.value = data.profiles; total.value = data.total; enabled.value = data.analysis_enabled; running.value = data.running
    if (offset.value && !data.items.length && data.total <= offset.value) { offset.value = Math.max(0, Math.floor((data.total - 1) / 20) * 20); await load() }
  } catch (e) { if (id === requestId && e.name !== 'AbortError') error.value = e.message }
  finally { if (id === requestId) loading.value = false }
}
async function analyze() {
  starting.value = true; notice.value = ''
  try { await api('/analyze', 'POST', {}); notice.value = '分析任务已启动，结果会自动刷新。'; await load(true) }
  catch (e) { if (e.name !== 'AbortError') notice.value = e.message }
  finally { starting.value = false }
}
async function loadValidations() {
  const id = ++validationId
  validationController?.abort(); validationController = new AbortController()
  validations.value = []; comparison.value = null; validationError.value = ''; validationLoading.value = false
  if (!profileProject.value) return
  validationLoading.value = true
  try {
    const data = await api('/validations?project_id=' + encodeURIComponent(profileProject.value), 'GET', undefined, validationController)
    if (disposed || id !== validationId) return
    validations.value = data.items; comparison.value = data.comparison
  } catch (e) { if (id === validationId && e.name !== 'AbortError') validationError.value = e.message }
  finally { if (id === validationId) validationLoading.value = false }
}
async function saveProfile() {
  const id = profileProject.value
  saving.value = true; profileNotice.value = ''
  try {
    const saved = await api('/profiles/' + encodeURIComponent(id), 'PUT', { ...form.value, capabilities: form.value.capabilities.split('\n').map(s => s.trim()).filter(Boolean) })
    if (disposed || id !== profileProject.value) return
    profiles.value = profiles.value.map(p => String(p.project_id) === id ? { ...p, ...saved } : p)
    profileNotice.value = '档案已保存，旧分析可能已过期，请刷新分析。'; await load(true)
  } catch (e) { if (id === profileProject.value && e.name !== 'AbortError') profileNotice.value = e.message }
  finally { saving.value = false }
}
function page(delta) { offset.value += delta; load() }
function missingVersion(item) { return !profiles.value.find(p => p.project_id === item.project_id)?.version }
watch([project, category, includeAll], () => { offset.value = 0; load() })
watch(profileProject, () => {
  const p = profiles.value.find(p => String(p.project_id) === profileProject.value)
  form.value = { usage_status: p?.usage_status || 'evaluating', version: p?.version || '', scenario: p?.scenario || '', capabilities: (p?.capabilities || []).join('\n') }
  profileNotice.value = ''; loadValidations()
})
onMounted(() => { load(); timer = setInterval(() => { if (running.value) load(true) }, 5000) })
onUnmounted(() => { disposed = true; ++requestId; ++validationId; clearInterval(timer); controllers.forEach(c => c.abort()) })
</script>

<template>
  <header class="masthead">
    <div class="topbar shell"><a class="brand" href="/"><span class="brand-icon">⌘</span> 开源观察</a><nav class="source-nav" aria-label="观察导航"><a href="/trending">每日 Trending</a><a href="/stars">Star 总榜</a><a href="/crawler-watch">采集项目观察</a><a href="/crawler-watch/updates">项目动态</a><a href="/crawler-watch/attention" aria-current="page">需要关注</a></nav></div>
    <div class="hero shell"><div><p class="eyebrow">NEEDS ATTENTION · 结合实际使用</p><h1>看懂变化，<span>判断下一步。</span></h1><p class="hero-copy">把来源证据、项目使用档案和固定任务测试放在一起，保留事实与模型解读的边界。</p></div></div>
  </header>
  <main class="shell attention-main">
    <section class="attention-intro"><div><h2>需要关注</h2><p>默认显示分析完成的高、中优先级动态；可切换查看全部及待分析内容。</p></div><button class="primary" :disabled="!enabled || running || starting" @click="analyze">{{ running || starting ? '分析中…' : '刷新分析' }}</button></section>
    <p v-if="!enabled" class="attention-note">未配置模型分析。可查看全部动态和来源证据，配置后再刷新分析。</p>
    <p v-if="notice" role="status" class="attention-note">{{ notice }}</p>
    <section class="toolbar" aria-label="关注筛选">
      <label>项目<select v-model="project"><option value="">全部关注项目</option><option v-for="p in profiles" :key="p.project_id" :value="String(p.project_id)">{{ p.full_name }}</option></select></label>
      <label>分类<select v-model="category"><option v-for="(label, key) in categories" :key="key" :value="key">{{ label }}</option></select></label>
      <label class="all-filter"><input v-model="includeAll" type="checkbox">显示全部及待分析</label><button @click="load()">刷新列表</button>
    </section>
    <p v-if="error" class="attention-note" role="alert">加载失败：{{ error }} <button @click="load()">重试</button></p>
    <p v-if="loading" class="empty" role="status">正在加载…</p>
    <div v-else-if="!items.length && !error" class="empty"><h3>暂无匹配的关注项</h3><p>可切换查看全部及待分析，或在<a href="/crawler-watch">采集项目观察</a>中关注项目。</p></div>
    <section v-else-if="!loading" class="attention-list" aria-label="关注列表">
      <article v-for="item in items" :key="item.id" class="attention-card">
        <div class="event-meta">{{ item.full_name }} · {{ categories[item.analysis?.category] || '待分类' }} · {{ priorities[item.analysis?.priority] || '优先级待定' }} <strong v-if="item.unread"> · 未读变化</strong></div>
        <h3><a :href="safeUrl(item.url)" target="_blank" rel="noopener noreferrer">{{ item.title }} ↗</a></h3>
        <p class="attention-warning">模型解读 · 未验证 · {{ states[item.analysis?.status] || '待分析' }}</p>
        <p v-if="missingVersion(item)" class="attention-warning">未填写版本，影响未知。请完善项目使用档案。</p>
        <dl><dt>变化摘要</dt><dd>{{ item.analysis?.summary || '暂无分析，先查看来源证据。' }}</dd><dt>对当前使用的影响</dt><dd>{{ item.analysis?.impact || '影响未知' }}</dd><dt>建议行动</dt><dd>{{ item.analysis?.action || '查看来源并人工确认。' }}</dd></dl>
        <p v-if="item.analysis?.error" class="attention-warning">分析错误：{{ item.analysis.error }}</p>
        <p v-for="warning in item.analysis?.warnings || []" :key="warning" class="attention-warning">证据限制：{{ warning }}</p>
        <p class="event-meta">分析时间 {{ time(item.analysis?.analyzed_at) }} · {{ item.analysis?.model || '暂无模型记录' }}</p>
        <details><summary>来源证据（{{ item.evidence?.length || 0 }}）与相关动态</summary><p class="attention-warning">来源内容不代表维护者确认；Issue 关闭不等于修复已发布。模型引用仅供核对。</p>
          <p v-if="item.analysis?.evidence_ids?.length">模型引用：{{ item.analysis.evidence_ids.join('、') }}</p>
          <div v-for="e in item.evidence" :key="e.id" class="evidence"><a :href="safeUrl(e.url)" target="_blank" rel="noopener noreferrer">{{ e.title || e.id }} ↗</a><p>{{ e.id }} · {{ e.kind }} · {{ e.state || '状态未知' }} · {{ e.author_role || '作者角色未知' }}</p><pre>{{ e.excerpt || '无摘要' }}</pre></div>
          <ul><li v-for="e in item.related_events" :key="e.id"><a :href="safeUrl(e.url)" target="_blank" rel="noopener noreferrer">{{ e.title }}</a> · {{ e.kind }}</li></ul>
        </details>
      </article>
    </section>
    <div class="attention-pagination"><button :disabled="offset === 0 || loading" @click="page(-20)">上一页</button><span>共 {{ total }} 条 · 第 {{ Math.floor(offset / 20) + 1 }} 页</span><button :disabled="offset + 20 >= total || loading" @click="page(20)">下一页</button></div>
    <section class="attention-card profile-panel" aria-label="项目使用档案">
      <h2>项目使用档案</h2><p>档案变更后需重新分析；未填写的上下文不能用于判断实际影响。版本、场景和能力会发送至已配置的模型服务用于分析。</p>
      <label for="profile-project">选择项目</label><select id="profile-project" v-model="profileProject" :disabled="saving"><option value="">请选择关注项目</option><option v-for="p in profiles" :key="p.project_id" :value="String(p.project_id)">{{ p.full_name }}</option></select>
      <form v-if="profileProject" @submit.prevent="saveProfile">
        <label>使用状态<select v-model="form.usage_status"><option value="evaluating">评估中</option><option value="using">使用中</option></select></label>
        <label for="profile-version">当前使用版本</label><input id="profile-version" v-model="form.version" maxlength="200" placeholder="例如 v1.2.3；留空表示未知">
        <label>使用场景<textarea v-model="form.scenario" rows="3" maxlength="4000"></textarea></label>
        <label>依赖能力（每行一个）<textarea v-model="form.capabilities" rows="3" maxlength="8000"></textarea></label>
        <button class="primary" :disabled="saving">{{ saving ? '保存中…' : '保存使用档案' }}</button>
      </form><p v-if="profileNotice" role="status" class="attention-note">{{ profileNotice }}</p>
    </section>
    <section v-if="profileProject" class="attention-card validation-results" aria-label="版本测试结果"><h2>版本测试结果</h2><p class="attention-warning">测试仅验证固定任务，不代表项目所有能力已验证。这里展示独立 CLI 隔离执行后保存的结果。</p><button @click="loadValidations">刷新测试结果</button>
      <p v-if="validationLoading" role="status">正在加载测试结果…</p><p v-else-if="validationError" role="alert">{{ validationError }}</p><p v-else-if="!validations.length">尚无测试结果。</p>
      <div v-if="comparison" class="attention-note"><strong>相同测试套件最近版本对比：{{ comparison.baseline_version }} → {{ comparison.candidate_version }}</strong><p>{{ comparison.regression ? '发现回归' : '未发现回归（仅限该固定任务）' }} · {{ comparison.summary }}</p></div><p v-else-if="validations.length">暂无可比较的相同测试套件版本。</p>
      <details v-for="v in validations" :key="v.id"><summary>{{ v.version }} · {{ v.suite }} · {{ v.status === 'passed' ? '固定任务通过' : '固定任务失败' }} · {{ time(v.created_at) }}</summary><h4>指标</h4><pre>{{ JSON.stringify(v.metrics, null, 2) }}</pre><h4>执行证据</h4><pre>{{ JSON.stringify(v.evidence, null, 2) }}</pre></details>
    </section>
    <footer><span>开源观察 / Needs Attention</span><a href="/crawler-watch/updates">查看全部项目动态 ↗</a></footer>
  </main>
</template>

<style scoped>
.attention-main{padding-top:28px}.attention-intro{display:flex;justify-content:space-between;align-items:center;gap:20px}.attention-intro p,.profile-panel p,.validation-results p{font-size:13px;line-height:1.8}.attention-list{display:grid;gap:16px}.attention-card{background:white;border:1px solid #dce5e9;border-radius:10px;padding:24px;overflow-wrap:anywhere}.attention-card h3{font-size:18px}.attention-card a{color:#194657}.event-meta{font-size:12px;color:#62788a}.attention-warning{font-size:12px;color:#976326;line-height:1.8}.attention-note{background:#e5f3f0;border-left:3px solid #258f91;padding:14px;font-size:13px;overflow-wrap:anywhere}.attention-card dl{font-size:13px;line-height:1.8}.attention-card dt{font-weight:600;margin-top:12px}.attention-card dd{margin:4px 0;white-space:pre-wrap}.attention-card summary{cursor:pointer;padding:12px 0;font-size:13px}.attention-card pre{font:inherit;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;background:#f4f7f8;padding:12px}.evidence{border-top:1px solid #e3eaed;padding-top:12px;font-size:12px}.attention-pagination{display:flex;justify-content:center;align-items:center;gap:18px;padding:24px;font-size:12px}.toolbar .all-filter{display:flex;flex-direction:row;align-items:center;gap:8px}.all-filter input{width:auto}.profile-panel,.validation-results{margin-top:20px}.profile-panel form{display:grid;gap:12px;margin-top:16px;max-width:720px}.profile-panel label{display:grid;gap:8px;font-size:13px}.profile-panel select,.profile-panel input,.profile-panel textarea{padding:10px;border:1px solid #ccd8df;border-radius:6px;font:inherit;max-width:100%;box-sizing:border-box}.profile-panel form button{justify-self:start}.source-nav{flex-wrap:wrap}@media(max-width:700px){.attention-intro{align-items:flex-start;flex-direction:column}.attention-card{padding:16px}.toolbar select{max-width:100%}}
</style>
