"""MonkeyCode 自动登录脚本。

实现 captcha challenge -> PoW 求解 -> redeem -> 密码登录 的完整流程，
支持 cookie 缓存以跳过重复登录，输出 cookie 文件路径供 GitHub Actions 后续步骤使用。

用法:
    python3 .github/scripts/monkeycode_login.py

环境变量:
    MONKEYCODE_EMAIL    - 登录邮箱（必需）
    MONKEYCODE_PASSWORD - 登录密码（必需）
    MONKEYCODE_WORKERS  - PoW 并行 worker 数（可选，默认为 CPU 核心数）
    GITHUB_OUTPUT       - GitHub Actions 输出文件（可选）
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import multiprocessing as mp
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

BASE_URL = "https://monkeycode-ai.com"
COOKIE_CACHE_DIR = ".monkeycode-cookie-cache"
COOKIE_CACHE_FILE = os.path.join(COOKIE_CACHE_DIR, "monkeycode_cookies.txt")
MASK32 = 0xFFFFFFFF
FNV_PRIME = 16777619
FNV_OFFSET = 2166136261

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)

COMMON_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/login",
}


def _fnv1a(value: str) -> int:
    result = FNV_OFFSET
    for char in value:
        result ^= ord(char)
        result = (result * FNV_PRIME) & MASK32
    return result


def prng(seed: str, length: int) -> str:
    state = _fnv1a(seed)
    chunks: list[str] = []
    produced = 0
    while produced < length:
        state ^= (state << 13) & MASK32
        state &= MASK32
        state ^= state >> 17
        state ^= (state << 5) & MASK32
        state &= MASK32
        chunks.append(f"{state:08x}")
        produced += 8
    return "".join(chunks)[:length]


def build_pow_tasks(
    token: str, c: int, s: int, d: int
) -> list[tuple[str, str]]:
    return [
        (prng(f"{token}{i}", s), prng(f"{token}{i}d", d))
        for i in range(1, c + 1)
    ]


def _solve_one(task: tuple[str, str]) -> int:
    salt, target = task
    salt_bytes = salt.encode("utf-8")
    nonce = 0
    while True:
        digest = hashlib.sha256(
            salt_bytes + str(nonce).encode("ascii")
        ).hexdigest()
        if digest.startswith(target):
            return nonce
        nonce += 1


def solve_challenges(
    token: str, c: int, s: int, d: int, workers: int
) -> list[int]:
    tasks = build_pow_tasks(token, c, s, d)
    if workers <= 1:
        return [_solve_one(task) for task in tasks]
    with mp.Pool(workers) as pool:
        return pool.map(_solve_one, tasks)


def _build_opener() -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar)
    )
    return opener, cookie_jar


def _post_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    data: dict | None = None,
) -> dict:
    body = json.dumps(data).encode("utf-8") if data else b""
    headers = {**COMMON_HEADERS, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with opener.open(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(
    opener: urllib.request.OpenerDirector,
    url: str,
) -> tuple[int, dict]:
    headers = {
        **COMMON_HEADERS,
        "Referer": f"{BASE_URL}/console/",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    with opener.open(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def login(
    email: str, password: str, workers: int | None = None
) -> tuple[dict, http.cookiejar.CookieJar]:
    worker_count = workers or int(
        os.environ.get("MONKEYCODE_WORKERS", str(mp.cpu_count()))
    )
    opener, cookie_jar = _build_opener()
    start = time.time()

    # 1. 获取 challenge
    challenge_resp = _post_json(
        opener, f"{BASE_URL}/api/v1/public/captcha/challenge"
    )
    token = challenge_resp["token"]
    cp = challenge_resp["challenge"]
    c, s, d = int(cp["c"]), int(cp["s"]), int(cp["d"])
    print(f"[1/4] challenge: c={c} s={s} d={d}")

    # 2. 求解 PoW
    pow_start = time.time()
    solutions = solve_challenges(token, c, s, d, worker_count)
    print(
        f"[2/4] solved {len(solutions)} PoW tasks "
        f"with {worker_count} workers in {(time.time() - pow_start) * 1000:.0f}ms"
    )

    # 3. Redeem
    redeem_resp = _post_json(
        opener,
        f"{BASE_URL}/api/v1/public/captcha/redeem",
        {"token": token, "solutions": solutions},
    )
    if not redeem_resp.get("success"):
        raise RuntimeError(f"captcha redeem failed: {redeem_resp}")
    captcha_token = str(redeem_resp["token"])
    print("[3/4] captcha redeemed")

    # 4. 密码登录
    login_resp = _post_json(
        opener,
        f"{BASE_URL}/api/v1/users/password-login",
        {"email": email, "password": password, "captcha_token": captcha_token},
    )
    if login_resp.get("code") != 0:
        raise RuntimeError(f"password login failed: {login_resp}")
    print(
        f"[4/4] login success in {(time.time() - start) * 1000:.0f}ms"
    )

    return login_resp, cookie_jar


def save_cookies(
    cookie_jar: http.cookiejar.CookieJar, path: str, mozilla_compat: bool = False
) -> None:
    """将 cookie 保存为 Netscape 格式文件。

    Args:
        cookie_jar: 要保存的 CookieJar 实例。
        path: 目标文件路径。
        mozilla_compat: 为 True 时写入 MozillaCookieJar.load() 所需的扩展头部。
    """
    with open(path, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        if mozilla_compat:
            f.write("# https://curl.se/docs/http-cookies.html\n")
            f.write("# This file was generated by monkeycode_login.py\n\n")
        for cookie in cookie_jar:
            secure = "TRUE" if cookie.secure else "FALSE"
            domain_dot = "TRUE" if cookie.domain.startswith(".") else "FALSE"
            expires = str(cookie.expires) if cookie.expires else "0"
            f.write(
                f"{cookie.domain}\t{domain_dot}\t{cookie.path}\t"
                f"{secure}\t{expires}\t{cookie.name}\t{cookie.value}\n"
            )


def load_cookies_from_file(path: str) -> http.cookiejar.CookieJar | None:
    """从 Netscape 格式文件加载 cookie，返回 CookieJar 或 None。"""
    if not os.path.isfile(path):
        return None
    cookie_jar = http.cookiejar.MozillaCookieJar(path)
    try:
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as e:
        print(f"加载缓存 cookie 失败: {e}")
        return None
    if not list(cookie_jar):
        return None
    return cookie_jar


def verify_cached_cookie(cookie_jar: http.cookiejar.CookieJar) -> bool:
    """用缓存的 cookie 调用订阅接口验证登录态是否有效。"""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar)
    )
    try:
        status, resp = _get_json(opener, f"{BASE_URL}/api/v1/users/subscription")
        if status == 200 and resp.get("data", {}).get("plan"):
            return True
    except urllib.error.HTTPError as e:
        print(f"缓存 cookie 验证失败 (HTTP {e.code})")
    except Exception as e:
        print(f"缓存 cookie 验证失败: {e}")
    return False


def write_github_output(key: str, value: str) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{key}={value}\n")


def main() -> None:
    email = os.environ.get("MONKEYCODE_EMAIL", "")
    password = os.environ.get("MONKEYCODE_PASSWORD", "")

    if not email or not password:
        print(
            "错误：请设置 MONKEYCODE_EMAIL 和 MONKEYCODE_PASSWORD 环境变量",
            file=sys.stderr,
        )
        sys.exit(1)

    # cookie 缓存：固定路径，由 actions/cache 在多次运行间持久化
    os.makedirs(COOKIE_CACHE_DIR, exist_ok=True)
    cached_cookie_path = COOKIE_CACHE_FILE

    # 尝试从缓存加载 cookie
    cached_jar = load_cookies_from_file(cached_cookie_path)
    if cached_jar is not None:
        print("发现缓存 cookie，正在验证登录态...")
        if verify_cached_cookie(cached_jar):
            print("缓存 cookie 有效，跳过登录流程")
            # 将缓存 cookie 复制到工作路径供 curl 使用
            cookie_file = os.path.join(
                tempfile.gettempdir(), "monkeycode_cookies.txt"
            )
            save_cookies(cached_jar, cookie_file)
            print(f"Cookie 已保存: {cookie_file}")
            write_github_output("cookie_file", cookie_file)
            write_github_output("login_success", "true")
            write_github_output("cache_hit", "true")

            # 验证订阅信息
            _print_subscription(cached_jar)
            return
        else:
            print("缓存 cookie 已失效，将重新登录")

    # 正常登录流程
    try:
        result, cookie_jar = login(email, password)
    except urllib.error.HTTPError as e:
        print(f"登录失败 (HTTP {e.code}): {e.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        write_github_output("login_error", f"HTTP {e.code}")
        sys.exit(1)
    except Exception as e:
        print(f"登录失败: {e}", file=sys.stderr)
        write_github_output("login_error", str(e))
        sys.exit(1)

    user = result.get("data", {})
    print(f"已登录: {user.get('name', 'unknown')} <{user.get('email', 'unknown')}>")

    # 保存 cookie 文件供当前 workflow 使用
    cookie_file = os.path.join(tempfile.gettempdir(), "monkeycode_cookies.txt")
    save_cookies(cookie_jar, cookie_file)
    print(f"Cookie 已保存: {cookie_file}")

    # 同时保存到缓存目录供后续 workflow 复用
    save_cookies(cookie_jar, cached_cookie_path, mozilla_compat=True)
    print(f"Cookie 已缓存到: {cached_cookie_path}")

    # 输出到 GitHub Actions
    write_github_output("cookie_file", cookie_file)
    write_github_output("login_success", "true")
    write_github_output("cache_hit", "false")

    # 验证登录态
    _print_subscription(cookie_jar)


def _print_subscription(cookie_jar: http.cookiejar.CookieJar) -> None:
    """打印订阅信息，不影响主流程。"""
    try:
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar)
        )
        status, sub_resp = _get_json(
            opener, f"{BASE_URL}/api/v1/users/subscription"
        )
        plan = sub_resp.get("data", {}).get("plan", "unknown")
        expires_at = sub_resp.get("data", {}).get("expires_at", "unknown")
        print(f"订阅验证: plan={plan}, expires_at={expires_at}")
        write_github_output("plan", plan)
        write_github_output("expires_at", expires_at)
    except Exception as e:
        print(f"订阅验证失败（不影响任务创建）: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
