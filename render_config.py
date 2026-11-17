"""Render or check the measured Tinfoil config for one completed schema-2 pack."""

import argparse
import json
from pathlib import Path
import re
from textwrap import indent


ROOT = Path(__file__).resolve().parent
REPO = "audnai/penclaw-Kimi-K3.1-pro-unrestricted"
REVISION = "781d40495beb276fc52d0afd470a5aad1fd5d1bf"
MPK_PATTERN = r"([0-9a-f]{64})_([1-9][0-9]*)_([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})"


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

    template = (ROOT / "tinfoil-config.template.yml").read_text()
    if template.count(f"repo: {REPO}@{REVISION}") != 1:
        raise ValueError("Config must pin the manifest revision")
    replacements = {
        "MPK": mpk,
        "ROOT": pack[1],
        "VERIFIER": indent((ROOT / "verify_snapshot.py").read_text().rstrip(), "    "),
        "SNAPSHOT": indent(json.dumps(manifest, indent=2), "      "),
    }
    for key, value in replacements.items():
        placeholder = f"__PENCLAW_{key}__"
        if template.count(placeholder) != 1:
            raise ValueError(f"Expected one config placeholder for {key}")
        template = template.replace(placeholder, value)
    return template


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mpk", metavar="ROOT_OFFSET_UUID", help="Tuple from the completed schema-2 wrap")
    mode.add_argument("--check", action="store_true", help="Check the generated config is renderer-exact")
    parser.add_argument("--output", type=Path, default=ROOT / "tinfoil-config.yml")
    args = parser.parse_args()
    try:
        if args.check:
            config = args.output.read_text()
            packs = re.findall(r'^    mpk: "([^"\n]+)"$', config, re.MULTILINE)
            if len(packs) != 1 or config != render(packs[0]):
                raise ValueError("Measured config must match a fresh render of the declared pack")
        else:
            args.output.write_text(render(args.mpk))
    except (KeyError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
