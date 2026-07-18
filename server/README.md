# 本地开发后端

该服务只用于 `ganwanle-miniapp` 本地开发，不包含身份认证、多租户或生产环境安全配置，不应直接部署到公网。

## 创建并启动虚拟环境（PowerShell）

在项目根目录执行：

```powershell
python -m venv server/.venv
server/.venv/Scripts/python.exe -m pip install -r server/requirements.txt
server/.venv/Scripts/python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8001 --reload
```

健康检查地址：`http://127.0.0.1:8001/api/health`，交互式接口文档：`http://127.0.0.1:8001/docs`。

## 腾讯云一句话识别

复制 `server/.env.example` 为 `server/.env`，并填写：

```dotenv
TENCENTCLOUD_SECRET_ID=腾讯云SecretId
TENCENTCLOUD_SECRET_KEY=腾讯云SecretKey
TENCENTCLOUD_REGION=ap-shanghai
TENCENT_ASR_ENGINE=16k_zh
TENCENT_ASR_ENABLED=true
```

密钥只由 Python 后端读取，不能写入小程序环境变量或前端源码。未填写密钥时后端仍可启动、录音仍可上传，识别接口会返回“语音服务尚未配置”。`server/.env` 已加入 `.gitignore`。

## 阿里云百炼服务报告整理

在 `server/.env` 中填写以下配置，API Key 只由 Python 后端读取：

```dotenv
DASHSCOPE_API_KEY=你的百炼APIKey
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.5-plus-2026-02-15
AI_REPORT_ENABLED=true
```

修改配置后重启后端。完成录音识别并确认文字后，在小程序点击“AI生成报告”即可进行一次真实测试。请求使用 JSON Mode、低温度和非思考模式；未设置 API Key 时后端仍可正常启动，生成接口会返回“AI报告服务尚未配置”，师傅可以转为手工填写。

不要把 `DASHSCOPE_API_KEY` 写入前端环境变量、源码、日志或错误响应。本地接口没有登录和权限控制，不可直接部署到公网。

## 客户验收链接与 H5

本地验收链接配置放在 `server/.env`：

```dotenv
PUBLIC_H5_BASE_URL=http://127.0.0.1:10086/customer-acceptance
ACCEPTANCE_LINK_EXPIRES_DAYS=7
```

启动 H5 开发服务：

```powershell
$env:TARO_APP_API_BASE_URL='http://127.0.0.1:8001'
npm.cmd run dev:h5
```

H5 使用浏览器路由，客户验收入口为 `http://127.0.0.1:10086/customer-acceptance`。师傅端生成的链接会自动附带一次原始 Token；页面读取后立即从地址栏移除，并通过 `Authorization: Bearer` 调用公开接口。数据库只保存 Token 的 SHA-256 摘要。

如果要在同一局域网的手机微信中测试，请同时完成以下修改：

1. 将 `PUBLIC_H5_BASE_URL` 改为电脑局域网地址，例如 `http://192.168.1.20:10086/customer-acceptance`。
2. 将 `TARO_APP_API_BASE_URL` 改为 `http://192.168.1.20:8001` 后重新启动 H5 和小程序构建。
3. 后端使用 `--host 0.0.0.0` 启动。
4. 将 `http://192.168.1.20:10086` 加入 `GANWANLE_CORS_ORIGINS`。
5. 确认 Windows 防火墙允许本地测试端口 `8001` 和 `10086`。

签名 PNG 保存到 `server/uploads/signatures/`，验收报告和照片快照保存在 SQLite 数据库。快照 SHA-256 仅用于检测内容是否变化，不代表司法或第三方电子存证。本地接口没有用户登录和权限控制，不得作为正式公网服务部署。

SQLite 数据库位于 `server/data/ganwanle.db`，上传文件位于 `server/uploads/`。二者均已加入 `.gitignore`。

## 前端 API 地址

默认地址为 `http://127.0.0.1:8001`。也可在启动构建前设置环境变量：

```powershell
$env:TARO_APP_API_BASE_URL='http://127.0.0.1:8001'
npm run dev:weapp
```

微信开发者工具本地调试时，在“详情 → 本地设置”中勾选“不校验合法域名、web-view（业务域名）、TLS版本以及HTTPS证书”。该选项仅用于本地调试。

真机无法通过 `127.0.0.1` 访问电脑，请将 API 地址改为电脑的局域网 IP，例如 `http://192.168.1.20:8001`，同时用 `--host 0.0.0.0` 启动服务并仅在可信局域网中测试。正式环境后续必须使用 HTTPS、认证和严格 CORS。
