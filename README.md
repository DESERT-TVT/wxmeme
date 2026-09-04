# wxmeme

把微信里已经能看到的表情包，收集成 GIF / PNG / WebP，下载后给 QQ、Telegram、Discord 等软件用。

包含两部分：

1. **浏览器插件**：在微信网页版、公众号文章等页面上，给表情图加下载按钮，并打包成 ZIP。
2. **本地导出工具**：只读取微信「我的表情」面板，按面板顺序导出其中已经是明文的图片，复制到 `~/Downloads/wxmeme/library`。

不会解密微信 4.x 的加密缓存，也不会接入非官方接口去扒表情商店。

表情包通常有版权，请只用于个人备份和自己已经有权使用的内容。

## 安装浏览器插件

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

只读用户自己收藏的表情库，顺序来自 `fav.archive` 或解密后的 `emoticon.db`。

```bash
pip3 install -r exporter/requirements.txt
python3 exporter/wxmeme.py --scan-only
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

# Mac 读不到内存时的替代方案：直接从 CDN 下载（推荐）
python3 exporter/wxmeme.py --cdn --scan-only

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
extension/     Chrome / Edge 插件
exporter/      本地缓存导出
```
