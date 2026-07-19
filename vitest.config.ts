import { defineConfig } from 'vitest/config'

export default defineConfig({
  define: {
    __GANWANLE_API_BASE_URL__: JSON.stringify('http://localhost:8000')
  },
  test: {
    environment: 'node',
    clearMocks: true
  }
})
