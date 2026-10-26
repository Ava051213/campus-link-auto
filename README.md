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

## 文件

- `campus_link.py` 主脚本
- `config.json` 首次运行自动生成，**密码明文存放**，不提交到仓库
- `campus_link.log` 运行日志，1MB 自动轮转 3 份

## 注意

认证服务在 **801 端口**，80 端口是另一个 web 服务，打过去只会返回 `Error code: 404 URL no found`。
config.json 里的 gateway 必须带端口：`172.30.255.42:801`。

IP 探测按「测速页 → 80 端口门户页的 v4ip/lip 字段 → 配置/手输」三级降级，换校区换网段一般也能自己找到。
