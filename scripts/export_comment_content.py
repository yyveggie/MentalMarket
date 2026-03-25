import argparse
import json
from pathlib import Path
from typing import Any

from pymongo import MongoClient


def export_comment_content(
    host: str,
    port: int,
    db_name: str,
    output_file: str,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Export comment_content from all collections in a MongoDB database."""
    if username and password:
        uri = f"mongodb://{username}:{password}@{host}:{port}/"
        client = MongoClient(uri)
    else:
        client = MongoClient(host, port)

    try:
        db = client[db_name]
        result: dict[str, list[Any]] = {}

        collection_names = db.list_collection_names()
        for collection_name in collection_names:
            collection = db[collection_name]
            cursor = collection.find(
                {"comment_content": {"$exists": True}},
                {"_id": 0, "comment_content": 1},
            )
            result[collection_name] = [doc.get("comment_content") for doc in cursor]

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"Export completed. {len(result)} collections were written to {output_path.resolve()}"
        )
    finally:
        client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export all 'comment_content' values from every collection in a MongoDB database "
            "to a local JSON file."
        )
    )
    parser.add_argument("--host", default="localhost", help="MongoDB host")
    parser.add_argument("--port", type=int, default=27017, help="MongoDB port")
    parser.add_argument(
        "--db-name",
        default="comment_info",
        help="MongoDB database name (default: comment_info)",
    )
    parser.add_argument(
        "--output",
        default="comment_info_comment_content.json",
        help="Output JSON file path",
    )
    parser.add_argument("--username", default=None, help="MongoDB username")
    parser.add_argument("--password", default=None, help="MongoDB password")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    export_comment_content(
        host=args.host,
        port=args.port,
        db_name=args.db_name,
        output_file=args.output,
        username=args.username,
        password=args.password,
    )
