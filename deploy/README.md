# Macbook 部署清单（私有优先）

把家里的 Macbook 改造成"24h 在线 + 私网可访问"的交易工作台。

## 推荐方案（隐私优先）

目标：不把 OpenD 暴露到公网，同时支持手机访问。

### 架构

```
Macbook
      ├── Futu OpenD (127.0.0.1:11111，仅本机)
      └── Streamlit (0.0.0.0:8501)
                        ├── 本机:      http://127.0.0.1:8501
                        ├── 同 Wi-Fi:  http://<Mac_LAN_IP>:8501
                        └── Tailscale: http://<Mac_Tailscale_IP>:8501 (可选)
```

### 一键启动（本机私有）

```bash
cd ~/code/TradingStragety
bash scripts/start_private_access.sh
```

脚本会打印三类地址：本机地址、局域网地址、Tailscale 私网地址（若已安装）。

### 隐私边界

- 不要对 OpenD 端口 11111 做任何公网映射。
- 不使用 Pinggy / Cloudflare Quick Tunnel 代理 OpenD。
- 仅开放 8501 给局域网或 Tailscale 私网访问。

---

下面内容保留为“公网访问”方案，仅在你明确接受公网暴露风险时使用。

## 架构

```
公司 Windows ──git push──► GitHub ──git pull──► 家里 Macbook
                                                    │
                                                    ├── Futu OpenD (本机 11111)
                                                    ├── Streamlit (本机 8501)
                                                    └── cloudflared 隧道
                                                          │
                                                    Cloudflare 边缘
                                                          │
                                            手机 / 出差笔记本 (HTTPS)
```

## 一次性安装（Macbook 上执行）

> 全部命令在 Macbook 终端里跑。仓库假设克隆到 `~/code/TradingStragety`，路径不同请自行替换。

### 1. 基础依赖

```bash
# Homebrew（如已装跳过）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.13 cloudflared netcat

# 富途 OpenD Mac 版从富途官网下载安装包，无脚本化方式
```

### 2. 克隆仓库 + 装 Python 依赖

```bash
mkdir -p ~/code && cd ~/code
git clone <your-repo-url> TradingStragety
cd TradingStragety
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 防睡眠

> macOS 系统设置 → 电池 → 电源适配器 → 开启「合上盖子时防止自动睡眠」  
> 或在 launchd 启动命令前包一层 `caffeinate -dimsu`

外接电源 + 合盖不睡眠是最稳的；电池模式合盖一定会睡，没法绕过。

### 4. 注册 launchd 守护

```bash
REPO_ROOT="$HOME/code/TradingStragety"

# 替换 plist 里的占位符
sed "s|__REPO_ROOT__|$REPO_ROOT|g" \
  "$REPO_ROOT/deploy/com.trading.streamlit.plist" \
  > ~/Library/LaunchAgents/com.trading.streamlit.plist

# 加载并启动
launchctl load ~/Library/LaunchAgents/com.trading.streamlit.plist

# 验证
launchctl list | grep com.trading.streamlit
curl -I http://127.0.0.1:8501  # 期望 200
tail -f "$REPO_ROOT/deploy/logs/streamlit.log"
```

常用维护命令：

```bash
# 重启
launchctl unload ~/Library/LaunchAgents/com.trading.streamlit.plist
launchctl load   ~/Library/LaunchAgents/com.trading.streamlit.plist

# 完全卸载
launchctl unload ~/Library/LaunchAgents/com.trading.streamlit.plist
rm ~/Library/LaunchAgents/com.trading.streamlit.plist
```

### 5. 配置 Cloudflare Tunnel

#### 5.1 注册并登录

```bash
cloudflared tunnel login
# 浏览器弹出，登录 Cloudflare 账号并授权域名（没有域名先去 Cloudflare 注册一个，约 ¥60/年）
```

#### 5.2 创建 tunnel

```bash
cloudflared tunnel create trading
# 输出会包含 tunnel UUID 和凭证文件路径，记下 UUID
```

#### 5.3 写 config.yml

```bash
cp deploy/cloudflared/config.yml.example ~/.cloudflared/config.yml
# 编辑 ~/.cloudflared/config.yml：
#   - 把 __REPLACE_WITH_TUNNEL_UUID__ 改为上一步的 UUID
#   - 把 __YOUR_USERNAME__ 改为你的 Mac 用户名
#   - 把 trading.example.com 改为你的域名
```

#### 5.4 绑定 DNS

```bash
cloudflared tunnel route dns trading trading.example.com
```

#### 5.5 安装为系统服务

```bash
sudo cloudflared service install
# 这会创建并启动 launchd 服务，开机自启
```

验证：在手机 4G 网络下打开 `https://trading.example.com`，能看到 Streamlit 页面即成功。

### 6. 加访问控制（强烈建议）

公网暴露后任何人扫到域名就能进，必须加一层认证：

1. 打开 Cloudflare Dashboard → Zero Trust → Access → Applications → Add an application
2. 选 Self-hosted，Application domain 填 `trading.example.com`
3. Policy 选 Email → 只允许你的邮箱
4. 保存后，访问域名会先跳转到邮箱 OTP 验证页

完全免费，每月 50 用户额度，你一个人完全够用。

## 临时方案（不想买域名）

只想先试试，不买域名：

```bash
cd ~/code/TradingStragety
cloudflared tunnel --url http://127.0.0.1:8501
# 会输出一个 https://xxx-yyy-zzz.trycloudflare.com 临时 URL，关掉就失效，URL 每次重启都变
```

适合做技术验证，不适合长期用。

## 故障排查

| 现象 | 排查 |
|---|---|
| 域名打不开 | `cloudflared tunnel info trading` 看连接状态；`tail -f ~/.cloudflared/cloudflared.log` |
| 域名能开但 Streamlit 报错 | `tail -f deploy/logs/streamlit.log`；`curl -I http://127.0.0.1:8501` 在 Mac 本机能不能通 |
| 账户/行情显示「OpenD 未连接」 | Macbook 上手动打开 Futu OpenD GUI 登录富途账号，确认 11111 端口监听 |
| Streamlit 反复重启 | `tail -f deploy/logs/launchd.err.log` |
| 合盖后断连 | 系统设置确认「防止自动睡眠」开启；外接电源 |

## 日常开发流程（公司 Windows）

部署完成后，公司端开发不变：

```powershell
# Windows 上正常开发、commit、push
git add -A
git commit -m "..."
git push origin <branch>
```

Macbook 上拉新代码 + 重启服务：

```bash
cd ~/code/TradingStragety
git pull
launchctl unload ~/Library/LaunchAgents/com.trading.streamlit.plist
launchctl load   ~/Library/LaunchAgents/com.trading.streamlit.plist
```

后续可以做一个 webhook 触发的自动 pull + reload，但先用这个手动版本跑通。

## 数据架构说明

`.gitignore` 已经排除了 `data/*.csv|*.json|*.db`，所以：

- **代码** 通过 git 同步（Windows ↔ GitHub ↔ Macbook）
- **数据**（持仓、回测历史、复盘记录、账户快照）**只在 Macbook 上**
- 公司想看真实数据 → 通过 Cloudflare Tunnel 访问 Macbook 的页面
- 公司想用真实数据开发 → 手动从 Macbook scp 一份 data/ 过来

这是有意为之：Macbook 是唯一生产数据源，避免多端写入冲突。
