import test from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
import { renderMarkdown } from '../src/markdown.js'

const window = new JSDOM('').window
const repo = { full_name: 'owner/repo', default_branch: 'main', readme_path: 'docs/README.md' }
function render(source) { return new JSDOM(renderMarkdown(source, repo, window)).window.document.body }
test('removes executable HTML, event handlers and dangerous links', () => {
  const body = render('<script>alert(1)</script><img src="x" onerror="alert(1)"><a href="javascript:alert(1)">bad</a><iframe src="https://evil.test"></iframe>')
  assert.equal(body.querySelector('script,iframe,[onerror],a[href^="javascript:"]'), null)
})
test('resolves relative links and images against the README location', () => {
  const body = render('[Guide](../guide.md) ![Diagram](images/map.png)')
  assert.equal(body.querySelector('a').href, 'https://github.com/owner/repo/blob/main/guide.md')
  assert.equal(body.querySelector('img').src, 'https://raw.githubusercontent.com/owner/repo/main/docs/images/map.png')
  assert.equal(body.querySelector('a').rel, 'noopener noreferrer')
})
test('resolves anchors, HTML images, root paths and branch names safely', () => {
  const body = new JSDOM(renderMarkdown('[Top](#top) [Root](/LICENSE)<img src="./a.png"><a href="data:text/html,evil">bad</a>', {...repo, default_branch:'release/v1'}, window)).window.document.body
  assert.equal(body.querySelector('a').href, 'https://github.com/owner/repo/blob/release%2Fv1/docs/README.md#top')
  assert.match(body.querySelectorAll('a')[1].href, /blob\/release%2Fv1\/LICENSE$/)
  assert.match(body.querySelector('img').src, /release%2Fv1\/docs\/a.png$/)
  assert.equal(body.querySelector('a[href^="data:"]'), null)
})
test('opens README section links safely at the original GitHub document', () => {
  const body = new JSDOM(renderMarkdown('[Section](#heading)', {full_name:'o/r', default_branch:'main', readme_path:'README.md'}, window)).window.document.body
  const link = body.querySelector('a')
  assert.equal(link.href, 'https://github.com/o/r/blob/main/README.md#heading')
  assert.equal(link.target, '_blank')
  assert.equal(link.rel, 'noopener noreferrer')
})
