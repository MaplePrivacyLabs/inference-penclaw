# Performance experiments

Releases after v0.1.4 are throughput experiments on the staging node. The node
carries no customer traffic. v0.1.4 remains the release that equals the stock
Maple Kimi v0.0.3 configuration apart from the primary checkpoint fields.

`render_config.py` lists every difference from stock in `EXPERIMENT_EDITS` and
refuses to render a template that differs in any other way.

| Release | Change from the previous release | Why |
|---|---|---|
| v0.1.5 | `cpus` 32 to 112; `/metrics` added to the shim paths | The identical host class runs two 56-vCPU guests, so 32 vCPUs for eight GPUs looked low. vLLM's Prometheus metrics give running and waiting requests, token counters, latency histograms and speculative-decoding acceptance, which have never been readable on this node. |

`/metrics` is reachable without a key while `shim.authenticated` is false. It
exposes counters and histograms, not request content. Remove it again before
this configuration serves anyone.
