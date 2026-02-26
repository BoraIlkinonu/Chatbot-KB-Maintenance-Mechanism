"""
Stage 3: Native Google Format Extraction
Uses Google Slides, Docs, and Sheets APIs to extract structured content
from native Google files (not uploaded Office files).
"""

import sys
import json
import hashlib
import requests
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8")

from config import NATIVE_DIR, LOGS_DIR, SOURCES_DIR, MEDIA_DIR
from auth import authenticate, get_slides_service, get_docs_service, get_sheets_service

IMAGE_EXTS_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


# ──────────────────────────────────────────────────────────
# Google Slides extraction
# ──────────────────────────────────────────────────────────

def extract_slides(service, file_id, file_name):
    """Extract structured content from a Google Slides presentation."""
    try:
        pres = service.presentations().get(presentationId=file_id).execute()
    except Exception as e:
        return {"error": str(e), "file_id": file_id, "file_name": file_name}

    slides_data = []
    for i, slide in enumerate(pres.get("slides", []), 1):
        slide_content = {
            "slide_number": i,
            "object_id": slide.get("objectId", ""),
            "texts": [],
            "tables": [],
            "image_urls": [],
            "links": [],
            "videos": [],
            "speaker_notes": "",
        }

        for element in slide.get("pageElements", []):
            # Images
            image = element.get("image", {})
            content_url = image.get("contentUrl")
            if content_url:
                slide_content["image_urls"].append({
                    "url": content_url,
                    "source_url": image.get("sourceUrl", ""),
                    "object_id": element.get("objectId", ""),
                })

            # Embedded videos (Drive video embeds)
            video = element.get("video", {})
            if video:
                video_info = {
                    "url": video.get("url", ""),
                    "source": video.get("source", ""),
                    "video_id": video.get("id", ""),
                    "object_id": element.get("objectId", ""),
                    "slide_number": i,
                }
                slide_content["videos"].append(video_info)

            # Text boxes — extract text AND links
            shape = element.get("shape", {})
            if shape.get("text"):
                texts = []
                for text_element in shape["text"].get("textElements", []):
                    run = text_element.get("textRun", {})
                    content_text = run.get("content", "").strip()
                    if content_text:
                        texts.append(content_text)
                    # Extract hyperlinks from text runs
                    link = run.get("style", {}).get("link", {})
                    link_url = link.get("url", "")
                    if link_url:
                        slide_content["links"].append({
                            "url": link_url,
                            "text": content_text,
                            "slide_number": i,
                        })
                if texts:
                    slide_content["texts"].append(" ".join(texts))

            # Tables — also extract links from table cell text
            table = element.get("table", {})
            if table:
                rows_data = []
                for row in table.get("tableRows", []):
                    row_cells = []
                    for cell in row.get("tableCells", []):
                        cell_text = ""
                        if cell.get("text"):
                            for te in cell["text"].get("textElements", []):
                                run = te.get("textRun", {})
                                cell_text += run.get("content", "")
                                # Links in table cells
                                link = run.get("style", {}).get("link", {})
                                link_url = link.get("url", "")
                                if link_url:
                                    slide_content["links"].append({
                                        "url": link_url,
                                        "text": run.get("content", "").strip(),
                                        "slide_number": i,
                                    })
                        row_cells.append(cell_text.strip())
                    rows_data.append(row_cells)

                if rows_data:
                    slide_content["tables"].append({
                        "headers": rows_data[0] if rows_data else [],
                        "rows": rows_data[1:] if len(rows_data) > 1 else [],
                    })

        # Speaker notes — also extract links
        notes_page = slide.get("slideProperties", {}).get("notesPage", {})
        for element in notes_page.get("pageElements", []):
            shape = element.get("shape", {})
            if shape.get("shapeType") == "TEXT_BOX" and shape.get("text"):
                notes_texts = []
                for te in shape["text"].get("textElements", []):
                    run = te.get("textRun", {})
                    content_text = run.get("content", "").strip()
                    if content_text:
                        notes_texts.append(content_text)
                    link = run.get("style", {}).get("link", {})
                    link_url = link.get("url", "")
                    if link_url:
                        slide_content["links"].append({
                            "url": link_url,
                            "text": content_text,
                            "slide_number": i,
                        })
                if notes_texts:
                    slide_content["speaker_notes"] = " ".join(notes_texts)

        slides_data.append(slide_content)

    total_images = sum(len(s.get("image_urls", [])) for s in slides_data)
    total_links = sum(len(s.get("links", [])) for s in slides_data)
    total_videos = sum(len(s.get("videos", [])) for s in slides_data)

    return {
        "file_id": file_id,
        "file_name": file_name,
        "title": pres.get("title", ""),
        "total_slides": len(slides_data),
        "total_images": total_images,
        "total_links": total_links,
        "total_videos": total_videos,
        "slides": slides_data,
    }


# ──────────────────────────────────────────────────────────
# Google Docs extraction
# ──────────────────────────────────────────────────────────

def extract_doc(service, file_id, file_name):
    """Extract structured content from a Google Doc."""
    try:
        doc = service.documents().get(documentId=file_id).execute()
    except Exception as e:
        return {"error": str(e), "file_id": file_id, "file_name": file_name}

    content_blocks = []
    all_links = []

    for element in doc.get("body", {}).get("content", []):
        para = element.get("paragraph", {})
        if para:
            style = para.get("paragraphStyle", {}).get("namedStyleType", "")
            texts = []
            for pe in para.get("elements", []):
                run = pe.get("textRun", {})
                content_text = run.get("content", "").strip()
                if content_text:
                    texts.append(content_text)
                # Extract hyperlinks
                link = run.get("textStyle", {}).get("link", {})
                link_url = link.get("url", "")
                if link_url:
                    all_links.append({
                        "url": link_url,
                        "text": content_text,
                    })

            if texts:
                content_blocks.append({
                    "type": "paragraph",
                    "style": style,
                    "text": " ".join(texts),
                })

        table = element.get("table", {})
        if table:
            rows_data = []
            for row in table.get("tableRows", []):
                row_cells = []
                for cell in row.get("tableCells", []):
                    cell_text = ""
                    for cell_content in cell.get("content", []):
                        cell_para = cell_content.get("paragraph", {})
                        for pe in cell_para.get("elements", []):
                            run = pe.get("textRun", {})
                            cell_text += run.get("content", "")
                            # Links in table cells
                            link = run.get("textStyle", {}).get("link", {})
                            link_url = link.get("url", "")
                            if link_url:
                                all_links.append({
                                    "url": link_url,
                                    "text": run.get("content", "").strip(),
                                })
                    row_cells.append(cell_text.strip())
                rows_data.append(row_cells)

            if rows_data:
                content_blocks.append({
                    "type": "table",
                    "headers": rows_data[0] if rows_data else [],
                    "rows": rows_data[1:] if len(rows_data) > 1 else [],
                })

    return {
        "file_id": file_id,
        "file_name": file_name,
        "title": doc.get("title", ""),
        "content_blocks": content_blocks,
        "links": all_links,
        "total_links": len(all_links),
    }


# ──────────────────────────────────────────────────────────
# Google Sheets extraction
# ──────────────────────────────────────────────────────────

def extract_sheet(service, file_id, file_name):
    """Extract structured data from a Google Sheet."""
    try:
        spreadsheet = service.spreadsheets().get(
            spreadsheetId=file_id, includeGridData=True
        ).execute()
    except Exception as e:
        return {"error": str(e), "file_id": file_id, "file_name": file_name}

    sheets_data = []
    for sheet in spreadsheet.get("sheets", []):
        props = sheet.get("properties", {})
        sheet_title = props.get("title", "")

        rows_data = []
        for grid_data in sheet.get("data", []):
            for row in grid_data.get("rowData", []):
                cells = []
                for cell in row.get("values", []):
                    formatted = cell.get("formattedValue", "")
                    cells.append(formatted)
                if any(c for c in cells):
                    rows_data.append(cells)

        sheets_data.append({
            "sheet_name": sheet_title,
            "headers": rows_data[0] if rows_data else [],
            "rows": rows_data[1:] if len(rows_data) > 1 else [],
            "total_rows": len(rows_data),
        })

    return {
        "file_id": file_id,
        "file_name": file_name,
        "title": spreadsheet.get("properties", {}).get("title", ""),
        "sheets": sheets_data,
    }


# ──────────────────────────────────────────────────────────
# Slide image downloading
# ──────────────────────────────────────────────────────────

def download_slide_images(slides_data, file_name, output_base):
    """Download images from Slides API contentUrls.
    contentUrls are signed URLs valid for ~30 minutes — no auth needed.

    Returns list of image metadata dicts.
    """
    safe_name = file_name.replace(" ", "_").replace("/", "_")
    output_folder = output_base / safe_name
    output_folder.mkdir(parents=True, exist_ok=True)

    downloaded = []
    seen_urls = set()
    index = 0

    for slide in slides_data:
        slide_num = slide["slide_number"]
        for img_info in slide.get("image_urls", []):
            url = img_info["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            index += 1
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code != 200:
                    print(f"    Image {index}: HTTP {resp.status_code}, skipping")
                    continue

                # Determine extension from Content-Type or URL
                content_type = resp.headers.get("Content-Type", "")
                ext = IMAGE_EXTS_BY_MIME.get(content_type.split(";")[0].strip(), "")
                if not ext:
                    url_path = urlparse(url).path
                    ext = Path(url_path).suffix.lower() if Path(url_path).suffix else ".png"

                output_name = f"image_{index:03d}{ext}"
                output_path = output_folder / output_name

                with open(output_path, "wb") as f:
                    f.write(resp.content)

                md5 = hashlib.md5(resp.content).hexdigest()

                downloaded.append({
                    "image_path": str(output_path),
                    "index": index,
                    "slide_numbers": [slide_num],
                    "primary_slide": slide_num,
                    "size_bytes": len(resp.content),
                    "extension": ext,
                    "md5": md5,
                    "source": "native_slides_api",
                    "object_id": img_info.get("object_id", ""),
                })

            except Exception as e:
                print(f"    Image {index}: download error: {e}")

    return downloaded


def diff_images(current_metadata, previous_metadata_path):
    """Compare current image extraction against previous run.
    Uses object_id (stable element ID from Slides API) + md5 to detect:
      - ADDED: new object_id not in previous
      - REMOVED: old object_id not in current
      - CHANGED: same object_id, different md5
      - UNCHANGED: same object_id, same md5

    Returns dict keyed by presentation source_name.
    """
    # Load previous
    previous = {}
    if previous_metadata_path.exists():
        with open(previous_metadata_path, "r", encoding="utf-8") as f:
            prev_data = json.load(f)
        for pres in prev_data.get("presentations", []):
            pres_key = pres.get("file_id", pres.get("source_name", ""))
            prev_images = {}
            for img in pres.get("images", []):
                oid = img.get("object_id", "")
                if oid:
                    prev_images[oid] = img
            previous[pres_key] = prev_images

    diff_results = {}

    for pres in current_metadata.get("presentations", []):
        pres_key = pres.get("file_id", pres.get("source_name", ""))
        pres_name = pres.get("source_name", "")
        prev_images = previous.get(pres_key, {})

        current_oids = {}
        for img in pres.get("images", []):
            oid = img.get("object_id", "")
            if oid:
                current_oids[oid] = img

        added = []
        changed = []
        unchanged = []
        removed = []

        for oid, img in current_oids.items():
            if oid not in prev_images:
                added.append({"object_id": oid, "slide": img.get("primary_slide"), "md5": img.get("md5", "")})
            elif img.get("md5", "") != prev_images[oid].get("md5", ""):
                changed.append({
                    "object_id": oid,
                    "slide": img.get("primary_slide"),
                    "old_md5": prev_images[oid].get("md5", ""),
                    "new_md5": img.get("md5", ""),
                })
            else:
                unchanged.append(oid)

        for oid in prev_images:
            if oid not in current_oids:
                prev = prev_images[oid]
                removed.append({"object_id": oid, "slide": prev.get("primary_slide"), "md5": prev.get("md5", "")})

        if added or changed or removed:
            diff_results[pres_name] = {
                "added": added,
                "changed": changed,
                "removed": removed,
                "unchanged_count": len(unchanged),
            }

    return diff_results


# ──────────────────────────────────────────────────────────
# Main extraction
# ──────────────────────────────────────────────────────────

def run_native_extraction(sync_result=None):
    """
    Extract content from native Google files identified during sync.
    If sync_result not provided, reads the latest sync log.
    """
    print("=" * 60)
    print("  Stage 3: Native Google Format Extraction")
    print("=" * 60)
    print()

    NATIVE_DIR.mkdir(parents=True, exist_ok=True)

    # Gather native Google files from sync results
    native_files = []
    if sync_result:
        for term_key, term_data in sync_result.get("terms", {}).items():
            for f in term_data.get("files", []):
                if f.get("is_native_google") and f.get("native_type"):
                    native_files.append({**f, "term": term_key})
    else:
        # Read from latest sync log
        from config import LOGS_DIR
        logs = sorted(LOGS_DIR.glob("sync_*.json"), reverse=True)
        if logs:
            with open(logs[0], "r", encoding="utf-8") as fh:
                sync_data = json.load(fh)
            for term_key, term_data in sync_data.get("terms", {}).items():
                for f in term_data.get("files", []):
                    if f.get("is_native_google") and f.get("native_type"):
                        native_files.append({**f, "term": term_key})

    if not native_files:
        print("No native Google files found to extract.")
        return {"extractions": [], "total": 0}

    print(f"Found {len(native_files)} native Google files\n")

    # Authenticate and build services
    creds = authenticate()
    slides_svc = get_slides_service(creds)
    docs_svc = get_docs_service(creds)
    sheets_svc = get_sheets_service(creds)

    results = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "extractions": [],
        "total": 0,
        "errors": 0,
    }

    # Track image downloads for all presentations
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    native_img_dir = MEDIA_DIR / "native_slides"
    native_img_dir.mkdir(parents=True, exist_ok=True)

    image_metadata = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "presentations": [],
        "total_images": 0,
    }

    for nf in native_files:
        fid = nf["id"]
        name = nf.get("name", "")
        ntype = nf["native_type"]

        print(f"[{ntype}] {name}")

        if ntype == "google_slides":
            data = extract_slides(slides_svc, fid, name)
        elif ntype == "google_doc":
            data = extract_doc(docs_svc, fid, name)
        elif ntype == "google_sheet":
            data = extract_sheet(sheets_svc, fid, name)
        else:
            print(f"  Skipping unknown native type: {ntype}")
            continue

        if "error" in data:
            print(f"  ERROR: {data['error']}")
            results["errors"] += 1
        else:
            results["total"] += 1

        data["term"] = nf.get("term", "")
        data["folder_path"] = nf.get("folder_path", "")
        data["source_path"] = f"{nf.get('term', '')}/{nf.get('folder_path', '')}/{name}"
        data["native_type"] = ntype
        data["drive_id"] = fid
        results["extractions"].append(data)

        # Log link/video counts for Slides and Docs
        if "error" not in data:
            if data.get("total_links", 0) > 0:
                print(f"  Found {data['total_links']} links")
            if data.get("total_videos", 0) > 0:
                print(f"  Found {data['total_videos']} embedded videos")

        # Download images from Google Slides presentations
        if ntype == "google_slides" and "error" not in data:
            total_img = data.get("total_images", 0)
            if total_img > 0:
                print(f"  Downloading {total_img} images...")
                downloaded = download_slide_images(
                    data["slides"], name, native_img_dir
                )
                print(f"  Downloaded {len(downloaded)} images")

                image_metadata["presentations"].append({
                    "source_name": name,
                    "file_id": fid,
                    "term": nf.get("term", ""),
                    "folder_path": nf.get("folder_path", ""),
                    "source_path": data["source_path"],
                    "images_count": len(downloaded),
                    "images": downloaded,
                })
                image_metadata["total_images"] += len(downloaded)

    # Save text extractions
    output_path = NATIVE_DIR / "native_extractions.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Diff images against previous run
    img_meta_path = MEDIA_DIR / "native_image_metadata.json"
    image_diff = diff_images(image_metadata, img_meta_path)

    if image_diff:
        print(f"\n  Image changes detected:")
        for pres_name, diff in image_diff.items():
            parts = []
            if diff["added"]:
                parts.append(f"{len(diff['added'])} added")
            if diff["changed"]:
                parts.append(f"{len(diff['changed'])} changed")
            if diff["removed"]:
                parts.append(f"{len(diff['removed'])} removed")
            print(f"    {pres_name}: {', '.join(parts)} ({diff['unchanged_count']} unchanged)")

        # Save diff log
        diff_log_path = LOGS_DIR / f"image_diff_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(diff_log_path, "w", encoding="utf-8") as f:
            json.dump({"diffed_at": datetime.now(timezone.utc).isoformat(), "diffs": image_diff}, f, indent=2, ensure_ascii=False)
        print(f"    Diff log: {diff_log_path}")
    else:
        print(f"\n  No image changes detected vs. previous run.")

    # Save image metadata (overwrite previous for next diff comparison)
    with open(img_meta_path, "w", encoding="utf-8") as f:
        json.dump(image_metadata, f, indent=2, ensure_ascii=False)

    print(f"\nExtracted: {results['total']} files")
    print(f"Errors: {results['errors']}")
    print(f"Images downloaded: {image_metadata['total_images']}")
    print(f"Saved: {output_path}")
    print(f"Image metadata: {img_meta_path}")
    print("=" * 60)

    return results


if __name__ == "__main__":
    run_native_extraction()
