-- Tushare A股日线行情表
CREATE TABLE daily_stock_quotes (
    ts_code      TEXT    NOT NULL,  -- 股票代码
    trade_date   TEXT    NOT NULL,  -- 交易日期 YYYYMMDD

    open         REAL,              -- 开盘价
    high         REAL,              -- 最高价
    low          REAL,              -- 最低价
    close        REAL,              -- 收盘价

    pre_close    REAL,              -- 昨收价（除权价）
    change       REAL,              -- 涨跌额
    pct_chg      REAL,              -- 涨跌幅（%）

    vol          REAL,              -- 成交量（手）
    amount       REAL,              -- 成交额（千元）

    PRIMARY KEY (ts_code, trade_date)
);

-- 常用查询索引
CREATE INDEX idx_daily_trade_date
ON daily_stock_quotes(trade_date);

CREATE INDEX idx_daily_ts_code
ON daily_stock_quotes(ts_code);