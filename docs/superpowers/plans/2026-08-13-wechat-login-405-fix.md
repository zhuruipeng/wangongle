# 微信登录 405 修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让生产小程序直接以 `POST` 请求规范的带 `www` 微信登录地址，消除 301 将请求方法改成 `GET` 后产生的 405。

**Architecture:** Taro 配置继续集中生成 `__GANWANLE_API_BASE_URL__`；生产环境无显式覆盖时使用 `https://www.weiyuantool.com/ganwanle-api`，开发环境仍使用本地服务，`TARO_APP_API_BASE_URL` 保持最高优先级。后端认证路由保持只接受 `POST`。

**Tech Stack:** Taro 4.1.5、TypeScript 5.7、Vitest 4、微信小程序构建、FastAPI 公网接口

## Global Constraints

- 微信登录接口 `/api/v1/auth/wechat` 必须继续只接受 `POST`。
- 生产默认 API 基地址必须为 `https://www.weiyuantool.com/ganwanle-api`。
- `TARO_APP_API_BASE_URL` 必须仍可覆盖默认地址。
- 开发默认 API 基地址必须继续为 `http://127.0.0.1:8001`。
- 不修改 Nginx 全站重定向，不新增后端 `GET` 登录路由。

---

### Task 1: 用配置回归测试固定规范生产地址

**Files:**
- Create: `config/index.test.ts`
- Modify: `config/index.ts:14-17`

**Interfaces:**
- Consumes: Taro 配置工厂默认导出、`NODE_ENV`、`TARO_APP_API_BASE_URL`。
- Produces: `defineConstants.__GANWANLE_API_BASE_URL__`，值是 JSON 字符串形式的最终 API 基地址。

- [ ] **Step 1: 写生产默认地址失败测试**

创建 `config/index.test.ts`，通过真实配置工厂解析配置，不模拟配置实现：

```ts
import { afterEach, describe, expect, it } from 'vitest'
import configExport from './index'

type ResolvedConfig = {
  defineConstants?: Record<string, string>
}

const originalNodeEnv = process.env.NODE_ENV
const originalApiBaseUrl = process.env.TARO_APP_API_BASE_URL

async function resolveConfig(): Promise<ResolvedConfig> {
  if (typeof configExport !== 'function') return configExport as ResolvedConfig
  const merge = (...configs: Array<object | null | undefined>) => Object.assign({}, ...configs) as ResolvedConfig
  return configExport(merge, { command: 'build', mode: 'production' }) as Promise<ResolvedConfig>
}

afterEach(() => {
  if (originalNodeEnv === undefined) delete process.env.NODE_ENV
  else process.env.NODE_ENV = originalNodeEnv
  if (originalApiBaseUrl === undefined) delete process.env.TARO_APP_API_BASE_URL
  else process.env.TARO_APP_API_BASE_URL = originalApiBaseUrl
})

describe.sequential('Taro API base URL configuration', () => {
  it('uses the canonical www API URL by default in production', async () => {
    process.env.NODE_ENV = 'production'
    delete process.env.TARO_APP_API_BASE_URL

    const config = await resolveConfig()

    expect(config.defineConstants?.__GANWANLE_API_BASE_URL__)
      .toBe(JSON.stringify('https://www.weiyuantool.com/ganwanle-api'))
  })
})
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `npx vitest run config/index.test.ts`

Expected: FAIL；实际值为 `"http://127.0.0.1:8001"`，不是规范生产地址。

- [ ] **Step 3: 增加覆盖地址和开发地址测试**

在同一个 `describe.sequential` 中增加：

```ts
it('keeps an explicit API URL override in production', async () => {
  process.env.NODE_ENV = 'production'
  process.env.TARO_APP_API_BASE_URL = 'https://staging.example.test/api'

  const config = await resolveConfig()

  expect(config.defineConstants?.__GANWANLE_API_BASE_URL__)
    .toBe(JSON.stringify('https://staging.example.test/api'))
})

it('keeps the local API URL by default in development', async () => {
  process.env.NODE_ENV = 'development'
  delete process.env.TARO_APP_API_BASE_URL

  const config = await resolveConfig()

  expect(config.defineConstants?.__GANWANLE_API_BASE_URL__)
    .toBe(JSON.stringify('http://127.0.0.1:8001'))
})
```

- [ ] **Step 4: 写最小配置修复**

将 `config/index.ts` 的 API 常量改为：

```ts
const defaultApiBaseUrl = process.env.NODE_ENV === 'production'
  ? 'https://www.weiyuantool.com/ganwanle-api'
  : 'http://127.0.0.1:8001'

const base: UserConfigExport<'webpack5'> = {
  // existing fields stay unchanged
  defineConstants: {
    __GANWANLE_API_BASE_URL__: JSON.stringify(process.env.TARO_APP_API_BASE_URL || defaultApiBaseUrl),
    __GANWANLE_DEV__: JSON.stringify(process.env.NODE_ENV !== 'production')
  }
}
```

- [ ] **Step 5: 运行配置测试并确认通过**

Run: `npx vitest run config/index.test.ts`

Expected: 3 tests PASS，0 failed。

- [ ] **Step 6: 运行现有登录会话测试**

Run: `npx vitest run src/services/session.test.ts`

Expected: 测试通过，其中 `posts the WeChat code...` 继续验证 `method: 'POST'` 和 `data: { code: 'wx-code' }`。

- [ ] **Step 7: 提交配置修复**

```bash
git add config/index.test.ts config/index.ts
git commit -m "fix: use canonical production API URL"
```

---

### Task 2: 重建并验证微信小程序产物

**Files:**
- Verify generated ignored artifact: `dist/common.js`
- Verify: `src/services/session.ts:45-74`
- Verify: `server/routers/auth.py:85-120`

**Interfaces:**
- Consumes: Task 1 生成的 `__GANWANLE_API_BASE_URL__` 和现有 `loginWithWechat(): Promise<SessionResponse>`。
- Produces: 微信开发者工具从 `dist/` 加载的生产小程序产物。

- [ ] **Step 1: 运行前端全量单元测试**

Run: `npm run test:unit`

Expected: 所有 Vitest 测试文件和测试用例通过，0 failed。

- [ ] **Step 2: 生成生产微信小程序产物**

Run: `npm run build:weapp`

Expected: Taro 编译完成，退出码 0，产物写入 `dist/`。

- [ ] **Step 3: 检查产物只包含规范生产地址**

Run:

```bash
rg -n 'https://www\.weiyuantool\.com/ganwanle-api' dist/common.js
if rg -n 'https://weiyuantool\.com/ganwanle-api' dist/common.js; then exit 1; fi
```

Expected: 第一条找到规范地址；第二条找不到旧的无 `www` 地址。

- [ ] **Step 4: 验证公网规范地址不重定向且接受 POST**

Run:

```bash
curl -sS -D - -o /tmp/ganwanle-login-verification.json \
  --max-time 15 \
  -X POST \
  -H 'content-type: application/json' \
  --data '{"code":"codex-verification-invalid"}' \
  'https://www.weiyuantool.com/ganwanle-api/api/v1/auth/wechat'
```

Expected: 首个响应不是 301/302/307/308，也不是 405；测试凭证进入后端后可返回 502 `微信登录失败`。

- [ ] **Step 5: 运行后端认证回归测试**

Run: `python3 -m pytest -q server/tests/test_auth.py`

Expected: 所有认证测试通过，0 failed。

- [ ] **Step 6: 检查最终差异和工作区**

Run:

```bash
git diff --check HEAD~1..HEAD
git status --short
git show --stat --oneline HEAD
```

Expected: 无空白错误；最新提交只包含 `config/index.ts` 和 `config/index.test.ts`；`dist/` 因现有忽略规则不出现在 Git 状态中。
