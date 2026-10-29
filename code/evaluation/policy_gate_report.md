# Policy decision gate (32 labeled samples)

- Cached ledger: 3169 facts; cache_hit=True.
- Distinct sample resource triples: 111.
- Decisions produced: 49; unexpected triples: 2.
- Exact operation tuple matches: 40/111 (36.0%).

## Operation confusion tables

Each row is an expected operation and predicted operation for one of the 111 sample resource triples. `None` means no finding/remediation; for verification it means no Decision.

### finding_op

| Expected | Predicted | Count |
|---|---|---:|
| `None` | `None` | 70 |
| `REPORT_ACTIVE_DATA_FLOW` | `None` | 3 |
| `REPORT_ACTIVE_DATA_FLOW` | `REPORT_ACTIVE_DATA_FLOW` | 3 |
| `REPORT_EXPOSED_PII` | `None` | 5 |
| `REPORT_EXPOSED_PII` | `REPORT_EXPOSED_PII` | 6 |
| `REPORT_REMAINING_RECORD` | `None` | 8 |
| `REPORT_REMAINING_RECORD` | `REPORT_REMAINING_RECORD` | 13 |
| `REPORT_RESTORE_RISK` | `None` | 1 |
| `REPORT_RESTORE_RISK` | `REPORT_RESTORE_RISK` | 2 |

### remediation_op

| Expected | Predicted | Count |
|---|---|---:|
| `ANONYMIZE_RECORD` | `ANONYMIZE_RECORD` | 4 |
| `ANONYMIZE_RECORD` | `None` | 1 |
| `BLOCK_RESTORE` | `BLOCK_RESTORE` | 2 |
| `BLOCK_RESTORE` | `None` | 1 |
| `DELETE_RECORD` | `DELETE_RECORD` | 13 |
| `DELETE_RECORD` | `None` | 8 |
| `DISABLE_DATA_FLOW` | `DISABLE_DATA_FLOW` | 3 |
| `DISABLE_DATA_FLOW` | `None` | 3 |
| `None` | `None` | 70 |
| `REDACT_RECORD` | `None` | 4 |
| `REDACT_RECORD` | `REDACT_RECORD` | 2 |

### verify_op

| Expected | Predicted | Count |
|---|---|---:|
| `VERIFY_DATA_FLOW_DISABLED` | `None` | 3 |
| `VERIFY_DATA_FLOW_DISABLED` | `VERIFY_DATA_FLOW_DISABLED` | 6 |
| `VERIFY_RECORD_ABSENT` | `None` | 29 |
| `VERIFY_RECORD_ABSENT` | `VERIFY_RECORD_ABSENT` | 21 |
| `VERIFY_RECORD_ANONYMIZED` | `None` | 8 |
| `VERIFY_RECORD_ANONYMIZED` | `VERIFY_RECORD_ANONYMIZED` | 4 |
| `VERIFY_RECORD_PRESENT` | `None` | 22 |
| `VERIFY_RECORD_PRESENT` | `VERIFY_RECORD_ABSENT` | 2 |
| `VERIFY_RECORD_REDACTED` | `None` | 1 |
| `VERIFY_RECORD_REDACTED` | `VERIFY_RECORD_ABSENT` | 1 |
| `VERIFY_RECORD_REDACTED` | `VERIFY_RECORD_REDACTED` | 8 |
| `VERIFY_RESTORE_BLOCKED` | `None` | 1 |
| `VERIFY_RESTORE_BLOCKED` | `VERIFY_RESTORE_BLOCKED` | 5 |

## Mismatches (71)

| Case | System | Resource | Expected (finding / remediation / verify) | Predicted (finding / remediation / verify) | Rule fired / resolution |
|---|---|---|---|---|---|
| `case_01` | `account_service` | `account_001` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_02` | `account_service` | `account_002` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_03` | `account_service` | `account_7566` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: state=UNKNOWN, category=USER_PROFILE |
| `case_03` | `security_service` | `audit_record_2016` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=UNKNOWN, category=SECURITY_AUDIT_LOG |
| `case_03` | `analytics_platform` | `analytics_9406` | `— / — / VERIFY_RECORD_ANONYMIZED` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_04` | `account_service` | `account_004` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_04` | `analytics_platform` | `analytics_901` | `— / — / VERIFY_RECORD_ANONYMIZED` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_05` | `account_service` | `account_005` | `REPORT_REMAINING_RECORD / DELETE_RECORD / VERIFY_RECORD_ABSENT` | `— / — / VERIFY_RECORD_ABSENT` | rule_01: USER_PROFILE / Always / ABSENT [always] |
| `case_07` | `support_platform` | `support_001` | `REPORT_REMAINING_RECORD / DELETE_RECORD / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SUPPORT_ATTACHMENT |
| `case_07` | `account_service` | `account_007` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_08` | `account_service` | `account_008` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_09` | `account_service` | `account_3960` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_09` | `security_service` | `audit_record_4902` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_10` | `support_platform` | `support_002` | `REPORT_REMAINING_RECORD / DELETE_RECORD / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_10` | `account_service` | `account_010` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_11` | `security_service` | `audit_record_9394` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_12` | `analytics_platform` | `analytics_9914` | `REPORT_REMAINING_RECORD / DELETE_RECORD / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_12` | `account_service` | `account_9797` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_12` | `security_service` | `audit_record_2945` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / VERIFY_RECORD_ABSENT` | rule_12: SECURITY_AUDIT_LOG / Record is within the supplied retention period / ABSENT [always] |
| `case_13` | `support_platform` | `support_4218` | `REPORT_REMAINING_RECORD / DELETE_RECORD / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SUPPORT_ATTACHMENT |
| `case_13` | `security_service` | `audit_record_4816` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_14` | `security_service` | `audit_record_987` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_15` | `integration_service` | `data_flow_9846` | `REPORT_ACTIVE_DATA_FLOW / DISABLE_DATA_FLOW / VERIFY_DATA_FLOW_DISABLED` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_15` | `security_service` | `audit_record_1596` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_16` | `security_service` | `audit_record_9528` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_17` | `backup_service` | `backup_3245` | `REPORT_RESTORE_RISK / BLOCK_RESTORE / VERIFY_RESTORE_BLOCKED` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_17` | `account_service` | `account_4092` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_17` | `security_service` | `audit_record_1797` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / VERIFY_RECORD_ABSENT` | rule_12: SECURITY_AUDIT_LOG / Record is within the supplied retention period / ABSENT [always] |
| `case_18` | `search_service` | `search_4013` | `REPORT_REMAINING_RECORD / DELETE_RECORD / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: state=UNKNOWN, category=SEARCH_INDEX_ENTRY |
| `case_18` | `analytics_platform` | `analytics_037` | `REPORT_EXPOSED_PII / ANONYMIZE_RECORD / VERIFY_RECORD_ANONYMIZED` | `— / — / —` | NO_RULE: state=UNKNOWN, category=ANALYTICS_PROFILE |
| `case_18` | `support_platform` | `support_5569` | `REPORT_EXPOSED_PII / REDACT_RECORD / VERIFY_RECORD_REDACTED` | `— / — / —` | NO_RULE: state=UNKNOWN, category=SUPPORT_MESSAGE |
| `case_18` | `integration_service` | `data_flow_4890` | `REPORT_ACTIVE_DATA_FLOW / DISABLE_DATA_FLOW / VERIFY_DATA_FLOW_DISABLED` | `— / — / —` | NO_RULE: state=UNKNOWN, category=DATA_FLOW |
| `case_18` | `account_service` | `account_5521` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_18` | `security_service` | `audit_record_6645` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_19` | `search_service` | `search_6083` | `REPORT_REMAINING_RECORD / DELETE_RECORD / VERIFY_RECORD_ABSENT` | `— / — / VERIFY_RECORD_ABSENT` | rule_03: SEARCH_INDEX_ENTRY / Always / ABSENT [always] |
| `case_19` | `support_platform` | `support_9553` | `REPORT_EXPOSED_PII / REDACT_RECORD / VERIFY_RECORD_REDACTED` | `— / — / VERIFY_RECORD_ABSENT` | rule_05: SUPPORT_MESSAGE / Conversation contains shared customer, agent, or order context that must be retained / ABSENT [always] |
| `case_19` | `account_service` | `account_9102` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_19` | `security_service` | `audit_record_6793` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_20` | `search_service` | `search_4262` | `REPORT_REMAINING_RECORD / DELETE_RECORD / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: state=UNKNOWN, category=SEARCH_INDEX_ENTRY |
| `case_20` | `integration_service` | `data_flow_1770` | `REPORT_ACTIVE_DATA_FLOW / DISABLE_DATA_FLOW / VERIFY_DATA_FLOW_DISABLED` | `— / — / —` | NO_RULE: state=UNKNOWN, category=DATA_FLOW |
| `case_20` | `account_service` | `account_5037` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_20` | `security_service` | `audit_record_5569` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_21` | `account_service` | `account_6440` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_21` | `security_service` | `audit_record_3737` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_21` | `analytics_platform` | `analytics_5335` | `— / — / VERIFY_RECORD_ANONYMIZED` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_22` | `account_service` | `account_4990` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_22` | `security_service` | `audit_record_3482` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_23` | `account_service` | `account_410` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_23` | `security_service` | `audit_record_4128` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_24` | `security_service` | `audit_record_7095` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_25` | `account_service` | `account_3136` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_25` | `security_service` | `audit_record_451` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_25` | `analytics_platform` | `analytics_1895` | `— / — / VERIFY_RECORD_ANONYMIZED` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_26` | `security_service` | `audit_record_5416` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_26` | `analytics_platform` | `analytics_4566` | `— / — / VERIFY_RECORD_ANONYMIZED` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_27` | `account_service` | `account_3866` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_27` | `security_service` | `audit_record_3830` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_27` | `analytics_platform` | `analytics_4574` | `— / — / VERIFY_RECORD_ANONYMIZED` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_28` | `account_service` | `account_5482` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_28` | `security_service` | `audit_record_9265` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_28` | `analytics_platform` | `analytics_6077` | `— / — / VERIFY_RECORD_ANONYMIZED` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_29` | `support_platform` | `support_5281` | `REPORT_EXPOSED_PII / REDACT_RECORD / VERIFY_RECORD_REDACTED` | `— / — / VERIFY_RECORD_REDACTED` | rule_05: SUPPORT_MESSAGE / Conversation contains shared customer, agent, or order context that must be retained / REDACTED [always] |
| `case_29` | `account_service` | `account_7012` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_29` | `security_service` | `audit_record_3954` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_30` | `support_platform` | `support_6477` | `REPORT_EXPOSED_PII / REDACT_RECORD / VERIFY_RECORD_REDACTED` | `— / — / VERIFY_RECORD_REDACTED` | rule_05: SUPPORT_MESSAGE / Conversation contains shared customer, agent, or order context that must be retained / REDACTED [always] |
| `case_30` | `account_service` | `account_4163` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_30` | `security_service` | `audit_record_1707` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_31` | `account_service` | `account_4857` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_31` | `security_service` | `audit_record_6909` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |
| `case_32` | `account_service` | `account_8858` | `— / — / VERIFY_RECORD_ABSENT` | `— / — / —` | NO_RULE: no ResourceState was resolved for this resource |
| `case_32` | `security_service` | `audit_record_7068` | `— / — / VERIFY_RECORD_PRESENT` | `— / — / —` | NO_RULE: state=PRESENT, category=SECURITY_AUDIT_LOG |

## Unexpected decisions (2)

- `case_17` / `account_service` / `account_6523`: `— / — / VERIFY_RECORD_ABSENT`; rule_01: USER_PROFILE / Always / ABSENT [always].
- `case_17` / `identity_service` / `tombstone_17`: `— / — / VERIFY_RECORD_ABSENT`; rule_15: ACCOUNT_TOMBSTONE / Account is deleted and only a stable internal user_id is needed to preserve references to retained records / ABSENT [always].

The mismatches mainly reflect absent/unresolved `ResourceState` candidates and disagreement between available parsed state and the sample-cited state. `reported_result` is not used as state evidence.
