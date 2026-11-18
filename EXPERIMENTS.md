# Performance experiments

Releases after v0.1.4 are throughput experiments on the staging node. The node
carries no customer traffic. v0.1.4 remains the release that equals the stock
Maple Kimi v0.0.3 configuration apart from the primary checkpoint fields.

`render_config.py` lists every difference from stock in `EXPERIMENT_EDITS` and
refuses to render a template that differs in any other way.

| Release | Change from the previous release | Why |
|---|---|---|
| v0.1.5 | `cpus` 32 to 112; `/metrics` added to the shim paths. **Never deployed:** the platform accepts only 2, 4, 8, 16, 32, 56, 64, 120 or 128 vCPUs and rejected 112 at update planning | The identical host class runs two 56-vCPU guests, so 32 vCPUs for eight GPUs looked low. vLLM's Prometheus metrics give running and waiting requests, token counters, latency histograms and speculative-decoding acceptance, which have never been readable on this node. |
| v0.1.6 | `cpus` 120 in place of 112; otherwise v0.1.5 | Nearest accepted size above the 112 vCPUs that two DeepSeek guests use on the identical host class. |
| v0.1.7 | DSpark draft tokens 5 to 3 | On v0.1.6 the draft tokens were accepted 65%, 40%, 23%, 13% and 7% of the time by position: the fourth and fifth add about 0.2 tokens per step while every step carries a third more rows. Result on v0.1.6 for comparison: 128-134 tokens/s for one request, 549-603 at 8, 1,358-1,378 at 32. |
| v0.1.8 | `/v1/messages` and `/v1/messages/count_tokens` added to the shim paths | The published Terminal-Bench 4.1 result for Kimi K3.1 Pro was run with Claude Code, which speaks the Anthropic Messages format. vLLM already serves that format at this build; only the shim blocked the path. No engine setting changes. |

**Result of v0.1.7, and the configuration kept:** three draft tokens were faster at every level in the same clean test: 140-146 tokens/s for one request, 600-642 at 8, 1,568-1,612 at 32 (about 15% more than v0.1.6), and 1,493 at 32 with real prompts against 1,281. Tokens per step fell only from about 2.5 to about 2.25.

`/metrics` is reachable without a key while `shim.authenticated` is false. It
exposes counters and histograms, not request content. Remove it again before
this configuration serves anyone.
