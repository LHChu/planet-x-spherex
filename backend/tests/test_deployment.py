"""Deployment checks with generated responses and no local FITS dependency."""
import json
import http.client
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch

from fastapi.testclient import TestClient
import psutil

from backend import start
from backend.app.main import create_app
from backend.app.service import preview_directory

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://zo4j433.github.io"


class DeploymentTests(unittest.TestCase):
    def test_preview_profiles_on_production_origin_and_free_single_worker_contract(self):
        # Read-only checks: never modify deployment or contact Render.
        config = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("plan: free", config)
        self.assertIn('value: "1"', config)
        with patch.dict(os.environ, {"CORS_ORIGINS": ORIGIN}):
            app = create_app()
        with TestClient(app, base_url="https://example.onrender.com") as client:
            for profile in (None, "small", "medium"):
                body = {"ra":1., "dec":2., "radius_deg":.01}
                if profile is not None:
                    body["cutout_profile"] = profile
                with patch("backend.app.main.create_preview", return_value=(b"png",b"inverse",{})) as create:
                    response = client.post("/api/preview", json=body, headers={"Origin":ORIGIN})
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(create.call_args.kwargs, {"cutout_profile":"medium"} if profile == "medium" else {})
                self.assertEqual(response.headers["access-control-allow-origin"],ORIGIN)
                self.assertTrue(response.json()["image_url"].startswith("https://example.onrender.com/"))
                self.assertEqual(client.get(response.json()["image_url"]).content,b"png")
            invalid = client.post("/api/preview",json={"ra":1.,"dec":2.,"radius_deg":.01,"cutout_profile":"large"})
            self.assertEqual(invalid.status_code,422)

    def test_start_configuration(self):
        with patch.dict(os.environ, {"PORT": "12345", "WEB_CONCURRENCY": "8"}), patch.object(start.uvicorn, "run") as run:
            start.main()
        self.assertEqual(run.call_args.args, ("backend.app.main:app",))
        options = run.call_args.kwargs
        self.assertEqual((options["host"], options["port"], options["workers"], options["reload"]),
                         ("0.0.0.0", 12345, 1, False))
        with patch.dict(os.environ, {"PORT": "0"}), self.assertRaises(ValueError):
            start.main()

    def test_production_cors_and_https_artifact_urls(self):
        with patch.dict(os.environ, {"CORS_ORIGINS": ORIGIN}):
            app = create_app()
        with TestClient(app, base_url="https://example.onrender.com") as client:
            for origin, status in [(ORIGIN, 200), ("https://untrusted.example", 400)]:
                response = client.options("/api/preview", headers={"Origin": origin,
                    "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"})
                self.assertEqual(response.status_code, status)
            with patch("backend.app.main.create_preview", return_value=(b"png", b"inverse", {})):
                result = client.post("/api/preview", json={"ra": 1., "dec": 2., "radius_deg": .01}).json()
            self.assertTrue(result["image_url"].startswith("https://example.onrender.com/"))
            self.assertEqual(client.get(result["image_url"]).content, b"png")
        with patch.dict(os.environ, {"CORS_ORIGINS": ORIGIN + "/planet-x-spherex/"}), self.assertRaises(ValueError):
            create_app()

    def test_temporary_cleanup_on_failure(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with preview_directory() as directory:
                (directory / "cutout.fits").write_bytes(b"synthetic")
                raise RuntimeError("synthetic")
        self.assertFalse(directory.exists())

    def test_real_server_without_outputs_or_fits(self):
        # Copy runtime source only; never copy ignored outputs, fixtures or venvs.
        with tempfile.TemporaryDirectory(prefix="spherex-deploy-test-") as temporary:
            clean = Path(temporary)
            for relative in [Path("backend/__init__.py"), Path("backend/start.py"),
                             Path("research/__init__.py"), Path("research/spherex.py"),
                             *[p.relative_to(ROOT) for p in (ROOT / "backend/app").glob("*.py")]]:
                target = clean / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            env = {**os.environ, "PORT": str(port), "CORS_ORIGINS": ORIGIN,
                   "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
            # Allow Windows asyncio's loopback socketpair; reject external access.
            script = ("import sys,runpy\n"
                      "def audit(event,args):\n"
                      " if event == 'socket.connect':\n"
                      "  address=args[1]\n"
                      "  if isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'): return\n"
                      " elif event == 'socket.getaddrinfo':\n"
                      "  if args[0] in ('localhost','127.0.0.1','::1'): return\n"
                      " else: return\n"
                      " raise RuntimeError('Server must not access external network')\n"
                      "sys.addaudithook(audit)\n"
                      "runpy.run_module('backend.start',run_name='__main__')\n")
            with (clean / "server.log").open("w+", encoding="utf-8") as log:
                process = subprocess.Popen([sys.executable, "-c", script], cwd=clean, env=env,
                    stdout=log, stderr=subprocess.STDOUT)
                try:
                    began = time.monotonic()
                    deadline = began + 30
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            break
                        try:
                            request = urllib.request.Request(f"http://127.0.0.1:{port}/health",
                                headers={"X-Forwarded-Proto": "https"})
                            with urllib.request.urlopen(request, timeout=1) as response:
                                self.assertEqual(json.load(response), {"status": "ok"})
                            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                            try:
                                connection.request("GET", "/health/", headers={"X-Forwarded-Proto": "https"})
                                forwarded = connection.getresponse()
                                self.assertEqual(forwarded.status, 307)
                                self.assertTrue(forwarded.getheader("Location").startswith("https://"))
                                forwarded.read()
                            finally:
                                connection.close()
                            server = psutil.Process(process.pid)
                            # Windows venv's launcher can create a child interpreter.
                            # Include it in RSS; worker count is checked above via run().
                            processes = [server, *server.children(recursive=True)]
                            rss = sum(p.memory_info().rss for p in processes)
                            print(f"Clean-source server ready in {time.monotonic() - began:.2f}s; "
                                  f"process-tree idle RSS {rss / 1024**2:.1f} MiB")
                            return
                        except (OSError, urllib.error.URLError):
                            time.sleep(.1)
                    log.flush()
                    self.fail((clean / "server.log").read_text(encoding="utf-8"))
                finally:
                    try:
                        children = psutil.Process(process.pid).children(recursive=True)
                    except psutil.NoSuchProcess:
                        children = []
                    for child in children:
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    _, alive = psutil.wait_procs(children, timeout=5)
                    for child in alive:
                        child.kill()
