import { defineConfig, type UserConfigExport } from '@tarojs/cli'

export default defineConfig<'webpack5'>(async (merge) => {
  const base: UserConfigExport<'webpack5'> = {
    projectName: 'ganwanle-miniapp',
    date: '2026-07-18',
    designWidth: 750,
    deviceRatio: { 750: 1 },
    sourceRoot: 'src',
    // Keep H5 artifacts separate so they never overwrite the WeChat app.json.
    outputRoot: process.env.TARO_ENV === 'h5' ? 'dist-h5' : 'dist',
    framework: 'react',
    compiler: 'webpack5',
    defineConstants: {
      __GANWANLE_API_BASE_URL__: JSON.stringify(process.env.TARO_APP_API_BASE_URL || 'http://127.0.0.1:8001'),
      __GANWANLE_DEV__: JSON.stringify(process.env.NODE_ENV !== 'production')
    },
    cache: { enable: false },
    mini: { postcss: { pxtransform: { enable: true }, url: { enable: true, config: { limit: 1024 } }, cssModules: { enable: false } } },
    h5: {
      publicPath: '/',
      staticDirectory: 'static',
      router: {
        mode: 'browser',
        customRoutes: { 'pages/customer-acceptance/index': 'customer-acceptance' }
      },
      devServer: { host: '0.0.0.0', port: 10086, historyApiFallback: true },
      htmlPluginOption: { meta: { robots: 'noindex,nofollow,noarchive' } }
    }
  }
  if (process.env.NODE_ENV === 'development') return merge({}, base, require('./dev').default)
  return merge({}, base, require('./prod').default)
})
