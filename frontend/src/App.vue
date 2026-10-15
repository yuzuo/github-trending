<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { renderMarkdown } from './markdown.js'
import { runCompleted } from './run-state.js'
import { sourceForPath, sourceApiPath } from './source.js'

const source = sourceForPath(window.location.pathname)
const isTrending = source === 'trending'
const pageTitle = isTrending ? '每日 Trending' : 'Star 总榜'
const collectLabel = '补齐今日采集'
document.title = `GitHub ${pageTitle} · 开源观察`
const dates = ref([]), date = ref(''), query = ref(''), language = ref(''), languages = ref([]), items = ref([])
const snapshotLimit = ref(null)
const loading = ref(true), error = ref(''), run = ref(null), collecting = ref(false), notice = ref('')
const dialog = ref(null), detail = ref(null), detailLoading = ref(false), detailError = ref(''), readmeLanguage = ref('zh')
let listRequest = 0, detailRequest = 0, searchTimer, pollTimer, pollBusy = false
const running = computed(() => collecting.value || run.value?.status === 'running')
const statusLabels = { running: '正在采集', success: '采集完成', partial: '部分完成', failed: '采集失败', interrupted: '采集中断' }
const translationLabels = { pending: '等待翻译', unconfigured: '未配置翻译', translated: '已翻译', failed: '翻译失败', missing: '无 README', stale: '译文待更新', not_required: '待翻译' }
const renderedReadme = computed(() => detail.value ? renderMarkdown(readmeLanguage.value === 'zh' ? detail.value.readme_zh : detail.value.readme_original, detail.value) : '')
const number = value => new Intl.NumberFormat('zh-CN').format(value || 0)
const time = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '暂无记录'
async function api(path, options) {
  const response = await fetch(sourceApiPath(path, source, date.value), options)
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（${response.status}）`) }
  return response.json()
}
async function loadItems() {
  const request = ++listRequest
  loading.value = true; error.value = ''
  try {
    if (!date.value) { items.value = []; languages.value = []; return }
    const result = await api('/repositories?' + new URLSearchParams({ date: date.value, q: query.value, language: language.value }))
    if (request !== listRequest) return
    items.value = result.items; languages.value = result.languages; snapshotLimit.value = result.limit
  } catch (e) { if (request === listRequest) error.value = e.message }
  finally { if (request === listRequest) loading.value = false }
}
async function refresh() {
  try {
    dates.value = await api('/dates')
    if (!date.value && dates.value.length) date.value = dates.value[0]
    else await loadItems()
  } catch (e) { error.value = e.message; loading.value = false }
}
async function poll() {
  if (pollBusy) return
  pollBusy = true
  try {
    const previous = run.value
    run.value = await api('/runs/latest')
    notice.value = ''
    if (runCompleted(previous, run.value)) await refresh()
  } catch (e) { notice.value = `采集状态暂不可用：${e.message}` }
  finally { pollBusy = false }
}
async function collect() {
  collecting.value = true; notice.value = ''
  try {
    await api('/collect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    notice.value = '采集已启动，完成后列表会自动更新。'
    await poll()
  } catch (e) { await poll(); notice.value = e.message }
  finally { collecting.value = false }
}
async function openDetail(id) {
  const request = ++detailRequest
  detail.value = null; detailError.value = ''; detailLoading.value = true; readmeLanguage.value = isTrending ? 'zh' : 'original'
  await nextTick()
  if (!dialog.value.open) dialog.value.showModal()
  try {
    const result = await api('/repositories/' + id)
    if (request !== detailRequest) return
    detail.value = result
    if (!result.readme_zh) readmeLanguage.value = 'original'
  } catch (e) { if (request === detailRequest) detailError.value = e.message }
  finally { if (request === detailRequest) detailLoading.value = false }
}
function closeDetail() { ++detailRequest; dialog.value.close() }
watch([date, language], loadItems)
watch(query, () => { ++listRequest; clearTimeout(searchTimer); searchTimer = setTimeout(loadItems, 250) })
onMounted(async () => { await Promise.all([refresh(), poll()]); pollTimer = setInterval(poll, 4000) })
onUnmounted(() => { clearTimeout(searchTimer); clearInterval(pollTimer); ++listRequest; ++detailRequest })
</script>

<template>
  <header class="masthead">
    <div class="topbar shell"><a class="brand" href="/" aria-label="开源观察首页"><span class="brand-icon">⌘</span> 开源观察</a><nav class="source-nav" aria-label="榜单来源"><a href="/trending" :aria-current="isTrending ? 'page' : undefined">每日 Trending</a><a href="/stars" :aria-current="!isTrending ? 'page' : undefined">Star 总榜</a><a href="/crawler-watch">采集项目观察</a><a href="/crawler-watch/updates">项目动态</a></nav><span class="local"><i></i> 本地知识库</span></div>
    <div class="hero shell"><div><p class="eyebrow">{{ isTrending ? 'GITHUB TRENDING · 每日开源趋势' : 'GITHUB SEARCH · 公开仓库 STAR 总榜' }}</p><h1>{{ isTrending ? '捕捉今天的' : '发现下一份' }}<span>开源灵感。</span></h1><p class="hero-copy">{{ isTrending ? '追踪每日 Trending 榜单，发现正在升温的项目，留存趋势快照。' : '按累计 Stars 发现公开仓库，阅读项目原文，留存每日榜单快照。' }}</p></div><div class="hero-note"><span>保持好奇，持续构建。</span><strong>Explore. Learn. Build.</strong></div></div>
  </header>
  <main class="shell">
    <section class="toolbar" aria-label="项目筛选"><label>浏览日期<select v-model="date" :disabled="!dates.length"><option v-if="!dates.length" value="">暂无采集日期</option><option v-for="day in dates" :key="day">{{ day }}</option></select></label><label class="search">搜索项目<input v-model="query" type="search" placeholder="项目名称、描述或关键词…"></label><label>开发语言<select v-model="language"><option value="">全部语言</option><option v-for="name in languages" :key="name">{{ name }}</option></select></label><button class="primary collect" :disabled="running" @click="collect"><span :class="{ spin: running }">↻</span> {{ running ? '采集中…' : collectLabel }}</button></section>
    <div class="run-info" aria-live="polite"><span><i :class="['dot', { active: running }]"></i>{{ run ? statusLabels[run.status] || run.status : '尚未开始采集' }}<template v-if="run?.finished_at"> · {{ time(run.finished_at) }}</template><template v-if="run && !running && run.success_count != null"> · 成功 {{ run.success_count }} / 失败 {{ run.failure_count }}</template></span><span>{{ run?.error || notice }}</span></div>
    <div class="section-heading"><div><p class="eyebrow">{{ isTrending ? 'THE DAILY TRENDING' : snapshotLimit ? 'DAILY SNAPSHOT · TOP ' + number(snapshotLimit) : 'DAILY STAR SNAPSHOT' }}</p><h2>{{ pageTitle }} <span>{{ number(items.length) }} 个项目</span></h2></div><p>{{ isTrending ? '按当日新增 Stars 排序 ↓' : '按累计 Stars 排序 ↓' }}</p></div>
    <div v-if="loading" class="empty" role="status"><span class="loader"></span><h3>正在加载项目</h3><p>为你整理这一天的开源发现…</p></div>
    <div v-else-if="error" class="empty error" role="alert"><h3>暂时无法加载</h3><p>{{ error }}</p><button @click="refresh">重新加载</button></div>
    <div v-else-if="!items.length" class="empty"><div class="empty-symbol">⌘</div><h3>{{ dates.length ? '没有找到匹配的项目' : '你的开源观察，从这里开始' }}</h3><p>{{ dates.length ? '试试其他关键词、语言或日期。' : '点击「' + collectLabel + '」，建立第一份 ' + pageTitle + ' 快照。' }}</p></div>
    <section v-else class="cards" :aria-label="pageTitle + '项目'"><article v-for="repo in items" :key="repo.id" class="repo-card"><div class="card-top"><span class="rank">{{ isTrending ? '来源排名' : '总榜排名' }} {{ String(repo.rank || repo.trending_rank || '—').padStart(2, '0') }}</span><span v-if="isTrending" class="star-count">{{ repo.daily_stars == null ? '未提供' : '↗ +' + number(repo.daily_stars) }} <small>今日</small></span><span v-else class="star-count">☆ {{ number(repo.stars) }} <small>Stars</small></span></div><button class="repo-title" @click="openDetail(repo.id)"><span>{{ repo.full_name.split('/')[0] }} /</span><strong>{{ repo.full_name.split('/')[1] }}</strong></button><p class="description">{{ (isTrending && repo.description_zh) || repo.description || '这个项目暂时没有描述。' }}</p><div class="card-tags"><span v-if="repo.language"><i class="language-dot"></i>{{ repo.language }}</span><span v-if="repo.license">{{ repo.license }}</span><span v-if="isTrending && !repo.description_zh" class="translation-tag">{{ translationLabels[repo.translation_status] || '原文介绍' }}</span></div><div class="card-bottom"><span v-if="isTrending">☆ {{ number(repo.stars) }} <small>Stars</small></span><a :href="'https://github.com/' + repo.full_name" target="_blank" rel="noopener noreferrer">GitHub ↗</a><button @click="openDetail(repo.id)">阅读项目 <span aria-hidden="true">↗</span></button></div><p class="snapshot-time">采集于 {{ time(repo.fetched_at) }}</p></article></section>
    <p v-if="items.some(repo => repo.details_origin === 'legacy_backfill')" class="snapshot-warning" role="note">此日期包含旧数据回填：部分项目的元数据与 README 来自迁移时的最新版本，并非历史当日实况；请勿用于对应日期的内容变化分析。</p>
    <p v-if="isTrending" class="coverage-note">每日 01:00 采集，已完成的当日快照不会覆盖；手动采集仅补齐今日数据。此列表仅覆盖 GitHub Trending 每日榜单，并非 GitHub 全站项目。「今日」新增 Stars 为来源页面的统计窗口值，非自然日实时计数；总 Stars 为所选日期的采集快照。搜索与语言筛选作用于本地快照。</p>
    <p v-else class="coverage-note">每天北京时间 01:00 采集前 100 项，不翻译；当天成功记录不覆盖。历史榜单按原有数量保留。数据来自 GitHub 官方 Search API，按公开仓库累计 Stars 选取每日 {{ snapshotLimit ? 'Top ' + number(snapshotLimit) : 'Top N' }} 快照；Search API 最多返回前 1,000 个结果，并非全站完整归档。Stars 为所选日期采集时的累计值，不代表当日增长；搜索与语言筛选作用于本地快照。</p>
    <footer><span>开源观察 / {{ isTrending ? 'GitHub Trending Archive' : 'GitHub Search · Star Archive' }}</span><span>每日快照 · 本地保存 · {{ isTrending ? '中文阅读' : '原文阅读' }}</span></footer>
  </main>
  <dialog ref="dialog" class="detail-dialog" aria-labelledby="detail-title" @click="event => { if (event.target === dialog) closeDetail() }" @cancel="++detailRequest">
    <div class="dialog-top"><span class="eyebrow">REPOSITORY / 项目档案</span><button class="close" aria-label="关闭项目详情" @click="closeDetail">×</button></div>
    <div v-if="detailLoading" class="empty" role="status">正在加载项目详情…</div><div v-else-if="detailError" class="empty error" role="alert">{{ detailError }}</div>
    <template v-else-if="detail"><div class="detail-header"><h2 id="detail-title">{{ detail.full_name }}</h2><p>{{ (isTrending && detail.description_zh) || detail.description }}</p><a :href="'https://github.com/' + detail.full_name" target="_blank" rel="noopener noreferrer" class="github-link">在 GitHub 查看 ↗</a><div class="detail-badges"><span>{{ detail.language || '未识别语言' }}</span><span>{{ detail.license || '未标注许可证' }}</span><span>☆ {{ number(detail.stars) }} Stars（{{ (detail.date || date) + ' 快照' }}）</span><span v-if="isTrending">{{ translationLabels[detail.translation_status] }}</span></div><p class="snapshot-time">快照采集于 {{ time(detail.fetched_at) }}</p><p v-if="detail.details_origin === 'legacy_backfill'" class="snapshot-warning" role="note">旧数据回填：此项目的元数据与 README 来自迁移时的最新版本，并非 {{ detail.date || date }} 当日实况。不能据此还原该日内容。</p><dl class="dates-grid"><div v-for="[key, label] in [['created_at','项目创建'],['updated_at','项目更新'],['pushed_at','最近推送'],['first_fetched_at','首次采集'],['last_fetched_at','最近采集']]" :key="key"><dt>{{ label }}</dt><dd>{{ time(detail[key]) }}</dd></div></dl></div><div class="readme-bar"><h3>README<span>.md</span></h3><div v-if="isTrending" class="toggle" aria-label="README 语言"><button :aria-pressed="readmeLanguage === 'zh'" :disabled="!detail.readme_zh" @click="readmeLanguage = 'zh'">中文</button><button :aria-pressed="readmeLanguage === 'original'" @click="readmeLanguage = 'original'">原文</button></div></div><p v-if="isTrending && (detail.translation_stale || detail.translation_error)" class="translation-notice">{{ detail.translation_stale ? '中文译文可能落后于最新原文。' : '' }}{{ detail.translation_error }}</p><article v-if="renderedReadme" class="markdown-body" v-html="renderedReadme"></article><div v-else class="empty">此项目暂未提供 README。</div></template>
  </dialog>
</template>
