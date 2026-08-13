import '@swc/register'
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

  it('uses the canonical www API URL when the build process has not preset NODE_ENV', async () => {
    delete process.env.NODE_ENV
    delete process.env.TARO_APP_API_BASE_URL

    const config = await resolveConfig()

    expect(config.defineConstants?.__GANWANLE_API_BASE_URL__)
      .toBe(JSON.stringify('https://www.weiyuantool.com/ganwanle-api'))
  })

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
})
