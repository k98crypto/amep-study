# AMEPOnline HTTPS Access

This service gives a family member an authenticated AMEPOnline entry point and a separate study-progress tracker:

- Official AMEPOnline: `https://LWA.spiritwave.dpdns.org/`
- Progress tracker: `https://study.spiritwave.dpdns.org/`
- Authentication: personal accounts created on the study site, with private per-account progress
- Upstream: `https://ameponline.homeaffairs.gov.au/`

The official-site endpoint forwards requests to AMEPOnline. It does not download, archive, or cache course pages or files, and it preserves the official site's content and branding. The Nginx layer rewrites official-host URLs, redirects, and cookie domains so navigation stays on the HTTPS entry point. The proxy sends the browser's User-Agent to the official site and omits client IP forwarding headers.

The tracker stores learning records in a local SQLite database on Ubuntu. It supports starting with an empty record list, adding progress manually, exporting records, and importing JSON generated from visible course-progress information in the browser. The importer does not read cookies, passwords, or login tokens. Browser import is a user-confirmed download from the original site followed by an upload to the tracker.

Each person creates an account on the study site. The password reset flow uses a recovery code shown once during registration; each reset rotates the code and shows its replacement. No email service is required. Registration is limited to five accounts.

To import from AMEPOnline, open the tracker, show the import panel, drag the `AMEP 进度导出书签` link to the browser's bookmarks bar, then open a progress page on the official-site endpoint and click that bookmark. It downloads only visible course and completion fields as JSON. Return to the tracker, select the file, review the count, and confirm the import. If the page does not expose a progress table or progress bar, start with an empty tracker or add records manually.

## Ubuntu setup

Copy this project to `~/services/ameponline-study`, then run:

```sh
cd ~/services/ameponline-study
docker compose up -d
docker compose ps
```

The account owner chooses a username and password in the browser and saves the one-time recovery code displayed after registration.

Caddy runs on the Ubuntu host network so it can reach the certificate authority. The tracker and upstream proxy bind only to loopback ports `18081` and `18080`. Create proxied CNAME records named `LWA` and `study` targeting `spiritwave1.dpdns.org` in the delegated Cloudflare DNS zone. Inbound TCP ports 80 and 443 must reach the Ubuntu server's public IPv6 address. Caddy requests and renews TLS certificates automatically after the firewall allows those connections.

## Update or stop

```sh
docker compose pull
docker compose up -d
docker compose down
```

Course access remains subject to AMEPOnline's terms and the rights attached to each resource.
