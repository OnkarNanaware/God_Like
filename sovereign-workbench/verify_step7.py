"""
verify_step7_load.py
====================
Step 7: Sequential load check — all 4 model slots probed back-to-back.
Reports per-model latency and any failures.

macOS/Apple Silicon: nvidia-smi is not available.
VRAM is reported via `memory_pressure` and `vm_stat` as the best available proxy.
"""
import asyncio, sys, time, subprocess, pathlib, tempfile
sys.stdout.reconfigure(line_buffering=True)


async def main():
    from app.audit.logger import AuditLogger
    from app.models.ollama_client import OllamaClient, MODEL_REGISTRY

    tmp = pathlib.Path(tempfile.mkdtemp())
    audit = AuditLogger(log_path=tmp / "audit.jsonl")

    print("=== STEP 7: SEQUENTIAL LOAD CHECK ===")
    print("Firing 4 model slots back-to-back with no delay between calls.\n")

    probes = [
        {
            "slot": "reasoning (text)",
            "model_key": "qwen25_7b_instruct",
            "prompt": "In one sentence, what is the main goal of a process safety management system?",
            "embed": False,
        },
        {
            "slot": "coder (code)",
            "model_key": "qwen25_coder_14b",
            "prompt": "Fix this Python bug and explain it in one line: def add(a,b): return a-b",
            "embed": False,
        },
        {
            "slot": "vision (text gen)",
            "model_key": "qwen25vl_3b",
            "prompt": "Describe a typical industrial safety sign in two words.",
            "embed": False,
        },
        {
            "slot": "embedding (bge-m3)",
            "model_key": "bge_m3",
            "prompt": "MRPL environmental compliance inspection",
            "embed": True,
        },
    ]

    results = []
    all_ok = True

    for p in probes:
        model_key = p["model_key"]
        slot = p["slot"]
        reg = MODEL_REGISTRY.get(model_key, {})
        tag = reg.get("ollama_tag", "?")

        t0 = time.monotonic()
        try:
            llm = OllamaClient(model_name=model_key, audit_logger=audit)
            if p["embed"]:
                vec = await llm.embeddings(p["prompt"])
                elapsed = time.monotonic() - t0
                ok = len(vec) == 1024
                detail = f"dim={len(vec)} elapsed={elapsed:.1f}s"
            else:
                resp = await asyncio.wait_for(
                    llm.chat_completion(
                        [{"role": "user", "content": p["prompt"]}],
                        request_id=f"load-{model_key}",
                        temperature=0.0,
                        max_tokens=64,
                    ),
                    timeout=120.0,
                )
                elapsed = time.monotonic() - t0
                ok = bool(resp.content and resp.content.strip())
                detail = f"tokens={resp.response_tokens} elapsed={elapsed:.1f}s preview={repr(resp.content[:80])}"

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            ok = False
            detail = f"TIMEOUT after {elapsed:.0f}s"
        except Exception as exc:
            elapsed = time.monotonic() - t0
            ok = False
            detail = f"ERROR {type(exc).__name__}: {exc}"

        if not ok:
            all_ok = False

        icon = "PASS" if ok else "FAIL"
        print(f"  [{icon}] {slot}: model={model_key} tag={tag} {detail}")
        results.append({"slot": slot, "ok": ok, "elapsed": elapsed, "detail": detail})

    # Memory pressure report (macOS proxy for VRAM)
    print()
    mp = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10)
    if mp.returncode == 0:
        # Parse the system-wide memory pressure percentage
        for line in mp.stdout.splitlines():
            if "System-wide memory free percentage" in line or "Pages free" in line or "memory pressure" in line.lower():
                print(f"  Memory: {line.strip()}")
    else:
        vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10)
        if vm.returncode == 0:
            lines = vm.stdout.splitlines()
            print(f"  vm_stat (first 4 lines):")
            for l in lines[:4]:
                print(f"    {l}")

    # Ollama process memory
    ol_mem = subprocess.run(
        ["ps", "-o", "pid,rss,vsz,comm", "-p", 
         subprocess.run(["pgrep", "ollama"], capture_output=True, text=True).stdout.strip()],
        capture_output=True, text=True, timeout=10
    )
    if ol_mem.returncode == 0:
        print(f"  Ollama process memory (RSS/VSZ in KB):")
        for line in ol_mem.stdout.strip().splitlines():
            print(f"    {line}")

    total_elapsed = sum(r["elapsed"] for r in results)
    print(f"\n  Total elapsed (sequential): {total_elapsed:.1f}s")
    print(f"  VRAM: macOS/Apple Silicon — no NVIDIA GPU; nvidia-smi not available")
    print(f"  Peak VRAM (nvidia-smi): N/A — CPU/Apple Silicon inference only")
    print(f"\nStep 7 result: {'PASS' if all_ok else 'FAIL'}")
    if not all_ok:
        for r in results:
            if not r["ok"]:
                print(f"  FAIL: {r['slot']} — {r['detail']}")


asyncio.run(main())
