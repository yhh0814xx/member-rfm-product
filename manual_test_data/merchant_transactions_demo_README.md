# Merchant Transactions Demo

## 模拟商家背景

该数据模拟一家经营家居用品、生活用品与小型电子产品的综合零售商。数据由固定随机种子 `20260706` 和明确的客户行为规则独立生成，未读取、复制、抽样或修改项目中的 stage3/UCI 数据。

## 文件与字段

- `merchant_transactions_demo.xlsx`：主要测试文件，仅含 `Transactions` 工作表。
- `merchant_transactions_demo.csv`：与 XLSX 相同的明细，UTF-8 编码。
- 字段：`InvoiceNo`、`StockCode`、`Description`、`Quantity`、`InvoiceDate`、`UnitPrice`、`CustomerID`、`Country`。
- `CustomerID` 为匿名合成标识；不含姓名、电话、地址或其他真实个人信息。

## 原始数据统计

- 时间范围：2025-01-01 09:00:00 至 2025-12-31 20:00:00
- 客户数：500
- 订单数：3,102
- 交易明细行数：8,977
- 商品数：80
- 国家数：8
- 总销量：35,249
- 总金额：808,531.52

## 生成规则

客户被设计为近期高频高消费、稳定复购、近期新增、近期潜力、流失风险、重点挽回、沉睡和流失八类行为原型。订单包含 2–4 个不同商品；价格、销量、国家规模、月份和复购频率均有差异。三个低价商品被设为高销量商品，三个较高价格商品被设为高金额商品，另有三个低销量长尾商品。八个商品仅在指定国家销售，以支持国家与商品组合筛选。原始数据不写入 RFM Segment，分层完全由项目 pipeline 计算。

## 推荐人工测试步骤

1. 在上传页选择 XLSX，确认校验通过且无阻断错误。
2. 执行一键分析并选择新 run。
3. 依次检查经营总览、月度趋势、国家分析、商品分析、Cohort 留存、交易明细、RFM 与聚类、会员运营建议和下载中心。
4. 先使用完整日期范围，再按季度或单月缩小日期范围，观察客户数、订单数、收入和名单变化。
5. 分别筛选 `China`、`Singapore`、`Australia`、`United Kingdom`；再与下列常见商品组合筛选。
6. 搜索下列 CustomerID，核对交易明细、RFM 客户展示和建议名单。

## 推荐筛选国家

- China（客户与交易最多）
- Singapore（中等规模且含区域商品）
- Australia（中等规模且含区域商品）
- United Kingdom（较小规模且含区域商品）

## 推荐筛选商品

- `SKU050 | Smart Temperature Sensor`
- `SKU047 | Mini Air Quality Monitor`
- `SKU028 | LED Floor Lamp`
- `SKU060 | Eco Cleaning Sponge Pack`
- `SKU051 | Microfiber Cleaning Cloth`
- `SKU034 | A5 Hardcover Notebook`

## 推荐查询 CustomerID

- `M0001`：recent_high_value
- `M0061`：stable_repeat
- `M0151`：new_customer
- `M0206`：recent_potential
- `M0271`：at_risk
- `M0331`：cant_lose
- `M0376`：hibernating
- `M0446`：lost

> 本文件为合成测试数据，不含真实个人信息，也不代表真实商家经营结果。
