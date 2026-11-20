import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const teamURL = 'http://127.0.0.1:8012'
const password = 'playwright-fixture-263!'

async function activate(page: Page, link: string, username: string, name: string) {
  await page.goto(link)
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('显示名称').fill(name)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '激活账号', exact: true }).click()
  await expect(page.getByRole('heading', { name: '项目知识问答' })).toBeVisible()
}

test('real team imports a document and turns a member report into a passing regression', async ({ page, browser }, info) => {
  const db = process.env.SCOPEBRIEF_E2E_TEAM_DB
  if (!db) throw new Error('Team test database is missing')
  const code = execFileSync('uv', ['run', '--frozen', 'python', '-m', 'scopebrief.admin', '--db', db, 'bootstrap'], {
    cwd: fileURLToPath(new URL('../../', import.meta.url)), encoding: 'utf8', timeout: 20_000,
  }).trim()
  await activate(page, teamURL + '/#invite=' + encodeURIComponent(code), 'team-lead', '团队管理员')
  await page.getByRole('button', { name: '团队管理', exact: true }).click()
  await page.getByRole('button', { name: '创建项目', exact: true }).click()
  const project = page.getByRole('dialog', { name: '创建项目' })
  await project.getByLabel('项目名称').fill('门店支持')
  await project.getByLabel('项目标识').fill('store-support')
  await project.getByLabel('描述').fill('统一设备售后服务口径')
  await project.getByRole('button', { name: '保存项目' }).click()
  await expect(page.getByRole('heading', { name: '门店支持', exact: true })).toBeVisible()
  await page.screenshot({ path: info.outputPath('team-admin.png'), animations: 'disabled' })

  await page.getByRole('button', { name: '项目资料', exact: true }).click()
  await page.getByRole('button', { name: '发布资料' }).click()
  const publish = page.getByRole('dialog', { name: '发布 Markdown 资料' })
  await publish.getByLabel('导入文件').setInputFiles({
    name: '设备保固规范.md', mimeType: 'text/markdown',
    buffer: Buffer.from('## 保固流程\n设备 GX-782 的保固期限为 90 天。'),
  })
  await expect(publish.getByLabel('标题')).toHaveValue('设备保固规范')
  await publish.getByLabel('文档键').fill('warranty')
  await publish.getByRole('button', { name: '确认发布' }).click()
  await expect(page.getByText('已发布 设备保固规范 · v1', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '团队管理', exact: true }).click()
  await page.getByRole('button', { name: '成员与邀请', exact: true }).click()
  await page.getByRole('button', { name: '邀请成员', exact: true }).click()
  const invite = page.getByRole('dialog', { name: '邀请成员' })
  await invite.getByLabel('邀请备注').fill('售后新人')
  await invite.getByLabel('门店支持权限').selectOption('reader')
  await invite.getByRole('button', { name: '生成邀请' }).click()
  const activation = page.getByRole('dialog', { name: '邀请码已生成' })
  const link = await activation.getByLabel('激活链接').inputValue()
  await activation.getByRole('button', { name: '完成' }).click()

  const member = await browser.newContext()
  try {
    const user = await member.newPage()
    await activate(user, link, 'support-user', '售后成员')
    await user.getByRole('button', { name: '项目资料', exact: true }).click()
    await expect(user.getByRole('button', { name: '设备保固规范', exact: true })).toBeVisible()
    await expect(user.getByRole('button', { name: '发布资料', exact: true })).toHaveCount(0)
    await expect(user.getByRole('button', { name: '团队管理', exact: true })).toHaveCount(0)
    await user.getByRole('button', { name: '评审问答', exact: true }).click()
    await user.getByLabel('查询团队知识').fill('设备 GX-782 的保固期限是什么？')
    await user.getByRole('button', { name: '查证', exact: true }).click()
    await expect(user.getByText('设备 GX-782 的保固期限为 90 天。', { exact: false })).toBeVisible()
    await user.getByRole('button', { name: '查看引用 1' }).click()
    await expect(user.getByRole('dialog').getByText('来源文件 · 设备保固规范.md')).toBeVisible()
    await user.keyboard.press('Escape')
    await user.getByRole('button', { name: '需复核', exact: true }).click()
    await user.getByLabel('复核说明').fill('把保固期限作为发布后的回归检查。')
    await user.getByRole('button', { name: '提交复核' }).click()
    await expect(user.getByText('已提交给管理员', { exact: true })).toBeVisible()
  } finally {
    await member.close()
  }

  await page.getByRole('button', { name: '业务回归', exact: true }).click()
  await expect(page.getByText('把保固期限作为发布后的回归检查。')).toBeVisible()
  await page.getByRole('button', { name: '转为用例' }).click()
  const editor = page.getByRole('dialog', { name: '新建回归用例' })
  await editor.getByRole('checkbox', { name: '设备保固规范' }).check()
  await editor.getByLabel('引文应包含的文本').fill('90 天')
  await editor.getByRole('button', { name: '保存用例' }).click()
  await page.getByRole('button', { name: '运行团队评测' }).click()
  await expect(page.getByRole('heading', { name: '通过 1 / 1' })).toBeVisible()
  await expect(page.getByText('store-support--warranty@1', { exact: true })).toBeVisible()
  await page.screenshot({ path: info.outputPath('team-regression.png'), animations: 'disabled' })

  await page.getByRole('button', { name: '项目资料', exact: true }).click()
  await page.getByRole('button', { name: '批量导入', exact: true }).click()
  const bulk = page.getByRole('dialog', { name: '批量导入资料' })
  await bulk.getByLabel('选择多个文件').setInputFiles([
    { name: 'escalation.md', mimeType: 'text/markdown', buffer: Buffer.from('## 服务升级\n工作日由售后支持处理。') },
    { name: 'unsupported.zip', mimeType: 'application/zip', buffer: Buffer.from('not a supported document') },
  ])
  await expect(bulk.getByText('待发布', { exact: true })).toBeVisible()
  await expect(bulk.getByText('请选择 Markdown、TXT、可复制文本的 PDF 或 DOCX。', { exact: true })).toBeVisible()
  await bulk.getByRole('button', { name: '发布可用资料', exact: true }).click()
  await expect(bulk.getByText('已发布 v1', { exact: true })).toBeVisible()
  await bulk.getByRole('button', { name: '关闭', exact: true }).last().click()
  await expect(page.getByRole('button', { name: 'escalation', exact: true })).toBeVisible()
})
