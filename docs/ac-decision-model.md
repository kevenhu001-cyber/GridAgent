# Local AC candidate decision model (initial Phase 8)

This is an optional, offline, lightweight supervised ranking model, not a replacement for the AC solver. It uses existing NumPy and SciPy, family-weighted L2-regularized logistic regression, 26 fixed features (including missing indicators, base topology, measured margins, target class and authorized signed probe size). No LLM calls, new native simulations or additional dependencies. It learns from completed fixed AC diagnostic pools that are independently replayed; uncertain or version-mismatched observations are excluded rather than assigned negative labels. Positive labels require both the target and all selected snapshot checks to pass. Negative labels require observed violations. Features come from the original snapshot and authorized candidate, never candidate outcomes.

Train explicitly:

    python -m gridagent.ac_decision_train WORKSPACE SPLITS.json

SPLITS.json contains cases with study_id, family and split (train, validation, test). Up to 120 distinct fixed studies. Each declared family must be confined to one split; source report duplicates and cross-split model IDs or identical named topology fingerprints are rejected. The caller must group related network variants and renamed copies correctly; no guarantee of true independence from names or fingerprints. Training requires at least 12 labeled probes from at least three training families and both labels; all splits must have labeled records and the same native solver version.

The train split alone fits standardization and coefficients. The predeclared 0.8 score threshold is evaluated on validation; activation requires at least eight high-score validation families, no unknown validation outcomes, and a one-sided binomial lower-bound diagnostic of at least 0.5 for families where every selected prediction is correct. This diagnostic assumes independent families; it is not a guarantee, and logistic scores are not calibrated probabilities. Test metrics (coverage, precision, Brier score, family-level results) never affect fit or activation. No training on benchmark labels. The study persists evidence-derived dataset, authorization, feature schema, model coefficients, metrics and fingerprints as JSON. No executable model serialization.

Rank a reviewed candidate pool:

    python -m gridagent.ac_decision_train WORKSPACE --rank TRAINING_ID PROBE_POOL.json

The existing AC diagnostic authorization validates the pool. The ranker rebuilds the training dataset from verified evidence, refits and compares the stored artifact, and checks source snapshot evidence. It abstains if validation gate failed, native solver version differs, features lie outside the training envelope, or no candidate reaches threshold. Any result is advisory ordering only, not a new physical solution or authorization. The existing adaptive policy is unchanged; run separately authorized numerical experiments in either case, then whole-scope repair verification if eligible. There is no automatic injection of scores into experiment execution. Explicit model activation in the runtime, prospective independent evaluation, probability calibration and real timing comparisons remain future work.

Tests use constructed features and labels to verify mechanics, not engineering model accuracy. Real training requires sufficient local replayable studies; the repository does not ship a trained or validated model or report measured speedup.
