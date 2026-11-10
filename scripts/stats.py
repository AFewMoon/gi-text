"""字数统计：按「大类 -> 幕 -> 子任务」三级统计剧情正文字数，并统计各角色台词字数。

只读 output/ 下已渲染的 txt，不依赖网络与 cache。

用法：
    python scripts/stats.py                  # 生成 report/字数统计.txt
    python scripts/stats.py --top 50         # 全库角色榜只列前 50
    python scripts/stats.py --output x.txt   # 写到指定路径
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from render import TEXT_ENCODING, TEXT_NEWLINE, TITLE_RULE  # noqa: E402

RULE_RE = re.compile(r"^=+$")
SOURCE_RE = re.compile(r"^来源[：:]")
SECTION_RE = re.compile(r"^【.*】$")
COMMENT_RE = re.compile(r"^<!--|-->$")
SPEAKER_RE = re.compile(r"^([^：:\n]{1,12})\s*[：:]\s*(.+)$")
WS_RE = re.compile(r"\s+")
DIGITS_RE = re.compile(r"(\d+)")

NOTE_PREFIX = "▷ "
CHOICE_PREFIX = "选项："
# 允许「？？？」「凯瑟琳？」这类带疑问号的称呼，只排除真正的句读符号
SPEAKER_BAD_CHARS = set("，。、；,.;【】《》[]…—")
SPEAKER_DENY = {"选项", "旁白", "备注", "注", "来源", "地点"}
NARRATION_PREFIXES = ("旁白：", "旁白:")   # wiki 里显式标注的旁白行

SUSPICIOUS_MIN_WORDS = 50  # 仅 1 条台词却超过该字数，多半是把旁白误当台词


# ------------------------------------------------------------------ 数据结构


@dataclass
class FileStat:
    """单篇子任务的统计结果。"""

    category: str
    folder: str
    name: str
    words: int
    speech: int
    choice: int
    narration: int


@dataclass
class SpeakerStat:
    """单个角色的累计统计。"""

    name: str
    words: int = 0
    lines: int = 0
    files: set[str] = field(default_factory=set)


@dataclass
class Parsed:
    """单篇文件的解析中间结果。"""

    words: int = 0
    speech: int = 0
    choice: int = 0
    narration: int = 0
    comments: int = 0  # 混进正文的 HTML 注释残片行数
    speakers: dict[str, list[int]] = field(default_factory=dict)  # 角色 -> [字数, 条数]


@dataclass
class Collector:
    """全局聚合容器。"""

    files: list[FileStat] = field(default_factory=list)
    speakers: dict[str, SpeakerStat] = field(default_factory=dict)
    category_speakers: dict[str, Counter] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    category_lines: dict[str, Counter] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    loose_files: list[str] = field(default_factory=list)
    comments: int = 0

    def add_file(self, stat: FileStat, speakers: dict[str, list[int]]) -> None:
        self.files.append(stat)
        key = f"{stat.category}/{stat.folder}/{stat.name}"
        for name, (words, lines) in speakers.items():
            item = self.speakers.get(name)
            if item is None:
                item = SpeakerStat(name)
                self.speakers[name] = item
            item.words += words
            item.lines += lines
            item.files.add(key)
            self.category_speakers[stat.category][name] += words
            self.category_lines[stat.category][name] += lines


# ------------------------------------------------------------------ 文本解析


def _words(text: str) -> int:
    """字数口径：去掉所有空白后的字符数（含标点）。"""
    return len(WS_RE.sub("", text))


def _strip_prefix(line: str, prefixes: tuple[str, ...]) -> str | None:
    """命中任一前缀时返回去掉前缀的正文，否则返回 None。"""
    for prefix in prefixes:
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


def _valid_speaker(name: str) -> bool:
    text = name.strip()
    if not text or len(text) > 12 or text in SPEAKER_DENY:
        return False
    return not any(ch in SPEAKER_BAD_CHARS or ch.isspace() for ch in text)


def parse_file(path: Path) -> Parsed:
    """逐行解析单篇 txt，剔除标题 / 分隔线 / 来源 / 空行 / 小节名后统计正文。

    无角色前缀的行一律按旁白处理：渲染层不会给续行补前缀，文本上无法可靠区分
    「多行台词的续行」与「独立的旁白」，宁可漏记也不张冠李戴。
    """
    parsed = Parsed()
    header_done = False

    with path.open("r", encoding=TEXT_ENCODING, newline="") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if not header_done:
                # 首个分隔线之前的行是标题，不算正文
                if RULE_RE.match(line):
                    header_done = True
                continue
            if RULE_RE.match(line) or SOURCE_RE.match(line):
                continue
            if COMMENT_RE.match(line):
                parsed.comments += 1
                continue
            if SECTION_RE.match(line):
                continue
            if line.startswith(NOTE_PREFIX):
                count = _words(line[len(NOTE_PREFIX) :])
                parsed.narration += count
                parsed.words += count
                continue
            if line.startswith(CHOICE_PREFIX):
                count = _words(line[len(CHOICE_PREFIX) :])
                parsed.choice += count
                parsed.words += count
                continue
            narration_body = _strip_prefix(line, NARRATION_PREFIXES)
            if narration_body is not None:
                count = _words(narration_body)
                parsed.narration += count
                parsed.words += count
                continue

            match = SPEAKER_RE.match(line)
            if match and _valid_speaker(match.group(1)):
                name = match.group(1).strip()
                count = _words(match.group(2))
                parsed.speech += count
                parsed.words += count
                slot = parsed.speakers.setdefault(name, [0, 0])
                slot[0] += count
                slot[1] += 1
                continue

            count = _words(line)
            parsed.narration += count
            parsed.words += count
    return parsed


# ------------------------------------------------------------------ 遍历聚合


def _natural_key(text: str) -> tuple:
    """让 02-xxx 排在 10-xxx 前面。"""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in DIGITS_RE.split(text)
        if part
    )


def _iter_categories(root: Path) -> list[tuple[str, Path]]:
    """按 config.CATEGORY_ORDER 排序，额外目录追加在末尾。"""
    dirs = {p.name: p for p in root.iterdir() if p.is_dir()}
    ordered: list[tuple[str, Path]] = []
    for name in config.CATEGORY_ORDER:
        if name in dirs:
            ordered.append((name, dirs.pop(name)))
    ordered.extend(sorted(dirs.items(), key=lambda kv: _natural_key(kv[0])))
    return ordered


def scan_output(root: Path | None = None) -> Collector:
    root = root or config.OUTPUT_DIR
    collector = Collector()

    for category, cdir in _iter_categories(root):
        collector.loose_files.extend(
            sorted((p.name for p in cdir.glob("*.txt")), key=_natural_key)
        )
        folders = sorted(
            (p for p in cdir.iterdir() if p.is_dir()), key=lambda p: _natural_key(p.name)
        )
        for fdir in folders:
            for path in sorted(fdir.glob("*.txt"), key=lambda p: _natural_key(p.stem)):
                parsed = parse_file(path)
                stat = FileStat(
                    category=category,
                    folder=fdir.name,
                    name=path.stem,
                    words=parsed.words,
                    speech=parsed.speech,
                    choice=parsed.choice,
                    narration=parsed.narration,
                )
                collector.add_file(stat, parsed.speakers)
                collector.comments += parsed.comments
    return collector


# ------------------------------------------------------------------ 渲染工具


def _width(text: str) -> int:
    """按东亚宽字符占两格计算显示宽度，保证纯文本表格对齐。

    A（歧义字符，如 · … — ）在中文等宽字体里同样占两格，一并按宽字符处理。
    """
    return sum(2 if unicodedata.east_asian_width(ch) in "WFA" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def _num(text: str, width: int) -> str:
    return " " * max(0, width - _width(text)) + text


def _int(value: int) -> str:
    return f"{value:,}"


def _pct(part: int, total: int) -> str:
    if not total:
        return "0.0%"
    value = part / total * 100
    return "<0.1%" if value < 0.1 else f"{value:.1f}%"


def _table(headers: list[str], rows: list[list[str]], aligns: str) -> list[str]:
    widths = [_width(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], _width(cell))

    def fmt(row: list[str]) -> str:
        cells = [
            _pad(cell, widths[i]) if aligns[i] == "l" else _num(cell, widths[i])
            for i, cell in enumerate(row)
        ]
        return "  ".join(cells).rstrip()

    lines = [fmt(headers), "  ".join("-" * width for width in widths)]
    lines.extend(fmt(row) for row in rows)
    return lines


def _group_by_folder(items: list[FileStat]) -> dict[str, list[FileStat]]:
    grouped: dict[str, list[FileStat]] = {}
    for item in items:
        grouped.setdefault(item.folder, []).append(item)
    return grouped


def _source_label() -> str:
    try:
        return config.OUTPUT_DIR.relative_to(ROOT).as_posix()
    except ValueError:
        return str(config.OUTPUT_DIR)


# ------------------------------------------------------------------ 报告渲染


def render_report(collector: Collector, top: int = config.STATS_TOP_SPEAKERS) -> str:
    files = collector.files
    total = sum(item.words for item in files)
    speech = sum(item.speech for item in files)
    choice = sum(item.choice for item in files)
    narration = sum(item.narration for item in files)

    cat_files: dict[str, list[FileStat]] = {}
    for item in files:
        cat_files.setdefault(item.category, []).append(item)
    folder_count = sum(len(_group_by_folder(items)) for items in cat_files.values())

    lines: list[str] = [
        "原神剧情文本字数统计",
        TITLE_RULE,
        "",
        f"统计时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        f"数据来源：{_source_label()}/（{len(files)} 篇 txt，{len(cat_files)} 个大类，{folder_count} 幕）",
        "统计口径：仅剧情正文。剔除首行标题、分隔线（60 个 =）、来源行、空行、"
        "「【小节名】」与 HTML 注释残片，字数 = 非空白字符数（含标点）。",
        "分类规则：以「角色：台词」开头的行计入对白与该角色，"
        "「选项：」行计入选项，「▷」与其余无前缀行计入旁白。",
        "",
        "【总计】",
        "-" * 60,
    ]
    lines.extend(
        _table(
            ["项目", "数值"],
            [
                ["大类", str(len(cat_files))],
                ["幕", str(folder_count)],
                ["子任务", str(len(files))],
                ["字数", _int(total)],
                ["角色", _int(len(collector.speakers))],
            ],
            "lr",
        )
    )
    lines.extend(["", "【正文构成】", "-" * 60])
    lines.extend(
        _table(
            ["类型", "字数", "占比"],
            [
                ["对白", _int(speech), _pct(speech, total)],
                ["选项", _int(choice), _pct(choice, total)],
                ["旁白", _int(narration), _pct(narration, total)],
            ],
            "lrr",
        )
    )

    # ------------------------------------------------------------- 大纲
    lines.extend(["", "【大纲】各大类汇总", "-" * 60])
    rows: list[list[str]] = []
    for category, items in cat_files.items():
        cat_total = sum(item.words for item in items)
        rows.append(
            [
                category,
                str(len(_group_by_folder(items))),
                str(len(items)),
                _int(cat_total),
                _pct(cat_total, total),
            ]
        )
    rows.append(
        ["合计", str(folder_count), str(len(files)), _int(total), _pct(total, total)]
    )
    lines.extend(_table(["大类", "幕", "篇", "字数", "占比"], rows, "lrrrr"))

    # ------------------------------------------------------------- 角色排行
    ranked = sorted(collector.speakers.values(), key=lambda s: (-s.words, s.name))
    lines.extend(["", f"【角色统计】全库 Top {min(top, len(ranked))}", "-" * 60])
    lines.append("说明：角色名取自台词行前缀，含 NPC、系统提示等非正式角色名。")
    lines.append("")
    rows = []
    for index, item in enumerate(ranked[:top], start=1):
        rows.append(
            [
                str(index),
                item.name,
                _int(item.lines),
                _int(item.words),
                _int(len(item.files)),
                _pct(item.words, total),
            ]
        )
    lines.extend(_table(["排名", "角色", "台词条数", "字数", "登场篇数", "占比"], rows, "rllrrr"))

    lines.extend(["", f"【角色统计】各大类 Top {config.STATS_CATEGORY_TOP}", "-" * 60])
    for category, items in cat_files.items():
        cat_total = sum(item.words for item in items)
        counter = collector.category_speakers.get(category, Counter())
        line_counter = collector.category_lines.get(category, Counter())
        names = sorted(counter, key=lambda n: (-counter[n], n))
        lines.append("")
        lines.append(f"· {category}（{_int(cat_total)} 字，{_int(len(names))} 个角色）")
        rows = []
        for index, name in enumerate(names[: config.STATS_CATEGORY_TOP], start=1):
            rows.append(
                [
                    str(index),
                    name,
                    _int(line_counter[name]),
                    _int(counter[name]),
                    _pct(counter[name], cat_total),
                ]
            )
        if rows:
            lines.extend(_table(["排名", "角色", "台词条数", "字数", "占比"], rows, "rllrr"))

    # ------------------------------------------------------------- 分类明细
    lines.extend(["", "【分类明细】大类 -> 幕 -> 子任务", "-" * 60])
    for category, items in cat_files.items():
        cat_total = sum(item.words for item in items)
        grouped = _group_by_folder(items)
        lines.extend(
            [
                "",
                f"■ {category}：{len(grouped)} 幕 · {len(items)} 篇 · "
                f"{_int(cat_total)} 字（占 {_pct(cat_total, total)}）",
                "",
                "· 幕汇总（按字数降序）",
            ]
        )
        rows = []
        for folder, folder_items in sorted(
            grouped.items(), key=lambda kv: (-sum(f.words for f in kv[1]), kv[0])
        ):
            folder_total = sum(item.words for item in folder_items)
            rows.append(
                [
                    folder,
                    str(len(folder_items)),
                    _int(folder_total),
                    _pct(folder_total, cat_total),
                ]
            )
        lines.extend(_table(["幕", "篇", "字数", "占比"], rows, "lrrr"))

        lines.extend(["", "· 子任务明细"])
        for folder, folder_items in grouped.items():
            folder_total = sum(item.words for item in folder_items)
            name_width = min(60, max((_width(item.name) for item in folder_items), default=10))
            num_width = max((len(_int(item.words)) for item in folder_items), default=1)
            lines.append("")
            lines.append(
                f"  {folder}（{len(folder_items)} 篇 · {_int(folder_total)} 字）"
            )
            for item in folder_items:
                lines.append(f"    {_pad(item.name, name_width)}  {_num(_int(item.words), num_width)}")

    # ------------------------------------------------------------- 附录
    lines.extend(["", "【附录】核对信息", "-" * 60])
    empty = [f"{item.category}/{item.folder}/{item.name}" for item in files if item.words == 0]
    lines.append(f"· 空正文文件：{len(empty)} 个")
    for path in empty:
        lines.append(f"    {path}")

    lines.append("")
    lines.append(
        f"· 正文里的 HTML 注释残片（`<!--` / `-->`）：{collector.comments} 行，"
        "已从字数中剔除（属渲染层遗留，可另行修 render.py）"
    )

    suspicious = [
        item
        for item in ranked
        if item.lines == 1 and item.words >= SUSPICIOUS_MIN_WORDS
    ]
    lines.append("")
    lines.append(
        f"· 疑似误判样本（仅 1 条台词且不少于 {SUSPICIOUS_MIN_WORDS} 字的「角色」，"
        f"共 {len(suspicious)} 个，列前 20）"
    )
    if suspicious:
        rows = [
            [item.name, _int(item.words), str(len(item.files))]
            for item in suspicious[:20]
        ]
        lines.extend(_table(["疑似名称", "字数", "篇数"], rows, "lrr"))
    else:
        lines.append("    无")

    lines.append("")
    lines.append(f"· 分类根目录下的游离 txt（未计入统计）：{len(collector.loose_files)} 个")
    for name in collector.loose_files:
        lines.append(f"    {name}")

    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------ 命令行


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="统计 output/ 下剧情正文的字数（大类 -> 幕 -> 子任务，含角色排行）。"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=config.STATS_TOP_SPEAKERS,
        help=f"全库角色榜条数（默认 {config.STATS_TOP_SPEAKERS}）",
    )
    parser.add_argument("--output", default=None, help="报告路径，默认 report/字数统计.txt")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not config.OUTPUT_DIR.is_dir():
        print(
            f"未找到输出目录：{config.OUTPUT_DIR}\n请先运行 python scripts/crawl.py 生成 txt。",
            file=sys.stderr,
        )
        return 1

    collector = scan_output()
    if not collector.files:
        print(f"{config.OUTPUT_DIR} 下没有可统计的 txt。", file=sys.stderr)
        return 1

    report = render_report(collector, top=args.top)
    target = Path(args.output) if args.output else config.STATS_REPORT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding=TEXT_ENCODING, newline=TEXT_NEWLINE)

    total = sum(item.words for item in collector.files)
    print(
        f"已写入 {target}：{len(collector.files)} 篇 / {_int(total)} 字 / "
        f"{len(collector.speakers)} 个角色"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
