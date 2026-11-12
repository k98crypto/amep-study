import getpass
import hashlib
import http.client
import json
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from urllib.parse import urlencode


class Fields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        item = dict(attrs)
        if tag == "input" and item.get("name"):
            self.values[item["name"]] = item.get("value", "")


class RouterConnection(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(("192.168.10.1", self.port), timeout=self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname="cudy.net")


def main():
    password = getpass.getpass("Cudy admin password: ")
    context = ssl.create_default_context(cafile="/tmp/codex-openwrt-router.pem")
    context.check_hostname = False
    conn = RouterConnection("OpenWrt", context=context, timeout=8)
    cookies = {}

    def request(method, path, body=None, xhr=False):
        headers = {"Host": "cudy.net"}
        if body is not None:
            headers.update(
                {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://cudy.net",
                    "Referer": "https://cudy.net/cgi-bin/luci/",
                }
            )
            if xhr:
                headers["X-Requested-With"] = "XMLHttpRequest"
        if cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read()
        for key, value in response.getheaders():
            if key.lower() == "set-cookie":
                parsed = SimpleCookie()
                parsed.load(value)
                cookies.update({name: morsel.value for name, morsel in parsed.items()})
        return response.status, data

    try:
        _, page = request("GET", "/cgi-bin/luci/")
        parser = Fields()
        parser.feed(page.decode("utf-8", errors="replace"))
        fields = parser.values
        token_status, token_data = request("POST", "/cgi-bin/luci/admin/get_token", b"", xhr=True)
        print("Token HTTP status:", token_status)
        token = token_data.decode("utf-8").strip()
        if token.startswith('"'):
            token = json.loads(token)
        salted = hashlib.sha256((password + fields["salt"]).encode()).hexdigest()
        fields.update(
            {
                "token": token,
                "zonename": "Asia/Shanghai",
                "timeclock": str(int(time.time())),
                "luci_language": "zh_cn",
                "luci_username": "admin",
                "luci_password": hashlib.sha256((salted + token).encode()).hexdigest(),
            }
        )
        status, _ = request("POST", "/cgi-bin/luci/", urlencode(fields).encode())
        print("LuCI HTTP status:", status)
        print("LuCI cookie names:", ",".join(k for k in cookies if k.startswith("sysauth")) or "none")

        def ubus(session, obj, method, params):
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "call",
                "params": [session, obj, method, params],
            }
            body = json.dumps(payload).encode()
            headers = {"Host": "cudy.net", "Content-Type": "application/json"}
            if cookies:
                headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
            conn.request("POST", "/ubus", body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            return response.status, json.loads(data)

        status, reply = ubus("0" * 32, "session", "login", {"username": "admin", "password": password})
        login = reply.get("result", [None, {}])
        session = login[1].get("ubus_rpc_session") if login and login[0] == 0 else None
        if not session:
            print("Ubus login status:", status, "code:", login[0] if login else "unknown")
            return
        status, reply = ubus(session, "uci", "get", {"config": "firewall"})
        error = reply.get("error", {})
        if error:
            print("UCI HTTP status:", status, "JSON-RPC code:", error.get("code", "unknown"))
        else:
            result = reply.get("result", [])
            print("UCI HTTP status:", status, "Ubus code:", result[0] if result else "unknown")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
