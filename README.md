# Penclaw Kimi K3.1 Pro staging

This repository defines a dedicated Tinfoil staging deployment, based on the
[Tinfoil Kimi v0.0.3 runtime](https://github.com/tinfoilsh/confidential-kimi-k3-1-pro/tree/v0.0.3).
The template uses one confidential VM with eight B300 GPUs and an authenticated
vLLM endpoint.

The [snapshot manifest](snapshot-manifest.json) records the exact Audn checkpoint
revision and Hugging Face's checksums. The measured configuration pins the
schema-2 Modelwrap pack and the serving image digest. Its entrypoint checks
every mounted file before starting vLLM. The mount uses `dm-verity` to verify
disk reads against the pinned pack root. [Pinned Hugging Face metadata](https://huggingface.co/api/models/audnai/penclaw-Kimi-K3.1-pro-unrestricted/revision/781d40495beb276fc52d0afd470a5aad1fd5d1bf?blobs=true)

## Verify a release

1. Read `tinfoil-config.yml` at the published tag and check the checkpoint,
   Modelwrap schema and root, runtime image digest, and `--model` path.
2. Verify the signed deployment artifacts and use the Tinfoil CLI with the exact
   release tag and deployment digest to verify the live enclave and TLS key.
3. Auditors with Hugging Face access can download the pinned snapshot, verify its
   files, rebuild the schema-2 pack, and compare its root with the measured config.

Audn controls access to the checkpoint files. The checkpoint is distributed under
the [Kimi K3.1-Pro license](https://huggingface.co/audnai/penclaw-Kimi-K3.1-pro-unrestricted/blob/781d40495beb276fc52d0afd470a5aad1fd5d1bf/LICENSE).
The [Tinfoil Modelwrap documentation](https://docs.tinfoil.sh/containers/models#reproducing-a-pack)
explains how to reproduce the pack.

## Prepare the measured configuration

Pass the full `root_offset_uuid` tuple from the completed schema-2 wrap to
`python3 render_config.py --mpk TUPLE`. Run `python3 render_config.py --check`
before publishing. The release workflow checks the rendered config on the
default branch and again on the release tag before measuring it.
