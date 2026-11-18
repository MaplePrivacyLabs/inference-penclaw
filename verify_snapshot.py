"""Check the measured checkpoint before allowing the serving process to start."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import sys


CHECKPOINT_VERIFICATION_FAILED = 42
SERVING_ENTRYPOINT_FAILED = 43


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
        os.execv(sidecar, [sidecar, "vllm", "serve", *arguments])
    except OSError:
        print("The verified checkpoint's serving entrypoint could not start", file=sys.stderr)
        return SERVING_ENTRYPOINT_FAILED


if __name__ == "__main__":
    sys.exit(main())
