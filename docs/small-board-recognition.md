# 观战小棋盘与日志优化

分支：`codex/small-board-recognition`。仅提交修复分支，等待实机验收，不合并、不推送。

## 复现与修复

用户提供的天天象棋观战窗口中，旧定位器把右侧头像栏的线条拼进九列网格，
棋盘框向右偏移约一列。正确裁剪同一图片后，原模型即可完整识别 14 个棋子。

- 优先使用网格/外框定位，找不到几何证据时才尝试原有棋子组合。
- 独立外框与九列十行交叉验证，拒绝延伸到头像栏的伪网格。
- 小于 360 像素宽的棋盘使用 cubic 放大，减少细笔画振铃。
- 小图中不确定格点增加紧裁剪及微偏移复核，至少三个高置信结果一致，且平均分布通过原置信度/位置检查才采用。最多复核 16 格，结果进入缓存。
- 裁剪只复制单格，不再为每格反复复制整张棋盘；边缘补齐保持原行为。
- 分辨率过低且识别不确定时建议放大窗口，不放宽门槛、不补造棋子。
- 控制台默认 INFO；逐帧方向判断与引擎原始响应降为 DEBUG。重复消息限频 10 秒，待确认数量波动使用同一限频类别。界面状态更新不受影响，新错误仍显示。

需要完整调试日志时，在启动前设置 `$env:CHESS_LOG_LEVEL = 'DEBUG'`；
恢复普通输出用 `Remove-Item Env:CHESS_LOG_LEVEL -ErrorAction SilentlyContinue`。
本轮不默认开启持续截图存盘。个人 `app/json/game_config.json` 不进入提交。

## 自动测试与回放

```powershell
conda activate chess-helper
python -m unittest discover -s tests -v
python scripts/diagnose_recognition.py tests/fixtures/tt_spectator.png --width 246
```

完整桌面截图先用 `--crop 左 上 宽 高` 指定**游戏窗口**，再加 `--locate`，
可离线测试“自动定位→分类”，无需运行游戏或引擎。例如本次原始截图：

```powershell
python scripts/diagnose_recognition.py C:\path\spectator.png --crop 635 88 501 941 --locate
```

`located_region` 相对于输入图/指定窗口，`source_cell_pixels` 表示源图格距，
`refined_squares` 表示本帧小图复核成功格数。`board_valid` 不会接受仍有疑点的棋盘。
仓库只保存棋盘裁剪图；带头像栏的错误网格候选由测试模拟，不保存账号信息。

## 实机验收

先关闭旧助手，然后：

```powershell
cd D:\qtproject\chess-helper-app
conda activate chess-helper
git switch codex/small-board-recognition
python app/main.py
```

1. 打开天天象棋观战，重新自动定位（必须清除旧偏移框），核对双方所有棋子和位置。
2. 换至少三盘、红方在上/在下分别测试，观察连续落子后的更新。
3. 切换普通对战与观战布局后重新定位，避免沿用旧布局坐标；窗口尺寸不变的内部布局切换尚未自动检测。
4. 适当缩小/放大窗口，测试手动定位木质棋盘外框，排除头像与聊天区域。
5. 稳定画面保持一分钟，终端不应每秒输出方向判断；遮挡再移开，恢复识别但不强行确认错棋盘。
6. 正常对战、JJ 棋盘仍须实机复验；目前真实样本来自天天象棋，不能保证所有皮肤和小尺寸都准确。

首次观战中局静态图不能确定谁走，仍须用「轮次」确认，或等待识别到完整合法落子。
只有你确认使用效果后再讨论合并。
