#!/usr/bin/env python3
"""从 MongoDB 读取成分股报价并导出到 data 目录。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from pymongo import MongoClient


CODE_PATTERN = re.compile(r"\b(?:SH|SZ)\d{6}\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "读取 data/stock_profile.csv 中每个指数的成分股代码，并从 MongoDB 导出 Quote 数据到 data/ 目录。"
        )
    )
    parser.add_argument("--profile-csv", default="data/stock_profile.csv", help="指数成分描述文件")
    parser.add_argument("--output-dir", default="data", help="导出目录")
    parser.add_argument("--mongo-uri", default="", help="MongoDB URI，设置后优先生效")
    parser.add_argument("--host", default="localhost", help="MongoDB host")
    parser.add_argument("--port", type=int, default=27017, help="MongoDB port")
    parser.add_argument("--db-name", default="quote", help="MongoDB 数据库名")
    parser.add_argument("--username", default="", help="MongoDB 用户名")
    parser.add_argument("--password", default="", help="MongoDB 密码")
    parser.add_argument(
        "--quote-collection",
        default="Quote",
        help="单集合模式下的集合名（若库中存在与股票代码同名集合，会优先使用同名集合）",
    )
    return parser.parse_args()


def normalize_code(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return raw
    prefix = raw[:2].lower()
    digits = raw[2:]
    return f"{prefix}{digits}"


def extract_components(profile_csv: Path) -> tuple[dict[str, list[str]], list[str]]:
    index_components: dict[str, list[str]] = {}
    all_codes: set[str] = set()

    with profile_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = (row.get("stock_id") or "").strip()
            desc = row.get("description") or ""
            matches = [normalize_code(m.group(0)) for m in CODE_PATTERN.finditer(desc)]
            unique = sorted(set(matches))
            index_components[idx] = unique
            all_codes.update(unique)

    return index_components, sorted(all_codes)


def build_client(args: argparse.Namespace) -> MongoClient:
    if args.mongo_uri:
        return MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    if args.username and args.password:
        uri = f"mongodb://{args.username}:{args.password}@{args.host}:{args.port}/"
        return MongoClient(uri, serverSelectionTimeoutMS=5000)
    return MongoClient(args.host, args.port, serverSelectionTimeoutMS=5000)


def fetch_docs_from_collection(db: Any, collection_name: str) -> list[dict[str, Any]]:
    docs = list(
        db[collection_name]
        .find(
            {},
            {
                "_id": 0,
                "date": 1,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
                "amount": 1,
                "outstanding_share": 1,
                "turnover": 1,
            },
        )
        .sort("date", 1)
    )
    return docs


def fetch_docs_from_quote_collection(db: Any, collection_name: str, code: str) -> list[dict[str, Any]]:
    coll = db[collection_name]
    candidates = [code, code.upper(), code.lower(), code[2:], code[2:].upper()]
    symbol_fields = ["symbol", "ts_code", "stock_id", "code"]

    for field in symbol_fields:
        for value in candidates:
            docs = list(
                coll.find(
                    {field: value},
                    {
                        "_id": 0,
                        "date": 1,
                        "open": 1,
                        "high": 1,
                        "low": 1,
                        "close": 1,
                        "volume": 1,
                        "amount": 1,
                        "outstanding_share": 1,
                        "turnover": 1,
                        "symbol": 1,
                        "ts_code": 1,
                        "stock_id": 1,
                        "code": 1,
                    },
                ).sort("date", 1)
            )
            if docs:
                return docs
    return []


def main() -> int:
    args = parse_args()
    profile_csv = Path(args.profile_csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not profile_csv.exists():
        raise FileNotFoundError(f"profile csv not found: {profile_csv}")

    index_components, all_codes = extract_components(profile_csv)
    print(f"[info] indices={len(index_components)} component_stocks={len(all_codes)}")

    client = build_client(args)
    db = client[args.db_name]

    try:
        collection_names = set(db.list_collection_names())
    except Exception as e:
        print(f"[error] 无法连接 MongoDB 或读取集合列表: {e}")
        return 2

    by_stock: dict[str, list[dict[str, Any]]] = {}
    source_map: dict[str, str] = {}
    missing: list[str] = []

    for code in all_codes:
        # 优先：每个股票代码对应一个集合
        candidate_collections = [code, code.upper(), code.lower()]
        selected_collection = ""
        docs: list[dict[str, Any]] = []

        for cname in candidate_collections:
            if cname in collection_names:
                selected_collection = cname
                docs = fetch_docs_from_collection(db, cname)
                if docs:
                    break

        # 回退：单个 Quote 集合里按 symbol/ts_code/code 过滤
        if not docs and args.quote_collection in collection_names:
            selected_collection = args.quote_collection
            docs = fetch_docs_from_quote_collection(db, args.quote_collection, code)

        if not docs:
            missing.append(code)
            continue

        by_stock[code] = docs
        source_map[code] = selected_collection

    # 导出 1：逐股票 JSON
    by_stock_dir = output_dir / "mongodb_quotes_by_stock"
    by_stock_dir.mkdir(parents=True, exist_ok=True)
    for code, docs in by_stock.items():
        (by_stock_dir / f"{code}.json").write_text(
            json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 导出 2：汇总 CSV
    csv_path = output_dir / "mongodb_quotes_export.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "stock_code",
                "source_collection",
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "outstanding_share",
                "turnover",
            ],
        )
        writer.writeheader()
        for code in sorted(by_stock.keys()):
            for d in by_stock[code]:
                writer.writerow(
                    {
                        "stock_code": code,
                        "source_collection": source_map.get(code, ""),
                        "date": d.get("date", ""),
                        "open": d.get("open", ""),
                        "high": d.get("high", ""),
                        "low": d.get("low", ""),
                        "close": d.get("close", ""),
                        "volume": d.get("volume", ""),
                        "amount": d.get("amount", ""),
                        "outstanding_share": d.get("outstanding_share", ""),
                        "turnover": d.get("turnover", ""),
                    }
                )

    # 导出 3：元信息
    meta = {
        "profile_csv": str(profile_csv),
        "db_name": args.db_name,
        "quote_collection": args.quote_collection,
        "index_components": index_components,
        "component_stock_count": len(all_codes),
        "exported_stock_count": len(by_stock),
        "missing_stocks": missing,
        "source_map": source_map,
        "output_csv": str(csv_path),
        "output_json_dir": str(by_stock_dir),
    }
    meta_path = output_dir / "mongodb_quotes_export_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] exported_stocks={len(by_stock)} missing={len(missing)}")
    print(f"[done] csv={csv_path}")
    print(f"[done] json_dir={by_stock_dir}")
    print(f"[done] meta={meta_path}")
    if missing:
        print("[warn] missing codes:", ",".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
