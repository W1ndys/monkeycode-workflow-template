"""MonkeyCode WebSocket 客户端脚本。

通过 WebSocket 与 MonkeyCode 平台交互，支持：
1. restart: 重置任务上下文（不销毁 VM 环境）
2. send: 向任务发送新的用户输入

用法:
    # 重置上下文
    python3 .github/scripts/monkeycode_ws.py restart --task-id <id> --cookie-file <path>

    # 重置上下文并发送新指令
    python3 .github/scripts/monkeycode_ws.py send --task-id <id> --cookie-file <path> --content <text>

    # 仅发送新指令（不重置上下文）
    python3 .github/scripts/monkeycode_ws.py send --task-id <id> --cookie-file <path> --content <text> --no-restart

环境变量:
    GITHUB_OUTPUT - GitHub Actions 输出文件（可选）
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import time
import uuid

# websocket-client 库，GitHub Actions runner 上需要 pip install
import websocket

BASE_URL = "https://monkeycode-ai.com"
WS_BASE_URL = "wss://monkeycode-ai.com"
CONTROL_ENDPOINT = "/api/v1/users/tasks/control"
STREAM_ENDPOINT = "/api/v1/users/tasks/stream"

RESTART_TIMEOUT_S = 60
SEND_TIMEOUT_S = 30


def write_github_output(key: str, value: str) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{key}={value}\n")


def load_cookie_header(cookie_file: str) -> str:
    """从 Netscape 格式 cookie 文件中读取 cookie，拼成 HTTP Cookie 头。"""
    cookies: list[str] = []
    with open(cookie_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                name = parts[5]
                value = parts[6]
                cookies.append(f"{name}={value}")
    return "; ".join(cookies)


def b64encode(text: str) -> str:
    """Base64 编码字符串。"""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def restart_context(task_id: str, cookie_header: str) -> bool:
    """通过 Control WebSocket 重置任务上下文。

    协议：
      上行: {"type":"call","kind":"restart","data":<json_bytes>}
      data 内容: {"request_id":"...","load_session":false}
      下行: {"type":"call-response","kind":"restart","data":<json_bytes>}
      data 内容: {"success":true,"message":"...","session_id":"..."}
    """
    url = f"{WS_BASE_URL}{CONTROL_ENDPOINT}?id={task_id}"
    request_id = str(uuid.uuid4())

    print(f"[restart] 连接 Control WebSocket: {task_id}")
    ws = websocket.create_connection(
        url,
        timeout=RESTART_TIMEOUT_S,
        header={"Cookie": cookie_header},
        sslopt={"cert_reqs": ssl.CERT_NONE},
    )

    try:
        # 发送 restart call
        call_data = json.dumps({"request_id": request_id, "load_session": False})
        message = json.dumps({
            "type": "call",
            "kind": "restart",
            "data": json.loads(call_data),  # data 是 JSON object，不是字符串
        })
        ws.send(message)
        print(f"[restart] 已发送 restart 请求 (request_id={request_id})")

        # 等待 call-response
        deadline = time.time() + RESTART_TIMEOUT_S
        while time.time() < deadline:
            raw = ws.recv()
            if not raw:
                continue
            resp = json.loads(raw)

            # 跳过 ping 和其他事件
            if resp.get("type") == "ping":
                continue
            if resp.get("type") == "task-event":
                continue

            if resp.get("type") == "call-response" and resp.get("kind") == "restart":
                data = resp.get("data")
                if isinstance(data, str):
                    data = json.loads(data)
                success = data.get("success", False) if data else False
                msg = data.get("message", "") if data else ""
                print(f"[restart] 响应: success={success}, message={msg}")
                return success

        print("[restart] 等待响应超时")
        return False
    finally:
        ws.close()


def send_user_input(task_id: str, cookie_header: str, content: str) -> bool:
    """通过 Stream WebSocket 发送用户输入。

    协议：
      连接: wss://host/api/v1/users/tasks/stream?id={taskId}&mode=new
      上行: {"type":"user-input","data":"base64(json)"}
        json 内容: {"content":"base64(text)","attachments":[]}
      下行: 等待 task-started 确认任务已启动
    """
    url = f"{WS_BASE_URL}{STREAM_ENDPOINT}?id={task_id}&mode=new"

    print(f"[send] 连接 Stream WebSocket: {task_id}")
    ws = websocket.create_connection(
        url,
        timeout=SEND_TIMEOUT_S,
        header={"Cookie": cookie_header},
        sslopt={"cert_reqs": ssl.CERT_NONE},
    )

    try:
        # 构造 user-input payload
        # 内层: {"content": base64(text), "attachments": []}
        inner_payload = json.dumps({
            "content": b64encode(content),
            "attachments": [],
        })
        # 外层: {"type": "user-input", "data": base64(inner_payload)}
        message = json.dumps({
            "type": "user-input",
            "data": b64encode(inner_payload),
        })
        ws.send(message)
        print(f"[send] 已发送 user-input ({len(content)} 字符)")

        # 等待 task-started 或 task-running 确认
        deadline = time.time() + SEND_TIMEOUT_S
        while time.time() < deadline:
            raw = ws.recv()
            if not raw:
                continue
            resp = json.loads(raw)
            msg_type = resp.get("type", "")

            if msg_type == "ping":
                continue
            if msg_type == "user-input":
                # 服务端回显用户输入，说明已接收
                print("[send] 服务端已接收用户输入")
                return True
            if msg_type == "task-started":
                print("[send] 任务已启动")
                return True
            if msg_type == "task-running":
                print("[send] 任务正在运行")
                return True
            if msg_type == "error" or msg_type == "task-error":
                data = resp.get("data", "")
                print(f"[send] 收到错误: {data}")
                return False

        print("[send] 等待确认超时（输入可能已发送）")
        # 超时不一定是失败，消息可能已经被处理
        return True
    finally:
        ws.close()


def check_task_status(task_id: str, cookie_header: str) -> str | None:
    """通过 REST API 检查任务状态，返回 status 字符串或 None。"""
    import http.cookiejar
    import urllib.request

    url = f"{BASE_URL}/api/v1/users/tasks/{task_id}"
    req = urllib.request.Request(url, method="GET", headers={
        "Accept": "*/*",
        "Cookie": cookie_header,
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", {}).get("status")
    except Exception as e:
        print(f"[check] 查询任务状态失败: {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="MonkeyCode WebSocket 客户端")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # restart 子命令
    restart_parser = subparsers.add_parser("restart", help="重置任务上下文")
    restart_parser.add_argument("--task-id", required=True, help="任务 ID")
    restart_parser.add_argument("--cookie-file", required=True, help="Cookie 文件路径")

    # send 子命令
    send_parser = subparsers.add_parser("send", help="重置上下文并发送新指令")
    send_parser.add_argument("--task-id", required=True, help="任务 ID")
    send_parser.add_argument("--cookie-file", required=True, help="Cookie 文件路径")
    send_parser.add_argument("--content", required=True, help="要发送的内容")
    send_parser.add_argument(
        "--no-restart", action="store_true",
        help="不重置上下文，仅发送输入",
    )

    args = parser.parse_args()
    cookie_header = load_cookie_header(args.cookie_file)

    if not cookie_header:
        print("Cookie 文件为空或格式错误", file=sys.stderr)
        write_github_output("ws_success", "false")
        sys.exit(1)

    if args.command == "restart":
        # 先检查任务是否在运行
        status = check_task_status(args.task_id, cookie_header)
        if status != "processing":
            print(f"任务状态为 {status}，不是 processing，无法 restart")
            write_github_output("ws_success", "false")
            write_github_output("task_status", status or "unknown")
            sys.exit(1)

        success = restart_context(args.task_id, cookie_header)
        write_github_output("ws_success", str(success).lower())
        if not success:
            sys.exit(1)

    elif args.command == "send":
        # 先检查任务是否在运行
        status = check_task_status(args.task_id, cookie_header)
        if status != "processing":
            print(f"任务状态为 {status}，不是 processing，无法操作")
            write_github_output("ws_success", "false")
            write_github_output("task_status", status or "unknown")
            sys.exit(1)

        if not args.no_restart:
            print("=== 第一步：重置上下文 ===")
            if not restart_context(args.task_id, cookie_header):
                print("重置上下文失败", file=sys.stderr)
                write_github_output("ws_success", "false")
                sys.exit(1)
            # 等待 agent 重启完成
            print("等待 agent 重启...")
            time.sleep(5)

        print("=== 发送用户输入 ===")
        success = send_user_input(args.task_id, cookie_header, args.content)
        write_github_output("ws_success", str(success).lower())
        if not success:
            sys.exit(1)

    print("完成")


if __name__ == "__main__":
    main()
