# campus-link-auto

深大 eportal 校园网自动登录保活。纯标准库，不用 pip 装任何东西——断网时也能直接跑。

## 用法

```bash
python campus_link.py           # 首次会问账号密码，之后常驻保活
python campus_link.py --setup   # 改账号密码
python campus_link.py --once    # 只跑一轮，退出码 0 成功 / 1 失败
python campus_link.py -i 30 -v  # 30 秒一轮，带调试日志
```

后台常驻（不弹黑框）：把启动命令换成 `pythonw campus_link.py`，或用计划任务每分钟跑一次 `python campus_link.py --once`。

## 文件

- `campus_link.py` 主脚本
- `config.json` 首次运行自动生成，**密码明文存放**，别提交到仓库
- `campus_link.log` 运行日志，1MB 自动轮转 3 份

## 和原脚本的差别

- 抓 IP 不再写死 `>1`，改成认 `<font color="#D00000">` 标签，非 172.30 网段也能用
- 检查页拿不到 IP 时，退回网关首页的 `wlanuserip` 参数，再退回配置/手输
- 参数用 `urlencode` 拼装，密码含 `& + % #` 不会截断
- 请求带超时，系统代理显式清空（原来那行 NO_PROXY 带 scheme 是失效的）
- Ctrl+C 正常退出，不会再抛 traceback
- 解析回调里的 `result` / `ret_code` 判断成败，日志能区分"登录成功 / 密码错误 / 响应异常"
- 手输的 IP 不会再被下一轮循环覆盖成 None
