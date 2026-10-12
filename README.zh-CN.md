# slash

自托管的个人 Android Agent。后端是 Linux 上的 Redroid，通过无障碍树和截图操作手机 App。英文说明和命令见 [README.md](README.md)。使用前读 [DISCLAIMER.md](DISCLAIMER.md)。

## 快速上手

```bash
sudo ./host/install.sh
./host/check.sh --json
sudo docker compose --env-file deploy/compose/.env.example \
  -f deploy/compose/docker-compose.yml up -d
adb connect 127.0.0.1:5601
adb shell getprop sys.boot_completed
```

ADB 只绑定 `127.0.0.1`。多实例示例是 `deploy/compose/docker-compose.multi.yml`。上面的命令只起 `phone-u1`。接管流是另一个 profile：

```bash
sudo docker compose --profile takeover -f deploy/compose/docker-compose.yml up -d --build ws-scrcpy
```

镜像按 `third_party/ws-scrcpy/PIN` 在构建时拉取上游，仓库里不放 `node_modules`。Caddy 配置在 `deploy/caddy/Caddyfile`。

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp examples/config.example.yaml config.yaml
.venv/bin/slash device create u1 --config config.yaml
.venv/bin/slash run u1 "打开设置并搜索显示" --config config.yaml
.venv/bin/slash serve --config config.yaml
```

浏览器打开 `http://127.0.0.1:8787/`。任务遇到 `NEED_HUMAN` 时，面板嵌入 ws-scrcpy，点「交还」后续跑。手动链接：`slash takeover u1 --config config.yaml`。

兼容矩阵模板是 `docs/compat-matrix.md`，数据在 `tests/compat/apps.yaml`。有真机或 Redroid 时：

```bash
SLASH_ADB_SERIAL=127.0.0.1:5601 .venv/bin/pytest tests/integration
.venv/bin/slash compat run
```

没设 `SLASH_ADB_SERIAL` 时，集成测试会跳过，`slash compat run` 只打印模板。

Kubernetes 清单在 `deploy/k8s`（StatefulSet、PVC、ClusterIP、NetworkPolicy）。出口代理是 `deploy/proxy`。加密备份：

```bash
sudo deploy/backup/backup.sh backup --data /srv/slash/devices/u1/data --db /var/lib/slash/slash.db --out /var/backups/u1.tar.gz.enc
```

口令用环境变量 `SLASH_BACKUP_PASSPHRASE`。先停容器再备份。

`devices.backend: physical` 和 `devices.serials` 用来接已经在 adb 上的 USB 手机，不另起容器。

离线测试：`make test`。不需要 Docker 或 adb。安全清单见 `docs/security.md`。
