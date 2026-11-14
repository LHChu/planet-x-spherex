"""Real IRSA verification. Run from any directory; no synthetic data or full-frame fallback."""
import csv
import io
import json
import platform
import re
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


if __package__:
    from .spherex import fetch, query_images, build_cutout_url, render_cutout
else:
    from spherex import fetch, query_images, build_cutout_url, render_cutout

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
RA, DEC, RADIUS = 127.69444, -39.17760, 0.01
LIMIT = 32 * 1024 * 1024



def write_report(result):
    (OUT / "run.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    text = ["# NASA SPHEREx 真實資料最小驗證", "",
            "此報告由 verify_spherex.py 的實際執行產生。", "",
            f"- UTC：{result['started_utc']}",
            f"- 狀態：{result['status']}",
            f"- 查詢：RA={RA}, Dec={DEC}, radius={RADIUS} deg；DR1 無結果才查 QR3。",
            "- Cutout：3arcmin 完整邊長；不下載完整影像。",
            f"- 總執行秒數：{result['elapsed_seconds']:.3f}",
            f"- 程序最高 RSS bytes：{result.get('peak_rss_bytes', '未測得')}",
            f"- FITS bytes：{result.get('fits_bytes', '未取得')}", "",
            "## 執行紀錄", "", "```json", json.dumps(result, indent=2, ensure_ascii=False), "```", "",
            "## 檢查方式", "",
            "查看 outputs/images.csv、metadata.json、run.json 以及保存的 SIA VOTable。",
            "成功時開啟 outputs/black-background.png 和 outputs/white-background.png。",
            "outputs/ 與 FITS 已由 research/.gitignore 排除；不應提交大型資料。", ""]
    (ROOT / "api-verification.md").write_text("\n".join(text), encoding="utf-8")


def main():
    OUT.mkdir(exist_ok=True)
    # Do not let failed reruns leave apparently current preview artifacts.
    for name in ("black-background.png", "white-background.png", "metadata.json", "cutout.fits", "images.csv"):
        (OUT / name).unlink(missing_ok=True)
    started = time.perf_counter()
    result = {"started_utc": datetime.now(timezone.utc).isoformat(), "status": "failed",
              "python": sys.version, "platform": platform.platform(), "events": [], "errors": []}
    stop = threading.Event()
    peak = [0]
    monitor = None
    try:
        import psutil
        process = psutil.Process()

        def sample():
            while not stop.is_set():
                mem = process.memory_info()
                peak[0] = max(peak[0], mem.rss, getattr(mem, "peak_wset", 0))
                stop.wait(0.02)

        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        import numpy as np
        import astropy
        from astropy.io import fits
        from astropy.io.votable import parse
        from astropy.coordinates import SkyCoord
        from astropy.time import Time
        from astropy.wcs import WCS
        from PIL import Image, __version__ as pillow_version
        result["versions"] = {"astropy": astropy.__version__, "numpy": np.__version__,
                              "Pillow": pillow_version, "psutil": psutil.__version__}

        rows, query_info = query_images(RA, DEC, RADIUS, OUT, result["events"])
        result.update(query_info)
        result["image_count_returned"] = len(rows)
        fields = ["obs_id", "obs_collection", "access_url", "t_min", "t_max", "t_exptime", "energy_bandpassname", "detector", "detector_source"]
        with (OUT / "images.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps([{k: r.get(k) for k in fields} for r in rows], indent=2))
        if not rows:
            result["status"] = "no_data"
            return 2

        for index, row in enumerate(rows[:5]):
            try:
                cutout_url = build_cutout_url(row, RA, DEC)
                path = OUT / "cutout.fits"
                fetch(cutout_url, path, LIMIT, result["events"])
                metadata = render_cutout(path, row, RA, DEC, RADIUS, OUT, cutout_url)
                result.update(status="success", fits_bytes=path.stat().st_size,
                              selected_obs_id=row.get("obs_id"), detector=metadata["detector"],
                              image_shape=metadata["shape"], hdu_summary=[{k: v for k, v in h.items() if k != "header"} for h in metadata["hdu"]])
                return 0
            except Exception as exc:
                result["errors"].append({"candidate": index, "error": repr(exc)})
        raise RuntimeError("No valid cutout among first five candidates; see errors")
    except Exception:
        result["errors"].append({"traceback": traceback.format_exc()})
        return 1
    finally:
        stop.set()
        if monitor:
            monitor.join()
            result["peak_rss_bytes"] = peak[0]
            result["memory_method"] = "20 ms RSS polling plus Windows peak_wset when available; process only"
        result["elapsed_seconds"] = time.perf_counter() - started
        write_report(result)
        print(f"Status: {result['status']}; report: {ROOT / 'api-verification.md'}")


if __name__ == "__main__":
    sys.exit(main())
