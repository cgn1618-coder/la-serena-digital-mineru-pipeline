#!/usr/bin/env python3
"""
Poll MinerU tasks and download results.
Reads tasks from /tmp/mineru_tasks.json
"""
import requests
import json
import time
import os
import sys

from auth import CredentialError, mineru_headers, raise_for_auth

API_POLL = "https://mineru.net/api/v4/extract/task/{}"
OUTPUT_DIR = "/root/pipeline/mineru_output"

# Cota superior de rondas para no quedarse girando si una tarea nunca termina.
MAX_ROUNDS = int(os.getenv("MINERU_POLL_MAX_ROUNDS", "120"))

def poll_all():
    mineru_headers()  # puerta de credenciales antes de cualquier petición

    with open('/tmp/mineru_tasks.json') as f:
        tasks = json.load(f)
    
    pending = [t for t in tasks if t.get('status') == 'submitted']
    print(f"Pending tasks: {len(pending)}/{len(tasks)}")
    
    round_num = 0
    while pending and round_num < MAX_ROUNDS:
        round_num += 1
        done_count = 0
        fail_count = 0
        running_count = 0
        
        for t in pending[:]:  # iterate over copy
            try:
                resp = requests.get(
                    API_POLL.format(t['task_id']),
                    headers=mineru_headers(content_type=False),
                    timeout=30,
                )
                raise_for_auth(resp)
                data = resp.json()
                state = data.get('data', {}).get('state', 'unknown')
                
                if state == 'done':
                    zip_url = data['data'].get('full_zip_url')
                    if zip_url:
                        fname = t['filename'][:60]
                        # Determine subdir
                        if any(kw in fname.lower() for kw in ['ecology', 'environmental', 'biology', 'living', 'principles', 'commerce']):
                            subdir = 'ecologia'
                        elif 'ecology_part' in fname.lower():
                            subdir = 'ecologia'
                        else:
                            subdir = 'geologia'
                        
                        safe = fname.replace('/', '_').replace(' ', '_')[:80]
                        out = os.path.join(OUTPUT_DIR, subdir, safe + '.zip')
                        
                        dl = requests.get(zip_url, timeout=300)
                        with open(out, 'wb') as f:
                            f.write(dl.content)
                        
                        size_mb = len(dl.content) / (1024*1024)
                        t['status'] = 'done'
                        pending.remove(t)
                        done_count += 1
                        print(f"  ✅ [{round_num}] {fname} ({size_mb:.1f}MB)")
                    else:
                        t['status'] = 'failed'
                        pending.remove(t)
                        fail_count += 1
                        print(f"  ❌ [{round_num}] {t['filename'][:50]} - no zip_url")
                        
                elif state == 'failed':
                    err = data['data'].get('err_msg', 'unknown')
                    t['status'] = 'failed'
                    pending.remove(t)
                    fail_count += 1
                    print(f"  ❌ [{round_num}] {t['filename'][:50]} - {err[:80]}")
                else:
                    running_count += 1
                    
            except CredentialError:
                raise
            except Exception as e:
                print(f"  ⚠️ [{round_num}] {t['filename'][:40]} - poll error: {str(e)[:50]}")
        
        print(f"[Round {round_num}] done={done_count}, failed={fail_count}, running={running_count}, pending={len(pending)}")
        
        if not pending:
            break
        
        # Save progress
        with open('/tmp/mineru_tasks.json', 'w') as f:
            json.dump(tasks, f, indent=2)
        
        time.sleep(20)
    
    if pending:
        print(f"\n⚠️ Se alcanzó el límite de {MAX_ROUNDS} rondas con {len(pending)} tarea(s) "
              f"aún en curso. Vuelve a ejecutar para seguir esperándolas.")

    # Guardar el estado final, no solo el de rondas intermedias.
    with open('/tmp/mineru_tasks.json', 'w') as f:
        json.dump(tasks, f, indent=2)

    # Final summary
    done = sum(1 for t in tasks if t.get('status') == 'done')
    failed = sum(1 for t in tasks if t.get('status') == 'failed')
    print(f"\n=== FINAL ===")
    print(f"Done: {done}/{len(tasks)}")
    print(f"Failed: {failed}/{len(tasks)}")
    
    geo = len(os.listdir(os.path.join(OUTPUT_DIR, 'geologia')))
    eco = len(os.listdir(os.path.join(OUTPUT_DIR, 'ecologia')))
    print(f"ZIPs: geología={geo}, ecología={eco}")

if __name__ == '__main__':
    poll_all()
