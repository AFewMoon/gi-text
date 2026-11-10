"""全局配置：站点地址、请求头、限速、目录映射。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- 站点
BASE_URL = "https://wiki.biligame.com/ys"
API_URL = BASE_URL + "/api.php"
SITE_NAME = "原神 BWIKI"

# 该站对无 Referer / 非浏览器 UA 的请求返回 HTTP 567，必须伪装成浏览器。
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Referer": BASE_URL + "/",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------- 抓取参数
MIN_INTERVAL = 1.2       # 相邻请求最小间隔（秒）
BATCH_SIZE = 50          # 单次 query 携带的页面标题数
ASK_LIMIT = 5000         # SMW ask 单次返回上限
MAX_RETRY = 5            # 失败重试次数
TIMEOUT = 60             # 单次请求超时（秒）
RETRY_STATUS = {429, 500, 502, 503, 504, 567}

# ---------------------------------------------------------------- 路径
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_INDEX = CACHE_DIR / "_index.json"
CATALOG_PATH = DATA_DIR / "catalog.json"
OUTPUT_DIR = ROOT / "output"
REPORT_DIR = ROOT / "report"
MISSING_REPORT = REPORT_DIR / "missing.txt"
UNKNOWN_TPL_REPORT = REPORT_DIR / "unknown_templates.txt"
STATS_REPORT = REPORT_DIR / "字数统计.txt"

# ---------------------------------------------------------------- 字数统计
STATS_TOP_SPEAKERS = 100     # 全库角色排行默认条数
STATS_CATEGORY_TOP = 10      # 每个大类内角色排行条数

# ---------------------------------------------------------------- 分类
CATEGORY_ORDER = [
    "魔神任务",
    "传说任务",
    "世界任务",
    "游逸旅闻",
    "银月之庭·伴月纪闻",
    "活动任务",
    "委托任务",
    "隐藏任务",
    "其他",
]

# 任务页的「任务类型」属性 -> 顶层目录
TYPE_TO_CATEGORY = {
    "魔神任务": "魔神任务",
    "传说任务": "传说任务",
    "部族纪闻": "传说任务",
    "热点事件": "传说任务",
    "邀约事件": "传说任务",
    "世界任务": "世界任务",
    "活动任务": "活动任务",
    "委托任务": "委托任务",
    "委托事件": "委托任务",
    "游逸旅闻": "游逸旅闻",
    "伴月纪闻": "银月之庭·伴月纪闻",
    "隐藏任务": "隐藏任务",
}
DEFAULT_CATEGORY = "其他"

# 用户给定的入口页 -> 顶层目录，用于取官方剧情顺序
ENTRY_PAGES = {
    "魔神任务": "魔神任务",
    "传说任务": "传说任务",
    "世界任务": "世界任务",
    "游逸旅闻": "游逸旅闻",
    "银月之庭·伴月纪闻": "银月之庭·伴月纪闻",
    "活动任务": "活动任务",
    "委托任务": "委托任务",
}

# 邀约事件的剧情在「邀约事件·<角色>」整页里，单独枚举
INVITATION_PREFIX = "邀约事件·"
INVITATION_CATEGORY = "传说任务"
INVITATION_FOLDER = "邀约事件"

# 剧情章节标题（容忍等号内外空格）
STORY_HEADINGS = ("任务剧情", "剧情")
# 邀约事件页的剧情章节
INVITATION_HEADING = "剧情分支"

# 页面标题里需要从展示名中剔除的后缀
TITLE_SUFFIXES = ("（系列任务）",)

# 误入 分类:任务 的维护页 / 模板说明页，不参与抓取
EXCLUDED_TITLES = {"添加主线任务"}
UNSORTED_FOLDER = "未归类"
