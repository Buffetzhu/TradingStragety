# Streamlit Cloud 部署指南

本项目支持免费部署到 **Streamlit Cloud**，无需任何成本。

## 前置条件

- GitHub 账号
- Streamlit 账号（用 GitHub 账号注册）
- 代码已推送到 GitHub

## 部署步骤

### 1. 登录 Streamlit Cloud

访问 [share.streamlit.io](https://share.streamlit.io)，用 GitHub 账号登录。

### 2. 创建新应用

点击 **"New app"** 按钮，填写以下信息：

| 字段 | 值 |
|------|-----|
| Repository | `Buffetzhu/TradingStragety` |
| Branch | `v0.6-page-diet` |
| Main file path | `app.py` |

### 3. 部署完成

点击 "Deploy"，等待 1-2 分钟，自动获得公网 URL。

**示例 URL**: `https://your-app.streamlit.app`

## 使用说明

### 演示模式（推荐）

- 无需配置，直接使用缓存数据
- 支持所有回测功能
- 完全免费，24/7 在线

### 真实行情模式

需要配置 OpenD 服务器地址：

1. 打开应用 → 左侧边栏 → 找到 "📡 数据接入"
2. 选择 "富途真实行情"
3. 填入 OpenD 服务器 IP 和端口（默认 `127.0.0.1:11111`）
4. 点 "测试 OpenD 连接" 验证

**注意**：
- 云端 Streamlit 无法直接访问你本机的 OpenD
- 需要 OpenD 部署在公网服务器或使用隧道（如 Tailscale）
- 或者使用隧道暴露本机 OpenD 端口

## 生产环境优化

### 1. 自定义域名（可选）

在 Streamlit Cloud 的 App settings 中，可以绑定自定义域名。

### 2. 性能优化

如果应用响应缓慢，可以：

```bash
# 清理缓存
rm -rf ~/.streamlit/cache_dir
```

### 3. 敏感信息管理

对于需要保存的敏感信息（如 API 密钥），使用 Streamlit secrets：

1. 在 Streamlit Cloud App settings 中点击 "Secrets"
2. 添加键值对，如：
   ```
   opend_default_host = "your.server.ip"
   opend_default_port = "11111"
   ```
3. 在 app.py 中访问：
   ```python
   import streamlit as st
   host = st.secrets.get("opend_default_host", "127.0.0.1")
   ```

## 故障排查

### 应用启动缓慢

- Streamlit Cloud 的免费层有资源限制
- 首次加载较慢是正常的
- 后续使用会更快（缓存）

### 无法连接 OpenD

- 确认 OpenD 服务在线
- 确认地址和端口正确
- 如果是本机 OpenD，需要使用隧道暴露（Tailscale/Pinggy/Cloudflare）

### 数据源读取失败

- 检查缓存数据是否存在于 `data/cache/` 目录
- 在演示模式下可以正常使用而不依赖 OpenD

## 更新应用

代码更新会自动部署到 Streamlit Cloud：

```bash
# 提交代码到 GitHub
git push origin v0.6-page-diet

# 2-3 分钟后自动部署
```

## 本地开发与部署对比

| 特性 | 本地 + 隧道 | Streamlit Cloud |
|------|------------|-----------------|
| 成本 | 免费 | 免费 |
| 可用性 | 依赖主机在线 | 24/7 在线 |
| 更新 | 手动部署 | 自动部署 |
| 真实行情 | ✓ 支持 | 需要配置 |
| 演示模式 | ✓ 支持 | ✓ 支持 |

## 问题反馈

如有问题，请提交 Issue 或 PR：https://github.com/Buffetzhu/TradingStragety/issues
