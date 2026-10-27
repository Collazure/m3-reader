"""prts_tool — PRTS（prts.wiki）文本采集工具箱。

把「剧情 / 活动长文 / 干员档案与模组与密录 / 家具 / 关卡文本」等采集器统一到一个
click 命令行工具里，并提供通用抓取接口，方便以后继续扩充新的文本类型。

快速开始：
    python prts_crawler.py --help
    python prts_crawler.py all                 # 全量采集
    python prts_crawler.py refresh -m avg      # 只补齐/更新 avg 剧情
"""

__version__ = "2.10.4"
