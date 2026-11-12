import http.client
import ipaddress
import json
import socket
import xml.etree.ElementTree as ET
from pathlib import Path


ROUTER_IP = "192.168.10.1"
ROUTER_PORT = 5000
CONTROL_PATH = "/ctl/IP6FCtl"
SERVICE = "urn:schemas-upnp-org:service:WANIPv6FirewallControl:1"
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
STATE_FILE = Path("/state/pinhole-ids.json")
LEASE_SECONDS = 86400
PORTS = (80, 443)


class UpnpFault(RuntimeError):
    def __init__(self, code, message):
        super().__init__(f"UPnP fault {code}: {message}")
        self.code = code


def find_server_ipv6():
    addresses = socket.getaddrinfo(
        "spiritwave1.dpdns.org", None, socket.AF_INET6, socket.SOCK_STREAM
    )
    for address in addresses:
        candidate = ipaddress.IPv6Address(address[4][0])
        if candidate.is_global:
            return str(candidate)
    raise RuntimeError("The Ubuntu public IPv6 address could not be resolved")


def local_text(root, name):
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == name:
            return element.text or ""
    return ""


def call(action, arguments=None):
    envelope = ET.Element(f"{{{SOAP}}}Envelope", {f"{{{SOAP}}}encodingStyle": "http://schemas.xmlsoap.org/soap/encoding/"})
    body = ET.SubElement(envelope, f"{{{SOAP}}}Body")
    operation = ET.SubElement(body, f"{{{SERVICE}}}{action}")
    for name, value in (arguments or {}).items():
        ET.SubElement(operation, name).text = str(value)

    connection = http.client.HTTPConnection(ROUTER_IP, ROUTER_PORT, timeout=8)
    try:
        connection.request(
            "POST",
            CONTROL_PATH,
            body=ET.tostring(envelope, encoding="utf-8", xml_declaration=True),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPAction": f'"{SERVICE}#{action}"',
            },
        )
        response = connection.getresponse()
        data = response.read()
    finally:
        connection.close()

    root = ET.fromstring(data)
    if response.status >= 400:
        raise UpnpFault(local_text(root, "errorCode"), local_text(root, "errorDescription"))
    values = {}
    response_name = f"{action}Response"
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == response_name:
            values = {child.tag.rsplit("}", 1)[-1]: child.text or "" for child in element}
            break
    return values


def save_state(state):
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    temporary.replace(STATE_FILE)


def add_pinhole(client, port):
    result = call(
        "AddPinhole",
        {
            "RemoteHost": "::",
            "RemotePort": 0,
            "InternalClient": client,
            "InternalPort": port,
            "Protocol": 6,
            "LeaseTime": LEASE_SECONDS,
        },
    )
    unique_id = result.get("UniqueID")
    if not unique_id:
        raise RuntimeError(f"The router returned no pinhole ID for TCP {port}")
    return unique_id


def main():
    status = call("GetFirewallStatus")
    if status.get("FirewallEnabled") != "1" or status.get("InboundPinholeAllowed") != "1":
        raise RuntimeError("The router does not currently allow inbound IPv6 pinholes")

    client = find_server_ipv6()
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {}
    if state.get("client") != client:
        for unique_id in state.get("pinholes", {}).values():
            try:
                call("DeletePinhole", {"UniqueID": unique_id})
            except UpnpFault:
                pass
        state = {"client": client, "pinholes": {}}

    pinholes = state.setdefault("pinholes", {})
    for port in PORTS:
        unique_id = pinholes.get(str(port))
        if unique_id:
            try:
                call("UpdatePinhole", {"UniqueID": unique_id, "NewLeaseTime": LEASE_SECONDS})
                continue
            except UpnpFault as error:
                if error.code not in ("714", "716", "718"):
                    raise
                try:
                    call("DeletePinhole", {"UniqueID": unique_id})
                except UpnpFault:
                    pass
        pinholes[str(port)] = add_pinhole(client, port)

    save_state(state)
    print(f"IPv6 TCP 80/443 pinholes active for {client}; lease renewed for 24 hours.")


if __name__ == "__main__":
    main()
