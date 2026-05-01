"""MonkeyCode 配置辅助脚本。

通过 API 获取账号内的模型、项目、开发环境镜像 ID，
简化配置流程，避免强依赖抓包获取。

用法:
    # 查询所有配置信息（模型、项目、镜像）
    python3 scripts/monkeycode_config_helper.py

    # 仅查询模型列表
    python3 scripts/monkeycode_config_helper.py models

    # 仅查询项目列表
    python3 scripts/monkeycode_config_helper.py projects

    # 仅查询镜像列表
    python3 scripts/monkeycode_config_helper.py images

    # 输出 JSON 格式（方便脚本解析）
    python3 scripts/monkeycode_config_helper.py --json

环境变量:
    MONKEYCODE_EMAIL    - 登录邮箱（必需）
    MONKEYCODE_PASSWORD - 登录密码（必需）
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
        print("  (no models found)")
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
        print("  (no projects found)")
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
        print("  (no images found)")
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

def get_authenticated_opener() -> urllib.request.OpenerDirector:
    """登录并返回带认证 cookie 的 opener。

    优先使用缓存 cookie，失效时自动重新登录。
    """
    email = os.environ.get("MONKEYCODE_EMAIL", "")
    password = os.environ.get("MONKEYCODE_PASSWORD", "")

    if not email or not password:
        print(
            "Error: please set MONKEYCODE_EMAIL and MONKEYCODE_PASSWORD",
            file=sys.stderr,
        )
        sys.exit(1)

    # Try cached cookie first
    os.makedirs(COOKIE_CACHE_DIR, exist_ok=True)
    cached_jar = load_cookies_from_file(COOKIE_CACHE_FILE)
    if cached_jar is not None:
        print("Found cached cookie, verifying...")
        if verify_cached_cookie(cached_jar):
            print("Cached cookie is valid, skipping login")
            return _build_opener(cached_jar)
        print("Cached cookie expired, re-logging in...")

    # Full login
    _, cookie_jar = login(email, password)
    save_cookies(cookie_jar, COOKIE_CACHE_FILE, mozilla_compat=True)
    return _build_opener(cookie_jar)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MonkeyCode config helper - fetch model/project/image IDs"
    )
    parser.add_argument(
        "resource",
        nargs="?",
        choices=["models", "projects", "images"],
        default=None,
        help="Query a specific resource type (default: all)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output in JSON format",
    )
    args = parser.parse_args()

    opener = get_authenticated_opener()

    query_all = args.resource is None
    result: dict[str, list[dict]] = {}

    if query_all or args.resource == "models":
        print("\n[Models] Fetching model list...")
        models = fetch_models(opener)
        result["models"] = models
        if not args.output_json:
            print_models(models)

    if query_all or args.resource == "projects":
        print("\n[Projects] Fetching project list...")
        projects = fetch_projects(opener)
        result["projects"] = projects
        if not args.output_json:
            print_projects(projects)

    if query_all or args.resource == "images":
        print("\n[Images] Fetching image list...")
        images = fetch_images(opener)
        result["images"] = images
        if not args.output_json:
            print_images(images)

    if args.output_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    # Print summary with recommended variable values
    if not args.output_json:
        print("\n" + "=" * 70)
        print("Configuration Summary")
        print("=" * 70)
        _print_recommendations(result)


def _print_recommendations(result: dict[str, list[dict]]) -> None:
    """Print recommended variable values based on query results."""
    models = result.get("models", [])
    projects = result.get("projects", [])
    images = result.get("images", [])

    print("\nRecommended GitHub Actions Variables:")
    print("-" * 50)

    if models:
        # Prefer default model, otherwise first one
        default_model = next((m for m in models if m.get("is_default")), None)
        rec_model = default_model or models[0]
        print(f"  MONKEYCODE_MODEL_ID = {rec_model['id']}")
        print(f"    -> {rec_model.get('model', '?')} ({rec_model.get('provider', '?')})")
    else:
        print("  MONKEYCODE_MODEL_ID = (no models available, please configure one first)")

    if images:
        default_image = next((i for i in images if i.get("is_default")), None)
        rec_image = default_image or images[0]
        print(f"  MONKEYCODE_IMAGE_ID = {rec_image['id']}")
        print(f"    -> {rec_image.get('name', '?')}")
    else:
        print("  MONKEYCODE_IMAGE_ID = (no images available)")

    if projects:
        if len(projects) == 1:
            rec_project = projects[0]
            print(f"  MONKEYCODE_PROJECT_ID = {rec_project['id']}")
            print(f"    -> {rec_project.get('name', '?')} ({rec_project.get('repo_url', '?')})")
        else:
            print("  MONKEYCODE_PROJECT_ID = (multiple projects found, pick one from the list above)")
    else:
        print("  MONKEYCODE_PROJECT_ID = (no projects found, please create one first)")

    print()


if __name__ == "__main__":
    main()
