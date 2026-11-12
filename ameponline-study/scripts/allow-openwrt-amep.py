import getpass
import http.client
import ipaddress
import json
import socket
import ssl
import sys


ROUTER_IP = "192.168.10.1"
ROUTER_NAME = "OpenWrt"
CERT_FILE = "/tmp/codex-openwrt-router.pem"
RULE_SECTION = "codex_amep_https"
RULE_NAME = "AMEP HTTPS"


class RouterHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection((ROUTER_IP, self.port), timeout=self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=ROUTER_NAME)


def find_server_ipv6():
    addresses = socket.getaddrinfo("spiritwave1.dpdns.org", None, socket.AF_INET6, socket.SOCK_STREAM)
    for address in addresses:
        candidate = ipaddress.IPv6Address(address[4][0])
        if candidate.is_global:
            return str(candidate)
    raise RuntimeError("The Ubuntu public IPv6 address could not be resolved")


def main():
    context = ssl.create_default_context(cafile=CERT_FILE)
    connection = RouterHTTPSConnection(ROUTER_NAME, context=context, timeout=8)
    password = getpass.getpass("Cudy admin password: ")
    next_id = 0

    def call(session, obj, method, params):
        nonlocal next_id
        next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": next_id,
            "method": "call",
            "params": [session, obj, method, params],
        }
        connection.request(
            "POST",
            "/ubus",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"Router API returned HTTP {response.status}")
        try:
            reply = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("Router API returned an invalid response") from None
        if "result" not in reply:
            error = reply.get("error", {})
            code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
            raise RuntimeError(f"Router API call failed: {obj}.{method} (JSON-RPC code {code})")
        result = reply["result"]
        if not result or result[0] != 0:
            code = result[0] if result and isinstance(result[0], int) else "unknown"
            if obj == "session" and method == "login":
                raise RuntimeError(f"Router login rejected (Ubus code {code})")
            raise RuntimeError(f"Router API call failed: {obj}.{method} (Ubus code {code})")
        return result[1] if len(result) > 1 else {}

    try:
        login = call(
            "00000000000000000000000000000000",
            "session",
            "login",
            {"username": "admin", "password": password},
        )
        session = login.get("ubus_rpc_session")
        if not session:
            raise RuntimeError("OpenWrt login failed")

        ipv6 = find_server_ipv6()
        config = call(session, "uci", "get", {"config": "firewall"})
        sections = config.get("values", {})
        desired = {
            "name": RULE_NAME,
            "src": "wan",
            "dest": "lan",
            "family": "ipv6",
            "proto": "tcp",
            "dest_ip": ipv6,
            "dest_port": "80 443",
            "target": "ACCEPT",
        }

        section = sections.get(RULE_SECTION)
        if section is not None and section.get(".type") != "rule":
            raise RuntimeError("The reserved firewall rule section has another type")
        if section is not None and all(section.get(key) == value for key, value in desired.items()):
            print("The AMEP IPv6 TCP 80/443 rule is already present.")
            return

        if section is None:
            call(
                session,
                "uci",
                "add",
                {"config": "firewall", "type": "rule", "name": RULE_SECTION, "values": desired},
            )
        else:
            call(
                session,
                "uci",
                "set",
                {"config": "firewall", "section": RULE_SECTION, "values": desired},
            )
        call(session, "uci", "commit", {"config": "firewall"})
        call(session, "firewall", "reload", {})
        print("Added the AMEP IPv6 TCP 80/443 rule for this Ubuntu server.")
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Firewall update failed: {error}", file=sys.stderr)
        raise SystemExit(1)
