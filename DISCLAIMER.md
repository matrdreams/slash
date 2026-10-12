# 免责声明

slash 只适合操作**你自己的账号**。多数 App 的用户协议禁止自动化、模拟器和外挂，有封号风险。本项目不提供批量注册、刷量、抢购、爬取，也不对接接码平台。

不要把 ADB 或 ws-scrcpy 暴露到公网。privileged 容器接近宿主 root，一台机器只放一个信任域。接管期间的录屏是账户数据，和 `/data` 一样要加密保存。v1 是单信任域，不是多租户隔离。

截图默认按 `data_residency: cn` 只发给境内或本机模型。这不是法律意见。详见 `docs/compliance.zh.md`。

# Disclaimer

slash is for operating **your own accounts**. Many apps forbid automation and emulators in their terms of service, and accounts can be banned. This project does not offer bulk signup, fake engagement, scalping, scraping, or SMS-code resale.

Do not publish ADB or ws-scrcpy on a public address. A privileged container is close to host root; keep one trust domain per machine. Screen recordings taken during takeover are account data and should be stored encrypted, same as `/data`. v1 is one trust domain, not tenant isolation.

With `data_residency: cn`, screenshots are sent only to providers marked `cn` or `local`. This is not legal advice.
