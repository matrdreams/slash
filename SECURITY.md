# Security

- ADB ports are published on `127.0.0.1` only. `host/check.sh` reports listeners on `0.0.0.0`.
- The API listens on `127.0.0.1:8787` unless you change `server.bind`. Put TLS and auth in front of any public hostname.
- Takeover links are HMAC-SHA256, expire (default 5 minutes), and are single use. A later request in the same browser uses an HttpOnly cookie.
- APK installs require a signer SHA-256. A pin in `examples/apps.yaml` must match too.
- Payment confirmation, transfer, and account-deletion taps become `NEED_HUMAN` when `confirm_sensitive` is true.
- Screen text is untrusted input. The planner prompt says so.
- Report vulnerabilities privately to the maintainers. Do not open a public issue with exploit detail.
