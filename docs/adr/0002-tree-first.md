# ADR 0002: Tree first

The default observation mode is `tree+vision`. The accessibility tree is cheaper and more stable than a screenshot-only model. `vision-only` remains available when the tree is empty (WeChat, Flutter, WebView). Coordinates from a model are converted to device pixels before `input tap`.
