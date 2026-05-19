-- Tushare stock_basic 输出参数表
CREATE TABLE stock_basic (
    ts_code        TEXT PRIMARY KEY,   -- TS代码
    symbol         TEXT,               -- 股票代码
    name           TEXT,               -- 股票名称
    area           TEXT,               -- 地域
    industry       TEXT,               -- 所属行业
    fullname       TEXT,               -- 股票全称
    market         TEXT,               -- 市场类型
    exchange       TEXT,               -- 交易所代码
    list_date      TEXT,               -- 上市日期 YYYYMMDD
    is_hs          TEXT                -- 是否沪深港通标的
);

-- 常用索引
CREATE INDEX idx_stock_basic_symbol
ON stock_basic(symbol);

CREATE INDEX idx_stock_basic_name
ON stock_basic(name);

CREATE INDEX idx_stock_basic_industry
ON stock_basic(industry);

CREATE INDEX idx_stock_basic_market
ON stock_basic(market);
