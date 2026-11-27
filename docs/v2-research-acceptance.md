# V2 research acceptance

The full prospective campaign reserves 39 DC solves and 273 AC runs across the frozen 13 synthetic topology families. Run in a fresh research workspace with the engineering extra:

    pip install -e '.[dev,engineering]'
    python scripts/run_v2_research.py ./research-v2 ./research-reports

The plan ID is written before execution; recover using --resume-collection ID. Only replay-verified eligible studies can contribute labels. Validation, test and train are predeclared by family. The validation gate may abstain; do not lower its threshold after observing test performance. Reports include native collection counts, public AC screening, training diagnostics and held-out replay against fixed and adaptive baselines. Learned ordering is only tested if enabled; abstentions fall back to the adaptive policy. Replay counts are projected, not online speedups. The public cases are screening, not reference-solution acceptance. This campaign is synthetic, not an independent population of real grids.

Remaining gates: independent IEEE reference solutions, expanded AC generator contingency modeling, dynamic controller tuning, native elapsed-time comparisons, matched pure-LLM and hybrid trials, real Windows interactive QA, signed release. Do not mark these completed on the basis of this campaign.
