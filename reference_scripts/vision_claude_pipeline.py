"""
Claude Vision Pipeline - Generates batches for Claude Code processing
Creates image batches and stores results for KB building
"""

import json
from pathlib import Path
from datetime import datetime

EXTRACTED_DIR = Path(r"D:\Term 3 QA\Teacher Resources - Term 2\Extracted Media")
OUTPUT_DIR = EXTRACTED_DIR / "claude_descriptions"
METADATA_DIR = EXTRACTED_DIR / "metadata"

BATCH_SIZE = 10  # Images per batch for Claude Code processing

def setup():
    """Create output directories"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "batches").mkdir(exist_ok=True)
    (OUTPUT_DIR / "results").mkdir(exist_ok=True)

def load_metadata():
    """Load extraction metadata"""
    metadata_path = METADATA_DIR / "extraction_metadata.json"
    with open(metadata_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_batches(metadata):
    """Generate batch files for Claude Code processing"""

    all_images = []

    # Collect PPTX images
    for pptx_info in metadata.get("pptx_files", []):
        relative_path = pptx_info["relative_path"]
        slides = pptx_info.get("slides", [])

        for img_info in pptx_info.get("images", []):
            all_images.append({
                "type": "pptx_image",
                "image_path": img_info["image_path"],
                "source": relative_path,
                "index": img_info["index"],
                "context": f"From {relative_path}"
            })

    # Collect video keyframes
    for video_info in metadata.get("video_files", []):
        relative_path = video_info["relative_path"]

        for kf_info in video_info.get("keyframes", []):
            all_images.append({
                "type": "video_keyframe",
                "image_path": kf_info["keyframe_path"],
                "source": relative_path,
                "timestamp": kf_info.get("timestamp_formatted", "0:00"),
                "context": f"Video keyframe from {relative_path} at {kf_info.get('timestamp_formatted', '0:00')}"
            })

    # Create batches
    batches = []
    for i in range(0, len(all_images), BATCH_SIZE):
        batch = all_images[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        batches.append({
            "batch_number": batch_num,
            "images": batch,
            "count": len(batch)
        })

    return batches

def save_batches(batches):
    """Save batch files"""
    batch_index = {
        "total_batches": len(batches),
        "total_images": sum(b["count"] for b in batches),
        "batch_size": BATCH_SIZE,
        "batches": []
    }

    for batch in batches:
        batch_path = OUTPUT_DIR / "batches" / f"batch_{batch['batch_number']:03d}.json"
        with open(batch_path, 'w', encoding='utf-8') as f:
            json.dump(batch, f, indent=2, ensure_ascii=False)

        batch_index["batches"].append({
            "batch_number": batch["batch_number"],
            "file": str(batch_path),
            "count": batch["count"],
            "status": "pending"
        })

    index_path = OUTPUT_DIR / "batch_index.json"
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(batch_index, f, indent=2, ensure_ascii=False)

    return batch_index

def save_batch_result(batch_number: int, results: list):
    """Save results for a processed batch"""
    result_path = OUTPUT_DIR / "results" / f"result_{batch_number:03d}.json"
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump({
            "batch_number": batch_number,
            "processed_at": datetime.now().isoformat(),
            "results": results
        }, f, indent=2, ensure_ascii=False)

    # Update batch index status
    index_path = OUTPUT_DIR / "batch_index.json"
    with open(index_path, 'r', encoding='utf-8') as f:
        index = json.load(f)

    for batch in index["batches"]:
        if batch["batch_number"] == batch_number:
            batch["status"] = "completed"
            batch["result_file"] = str(result_path)
            break

    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

def compile_results():
    """Compile all batch results into final KB data"""
    results_dir = OUTPUT_DIR / "results"

    all_results = {
        "pptx_descriptions": {},
        "video_descriptions": {},
        "model": "claude-claude-code"
    }

    for result_file in sorted(results_dir.glob("result_*.json")):
        with open(result_file, 'r', encoding='utf-8') as f:
            batch_result = json.load(f)

        for item in batch_result.get("results", []):
            source = item.get("source", "unknown")

            if item.get("type") == "pptx_image":
                if source not in all_results["pptx_descriptions"]:
                    all_results["pptx_descriptions"][source] = []
                all_results["pptx_descriptions"][source].append(item)
            else:
                if source not in all_results["video_descriptions"]:
                    all_results["video_descriptions"][source] = []
                all_results["video_descriptions"][source].append(item)

    # Save compiled results
    output_path = OUTPUT_DIR / "claude_kb_data.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    return output_path

def main():
    print("=" * 60)
    print("CLAUDE VISION PIPELINE - BATCH GENERATOR")
    print("=" * 60)

    setup()
    metadata = load_metadata()

    print(f"\nMetadata loaded:")
    print(f"  PPTX images: {metadata.get('total_images_extracted', 0)}")
    print(f"  Video keyframes: {metadata.get('total_keyframes_extracted', 0)}")

    batches = generate_batches(metadata)
    batch_index = save_batches(batches)

    print(f"\nBatches created:")
    print(f"  Total batches: {batch_index['total_batches']}")
    print(f"  Total images: {batch_index['total_images']}")
    print(f"  Batch size: {BATCH_SIZE}")
    print(f"\nBatch files saved to: {OUTPUT_DIR / 'batches'}")

    print("\n" + "-" * 60)
    print("NEXT STEPS:")
    print("-" * 60)
    print("1. In Claude Code, read batch files one at a time")
    print("2. For each batch, read the images and generate descriptions")
    print("3. Save results using save_batch_result(batch_num, results)")
    print("4. Run compile_results() to create final KB data")

if __name__ == "__main__":
    main()
