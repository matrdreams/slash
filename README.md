# slash

自托管的个人 Android Agent。手机跑在 Linux 上的 Redroid（Docker 里的 Android）里，Agent 读无障碍树和截图，再用 adb 操作 App。优先支持只有 ARM 包、没有网页版的国产 App。

A self-hosted personal Android agent. The phone is Redroid (Android in Docker) on Linux. The agent reads the accessibility tree and a screenshot, then acts through adb. The interesting targets are ARM-only apps that have no web version.

只操作你自己的账号。读 [DISCLAIMER.md](DISCLAIMER.md)。ADB 只监听 `127.0.0.1`。

Only drive your own accounts. Read [DISCLAIMER.md](DISCLAIMER.md). ADB listens on `127.0.0.1` only.

## 中文

### 它做什么

1. `host/install.sh` 安装 adb、Docker，并加载 `binder_linux`（重启后仍会加载）。
2. `deploy/compose` 起一台或多台 Redroid。端口形如 `127.0.0.1:5601:5555`。
3. `slash device` 创建、启动、停止、删除实例，做快照，并在校验签名后安装 APK。
4. `slash run` 跑任务循环：观察 → 模型给出一个 JSON 动作 → 执行。中文输入走 ADBKeyBoard 的 `ADB_INPUT_B64`。
5. 遇到验证码或敏感按钮时任务变成 `NEED_HUMAN`，并给出 5 分钟、一次性的接管链接。交还（`POST /api/v1/takeover/{id}:release` 或面板上的「交还」）会停掉录屏并让 Agent 继续。
6. `slash serve` 在 `/` 提供任务面板：任务列表、步骤截图，以及接管时嵌入的 ws-scrcpy 画面。
7. `tests/compat` 是兼容矩阵的探测脚本。`deploy/k8s` 是 StatefulSet + PVC。`deploy/backup/backup.sh` 加密备份已停止实例的数据。

### 快速上手（Ubuntu 22.04 / 24.04，ARM64 优先）

```bash
sudo ./host/install.sh
./host/check.sh --json
sudo docker compose --env-file deploy/compose/.env.example \
  -f deploy/compose/docker-compose.yml up -d phone-u1
adb connect 127.0.0.1:5601
adb shell getprop sys.boot_completed   # 输出 1
```

接管画面（可选，第一次会按 `third_party/ws-scrcpy/PIN` 构建镜像，不把 `node_modules` 放进仓库）：

```bash
sudo docker compose --env-file deploy/compose/.env.example \
  --profile takeover -f deploy/compose/docker-compose.yml up -d --build ws-scrcpy
```

ws-scrcpy 只监听 `127.0.0.1:8000`，通过宿主上的 adb server 看到手机。对外用 `deploy/caddy/Caddyfile`：`/takeover/<token>/` 先经 slashd 校验一次性签名，再反代到 ws-scrcpy。

x86_64 开发机用 KVM 虚拟机：`dev/qemu/make-x86-vm.sh`（必须有 `/dev/kvm`）。ARM64 虚拟机是 `dev/qemu/make-arm64-vm.sh`：在 ARM 宿主机上走 KVM，在 x86 上只能 TCG，很慢。

控制面：

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp examples/config.example.yaml config.yaml
# 编辑 db 路径、token 和模型名。境内默认 data_residency: cn
.venv/bin/slash device create u1 --config config.yaml
.venv/bin/slash run u1 "打开设置并搜索显示" --config config.yaml
.venv/bin/slash serve --config config.yaml
# 浏览器打开 http://127.0.0.1:8787/ ，填入 API token
.venv/bin/slash takeover u1 --config config.yaml
.venv/bin/slash compat run
```

API 前缀 `/api/v1`，鉴权 `Authorization: Bearer <token>`。交互文档在 `/docs`（OpenAPI）。Prometheus 文本在 `/metrics`。

`devices.backend: physical` 配 `devices.serials.<name>` 时不启容器，直接用已经连上的 adb（USB 真机或已有的端口转发）。

没有 Docker 时把 `devices.backend` 设为 `fake`，`llm.providers.*.kind` 设为 `scripted`，可以离线跑通循环。单元测试就是这样做的。

### 开发与测试（L0）

容器和 macOS 上跑不了 Redroid（没有 binder）。单元测试、API 和回放不需要它们：

```bash
make dev
make test
make lint
```

集成测试默认跳过。有一台已启动的 Redroid 时：

```bash
SLASH_ADB_SERIAL=127.0.0.1:5601 .venv/bin/pytest tests/integration
SLASH_ADB_SERIAL=127.0.0.1:5601 .venv/bin/slash compat run
```

`tests/integration` 会检查 `sys.boot_completed`、截图、uiautomator dump、点击和 Home 键；装了 ADBKeyBoard 才会发中文广播。

### 配置

见 `examples/config.example.yaml`。模型名和价格写在配置里。`data_residency: cn` 时只能用 `region: cn` 或 `region: local` 的提供方。Qwen 兼容模式默认地址是 DashScope 的 `/compatible-mode/v1`，用 `kind: qwen` 且留空 `base_url` 即可。

## English

### What it does

1. `host/install.sh` installs adb and Docker and loads `binder_linux` so it comes back after reboot.
2. `deploy/compose` starts one or more Redroid containers. Published ports look like `127.0.0.1:5601:5555`.
3. `slash device` creates, starts, stops, and deletes instances, snapshots `/data`, and installs an APK only after the signer certificate matches.
4. `slash run` loops: observe, ask the model for one JSON action, execute it. Chinese text is sent with ADBKeyBoard `ADB_INPUT_B64`, not `input text`.
5. A captcha or a sensitive button moves the task to `NEED_HUMAN` and returns a 5-minute, single-use takeover link. Handing it back (`POST /api/v1/takeover/{id}:release`, or the panel button) stops the recording and resumes the agent.
6. `slash serve` hosts a task panel at `/`: the task list, step screenshots, and the ws-scrcpy picture while a person has the device.
7. `tests/compat` probes the compatibility matrix. `deploy/k8s` is a StatefulSet plus a PVC. `deploy/backup/backup.sh` encrypts a stopped device's data directory.

### Quick start (Ubuntu 22.04 / 24.04, ARM64 first)

```bash
sudo ./host/install.sh
./host/check.sh --json
sudo docker compose --env-file deploy/compose/.env.example \
  -f deploy/compose/docker-compose.yml up -d phone-u1
adb connect 127.0.0.1:5601
adb shell getprop sys.boot_completed   # prints 1
```

Optional takeover stream. The first build fetches the commit in `third_party/ws-scrcpy/PIN`. `node_modules` stay inside the image.

```bash
sudo docker compose --env-file deploy/compose/.env.example \
  --profile takeover -f deploy/compose/docker-compose.yml up -d --build ws-scrcpy
```

ws-scrcpy listens on `127.0.0.1:8000` and uses the host adb server. `deploy/caddy/Caddyfile` checks the one-time signature at slashd, then proxies `/takeover/<token>/` to that port.

For day-to-day work on x86_64, boot an Ubuntu VM with KVM: `dev/qemu/make-x86-vm.sh` (it exits if `/dev/kvm` is missing). `dev/qemu/make-arm64-vm.sh` uses KVM on an arm64 host and TCG on x86, which is too slow for app tests.

Control plane:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp examples/config.example.yaml config.yaml
.venv/bin/slash device create u1 --config config.yaml
.venv/bin/slash run u1 "Open Settings and search for Display" --config config.yaml
.venv/bin/slash serve --config config.yaml
# open http://127.0.0.1:8787/ and paste the API token
.venv/bin/slash takeover u1 --config config.yaml
.venv/bin/slash compat run
```

The API is under `/api/v1` with `Authorization: Bearer <token>`. Interactive OpenAPI is at `/docs`. Prometheus text is at `/metrics`.

`devices.backend: physical` plus `devices.serials.<name>` skips containers and uses an adb serial that is already connected (a USB phone or an existing forward).

Set `devices.backend: fake` and a `scripted` provider to run the loop with no Docker. That is what the unit tests do.

### Tests (L0)

```bash
make dev
make test
make lint
```

Integration tests stay skipped until a device is up:

```bash
SLASH_ADB_SERIAL=127.0.0.1:5601 .venv/bin/pytest tests/integration
SLASH_ADB_SERIAL=127.0.0.1:5601 .venv/bin/slash compat run
```

`tests/integration` checks `sys.boot_completed`, a PNG screenshot, a parsed uiautomator dump, tap, and HOME. The ADBKeyBoard broadcast runs only when that IME is installed.

### Configuration

`examples/config.example.yaml` is the template. Model ids live in that file. With `data_residency: cn`, a provider must be `region: cn` or `region: local`. `kind: qwen` with an empty `base_url` uses DashScope's OpenAI-compatible endpoint.

## Layout

`host/` `images/` `deploy/` `dev/qemu/` `slash/` `web/` `third_party/ws-scrcpy/` `tests/` `examples/` `docs/`

More detail: [docs/architecture.md](docs/architecture.md), [docs/security.md](docs/security.md), [docs/compat-matrix.md](docs/compat-matrix.md), [docs/release-checklist.md](docs/release-checklist.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
