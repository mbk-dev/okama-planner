# 用户指南

[English](en.md) · [Русский](ru.md) · [Deutsch](de.md) · [Español](es.md) · [中文](zh.md)

## 安装与运行

okama Planner 用于建立家庭月度现金流和蒙特卡洛预测。支持 Python 3.11 及以上版本。导出 Excel 时，请安装 `reports` 扩展。开发配置使用 Python 3.14；参与代码开发时，请明确选择该解释器：

```bash
git clone https://github.com/mbk-dev/okama-planner.git
cd okama-planner
poetry env use python3.14
poetry install --extras reports
poetry run python examples/localized_plan.py --output-dir tmp/localized-example
```

此示例无需下载市场数据、启动浏览器或访问客户数据库。它使用虚构的 USD 金额和固定的合成月度收益率。以 `seed=42` 计算一次后，保存 `request.json` 和 `result.json`，再导出 `plan-en.xlsx`、`plan-ru.xlsx`、`plan-de.xlsx`、`plan-es.xlsx`、`plan-zh.xlsx`，以及各语言 `linear/` 和 `log/` 目录中的离线交互式 `forecast.html`。在本地打开 HTML 文件即可查看投资组合和净资产。五个版本的 USD 金额、假设和数值结果完全相同。随机种子并不固定依赖版本；精确复现时还需保留环境版本。

用 `--languages en zh` 选择需要的语言。安装 Chrome 或 Chromium 后，可添加 `--image-format png` 或 `--image-format svg` 生成静态图表；`--browser-executable /path/to/chromium` 指定浏览器可执行文件。HTML 和 Excel 导出不需要浏览器。

## 编制计划

从[虚构请求](../../examples/baseline-request.json)开始，将完整请求传给 `okama_planner` 的 `forecast(request)`。`plan.t0` 是起始月份；还需提供规划期限、退休时间、资产、负债、月收入和月支出。每个目标应指定唯一的 `goal_id`、名称 `label`、类型 `kind`、当前金额 `amount_pv`、估值年份 `pv_year` 和目标日期。利率和概率用小数表示：`0.02` 代表 2%。收入和支出输入为正数；现金流明细将支出记为负数。

`currency="USD"` 指定计算货币。`export_report` 或 `export_charts` 的 `language="zh"` 选择中文展示。语言不会兑换货币，也不会改变通胀、投资组合收益或法律假设。用户填写的名称保持原样；制作另一语言版本时请自行翻译这些名称。[本地化约定](../localization.md)说明了支持的消息、格式和 MCP 启动语言设置。

单币种请求使用一种货币。多币种请求需明确指定 `reporting_currency`、原币种的 `currency_groups` 和汇率假设；翻译后的报告保留各组原币种及报告货币。请参阅[多币种规划](../multicurrency.md)和[投资组合模式](../portfolio-modes.md)。本地化不会补充输入中缺少的税费，也不会向预测请求添加不支持的 gamma/alpha 字段。

## 阅读与保存结果

报告和图表中的金额是名义金额，指数化遵循输入的利率。通胀不会自动将图表金额转换为不变购买力。在对数坐标下，零值和负值被省略，受影响的区间带会出现空缺；请用线性图表查看这些时期。

导出使用已保存的请求和结果快照，不会重新运行预测：

```python
import json
from pathlib import Path
from okama_planner.reports import export_report
from okama_planner.charts import export_charts

folder = Path("tmp/localized-example")
request = json.loads((folder / "request.json").read_text())
result = json.loads((folder / "result.json").read_text())
export_report([{"label": "Synthetic USD", "request": request, "result": result}],
              folder / "review.xlsx", language="zh")
export_charts(result, folder / "review", language="zh")
```

修改工作簿中的数字不会重新计算蒙特卡洛。若需变更计划，请修改输入，重新运行 `forecast`，保存新快照后再导出。使用 Excel 汇总公式的缓存值前，请先重新计算公式。请将原始 JSON 和计算来源信息与导出文件一并保存。

## 本地记录与隐私

可选的 SQLite 客户登记库在本地保存客户、计划版本、情景和结果。姓名和联系方式应保存在登记库中；共享材料中使用客户登记代码。请勿将数据库或真实客户文档放入公开的 Git 仓库。本地化只改变展示文本；SQL 表名和列名、JSON 键、枚举值及技术标识符保持稳定。[存储指南](../storage.md)提供数据库设置和 API 示例。
