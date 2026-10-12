# Security notes

See also the repository `SECURITY.md`.

`check.sh` fails when:

- the kernel page size is not 4096
- binder is missing
- the process is inside a container (`systemd-detect-virt` starts with `container`)
- ports 5555 or 5600–5699 listen on `0.0.0.0`

Snapshots stop the container first so SQLite files in `/data` are not copied while open.
