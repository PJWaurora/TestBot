from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import ts3
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.tsperson import TS3Config


def main() -> int:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path)

    config = TS3Config.from_env()
    host = config.host
    port = config.query_port
    user = config.query_user
    password = config.query_password
    sid = config.virtual_server_id
    timeout = config.timeout

    print(
        "config:",
        {
            "host": host,
            "port": port,
            "user_set": bool(user),
            "password_set": bool(password),
            "sid": sid,
            "timeout": timeout,
        },
    )

    try:
        print("step=resolve")
        resolved = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        print("resolve=ok", [item[-1] for item in resolved])
    except Exception as exc:
        print("resolve=failed", type(exc).__name__, exc)
        return 1

    try:
        print("step=tcp_connect")
        with socket.create_connection((host, port), timeout=timeout):
            pass
        print("tcp_connect=ok")
    except Exception as exc:
        print("tcp_connect=failed", type(exc).__name__, exc)
        return 2

    conn = ts3.query.TS3Connection()
    try:
        print("step=ts3_open")
        conn.open(host, port, timeout=timeout)
        print("ts3_open=ok")

        print("step=login")
        conn.login(client_login_name=user, client_login_password=password)
        print("login=ok")

        print("step=use")
        conn.use(sid=sid)
        print("use=ok")

        print("step=serverinfo")
        info = conn.send("serverinfo", timeout=timeout).parsed
        print("serverinfo=ok")
        if info:
            first = info[0]
            print(
                "server:",
                {
                    "name": first.get("virtualserver_name"),
                    "clients": first.get("virtualserver_clientsonline"),
                    "max_clients": first.get("virtualserver_maxclients"),
                },
            )
        return 0
    except Exception as exc:
        print("ts3_step=failed", type(exc).__name__, exc)
        return 3
    finally:
        try:
            conn.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
