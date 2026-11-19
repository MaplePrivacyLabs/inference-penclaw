# Differences from stock

v0.1.4 equals the stock Maple Kimi v0.0.3 configuration apart from the primary
checkpoint fields. Every later difference is listed here.

`render_config.py` lists every difference from stock in `EDITS` and refuses to
render a template that differs in any other way.

## Current configuration (v0.2.0 onwards)

| Difference from stock | Why |
|---|---|
| `cpus` 120 instead of 32 | The host is already paid for. Measured throughput is unchanged up to 32 concurrent requests. |
| Three DSpark draft tokens instead of five | About 15% more output at 32 concurrent requests in the same clean test (see v0.1.7 below). |
| Image built by this repository from Tinfoil's image | The [Dockerfile](Dockerfile) adds one file, [`maple_metrics_auth.py`](maple_metrics_auth.py), and changes nothing else. The build fails if the base image's vLLM is not the build the guard was written against. |
| `--middleware maple_metrics_auth.MetricsAuthMiddleware` | Loads the guard. It requires the `METRICS_API_KEY` bearer on every path under `/metrics` and passes all other requests through untouched. |
| Served model name `kimi-k3-1-pro-uncensored` instead of `kimi-k3-1-pro` | The node serves Audn's abliterated checkpoint, so it answers under a name that says so. Maple offers it as a separate model beside the stock Kimi K3.1 Pro. |
| `/metrics` in the shim paths | vLLM's Prometheus metrics (queue, cache, latency, token and speculative-decoding counters) become readable with the metrics key. Without the guard this path would be open: vLLM's own bearer check does not cover it, and the shim's only gate for it is Tinfoil's online admin-key validator. |

The same key already protects the shim's own `/.well-known/tinfoil-metrics` and
`/.well-known/metrics`. Metrics are counters and histograms; they contain no
request content.

## Release history

| Release | Change from the previous release | Why |
|---|---|---|
| v0.1.5 | `cpus` 32 to 112; `/metrics` added to the shim paths. **Never deployed:** the platform accepts only 2, 4, 8, 16, 32, 56, 64, 120 or 128 vCPUs and rejected 112 at update planning | The identical host class runs two 56-vCPU guests, so 32 vCPUs for eight GPUs looked low. vLLM's Prometheus metrics give running and waiting requests, token counters, latency histograms and speculative-decoding acceptance, which have never been readable on this node. |
| v0.1.6 | `cpus` 120 in place of 112; otherwise v0.1.5 | Nearest accepted size above the 112 vCPUs that two DeepSeek guests use on the identical host class. |
| v0.1.7 | DSpark draft tokens 5 to 3 | On v0.1.6 the draft tokens were accepted 65%, 40%, 23%, 13% and 7% of the time by position: the fourth and fifth add about 0.2 tokens per step while every step carries a third more rows. Result on v0.1.6 for comparison: 128-134 tokens/s for one request, 549-603 at 8, 1,358-1,378 at 32. |
| v0.1.8 | `/v1/messages` and `/v1/messages/count_tokens` added to the shim paths | The published Terminal-Bench 4.1 result for Kimi K3.1 Pro was run with Claude Code, which speaks the Anthropic Messages format. vLLM already serves that format at this build; only the shim blocked the path. No engine setting changes. |
| v0.2.0 | Image built here with the metrics guard, loaded by `--middleware`; served model name `kimi-k3-1-pro-uncensored`; `/v1/messages` and `/v1/messages/count_tokens` removed from the shim paths again | First release meant to serve customers. `/metrics` needs the metrics key from this release on. The Anthropic Messages paths were only needed for the benchmark run. |

**Result of v0.1.7, and the configuration kept:** three draft tokens were faster at every level in the same clean test: 140-146 tokens/s for one request, 600-642 at 8, 1,568-1,612 at 32 (about 15% more than v0.1.6), and 1,493 at 32 with real prompts against 1,281. Tokens per step fell only from about 2.5 to about 2.25.

In v0.1.6 to v0.1.8 `/metrics` was reachable without a key. Those releases were
staging experiments and carried no customer traffic.
