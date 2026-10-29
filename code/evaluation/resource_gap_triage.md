# Missing resource triage

The table contains the 17 expected (case, system, resource) triples with no exact resource Fact plus the 36 verification-only triples that have no sample evidence ID; 40 unique rows after overlap. Raw matching uses complete identifier boundaries, so `account_410` does not match `account_41038` and `audit_record_987` does not match `audit_record_9878`. Cached PNG/PDF parser extractions were searched alongside SQL/JSON/LOG/TXT text.

Classification counts: PARSER_GAP=0, ABSENCE_PROOF=9, ACTIVITY_ONLY=10, NOWHERE_IN_DATA=21.

**Linker rule:** only explicit LINK_RESOURCE_IDENTITY details or identity-matched evidence rows/facts link an account. User/account numeric similarity is shown only as a diagnostic. Unlinked activity-only IDs remain UNKNOWN and are not bound by event-time proximity. For `ABSENCE_PROOF`, the table shows the latest in-scope snapshot evidence when a linked account can be evaluated; gold COMPLETE rows without a source link remain UNLINKED.

|case|system|resource|raw evidence files (type; Fact)|activity types|activity count|case identity tie|user_id|number pattern only|expected step|sample cited file|link source|classification / state evidence|
|---|---|---|---|---|---:|---|---|---|---|---|---|---|
|case_01|account_service|account_001|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_01|yes|verification-only|evidence_54: evidence/databases/customer_accounts_failover_replica_20260902.sql|UNLINKED|ABSENCE_PROOF|
|case_02|account_service|account_002|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_02|yes|verification-only|evidence_54: evidence/databases/customer_accounts_failover_replica_20260902.sql|UNLINKED|ABSENCE_PROOF|
|case_04|account_service|account_004|-|-|0|LINK=no; DELETE-SYNC=no|user_04|yes|verification-only|evidence_54: evidence/databases/customer_accounts_failover_replica_20260902.sql|UNLINKED|ABSENCE_PROOF|
|case_06|account_service|account_006|evidence_57 (.sql; Fact=yes)|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_06|yes|verification-only|-|IDENTITY_ADJACENT_EVIDENCE|ABSENCE_PROOF; state ABSENT at evidence_90|
|case_07|account_service|account_007|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_07|yes|verification-only|-|UNLINKED|ACTIVITY_ONLY|
|case_08|account_service|account_008|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_08|yes|verification-only|-|UNLINKED|ACTIVITY_ONLY|
|case_09|account_service|account_3960|evidence_06 (.log; Fact=yes)|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_61|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_09|security_service|audit_record_4902|evidence_06 (.log; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_61|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_10|account_service|account_010|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_10|yes|verification-only|-|UNLINKED|ACTIVITY_ONLY|
|case_11|account_service|account_4248|evidence_03 (.txt; Fact=yes)|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_32|no|verification-only|-|IDENTITY_ADJACENT_EVIDENCE|ABSENCE_PROOF; state ABSENT at evidence_03|
|case_11|security_service|audit_record_9394|evidence_03 (.txt; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_32|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_12|account_service|account_9797|evidence_01 (.log; Fact=yes)|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_12|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_12|security_service|audit_record_2945|evidence_01 (.log; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_12|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_13|account_service|account_9335|evidence_03 (.txt; Fact=yes)|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_33|no|verification-only|-|IDENTITY_ADJACENT_EVIDENCE|ABSENCE_PROOF; state ABSENT at evidence_03|
|case_13|security_service|audit_record_4816|evidence_03 (.txt; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_33|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_14|account_service|account_3677|evidence_03 (.txt; Fact=yes)|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_37|no|verification-only|-|IDENTITY_ADJACENT_EVIDENCE|ABSENCE_PROOF; state ABSENT at evidence_03|
|case_14|security_service|audit_record_987|evidence_03 (.txt; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_37|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_15|account_service|account_4745|evidence_01 (.log; Fact=yes)|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_15|no|verification-only|-|EARLIER_IDENTITY_EVIDENCE|ABSENCE_PROOF; state ABSENT at evidence_51|
|case_15|security_service|audit_record_1596|evidence_01 (.log; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_15|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_16|security_service|audit_record_9528|evidence_05 (.sql; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_53|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_17|account_service|account_4092|evidence_01 (.log; Fact=yes)|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_17|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_17|security_service|audit_record_1797|evidence_01 (.log; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_17|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_18|account_service|account_5521|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_50|no|verification-only|-|UNLINKED|ACTIVITY_ONLY|
|case_18|security_service|audit_record_6645|-|-|0|LINK=no; DELETE-SYNC=no|user_50|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_19|account_service|account_9102|evidence_01 (.log; Fact=yes)|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_19|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_19|security_service|audit_record_6793|evidence_01 (.log; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_19|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_20|account_service|account_5037|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_48|no|verification-only|-|UNLINKED|ACTIVITY_ONLY|
|case_20|security_service|audit_record_5569|-|-|0|LINK=no; DELETE-SYNC=no|user_48|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_22|account_service|account_4990|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_51|no|verification-only|-|UNLINKED|ACTIVITY_ONLY|
|case_22|security_service|audit_record_3482|evidence_05 (.sql; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_51|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_23|account_service|account_410|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_23|no|verification-only|-|UNLINKED|ACTIVITY_ONLY|
|case_23|security_service|audit_record_4128|evidence_02 (.json; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_23|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_24|security_service|audit_record_7095|evidence_02 (.json; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_24|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_29|account_service|account_7012|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_29|no|verification-only|-|UNLINKED|ACTIVITY_ONLY|
|case_29|security_service|audit_record_3954|evidence_02 (.json; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_29|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_30|account_service|account_4163|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_30|no|verification-only|-|UNLINKED|ACTIVITY_ONLY|
|case_30|security_service|audit_record_1707|evidence_02 (.json; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_30|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|
|case_31|account_service|account_4857|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_541|no|verification-only|evidence_51: evidence/records/customer_data_snapshot_bundle_20260915.json|UNLINKED|ABSENCE_PROOF|
|case_32|account_service|account_8858|-|DELETE_RECORD x1|1|LINK=no; DELETE-SYNC=no|user_542|no|verification-only|-|UNLINKED|ACTIVITY_ONLY|
|case_32|security_service|audit_record_7068|evidence_51 (.json; Fact=yes)|-|0|LINK=no; DELETE-SYNC=no|user_542|no|verification-only|-|UNLINKED|NOWHERE_IN_DATA|

## Recall and precision

|resource group|found / expected|
|---|---:|
|Evidence-backed resources|56/75|
|Evidence-backed with known state|48/75|
|Verification-only resources|17/36|
|Verification-only with known state|17/36|
|All distinct resources|73/111|

Identity-matched, known-state, non-legal candidate Fact precision is 67/67 (100.0%). Unique known-state ResourceState precision is 65/65 (100.0%). UNKNOWN states are not actionable and are excluded from precision.

Verified account linker example: `account_006` is linked by `evidence_57` `source_resource_id` in an identity-bearing search row; the latest account-service snapshot in scope is `evidence_90`, which lacks it, so `resolve_states` returns ABSENT with `evidence_id=evidence_90`.

No parser gap remained after exact-token review: the apparent `account_410` and `audit_record_987` matches are longer IDs (`account_41038` and `audit_record_9878`), not the expected resources. The only exact relationship mention without a separate resource Fact is `account_006` in `evidence_57`; the existing parsed search-row Fact preserves it in `raw_ref`, so the linker can use the explicit relationship without synthesizing a Fact.
