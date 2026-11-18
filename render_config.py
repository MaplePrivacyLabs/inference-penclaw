"""Render the stock Kimi configuration with the Penclaw primary pack."""

import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
REPO = "audnai/penclaw-Kimi-K3.1-pro-unrestricted"
REVISION = "781d40495beb276fc52d0afd470a5aad1fd5d1bf"
MPK_PATTERN = r"([0-9a-f]{64})_([1-9][0-9]*)_([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})"
STOCK_REPO = "moonshotai/Kimi-K3.1-Pro@6d0a0202956796543364d666ab19c6ad1a494ee1"
STOCK_MPK = "8d9c355a94e60f43598713759028328bbe795336f2700799d0ff4f3898e785e0_1561355993088_97fb42e4-45a9-5745-813b-61cb6ddb043d"
STOCK_CONFIG_SHA256 = "2400260beabc0fe45b1c959a29c1401fbd703d6b233efa7de883eccba29de68b"
# Performance experiments on the staging node (see EXPERIMENTS.md). Each entry is
# (text in stock v0.0.3, text in this template). Undoing every entry must give
# back the stock configuration exactly, so the template can only differ from
# stock in the ways listed here and in the primary model fields.
EXPERIMENT_EDITS = [
    ("cpus: 32\n", "cpus: 120\n"),
    ("  - /health\n", "  - /health\n  - /metrics\n"),
    ('"num_speculative_tokens":5', '"num_speculative_tokens":3'),
    ("  - /v1/responses\n", "  - /v1/responses\n  - /v1/messages\n  - /v1/messages/count_tokens\n"),
]


def render(mpk):
    pack = re.fullmatch(MPK_PATTERN, mpk)
    if not pack or int(pack[2]) % 4096 != 0:
        raise ValueError("Expected Modelwrap root, block-aligned offset and verity UUID")

    manifest = json.loads((ROOT / "snapshot-manifest.json").read_text())
    if (manifest["repo"], manifest["revision"]) != (REPO, REVISION):
        raise ValueError("Checkpoint manifest has the wrong repository or revision")
    files = manifest["files"]
    shards = [entry for name, entry in files.items() if name.endswith(".safetensors")]
    if len(files) != 112 or len(shards) != 96 or sum(file["size"] for file in shards) != 1_561_293_163_576:
        raise ValueError("Checkpoint manifest has the wrong file inventory")
    for name, entry in files.items():
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in {".", ".."} or entry["size"] < 0:
            raise ValueError(f"Invalid checkpoint file metadata: {name}")
        if "sha256" in entry or name.endswith(".safetensors"):
            valid_digest = re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", ""))
        else:
            valid_digest = re.fullmatch(r"[0-9a-f]{40}", entry.get("git-blob-sha1", ""))
        if not valid_digest:
            raise ValueError(f"Invalid checkpoint file digest: {name}")
    if int(pack[2]) < sum(entry["size"] for entry in files.values()):
        raise ValueError("Modelwrap offset is smaller than this checkpoint")

    template = (ROOT / "tinfoil-config.template.yml").read_bytes().decode("utf-8")
    stock = template
    for stock_text, experiment_text in EXPERIMENT_EDITS:
        if stock.count(experiment_text) != 1:
            raise ValueError(f"Expected one experiment edit matching {experiment_text!r}")
        stock = stock.replace(experiment_text, stock_text)
    stock_values = {
        f"repo: {REPO}@{REVISION}": f"repo: {STOCK_REPO}",
        "mpk: __PENCLAW_MPK__\n  schema: 2": f"mpk: {STOCK_MPK}\n  schema: 1",
        "__PENCLAW_ROOT__": STOCK_MPK.split("_", 1)[0],
    }
    for marker, value in stock_values.items():
        if stock.count(marker) != 1:
            raise ValueError(f"Expected one primary model field matching {marker!r}")
        stock = stock.replace(marker, value)
    if hashlib.sha256(stock.encode("utf-8")).hexdigest() != STOCK_CONFIG_SHA256:
        raise ValueError("Template differs from stock v0.0.3 outside the primary model fields and the listed experiment edits")

    return template.replace("__PENCLAW_MPK__", mpk).replace("__PENCLAW_ROOT__", pack[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mpk", metavar="ROOT_OFFSET_UUID", help="Tuple from the completed schema-2 wrap")
    mode.add_argument("--check", action="store_true", help="Check the generated config is renderer-exact")
    parser.add_argument("--output", type=Path, default=ROOT / "tinfoil-config.yml")
    args = parser.parse_args()
    try:
        if args.check:
            config = args.output.read_bytes().decode("utf-8")
            packs = re.findall(r"^  mpk: (\S+)$", config, re.MULTILINE)
            if len(packs) != 2 or config != render(packs[0]):
                raise ValueError("Measured config must match the rendered primary and stock draft packs")
        else:
            args.output.write_bytes(render(args.mpk).encode("utf-8"))
    except (KeyError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
