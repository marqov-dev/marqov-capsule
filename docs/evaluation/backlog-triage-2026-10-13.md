# Review backlog verification on 13 October 2026

Checked against main `2e6b8e6` (including released 0.2.1) and the evaluation
branch. The independent Node checker passes all 55 vectors; the full Python
suite, including eight harness checks, passes 1,195 tests with one skip.
Issue titles and older handovers are not sufficient evidence to close an issue.

| Issue | Verified status | Evidence and remaining work |
|---|---|---|
| #101 | Resolved | PR #129 corrected the four stale locations; #133 updated the rehearsal pin to 0.2.1. RELEASING.md describes the single version source; spec section 6 and the policy test docstring describe `compare`. Historical tags remain historical. |
| #120 | Resolved | PR #130's `checkTag` resolves explicit finite floats, `decode` uses fatal UTF-8 decoding, and canonical strings reject unpaired surrogates. Accept/reject vectors cover these cases and pass in Node. The file explicitly identifies itself as a corpus checker, not a production capsule reader. |
| #119 | Partly resolved; keep open | PR #130 added JSON-profile rules and vectors for encodings, mappings, aliases, explicit tags and typed keys. The issue also lists raw YAML line-break/printability/directive and escaped-surrogate-pair differences; those rows are not all represented in the shipped edge corpus and are not established resolved by 55 passing vectors. |
| #118 | Partly resolved; keep open | The symlink fixture now first proves an intact seal opens; malformed-ID vs real mismatch and validation/dry-run assertions are corrected. `_rewrite_checksums` in test_tamper_evidence.py still writes legacy YAML checksums. The requested lifecycle-policy decision and exhaustive legacy-fixture migration are not established complete. |
| #115 | Partly resolved; keep open | release.yml gates build on its test job, workflow permissions are explicit, and macOS/Windows CI legs exist. Major action tags remain floating, 3.13/3.14 are absent from the CI matrix, and the separate fixture-validation block remains. A local 3.13 pass is not a CI matrix change. |

Do not close epic #91 or the broader old epics merely because the release shipped.
Other open issues, including schema strictness, scanner specification wording,
platform integration, signatures and statistical documentation, require their
own evidence or product decisions. This evaluation changes no manifest schema,
public package behavior, platform integration or release policy.
