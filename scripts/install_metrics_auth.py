"""Install the metrics guard into the image, after checking what it relies on.

Runs once while the image is built. It refuses to continue if the vLLM build is
not the one the guard was written against, so a changed base image fails the
build instead of shipping a guard that no longer covers /metrics.
"""

import importlib
import importlib.util
import inspect
import shutil
from importlib.metadata import version
from pathlib import Path

EXPECTED_VLLM = "0.1.dev24216+g266e88c05"
SOURCE = Path("/tmp/maple_metrics_auth.py")

# Exact text the guard depends on, by file under the installed vllm package.
REQUIRED_SOURCE = {
    # How `--middleware` loads a class: added with add_middleware, no wrapping.
    "entrypoints/serve/middleware/register.py": (
        "for middleware in args.middleware:",
        "if inspect.isclass(imported):",
        "app.add_middleware(imported)",
    ),
    # Where Prometheus is served: every path that starts with /metrics.
    "entrypoints/serve/instrumentator/metrics.py": (
        'Mount("/metrics", make_asgi_app(registry=registry))',
        're.compile("^/metrics(?P<path>.*)$")',
    ),
    # vLLM's own bearer check does not cover /metrics, which is why this exists.
    "entrypoints/serve/middleware/authenticate.py": (
        'GUARDED_PREFIX = ("/v1", "/v2", "/inference", "/cohere")',
    ),
}


def main():
    installed = version("vllm")
    if installed != EXPECTED_VLLM:
        raise SystemExit(f"Expected vllm {EXPECTED_VLLM}, found {installed}")

    spec = importlib.util.find_spec("vllm")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("The vllm package is not importable by this interpreter")
    package = Path(next(iter(spec.submodule_search_locations)))

    for relative, needles in REQUIRED_SOURCE.items():
        text = (package / relative).read_text()
        for needle in needles:
            if text.count(needle) != 1:
                raise SystemExit(f"{relative} no longer contains exactly one {needle!r}")

    target = package.parent / SOURCE.name
    if target.exists():
        raise SystemExit(f"{target} already exists")
    shutil.copyfile(SOURCE, target)
    target.chmod(0o644)

    module = importlib.import_module("maple_metrics_auth")
    if Path(module.__file__).resolve() != target.resolve():
        raise SystemExit(f"Imported {module.__file__}, expected {target}")
    if not inspect.isclass(module.MetricsAuthMiddleware):
        raise SystemExit("MetricsAuthMiddleware must be a class")
    print(f"Installed {target} for vllm {installed}")


if __name__ == "__main__":
    main()
