#!/usr/bin/env python3
"""
Split PDFs that exceed 200 pages, re-expose via portal, submit new tasks.
"""
import fitz
import os
import json
import requests
import time

from auth import CredentialError, mineru_headers, raise_for_auth

API_SUBMIT = "https://mineru.net/api/v4/extract/task"
BASE_URL = "https://laserenadigital.cl"
PDF_DIR = "/root/portal/static/pdfs"
TASKS_FILE = "/tmp/mineru_tasks.json"

def get_page_count(filepath):
    try:
        doc = fitz.open(filepath)
        pages = doc.page_count
        doc.close()
        return pages
    except Exception as exc:
        print(f"  ⚠️ No se pudo leer {os.path.basename(filepath)}: {exc}")
        return 0

def split_pdf(filepath, max_pages=200):
    """Split PDF into parts of max_pages each. Returns list of output paths."""
    doc = fitz.open(filepath)
    total = doc.page_count
    parts = []
    
    for i, start in enumerate(range(0, total, max_pages)):
        end = min(start + max_pages, total) - 1
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=start, to_page=end)
        
        base = os.path.splitext(os.path.basename(filepath))[0]
        out = os.path.join(PDF_DIR, f"{base}_p{start+1}-{end+1}.pdf")
        new_doc.save(out)
        new_doc.close()
        parts.append(out)
        print(f"  Split: {os.path.basename(out)} (pp {start+1}-{end+1})")
    
    doc.close()
    return parts

def main():
    mineru_headers()  # puerta de credenciales antes de dividir y reenviar

    # Load current tasks
    with open(TASKS_FILE) as f:
        tasks = json.load(f)
    
    # Identify failed tasks (page limit exceeded)
    failed = [t for t in tasks if t.get('status') == 'failed']
    print(f"Failed tasks to split: {len(failed)}")
    
    new_tasks = []
    
    for t in failed:
        # Find the PDF file
        for f in os.listdir(PDF_DIR):
            if f.startswith(t['filename'][:30]) and f.endswith('.pdf') and '_p' not in f:
                filepath = os.path.join(PDF_DIR, f)
                pages = get_page_count(filepath)
                print(f"\n{t['filename'][:60]} ({pages} pages)")
                
                if pages > 200:
                    parts = split_pdf(filepath)
                    from urllib.parse import quote
                    
                    for part_path in parts:
                        part_name = os.path.basename(part_path)
                        url = f"{BASE_URL}/static/pdfs/{quote(part_name)}"
                        
                        payload = {
                            "url": url,
                            "language": "en",
                            "model_version": "pipeline",
                            "is_ocr": False,
                            "enable_formula": True,
                            "enable_table": True
                        }
                        
                        try:
                            resp = requests.post(API_SUBMIT, headers=mineru_headers(), json=payload, timeout=60)
                            raise_for_auth(resp)
                            data = resp.json()
                            if data.get('code') == 0:
                                tid = data['data']['task_id']
                                new_tasks.append({"filename": part_name, "task_id": tid, "status": "submitted"})
                                print(f"    → task_id: {tid}")
                            else:
                                print(f"    → ERROR: {data.get('msg')}")
                        except CredentialError:
                            raise
                        except Exception as e:
                            print(f"    → EXCEPTION: {e}")
                        
                        time.sleep(2)  # rate limit
                break
    
    # Update tasks file
    tasks.extend(new_tasks)
    with open(TASKS_FILE, 'w') as f:
        json.dump(tasks, f, indent=2)
    
    print(f"\nNew tasks added: {len(new_tasks)}")
    print(f"Total tasks now: {len(tasks)}")

if __name__ == '__main__':
    main()
