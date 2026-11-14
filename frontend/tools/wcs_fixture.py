"""Build display fixtures from local files only; never call a NASA service."""
import base64
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.epoch_frames import grid, SIZE
from backend.app.wcs_axes import axes_from_fits, axes_from_wcs
from research import spherex


def build():
    recorded = ROOT / "research" / "outputs"
    original = json.loads((recorded / "metadata.json").read_text(encoding="utf-8"))
    query = original["query"]
    # Re-render the existing local FITS so these PNGs and WCS are a verified pair.
    with tempfile.TemporaryDirectory(prefix="spherex-wcs-fixture-") as directory:
        output = Path(directory)
        metadata = spherex.render_cutout(recorded / "cutout.fits", original.get("sia", {}),
                                        query["ra"], query["dec"], query["radius_deg"], output,
                                        original.get("cutout_url", "offline fixture"))
        metadata["wcs_axes"] = axes_from_fits(recorded / "cutout.fits")
        metadata["fixture_note"] = "OFFLINE REPLAY of local FITS; no NASA requests. Query controls do not select new data."
        images = {name: base64.b64encode((output / f"{name}-background.png").read_bytes()).decode("ascii")
                  for name in ("black", "white")}
    target = grid(query["ra"], query["dec"])
    return {"preview": {"metadata": metadata, **images},
            "epochs": {"grid": {"header": dict(target.to_header()), "shape_yx": [SIZE, SIZE]},
                       "wcs_axes": axes_from_wcs(target, (SIZE, SIZE), "SYNTHETIC_UI_FIXTURE: Phase 4.4 ICRS TAN grid")}}


if __name__ == "__main__":
    print(json.dumps(build(), allow_nan=False))
