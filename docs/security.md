# Security

This is the v1 checklist for a single trust domain on one host. It is not a pentest report.

## Checklist

- [ ] `host/check.sh --json` reports no issues. Page size is 4096, binder is loaded, and the process is not inside a container.
- [ ] Redroid ADB ports are `127.0.0.1:5600+n` only. `check.sh` fails if 5555, 5600–5699, or 8000 listen on `0.0.0.0`.
- [ ] ws-scrcpy is published as `127.0.0.1:8000:8000` (`docker compose --profile takeover`). The public path is Caddy `/takeover/<token>/`, which calls `GET /api/v1/takeover/verify` before proxying.
- [ ] Takeover links are HMAC-SHA256 over `device_id|task_id|exp|nonce`, expire in 5 minutes (`takeover.ttl_s`), and are single use. A replay without the HttpOnly cookie is rejected.
- [ ] The API token and HMAC secret are files with mode `0600`, not flags in a process listing. `server.bind` stays on loopback unless TLS terminates in front.
- [ ] APK installs require `expected_cert_sha256`. Pins in `examples/apps.yaml` must match.
- [ ] `confirm_sensitive: true` turns payment, transfer, and account-deletion taps into `NEED_HUMAN`.
- [ ] The planner prompt treats screen text as untrusted data.
- [ ] `data_residency: cn` refuses providers that are not `cn` or `local`. Payment and captcha screenshots are redacted before a non-local provider sees them.
- [ ] Snapshots and `deploy/backup/backup.sh` run only after the container is stopped. The backup passphrase is `SLASH_BACKUP_PASSPHRASE` or a file, and the archive is openssl AES-256-CBC with PBKDF2.
- [ ] `/metrics` is the Prometheus text endpoint (`slash_devices_running`, `slash_device_boot_seconds`, `slash_task_steps_total`, `slash_task_success_ratio`, `slash_llm_tokens_total`, `slash_llm_cost_cny_total`). Do not expose it on a public interface.
- [ ] Kubernetes: privileged StatefulSet, PVC for `/data`, Service type ClusterIP, `NetworkPolicy` allowing TCP 5555 only from `slashd` and `ws-scrcpy`, node selector `slash.dev/binder=true`.
- [ ] One host is one trust domain. A privileged container is close to host root. Do not colocate untrusted tenants.
- [ ] Audit recordings from `screenrecord` (180 second segments) live under the blob directory. Treat them as account data.

## What this does not do

slash does not hide that the device is a container, does not pass Play Integrity, and does not store account passwords. Login stays on the takeover page or `POST /api/v1/tasks/{id}:reply`.

See also `SECURITY.md` and `docs/compliance.zh.md`.
