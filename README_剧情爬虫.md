# M3 Reader · PRTS 文本采集与阅读

把 [PRTS 明日方舟中文 Wiki](https://prts.wiki) 的各类文本 / 图片抓成便于阅读的本地副本，
纯标准库 + click 作为采集核心，可反复增量刷新。当前版本：2.5.3。

资源已迁入 [resources/](resources/README.md)。其他设备安装包位于 [installpacks/](installpacks/README.md)。GUI / TUI 的安装与使用见 [资料终端说明](docs/APP_README.md)；需求记录见 [需求记录](docs/REQUIREMENTS.md)，
调研事实及待验证事项见 [已知信息](docs/KNOWN_INFO.md)，
程序与资源分离、资料维护分类及实现结构见 [工程结构](docs/ARCHITECTURE.md)。
下文的 `prts_text/`、`terra/` 等短路径均指 resources 下对应的资源根。

> **本工具整体放在 `m3-reader/` 目录里**（代码位于 `prts_tool/`；资源位于 `resources/`），
> 同级还有一份 `../prts-wiki-map/`（站点结构勘察资料，只读参考，不属于本工具）。

```
resources/collected/prts_text/                  ← 文本数据（默认输出根）
├── avg/                                  ← 剧情（网页上的「剧情一览」）
│   ├── 主线/第2章 异卵同生/0036 2-1 龙门之行 行动后.txt
│   ├── 主线/第2章 异卵同生/关卡文本.txt
│   ├── 支线/巴别塔/…
│   ├── 联动/源石尘行动/…                  ← 联动活动（分类:联动活动）
│   ├── 故事集/战地秘闻/…
│   ├── 四月辑录/断罪者的挑战状/…            ← 四月辑录也自成一级分类
│   ├── 特殊 危机合约/…                     ← 未归类的大类保持原样
│   └── _索引.md / _manifest.json / _stage_manifest.json
├── activity/                             ← 活动页专属长文（avg 不收的活动文本）
│   ├── 孤星/综合调查数据库.txt
│   ├── 叙拉古人/待办事项记录.txt
│   ├── 崔林特尔梅之金/PRTS金律记录.txt
│   ├── 愚人号/审判庭纪要.txt
│   └── _索引.md / _manifest.json / _pages.json（子页面索引缓存，7 天）
├── operator/                             ← 干员文本（目录名与命令名一致）
│   └── 琴柳/
│       ├── 干员档案.txt
│       ├── 模组1-琴柳证章.txt  模组2-牧人的歌.txt  模组3-“友谊万岁”.txt
│       ├── avg1-一双羽兽.txt   avg2-鬓旁的花.txt      ← 干员密录（首行是前置文本）
│       └── 悖论模拟.txt
├── furniture/                            ← 家具（一主题一个 txt）
│   ├── 龙门食坊.txt  … 独立家具.txt
│   └── _家具索引.md / _manifest.json
├── enemies/                              ← 敌人描述（按地位级别分三个文件）
│   ├── 普通.txt   精英.txt   领袖.txt
├── roguelike/                            ← 集成战略（肉鸽，7 个主题）
│   └── 傀影与猩红孤钻/                     ← 例：该主题的目录
│       ├── 事件/<事件大类>/<事件名>.txt
│       ├── 藏品.txt
│       ├── 序章/avg.txt
│       ├── 结局/结局一 舞会终场/{avg.txt, part1.txt …}
│       ├── 月度小队/<小队名>.txt            ← 各主题名称不同：追忆映射/游园访谈…
│       ├── 关卡.txt   加载文本.txt   其他文本/*.txt
├── reclamation/                          ← 生息演算（与 avg / roguelike 同级）
│   ├── 沙中之火/ 沙洲遗闻/ 重启锚点/
│   │   ├── 0506 沙中之火.txt  …
│   │   └── 关卡文本.txt
│   └── _索引.md / _manifest.json

resources/collected/terra/                    ← 泰拉记事社微博长图
├── 行于泰拉/相变临界/{说明.txt, 微博@…_2026-05-12_(1).jpg}
├── 泰拉那些事/…  其它档案/…
└── _索引.md / _manifest.json
```

> 最外两层目录（`prts_text` 与 `avg`/`activity`/`operator`/`furniture`/`enemies`/`roguelike`/`reclamation`）
> 全部用英文，并与子命令名一一对应。
> **干员密录只存放在 `operator/<干员>/avgN-*.txt`**；`avg` 不再重复收录，
> 旧版本留下的 `avg/特殊 <干员>/` 会在下次 `avg` 运行时自动清理。
> 集成战略与生息演算的剧情**不放在 avg 里**，由各自的模块单独存到自己的目录树下。
> `terra/`（泰拉记事社的图片）默认放在 `resources/collected/terra/`，
> 与 `resources/collected/prts_text/` 分开。显式指定 `--out` 时，terra 仍放在自定义输出根的兄弟目录。
> 它默认**只写 `说明.txt` 与索引、不下载图片**，抓图要单独跑 `terra-images`。

`resources/updates/new/` 保存最近一次命令实际写入的所有内容文件。每个文件只保留其直接上一级目录，
例如 `resources/updates/new/不期而遇/被歌颂的影子.txt`。每次有效爬取后会整体替换其中的旧内容；
如果本次没有写入内容，或使用 `--dry-run`，则保留上一次的副本。
索引和增量清单不计入新内容。
重新抓取时若生成内容与磁盘上的文件相同，脚本会跳过写入并保留原修改时间；
剧情文件的“抓取时间”和索引的“生成时间”单独变化也不会触发重写。

---

## 1. 快速开始

```bash
bash scripts/install_cli.sh        # 一次性安装命令：在 ~/.local/bin 建立 m3-reader 软链接

m3-reader --help                   # 查看全部命令
m3-reader info                     # 模块说明 + 输出布局
m3-reader update                   # ★ 更新全部内容（首次跑全量，之后只补有变化/缺失的；不含 terra 图片）
m3-reader refresh -m avg           # 只想更新某个模块时用 refresh
m3-reader terra-images             # 单独抓泰拉记事社的图片（唯一会下载图片的指令）
m3-reader gui                      # GUI 资料终端（需要 PySide6）
m3-reader tui                      # TUI 资料终端（需要 prompt_toolkit）
```

> **不再需要写 `python 脚本名`**：`scripts/install_cli.sh` 只建立软链接，不复制代码，
> 项目移动或外置盘重新挂载后重新运行一次即可。默认使用系统的 `python3`
> （依赖 `click`；Ubuntu 可 `sudo apt install python3-click`），
> 也可用 `M3_READER_PYTHON` 指定解释器、`M3_READER_HOME` 指定项目根。
> `m3-reader-gui` 等价于 `m3-reader gui`。原来的 `python prts_crawler.py …` 仍然可用。
> Ubuntu 所需 apt 依赖（QtPdf、prompt_toolkit、tesseract、poppler、中文字体等）
> 见[资料终端说明](docs/APP_README.md)的「Ubuntu 依赖」。

| 文件 | 说明 |
| --- | --- |
| `prts_crawler.py` | **主入口**（click 命令行） |
| `prts_tool/` | 实现代码：网络层 / wikitext 解析 / 剧情脚本解析 / 采集器 / CLI |
| `prts_story_crawler.py` | 旧入口兼容层，等价于 `prts_crawler.py avg` |
| `resources/collected/prts_text/` | 抓下来的文本（程序默认输出根） |
| `resources/collected/terra/` | 泰拉记事社的图片（默认只写说明，图片用 `terra-images` 抓） |
| `resources/ocr/terra_text/` | terra 图片的 OCR 文本，链接回原图 |
| `resources/local/大地巡旅/` | 本地 PDF 与逐页 / 合并 OCR，不属于 PRTS 采集范围 |
| `../prts-wiki-map/` | 站点结构勘察资料（数据来源、Cargo 表、坑位，建议先读；不属于本工具） |

---

## 2. 命令一览

| 命令 | 作用 | 输出 |
| --- | --- | --- |
| `avg` | 剧情文本（主线 / 支线 / 联动 / 故事集 / 四月辑录） | `avg/<分类>/<章节>/*.txt` |
| `activity` | 活动页专属长文：活动公告 / 综合调查数据库 / 审判庭纪要 / 待办事项记录… | `activity/<活动名>/*.txt` |
| `stage` | 各章节、活动的关卡文本 | `avg/…/关卡文本.txt`、`reclamation/…/关卡文本.txt` |
| `operator` | 干员档案 / 模组故事 / 干员密录(avg) / 悖论模拟 | `operator/<干员名>/*.txt` |
| `furniture` | 家具文本（按主题/套组汇总） | `furniture/<主题>.txt` |
| `enemies` | 敌人描述（按地位级别） | `enemies/{普通,精英,领袖}.txt` |
| `roguelike` | 集成战略（7 个主题）：事件 / 藏品 / 序章 / 结局 / 月度小队 / 关卡 / 加载文本 | `roguelike/<主题>/*` |
| `reclamation` | 生息演算（3 个场次）的剧情文本 | `reclamation/<场次>/*.txt` |
| `terra` | 泰拉记事社的**说明文本 + 索引**（默认不下载图片） | `terra/<大节>/<条目名>/说明.txt` |
| **`terra-images`** | **只抓图片**（等价于 `terra --images`） | `terra/<大节>/<条目名>/*.jpg` |
| **`update`** | **更新全部内容**（所有模块，只处理有变化/缺失的部分） | — |
| `all` | 同 `update`（一次性把所有模块跑一遍） | — |
| `refresh` | 按模块刷新（`-m avg`、`-m roguelike`…） | — |
| `info` | 列出模块与输出布局 | — |
| `fetch` | 通用接口：`raw` / `template` / `cargo` / `category` / `embeddedin` | 屏幕或文件 |

> **更新全部内容**就用 `update`：`m3-reader update`。
> 加 `--force` 是「全库强制重抓」，加 `--missing` 是「只补本地没有的」，
> 加 `--dry-run` 可以先看会更新什么。`all` 与 `update` 行为一致。

> **图片默认不抓**：`update` / `all` / `refresh` 碰到 terra 只更新 `说明.txt` 和索引，
> **不会下载那 ~400 MB 图片**（写代码时也没有任何开关能打开它）。
> 想抓图只有两条路：
> ```powershell
> m3-reader terra-images              # 推荐：单独抓图，增量（已下过的不重下）
> m3-reader terra-images --force      # 已有图片也重下一遍
> m3-reader terra --images            # 等价写法
> ```

所有子命令都支持 `--help`：

```powershell
m3-reader avg --help
m3-reader roguelike --help
m3-reader fetch cargo --help
```

### 公共参数

| 参数 | 说明 |
| --- | --- |
| `-o, --out DIR` | 文本输出根目录（默认 `resources/collected/prts_text/`） |
| `-m, --mode` | `changed`（默认，按 wiki 版本号增量）/ `missing`（只补本地缺失）/ `force`（全部重抓） |
| `--force` / `--missing` | 上面两种模式的简写 |
| `--dry-run` | 只显示会写哪些文件，不下载不写入 |
| `-n, --limit N` | 最多处理 N 条（调试用） |
| `-g, --keyword K` | 只处理包含 K 的条目，可重复（`-g 巴别塔`、`-g 琴柳`、`-g 龙门`） |
| `--delay 秒` | 每次 API 请求间隔（默认 0.3，**别设成 0**） |
| `-v, --verbose` | 输出更多细节 |

> 默认文本根在 `resources/collected/prts_text/`，默认 terra 根在 `resources/collected/terra/`。
> 显式指定其他 `-o/--out` 时，terra 位于自定义文本根的兄弟目录。
> 例如 `-o D:\prts\prts_text` → 文本在 `D:\prts\prts_text\`，图片在 `D:\prts\terra\`。

### 常用例子

```powershell
m3-reader avg -g 巴别塔                     # 只抓某个活动
m3-reader activity -g 孤星                  # 只抓某个活动的公告/长文
m3-reader operator -g 琴柳                   # 只抓某个干员
m3-reader roguelike --theme 傀影与猩红孤钻     # 只抓某个肉鸽主题
m3-reader avg --format plain --merge-speaker  # 更易读的纯文本
m3-reader stage --with-conditions             # 关卡文本连作战条件一起保留
m3-reader furniture --furniture-dir 家具        # 家具换个目录名（默认 furniture）
```

---

## 3. 刷新：`refresh` 的三种模式

```powershell
m3-reader refresh                          # 全部模块，按版本号增量更新
m3-reader refresh -m avg                   # 只刷新剧情
m3-reader refresh -m enemies -m furniture   # 刷两个模块
m3-reader refresh -m all --mode missing    # 只补本地缺失的
m3-reader refresh -m roguelike --force     # 肉鸽全部重抓
m3-reader refresh --dry-run                # 先看会动哪些东西
```

| 模式 | 判断依据 | 用途 |
| --- | --- | --- |
| `changed`（默认） | 各模块清单里的 wiki revid / 组合签名 | 日常更新 |
| `missing` | **本地文件是否存在**（空文件也算缺） | 补缺失、换机器、清单丢了 |
| `force` | 不判断 | 改了输出格式、想强制刷新 |

清单文件：`avg/_manifest.json`、`avg/_stage_manifest.json`、`operator/_manifest.json`、
`furniture/_manifest.json`、`enemies/_manifest.json`、`roguelike/_manifest.json`、
`reclamation/_manifest.json`、`terra/_manifest.json`（terra 那份在 `resources/collected/terra/`）。

---

## 4. 各模块的数据来源与解析要点

| 模块 | 来源 | 数量级 |
| --- | --- | --- |
| avg 剧情 | `Template:剧情模拟器` 的 `文本数据=`（索引：`Template:剧情导航` + `分类:剧情`） | 1841 段有正文 / 1848 条清单（干员密录由 operator 负责，avg 不再重复） |
| avg 分类 | 页面 `剧情类型` + 导航表类型 + `分类:联动活动` | 主线 431 / 支线 946 / 联动 119 / 故事集 135 / 四月辑录 23（另有 4 段未归类） |
| activity | 活动页子页面（`action=parse` 渲染后转文本）：`活动公告`（含复刻）+ 综合调查数据库 / 审判庭纪要 / 待办事项记录 等长文 | 146 个文件 / 115 个活动（2026-10-24） |
| 关卡文本 | 关卡页 `{{普通关卡信息|关卡描述=…}}`（`Template:普通关卡信息` 嵌入列表枚举） | 3530 关 / 99 个章节文件（avg 96 + reclamation 3） |
| 干员档案 | 干员页 `==干员档案==` 的 `{{人员档案|档案N文本=…}}` | 436 人 |
| 模组故事 | 干员页 `==模组==` 的 `{{模组|基础信息=…}}` | 885 个 |
| 干员密录 | Cargo `char_memory`（`storyIntro` 前置文本 + `storyTxt` 密录页） | 390 篇 |
| 悖论模拟 | 干员页 `==悖论模拟==` 的 `{{悖论模拟|description=…}}` | 308 篇 |
| 家具 | 家具页 `{{家具信息}}` + 主题页 `{{家具主题总览}}` + Cargo `furniture_themes` | 2853 件 / 138 套组 + 384 件独立家具 |
| 敌人 | 敌人页 `{{敌人信息/common2}}` 的 `描述`（`地位级别` 分类） | 1728 条 / 1807 页 |
| 集成战略 | 各主题的事件一览 / 藏品页 / 记录页 / `ROn-*-NBT` 剧情页 / 思绪·密文板·通宝·零件图鉴 | 7 个主题、322 个事件、1793 件藏品、8 个道具图鉴文件 |
| 生息演算 | `RA…/ENTRY`、`RA…-END-*` 等剧情页（导航表 + 分类:剧情）；`沙中之火/事件一览`、`沙洲遗闻/事件一览` 的 `{{生息演算事件}}` | 16 段剧情 + 100 个事件 / 3 个场次 |
| 泰拉记事社 | `泰拉记事` 页面的 `{{微博}}` 模板（图片来自 PRTS 文件库；输出到 `terra/`，图片默认不抓） | 67 条 / 169 张图 / 约 408 MB |

**风味文本 vs 机制说明**：PRTS 把「关卡描述」和「作战条件」写在同一个字段里，条件段落用 `{{color|…}}`
标注；脚本在第一个 `{{color}}` 处截断，只留故事文本（`--with-conditions` 可保留全部）。悖论模拟同理。

**剧情脚本**：`[name="陈"] 台词` → `陈：台词`；`[multiline]`、`[Subtitle]`、`[Sticker]`、`[animtext]`、
`[Decision]`、`[HEADER]`、`[Dialog]` 都会翻译成可读文本，其余演出指令默认丢弃
（`--keep-directives` 保留）。

**跨页引用**：`{{#lst:页面|小节}}`、`{{:子页面}}`、`{{:{{PAGENAME}}/data}}` 会自动展开
（有两个密录页的正文字在 `/data` 子页里）。

**敌人文本**只保留 `描述` 字段，能力/数值/关卡效果等功能性内容不抓。

---

## 5. 集成战略（肉鸽）模块

7 个主题全部支持。各主题的网页结构差别很大，因此在 `prts_tool/collectors/roguelike.py` 的
`THEMES` 里逐个配置（事件用哪套模板、藏品/记录页叫什么、月度小队按小队还是按角色）：

| 主题（代码） | 事件 | 藏品页（数量/分类） | 结局 | 月度小队（目录名 / 单位） |
| --- | --- | --- | --- | --- |
| 刻俄柏的灰蕈迷境（RO） | `{{集成战略事件}}` 31 个 | 收藏品图鉴（182 / 1） | 3 | 无（首个主题没有这个系统） |
| 傀影与猩红孤钻（RO1） | `{{ISEvent/scene}}` 45 个 | 长生者宝盒（245 / 8） | 4 | 月度小队 / **按小队**（8） |
| 水月与深蓝之树（RO2） | `{{ISEvent/scene}}` 53 个 | 生物制品陈设（262 / 9） | 4 | 追忆映射 / 按角色（8） |
| 探索者的银凇止境（RO3） | `{{ISEvent/scene}}` 44 个 | 仪式用品索引（263 / 10） | 4 | 探索者档案 / 按角色（8） |
| 萨卡兹的无终奇语（RO4） | `{{ISEvent/scene}}` 52 个 | 想象实体图鉴（296 / 10） | 5 | 讲述者列表 / 按角色（8） |
| 岁的界园志异（RO5） | `{{ISEvent/scene}}` 58 个（含「代理人」子页） | 珍玩集册（294 / 9） | 5 | **游园访谈** / 按角色（8） |
| 沉沦者的黑流树海（RO6） | `{{ISEvent/scene}}` 39 个 | 拟造物质编目（251 / 8） | 4 | 实践者列表 / 按角色（4） |

产出说明：

* **事件**：每个事件一个 txt，含事件描述、各选项（行动 + 效果）与后续剧情。
  傀影及后续主题的大类（不期而遇 / 幕间余兴 / 古堡馈赠…）按页面里 `etype` 的出现位置顺延，
  与页面渲染逻辑一致。
* **藏品.txt**：分类为主标题、藏品名为次级标题，只保留描述文本（`效果` 等游戏内数值不抓）。
* **序章/avg.txt**：该主题的序章剧情（`ROn-BEG/NBT`）。
* **结局/结局N <名称>/**：`avg.txt` 是结局 avg 剧情；`part1.txt…` 是该结局附带的说明文本
  （结局表里的描述、戏剧彩排/展览的插画说明等，按页面顺序编号）。
  结局列表按页面自动发现，名称以主题数据为准。
* **月度小队/追忆映射/游园访谈/<名字>.txt**：目录名随主题变化（傀影叫「月度小队」、界园叫「游园访谈」）；
  傀影是一个小队一个文件，其余主题是**一个角色一个文件**（如 `游园访谈/左乐.txt` 里是该角色的
  `Part.01~03`，文件头写明「岁的界园志异 2025年7月 忆峥嵘 / 界园游客：左乐」）。
* **关卡.txt**：该主题在「关卡一览/活动关卡」里列出的全部关卡（`ISW-NO …`/`ISW-DF …`）+ 关卡描述。
* **加载文本.txt**：过场界面出现的世界观文本（`名称——说明` 形式的条目，游戏指引类的行会被过滤），
  来自记录页的「PRTS额外资料 → 探索情报板」。
* **其他文本/**：区域介绍、深入调查/探索、插画展览、专题小节（幻觉报告册 / 时代追忆 / 界园秘辛 …），
  以及各类道具图鉴：**思绪**（萨卡兹）、**密文板**（银凇止境）、**通宝**（岁的界园）、
  **零件**（黑流树海）、战术道具箱、活页剧目集、坍缩范式辑录。
  这些页面用子页面转写模板 `{{:主题/思绪|名称=…|描述=…}}` 而不是 `{{收藏品}}`，
  2.1.0 起按条目提取 名称 / 描述 / 效果 / 获取 / 占卜 等字段。

想再加一个主题：在 `THEMES` 里加一条 `ThemeSpec`（页面名 + 解析方式 + 小节名），
必要时补一个解析函数即可（`event_style` 决定事件用哪套解析）。

---

## 5.5 生息演算（reclamation）模块

生息演算的剧情页格式和普通剧情一样，但**不混在 avg 里**，单独一棵目录树：

```
reclamation/
├── 沙中之火/0506 沙中之火.txt  0507 结局1.txt …
├── 沙洲遗闻/0510 初来乍到.txt …
├── 重启锚点/0515 可露希尔的任务汇报.txt …
├── 沙中之火/事件/奇遇/树林的区别.txt     ← 事件一览里的 45 条（合并重复分支后 37 个文件）
├── 沙洲遗闻/事件/陌域奇遇/异兽之息.txt   ← 67 条（合并后 63 个文件）
├── 沙中之火/关卡文本.txt          ← stage 模块也认这些目录
└── _索引.md / _manifest.json
```

主题识别：导航表里大类为「生息演算」的行，外加首个场次「沙中之火」（它在导航表里被标成了支线）
以及 `RA…` 开头的页面。索引同样每次重新构建，新场次会自动出现。

**关于「沙中之火 / 沙洲遗闻 / 重启锚点」的关系**（这是 wiki 结构里最容易踩坑的地方）：

* 它们是**同一个生息演算模式的三个场次**：沙中之火（2023-01，`RA-*`）、
  沙洲遗闻（2024-02，是它的扩写版，`RA1-*`）、重启锚点（2026-05，`RA2-*`）。
* 三个场次**共用 `RA-*` 关卡代号、且关卡页没有「所属区域」**，所以光看代号一定会分错组。
  脚本用三条规则精确定位（`avg.folder_for_stage` + `stage.exact_stage_folders`）：
  1. 关卡页的 `关卡id`：`sandbox_0_*`→沙中之火、`sandbox_1_*`→沙洲遗闻、`sandbox_2_*`→重启锚点；
  2. 关卡页标题里的括号限定，如 `RA-NO 驻扎地(沙洲遗闻)`；
  3. 「关卡一览/活动关卡」里各场次小节的关卡清单（最权威）。
* 于是 `reclamation/沙中之火/关卡文本.txt`、`沙洲遗闻/关卡文本.txt`、`重启锚点/关卡文本.txt`
  各装各的关卡，不会互相串。

avg 模块会把这两类剧情**主动让给** `roguelike` / `reclamation`（`avg.py` 里的 `HANDOFF_*` 规则），
所以 `avg/` 下不会再出现「集成战略 X」「生息演算 X」这类目录。

> **新场次注意**：剧情页会由导航表自动发现；但「事件一览」的解析目前以
> `reclamation.py` 里的 `THEMES = ("沙中之火", "沙洲遗闻", "重启锚点")` 为准，
> 新场次需要把名字加进去，才会去抓 `<场次>/事件一览`。

---

## 5.6 泰拉记事社（terra）模块

**@泰拉记事社** 与 **@明日方舟Arknights** 微博发布的外部剧情资料（长图），
PRTS 用 `泰拉记事` 页面的 `{{微博|…}}` 模板收录，图片也已上传到 prts.wiki —— 所以直接抓 PRTS，
不去微博。

**目录位置**：默认在 `resources/collected/terra/`；采集文本默认在
`resources/collected/prts_text/`。图片与文本按资料类型分开。

```
resources/collected/terra/
├── 行于泰拉/<活动名>/说明.txt + 微博@泰拉记事社_2024-04-25_(1).jpg …
├── 泰拉那些事/…   其它档案/…
└── _索引.md / _manifest.json
```

**图片默认不下载**（这是本模块最重要的约定）：

| 命令 | 结果 |
| --- | --- |
| `prts_crawler.py terra` | 只写 `说明.txt` + `_索引.md`，**不下载图片** |
| `prts_crawler.py terra --images` | 文本 + 图片 |
| **`prts_crawler.py terra-images`** | **单独抓图**（等价于上一条），推荐用这个 |
| `prts_crawler.py terra-images --force` | 已有图片也重下一遍 |
| `prts_crawler.py update` / `all` / `refresh` | 只更新文本与索引，**永不下载图片** |

* 每个条目一个目录：`说明.txt` 记录微博链接、日期、标题、描述文本；图片保持 wiki 上的原文件名。
* 同名条目（例如「大地巡旅」有多期）用日期后缀区分：`大地巡旅（2023-09-30）`。
* 体积很大（67 条 / 169 张 / 约 408 MB），抓图前建议先 `--dry-run` 看规模；
  `--limit N` 只处理前 N 条（调试用），`--no-images` 显式关掉图片。
* 增量按图片的 sha1 判断，重跑不会重复下载；`_索引.md` 里会写「本地已下载 N 张」，
  一眼能看出图片到底抓了没有。

---

## 5.7 活动文本（activity）模块

`avg` 只收 `{{剧情模拟器}}`（关卡剧情）。活动页里还有一类**只存在于活动页**的正文，
最典型的是「孤星/综合调查数据库」——克丽斯腾在静滞所终端里看到“神”（保存者）的那段
通信就只在这里，关卡剧情里没有。`activity` 模块专门补这一类：

```
activity/
├── 孤星/综合调查数据库.txt
├── 叙拉古人/待办事项记录.txt
├── 崔林特尔梅之金/PRTS金律记录.txt
├── 愚人号/审判庭纪要.txt
├── 长夜临光/信息端口.txt
├── 沙中之火/PRTS绿洲记录.txt  日志.txt  敌袭记录.txt  剧情链.txt
├── 危机合约/涤墨作战/活动公告.txt
└── _索引.md / _manifest.json
```

**收录规则**（`prts_tool/collectors/activity.py`）：

* 活动名来自 `Template:剧情导航` 的分组名；子页面来自 `allpages&apprefix=<活动>/`
  （覆盖子子页面，如 `危机合约/涤墨作战/活动公告`）。
* 收所有 `活动公告`；其余页面名命中 `LORE_HINTS`（记录 / 日志 / 纪要 / 档案 /
  数据库 / 手记 / 来信 / 访谈 / 见闻 / 委托 / 报告 / 剧情 / 情报 / 庆典 / PRTS…）
  才收，并排除 `NOISE_HINTS`（关卡 / 商店 / 地图 / 合约指标 / 图鉴 / 行囊…）。
* **去重**：`avg` / `reclamation` 清单里已有的页面（如 `危机合约/剧情`）不再写；
  集成战略七个主题的图鉴与记录页由 `roguelike` 负责，这里只收它们的 `活动公告`。
* 正文用 `action=parse&prop=text` 取渲染后的 HTML，再由 `prts_tool/htmltext.py`
  转纯文本；这样表格、折叠框、HTML 样式不会留下 `{|` / `style=` 噪声。
* 汉字数少于 `--min-cjk`（默认 40）的页面记为「无正文」，不会反复重抓。

常用：

```powershell
m3-reader activity -g 孤星          # 只抓孤星
m3-reader activity --dry-run        # 先看会抓哪些页面
m3-reader activity --no-announcements   # 只收长文，跳过活动公告
m3-reader activity --force          # 全部重渲染
```

---

## 6. 扩展：再抓一类文本

### 6.1 通用接口（不改代码先摸数据）

```powershell
m3-reader fetch raw 锡兰                       # 取 wikitext
m3-reader fetch template 琴柳 悖论模拟           # 看模板全部参数
m3-reader fetch cargo chara --fields "_pageName=PAGE,cn,rarity" --where "cn='锡兰'"
m3-reader fetch category 联动活动                # 分类成员
m3-reader fetch embeddedin 家具信息              # 谁嵌入了某模板
```

### 6.2 新增一个采集器（自动变成子命令）

在 `prts_tool/collectors/` 下新建文件即可，CLI 会自动发现：

```python
# prts_tool/collectors/item.py
"""道具描述：Cargo item 表的 description/purpose/obtain_method。"""
from ..output import Manifest, sanitize, signature
from ..registry import Collector, Context, Stat, need_update, register

@register
class ItemCollector(Collector):
    name = "item"                       # → m3-reader item
    title = "道具文本（名称/描述/用途/获取方式）"
    help = "输出：OUT/item/<道具名>.txt"
    order = 50                          # all / refresh 的执行顺序

    def run(self, ctx: Context) -> Stat:
        stat = Stat()
        out = ctx.out_dir / "item"
        manifest = Manifest(out / "_manifest.json")
        for row in ctx.client.cargo_all("item", "_pageName=PAGE,name,description"):
            name = row.get("PAGE") or row.get("name")
            if not name or not ctx.match(name):
                continue
            sig = signature(row.get("description", ""))
            path = out / f"{sanitize(name)}.txt"
            if not need_update(ctx, manifest, name, sig, path.exists()):
                stat.skipped += 1
                continue
            if ctx.dry_run:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{name}\n{row.get('description','')}\n", encoding="utf-8")
            manifest.record(name, sig, file=path.name)
            stat.written += 1
        manifest.save()
        return stat
```

要点：继承 `Collector` + `@register` + 实现 `run(ctx)`；需要自定义参数时实现 `params()`，
返回 `click.Option` 列表（回调值会放进 `ctx.extra`）；用 `need_update()` 统一三种刷新模式，
用 `Manifest` 记增量签名。

基类上还有几个可选开关：

| 属性 | 作用 |
| --- | --- |
| `data_root = "terra"` | 数据放到**输出根的兄弟目录**（与 `prts_text` 并列），不塞进文本树 |
| `aliases = ({...},)` | 派生出额外子命令，可预设参数（terra 的 `terra-images = terra --images` 就是这么来的） |
| `order = 65` | `all` / `update` / `refresh` 里的执行顺序 |
| `params()` | 返回 `click.Option` 列表，自动挂到子命令上 |

`aliases` 的一项写成：

```python
aliases = (
    {"name": "item-images", "short": "道具图鉴：只抓图片",
     "help": "单独抓道具图片（默认不抓）。",
     "preset": {"images": True}},     # 预设值会覆盖同名 click 参数
)
```

---

## 7. 常见问题

**Q：403 Forbidden？**
prts.wiki 的 WAF 会拦浏览器 UA，并要求带 `Accept-Language`。本工具用自定义 UA +
`Accept-Language: zh-CN`，**不要**改成 `Mozilla/…`。另外不要直接抓 `/w/xxx` 这类 HTML（会命中反机器人挑战页）。

**Q：有没有「一次更新全部内容」的指令？**
`update` 就是：`m3-reader update`。它按 `changed` 模式跑全部模块——
既补缺失文件，又抓 wiki 上版本号变过的条目，已是最新的条目会跳过。
首次在新目录运行等价于全量；想强制重写全部文件加 `--force`，只补缺失加 `--missing`。
注意它**不下载 terra 的图片**（见下一条）。

**Q：`update` 跑完了，为什么 `terra/` 里只有 `说明.txt` 没有图片？**
这是设计如此：图片约 400 MB，混在「更新全部内容」里既慢又占地方。
`update` / `all` / `refresh` 对 terra 只更新说明与索引，
**唯一的取图方式是单独跑**：
```powershell
m3-reader terra-images              # 增量，已下过的不重下
m3-reader terra-images --force      # 全部重下
```
`terra` 命令本身也可以 `--images` 打开图片（等价写法）。

**Q：抓一半断了？**
每个模块边解析边写盘、定期保存清单；重跑 `refresh`（或 `-m missing`）即可接着补。

**Q：换了输出格式但文件没变？**
增量只看 wiki 版本号，换格式请配 `--force`，或换一个输出目录。

**Q：某些页面没有文件夹？**
`EP10/ENTRY` 这类纯视频过场在 wiki 上就没有台词；集成战略/卫戍协议的临时干员也没有档案。
脚本会记一笔「无文本」并跳过，不会每次重抓。

**Q：怎么快速找一个章节？**
`avg/_索引.md`、`operator/_索引.md`、`furniture/_家具索引.md`、`roguelike/_索引.md`
都是自动生成的目录。

**Q：改了源码后行为没变？**
Python 的字节码缓存偶尔会因为「源码 mtime + 文件大小都没变」而命中旧缓存，
遇到怪问题时删掉 `__pycache__` 或加 `PYTHONDONTWRITEBYTECODE=1` 再跑。

---

## 8. 维护、已知坑与版本日志

### 8.1 已知坑（按踩坑时间记录）

| # | 现象 / 坑 | 处理方式 |
| --- | --- | --- |
| 1 | 直接抓 `/w/xxx` 会命中 Anubis 反机器人挑战页 | 只走 `api.php` / `index.php?action=raw`；`Accept-Language` 必带 |
| 2 | 全量扫描时偶发 `503 Service Temporarily Unavailable` | 2026-10-24 实测：短时间内大量 `action=parse` / `allpages` 会触发。把 `--delay` 调到 `1.0~1.5`，等 1~2 分钟再跑；`PrtsClient` 自带 4 次退避重试 |
| 3 | `Template:剧情导航` 的分组里混着肉鸽 / 生息演算 | `avg` 通过 `HANDOFF_*` 主动让给 `roguelike` / `reclamation`；不要在 avg 里再收一遍 |
| 4 | 旧版 `avg/特殊 <干员>/` 与 `operator/<干员>/avgN-*.txt` 完全重复 | 2.1.0 起 avg 跳过 `干员名/干员密录/N`；每次 avg 运行会清理旧清单中的重复文件（只删 operator 已存在的） |
| 5 | 活动页大量 HTML / 表格 / 折叠框，直接清 wikitext 会留下 `{|`、`style=` | `activity` 走 `action=parse&prop=text`，再用 `prts_tool/htmltext.py` 转纯文本；目录、编辑链接、音频播放器降级提示会被丢弃 |
| 6 | `activity` 按页面名启发式选长文，新活动可能出现没见过的子页面名 | 先看 `activity/_索引.md`；漏了就往 `LORE_HINTS` 加关键词，或临时用 `-g <活动>` 检查 `--dry-run` 输出。子页面索引缓存在 `activity/_pages.json`（7 天），新活动或改规则后用 `--refresh-index` 强制重扫 |
| 7 | `resources/updates/new/` 只保留文件的直接上一级目录，同名文件会加 ` (2)` | 这是「最近一次写入」的快照；主归档在 `resources/collected/prts_text/` |
| 8 | 大地巡旅 PDF（`resources/local/大地巡旅/`）没有文字层 | `pdftotext` 输出为空；2026-10-24 已用 `tesseract-ocr` + `tesseract-ocr-chi-sim` 重跑 454 页，449 页有正文，合并为同目录的 `大地巡旅_OCR.txt`（约 47.7 万字）。重跑/检索见 `docs/OCR_README.md` |
| 9 | `EP10/ENTRY`、`CR-BEG/NBT` 等页面没有台词 | 模块会记「无正文」，不会每次重抓；这是 wiki 本身只有演出/视频 |
| 10 | 索引与清单是自动生成的 | 不要手改 `_索引.md` / `_manifest.json`；重跑对应模块即可 |

### 8.2 日常维护流程

```powershell
# 1. 日常增量（不含 terra 图片）
m3-reader update

# 2. 只补活动长文（新活动上线后）
m3-reader activity --dry-run
m3-reader activity

# 3. 改了某个采集器的解析逻辑后，强制重写该模块
m3-reader refresh -m activity --force
m3-reader refresh -m roguelike --force

# 4. 肉鸽新增主题：在 roguelike.py 的 THEMES 加 ThemeSpec，然后
m3-reader roguelike --theme <新主题名>
```

**检查完整性的小命令**（在 `m3-reader/` 下执行）：

```bash
# 正文完全重复的文件（应为 0）
python3 - <<'PY'
import glob,hashlib,re,collections
sig=collections.defaultdict(list)
for p in glob.glob('resources/collected/prts_text/**/*.txt',recursive=True):
    if p.rsplit('/',1)[-1].startswith('_'): continue
    b=re.sub(r'\s+','',open(p,encoding='utf-8').read().split('---',1)[-1])
    if len(b)>=200: sig[hashlib.md5(b.encode()).hexdigest()].append(p)
for v in sig.values():
    if len(v)>1: print(v)
PY
```

**新增采集器**：在 `prts_tool/collectors/` 放一个继承 `Collector` 并 `@register` 的类，
CLI 会自动发现；同时在本 README 的模块表、输出树和 `CHANGELOG.md` 里补一行。

**PDF / 扫描件**：`resources/local/大地巡旅/大地巡旅_OCR.txt` 是《大地巡旅》的 OCR 全文；
重新 OCR 用 `python -m prts_tool.ocr_book`（增量）或加 `--force`（全量），
细节见 [OCR 说明](docs/OCR_README.md)。

### 8.3 版本日志

完整记录见 [`CHANGELOG.md`](CHANGELOG.md)。最近更新：

* **2.5.3（2026-10-25）**：TUI 改为终端式焦点：启动即命令栏，任意区域输入字符都能
  开始命令；修复只读区抢占 `n`/`N`/`/`/`?` 导致首字符丢失。Enter 始终提交并清空，
  Tab 唯一匹配立即补全，Ctrl+U/Ctrl+C 清空，PageUp/PageDown 滚动。

* **2.5.2（2026-10-25）**：TUI 命令栏支持 Tab 补全、↑↓ 历史和 Esc 返回；更新显示
  实时进度并可 `Ctrl+C` 取消，错误按级别提示。GUI 启动时默认隐藏更新意见和变动栏，
  顶部工具栏新增「变动栏」开关。

* **2.5.1（2026-10-25）**：新增免安装 CLI 启动器 `scripts/install_cli.sh`
  （`~/.local/bin` 软链接，不依赖 pip/虚拟环境），命令行帮助统一显示 `m3-reader`；
  工程代码纳入 Git 管理，资源与运行数据不跟踪。

* **2.5.0（2026-10-25）**：更名为 M3 Reader；提供不带用户资料和采集正文的 Windows 便携包及 Ubuntu 源码安装包。

* **2.4.0（2026-10-25）**：非采集资料统一归入 `resources/local/`，意见改为可直接编辑的
  本地 Markdown，优化文本换行、缩放和历史差异；新增 Windows / Ubuntu 可执行程序构建入口。

* **2.3.0（2026-10-25）**：新增 GUI / TUI、共享搜索、逐行更新历史、本地意见和
  手动资料导入替换；提供 Windows 与 Ubuntu GUI 入口。
* **2.2.0（2026-10-25）**：资源统一移至 `resources/`，爬虫默认输出、terra 图文、
  图片 OCR 和《大地巡旅》PDF / OCR 均按来源分类；OCR 工具移入 `prts_tool/`。

---

## 9. 文件清单

```
prts_crawler.py              主入口（click）
prts_story_crawler.py        旧入口兼容层
scripts/install_cli.sh       安装 m3-reader / m3-reader-gui 命令（软链接，不需 pip）
scripts/m3-reader            CLI 启动器（任意工作目录均可运行）
scripts/m3-reader-gui        GUI 启动器（等价于 m3-reader gui）
prts_tool/
├── http.py                  PrtsClient：api / raw / cargo / embeddedin / category + 重试限速
├── wikitext.py              模板参数、章节切片、标记清理、风味文本提取
├── story.py                 剧情脚本 DSL 解析 + 跨页引用展开
├── htmltext.py              渲染后 HTML → 纯文本（活动页用）
├── output.py                文件名清洗（含多级路径）、自然排序、增量 Manifest
├── registry.py              Collector 基类 / 注册表 / 公共 click 参数
├── cli.py                   命令组装（子命令自动生成）
├── paths.py                 默认资源路径
├── library.py               资源枚举、搜索与本地意见
├── history.py               更新前后版本、逐行差异与本地资料导入
├── jobs.py                  更新参数及跨进程文件锁
├── gui.py                   PySide6 GUI
├── tui.py                   prompt_toolkit TUI
├── ocr_book.py              《大地巡旅》PDF OCR
└── collectors/
    ├── avg.py               剧情 + 分类分层（供 stage 复用章节映射）
    ├── activity.py          活动公告 / 活动专属长文
    ├── stage.py             关卡文本
    ├── operator.py          干员档案 / 模组 / 密录 / 悖论模拟
    ├── furniture.py         家具主题 / 独立家具
    ├── enemies.py           敌人描述（普通/精英/领袖）
    ├── roguelike.py         集成战略（按主题量身定制）
    ├── reclamation.py       生息演算（沙中之火 / 沙洲遗闻 / 重启锚点）
    └── terra.py             泰拉记事社（默认只写说明；图片要 terra-images）
README_剧情爬虫.md           本说明
CHANGELOG.md                 版本日志（改代码 / 增模块时同步更新）
resources/collected/prts_text/   文本数据（默认输出根，目录名与子命令一致）
├── avg/                     剧情（主线/支线/联动/故事集/四月辑录）
├── activity/                活动公告与活动专属长文
├── operator/                干员档案、模组、密录、悖论模拟
├── furniture/               家具主题 + 独立家具
├── enemies/                 敌人描述（普通/精英/领袖）
├── roguelike/               集成战略 7 个主题
└── reclamation/             生息演算 3 个场次
resources/collected/terra/     泰拉记事社（说明.txt + 索引，图片靠 terra-images 抓）
resources/ocr/terra_text/    terra 图片的 OCR 文本
resources/local/大地巡旅/           整本 PDF、页面图、OCR 文本
prts-wiki-map/               站点结构勘察资料（数据来源与坑位；与本工具同级，勿删）
```


