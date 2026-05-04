#!/usr/bin/env python3
"""MonkeyCode 配置辅助 CLI。

通过 API 获取账号内的模型、项目、开发环境镜像 ID，
简化配置流程，避免强依赖抓包获取。

用法:
    # 查询所有配置信息
    ./scripts/monkeycode_config_helper.py

    # 子命令查询
    ./scripts/monkeycode_config_helper.py models
    ./scripts/monkeycode_config_helper.py projects
    ./scripts/monkeycode_config_helper.py images

    # JSON 输出
    ./scripts/monkeycode_config_helper.py models --json
    ./scripts/monkeycode_config_helper.py --json

环境变量（优先级低于 CLI 参数）:
    MONKEYCODE_EMAIL    - 登录邮箱
    MONKEYCODE_PASSWORD - 登录密码
    MONKEYCODE_WORKERS  - PoW 并行 worker 数（可选，默认为 CPU 核心数）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Add .github/scripts to path so we can reuse the login module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".github", "scripts"))

from monkeycode_login import (
    BASE_URL,
    COMMON_HEADERS,
    login,
    load_cookies_from_file,
    verify_cached_cookie,
    save_cookies,
    COOKIE_CACHE_DIR,
    COOKIE_CACHE_FILE,
)

import getpass
import http.cookiejar
import urllib.request
import urllib.error


def _get_json(
    opener: urllib.request.OpenerDirector,
    url: str,
) -> dict:
    """GET 请求并返回 JSON 响应。"""
    headers = {
        **COMMON_HEADERS,
        "Referer": f"{BASE_URL}/console/",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    with opener.open(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _build_opener(
    cookie_jar: http.cookiejar.CookieJar,
) -> urllib.request.OpenerDirector:
    """构建带 cookie 的 URL opener。"""
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar)
    )


def _fetch_all_pages(
    opener: urllib.request.OpenerDirector,
    url: str,
    data_key: str,
) -> list[dict]:
    """自动翻页获取所有数据。"""
    results: list[dict] = []
    cursor = ""
    while True:
        sep = "&" if "?" in url else "?"
        paged_url = f"{url}{sep}limit=100"
        if cursor:
            paged_url += f"&cursor={cursor}"
        resp = _get_json(opener, paged_url)
        data = resp.get("data", {})
        items = data.get(data_key, [])
        results.extend(items)
        page = data.get("page", {})
        if not page.get("has_more"):
            break
        cursor = page.get("cursor", "")
        if not cursor:
            break
    return results


def fetch_models(
    opener: urllib.request.OpenerDirector,
) -> list[dict]:
    """获取用户可用的模型列表。"""
    return _fetch_all_pages(
        opener, f"{BASE_URL}/api/v1/users/models", "models"
    )


def fetch_projects(
    opener: urllib.request.OpenerDirector,
) -> list[dict]:
    """获取用户的项目列表。"""
    return _fetch_all_pages(
        opener, f"{BASE_URL}/api/v1/users/projects", "projects"
    )


def fetch_images(
    opener: urllib.request.OpenerDirector,
) -> list[dict]:
    """获取开发环境镜像列表。"""
    return _fetch_all_pages(
        opener, f"{BASE_URL}/api/v1/users/images", "images"
    )


# --- Display helpers ---

def _owner_label(owner: dict | None) -> str:
    """格式化 owner 信息。"""
    if not owner:
        return ""
    owner_type = owner.get("type", "")
    owner_name = owner.get("name", "")
    if owner_type == "public":
        return "[public]"
    if owner_type == "team":
        return f"[team: {owner_name}]"
    return "[private]"


def print_models(models: list[dict]) -> None:
    """以表格形式打印模型列表。"""
    if not models:
        print("  (未找到模型)")
        return

    # Header
    print(f"  {'ID':<38} {'Model':<30} {'Provider':<15} {'Owner':<15} {'Default'}")
    print(f"  {'-'*38} {'-'*30} {'-'*15} {'-'*15} {'-'*7}")

    for m in models:
        model_id = m.get("id", "")
        model_name = m.get("model", "")
        provider = m.get("provider", "")
        owner = _owner_label(m.get("owner"))
        is_default = "yes" if m.get("is_default") else ""
        print(f"  {model_id:<38} {model_name:<30} {provider:<15} {owner:<15} {is_default}")


def print_projects(projects: list[dict]) -> None:
    """以表格形式打印项目列表。"""
    if not projects:
        print("  (未找到项目)")
        return

    print(f"  {'ID':<38} {'Name':<30} {'Platform':<10} {'Repo URL'}")
    print(f"  {'-'*38} {'-'*30} {'-'*10} {'-'*40}")

    for p in projects:
        project_id = p.get("id", "")
        name = p.get("name", "")
        platform = p.get("platform", "")
        repo_url = p.get("repo_url", "")
        print(f"  {project_id:<38} {name:<30} {platform:<10} {repo_url}")


def print_images(images: list[dict]) -> None:
    """以表格形式打印镜像列表。"""
    if not images:
        print("  (未找到镜像)")
        return

    print(f"  {'ID':<38} {'Name':<30} {'Owner':<15} {'Default'}")
    print(f"  {'-'*38} {'-'*30} {'-'*15} {'-'*7}")

    for img in images:
        image_id = img.get("id", "")
        name = img.get("name", "")
        owner = _owner_label(img.get("owner"))
        is_default = "yes" if img.get("is_default") else ""
        print(f"  {image_id:<38} {name:<30} {owner:<15} {is_default}")


# --- Main ---

def get_authenticated_opener(
    email: str,
    password: str,
) -> urllib.request.OpenerDirector:
    """登录并返回带认证 cookie 的 opener。

    优先使用缓存 cookie，失效时自动重新登录。
    """
    os.makedirs(COOKIE_CACHE_DIR, exist_ok=True)
    cached_jar = load_cookies_from_file(COOKIE_CACHE_FILE)
    if cached_jar is not None:
        print("发现缓存 cookie，正在验证...")
        if verify_cached_cookie(cached_jar):
            print("缓存 cookie 有效，跳过登录")
            return _build_opener(cached_jar)
        print("缓存 cookie 已过期，重新登录...")

    _, cookie_jar = login(email, password)
    save_cookies(cookie_jar, COOKIE_CACHE_FILE, mozilla_compat=True)
    return _build_opener(cookie_jar)


def _run_query(
    email: str,
    password: str,
    resources: list[str],
    output_json: bool,
) -> None:
    """执行查询并输出结果。"""
    opener = get_authenticated_opener(email, password)
    result: dict[str, list[dict]] = {}

    fetchers: dict[str, tuple[str, callable, callable]] = {
        "models": ("模型", fetch_models, print_models),
        "projects": ("项目", fetch_projects, print_projects),
        "images": ("镜像", fetch_images, print_images),
    }

    for res in resources:
        label, fetcher, printer = fetchers[res]
        print(f"\n[{label}] 正在获取{label}列表...")
        data = fetcher(opener)
        result[res] = data
        if not output_json:
            printer(data)

    if output_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("\n" + "=" * 70)
        print("配置摘要")
        print("=" * 70)
        _print_recommendations(result)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="monkeycode-config",
        description="MonkeyCode 配置辅助 CLI — 获取模型/项目/镜像 ID",
    )
    parser.add_argument(
        "-e", "--email",
        default=None,
        help="登录邮箱（也可通过 MONKEYCODE_EMAIL 环境变量设置）",
    )
    parser.add_argument(
        "-p", "--password",
        default=None,
        help="登录密码（也可通过 MONKEYCODE_PASSWORD 环境变量设置）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="以 JSON 格式输出（方便脚本解析）",
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("models", help="查询可用模型列表")
    sub.add_parser("projects", help="查询项目列表")
    sub.add_parser("images", help="查询开发环境镜像列表")
    sub.add_parser("all", help="查询所有资源（默认行为）")

    args = parser.parse_args()

    all_resources = ["models", "projects", "images"]
    resources = all_resources if args.command in (None, "all") else [args.command]

    email = args.email or os.environ.get("MONKEYCODE_EMAIL", "")
    password = args.password or os.environ.get("MONKEYCODE_PASSWORD", "")

    if not email:
        email = input("邮箱: ")
    if not password:
        password = getpass.getpass("密码: ")

    _run_query(email, password, resources, args.output_json)


def _print_recommendations(result: dict[str, list[dict]]) -> None:
    """Print recommended variable values based on query results."""
    models = result.get("models", [])
    projects = result.get("projects", [])
    images = result.get("images", [])

    print("\n推荐的 GitHub Actions 变量配置:")
    print("-" * 50)

    if models:
        # Prefer default model, otherwise first one
        default_model = next((m for m in models if m.get("is_default")), None)
        rec_model = default_model or models[0]
        print(f"  MONKEYCODE_MODEL_ID = {rec_model['id']}")
        print(f"    -> {rec_model.get('model', '?')} ({rec_model.get('provider', '?')})")
    else:
        print("  MONKEYCODE_MODEL_ID = (无可用模型，请先配置)")

    if images:
        default_image = next((i for i in images if i.get("is_default")), None)
        rec_image = default_image or images[0]
        print(f"  MONKEYCODE_IMAGE_ID = {rec_image['id']}")
        print(f"    -> {rec_image.get('name', '?')}")
    else:
        print("  MONKEYCODE_IMAGE_ID = (无可用镜像)")

    if projects:
        if len(projects) == 1:
            rec_project = projects[0]
            print(f"  MONKEYCODE_PROJECT_ID = {rec_project['id']}")
            print(f"    -> {rec_project.get('name', '?')} ({rec_project.get('repo_url', '?')})")
        else:
            print("  MONKEYCODE_PROJECT_ID = (存在多个项目，请从上方列表中选择)")
    else:
        print("  MONKEYCODE_PROJECT_ID = (未找到项目，请先创建)")

    print()


if __name__ == "__main__":
    main()
