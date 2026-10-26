#!/usr/bin/env python3
"""校园网 eportal 自动登录保活脚本

用法:
    python campus_link.py           常驻保活
    python campus_link.py --once    只跑一轮（计划任务用）
    python campus_link.py --setup   重填账号密码
"""

from __future__ import annotations

import argparse
import getpass
import gzip
import json
import logging
import logging.handlers
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_LOG_PATH = BASE_DIR / "campus_link.log"
SINGLETON_PORT = 49731

DEFAULT_CONFIG = {
    # 认证服务在 801 端口，80 端口是另一个 web 服务，访问会 404
    "gateway": "172.30.255.42:801",
    "check_url": "http://www1.szu.edu.cn/nc/speedtest/",
    "username": "",
    "password": "",
    "ip": "",
    "interval": 60,
    "idle_interval": 120,
    "timeout": 8,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/116.0.5845.141 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "close",
}

IPV4_PATTERN = r"\d{1,3}(?:\.\d{1,3}){3}"
IPV4_RE = re.compile(IPV4_PATTERN)
FONT_IP_RE = re.compile(
    r"<font[^>]*color\s*=\s*[\"']?#?[Dd]00000[\"']?[^>]*>\s*([^<\s]+)", re.I
)
NAMED_IP_RE = re.compile(
    r"(?:您的|你的|本机|Your)\s*IP[^0-9]{0,30}(" + IPV4_PATTERN + r")", re.I
)
GATEWAY_IP_RE = re.compile(r"(?:wlan_?user_?ip|lip|v4ip)=['\"]?([0-9.]+)", re.I)
CALLBACK_RE = re.compile(r"^[\w$.]*\((.*)\)\s*;?\s*$", re.S)

OK_HINTS = ("成功", "已在线", "已经在线", "无需重复", "success")
FAIL_HINTS = ("密码错误", "用户名", "不存在", "欠费", "锁定", "暂停")
# 网关用这句回绝非宿舍区的认证请求，属于「不需要登录」而不是「登录失败」
AWAY_HINTS = ("请在宿舍区", "不在宿舍区", "非宿舍区", "AC认证失败")

# 显式清空代理，避免系统代理把内网认证请求带跑偏
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

logger = logging.getLogger("campus_link")


def http_get(url: str, timeout: float = 8.0) -> tuple[str, str]:
    """发起 GET，返回 (最终地址, 正文)。禁代理、带超时、自动解 gzip。"""
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return response.geturl(), _decode(response)
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.geturl() or url, _decode(exc)


def _decode(response) -> str:
    raw = response.read()
    if "gzip" in (response.headers.get("Content-Encoding") or "").lower():
        raw = gzip.decompress(raw)
    charset = response.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def valid_ipv4(text: str | None) -> str | None:
    if not text:
        return None
    for match in IPV4_RE.finditer(text):
        candidate = match.group(0)
        if all(0 <= int(part) <= 255 for part in candidate.split(".")):
            return candidate
    return None


def ip_from_check_page(text: str) -> str | None:
    """从测速页里抠出本机 IP。优先认 <font color="#D00000"> 那个标签。"""
    match = FONT_IP_RE.search(text)
    if match:
        found = valid_ipv4(match.group(1))
        if found:
            return found
    match = NAMED_IP_RE.search(text)
    if match:
        found = valid_ipv4(match.group(1))
        if found:
            return found
    return None


def ip_from_gateway(final_url: str, text: str) -> str | None:
    for source in (final_url, text):
        for match in GATEWAY_IP_RE.finditer(source or ""):
            found = valid_ipv4(match.group(1))
            if found:
                return found
    return None


def detect_ip(config: dict, allow_prompt: bool = True) -> tuple[str | None, str]:
    """三级探测：检查页 -> 网关首页 -> 配置/手输。返回 (ip, 来源)。"""
    timeout = config["timeout"]
    try:
        _, text = http_get(config["check_url"], timeout)
        found = ip_from_check_page(text)
        if found:
            return found, "检查页"
    except Exception as exc:  # noqa: BLE001 - 探测失败属于常态
        logger.debug("检查页不可用: %s", exc)

    try:
        # 80 端口的门户页含 v4ip/lip 字段，801 端口的 SPA 页没有
        host = config["gateway"].split(":")[0]
        final_url, text = http_get(f"http://{host}/", timeout)
        found = ip_from_gateway(final_url, text)
        if found:
            return found, "网关首页"
    except Exception as exc:  # noqa: BLE001
        logger.debug("网关首页不可用: %s", exc)

    saved = valid_ipv4(config.get("ip"))
    if saved:
        return saved, "配置"

    if allow_prompt:
        raw = input("无法自动获取 IP，请手动输入（直接回车跳过本轮）: ").strip()
        found = valid_ipv4(raw)
        if found:
            config["ip"] = found
            return found, "手动"
    return None, ""


def login(config: dict, ip: str) -> tuple[bool | None, str]:
    username = config["username"].strip()
    account = username if username.startswith(",") else f",0,{username}"
    params = {
        "callback": "dr1003",
        "login_method": "1",
        "user_account": account,
        "user_password": config["password"],
        "wlan_user_ip": ip,
        "wlan_user_ipv6": "",
        "wlan_user_mac": "000000000000",
        "wlan_ac_ip": "",
        "wlan_ac_name": "",
        "jsVersion": "4.1.3",
        "terminal_type": "1",
        "lang": "zh-cn",
        "v": str(int(time.time()) % 100000),
    }
    url = f"http://{config['gateway']}/eportal/portal/login?" + urllib.parse.urlencode(
        params
    )
    _, text = http_get(url, config["timeout"])
    return analyse_reply(text)


def analyse_reply(text: str) -> tuple[bool | None, str]:
    body = (text or "").strip()
    if not body:
        return None, "空响应"
    match = CALLBACK_RE.match(body)
    if match:
        body = match.group(1).strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None, body[:200]
    if not isinstance(data, dict):
        return None, body[:200]

    message = str(data.get("msg") or data.get("message") or "")
    result = data.get("result")
    ret_code = data.get("ret_code")
    summary = message or f"result={result} ret_code={ret_code}"

    if str(result) == "1" or str(ret_code) == "2":
        return True, summary
    if any(hint in message for hint in OK_HINTS):
        return True, summary
    if str(result) == "0" or any(hint in message for hint in FAIL_HINTS):
        return False, summary
    return None, summary


def run_round(config: dict, allow_prompt: bool = True) -> tuple[bool, str]:
    """跑一轮。返回 (是否成功, 状态)。

    状态取值：
      ok    - 已登录 / 本来就在线
      away  - 不在宿舍区，网关明确拒绝，不该继续尝试
      retry - 网络没就绪之类，值得稍后再试
      fatal - 密码错误、欠费这类硬失败，重试也没用
    """
    ip, source = detect_ip(config, allow_prompt)
    if not ip:
        logger.warning("没有拿到本机 IP，本轮跳过")
        return False, "retry"

    try:
        ok, message = login(config, ip)
    except Exception as exc:  # noqa: BLE001
        logger.error("登录请求异常 %s: %s", type(exc).__name__, exc)
        return False, "retry"

    if ok is True:
        logger.info("登录成功 ip=%s 来源=%s %s", ip, source, message)
        return True, "ok"
    if ok is False:
        if any(hint in message for hint in AWAY_HINTS):
            logger.debug("不在宿舍区 ip=%s %s", ip, message)
            return False, "away"
        logger.error("登录失败 ip=%s 来源=%s %s", ip, source, message)
        return False, "fatal"
    logger.warning("响应无法识别 ip=%s 来源=%s %s", ip, source, message)
    return False, "retry"


def claim_singleton():
    """占一个本地端口当锁，保证只有一个常驻实例；进程退出端口自动释放。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", SINGLETON_PORT))
        sock.listen(1)
    except OSError:
        sock.close()
        return None
    return sock


def sleep_until(seconds: float) -> bool:
    """分段睡眠。返回 True 表示墙钟跳变，即中间系统休眠过。"""
    start = time.time()
    target = start + seconds
    while True:
        remain = target - time.time()
        if remain <= 0:
            break
        time.sleep(min(remain, 5.0))
    return time.time() - start > seconds * 2 + 30


def gateway_reachable(config: dict) -> bool:
    """TCP 探一下认证网关。连不上基本可以断定：当前不在校园网里。"""
    host, _, port = config["gateway"].partition(":")
    try:
        with socket.create_connection((host, int(port or 80)), timeout=3):
            return True
    except (OSError, ValueError):
        return False


def run_forever(config: dict) -> None:
    interval = max(5.0, float(config["interval"]))
    # 实测网关对同一 IP 的连续认证有限流：5 秒一档约一半请求被 503 打回，
    # 15 秒一档稳定通过，所以快速重试的最短间隔定 15 秒
    retry_interval = min(interval, 15.0)
    idle_interval = max(30.0, float(config.get("idle_interval", 120)))
    delay = interval
    away = False
    logger.info(
        "开始保活，间隔 %.0fs，失败后 %.0fs 起快速重试", interval, retry_interval
    )
    while True:
        if not gateway_reachable(config):
            state = "away"
        else:
            try:
                ok, state = run_round(config, allow_prompt=False)
            except Exception as exc:  # noqa: BLE001
                logger.error("轮次异常 %s: %s", type(exc).__name__, exc)
                ok, state = False, "retry"

        if state == "away":
            if not away:
                away = True
                logger.info(
                    "不在宿舍区或网关不可达，转入待机（每 %.0fs 检查一次）", idle_interval
                )
            delay = idle_interval
        else:
            if away:
                away = False
                logger.info("网络环境恢复，重新开始保活")

            # 成功回到正常节奏；网络类失败快速重试并逐步退避；
            # 密码错误这类硬失败不折腾，按正常间隔慢慢试
            if state == "ok":
                delay = interval
            elif state == "retry":
                delay = (
                    retry_interval if delay >= interval else min(interval, delay * 2)
                )
            else:
                delay = interval

        if sleep_until(delay):
            logger.info("系统休眠唤醒，立即重连")
            delay = retry_interval


def load_config(path: Path) -> dict:
    config = dict(DEFAULT_CONFIG)
    if not path.exists():
        return config
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("配置文件读取失败: %s", exc)
        return config
    if isinstance(data, dict):
        for key in DEFAULT_CONFIG:
            if key in data:
                config[key] = data[key]
    return config


def save_config(path: Path, config: dict) -> None:
    data = {key: config.get(key, DEFAULT_CONFIG[key]) for key in DEFAULT_CONFIG}
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def interactive_setup(config: dict, path: Path) -> None:
    print("填写校园网账号（密码以明文保存在 config.json）")
    username = input(f"  账号 [{config['username'] or '空'}] : ").strip()
    if username:
        config["username"] = username
    if has_tty():
        try:
            password = getpass.getpass("  密码: ")
        except Exception:  # noqa: BLE001 - 某些终端不支持
            password = input("  密码: ")
    else:
        password = input("  密码: ")
    if password:
        config["password"] = password
    save_config(path, config)
    print(f"已保存到 {path}")


def has_tty() -> bool:
    """pythonw 模式下 sys.stdin 是 None，直接 isatty() 会崩。"""
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:  # noqa: BLE001
        return False


def setup_logging(verbose: bool, no_file: bool) -> None:
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 无控制台（pythonw）时 sys.stdout 为 None，此时只写文件
    stream = sys.stdout or sys.stderr
    if stream is not None:
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        console = logging.StreamHandler(stream)
        console.setFormatter(formatter)
        logger.addHandler(console)

    if not no_file:
        file_handler = logging.handlers.RotatingFileHandler(
            DEFAULT_LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="校园网 eportal 自动登录保活",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-c", "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="配置文件路径"
    )
    parser.add_argument("-i", "--interval", type=float, help="保活间隔（秒）")
    parser.add_argument("--once", action="store_true", help="只执行一轮后退出")
    parser.add_argument("--setup", action="store_true", help="重新填写账号密码")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    parser.add_argument("--no-log-file", action="store_true", help="不写日志文件")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose, args.no_log_file)

    config = load_config(args.config)
    if args.interval:
        config["interval"] = args.interval

    if args.setup or not config["username"] or not config["password"]:
        if not has_tty():
            logger.error("缺少账号密码，且当前非交互终端，请先运行 --setup")
            return 2
        interactive_setup(config, args.config)

    try:
        if args.once:
            ok, state = run_round(config, allow_prompt=False)
            if state == "away":
                logger.info("当前不在宿舍区，无需登录")
                return 0
            return 0 if ok else 1
        guard = claim_singleton()
        if guard is None:
            logger.warning("已有实例在运行，本次退出")
            return 0
        run_forever(config)
    except KeyboardInterrupt:
        logger.info("已手动停止")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # pythonw 下没有控制台，未捕获异常必须落进日志才查得到
        logger.exception("未捕获异常，进程退出")
        raise
