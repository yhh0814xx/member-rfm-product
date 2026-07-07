#!/usr/bin/env python
"""Generate deterministic synthetic merchant transactions for manual testing.

The data is created from behavioral rules and a synthetic product catalog. It
does not read or derive from any existing project dataset.
"""

from __future__ import annotations

import csv
import json
import os
import random
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


SEED = 20260706
START_DATE = datetime(2025, 1, 1, 9, 0)
END_DATE = datetime(2025, 12, 31, 20, 0)
FIELDS = [
    "InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate",
    "UnitPrice", "CustomerID", "Country",
]

COUNTRY_WEIGHTS = {
    "China": 0.25,
    "Singapore": 0.15,
    "Malaysia": 0.13,
    "Australia": 0.12,
    "United Kingdom": 0.11,
    "Germany": 0.09,
    "France": 0.08,
    "Canada": 0.07,
}

BEHAVIOR_SPECS = [
    ("recent_high_value", 60, (12, 16), (datetime(2025, 6, 1), END_DATE)),
    ("stable_repeat", 90, (7, 11), (START_DATE, END_DATE)),
    ("new_customer", 55, (1, 1), (datetime(2025, 12, 1), END_DATE)),
    ("recent_potential", 65, (2, 4), (datetime(2025, 9, 1), END_DATE)),
    ("at_risk", 60, (6, 9), (START_DATE, datetime(2025, 8, 31, 20, 0))),
    ("cant_lose", 45, (10, 14), (START_DATE, datetime(2025, 6, 30, 20, 0))),
    ("hibernating", 70, (1, 2), (datetime(2025, 5, 1), datetime(2025, 9, 15, 20, 0))),
    ("lost", 55, (1, 3), (START_DATE, datetime(2025, 4, 30, 20, 0))),
]


def _catalog() -> list[dict]:
    category_products = {
        "Home Storage": [
            "Stackable Storage Box", "Glass Storage Jar", "Bamboo Drawer Organizer",
            "Foldable Fabric Bin", "Vacuum Storage Bag", "Shoe Storage Rack",
            "Wall Mounted Hook Set", "Underbed Storage Case", "Metal Utility Basket",
            "Acrylic Cosmetic Organizer",
        ],
        "Kitchen": [
            "Stainless Steel Bottle", "Silicone Spatula Set", "Bamboo Cutting Board",
            "Ceramic Coffee Mug", "Digital Kitchen Scale", "Lunch Container Set",
            "Stainless Steel Colander", "Manual Coffee Grinder", "Insulated Food Jar",
            "Glass Measuring Cup",
        ],
        "Lighting": [
            "LED Desk Lamp", "Rechargeable Night Light", "Motion Sensor Cabinet Light",
            "Outdoor String Lights", "Clip Reading Lamp", "Smart Color Bulb",
            "Solar Garden Light Set", "LED Floor Lamp", "Portable Lantern",
            "Dimmable Bedside Lamp",
        ],
        "Office": [
            "Ergonomic Laptop Stand", "Mesh Desk Organizer", "Wireless Mouse Pad",
            "A5 Hardcover Notebook", "Cable Management Box", "Desktop Document Tray",
            "Adjustable Monitor Riser", "Metal Pen Holder", "Weekly Planner Pad",
            "Cork Bulletin Board",
        ],
        "Electronics": [
            "Portable USB Fan", "Compact Power Bank", "Bluetooth Mini Speaker",
            "USB C Charging Hub", "Wireless Charging Pad", "Digital Alarm Clock",
            "Mini Air Quality Monitor", "Rechargeable Hand Warmer", "Travel Adapter",
            "Smart Temperature Sensor",
        ],
        "Cleaning": [
            "Microfiber Cleaning Cloth", "Spray Mop", "Silicone Dish Brush",
            "Reusable Lint Roller", "Window Cleaning Squeegee", "Mini Desktop Vacuum",
            "Laundry Mesh Bag Set", "Bamboo Cleaning Brush", "Dustpan and Brush Set",
            "Eco Cleaning Sponge Pack",
        ],
        "Textile": [
            "Cotton Cushion Cover", "Waffle Kitchen Towel", "Soft Fleece Throw",
            "Microfiber Bath Towel", "Linen Table Runner", "Cotton Apron",
            "Blackout Curtain Panel", "Quilted Sofa Protector", "Canvas Tote Bag",
            "Cooling Pillow Case",
        ],
        "Outdoor": [
            "Collapsible Water Bottle", "Picnic Blanket", "Camping Cutlery Set",
            "Waterproof Dry Bag", "Portable Folding Stool", "Garden Kneeling Pad",
            "Bike Phone Holder", "Compact Travel Umbrella", "Insulated Cooler Bag",
            "Solar Camping Shower",
        ],
    }
    base_prices = {
        "Home Storage": 18.0, "Kitchen": 16.0, "Lighting": 28.0, "Office": 20.0,
        "Electronics": 42.0, "Cleaning": 12.0, "Textile": 22.0, "Outdoor": 30.0,
    }
    expensive = {"LED Floor Lamp", "Mini Air Quality Monitor", "Smart Temperature Sensor"}
    high_volume = {"Microfiber Cleaning Cloth", "Eco Cleaning Sponge Pack", "A5 Hardcover Notebook"}
    low_volume = {"Solar Camping Shower", "Blackout Curtain Panel", "Quilted Sofa Protector"}
    regional = {
        "Solar Garden Light Set": "Australia", "Smart Color Bulb": "Germany",
        "Insulated Food Jar": "China", "Cooling Pillow Case": "Singapore",
        "Garden Kneeling Pad": "United Kingdom", "Linen Table Runner": "France",
        "Waterproof Dry Bag": "Canada", "Bamboo Cleaning Brush": "Malaysia",
    }
    products = []
    index = 1
    for category, names in category_products.items():
        for offset, name in enumerate(names):
            price = base_prices[category] * (0.72 + offset * 0.095)
            if name in expensive:
                price *= 3.8
            if name in high_volume:
                price *= 0.42
            products.append({
                "StockCode": f"SKU{index:03d}",
                "Description": name,
                "Category": category,
                "UnitPrice": round(price + (index % 4) * 0.35, 2),
                "weight": 8.0 if name in high_volume else (0.10 if name in low_volume else 1.0),
                "regional_country": regional.get(name),
                "high_volume": name in high_volume,
                "expensive": name in expensive,
            })
            index += 1
    return products


def _weighted_choice(rng: random.Random, items: list, weights: list[float]):
    return rng.choices(items, weights=weights, k=1)[0]


def _random_datetime(rng: random.Random, low: datetime, high: datetime) -> datetime:
    seconds = int((high - low).total_seconds())
    value = low + timedelta(seconds=rng.randint(0, max(seconds, 0)))
    return value.replace(second=0, microsecond=0)


def _customer_countries(rng: random.Random, count: int) -> list[str]:
    countries = list(COUNTRY_WEIGHTS)
    weights = list(COUNTRY_WEIGHTS.values())
    assigned = countries.copy()  # guarantee every country has distinct customers
    assigned.extend(rng.choices(countries, weights=weights, k=count - len(countries)))
    rng.shuffle(assigned)
    return assigned


def generate_rows() -> tuple[list[dict], dict[str, str]]:
    rng = random.Random(SEED)
    products = _catalog()
    country_assignments = _customer_countries(rng, 500)
    customers = []
    customer_index = 0
    for behavior, count, frequency_range, date_window in BEHAVIOR_SPECS:
        for _ in range(count):
            customer_index += 1
            customers.append({
                "CustomerID": f"M{customer_index:04d}",
                "Country": country_assignments[customer_index - 1],
                "behavior": behavior,
                "frequency": rng.randint(*frequency_range),
                "date_window": date_window,
            })

    invoices = []
    invoice_sequence = 1
    for customer in customers:
        low, high = customer["date_window"]
        dates = sorted(_random_datetime(rng, low, high) for _ in range(customer["frequency"]))
        # Force representative boundary dates and complete monthly coverage.
        if customer["CustomerID"] == "M0001":
            dates[-1] = END_DATE
        if customer["CustomerID"] == "M0376":
            dates[0] = START_DATE
        for order_date in dates:
            invoices.append({
                "InvoiceNo": f"INV25{invoice_sequence:05d}",
                "InvoiceDate": order_date,
                **customer,
            })
            invoice_sequence += 1

    # Ensure all calendar months occur even if behavior sampling changes later.
    months_present = {invoice["InvoiceDate"].month for invoice in invoices}
    for month in range(1, 13):
        if month not in months_present:
            target = invoices[month - 1]
            target["InvoiceDate"] = datetime(2025, month, 15, 12, 0)

    rows = []
    for invoice in invoices:
        country = invoice["Country"]
        eligible = [p for p in products if p["regional_country"] in (None, country)]
        line_count = rng.choices([2, 3, 4], weights=[0.30, 0.50, 0.20], k=1)[0]
        chosen = []
        pool = eligible.copy()
        for _ in range(line_count):
            weights = [p["weight"] for p in pool]
            product = _weighted_choice(rng, pool, weights)
            chosen.append(product)
            pool.remove(product)
        # Give high-value behaviors a controlled preference for expensive items.
        if invoice["behavior"] in {"recent_high_value", "cant_lose"} and rng.random() < 0.48:
            expensive = [p for p in eligible if p["expensive"]]
            replacement = rng.choice(expensive)
            if replacement not in chosen:
                chosen[-1] = replacement
        for product in chosen:
            if product["high_volume"]:
                quantity = rng.randint(4, 12)
            elif product["expensive"]:
                quantity = rng.choices([1, 2, 3], weights=[0.75, 0.20, 0.05], k=1)[0]
            else:
                quantity = rng.choices([1, 2, 3, 4, 5], weights=[0.28, 0.30, 0.22, 0.13, 0.07], k=1)[0]
            if invoice["behavior"] in {"recent_high_value", "cant_lose"} and not product["expensive"]:
                quantity += rng.choice([0, 1, 2])
            rows.append({
                "InvoiceNo": invoice["InvoiceNo"],
                "StockCode": product["StockCode"],
                "Description": product["Description"],
                "Quantity": quantity,
                "InvoiceDate": invoice["InvoiceDate"].strftime("%Y-%m-%d %H:%M:%S"),
                "UnitPrice": product["UnitPrice"],
                "CustomerID": invoice["CustomerID"],
                "Country": country,
            })
    rng.shuffle(rows)
    sample_ids = {
        "recent_high_value": "M0001", "stable_repeat": "M0061", "new_customer": "M0151",
        "recent_potential": "M0206", "at_risk": "M0271", "cant_lose": "M0331",
        "hibernating": "M0376", "lost": "M0446",
    }
    return rows, sample_ids


def _stats(rows: list[dict], sample_ids: dict[str, str]) -> dict:
    dates = [datetime.strptime(row["InvoiceDate"], "%Y-%m-%d %H:%M:%S") for row in rows]
    country_counts = Counter(row["Country"] for row in rows)
    monthly_counts = Counter(date.strftime("%Y-%m") for date in dates)
    product_amounts = Counter()
    product_qty = Counter()
    for row in rows:
        key = f'{row["StockCode"]} | {row["Description"]}'
        product_amounts[key] += row["Quantity"] * row["UnitPrice"]
        product_qty[key] += row["Quantity"]
    sample_products = [name for name, _ in product_amounts.most_common(3)]
    sample_products.extend(name for name, _ in product_qty.most_common(3) if name not in sample_products)
    return {
        "row_count": len(rows),
        "invoice_count": len({row["InvoiceNo"] for row in rows}),
        "customer_count": len({row["CustomerID"] for row in rows}),
        "product_count": len({row["StockCode"] for row in rows}),
        "country_count": len(country_counts),
        "date_min": min(dates).isoformat(sep=" "),
        "date_max": max(dates).isoformat(sep=" "),
        "total_quantity": sum(row["Quantity"] for row in rows),
        "total_amount": round(sum(row["Quantity"] * row["UnitPrice"] for row in rows), 2),
        "country_counts": dict(sorted(country_counts.items())),
        "monthly_counts": dict(sorted(monthly_counts.items())),
        "sample_customer_ids": list(sample_ids.values()),
        "sample_products": sample_products[:8],
    }


def _artifact_runtime() -> tuple[Path, Path]:
    runtime = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies"
    node = Path(os.environ.get("CODEX_NODE", runtime / "node" / "bin" / "node.exe"))
    modules = Path(os.environ.get("CODEX_NODE_MODULES", runtime / "node" / "node_modules"))
    if not node.is_file() or not modules.is_dir():
        raise RuntimeError("Codex bundled Node/artifact-tool runtime was not found")
    return node, modules


def _write_xlsx(rows: list[dict], output_path: Path) -> None:
    node, modules = _artifact_runtime()
    helper = Path(__file__).with_name("generate_merchant_test_data_xlsx.mjs")
    if not helper.is_file():
        raise RuntimeError(f"Missing workbook helper: {helper}")
    link = helper.parent / "node_modules"
    created_link = False
    if not link.exists():
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(modules)], check=True, capture_output=True)
        else:
            link.symlink_to(modules, target_is_directory=True)
        created_link = True
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as temp:
            json.dump(rows, temp, ensure_ascii=False)
            temp_path = Path(temp.name)
        subprocess.run([str(node), str(helper), str(temp_path), str(output_path)], check=True)
        output_path.with_name(output_path.stem + "_preview.png").unlink(missing_ok=True)
        output_path.with_suffix(output_path.suffix + ".inspect.ndjson").unlink(missing_ok=True)
    finally:
        if 'temp_path' in locals():
            temp_path.unlink(missing_ok=True)
        if created_link:
            link.rmdir()


def _write_readme(path: Path, stats: dict, sample_ids: dict[str, str]) -> None:
    products = "\n".join(f"- `{item}`" for item in stats["sample_products"])
    customers = "\n".join(f"- `{customer_id}`：{behavior}" for behavior, customer_id in sample_ids.items())
    text = f"""# Merchant Transactions Demo

## 模拟商家背景

该数据模拟一家经营家居用品、生活用品与小型电子产品的综合零售商。数据由固定随机种子 `{SEED}` 和明确的客户行为规则独立生成，未读取、复制、抽样或修改项目中的 stage3/UCI 数据。

## 文件与字段

- `merchant_transactions_demo.xlsx`：主要测试文件，仅含 `Transactions` 工作表。
- `merchant_transactions_demo.csv`：与 XLSX 相同的明细，UTF-8 编码。
- 字段：`InvoiceNo`、`StockCode`、`Description`、`Quantity`、`InvoiceDate`、`UnitPrice`、`CustomerID`、`Country`。
- `CustomerID` 为匿名合成标识；不含姓名、电话、地址或其他真实个人信息。

## 原始数据统计

- 时间范围：{stats['date_min']} 至 {stats['date_max']}
- 客户数：{stats['customer_count']:,}
- 订单数：{stats['invoice_count']:,}
- 交易明细行数：{stats['row_count']:,}
- 商品数：{stats['product_count']:,}
- 国家数：{stats['country_count']:,}
- 总销量：{stats['total_quantity']:,}
- 总金额：{stats['total_amount']:,.2f}

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

{products}

## 推荐查询 CustomerID

{customers}

> 本文件为合成测试数据，不含真实个人信息，也不代表真实商家经营结果。
"""
    path.write_text(text, encoding="utf-8")


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    output_dir = project_root / "manual_test_data"
    output_dir.mkdir(parents=True, exist_ok=True)
    rows, sample_ids = generate_rows()
    stats = _stats(rows, sample_ids)

    csv_path = output_dir / "merchant_transactions_demo.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    expected_path = output_dir / "merchant_transactions_demo_expected.json"
    expected_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_readme(output_dir / "merchant_transactions_demo_README.md", stats, sample_ids)
    _write_xlsx(rows, output_dir / "merchant_transactions_demo.xlsx")

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
