# 原神剧情文本库（gi-text）

从 [原神 BWIKI](https://wiki.biligame.com/ys) 抓取全部任务的**剧情文本**，按「任务类型 → 幕/章节 → 子任务」三级结构整理成**纯文本 txt**，产物只此一份，不带任何 Markdown 中间态。

## 数据规模

| 分类 | 幕 | 子任务 |
| --- | --- | --- |
| 魔神任务 | 51 | 230 |
| 传说任务（含部族纪闻/热点事件/邀约） | 89 | 300 |
| 世界任务 | 100 | 661 |
| 游逸旅闻 | 69 | 156 |
| 银月之庭·伴月纪闻 | 4 | 19 |
| 活动任务 | 117 | 453 |
| 委托任务 | 10 | 183 |
| 隐藏任务 | 14 | 85 |
| 其他（突发事件/彩蛋剧情等） | 3 | 4 |
| 邀约事件 | 1 | 2 |

共 2091 个子任务 txt，剧情正文约 **661 万字**（非空白字符口径，分类明细见 `report/字数统计.txt`）。少数页面在 wiki 上本身没有剧情正文（标注「待补充」或只收录了路线图），已汇总在 `report/missing.txt`。

## 环境

- Python 3.11+（本机为 3.14）
- 仅依赖 `requests`

```bash
pip install -r requirements.txt
```

## 用法

```bash
python scripts/crawl.py                # 全流程：枚举目录 -> 抓取正文 -> 生成 txt
python scripts/crawl.py --rebuild      # 只用本地缓存重新生成 txt（零网络请求）
python scripts/crawl.py --force        # 忽略缓存，重新下载全部正文
python scripts/crawl.py --rediscover   # 强制重新枚举目录
python scripts/crawl.py --only 魔神任务 传说任务
python scripts/crawl.py --limit 50     # 只抓前 50 页，调试用
python scripts/crawl.py --interval 2   # 调大请求间隔
python scripts/crawl.py --no-clean     # 保留 output 目录里的旧文件
python scripts/stats.py                # 统计字数，生成 report/字数统计.txt
python scripts/stats.py --top 50       # 全库角色榜只列前 50
```

抓取与渲染是分离的：正文按标题哈希缓存在 `data/cache/`，所以改渲染或解析规则后只要 `--rebuild` 即可，不会重复打扰源站。

## 输出结构

```
output/
├── index.txt                                 # 总索引：分类 -> 幕 -> 子任务
├── 魔神任务/
│   └── 序章 第一幕 捕风的异乡人/
│       ├── 01-鸟瞰风物.txt
│       └── 02-异常的权柄.txt
├── 传说任务/
│   ├── 邀约事件/北斗.txt
│   └── 小兔之章 第一幕 风、勇气和翅膀/...
├── 世界任务/、活动任务/、委托任务/、游逸旅闻/
├── 银月之庭·伴月纪闻/、隐藏任务/、其他/
report/
├── missing.txt                               # 无剧情正文 / 抓取失败的页面
├── unknown_templates.txt                     # 未适配的 wiki 模板（人工核查用）
└── 字数统计.txt                              # 大类 -> 幕 -> 子任务三级字数 + 角色排行
```

单篇 txt 形态：

```text
鸟瞰风物
============================================================

来源：https://wiki.biligame.com/ys/鸟瞰风物

【与派蒙对话】

派蒙：那就是「七天神像」了。
派蒙：神灵的造像散布在大陆上，象征七神守护世界。
选项：继续远离
```

排版约定：

- 一级标题下跟 60 个 `=` 组成的分隔线
- `【小节名】` —— 任务流程小节
- `角色：台词` —— 对白
- `选项：xxx` —— 玩家的对话选项（含分支选项）
- `▷ xxx` —— 旁白、地点、折叠块标题（如「额外对话（雅各布）」）

文件编码为 **UTF-8（带 BOM）+ CRLF 换行**，Windows 记事本双击即可正常阅读，不会乱码或挤成一行。

## 字数统计

`python scripts/stats.py` 只读 `output/`，不联网络、不依赖缓存，随时可重跑，产出 `report/字数统计.txt`：

- **口径**：只算剧情正文。剔除首行标题、60 个 `=` 分隔线、`来源：` 行、空行、`【小节名】` 与 HTML 注释残片；字数 = 去掉空白后的字符数（含标点）。
- **分类**：`角色：台词` → 对白（同时计入该角色），`选项：` → 选项，`▷` 与其余无前缀行 → 旁白。渲染层不会给续行补角色前缀，因此无前缀行一律按旁白计，避免张冠李戴。
- **层级**：总计 / 正文构成 → 大类汇总（大纲）→ 全库角色 Top N → 各大类角色 Top 10 → 大类 → 幕 → 每篇子任务三级明细 → 附录（空文件、疑似误判角色名、注释残片统计）。
- **参数**：`--top N` 调整全库角色榜条数（默认 100），`--output 路径` 改写输出位置。

## 实现要点

1. **目录来源**：不用页面爬链，而是走 Semantic MediaWiki 语义查询
   `[[分类:任务]]`（2116 条任务页 + `任务类型/系列任务/任务编号/任务地区/所属版本`）和
   `[[分类:系列任务]]`（492 条幕级页面 + `副标题`）。入口页只用来取**官方剧情顺序**（解析 `{{图标|任务|…}}` 与 `==[[任务名]]==` 标题的出现次序）。
2. **正文抓取**：`action=query&prop=revisions`，一次带 50 个标题，全量仅约 43 次请求。
3. **剧情提取**：定位 `==任务剧情==`（容忍等号内外空格，且兼容重复出现两次的页面），按 `===小节===` 切分，逐行还原台词、选项、旁白；表格转文本，`{{折叠}}` 展开为带标题的引用块，`{{剧情选项}}` 展开为选项 + 分支。
4. **文本清理**：`{{颜色}}`/`{{黑幕}}`/`{{ruby}}`/`{{图标}}` 等模板、`[[链接]]`、HTML 标签、`<ref>` 全部还原为纯文本；未能识别的模板会记入报告而不是静默丢弃。
5. **直接渲染成 txt**：渲染层不做 Markdown 中间态，`render.py` 一次写盘即产出最终纯文本。

## 常见问题

- **HTTP 567**：该站对缺少 `Referer` / 非浏览器 UA 的请求会直接拒绝。`config.py` 里已配好浏览器请求头，默认 1.2s 间隔 + 指数退避重试；若仍被限流，调大 `--interval`。
- **某篇是空的**：先看 `report/missing.txt`，多数是 wiki 页面本身没有正文。
- **想改目录分组**：调整 `config.py` 的 `TYPE_TO_CATEGORY`，或 `scripts/discover.py` 的 `fallback_folder()`（无系列任务时的兜底分组：活动按版本、其他按地区）。
- **改回 Markdown**：只需改 `scripts/render.py` 的 `format_line()` / `render_script()` 与写入后缀，其余分层不受影响。

## 许可

本仓库不是单一作品，三类材料分别授权，互不外溢：

| 范围 | 协议 |
| --- | --- |
| `scripts/`、`config.py` | [GPL-3.0-or-later](LICENSES/GPL-3.0-or-later.txt) |
| `output/` 剧情文本整理产物 | [CC BY-NC-SA 4.0](LICENSES/CC-BY-NC-SA-4.0.txt) |
| 文档（`README.md`、`AGENTS.md`、`NOTICE.md`） | CC BY-NC-SA 4.0 |

- 想复用/改抓取脚本 → 按 GPL-3.0 用，包括商业用途。
- 想用剧情文本 → 按 CC BY-NC-SA 4.0 用：**署名 + 非商业 + 相同方式共享**。注意 `output/` 用这个协议不是自选，而是 BWIKI 的 ShareAlike 义务（详见 [`LICENSE.md`](LICENSE.md)）。
- 代码与 txt 是 GPLv3 第 5 条意义上的**聚合**，各自协议只作用于自己那部分；但**请勿把两者打包成单一发行物**，否则 NC 与 GPL 的商用授权会冲突。

完整映射与理由见 [`LICENSE.md`](LICENSE.md)，权利归属与免责见 [`NOTICE.md`](NOTICE.md)。

## 版权

剧情文本抓取自 [原神 BWIKI](https://wiki.biligame.com/ys)，游戏原文（台词、任务名、旁白）的著作权归米哈游所有：

> © All rights reserved by miHoYo. Other properties belong to their respective owners.

本仓库不对游戏原文主张任何权利，仅对整理、排版与结构化编排部分按 CC BY-NC-SA 4.0 提供。米哈游并未授权本项目，其对二次创作的态度与署名要求、BWIKI 的六项署名要素，均见 [`NOTICE.md`](NOTICE.md)。
