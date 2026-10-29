# Evaluation Report

## Run configuration

- Prediction source: `D:\orchestrate\orchestrate oct\hackerrank-orchestrate-october26\output.csv`.
- Evaluation intent mode: `classified` (forced deletion decisions: 0; cases reaching policy: 0).
- The assume-deletion override is implemented only by this evaluator; it is not wired into the run command.

## a) Full metrics

- Case status accuracy: **0/32 (0.0%)**.
- Exact row accuracy: **0/32 (0.0%)**.
- Step-set accuracy (Jaccard, including evidence_id): **0/193 (0.0%)**.
- Field macro accuracy: **0.0%**.
- Sequence accuracy: **0/32 (0.0%)**.

## b) Ignoring evidence_id

- Step-set accuracy: **0/193 (0.0%)**.
- Sequence accuracy: **0/32 (0.0%)**.

## c) Linked-only view

Expected steps are retained only when the resource has an identity-matched parsed Fact or an explicit/evidence-adjacent identity link; timestamp-only anchors do not qualify.
- Linked-only step-set accuracy: **0/161 (0.0%)**.
- Linked-only sequence accuracy: **4/32 (12.5%)**.
- Exact rows among cases whose expected resources are all linked: **0/10 (0.0%)**.

## d) Status accuracy and confusion

| Expected status | Correct | Cases | Accuracy |
|---|---:|---:|---:|
| COMPLETE | 0 | 10 | 0.0% |
| INCOMPLETE | 0 | 22 | 0.0% |

### 2×2 expected-vs-predicted confusion table

| Expected \ Predicted | COMPLETE | INCOMPLETE |
|---|---:|---:|
| COMPLETE | 0 | 0 |
| INCOMPLETE | 0 | 0 |
- Predicted NOT_APPLICABLE or missing status outside the 2×2: 32 (case_01, case_02, case_03, case_04, case_05, case_06, case_07, case_08, case_09, case_10, case_11, case_12, case_13, case_14, case_15, case_16, case_17, case_18, case_19, case_20, case_21, case_22, case_23, case_24, case_25, case_26, case_27, case_28, case_29, case_30, case_31, case_32).

## Field breakdown on shared resources

Only resources present in both expected and predicted step lists are compared. Steps are aligned in local sequence order within each resource; unmatched positions count incorrect.

| Field | Correct | Compared | Accuracy |
|---|---:|---:|---:|
| `phase` | 0 | 0 | 100.0% |
| `system_id` | 0 | 0 | 100.0% |
| `resource_id` | 0 | 0 | 100.0% |
| `operation` | 0 | 0 | 100.0% |
| `state` | 0 | 0 | 100.0% |
| `evidence_id` | 0 | 0 | 100.0% |

## Per-case diagnostic table

| Case | Expected status | Predicted status | Expected findings | Predicted findings |
|---|---|---|---:|---:|
| case_01 | COMPLETE | <MISSING> | 0 | 0 |
| case_02 | COMPLETE | <MISSING> | 0 | 0 |
| case_03 | COMPLETE | <MISSING> | 0 | 0 |
| case_04 | COMPLETE | <MISSING> | 0 | 0 |
| case_05 | INCOMPLETE | <MISSING> | 1 | 0 |
| case_06 | INCOMPLETE | <MISSING> | 1 | 0 |
| case_07 | INCOMPLETE | <MISSING> | 1 | 0 |
| case_08 | INCOMPLETE | <MISSING> | 1 | 0 |
| case_09 | INCOMPLETE | <MISSING> | 1 | 0 |
| case_10 | INCOMPLETE | <MISSING> | 1 | 0 |
| case_11 | INCOMPLETE | <MISSING> | 4 | 0 |
| case_12 | INCOMPLETE | <MISSING> | 1 | 0 |
| case_13 | INCOMPLETE | <MISSING> | 2 | 0 |
| case_14 | INCOMPLETE | <MISSING> | 1 | 0 |
| case_15 | INCOMPLETE | <MISSING> | 1 | 0 |
| case_16 | INCOMPLETE | <MISSING> | 2 | 0 |
| case_17 | INCOMPLETE | <MISSING> | 1 | 0 |
| case_18 | INCOMPLETE | <MISSING> | 4 | 0 |
| case_19 | INCOMPLETE | <MISSING> | 2 | 0 |
| case_20 | INCOMPLETE | <MISSING> | 2 | 0 |
| case_21 | COMPLETE | <MISSING> | 0 | 0 |
| case_22 | INCOMPLETE | <MISSING> | 2 | 0 |
| case_23 | INCOMPLETE | <MISSING> | 2 | 0 |
| case_24 | INCOMPLETE | <MISSING> | 2 | 0 |
| case_25 | COMPLETE | <MISSING> | 0 | 0 |
| case_26 | COMPLETE | <MISSING> | 0 | 0 |
| case_27 | COMPLETE | <MISSING> | 0 | 0 |
| case_28 | COMPLETE | <MISSING> | 0 | 0 |
| case_29 | INCOMPLETE | <MISSING> | 4 | 0 |
| case_30 | INCOMPLETE | <MISSING> | 4 | 0 |
| case_31 | COMPLETE | <MISSING> | 0 | 0 |
| case_32 | INCOMPLETE | <MISSING> | 1 | 0 |

### Findings diagnostics for wrong-status cases

#### case_01 — expected COMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - none
- FALSE FINDINGS:
  - none

#### case_02 — expected COMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - none
- FALSE FINDINGS:
  - none

#### case_03 — expected COMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - none
- FALSE FINDINGS:
  - none

#### case_04 — expected COMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - none
- FALSE FINDINGS:
  - none

#### case_05 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `account_service/account_005` REPORT_REMAINING_RECORD (evidence `evidence_54`): **snapshot selection** — resolved Fact/evidence evidence_54 differs from expected evidence_54.
- FALSE FINDINGS:
  - none

#### case_06 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `search_service/search_001` REPORT_REMAINING_RECORD (evidence `evidence_57`): **snapshot selection** — resolved Fact/evidence evidence_57 differs from expected evidence_57.
- FALSE FINDINGS:
  - none

#### case_07 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `support_platform/support_001` REPORT_REMAINING_RECORD (evidence `evidence_58`): **resource not in ledger** — no parsed Fact exists for support_platform/support_001 at audit_at.
- FALSE FINDINGS:
  - none

#### case_08 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `export_service/export_001` REPORT_REMAINING_RECORD (evidence `evidence_59`): **snapshot selection** — resolved Fact/evidence evidence_59 differs from expected evidence_59.
- FALSE FINDINGS:
  - none

#### case_09 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `backup_service/backup_4978` REPORT_RESTORE_RISK (evidence `evidence_93`): **snapshot selection** — resolved Fact/evidence evidence_93 differs from expected evidence_93.
- FALSE FINDINGS:
  - none

#### case_10 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `support_platform/support_002` REPORT_REMAINING_RECORD (evidence `evidence_61`): **policy mapping** — resolved finding REPORT_EXPOSED_PII differs from expected REPORT_REMAINING_RECORD.
- FALSE FINDINGS:
  - none

#### case_11 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `search_service/search_052` REPORT_REMAINING_RECORD (evidence `evidence_03`): **snapshot selection** — resolved Fact/evidence evidence_03 differs from expected evidence_03.
  - `analytics_platform/analytics_2034` REPORT_EXPOSED_PII (evidence `evidence_03`): **snapshot selection** — resolved Fact/evidence evidence_03 differs from expected evidence_03.
  - `support_platform/support_864` REPORT_EXPOSED_PII (evidence `evidence_03`): **snapshot selection** — resolved Fact/evidence evidence_03 differs from expected evidence_03.
  - `integration_service/data_flow_9522` REPORT_ACTIVE_DATA_FLOW (evidence `evidence_03`): **snapshot selection** — resolved Fact/evidence evidence_03 differs from expected evidence_03.
- FALSE FINDINGS:
  - none

#### case_12 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `analytics_platform/analytics_9914` REPORT_REMAINING_RECORD (evidence `evidence_01`): **policy mapping** — resolved finding REPORT_EXPOSED_PII differs from expected REPORT_REMAINING_RECORD.
- FALSE FINDINGS:
  - none

#### case_13 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `search_service/search_1308` REPORT_REMAINING_RECORD (evidence `evidence_03`): **snapshot selection** — resolved Fact/evidence evidence_03 differs from expected evidence_03.
  - `support_platform/support_4218` REPORT_REMAINING_RECORD (evidence `evidence_03`): **snapshot selection** — resolved Fact/evidence evidence_03 differs from expected evidence_03.
- FALSE FINDINGS:
  - none

#### case_14 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `backup_service/backup_3870` REPORT_RESTORE_RISK (evidence `evidence_03`): **snapshot selection** — resolved Fact/evidence evidence_03 differs from expected evidence_03.
- FALSE FINDINGS:
  - none

#### case_15 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `integration_service/data_flow_9846` REPORT_ACTIVE_DATA_FLOW (evidence `evidence_01`): **snapshot selection** — resolved Fact/evidence evidence_01 differs from expected evidence_01.
- FALSE FINDINGS:
  - none

#### case_16 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `account_service/account_994` REPORT_REMAINING_RECORD (evidence `evidence_05`): **snapshot selection** — resolved Fact/evidence evidence_05 differs from expected evidence_05.
  - `search_service/search_1007` REPORT_REMAINING_RECORD (evidence `evidence_05`): **snapshot selection** — resolved Fact/evidence evidence_05 differs from expected evidence_05.
- FALSE FINDINGS:
  - none

#### case_17 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `backup_service/backup_3245` REPORT_RESTORE_RISK (evidence `evidence_01`): **snapshot selection** — resolved Fact/evidence evidence_01 differs from expected evidence_01.
- FALSE FINDINGS:
  - none

#### case_18 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `search_service/search_4013` REPORT_REMAINING_RECORD (evidence `evidence_94`): **snapshot selection** — resolved Fact/evidence evidence_94 differs from expected evidence_94.
  - `analytics_platform/analytics_037` REPORT_EXPOSED_PII (evidence `evidence_94`): **snapshot selection** — resolved Fact/evidence evidence_94 differs from expected evidence_94.
  - `support_platform/support_5569` REPORT_EXPOSED_PII (evidence `evidence_94`): **snapshot selection** — resolved Fact/evidence evidence_94 differs from expected evidence_94.
  - `integration_service/data_flow_4890` REPORT_ACTIVE_DATA_FLOW (evidence `evidence_94`): **snapshot selection** — resolved Fact/evidence evidence_94 differs from expected evidence_94.
- FALSE FINDINGS:
  - none

#### case_19 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `search_service/search_6083` REPORT_REMAINING_RECORD (evidence `evidence_01`): **snapshot selection** — resolved Fact/evidence evidence_01 differs from expected evidence_01.
  - `support_platform/support_9553` REPORT_EXPOSED_PII (evidence `evidence_01`): **snapshot selection** — resolved Fact/evidence evidence_01 differs from expected evidence_01.
- FALSE FINDINGS:
  - none

#### case_20 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `search_service/search_4262` REPORT_REMAINING_RECORD (evidence `evidence_94`): **snapshot selection** — resolved Fact/evidence evidence_94 differs from expected evidence_94.
  - `integration_service/data_flow_1770` REPORT_ACTIVE_DATA_FLOW (evidence `evidence_94`): **snapshot selection** — resolved Fact/evidence evidence_94 differs from expected evidence_94.
- FALSE FINDINGS:
  - none

#### case_21 — expected COMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - none
- FALSE FINDINGS:
  - none

#### case_22 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `search_service/search_8911` REPORT_REMAINING_RECORD (evidence `evidence_05`): **snapshot selection** — resolved Fact/evidence evidence_05 differs from expected evidence_05.
  - `analytics_platform/analytics_4440` REPORT_EXPOSED_PII (evidence `evidence_05`): **snapshot selection** — resolved Fact/evidence evidence_05 differs from expected evidence_05.
- FALSE FINDINGS:
  - none

#### case_23 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `export_service/export_7364` REPORT_REMAINING_RECORD (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
  - `search_service/search_898` REPORT_REMAINING_RECORD (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
- FALSE FINDINGS:
  - none

#### case_24 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `account_service/account_5334` REPORT_REMAINING_RECORD (evidence `evidence_92`): **snapshot selection** — expected cited file evidence_92, resolver selected evidence_51.
  - `search_service/search_5577` REPORT_REMAINING_RECORD (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
- FALSE FINDINGS:
  - none

#### case_25 — expected COMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - none
- FALSE FINDINGS:
  - none

#### case_26 — expected COMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - none
- FALSE FINDINGS:
  - none

#### case_27 — expected COMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - none
- FALSE FINDINGS:
  - none

#### case_28 — expected COMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - none
- FALSE FINDINGS:
  - none

#### case_29 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `search_service/search_1993` REPORT_REMAINING_RECORD (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
  - `analytics_platform/analytics_5208` REPORT_EXPOSED_PII (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
  - `support_platform/support_5281` REPORT_EXPOSED_PII (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
  - `integration_service/data_flow_3827` REPORT_ACTIVE_DATA_FLOW (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
- FALSE FINDINGS:
  - none

#### case_30 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `search_service/search_9359` REPORT_REMAINING_RECORD (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
  - `analytics_platform/analytics_3697` REPORT_EXPOSED_PII (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
  - `support_platform/support_6477` REPORT_EXPOSED_PII (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
  - `integration_service/data_flow_8524` REPORT_ACTIVE_DATA_FLOW (evidence `evidence_92`): **snapshot selection** — resolved Fact/evidence evidence_92 differs from expected evidence_92.
- FALSE FINDINGS:
  - none

#### case_31 — expected COMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - none
- FALSE FINDINGS:
  - none

#### case_32 — expected INCOMPLETE, predicted <MISSING>
- MISSED FINDINGS:
  - `identity_service/tombstone_9178` REPORT_EXPOSED_PII (evidence `evidence_51`): **snapshot selection** — resolved Fact/evidence evidence_51 differs from expected evidence_51.
- FALSE FINDINGS:
  - none

## Failure causes

| Cause | Cases | Case IDs |
|---|---:|---|
| identity | 22 | case_01, case_02, case_03, case_04, case_07, case_08, case_10, case_12, case_17, case_18, case_20, case_21, case_22, case_23, case_25, case_26, case_27, case_28, case_29, case_30, case_31, case_32 |
| missing finding | 22 | case_05, case_06, case_07, case_08, case_09, case_10, case_11, case_12, case_13, case_14, case_15, case_16, case_17, case_18, case_19, case_20, case_22, case_23, case_24, case_29, case_30, case_32 |
| extra finding | 0 | — |
| wrong evidence_id | 0 | — |
| wrong operation | 0 | — |
| ordering | 0 | — |
| scope | 28 | case_03, case_05, case_06, case_08, case_09, case_10, case_11, case_12, case_13, case_14, case_15, case_16, case_17, case_18, case_19, case_20, case_21, case_22, case_23, case_24, case_25, case_26, case_27, case_28, case_29, case_30, case_31, case_32 |

## Custom evaluation cases

- Intent accuracy: 24/24 (100.0%).

| ID | Expected | Predicted | Source | Result |
|---|---|---|---|---|
| nondeletion_01 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| nondeletion_02 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| nondeletion_03 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| nondeletion_04 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| nondeletion_05 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| nondeletion_06 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| nondeletion_07 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| nondeletion_08 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| nondeletion_09 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| nondeletion_10 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| deletion_variant_01 | COMPLETE_OR_INCOMPLETE_DELETION | DELETION_REQUESTED | TEMPLATE | PASS |
| deletion_variant_02 | COMPLETE_OR_INCOMPLETE_DELETION | DELETION_REQUESTED | TEMPLATE | PASS |
| deletion_variant_03 | COMPLETE_OR_INCOMPLETE_DELETION | DELETION_REQUESTED | TEMPLATE | PASS |
| deletion_variant_04 | COMPLETE_OR_INCOMPLETE_DELETION | DELETION_REQUESTED | TEMPLATE | PASS |
| deletion_variant_05 | COMPLETE_OR_INCOMPLETE_DELETION | DELETION_REQUESTED | TEMPLATE | PASS |
| negation_01 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| negation_02 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| negation_03 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| negation_04 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| negation_05 | NOT_APPLICABLE | NOT_APPLICABLE | NEGATION | PASS |
| perturb_old_email_only_case10 | COMPLETE_OR_INCOMPLETE_DELETION | DELETION_REQUESTED | TEMPLATE | PASS |
| perturb_flow_disabled_case11 | COMPLETE_OR_INCOMPLETE_DELETION | DELETION_REQUESTED | TEMPLATE | PASS |
| perturb_missing_system_snapshot_case05 | COMPLETE_OR_INCOMPLETE_DELETION | DELETION_REQUESTED | TEMPLATE | PASS |
| perturb_tombstone_phone_case32 | COMPLETE_OR_INCOMPLETE_DELETION | DELETION_REQUESTED | TEMPLATE | PASS |

### Intent sources before evaluation override

- TEMPLATE: 32

## Metric definitions

Full step-set is a micro Jaccard score over per-case sets of (phase, system_id, resource_id, operation, state, evidence_id). The evidence-free view removes evidence_id from those tuples. Sequence uses ordered tuples and excludes step_no. Full field macro averages positional accuracy for each serialized field plus deletion_status; the shared-resource breakdown compares fields only on resource keys appearing on both sides. Linked-only exact rows filter both step arrays to linked resources and renumber the filtered arrays. Status confusion lists COMPLETE/INCOMPLETE; predicted NOT_APPLICABLE and missing statuses are enumerated separately.
