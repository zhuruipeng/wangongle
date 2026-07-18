# 干完了——现场服务 AI 交付系统

`ganwanle-miniapp` 是基于 Taro + React + TypeScript + SCSS 的师傅端现场交付可操作原型。当前以微信小程序为首要目标，并保留 Taro H5 构建入口，便于后续增加客户验收页和网页版后台。

## 当前范围

包含师傅端交付和客户验收页面。服务单、照片、录音及报告可保存到项目内的 FastAPI 本地开发服务；语音识别文字与 AI 报告内容仍为模拟数据，不包含登录、支付、PDF 或正式分享能力。

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
npm run build:weapp
```

## 目录

- `src/pages`：业务页面，未来可继续按端或业务拆分
- `src/components`：步骤进度、照片上传、服务单摘要等公共组件
- `src/context`：本次交付流程的轻量状态
- `src/mock`：模拟服务单及报告数据
- `src/styles`：统一颜色、间距、圆角、字号与全局样式
- `config`：Taro 多端构建配置
