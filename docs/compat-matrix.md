# Compatibility matrix

Template from `tests/compat/apps.yaml`. `slash compat run` fills Install and Launch
when `SLASH_ADB_SERIAL` points at a booted Redroid. Login, the basic task, and cost
stay `not run` until a person finishes them. This file is not a measurement.

| App | Package | Mode | Install | Launch | Login | Basic task | Cost | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 淘宝 | `com.taobao.taobao` | tree+vision | not run | not run | not run | not run | not run | 打开首页并搜索机械键盘，返回前三个价格 |
| 京东 | `com.jingdong.app.mall` | tree+vision | not run | not run | not run | not run | not run | 打开首页并搜索机械键盘 |
| 拼多多 | `com.xunmeng.pinduoduo` | tree+vision | not run | not run | not run | not run | not run | 打开首页 |
| 美团 | `com.sankuai.meituan` | tree+vision | not run | not run | not run | not run | not run | 打开首页 |
| 饿了么 | `me.ele` | tree+vision | not run | not run | not run | not run | not run | 打开首页 |
| 抖音 | `com.ss.android.ugc.aweme` | vision-only | not run | not run | not run | not run | not run | 界面树经常不完整，默认视觉模式 |
| 快手 | `com.smile.gifmaker` | tree+vision | not run | not run | not run | not run | not run | 打开首页 |
| 小红书 | `com.xingin.xhs` | tree+vision | not run | not run | not run | not run | not run | 打开首页并搜索机械键盘 |
| 哔哩哔哩 | `tv.danmaku.bili` | tree+vision | not run | not run | not run | not run | not run | 打开首页 |
| 高德地图 | `com.autonavi.minimap` | tree+vision | not run | not run | not run | not run | not run | 打开地图首页 |
| 百度地图 | `com.baidu.BaiduMap` | tree+vision | not run | not run | not run | not run | not run | 打开地图首页 |
| 微信 | `com.tencent.mm` | vision-only | not run | not run | not run | not run | not run | 高风险，树不完整；登录只走人工接管 |
| 支付宝 | `com.eg.android.AlipayGphone` | vision-only | not run | not run | not run | not run | not run | 支付确认必须 ask_human；不在自动化成功标准里 |
| 网易云音乐 | `com.netease.cloudmusic` | tree+vision | not run | not run | not run | not run | not run | 打开首页 |
| 菜鸟 | `com.cainiao.wireless` | tree+vision | not run | not run | not run | not run | not run | 打开首页 |
| 铁路12306 | `com.MobileTicket` | tree+vision | not run | not run | not run | not run | not run | 不提供抢票 |
