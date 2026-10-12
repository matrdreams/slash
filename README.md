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
5. 遇到验证码或敏感按钮时任务变成 `NEED_HUMAN`，并给出 5 分钟、一次性的接管链接。

### 快速上手（Ubuntu 22.04 / 24.04，ARM64 优先）

```bash
sudo ./host/install.sh
./host/check.sh --json
sudo docker compose --env-file deploy/compose/.env.example \
  -f deploy/compose/docker-compose.yml up -d
adb connect 127.0.0.1:5601
adb shell getprop sys.boot_completed   # 输出 1
```

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
```

API 前缀 `/api/v1`，鉴权 `Authorization: Bearer <token>`。交互文档在 `/docs`（OpenAPI）。

没有 Docker 时把 `devices.backend` 设为 `fake`，`llm.providers.*.kind` 设为 `scripted`，可以离线跑通循环。单元测试就是这样做的。

### 开发与测试（L0）

容器和 macOS 上跑不了 Redroid（没有 binder）。单元测试、API 和回放不需要它们：

```bash
make dev
make test
make lint
```

### 配置

见 `examples/config.example.yaml`。模型名和价格写在配置里。`data_residency: cn` 时只能用 `region: cn` 或 `region: local` 的提供方。Qwen 兼容模式默认地址是 DashScope 的 `/compatible-mode/v1`，用 `kind: qwen` 且留空 `base_url` 即可。

## English

### What it does

1. `host/install.sh` installs adb and Docker and loads `binder_linux` so it comes back after reboot.
2. `deploy/compose` starts one or more Redroid containers. Published ports look like `127.0.0.1:5601:5555`.
3. `slash device` creates, starts, stops, and deletes instances, snapshots `/data`, and installs an APK only after the signer certificate matches.
4. `slash run` loops: observe, ask the model for one JSON action, execute it. Chinese text is sent with ADBKeyBoard `ADB_INPUT_B64`, not `input text`.
5. A captcha or a sensitive button moves the task to `NEED_HUMAN` and returns a 5-minute, single-use takeover link.

### Quick start (Ubuntu 22.04 / 24.04, ARM64 first)

```bash
sudo ./host/install.sh
./host/check.sh --json
sudo docker compose --env-file deploy/compose/.env.example \
  -f deploy/compose/docker-compose.yml up -d
adb connect 127.0.0.1:5601
adb shell getprop sys.boot_completed   # prints 1
```

For day-to-day work on x86_64, boot an Ubuntu VM with KVM: `dev/qemu/make-x86-vm.sh` (it exits if `/dev/kvm` is missing). `dev/qemu/make-arm64-vm.sh` uses KVM on an arm64 host and TCG on x86, which is too slow for app tests.

Control plane:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp examples/config.example.yaml config.yaml
.venv/bin/slash device create u1 --config config.yaml
.venv/bin/slash run u1 "Open Settings and search for Display" --config config.yaml
.venv/bin/slash serve --config config.yaml
```

The API is under `/api/v1` with `Authorization: Bearer <token>`. Interactive OpenAPI is at `/docs`.

Set `devices.backend: fake` and a `scripted` provider to run the loop with no Docker. That is what the unit tests do.

### Tests (L0)

```bash
make dev
make test
make lint
```

### Configuration

`examples/config.example.yaml` is the template. Model ids live in that file. With `data_residency: cn`, a provider must be `region: cn` or `region: local`. `kind: qwen` with an empty `base_url` uses DashScope's OpenAI-compatible endpoint.

## Layout

`host/` `images/` `deploy/` `dev/qemu/` `slash/` `tests/` `examples/` `docs/`

## License

Apache-2.0. See [LICENSE](LICENSE).
