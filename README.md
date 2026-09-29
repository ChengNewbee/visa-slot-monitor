# 北京 B1/B2 免费放号提醒器

读取 VisaBida 首页无需登录的公开摘要，监控北京 `B1/B2 / 普通面谈`。它不会登录美签官网，也不保存 CGI 账号、密码、密保、DS-160 或护照信息。

## 已配置目标

- 城市：北京
- 类型：B1/B2
- 类别：普通面谈（不是免面谈或紧急申请）
- 日期：从运行当天至 2026-11-30
- 排除：“官方紧急申请－不是普通号”
- 推送：ntfy、QQ 邮件、macOS 本地通知

## 安全说明

`.env` 已被 `.gitignore` 排除，不会上传到 GitHub。QQ 邮箱必须使用 SMTP 授权码，不要填 QQ 登录密码。

## 1. 手机推送

1. 在 iPhone 或 Android 安装 [ntfy](https://ntfy.sh/)。
2. 订阅 `.env` 中 `VISA_NTFY_TOPIC` 对应的私密 topic。
3. topic 相当于推送密码，不要公开。

## 2. QQ 邮件

1. 进入 QQ 邮箱网页版的“设置 → 账户与安全”。
2. 开启 `POP3/SMTP` 或 `IMAP/SMTP`。
3. 生成 SMTP 授权码。
4. 将授权码填入 `.env` 的 `VISA_SMTP_PASSWORD=` 后面。

## 3. 本地测试

```bash
cd /Users/iggchengsiyuan/Documents/Codex/2026-08-11/new-chat/visa_slot_monitor
zsh scripts/install_local.sh
python3.11 monitor.py --test-notify
python3.11 monitor.py --once
```

`install_local.sh` 会安装一个 `launchd` 任务，登录 Mac 后每约 60 秒检查一次。`caffeinate -s` 只在接通电源时防止空闲休眠；合盖、关机或电池供电下进入睡眠后会停止，云端任务负责兜底。

查看状态：

```bash
launchctl print gui/$(id -u)/com.csy.visa-slot-monitor | grep -E 'state|pid'
tail -f watch.log
tail -f watch.err.log
```

停止本地监控：

```bash
zsh scripts/uninstall_local.sh
```

## 4. GitHub Actions 24 小时备用

仓库中已包含 `.github/workflows/monitor.yml`，每约 5 分钟检查一次。建议建立一个公开 GitHub 仓库，以避免私有仓库 Actions 免费时长不足。代码中不包含密钥。

在仓库 `Settings → Secrets and variables → Actions` 创建：

| Secret | 值 |
|---|---|
| `VISA_NTFY_TOPIC` | `.env` 中的私密 topic |
| `VISA_EMAIL_TO` | 接收提醒的 QQ 邮箱 |
| `VISA_SMTP_USER` | 发件 QQ 邮箱 |
| `VISA_SMTP_PASSWORD` | QQ SMTP 授权码 |

不要把授权码写入代码、`.env.example` 或 Git 提交。

## 局限

- 数据源只公开每个领馆的“最早可约日期”和可约日期数量，并不是官方名额数。只要最早日期进入目标区间，就会提醒。
- 第三方没有观测到的号源，本程序也无法发现；公开摘要可能延迟，收到提醒不代表官网仍可预约。
- VisaBida 页面改版、限流或观测超过 24 小时时，程序会报警并继续重试，不会把旧数据当成新号。
- GitHub 定时任务可能有5–15分钟的调度延迟。
- 这是只读提醒器，不会自动预约，也无法解决 `SE0504`。
