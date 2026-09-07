#!/usr/bin/env python3
"""
MinerU Batch Processing Script
Submits all PDFs to MinerU Precision API v4, polls results, downloads ZIPs.
"""
import requests
import json
import time
import os
import sys

from auth import CredentialError, mineru_headers, raise_for_auth

BASE_URL = "https://laserenadigital.cl"
PDF_DIR = "/root/portal/static/pdfs"
OUTPUT_DIR = "/root/pipeline/mineru_output"
API_SUBMIT = "https://mineru.net/api/v4/extract/task"
API_POLL = "https://mineru.net/api/v4/extract/task/{}"
API_BATCH = "https://mineru.net/api/v4/file-urls/batch"
API_BATCH_RESULTS = "https://mineru.net/api/v4/extract-results/batch/{}"

def get_pdf_files():
    """Get all PDF files with their URLs."""
    pdfs = []
    for f in sorted(os.listdir(PDF_DIR)):
        if f.endswith('.pdf'):
            # URL-encode the filename for spaces and special chars
            from urllib.parse import quote
            url = f"{BASE_URL}/static/pdfs/{quote(f)}"
            path = os.path.join(PDF_DIR, f)
            size_mb = os.path.getsize(path) / (1024*1024)
            pdfs.append({
                "filename": f,
                "url": url,
                "size_mb": round(size_mb, 1)
            })
    return pdfs

def submit_batch(pdfs, batch_size=10):
    """Submit PDFs in batches to MinerU API."""
    all_tasks = []
    
    for i in range(0, len(pdfs), batch_size):
        batch = pdfs[i:i+batch_size]
        batch_num = i//batch_size + 1
        print(f"\n{'='*60}")
        print(f"BATCH {batch_num}: {len(batch)} files")
        
        urls = [p['url'] for p in batch]
        
        # Submit via batch endpoint
        payload = {
            "urls": urls,
            "language": "en",
            "model_version": "pipeline",
            "is_ocr": False,
            "enable_formula": True,
            "enable_table": True
        }
        
        try:
            resp = requests.post(API_BATCH, headers=mineru_headers(), json=payload, timeout=120)
            raise_for_auth(resp)
            data = resp.json()
            
            if data.get('code') == 0:
                batch_id = data['data']['batch_id']
                print(f"  Batch ID: {batch_id}")
                for p in batch:
                    all_tasks.append({
                        "filename": p['filename'],
                        "batch_id": batch_id,
                        "status": "submitted"
                    })
            else:
                print(f"  ERROR: {data.get('msg', 'unknown')}")
                # Fallback: submit individually
                for p in batch:
                    task = submit_single(p)
                    if task:
                        all_tasks.append(task)
        except CredentialError:
            # Un fallo de credenciales afecta a todo el lote: reintentar por
            # archivo solo gastaría tiempo repitiendo el mismo rechazo.
            raise
        except Exception as e:
            print(f"  Batch submit failed: {e}")
            # Fallback to individual
            for p in batch:
                task = submit_single(p)
                if task:
                    all_tasks.append(task)
        
        # Rate limit: 50 files/min = 10 files per batch = wait at least 12s between batches
        if i + batch_size < len(pdfs):
            time.sleep(15)
    
    return all_tasks

def submit_single(pdf):
    """Submit a single PDF."""
    payload = {
        "url": pdf['url'],
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
            task_id = data['data']['task_id']
            print(f"  {pdf['filename'][:50]}: task_id={task_id}")
            return {"filename": pdf['filename'], "task_id": task_id, "status": "submitted"}
        else:
            print(f"  {pdf['filename'][:50]}: ERROR - {data.get('msg')}")
    except CredentialError:
        raise
    except Exception as e:
        print(f"  {pdf['filename'][:50]}: EXCEPTION - {e}")
    return None

def poll_batch_results(tasks):
    """Poll batch results and download ZIPs."""
    batch_ids = set(t['batch_id'] for t in tasks if 'batch_id' in t)
    
    for batch_id in batch_ids:
        print(f"\nPolling batch: {batch_id}")
        max_polls = 30
        for attempt in range(max_polls):
            try:
                resp = requests.get(
                    API_BATCH_RESULTS.format(batch_id),
                    headers=mineru_headers(),
                    timeout=60
                )
                raise_for_auth(resp)
                data = resp.json()
                
                if data.get('code') == 0:
                    results = data.get('data', {}).get('results', [])
                    done = sum(1 for r in results if r.get('state') == 'done')
                    failed = sum(1 for r in results if r.get('state') == 'failed')
                    running = sum(1 for r in results if r.get('state') == 'running')
                    print(f"  [{attempt+1}] done={done}, running={running}, failed={failed}")
                    
                    if running == 0:
                        # All done or failed
                        for r in results:
                            fname = r.get('filename', 'unknown')
                            if r.get('state') == 'done' and r.get('full_zip_url'):
                                download_zip(fname, r['full_zip_url'])
                            elif r.get('state') == 'failed':
                                print(f"  FAILED: {fname} - {r.get('err_msg', '')}")
                        break
            except CredentialError:
                raise
            except Exception as e:
                print(f"  Poll error: {e}")
            
            time.sleep(15)
        
        # Also handle individually-submitted tasks
        for t in tasks:
            if 'task_id' in t and t['status'] == 'submitted':
                poll_single(t)

def poll_single(task):
    """Poll a single task."""
    task_id = task['task_id']
    for attempt in range(20):
        try:
            resp = requests.get(API_POLL.format(task_id), headers=mineru_headers(), timeout=30)
            raise_for_auth(resp)
            data = resp.json()
            state = data.get('data', {}).get('state', '')
            
            if state == 'done':
                zip_url = data['data'].get('full_zip_url')
                if zip_url:
                    print(f"  DONE: {task['filename'][:50]} → downloading")
                    download_zip(task['filename'], zip_url)
                    task['status'] = 'done'
                break
            elif state == 'failed':
                print(f"  FAILED: {task['filename'][:50]} → {data['data'].get('err_msg', '')}")
                task['status'] = 'failed'
                break
        except CredentialError:
            raise
        except Exception as e:
            print(f"  Poll error en {task['filename'][:40]}: {e}")
        time.sleep(10)

def download_zip(filename, url):
    """Download and save ZIP result."""
    safe_name = filename.replace('/', '_').replace(' ', '_')[:80]
    
    # Determine category
    if 'ecology' in filename.lower() or 'ecology' in safe_name.lower() or 'Environmental' in filename:
        subdir = 'ecologia'
    else:
        subdir = 'geologia'
    
    out_path = os.path.join(OUTPUT_DIR, subdir, safe_name + '.zip')
    
    try:
        resp = requests.get(url, timeout=120)
        with open(out_path, 'wb') as f:
            f.write(resp.content)
        size_mb = len(resp.content) / (1024*1024)
        print(f"    Saved: {safe_name}.zip ({size_mb:.1f} MB)")
    except Exception as e:
        print(f"    Download failed: {e}")

def main():
    # Puerta de credenciales: si falta o caducó el token, abortamos aquí y no
    # tras haber listado y subido archivos.
    mineru_headers()

    pdfs = get_pdf_files()
    total_size = sum(p['size_mb'] for p in pdfs)
    
    print(f"=== MinerU Batch Processing ===")
    print(f"Total PDFs: {len(pdfs)}")
    print(f"Total size: {total_size:.0f} MB")
    print(f"Output dir: {OUTPUT_DIR}")
    
    # Show what we're processing
    for p in pdfs:
        print(f"  [{p['size_mb']:.0f}MB] {p['filename'][:70]}")
    
    # Submit in batches
    tasks = submit_batch(pdfs, batch_size=10)
    print(f"\nSubmitted: {len(tasks)} tasks")
    
    # Save task list for recovery
    with open('/tmp/mineru_tasks.json', 'w') as f:
        json.dump(tasks, f, indent=2)
    
    # Poll and download
    poll_batch_results(tasks)
    
    # Summary
    done = sum(1 for t in tasks if t['status'] == 'done')
    failed = sum(1 for t in tasks if t['status'] == 'failed')
    print(f"\n=== SUMMARY ===")
    print(f"Done: {done}/{len(tasks)}")
    print(f"Failed: {failed}/{len(tasks)}")
    
    # Count outputs
    geo_zips = len(os.listdir(os.path.join(OUTPUT_DIR, 'geologia')))
    eco_zips = len(os.listdir(os.path.join(OUTPUT_DIR, 'ecologia')))
    print(f"Geología ZIPs: {geo_zips}")
    print(f"Ecología ZIPs: {eco_zips}")

if __name__ == '__main__':
    main()
