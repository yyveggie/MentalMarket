import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

DEFAULT_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"


def resolve_device(device_arg: str) -> int | str:
    """Resolve runtime device for transformers pipeline.

    Returns:
        -1 for CPU, integer CUDA index for NVIDIA GPU, or "mps" for Apple GPU.
    """
    value = device_arg.strip().lower()

    try:
        import torch
    except Exception:
        # If torch is unavailable, fall back to CPU.
        return -1

    if value == "auto":
        if torch.cuda.is_available():
            return 0
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return -1

    if value == "cpu":
        return -1

    if value == "mps":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        raise ValueError("MPS is not available on this machine")

    if value == "cuda":
        if torch.cuda.is_available():
            return 0
        raise ValueError("CUDA is not available on this machine")

    if value.startswith("cuda:"):
        if not torch.cuda.is_available():
            raise ValueError("CUDA is not available on this machine")
        index_str = value.split(":", 1)[1]
        if not index_str.isdigit():
            raise ValueError("Invalid CUDA device format, expected cuda:<index>")
        device_index = int(index_str)
        if device_index >= torch.cuda.device_count():
            raise ValueError(f"CUDA device index out of range: {device_index}")
        return device_index

    raise ValueError("Unsupported --device value, use auto/cpu/cuda/cuda:<index>/mps")


def label_to_class(label: str) -> str:
    """Normalize model label into one of: positive, neutral, negative."""
    normalized = label.strip().lower()
    if any(key in normalized for key in ["positive", "pos", "label_2"]):
        return "positive"
    if any(key in normalized for key in ["negative", "neg", "label_0"]):
        return "negative"
    if any(key in normalized for key in ["neutral", "neu", "label_1"]):
        return "neutral"
    return "neutral"


def score_from_probabilities(probabilities: list[dict[str, Any]]) -> tuple[float, str]:
    """Map sentiment probabilities to score and top label.

    Score rule: p(positive) - p(negative), in [-1, 1].
    """
    prob_map = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}

    for item in probabilities:
        mapped_class = label_to_class(str(item["label"]))
        prob_map[mapped_class] += float(item["score"])

    sentiment_score = prob_map["positive"] - prob_map["negative"]
    top_label = max(prob_map, key=lambda label: prob_map[label])
    return sentiment_score, top_label


def normalize_comment_content(value: Any) -> str:
    """Convert various comment_content forms into plain text for model inference."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def batched(iterable: list[str], size: int) -> list[list[str]]:
    return [iterable[i:i + size] for i in range(0, len(iterable), size)]


def calculate_collection_sentiment(
    input_data: dict[str, Any],
    model_name: str,
    cache_dir: str,
    device_arg: str,
    batch_size: int,
    max_length: int,
    include_details: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Compute total sentiment for each sub-collection using an NLP model."""
    resolved_device = resolve_device(device_arg)
    tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir or None)
    model = AutoModelForSequenceClassification.from_pretrained(model_name, cache_dir=cache_dir or None)
    classifier = pipeline(
        task="text-classification",
        model=model,
        tokenizer=tokenizer,
        device=resolved_device,
    )

    summary_output: dict[str, Any] = {}
    detail_output: dict[str, Any] | None = {} if include_details else None

    for sub_collection, comments in input_data.items():
        if not isinstance(comments, list):
            summary_output[sub_collection] = {
                "total_sentiment": 0,
                "comment_count": 0,
                "avg_sentiment": 0.0,
                "note": "invalid format: expected a list",
            }
            if include_details and detail_output is not None:
                detail_output[sub_collection] = []
            continue

        clean_texts: list[str] = []
        for item in comments:
            text = normalize_comment_content(item).strip()
            if text:
                clean_texts.append(text)

        total = 0.0
        count = 0
        detail_rows: list[dict[str, Any]] = []

        for text_batch in batched(clean_texts, batch_size):
            # return_all_scores gives probability distribution for better numeric aggregation.
            batch_results_raw = classifier(
                text_batch,
                return_all_scores=True,
                truncation=True,
                max_length=max_length,
            )
            batch_results = list(batch_results_raw) if isinstance(batch_results_raw, Iterable) else []

            for text, probabilities_raw in zip(text_batch, batch_results):
                if not isinstance(probabilities_raw, list):
                    continue

                probabilities: list[dict[str, Any]] = []
                for item in probabilities_raw:
                    if not isinstance(item, dict):
                        continue
                    label = item.get("label")
                    score_value = item.get("score")
                    if label is None or score_value is None:
                        continue
                    probabilities.append({"label": str(label), "score": float(score_value)})

                if not probabilities:
                    continue

                score, top_label = score_from_probabilities(probabilities)
                total += score
                count += 1
                if include_details:
                    detail_rows.append(
                        {
                            "comment_content": text,
                            "sentiment_score": round(score, 6),
                            "label": top_label,
                        }
                    )

        avg = (total / count) if count else 0.0
        summary_output[sub_collection] = {
            "total_sentiment": round(total, 6),
            "comment_count": count,
            "avg_sentiment": round(avg, 6),
            "model": model_name,
            "device": str(resolved_device),
        }

        if include_details and detail_output is not None:
            detail_output[sub_collection] = detail_rows

    return summary_output, detail_output


def parse_index_constituents(profile_csv: str) -> dict[str, dict]:
    """Parse stock_profile.csv to extract index → {stock_code: weight} mapping.

    The description field contains entries like:
        "包括中远海控(SH601919, 权重52.34%)、中国船舶(SH600150, 权重47.66%)"
    """
    pattern = re.compile(r"SH(\d+),\s*权重([\d.]+)%")
    indices: dict[str, dict] = {}

    with open(profile_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            index_id = (row.get("stock_id") or "").strip()
            index_name = (row.get("name") or index_id).strip()
            description = row.get("description") or ""
            stocks: dict[str, float] = {}
            for m in pattern.finditer(description):
                stock_code = m.group(1)
                weight_pct = float(m.group(2))
                stocks[stock_code] = weight_pct / 100.0
            indices[index_id] = {
                "name": index_name,
                "industry": (row.get("industry") or "").strip(),
                "stocks": stocks,
            }
    return indices


def aggregate_index_sentiment(
    stock_sentiments: dict[str, Any],
    index_map: dict[str, dict],
) -> dict[str, Any]:
    """Aggregate per-stock avg_sentiment into per-index weighted sentiment.

    Stocks without comment data have their weights redistributed
    proportionally to stocks that do have data within the same index.
    """
    result: dict[str, Any] = {}

    for index_id, info in index_map.items():
        constituents = info["stocks"]
        if not constituents:
            result[index_id] = {
                "index_name": info["name"],
                "industry": info["industry"],
                "index_sentiment": 0.0,
                "stocks_with_data": 0,
                "stocks_total": 0,
                "detail": {},
            }
            continue

        available: dict[str, float] = {}
        missing_weight = 0.0
        for code, w in constituents.items():
            if code in stock_sentiments:
                available[code] = w
            else:
                missing_weight += w

        if not available:
            result[index_id] = {
                "index_name": info["name"],
                "industry": info["industry"],
                "index_sentiment": 0.0,
                "stocks_with_data": 0,
                "stocks_total": len(constituents),
                "detail": {},
                "note": "no stock sentiment data available",
            }
            continue

        total_available_weight = sum(available.values())
        if total_available_weight <= 0:
            total_available_weight = 1.0

        weighted_sum = 0.0
        detail: dict[str, Any] = {}
        for code, original_w in available.items():
            adjusted_w = original_w / total_available_weight
            avg_sent = float(stock_sentiments[code].get("avg_sentiment", 0.0))
            weighted_sum += adjusted_w * avg_sent
            detail[code] = {
                "avg_sentiment": avg_sent,
                "comment_count": stock_sentiments[code].get("comment_count", 0),
                "original_weight": round(original_w, 6),
                "adjusted_weight": round(adjusted_w, 6),
            }

        result[index_id] = {
            "index_name": info["name"],
            "industry": info["industry"],
            "index_sentiment": round(weighted_sum, 6),
            "stocks_with_data": len(available),
            "stocks_total": len(constituents),
            "weight_redistributed": round(missing_weight, 6),
            "detail": detail,
        }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read local JSON file exported from comment_info and compute total sentiment "
            "for each sub-collection."
        )
    )
    parser.add_argument(
        "--input",
        default="comment_info_comment_content.json",
        help="Input JSON path generated by export script",
    )
    parser.add_argument(
        "--output",
        default="comment_info_sentiment_summary.json",
        help="Output JSON path for sentiment summary",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Hugging Face model name for sentiment classification",
    )
    parser.add_argument(
        "--cache-dir",
        default="",
        help="Optional local cache directory for model/tokenizer files",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Device selection: auto/cpu/cuda/cuda:<index>/mps",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Inference batch size",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=256,
        help="Max token length per comment (longer text will be truncated)",
    )
    parser.add_argument(
        "--detail-output",
        default="",
        help="Optional output path for per-comment sentiment details",
    )
    parser.add_argument(
        "--profile",
        default="",
        help="Path to stock_profile.csv for index aggregation",
    )
    parser.add_argument(
        "--index-output",
        default="",
        help="Output path for index-level sentiment (requires --profile)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    input_data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(input_data, dict):
        raise ValueError("Input JSON root must be an object: {sub_collection: [comment_content, ...]}")

    summary, detail = calculate_collection_sentiment(
        input_data=input_data,
        model_name=args.model,
        cache_dir=args.cache_dir,
        device_arg=args.device,
        batch_size=args.batch_size,
        max_length=args.max_length,
        include_details=bool(args.detail_output),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.detail_output and detail is not None:
        detail_path = Path(args.detail_output)
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        detail_path.write_text(
            json.dumps(detail, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Detail output written to: {detail_path.resolve()}")

    print(f"Done. Sentiment summary written to: {output_path.resolve()}")

    if args.profile and args.index_output:
        profile_path = Path(args.profile)
        if not profile_path.exists():
            raise FileNotFoundError(f"Profile CSV not found: {profile_path}")
        index_map = parse_index_constituents(str(profile_path))
        index_sentiment = aggregate_index_sentiment(summary, index_map)
        index_out_path = Path(args.index_output)
        index_out_path.parent.mkdir(parents=True, exist_ok=True)
        index_out_path.write_text(
            json.dumps(index_sentiment, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Index sentiment written to: {index_out_path.resolve()}")


if __name__ == "__main__":
    main()
