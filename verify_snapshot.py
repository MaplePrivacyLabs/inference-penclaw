"""Check the measured checkpoint before allowing the serving process to start."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import hmac
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time


CHECKPOINT_VERIFICATION_FAILED = 42
SERVING_ENTRYPOINT_FAILED = 43
SITE_PORT = 8001
DIAGNOSTIC_LINE_LIMIT = 2048
LOG_PREFIX = re.compile(
    rb"^(?:(?:\([A-Za-z0-9_-]+ pid=[0-9]+\)|\[rank[0-9]+\]:?|"
    rb"(?:INFO|DEBUG|ERROR|WARN(?:ING)?|CRITICAL) [0-9-]+ [0-9:.,]+ \[[^]\r\n]{1,160}\])\s*)*"
)
TERMINAL_EXCEPTION = re.compile(rb"^(?:[A-Za-z_][A-Za-z0-9_]*\.)*([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)):\s*(.*)$")
EXCEPTION_TYPES = {
    b"AssertionError", b"AttributeError", b"CUDAError", b"DistBackendError", b"DistNetworkError",
    b"FileNotFoundError", b"ImportError", b"KeyError", b"ModuleNotFoundError", b"NotImplementedError",
    b"OSError", b"OutOfMemoryError", b"RuntimeError", b"SafetensorError", b"TimeoutError", b"TypeError",
    b"ValidationError", b"ValueError",
}
FAILURE_CATEGORIES = (
    ("cuda_file_io", (b"cufile", b"fastsafetensors", b"gds error")),
    ("cuda_graph_warmup", (b"cuda graph", b"cudagraph", b"graph capture", b"kernel warmup")),
    ("cuda_gpu_memory", (b"cuda out of memory", b"cudaerroroutofmemory", b"outofmemoryerror", b"kv cache blocks")),
    ("distributed_setup", (b"nccl", b"process group", b"init_process_group", b"rendezvous", b"collective")),
    ("tokenizer_or_model_code", (b"tokenizer", b"tokenization", b"trust_remote_code", b"dynamic_module_utils")),
    ("checkpoint_tensor", (b"tensor not found", b"missing tensor", b"missing weight", b"weights were not initialized", b"safetensor")),
    ("cuda_runtime", (b"cuda error", b"cuda driver", b"cuda runtime", b"cudaerror", b"cuda failure")),
    ("model_load", (b"load_model", b"load model", b"loading model", b"loading weights")),
    ("engine_startup", (b"engine core initialization failed", b"engine core failed to start", b"engine startup")),
)


class StartupDiagnostics:
    def __init__(self):
        self.ready = False
        self.partial = b""
        self.skip_line = False
        self.best = (0, "unclassified", "unclassified")

    def mark_ready(self):
        self.ready = True
        self.partial = b""
        self.best = (0, "unclassified", "unclassified")

    def add(self, data):
        if self.ready:
            return
        parts = data.split(b"\n")
        for index, part in enumerate(parts):
            if not self.skip_line and len(self.partial) + len(part) <= DIAGNOSTIC_LINE_LIMIT:
                self.partial += part
            else:
                self.skip_line = True
                self.partial = b""
            if index < len(parts) - 1:
                self.finish_line()
                if self.ready:
                    return

    def finish_line(self):
        line = LOG_PREFIX.sub(b"", self.partial).strip()
        self.partial = b""
        self.skip_line = False
        if line in (b"Application startup complete.", b"INFO:     Application startup complete."):
            self.mark_ready()
            return
        parsed = TERMINAL_EXCEPTION.fullmatch(line)
        if parsed is None:
            return
        label, message = parsed.groups()
        exception = label.decode("ascii") if label in EXCEPTION_TYPES else "unclassified"
        message = message.lower()
        if label in (b"ImportError", b"ModuleNotFoundError"):
            category = "missing_dependency"
        elif label == b"KeyError":
            category = "missing_key"
        elif label in (b"DistBackendError", b"DistNetworkError"):
            category = "distributed_setup"
        elif label == b"SafetensorError":
            category = "checkpoint_tensor"
        elif label == b"OutOfMemoryError":
            category = "reported_out_of_memory"
        else:
            category = next((name for name, terms in FAILURE_CATEGORIES if any(term in message for term in terms)), "unclassified")
        if category == "engine_startup":
            score = 1
        elif category != "unclassified":
            score = 3
        else:
            score = 2 if exception != "unclassified" else 0
        if score > self.best[0]:
            self.best = (score, exception, category)

    def summary(self, exit_code):
        _, exception, category = self.best
        return {"exit_code": exit_code, "exception": exception, "category": category}


def healthy(port):
    connection = HTTPConnection("127.0.0.1", port, timeout=0.25)
    try:
        connection.request("GET", "/health")
        return connection.getresponse().status == 200
    except (HTTPException, OSError):
        return False
    finally:
        connection.close()


def serve_startup_failure(port, bearer, diagnostic, stopped):
    expected = hashlib.sha256(bearer.encode("utf-8")).digest()

    class FailureHandler(BaseHTTPRequestHandler):
        server_version = "PenclawStartup"
        sys_version = ""

        def log_message(self, *args):
            pass

        def send_error(self, code, message=None, explain=None):
            self.respond(code, {"status": "unavailable"})

        def respond(self, code, payload):
            body = json.dumps(payload, separators=(",", ":")).encode("ascii") + b"\n"
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Vary", "Authorization")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            headers = self.headers.get_all("Authorization", [])
            scheme, _, value = (headers[0] if len(headers) == 1 else "").partition(" ")
            supplied = hashlib.sha256(value.encode("latin-1")).digest()
            payload = {"status": "unavailable", "phase": "engine_startup_failed"}
            if hmac.compare_digest(supplied, expected) and scheme.lower() == "bearer":
                payload["diagnostic"] = diagnostic
            self.respond(503, payload)

        do_HEAD = do_GET

    class FailureServer(HTTPServer):
        timeout = 0.5

        def get_request(self):
            conn, address = super().get_request()
            conn.settimeout(2)
            return conn, address

        def handle_error(self, request, client_address):
            pass

    with FailureServer(("0.0.0.0", port), FailureHandler) as server:
        while not stopped():
            server.handle_request()


def supervise_sidecar(command, bearer, port=SITE_PORT):
    requested_signal = None
    child = None

    def relay(signum, frame):
        nonlocal requested_signal
        requested_signal = signum
        if child is not None and child.poll() is None:
            child.send_signal(signum)

    previous_handlers = {signum: signal.signal(signum, relay) for signum in (signal.SIGTERM, signal.SIGINT)}
    diagnostics = StartupDiagnostics()
    try:
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        ) as child, selectors.DefaultSelector() as output:
            if requested_signal is not None:
                child.send_signal(requested_signal)
            output.register(child.stdout, selectors.EVENT_READ)

            def read_output(timeout):
                events = output.select(timeout)
                for key, _ in events:
                    data = os.read(key.fd, 4096)
                    if data:
                        diagnostics.add(data)
                    else:
                        output.unregister(key.fileobj)
                return bool(events)

            next_probe = 0
            while child.poll() is None:
                read_output(0.5)
                if not diagnostics.ready and requested_signal is None and time.monotonic() >= next_probe:
                    if healthy(port):
                        diagnostics.mark_ready()
                    next_probe = time.monotonic() + 0.5
            # Read a bounded tail before dropping any pipe inherited by exited child workers.
            for _ in range(16):
                if not read_output(0):
                    break
            if not diagnostics.ready:
                diagnostics.finish_line()
            code = child.returncode
        exit_code = code if code >= 0 else 128 - code
        if requested_signal is None and exit_code and not diagnostics.ready:
            # The diagnostic listener must not keep any failed engine workers alive.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                serve_startup_failure(port, bearer, diagnostics.summary(exit_code), lambda: requested_signal is not None)
            except OSError:
                print("The startup failure health endpoint could not bind", file=sys.stderr)
        return 128 + requested_signal if requested_signal is not None else exit_code
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def verify_snapshot(root, manifest):
    files = manifest["files"]
    with os.scandir(root) as entries:
        present = {entry.name: entry.is_file(follow_symlinks=False) for entry in entries}
    if present.keys() != files.keys() or not all(present.values()):
        raise ValueError("Mounted checkpoint has missing, extra, or non-regular files")

    with ThreadPoolExecutor(max_workers=8) as workers:
        pending = [workers.submit(verify_file, root / name, expected) for name, expected in files.items()]
        try:
            for check in as_completed(pending):
                check.result()
        except (KeyError, OSError, ValueError):
            workers.shutdown(cancel_futures=True)
            raise


def verify_file(path, expected):
    size = expected["size"]
    if path.stat().st_size != size:
        raise ValueError(f"Checkpoint file size mismatch: {path.name}")

    if "sha256" in expected:
        digest = hashlib.sha256()
        expected_digest = expected["sha256"]
    else:
        digest = hashlib.sha1(usedforsecurity=False)
        digest.update(f"blob {size}\0".encode("ascii"))
        expected_digest = expected["git-blob-sha1"]

    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected_digest:
        raise ValueError(f"Checkpoint file digest mismatch: {path.name}")


def main():
    try:
        arguments = sys.argv[1:]
        if len(arguments) < 2 or arguments[0] != "--model" or arguments.count("--model") != 1:
            raise ValueError("Expected one explicit mount as the first --model argument")
        manifest = json.loads(os.environ.pop("MAPLE_PENCLAW_SNAPSHOT"))
        bearer = os.environ.pop("PENCLAW_STAGE_API_KEY", "")
        if not bearer or not os.environ.get("METRICS_API_KEY"):
            raise ValueError("Required serving or metrics credential is missing")
        verify_snapshot(Path(arguments[1]), manifest)
    except (KeyError, OSError, ValueError) as error:
        print(f"Checkpoint verification failed: {error}", file=sys.stderr)
        return CHECKPOINT_VERIFICATION_FAILED

    print(f"Verified {len(manifest['files'])} checkpoint files for {manifest['repo']}@{manifest['revision']}", flush=True)
    os.environ["VLLM_API_KEY"] = bearer
    os.environ.pop("METRICS_API_KEY")
    sidecar = "/opt/tinfoil/inference-sidecar"
    try:
        return supervise_sidecar([sidecar, "vllm", "serve", *arguments], bearer)
    except OSError:
        print("The verified checkpoint's serving entrypoint could not start", file=sys.stderr)
        return SERVING_ENTRYPOINT_FAILED


if __name__ == "__main__":
    sys.exit(main())
