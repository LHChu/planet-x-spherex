"""Local Preview API resource check, synthetic high-entropy FITS only."""
import base64
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import tracemalloc

from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.tests.cutout_size_probe import peak_rss
from backend.tests.test_preview_medium import BODY, synthetic_request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/"backend/test-results/preview-medium"


def deny_external(event,args):
    # Windows asyncio implements socketpair using a loopback connection.
    if event == "socket.connect":
        if isinstance(args[1],tuple) and args[1][0] in ("127.0.0.1","::1"): return
    elif event == "socket.getaddrinfo":
        if args[0] in ("localhost","127.0.0.1","::1"): return
    else: return
    raise RuntimeError("External network forbidden in Preview probe")


def worker(profile):
    sys.addaudithook(deny_external)
    OUT.mkdir(parents=True,exist_ok=True)
    app = create_app()
    with TestClient(app,base_url="https://offline.example") as client:
        baseline = peak_rss()
        tracemalloc.start()
        began = time.perf_counter()
        response,_,_,_ = synthetic_request(client,{**BODY,"cutout_profile":profile},
            dtype="float64",sip=True,shape=(65,65) if profile=="medium" else (29,29))
        assert response.status_code==200,response.text
        payload = response.json()
        black = client.get(payload["image_url"]).content
        white = client.get(payload["inverted_image_url"]).content
        elapsed = time.perf_counter()-began
        _,traced = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        retained = sum(len(b)+len(w) for _,b,w in app.state.image_cache._items.values())
        result = {"profile":profile,"shape_yx":payload["metadata"]["actual_shape_yx"],
                  "elapsed_seconds":elapsed,"process_peak_rss_bytes":peak_rss(),
                  "baseline_peak_rss_bytes":baseline,"traced_peak_bytes":traced,
                  "response_bytes":len(response.content),"png_cache_bytes":retained}
        # Local headless browser fixtures contain only generated data.
        payload.update(black_png_base64=base64.b64encode(black).decode(),white_png_base64=base64.b64encode(white).decode())
        (OUT/f"{profile}.json").write_text(json.dumps(payload,allow_nan=False),encoding="utf-8")
        print(json.dumps(result))


if __name__=="__main__":
    if len(sys.argv)==2: worker(sys.argv[1])
    else:
        samples=[]
        for profile in ("small","medium"):
            for _ in range(3):
                run=subprocess.run([sys.executable,"-m","backend.tests.preview_medium_probe",profile],
                    cwd=ROOT,capture_output=True,text=True,check=True)
                samples.append(json.loads(run.stdout))
        report={"platform":platform.platform(),"python":platform.python_version(),
                "network":"External socket DNS/connect denied; Windows asyncio loopback allowed", "samples":samples,
                "scope":"local sequential API, generated high-entropy float64 with SIP; includes fixture creation, JSON serialization, cache and PNG retrieval; tracemalloc enabled"}
        (ROOT/"docs/preview-medium-measurements.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps(report,indent=2))
