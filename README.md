# 干完了——现场服务 AI 交付系统

`ganwanle-miniapp` 是基于 Taro + React + TypeScript + SCSS 的现场服务交付微信小程序，后端使用 FastAPI。当前包含师傅作业、AI 报告和客户现场签名验收闭环，并保留 Taro H5 构建入口。

## 当前范围

当前已实现：

- 微信登录、师傅资料和按用户隔离的服务单数据
- 真实服务单创建、施工前后照片上传和录音上传
- 腾讯云语音识别、阿里云百炼 AI 服务报告生成与编辑
- 报告提交、客户现场手写签名和验收状态持久化
- 客户验收单微信聊天转发、免师傅登录查看和远程签名验收
- 访问令牌刷新、私有文件短时授权和关键操作审计

当前不包含支付或 PDF 导出能力。公网 staging 环境使用 SQLite 和服务器本地私有存储；正式生产环境应切换到 PostgreSQL、Redis 和私有 COS。

## 安装与运行

```bash
npm install
npm run dev:weapp
```

后端安装、启动、API 地址、微信域名校验和真机调试说明见 [server/README.md](server/README.md)。先启动 `127.0.0.1:8001` 后端，再启动小程序开发构建。

打开微信开发者工具，选择“导入项目”，项目目录选择本仓库根目录（包含 `project.config.json` 的 `ganwanle-miniapp` 文件夹）。开发工具会读取 `dist/` 作为小程序目录。无正式 AppID 时可使用测试号或游客模式。

微信小程序产物输出到 `dist/`，H5 产物输出到 `dist-h5/`，两种构建不会互相覆盖。

生产构建检查：

```bash
npm run test:unit
npm run build:weapp
```

后端回归测试：

```powershell
server/.venv/Scripts/python.exe -m pytest -q --basetemp C:\gwtest-tmp
```

Windows 默认 pytest 临时目录可能因签名和录音对象路径较长而触发路径长度限制，因此测试命令显式使用短临时目录。

## 目录

- `src/pages`：登录、工作台、现场采集、报告和客户验收页面
- `src/components`：步骤进度、照片上传、服务单摘要等公共组件
- `src/context`：登录状态和当前交付流程状态
- `src/services`：认证、服务单、上传和验收 API
- `src/mock`：仅用于缺省展示和开发辅助的数据
- `server`：FastAPI、数据库迁移、认证、存储、语音和 AI 服务
- `src/styles`：统一颜色、间距、圆角、字号与全局样式
- `config`：Taro 多端构建配置
