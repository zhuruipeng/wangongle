import Taro from '@tarojs/taro'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiRequest, downloadFile, publicApiRequest, publicDownloadFile, publicUploadFile, uploadFile } from './api'
import { clearSession, getAccessToken, refreshSession } from './session'

vi.mock('@tarojs/taro', () => ({
  default: {
    request: vi.fn(),
    downloadFile: vi.fn(),
    uploadFile: vi.fn(),
    reLaunch: vi.fn()
  }
}))

vi.mock('./session', () => ({
  clearSession: vi.fn(),
  getAccessToken: vi.fn(),
  refreshSession: vi.fn()
}))

describe('authenticated API transport', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getAccessToken).mockReturnValue('access-token')
    vi.mocked(refreshSession).mockResolvedValue({
      access_token: 'rotated-access',
      refresh_token: 'rotated-refresh',
      user: { id: 'user-1', technician_name: '王师傅', role: 'technician', profile_complete: true }
    })
  })

  it('sends the persisted access token as a Bearer header', async () => {
    vi.mocked(Taro.request).mockResolvedValueOnce({ statusCode: 200, data: { ok: true } } as never)

    await apiRequest('/api/v1/auth/me')

    expect(Taro.request).toHaveBeenCalledWith(expect.objectContaining({
      header: expect.objectContaining({ Authorization: 'Bearer access-token' })
    }))
  })

  it('refreshes one 401 and retries the original request exactly once', async () => {
    vi.mocked(Taro.request)
      .mockResolvedValueOnce({ statusCode: 401, data: { detail: 'expired' } } as never)
      .mockResolvedValueOnce({ statusCode: 200, data: { ok: true } } as never)
    vi.mocked(getAccessToken)
      .mockReturnValueOnce('expired-access')
      .mockReturnValueOnce('rotated-access')

    await expect(apiRequest('/api/v1/service-orders')).resolves.toEqual({ ok: true })

    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(Taro.request).toHaveBeenCalledTimes(2)
    expect(Taro.request).toHaveBeenLastCalledWith(expect.objectContaining({
      url: 'http://localhost:8000/api/v1/service-orders',
      header: expect.objectContaining({ Authorization: 'Bearer rotated-access' })
    }))
  })

  it('clears the session and reLaunches login after the retried request also returns 401', async () => {
    vi.mocked(Taro.request)
      .mockResolvedValueOnce({ statusCode: 401, data: { detail: 'expired' } } as never)
      .mockResolvedValueOnce({ statusCode: 401, data: { detail: 'invalid' } } as never)

    await expect(apiRequest('/api/v1/service-orders')).rejects.toThrow('invalid')

    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(Taro.request).toHaveBeenCalledTimes(2)
    expect(clearSession).toHaveBeenCalledTimes(1)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/pages/login/index' })
  })

  it('does not recursively refresh the login or refresh endpoints', async () => {
    vi.mocked(Taro.request).mockResolvedValue({ statusCode: 401, data: { detail: 'invalid' } } as never)

    await expect(apiRequest('/api/v1/auth/wechat', { method: 'POST' })).rejects.toThrow('invalid')
    await expect(apiRequest('/api/v1/auth/refresh', { method: 'POST' })).rejects.toThrow('invalid')

    expect(refreshSession).not.toHaveBeenCalled()
    expect(Taro.request).toHaveBeenCalledTimes(2)
  })

  it('adds Bearer auth to uploads and refreshes one 401 before retrying', async () => {
    vi.mocked(Taro.uploadFile)
      .mockResolvedValueOnce({ statusCode: 401, data: JSON.stringify({ detail: 'expired' }) } as never)
      .mockResolvedValueOnce({ statusCode: 200, data: JSON.stringify({ file_url: '/files/photo.jpg' }) } as never)
    vi.mocked(getAccessToken)
      .mockReturnValueOnce('expired-access')
      .mockReturnValueOnce('rotated-access')

    await expect(uploadFile('/api/v1/service-orders/order-1/photos', '/tmp/photo.jpg', { phase: 'before' }))
      .resolves.toEqual({ file_url: '/files/photo.jpg' })

    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(Taro.uploadFile).toHaveBeenCalledTimes(2)
    expect(Taro.uploadFile).toHaveBeenLastCalledWith(expect.objectContaining({
      header: { Authorization: 'Bearer rotated-access' },
      formData: { phase: 'before' }
    }))
  })

  it('keeps public customer requests independent from technician sessions', async () => {
    vi.mocked(Taro.request).mockResolvedValueOnce({ statusCode: 200, data: { id: 'order-1' } } as never)

    await publicApiRequest('/api/v1/service-orders/customer-share/token')

    expect(Taro.request).toHaveBeenCalledWith(expect.objectContaining({
      header: { 'content-type': 'application/json' }
    }))
    expect(refreshSession).not.toHaveBeenCalled()
  })

  it('downloads an authenticated PDF and refreshes one 401', async () => {
    vi.mocked(Taro.downloadFile)
      .mockResolvedValueOnce({ statusCode: 401, tempFilePath: '' } as never)
      .mockResolvedValueOnce({ statusCode: 200, tempFilePath: '/tmp/report.pdf' } as never)
    vi.mocked(getAccessToken)
      .mockReturnValueOnce('expired-access')
      .mockReturnValueOnce('rotated-access')

    await expect(downloadFile('/api/v1/service-orders/order-1/pdf')).resolves.toBe('/tmp/report.pdf')

    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(Taro.downloadFile).toHaveBeenCalledTimes(2)
    expect(Taro.downloadFile).toHaveBeenLastCalledWith(expect.objectContaining({
      header: { Authorization: 'Bearer rotated-access' },
      timeout: 60000
    }))
  })

  it('downloads a customer shared PDF without a Bearer header', async () => {
    vi.mocked(Taro.downloadFile).mockResolvedValueOnce({
      statusCode: 200,
      tempFilePath: '/tmp/shared-report.pdf'
    } as never)

    await expect(publicDownloadFile('/api/v1/service-orders/customer-share/token/pdf'))
      .resolves.toBe('/tmp/shared-report.pdf')

    expect(Taro.downloadFile).toHaveBeenCalledWith(expect.objectContaining({ header: {} }))
    expect(refreshSession).not.toHaveBeenCalled()
  })

  it('supports a custom multipart file field for signatures', async () => {
    vi.mocked(Taro.uploadFile).mockResolvedValueOnce({
      statusCode: 201,
      data: JSON.stringify({ status: 'accepted' })
    } as never)

    await uploadFile('/api/v1/service-orders/order-1/acceptance', '/tmp/signature.png', { accepted: 'true' }, 'signature')

    expect(Taro.uploadFile).toHaveBeenCalledWith(expect.objectContaining({
      name: 'signature',
      formData: { accepted: 'true' }
    }))
  })

  it('uploads a shared customer signature without a Bearer header', async () => {
    vi.mocked(Taro.uploadFile).mockResolvedValueOnce({
      statusCode: 201,
      data: JSON.stringify({ status: 'accepted' })
    } as never)

    await publicUploadFile(
      '/api/v1/service-orders/customer-share/token/acceptance',
      '/tmp/signature.png',
      { accepted: 'true' },
      'signature'
    )

    expect(Taro.uploadFile).toHaveBeenCalledWith(expect.objectContaining({
      header: {},
      name: 'signature'
    }))
    expect(refreshSession).not.toHaveBeenCalled()
  })

  it.each(['', '<html>unauthorized</html>'])('refreshes an upload when the first 401 body is non-JSON: %j', async unauthorizedBody => {
    vi.mocked(Taro.uploadFile)
      .mockResolvedValueOnce({ statusCode: 401, data: unauthorizedBody } as never)
      .mockResolvedValueOnce({ statusCode: 200, data: JSON.stringify({ file_url: '/files/photo.jpg' }) } as never)

    await expect(uploadFile('/api/v1/service-orders/order-1/photos', '/tmp/photo.jpg'))
      .resolves.toEqual({ file_url: '/files/photo.jpg' })

    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(Taro.uploadFile).toHaveBeenCalledTimes(2)
  })

  it('expires after a retried upload returns a non-JSON 401', async () => {
    vi.mocked(Taro.uploadFile)
      .mockResolvedValueOnce({ statusCode: 401, data: '' } as never)
      .mockResolvedValueOnce({ statusCode: 401, data: '<html>still unauthorized</html>' } as never)

    await expect(uploadFile('/api/v1/service-orders/order-1/photos', '/tmp/photo.jpg'))
      .rejects.toThrow('上传响应格式错误')

    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(Taro.uploadFile).toHaveBeenCalledTimes(2)
    expect(clearSession).toHaveBeenCalledTimes(1)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/pages/login/index' })
  })
})
