import MarkdownIt from 'markdown-it'
import createDOMPurify from 'dompurify'

const markdown = new MarkdownIt({ html: true, linkify: true })
export function renderMarkdown(source, repo, window = globalThis.window) {
  const clean = createDOMPurify(window).sanitize(markdown.render(source || ''), { USE_PROFILES: { html: true }, FORBID_TAGS: ['style', 'form', 'input', 'button'], FORBID_ATTR: ['style', 'srcset'] })
  const document = new window.DOMParser().parseFromString(clean, 'text/html')
  const name = repo.full_name.split('/').map(encodeURIComponent).join('/')
  const branch = encodeURIComponent(repo.default_branch || 'main')
  const path = (repo.readme_path || 'README.md').split('/').map(encodeURIComponent).join('/')
  for (const node of document.querySelectorAll('a[href],img[src]')) {
    const attr = node.tagName === 'A' ? 'href' : 'src'
    const value = node.getAttribute(attr).trim()
    const base = attr === 'href' ? `https://github.com/${name}/blob/${branch}/` : `https://raw.githubusercontent.com/${name}/${branch}/`
    try {
      const relative = !/^[a-z][a-z\d+.-]*:|^\/\//i.test(value)
      const url = relative ? new URL(value.replace(/^\//, ''), value.startsWith('/') ? base : base + path) : new URL(value, base)
      if (!['https:', 'http:', ...(attr === 'href' ? ['mailto:'] : [])].includes(url.protocol)) { node.removeAttribute(attr); continue }
      node.setAttribute(attr, url.href)
      if (attr === 'href') { node.setAttribute('target', '_blank'); node.setAttribute('rel', 'noopener noreferrer') }
      else { node.setAttribute('loading', 'lazy'); node.setAttribute('referrerpolicy', 'no-referrer') }
    } catch { node.removeAttribute(attr) }
  }
  return document.body.innerHTML
}
