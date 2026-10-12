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

ADB 只绑定 `127.0.0.1`。多实例示例是 `deploy/compose/docker-compose.multi.yml`。

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp examples/config.example.yaml config.yaml
.venv/bin/slash device create u1 --config config.yaml
.venv/bin/slash run u1 "打开设置并搜索显示" --config config.yaml
.venv/bin/slash serve --config config.yaml
```

离线测试：`make test`。不需要 Docker 或 adb。
