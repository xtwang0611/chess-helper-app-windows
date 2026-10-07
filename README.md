
# 象棋助手 (Chess Helper)

> Windows 兼容适配版。基于 [YoungerIOS/chess-helper-app](https://github.com/YoungerIOS/chess-helper-app) 修改，感谢原作者 YoungerIOS 及原项目贡献者。
>
> 本分支新增 Windows 依赖清单、Pikafish Windows 引擎接入，以及天天象棋窄窗口和 Windows 截图坐标兼容。

一款智能的中国象棋辅助工具，支持微信小程序平台 **JJ象棋** 和 **天天象棋** 直接使用，无需使用改造的官方客户端，无封号风险。利用计算机视觉技术和强大的Pikafish象棋引擎，为您提供实时的局势分析与着法推荐。

---

## 📸 功能演示 (Demo)

### 自动识别与实时分析
程序能够自动检测游戏窗口，精准定位棋盘，并实时显示最佳着法路线。
![实时分析演示](demo.gif)

计算速度快，引擎参数可调。
![窗口跟随演示](demo_2.gif)

---

## ✨ 主要功能 (Key Features)

-   **🤖 全自动平台检测**:
    -   无需手动选择，自动识别当前运行的游戏（支持 JJ象棋、天天象棋）。
    -   支持断线重连，游戏重启后自动恢复分析。

-   **🎯 动态棋盘定位**:
    -   **4K/Retina 支持**: 完美适配高分辨率屏幕，坐标识别精准。
    -   **智能跟随**: 窗口移动或缩放时，自动计算新的棋盘区域，无需人工干预。
    -   **抗干扰**: 采用霍夫圆变换与颜色过滤算法，排除背景干扰，精准锁定棋子。

-   **💡 强大引擎内核**:
    -   内置高性能 **Pikafish** 象棋引擎。
    -   支持 **深度优先**与**时间优先**两种分析模式。
    -   可自定义思考层数与时间限制，满足不同场景需求。

-   **🛡️ 稳健运行**:
    -   **防误触机制**: 智能识别结算画面与异常遮挡，避免错误着法推荐。
    -   **多线程架构**: 界面流畅，分析过程不卡顿。

---

## 🛠️ 安装与使用 (Installation & Usage)

### 环境要求
-   macOS 12+ (支持 Intel 与 Apple Silicon)
-   Python 3.10+
-   Windows 10/11（Windows 适配建议使用 Python 3.11）

### 快速开始
-   下载安装客户端dmg文件

### 自行编译
-   若有兴趣和技术能力，可以参考Pikafish开源引擎文档，自行编译Windows平台的引擎文件：https://github.com/official-pikafish/Pikafish
-   将编译好的引擎文件中的src目录放入本项目`chess-helper-app/app/Pikafish`目录下
-   下载本项目，安装依赖，执行`pip install -r requirements.txt`
-   运行`python app/main.py`即可使用
-   如有需要，可以使用`pyinstaller ChessHelper.spec --noconfirm`打包客户端

### Windows 运行方法

1. 建议创建 Python 3.11 环境并安装 Windows 依赖：

   ```powershell
   conda create -n chess-helper python=3.11
   conda activate chess-helper
   pip install -r requirements-windows.txt
   ```

2. 从 [Pikafish 官方发布页](https://github.com/official-pikafish/Pikafish/releases) 下载 Windows x86-64 universal 版本，将文件整理为：

   ```text
   app/Pikafish/src/pikafish.exe
   app/Pikafish/src/pikafish
   app/Pikafish/src/pikafish.nnue
   ```

   其中无扩展名的 `pikafish` 可由 Windows 可执行文件复制得到：

   ```powershell
   Copy-Item '.\app\Pikafish\src\pikafish.exe' '.\app\Pikafish\src\pikafish'
   ```

3. 启动程序：

   ```powershell
   python .\app\main.py
   ```

Pikafish 文件不包含在本仓库中，请从官方项目获取。请仅将本项目用于合法、合规的学习和本地分析场景。

---

## 🤝 贡献与反馈
欢迎提交 Issue 或 Pull Request 来帮助改进这个项目！

## 📄 许可证

原项目及本项目代码采用根目录 `LICENSE` 所载的木兰宽松许可证第 2 版（Mulan PSL v2），并保留原项目的版权及免责声明。原 README 中的 MIT 表述与根目录许可证不一致，本适配版以根目录 `LICENSE` 为准。

Pikafish 是独立的第三方项目，其引擎采用 GNU GPL v3；NNUE 权重文件另有其官方许可条件。分发或使用相关文件前，请查阅 [Pikafish 项目](https://github.com/official-pikafish/Pikafish) 和 [Networks 项目](https://github.com/official-pikafish/Networks) 的许可证说明。
