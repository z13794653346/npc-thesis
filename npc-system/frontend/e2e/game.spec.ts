import { expect, test, type Page } from '@playwright/test'

let browserErrors: string[] = []

async function borrowKey(page: Page) {
  await page.getByRole('button', { name: '帮店主核对大厅登记数量' }).click()
  await page.getByRole('button', { name: '帮店主把防汛沙袋移到门口' }).click()
  await page.getByRole('button', { name: /^确认承诺/ }).click()
  await page.getByRole('button', { name: /^请求借用备用钥匙/ }).click()
  await expect(page.getByRole('region', { name: '背包', exact: true })).toContainText('东翼备用钥匙')
}

test.beforeEach(async ({ page }) => {
  browserErrors = []
  page.on('pageerror', error => browserErrors.push(error.message))
  await page.goto('/')
  await expect(page.getByRole('button', { name: '选择林掌柜' })).toBeVisible()
})

test.afterEach(() => { expect(browserErrors).toEqual([]) })

test('complete a rule-driven story and restore the same saved session', async ({ page }) => {
  await borrowKey(page)
  await page.getByRole('button', { name: '选择周衡' }).click()
  await page.getByRole('button', { name: '与维修员修复配电箱' }).click()
  await page.getByRole('button', { name: '选择林掌柜' }).click()
  await page.getByRole('button', { name: '归还备用钥匙', exact: true }).click()
  await expect(page.getByRole('button', { name: '选择林掌柜' })).toContainText('70')
  await expect(page.getByRole('region', { name: '承诺', exact: true })).toContainText('已守约')
  for (const name of ['林掌柜', '周衡', '沈岚']) {
    await page.getByRole('button', { name: `选择${name}` }).click()
    await page.getByRole('button', { name: '询问并记录线索', exact: true }).click()
  }
  await page.getByRole('button', { name: '整理三条线索，完成调查' }).click()
  await expect(page.getByRole('region', { name: '调查结果' })).toContainText('调查完成')
  const saved = await page.evaluate(() => localStorage.getItem('npc-session-id'))
  await page.reload()
  await expect(page.getByRole('region', { name: '调查结果' })).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('npc-session-id'))).toBe(saved)
  await page.screenshot({ path: '../output/playwright/desktop-rules-complete.png', fullPage: true })
})

test('uninformed owner only loses trust after explicit verified notification', async ({ page }) => {
  await borrowKey(page)
  await page.getByRole('button', { name: '选择周衡' }).click()
  await page.getByRole('button', { name: '与维修员修复配电箱' }).click()
  await page.getByRole('button', { name: '询问并记录线索', exact: true }).click()
  await expect(page.getByRole('region', { name: '承诺', exact: true })).toContainText('已失信')
  await expect(page.getByRole('button', { name: '选择林掌柜' })).toContainText('60')
  await page.getByRole('button', { name: '选择林掌柜' }).click()
  await page.getByRole('button', { name: /^告知：维修后约定的归还期限/ }).click()
  await expect(page.getByRole('button', { name: '选择林掌柜' })).toContainText('45')
  await expect(page.getByRole('button', { name: /^告知：维修后约定的归还期限/ })).toHaveCount(0)
})

test('directed clue sharing and role-specific conversation are visible', async ({ page }) => {
  await page.getByRole('button', { name: '选择沈岚' }).click()
  await page.getByRole('button', { name: '询问并记录线索', exact: true }).click()
  await page.getByRole('button', { name: '选择林掌柜' }).click()
  await expect(page.getByRole('log')).not.toContainText('获得线索')
  await page.getByRole('button', { name: '转述线索：雨衣上的姓名' }).click()
  await expect(page.getByRole('log')).toContainText('已定向转述')
  await expect(page.getByRole('button', { name: '转述线索：雨衣上的姓名' })).toHaveCount(0)
})

test('missing real key is explicit and mobile view has no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByText('尚未配置真实模型：', { exact: false })).toBeVisible()
  await page.getByRole('textbox', { name: '输入消息' }).fill('你记得我吗？')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('尚未配置 DeepSeek API 密钥')
  await expect(page.getByRole('button', { name: /开发调试/ })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../output/playwright/mobile-no-key.png', fullPage: true })
})
