# wx-chat-export — 微信聊天记录查看 / 合集 / 导出（前后端）

在页面上直接浏览本地解密后的聊天记录，把任意几段消息**加入合集并写评论**，
或按好友/群聊**导出为 HTML（聊天气泡样式）/ CSV / JSON**。
支持微信 **4.0 ~ 4.1.x**（Windows，进程名 `Weixin.exe`），前后端架构，可部署到服务器。

> ⚠️ **仅供浏览与备份本人登录账号的本地数据**。工具只读微信进程内存与数据库文件，
> 不注入、不修改微信文件、不产生网络请求。请勿用于他人账号或非法用途。

---

## 使用（本机）

1. 双击 `run.bat`（首次运行自动创建 `.venv` 并安装依赖，全部写在本项目目录内）；
2. 浏览器自动打开 `http://127.0.0.1:8542`；
3. 保持微信登录状态 → 顶部选账号，点 **提取密钥并解密**（约 1 分钟）；
4. 四个标签页：
   - **聊天查看**：左侧选人，右侧直接翻聊天记录（自动从最新往前加载，滚到顶自动加载更早）；
     点气泡旁的圆圈选中消息（支持 Shift 范围选），底部「加入合集」挑选/新建合集并附评论；
   - **导出**：搜索勾选联系人，选格式批量导出（多人自动打 ZIP）；
   - **我的合集**：管理收藏片段——改评论、移除、删除，导出带评论的 HTML/JSON；
   - **分析**：任选一个聊天，查看消息总数/自己发送占比/活跃天数/时间范围/发送者 TOP10/
     按月、按小时、按星期分布/消息类型统计。
5. **只把想看的聊天放上网页（客户端→网页模式）**：点右上「⚙」配置网页地址和访问口令，
   然后三选一导入到网页：
   - 聊天头部「导入当前聊天到网页」：把当前打开的聊天全部记录推送过去；
   - 选中若干消息后「导入选中」：只推送选中的那几段；
   - 导出页勾选联系人后「把所选聊天导入网页」：批量推送。
   网页端（服务器）只会出现你导入的这些聊天，不会同步整库。

> 更喜欢桌面软件：本项目提供一个 **PySide6 桌面客户端**（`client.py`），
> 打包成 exe 后双击即用：自动找微信→提取密钥→解密→展示好友列表与聊天，
> 后台**实时监视微信新消息**（每 1.5 秒增量合并 -wal，收到新消息自动刷新，
> 纯只读、无注入、无 hook）。

**💡 AI 回复建议（选配）**：桌面客户端内置「下一句建议」——
点右上 `⚙ AI` 填 OpenAI 兼容 API（默认 DeepSeek，填密钥即可；也支持 OpenAI/通义/智谱/Ollama）。
启用后：选中某个联系人，**对方每次发来新消息会自动让 AI 生成「下一句说啥」**；
首次请求把该聊天全部历史打包给 AI 建立上下文，之后沿用同一对话，越聊越懂你的风格；
也可以随时点聊天区底部「AI 建议」手动生成/换一条。配置存在 `data/ai_config.json`，
上下文按条数滚动，不会无限膨胀。

打包命令：

```bash
.venv\Scripts\python.exe -m pip install PySide6 pyinstaller
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed \
  --name WeChatChatViewer \
  --hidden-import backend.core.memscan --hidden-import backend.core.decrypt \
  --hidden-import backend.core.models --hidden-import backend.core.pipeline \
  --hidden-import backend.core.watcher --hidden-import backend.core.exporter \
  --hidden-import backend.core.collections --hidden-import backend.core.imported_store \
  --hidden-import backend.core.media --hidden-import backend.core.aigen \
  --paths F:\ProgramFiles\微信逆向\wx-chat-export \
  F:\ProgramFiles\微信逆向\wx-chat-export\client.py
```

产物在 `dist/WeChatChatViewer/`，`data/` 目录会创建在 exe 旁边（不写系统盘）。

解密结果缓存在 `data/decrypted/`，之后刷新页面即可直接使用，无需重复提取。
密钥保存在 `data/keys/<账号>.json`（同账号以后可离线解密）。支持深链 `#chat=<wxid>`。

## 部署到服务器（已部署：43.157.9.194）

**当前状态**：已部署在 `/opt/wx-chat-export`，systemd 服务名 `wx-chat`，端口 `8542`，
已启用访问口令（环境变量 `WX_PASSWD`），开机自启、崩溃自动重启。服务器上已带一份
解密数据 + 密钥 + 合集，无需微信即可浏览/导出。

**访问方式（二选一）**：
- 腾讯云控制台防火墙放行 `8542/TCP` 后访问 `http://43.157.9.194:8542`（用户名任意，口令即 WX_PASSWD）；
- 不开端口走 SSH 隧道（更安全）：本机执行
  `ssh -L 8542:127.0.0.1:8542 ubuntu@43.157.9.194`，然后访问 `http://127.0.0.1:8542`。

**常用运维命令**（ssh 登录后）：

```bash
sudo systemctl status wx-chat          # 看状态 / 日志加 -l
sudo systemctl restart wx-chat         # 重启
sudo nano /etc/systemd/system/wx-chat.service   # 改口令/端口后 daemon-reload + restart
```

**同步最新聊天记录**：密钥不变。在本机跑一次「提取密钥并解密」（会合并最新 -wal），
然后重新打包上传数据目录：

```bash
# 本机（Git Bash / WSL）或用任意 SFTP 工具把 data/decrypted、data/keys 上传到服务器对应目录
tar -czf wxdata.tar.gz -C data decrypted keys collections.json
scp wxdata.tar.gz ubuntu@43.157.9.194:/tmp/
# 服务器上
tar -xzf /tmp/wxdata.tar.gz -C /opt/wx-chat-export/data && sudo systemctl restart wx-chat
```

**首次部署（新服务器）**：Ubuntu 24.04 需要 `sudo apt-get install -y python3.12-venv`，
然后项目目录内 `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`，
按上面 systemd 模板创建服务即可。代码目录里有 Windows 专用的内存扫描模块，
在 Linux 上会自动禁用（只做解密与浏览）。

## 工作原理（微信 4.x）

1. **定位数据**：`<微信文件目录>/<wxid>/db_storage/`，全库为 WCDB（SQLCipher）加密 SQLite；
2. **提取密钥**（只读内存扫描）：
   - 4.0.x：明文 `x'<key><salt>'` 字符串直接扫；
   - 4.1+：密钥被固定字节掩码 XOR 混淆存储，按掩码旋转搜索还原；同时尝试
     passphrase 路径（`PBKDF2-HMAC-SHA512(passphrase, 每库salt, 256000)` 派生）；
   - 所有候选一律用数据库第 1 页 HMAC-SHA512 校验，验证通过才采用；
3. **解密**：纯 Python 实现（AES-256-CBC，page 4096，reserve 80），不依赖 pysqlcipher3；
   **合并 -wal 帧**（WCDB 修改了帧头 salt 语义：当前代 = 文件头部第一组同 salt 帧），
   保证最近未 checkpoint 的消息不丢失；
4. **解析**：每个聊天对象一张表（`Msg_` + md5(wxid) 前 32 位），消息内容 zstd 解压，
   发送者经 `Name2Id → contact` 映射为昵称/备注。

## 性能设计

- 联系人列表**服务端过滤 + 分页**（24842 个联系人首屏 59KB/102ms，搜索 44ms），前端虚拟滚动 + 无限加载；
- 聊天记录**分页懒加载**（每次 300 条，滚动到顶部自动补更早的），DOM 不随总量膨胀；
- 解密库以 `immutable=1` 只读打开，零锁零 shm，联系人与消息表结构做运行时自适应缓存。

## 目录结构

```
wx-chat-export/
├── run.bat              # 一键启动
├── requirements.txt
├── backend/
│   ├── main.py          # 入口（uvicorn）
│   ├── app.py           # FastAPI 接口
│   ├── static/index.html# 前端单页（聊天查看/导出/合集）
│   └── core/            # memscan / decrypt / models / exporter / collections / pipeline / jobs
├── data/                # 运行产物（decrypted / exports / keys / collections.json / tmp）
└── tests/               # 端到端自测
```

## 说明与已知限制

- **图片/语音/视频**：4.x 媒体文件单独加密，本工具展示文本、系统消息、链接/文件标题，
  媒体在页面和导出中显示为 `[图片]`/`[语音]` 等占位；
- `session.db`（会话列表）若当前未被微信打开，其密钥可能不在内存中，会自动跳过（不影响导出）；
- 合集数据保存在 `data/collections.json`，条目为消息快照 + 评论，自包含、可随项目迁移；
- 换电脑/重装后若微信提示聊天记录迁移，密钥一般不变；微信大版本更新后需重新提取一次；
- 所有产物与缓存在项目目录内，**不写系统盘**。

## 主要接口

| 接口 | 说明 |
|---|---|
| `GET /api/status` | 微信进程/数据目录/账号状态 |
| `POST /api/extract` | 在线提取密钥并解密 `{account, data_dir?}` |
| `POST /api/decrypt-manual` | 离线解密 `{storage_dir, key, account?}` |
| `GET /api/contacts` | 联系人（服务端过滤+分页：`q/filter/page/page_size`，`usernames_only=1` 取全量 id） |
| `GET /api/messages` | 消息分页（`account/talker/offset/limit`，含发送者映射） |
| `POST /api/export` | 导出 `{account, usernames[], format: html\|csv\|json}` |
| `GET /api/collections` / `POST /api/collections/create` | 合集列表 / 新建 |
| `POST /api/collections/add` | 批量加入消息快照（按 mid 去重） |
| `POST /api/collections/comment` / `remove` / `rename` / `delete` | 评论 / 移除 / 重命名 / 删除 |
| `GET /api/collections/export` | 合集导出 `format=html\|json`（含评论） |
| `GET /api/analyze` | 聊天统计（总数/自占比/时段/发送者/类型等） |
| `POST /api/push` | 客户端推送选中聊天到网页 `{account, server, token, mode, ...}` |
| `POST /api/import` | 网页接收导入（受 Basic 认证保护，数据存 `data/imported/<ns>/`） |
| `POST /api/imported/delete` | 删除一个导入命名空间 |
| `GET /api/media` | 解密图片/表情包（`type=image\|sticker&md5=&variant=`） |
| `POST /api/media/extract-key` | 从微信进程内存提取图片解密密钥 |
| `GET /api/jobs/{id}` | 任务进度/日志 |
| `GET /api/download?path=` | 下载导出文件 |
