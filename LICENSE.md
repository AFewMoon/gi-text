# 许可 / Licensing

本仓库**不是单一作品**，而是三类权利来源不同、必须分别授权的材料。请按下面的映射表判断你要用的部分适用哪个协议；`output/` 与代码的协议**互不外溢**。

| 范围 | 内容 | 协议 | 协议正文 | 权利人 |
| --- | --- | --- | --- | --- |
| `scripts/`、`config.py` | 抓取、解析、渲染、统计源码 | **GPL-3.0-or-later** | [`LICENSES/GPL-3.0-or-later.txt`](LICENSES/GPL-3.0-or-later.txt) | © 2026 AFewMoon |
| `output/` | 剧情文本整理产物（2091 篇 txt + `index.txt`） | **CC BY-NC-SA 4.0** | [`LICENSES/CC-BY-NC-SA-4.0.txt`](LICENSES/CC-BY-NC-SA-4.0.txt) | 游戏原文 © 米哈游；wiki 整理 © 原神 BWIKI 编辑者；本项目的整理与编排 © 2026 AFewMoon |
| `README.md`、`AGENTS.md`、`NOTICE.md`、`CITATION.cff`、本文件 | 项目文档 | **CC BY-NC-SA 4.0** | 同上 | © 2026 AFewMoon |

## 为什么内容层是 CC BY-NC-SA 4.0

这一层**不是我们的选择，是上游协议的义务**：

1. 原神 BWIKI 声明「若无特殊说明，wiki 内容按 CC BY-NC-SA 协议提供」，其协议页（<https://wiki.biligame.com/tools/CC_BY-NC-SA>）载明为 **CC BY-NC-SA 4.0 国际版**。
2. 该协议第三条 b 款「相同方式共享」要求：基于授权作品创作的演绎作品，其「演绎作者的许可」**必须**是具有相同授权要素的 CC 协议（本版本或后续版本）。
3. `output/` 是把 wiki 页面去模板、换排版、按「任务类型 → 幕 → 子任务」重排后的产物，构成**演绎作品**，因此必须以 CC BY-NC-SA 4.0 发布。

换句话说：**内容层的协议被上游锁死，代码层的协议才是本项目可自选的。** 任何试图用 MIT / Apache-2.0 覆盖全仓的做法都会违反 wiki 的 SA 条款。

## 代码与内容为什么可以共存

两者不互相链接、不编译为同一程序，属于 GPLv3 第 5 条末段所说的**聚合（aggregate）**：

> A compilation of a covered work with other separate and independent works, which are not by their nature extensions of the covered work, and which are not combined with it such as to form a larger program, is called an "aggregate".

- GPL 的义务只作用于其 **covered work**（即 `scripts/` 与 `config.py` 及其衍生代码）；`output/` 不是以 GPL 授权的作品，不受 GPL 约束。
- CC 的 **NC（非商业性使用）** 条款只作用于内容层，不外溢到代码，你仍然可以出于任何目的（包括商业目的）使用、修改、分发这些脚本——但脚本产出的内容另受 CC 约束。
- 唯一的硬约束：**请勿把 `output/` 与代码打包成单一发行物**（wheel、二进制、整合包等）。一旦合并为同一程序，聚合关系消失，NC 与 GPL 的商用授权就会直接冲突。

## 关于 GitHub 的协议徽章

本仓库根目录**故意只放这份索引页**，两份协议正文放在 `LICENSES/` 子目录。GitHub 的协议检测只扫根目录，因此侧栏不会显示单一协议徽章——这是刻意的：仓库里 2106 个文件中有 2092 个是剧情 txt，任何"整仓 GPL-3.0"或"整仓 CC BY-NC-SA"的徽章都是误导。

如果你确实想要 GPL 徽章（例如为了让下游一眼看到代码可复用），执行一步即可：

```bash
git mv LICENSES/GPL-3.0-or-later.txt COPYING
```

## 归属与免责

游戏原文的版权归属、BWIKI 的署名要求、以及本项目的非官方声明，见 [`NOTICE.md`](NOTICE.md)。**本仓库不对游戏原文主张任何权利。**

## 协议正文来源

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `LICENSES/GPL-3.0-or-later.txt` | <https://www.gnu.org/licenses/gpl-3.0.txt> | 原样下载，未改动 |
| `LICENSES/CC-BY-NC-SA-4.0.txt` | <https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.zh-hans> | 简体中文官方译本，仅移除 HTML 标记与页面导航，条款文字与编号未改动；英文原本见 <https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.en> |
