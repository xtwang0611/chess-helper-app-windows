# Windows 解压版（测试版）

适用：Windows 10/11 x64。无需安装 Python、conda、VS Code 或 MaaFramework。
完整解压 ZIP 后双击 `ChessHelper.exe`。必须保留旁边的 `_internal` 目录，不能只复制 exe。
首次打开游戏棋盘后点开始；中残局/观战需要确认轮次。不同皮肤、缩放仍可能识别失败。
本工具用于合规的本地分析和学习，游戏自动化/辅助的使用须遵守平台规则。

配置保存在 `%APPDATA%\ChessHelper\game_config.json`，日志保存在
`%LOCALAPPDATA%\ChessHelper\Logs`。升级时解压到新目录；用户配置独立保留。
启动失败请提供该日志目录里的 `startup-error.txt`，不必截图整个桌面。
发行包尚未签名；不要通过关闭杀毒软件或全局安全防护来解决启动问题。

## 源码与构建

源码仓库：https://github.com/xtwang0611/chess-helper-app-windows
源码方式仍支持 `python app/main.py`；见仓库 README 的 Windows 依赖安装说明。

构建者使用 Python 3.11 x64，安装 `requirements-windows.txt` 及 `pyinstaller==6.16.0`，
下载并解压官方 `Pikafish-2026-09-06` 发布包，然后运行：

```powershell
python scripts/build_windows.py --engine-release-dir C:\path\Pikafish.2026-09-06
```

输出在 `dist/时间-提交号/`。构建不改个人配置，不上传、不创建 Release。
程序包默认带通用 x86-64 引擎，不要求用户自行选择 AVX 指令集版本。
构建脚本同时下载该引擎标签源码、打包许可证与第三方通知，生成版本/散列清单和 ZIP 校验值。
源码提交与二进制分别提供：代码留在 Git 仓库，ZIP 放 GitHub Releases（需单独审核后发布）。

## 第三方组件

项目自身遵循 Mulan PSL v2，见 `licenses/ChessHelper-LICENSE.txt`。
Pikafish 为独立 UCI 子进程，GPLv3 文本、作者与对应标签源码位于 `licenses/Pikafish`。
NNUE 权重具有单独限制（包括未经许可不得商用），见其中 `NNUE-License.md`。
Qt/PySide6 动态库随包分发，不能移除其许可证、通知或限制用户依法替换/调试这些库。
Python 依赖的许可材料及构建环境版本清单在 `licenses/python` 和 `python-environment.json`。
Qt/PySide6 对应源码可从 https://download.qt.io/official_releases/ 和
https://code.qt.io/cgit/pyside/pyside-setup.git/ 获取；Python 源码见 https://www.python.org/downloads/source/ 。
公开发布前还须在干净 Windows 环境验收，并核对完整分发材料，不能把本地通过等同于全面兼容。

## 发布前验收

1. 无 Python/conda 的 Windows 10/11 x64 普通用户环境，中文和空格目录均可解压启动。
2. TT/JJ 模型加载，普通对战/观战显示棋子，Pikafish 返回着法。
3. 关闭后重开，设置保留；解压目录无需管理员写权限。
4. 网络断开仍能启动和分析；测试停止、退出、窗口遮挡和恢复。
5. 保留引擎源码、第三方许可、散列文件；公开仓库保留本版本助手源码。

自动离线检查（不截图、不点击游戏，会初始化用户配置；建议使用独立测试账户）：

```powershell
.\ChessHelper.exe --self-test C:\path\self-test.json
```

成功生成 `ok: true` 的报告；失败返回非零退出码，并写启动错误日志。
