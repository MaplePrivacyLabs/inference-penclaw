# Penclaw Kimi K3.1 Pro staging

The v0.1.4 configuration serves Audn's Penclaw checkpoint using the
[Maple Kimi v0.0.3 configuration](https://github.com/MaplePrivacyLabs/inference-kimi-k3-1-pro/blob/06a62d7829bdb30237846544874830a86305e9f8/tinfoil-config.yml).
It changes the primary checkpoint repository and revision, Modelwrap tuple,
pack schema, and vLLM model path. It uses the same eight B300 GPUs, serving
image, Inferact DSpark draft, and native vLLM bearer authentication. The
`kimi-k3-1-pro` API model name is retained for compatibility. The signed
Penclaw release identifies the actual checkpoint served under that name.

The [snapshot manifest](snapshot-manifest.json) records the exact Audn checkpoint
revision and Hugging Face's checksums. The measured configuration pins each
checkpoint revision, Modelwrap tuple, and schema, along with the serving image
digest. The guest mounts the packs read-only and `dm-verity` authenticates
blocks as they are read against the pinned pack roots. Auditors can compare
the manifest's file hashes when independently validating the gated snapshot.
[Pinned Hugging Face metadata](https://huggingface.co/api/models/audnai/penclaw-Kimi-K3.1-pro-unrestricted/revision/781d40495beb276fc52d0afd470a5aad1fd5d1bf?blobs=true) ·
[Tinfoil model weight verification](https://docs.tinfoil.sh/containers/models)

## Verify a release

1. Read `tinfoil-config.yml` at the published tag and check the primary and
   draft checkpoint revisions, Modelwrap tuples and schemas, runtime image
   digest, and paths passed to `--model` and `--speculative-config`.
2. Verify the signed deployment artifacts and use the Tinfoil CLI with the exact
   release tag and deployment digest to verify the live enclave and TLS key.
3. Auditors with Hugging Face access can download the pinned snapshot, verify its
   files, rebuild the schema-2 pack, and compare its root with the measured config.

The release, pack commitment, and snapshot manifest are public. Audn approval
is required to download the primary tensor bytes and independently reproduce
that commitment. The checkpoint is distributed under the Kimi K3.1-Pro license.
[Checkpoint license](https://huggingface.co/audnai/penclaw-Kimi-K3.1-pro-unrestricted/blob/781d40495beb276fc52d0afd470a5aad1fd5d1bf/LICENSE) ·
[Modelwrap reproduction](https://docs.tinfoil.sh/containers/models#reproducing-a-pack)

## Prepare the measured configuration

Pass the full `root_offset_uuid` tuple from the completed schema-2 wrap to
`python3 render_config.py --mpk TUPLE`. Run `python3 render_config.py --check`
before publishing. The renderer verifies that the template matches the pinned
stock configuration outside the four primary pack fields. The release workflow
checks the rendered config on the default branch and at the release tag before
measuring it.
