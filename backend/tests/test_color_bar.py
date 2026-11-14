"""Cross-runtime check against the actual Phase 4.4 PNG mapping, offline."""
import io
import json
import subprocess
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from backend.app.epoch_frames import png

ROOT = Path(__file__).resolve().parents[2]


class ColorBarTests(unittest.TestCase):
    def test_frontend_matches_backend_png_including_denominator_floor_and_transparency(self):
        cases = []
        for lo, hi in [(-2., 6.), (-5., -1.), (1., 1. + 1e-10)]:
            values = np.r_[lo - 1, np.linspace(lo, hi, 33), hi + 1, np.nan]
            data = values.reshape(1, -1)
            before = data.copy()
            image = np.array(Image.open(io.BytesIO(png(data, lo, hi))))[0]
            np.testing.assert_equal(data, before)
            self.assertEqual(image[-1, 3], 0)
            cases.append({"scale": {"lo": lo, "hi": hi, "denominator": max(hi-lo, 1e-8),
                                    "stretch": "asinh", "a": 10, "unit": "MJy/sr", "rounding": "nearest_even"},
                          "values": [float(v) if np.isfinite(v) else None for v in values],
                          "expected": [int(v) if alpha else None for v, alpha in zip(image[:, 0], image[:, 3])]})
        script = """
const fs = require('node:fs'), vm = require('node:vm');
const context = { window: {} }; vm.runInNewContext(fs.readFileSync('frontend/color-bar.js', 'utf8'), context);
const cb = context.window.SpherexColorBar;
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(c => c.values.map(v => cb.gray(cb.mapping(c.scale), v)))));
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps(cases), text=True,
                                capture_output=True, check=True, cwd=ROOT, timeout=20)
        self.assertEqual(json.loads(result.stdout), [case["expected"] for case in cases])


if __name__ == "__main__":
    unittest.main()
