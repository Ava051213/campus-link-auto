# campus-link-auto

深大 eportal 校园网自动登录保活。

## 用法

```bash
python campus_link.py           # 首次会问账号密码，之后常驻保活
python campus_link.py --setup   # 改账号密码
python campus_link.py --once    # 只跑一轮，退出码 0 成功 / 1 失败
python campus_link.py -i 30 -v  # 30 秒一轮，带调试日志
```

后台常驻（不弹黑框）：把启动命令换成 `pythonw campus_link.py`，或用计划任务每分钟跑一次 `python campus_link.py --once`。

## 开机自启（已配置）

Windows 登录时自动拉起，无窗口、无黑框。

- 启动器：`start-silent.vbs`（项目根目录，双击即可立即启动）
- 自启位置：`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\campus-link-auto.vbs`
- 解释器：`D:\New_Folder\anaconda3\pythonw.exe`（Anaconda 自带，换 Python 时改这两个 vbs 里的路径）
- 取消自启：删掉启动文件夹里那个 `campus-link-auto.vbs`
- 确认在跑：任务管理器看有没有 `pythonw.exe`，或看 `campus_link.log` 最新时间戳

内置单实例保护（占用本地端口 49731），重复启动会被拒绝，不会出现两个进程同时登录。

## 掉线与唤醒恢复

- 开机或唤醒后 Wi-Fi 通常要几秒才就绪。探测失败会从 15 秒起快速重试，按 15 → 30 → 60 退避，网络一通立刻登录，不用等到下一分钟。
- 15 秒这个下限是实测出来的：网关对同一 IP 的连续认证有限流，5 秒一档约一半请求被 503 打回，15 秒一档稳定通过。
- 密码错误、欠费这类硬失败不快速重试，保持正常间隔，避免反复撞网关把账号锁了。
- 系统休眠唤醒后（睡眠期间墙钟跳变）立即重连一轮，不必等当前间隔走完。

## 外出时会自动待机

不在宿舍区的时候不需要认证，脚本会自己判断并停下来，不会反复重试刷日志：

- 网关 TCP 连不上 → 判定不在校园网
- 网关能连但回 `AC认证失败，请在宿舍区访问` → 判定不在宿舍区

两种情况都转入待机，只保留每 `idle_interval` 秒（默认 120 秒）一次的轻量检查，日志里只在状态切换时记一行。插回宿舍网线或回到宿舍区后，下一轮检查就会自动恢复保活。

## 文件

- `campus_link.py` 主脚本
- `start-silent.vbs` 无窗口启动器
- `config.json` 首次运行自动生成，**密码明文存放**，不提交到仓库
- `campus_link.log` 运行日志，1MB 自动轮转 3 份

## 注意

认证服务在 **801 端口**，80 端口是另一个 web 服务，打过去只会返回 `Error code: 404 URL no found`。
config.json 里的 gateway 必须带端口：`172.30.255.42:801`。

IP 探测按「测速页 → 80 端口门户页的 v4ip/lip 字段 → 配置/手输」三级降级，换校区换网段一般也能自己找到。
