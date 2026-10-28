// AST-guided inventory and rewrite. Run `inventory`, translate the catalog, then `apply`.
import ts from 'typescript'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const requireVue = createRequire(import.meta.resolve('vue'))
const { parse: parseSfc } = requireVue('@vue/compiler-sfc')
const requireSfc = createRequire(requireVue.resolve('@vue/compiler-sfc'))
const { baseParse, NodeTypes } = requireSfc('@vue/compiler-dom')
const base = path.resolve(root, '../../..')
const cjk = /[\u4e00-\u9fff]/u
const mode = process.argv[2] || 'inventory'
const catalogPath = path.join(base, 'web-literals.json')
const catalog = mode === 'apply' ? JSON.parse(fs.readFileSync(catalogPath, 'utf8')) : []
const bySource = new Map(catalog.map(x => [x.source, x]))
function entry(source) {
  if (bySource.has(source)) return bySource.get(source)
  if (mode === 'apply') throw new Error(`Missing translation: ${source}`)
  const item = { id: `W${String(catalog.length + 1).padStart(4, '0')}`, source }
  catalog.push(item); bySource.set(source, item); return item
}
function codeEdits(code, offset, edits) {
  const sourceFile = ts.createSourceFile('input.ts', code, ts.ScriptTarget.Latest, true)
  function visit(node) {
    let source, expressions = []
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) source = node.text
    else if (ts.isTemplateExpression(node)) {
      source = node.head.text
      node.templateSpans.forEach((span, i) => { source += `{${i}}` + span.literal.text; expressions.push(span.expression.getText(sourceFile)) })
    }
    if (source && cjk.test(source)) {
      // Wire values, object property names, and import paths are not labels.
      const p = node.parent
      if (ts.isPropertyAssignment(p) && (p.name === node || p.name.getText(sourceFile) === 'value')) return
      const item = entry(source)
      edits.push([offset + node.getStart(sourceFile), offset + node.end,
        expressions.length ? `tf('${item.id}', ${expressions.join(', ')})` : `t('${item.id}')`])
      return
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
}
function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => {
    if (['__tests__', 'demo', 'locales'].includes(e.name)) return []
    const p = path.join(dir, e.name)
    return e.isDirectory() ? walk(p) : /\.(vue|ts)$/.test(e.name) ? [p] : []
  })
}
for (const file of walk(path.join(root, 'src'))) {
  if (file.endsWith('i18n.ts')) continue
  let text = fs.readFileSync(file, 'utf8')
  const edits = []
  if (file.endsWith('.vue')) {
    const { descriptor } = parseSfc(text)
    const script = descriptor.scriptSetup || descriptor.script
    if (script) codeEdits(script.content, script.loc.start.offset, edits)
    if (descriptor.template) {
      const template = descriptor.template
      const tree = baseParse(template.content)
      function visit(node) {
        const offset = template.loc.start.offset
        if (node.type === NodeTypes.TEXT && cjk.test(node.content)) {
          const value = node.content.trim()
          const item = entry(value)
          const raw = node.loc.source
          const start = raw.indexOf(value)
          edits.push([offset + node.loc.start.offset + start, offset + node.loc.start.offset + start + value.length, `{{ t('${item.id}') }}`])
        }
        if (node.type === NodeTypes.ELEMENT) {
          for (const prop of node.props) {
            if (prop.type === NodeTypes.ATTRIBUTE && prop.value && cjk.test(prop.value.content)) {
              const item = entry(prop.value.content)
              edits.push([offset + prop.loc.start.offset, offset + prop.loc.end.offset, `:${prop.name}="t('${item.id}')"`])
            } else if (prop.type === NodeTypes.DIRECTIVE && prop.exp) {
              const lead = 'const x = '
              codeEdits(lead + prop.exp.content, offset + prop.exp.loc.start.offset - lead.length, edits)
            }
          }
        }
        if (node.type === NodeTypes.INTERPOLATION) {
          const lead = 'const x = '
          codeEdits(lead + node.content.content, offset + node.content.loc.start.offset - lead.length, edits)
        }
        node.children?.forEach(visit)
      }
      visit(tree)
    }
    if (mode === 'apply' && edits.length && script) {
      edits.push([script.loc.start.offset, script.loc.start.offset, "\nimport { t, tf } from '@/i18n'\n"])
    } else if (mode === 'apply' && edits.length) {
      edits.push([0, 0, "<script setup lang=\"ts\">\nimport { t, tf } from '@/i18n'\n</script>\n"])
    }
  } else {
    codeEdits(text, 0, edits)
    if (mode === 'apply' && edits.length) edits.push([0, 0, "import { t, tf } from '@/i18n'\n"])
  }
  if (mode === 'apply' && edits.length) {
    edits.sort((a, b) => b[0] - a[0])
    for (const [a,b,value] of edits) text = text.slice(0,a) + value + text.slice(b)
    fs.writeFileSync(file, text)
  }
}
if (mode !== 'apply') {
  fs.writeFileSync(catalogPath, JSON.stringify(catalog, null, 2))
  fs.writeFileSync(path.join(base, 'web-translate.txt'), catalog.map(x => `${x.id}\t${x.source}`).join('\n'))
}
console.log(mode, catalog.length)
