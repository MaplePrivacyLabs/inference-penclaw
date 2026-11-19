"""The image, the measured configuration and the metrics guard must agree with each other."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import render_config  # noqa: E402

CONFIG = (ROOT / "tinfoil-config.yml").read_text()
TEMPLATE = (ROOT / "tinfoil-config.template.yml").read_text()


def block(text, key):
    """The list items under a top-level-or-nested `key:` line, in order."""
    match = re.search(rf"^( *){re.escape(key)}:\n((?:\1 *- .*\n)+)", text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"No list under {key!r}")
    return [line.strip()[2:] for line in match.group(2).splitlines()]


class ReleaseInputs(unittest.TestCase):
    def test_image_is_built_from_the_stock_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertEqual(re.findall(r"^FROM (\S+)$", dockerfile, re.MULTILINE), [render_config.STOCK_IMAGE])

    def test_image_adds_only_the_guard(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        instructions = [line.split()[0] for line in dockerfile.splitlines() if line and line[0].isalpha()]
        self.assertEqual(instructions, ["FROM", "COPY", "RUN"])
        ignore = (ROOT / ".dockerignore").read_text().split()
        self.assertEqual(ignore, ["**", "!Dockerfile", "!maple_metrics_auth.py", "!scripts/", "!scripts/install_metrics_auth.py"])

    def test_source_names_exactly_one_unpinned_image_of_ours(self):
        for text in (CONFIG, TEMPLATE):
            self.assertEqual(re.findall(r'^ *image: "([^"]+)"', text, re.MULTILINE), [f"{render_config.IMAGE}:build-required"])

    def test_public_paths(self):
        self.assertEqual(
            block(CONFIG, "  paths"),
            ["/v1/chat/completions", "/v1/models", "/v1/responses", "/health", "/metrics"],
        )

    def test_metrics_is_public_only_with_the_guard_and_its_key(self):
        command = block(CONFIG, "  command")
        index = command.index("--middleware")
        self.assertEqual(command[index + 1], "maple_metrics_auth.MetricsAuthMiddleware")
        self.assertEqual(command.count("--middleware"), 1)
        self.assertEqual(block(CONFIG, "  secrets"), ["VLLM_API_KEY", "METRICS_API_KEY"])
        # The guard is Python middleware, so the Python API server must stay selected.
        self.assertIn("  - VLLM_USE_RUST_FRONTEND: '0'\n", CONFIG)

    def test_served_model_name(self):
        command = block(CONFIG, "  command")
        self.assertEqual(command[command.index("--served-model-name") + 1], "kimi-k3-1-pro-uncensored")
        self.assertEqual(command.count("--served-model-name"), 1)

    def test_installer_expects_the_stock_vllm_build(self):
        installer = (ROOT / "scripts" / "install_metrics_auth.py").read_text()
        self.assertIn('EXPECTED_VLLM = "0.1.dev24216+g266e88c05"', installer)


if __name__ == "__main__":
    unittest.main()
