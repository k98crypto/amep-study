# AMEPOnline LAN Proxy

This project provides a LAN-only forward proxy for the official AMEPOnline site. It does not download, mirror, modify, or cache course pages or files. Your browser continues to connect to the original AMEPOnline hostname through the Ubuntu server.

## Access

- Proxy auto-config (PAC): `http://192.168.10.10:8090/amep.pac`
- Manual HTTP proxy: `192.168.10.10`, port `3128`
- Official site: `https://ameponline.homeaffairs.gov.au/`

Set the browser's automatic proxy configuration to the PAC URL above. The PAC sends only AMEPOnline traffic through the proxy; all other sites remain direct. The proxy permits only LAN clients and the AMEPOnline domain. Do not expose either port through router port forwarding.

## Ubuntu deployment

Copy this folder to the Ubuntu server, then run from this directory:

```sh
docker compose -f compose.yml up -d
docker compose -f compose.yml ps
```

The Compose stack uses `ubuntu/squid` for HTTPS tunnelling and `nginx` to serve the PAC file. There is no persistent data volume and Squid request logging and caching are disabled.

## Update or stop

```sh
docker compose -f compose.yml pull
docker compose -f compose.yml up -d
docker compose -f compose.yml down
```

If the upstream site changes domains, update the Squid allowlist and PAC file together after verifying the new hostname from the official site.
