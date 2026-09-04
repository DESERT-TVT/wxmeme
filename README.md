# wxmeme

把微信里已经能看到的表情包，收集成 GIF / PNG / WebP，下载后给 QQ、Telegram、Discord 等软件用。

包含两部分：

1. **浏览器插件**：在微信网页版、公众号文章等页面上，给表情图加下载按钮，并打包成 ZIP。
2. **本地导出工具**：只读取微信「我的表情」面板，按面板顺序导出其中已经是明文的图片，复制到 `~/Downloads/wxmeme/library`。

不会解密微信 4.x 的加密缓存，也不会接入非官方接口去扒表情商店。

表情包通常有版权，请只用于个人备份和自己已经有权使用的内容。

## 打包分发

### 浏览器插件（ZIP）

```bash
bash scripts/package-extension.sh
# 输出: dist/wxmeme-extension.zip
```

解压后在 Chrome / Edge 的 `chrome://extensions` 里「加载已解压的扩展程序」。

### macOS App（轻量版）

```bash
bash scripts/build-macos-app.sh
# 输出: dist/wxmeme.app
```

双击 App 可图形化操作：完整导出、快速导出、打开预览、打开文件夹。  
需要本机已安装 **Python 3**（App 首次运行会自动创建 venv 并安装依赖）。

### macOS App（PyInstaller 独立版，推荐分发）

```bash
bash scripts/build-standalone-app.sh
# 输出: dist/wxmeme-standalone.app
```

内置 Python 与依赖，**无需本机安装 Python**。独立版启动后会在 **App 窗口内** 显示表情预览，支持单个下载与「打包下载 ZIP」。首次打开约需 **1–2 分钟** 完成导出，请耐心等待。

```bash
open dist/wxmeme-standalone.app
```

> 轻量版 `wxmeme.app` 使用 Tk 图形界面；独立版 `wxmeme-standalone.app` 使用 App 内嵌预览窗口。

### Windows 独立版

在 **Windows 10/11** 上打包（需已安装 [Python 3.9+](https://www.python.org/downloads/) 和 [WebView2 运行时](https://developer.microsoft.com/microsoft-edge/webview2/)）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-standalone-windows.ps1
# 输出: dist/wxmeme-standalone/wxmeme.exe
```

双击 `wxmeme.exe` 即可使用，界面与 macOS 独立版相同（内嵌预览 + 下载）。

**CLI 快速导出：**

```bat
scripts\export-stickers.bat
```

或手动：

```bat
pip install -r exporter\requirements.txt
python exporter\wxmeme.py --cdn --sync-persist --scan-only
```

微信数据目录默认扫描：

- `%USERPROFILE%\Documents\WeChat Files`
- `%USERPROFILE%\Documents\xwechat_files`

也可用环境变量指定：`set WXMEME_WECHAT_ROOT=D:\path\to\wechat`

**Windows 说明：**

| 功能 | 支持情况 |
|------|----------|
| 浏览器插件 | ✅ Chrome / Edge |
| CDN 导出 + 预览 | ✅ |
| 手动 `--db-key` / `--decrypted-db` 同步 | ✅ |
| 一键 `export-stickers.bat` | ✅（有密钥文件时） |
| macOS 专属 LLDB 密钥提取 | ❌ 需自行准备密钥 |
| `--auto-key` 内存扫描 | ❌ 仅 macOS |

导出目录：`%USERPROFILE%\Downloads\wxmeme\library`

**Windows 打包常见问题：**

1. **在 Mac 上运行此脚本会报错** — 必须在 Windows 电脑上打包，Mac 请用 `build-standalone-app.sh`
2. **`python` 找不到** — 安装 Python 时勾选 “Add python.exe to PATH”，或用 `py -3` 启动
3. **`ExecutionPolicy` 报错** — 用下面完整命令（已含 Bypass）
4. **`pyinstaller` 找不到** — 新脚本已改为 `python -m PyInstaller`，一般不会再出现

```powershell
cd C:\path\to\wxmeme
powershell -ExecutionPolicy Bypass -File scripts\build-standalone-windows.ps1
```

### 一次打包全部（macOS）

```bash
bash scripts/package-all.sh
# 输出: dist/wxmeme-extension.zip
#       dist/wxmeme.app
#       dist/wxmeme-standalone.app
```

## 安装浏览器插件（开发模式）

1. 用 Chrome / Edge 打开 `chrome://extensions`
2. 打开右上角「开发者模式」
3. 点「加载已解压的扩展程序」，选本仓库里的 `extension` 文件夹

## 使用插件

- 打开 [微信网页版](https://wx.qq.com) 或公众号文章
- 表情图右上角会出现绿色下载按钮
- 也可以右键图片 →「保存到 wxmeme 表情库」
- 点工具栏图标，预览后「打包下载」
- 支持拖入本地图片，或 `Cmd+V` 粘贴剪贴板里的图

导出的 ZIP 在浏览器默认下载目录，文件名类似 `wxmeme-2026-09-03.zip`。

## 导出「我的表情」（按面板顺序 + 可选解密）

只读用户自己收藏的表情库。**微信 4.x 的真实顺序在加密的 `emoticon.db` 里**；旧版 `fav.archive` 在迁移后往往不再更新（例如仍停在 7 月快照），所以增删不会反映到导出结果。

```bash
pip3 install -r exporter/requirements.txt
python3 exporter/wxmeme.py --cdn --scan-only
```

### 与微信保持同步（推荐）

完整同步需要解密 `emoticon.db`。**一条命令完成密钥提取 + 导出**：

```bash
bash scripts/export-stickers.sh
```

首次运行会：
1. 克隆 [wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool) 到 `~/Desktop/wcdb-key-tool`
2. 复制并重签名 `~/Applications/WeChat-resigned.app`（之后请用这个微信登录）
3. 提示你在微信里 **退出登录 → 重新登录**（仅首次，用于 LLDB 抓密钥）
4. 自动导出到 `~/Downloads/wxmeme/library`

已有 `all_keys.json` 后，再次运行会跳过密钥提取，直接导出。

手动方式：

```bash
# 方式 1：已有 db_key（wcdb-key-tool 的 all_keys.json）
python3 exporter/wxmeme.py --wcdb-keys --cdn --scan-only

# 方式 2：直接给 db_key
python3 exporter/wxmeme.py --db-key YOUR_64_HEX --cdn --scan-only

# 方式 3：已有明文 emoticon.db
python3 exporter/wxmeme.py --decrypted-db /path/to/emoticon.db --cdn --scan-only
```

**临时方案**（无法解密 db 时）：追加 4.x 本地新缓存到列表末尾，删除仍可能不准：

```bash
python3 exporter/wxmeme.py --cdn --sync-persist --scan-only
```

### 解密更多本地缓存

微信 4.x 的表情文件不是 MSG 同款加密，而是 **AES-128-CBC（key = IV）**：

```text
emoticon_key = md5(f"{seed}{wxid}EMOTICON") 的前 16 字节
```

```bash
# 方式 1：直接给 16 字节密钥
python3 exporter/wxmeme.py --emoticon-key YOUR_32_HEX --scan-only

# 方式 2：seed + wxid 自动派生
python3 exporter/wxmeme.py --seed 123456789 --wxid wxid_xxx_6075 --scan-only

# 验证密钥是否正确
python3 exporter/wxmeme.py --emoticon-key YOUR_32_HEX --verify-key

# macOS：从运行中的微信自动扫 seed（可能需要 sudo + 重签名）
sudo python3 exporter/wxmeme.py --auto-key --scan-only

# Mac 读不到内存时的替代方案：CDN + 近似同步
python3 exporter/wxmeme.py --cdn --sync-persist --scan-only

# 只查看扫到的 seed / key
python3 exporter/wxmeme.py --scan-seed
```

`emoticon.db` 使用 **SQLCipher 4**（和 Windows MSG*.db 不是同一套参数）：

```bash
python3 exporter/wxmeme.py --db-key YOUR_64_HEX_RAW_KEY --scan-only
```

已有明文 `emoticon.db` 时：

```bash
python3 exporter/wxmeme.py --decrypted-db /path/to/emoticon.db --scan-only
```

### Windows MSG*.db（参考你提供的脚本）

```bash
python3 exporter/wxmeme.py \
  --msg-key YOUR_HEX_PASSWORD \
  --decrypt-msg-dir "D:/ChatStorage/WeChat Files/xx/Msg/Multi" \
  --msg-output-dir "./decoded_msg" \
  --msg-talker wxid_xxx
```

导出文件名按面板位置编号，例如 `001.webp`、`004.gif`。

## 目录

```
app/           图形界面（macOS / Windows 独立版）
dist/          打包输出（插件 ZIP、wxmeme.app / wxmeme.exe）
extension/     Chrome / Edge 插件
exporter/      本地缓存导出
scripts/       打包与一键导出脚本
```
