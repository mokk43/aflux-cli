#!/usr/bin/env python3
"""今日热点板块分析 - 多数据源汇总。

数据源：
  - 申万行业指数 (sw_daily)          → 今日行业涨跌排行
  - 东财概念/行业指数 (dc_daily)      → 概念板块 + 行业板块涨跌排行
  - 同花顺 App 热榜 (ths_hot)         → 市场关注热度排行
  - 涨停列表 (limit_list_d)          → 涨停行业集中度
  - 板块资金流向 (moneyflow_ind_dc)   → 板块资金净流入

输出：Markdown 格式的热点板块研究简报。
"""

import pandas as pd
import tushare as ts
from datetime import datetime

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 300)
pd.set_option("display.max_colwidth", 50)

pro = ts.pro_api()

# ============================================================
# 配置
# ============================================================
TRADE_DATE = "20260518"  # 目标交易日，格式 YYYYMMDD
LAST_TRADING_DATE = "20260515"  # 最近有热榜数据的日期（ths_hot/dc_hot 盘后才更新）

# ============================================================
# 1. 交易日确认
# ============================================================
cal = pro.trade_cal(exchange="SSE", start_date=TRADE_DATE, end_date=TRADE_DATE)
is_open = cal.iloc[0]["is_open"] if len(cal) > 0 else 0
print(f"交易日: {TRADE_DATE}  is_open={is_open}")
if not is_open:
    print(f"{TRADE_DATE} 非交易日，请调整日期后重试。")

# ============================================================
# 2. 申万行业指数涨跌排行
# ============================================================
print("\n" + "=" * 60)
print(f"【申万行业指数涨跌排行】{TRADE_DATE}")
print("=" * 60)

sw = pro.sw_daily(trade_date=TRADE_DATE)
sw = sw.sort_values("pct_change", ascending=False)

print(f"\n涨幅前 15:")
print(sw.head(15)[["name", "pct_change", "close", "change", "vol"]].to_string(index=False))

print(f"\n跌幅前 10:")
print(sw.tail(10)[["name", "pct_change", "close", "change", "vol"]].to_string(index=False))

up = len(sw[sw["pct_change"] > 0])
down = len(sw[sw["pct_change"] < 0])
print(f"\n涨: {up}  跌: {down}  平: {len(sw) - up - down}")

# ============================================================
# 3. 东财概念/行业板块涨跌排行
# ============================================================
print("\n" + "=" * 60)
print(f"【东财概念板块涨幅前 15】{TRADE_DATE}")
print("=" * 60)

# dc_daily 不含板块名，需 join dc_index
dc_idx = pro.dc_index(trade_date=TRADE_DATE)
dc_daily = pro.dc_daily(trade_date=TRADE_DATE)
dc = dc_daily.merge(dc_idx[["ts_code", "name"]], on="ts_code", how="left")

# 概念板块
concept = dc[dc["category"] == "概念板块"].sort_values("pct_change", ascending=False)
# 过滤掉打板衍生指标（昨日xxx）
concept_real = concept[~concept["name"].str.startswith("昨日")]
print(concept_real.head(15)[["name", "pct_change", "close", "change", "turnover_rate"]].to_string(index=False))

# 行业板块
print(f"\n【东财行业板块涨幅前 15】{TRADE_DATE}")
print("=" * 60)
industry = dc[dc["category"] == "行业板块"].sort_values("pct_change", ascending=False)
print(industry.head(15)[["name", "pct_change", "close", "change", "turnover_rate"]].to_string(index=False))

# ============================================================
# 4. 涨停行业集中度
# ============================================================
print("\n" + "=" * 60)
print(f"【涨停行业集中度】{TRADE_DATE}")
print("=" * 60)

lim = pro.limit_list_d(trade_date=TRADE_DATE, limit_type="U")
print(f"涨停家数: {len(lim)}")
if "industry" in lim.columns:
    top_ind = lim["industry"].value_counts().head(10)
    print("涨停最多的行业:")
    for ind, cnt in top_ind.items():
        print(f"  {ind}: {cnt} 家")

# ============================================================
# 5. 同花顺 App 热榜（概念板块热度）
# ============================================================
print("\n" + "=" * 60)
print(f"【同花顺 App 热榜 - 概念板块】{LAST_TRADING_DATE} (最近可用)")
print("=" * 60)

ths = pro.ths_hot(trade_date=LAST_TRADING_DATE)
if len(ths) > 0:
    concept_hot = ths[ths["data_type"] == "概念板块"] if "data_type" in ths.columns else ths
    print(concept_hot.head(15)[["rank", "ts_name", "pct_change", "hot"]].to_string(index=False))
else:
    print("无数据（可能盘后尚未更新）")

# ============================================================
# 6. 板块资金流向 (东财口径)
# ============================================================
print("\n" + "=" * 60)
print(f"【板块资金流向(DC) 净流入前 10】{TRADE_DATE}")
print("=" * 60)

mf = pro.moneyflow_ind_dc(trade_date=TRADE_DATE)
mf = mf.sort_values("net_amount", ascending=False)
print(mf.head(10)[["name", "pct_change", "net_amount", "net_amount_rate"]].to_string(index=False))

# ============================================================
# 7. 快速总结
# ============================================================
print("\n" + "=" * 60)
print("【热点主线速览】")
print("=" * 60)

# 合并申万 + 东财概念 找共同方向
sw_top5_names = set(sw.head(5)["name"].tolist())
concept_top10_names = set(concept_real.head(10)["name"].tolist())
print(f"申万 Top5 行业: {sw_top5_names}")
print(f"东财 Top10 概念: {concept_top10_names}")
