# Intent classification gate

The labeled dataset evaluation uses the cached ledger and `classify()` lazy batching.

## Successful batch-response gate (mocked LLM)

- 518 requests: {'TEMPLATE': 421, 'LLM': 87, 'EVENT': 1, 'NEGATION': 9}
- Decisions: {True: 508, False: 10}
- Mocked LLM calls: 2 for 57 unique ambiguous texts (batch size 40).
- Labeled samples: 32/32 deletion.
- Custom evaluation cases: 20/20 passed.

## Real client attempt

- Logical batch calls: 2; cache hits: 0.
- Needs review: 87 request rows.
- Labeled samples classified deletion: 20/32.
- The configured endpoint was unreachable (ConnectionError). Per fail-closed policy, ambiguous requests defaulted to NOT_APPLICABLE with NEEDS_REVIEW.

## Unique texts routed to LLM

1. I closed my account, but an old “download your data” link still works. Please delete that export file as well.
2. I deleted this account and received a confirmation, but the same email address is still recognized. Please remove any remaining copy of my profile.
3. I disconnected my account last week, but one of the integrations still seems active. Close the account completely and make sure it can no longer send my data to other systems.
4. I found an old report saying my account still existed. Please check the latest state and confirm that the profile is gone and that remaining records cannot identify me.
5. I’m deleting my account. You can keep anonymous statistics, but nothing in analytics should still point back to me.
6. I no longer need this account. Please remove my name and contact details, but keeping an internal deleted-account reference is fine if other required records still depend on it.
7. I was told that deletion was complete, but the account and its search result can still be found. Please investigate and finish the deletion.
8. I was told the account had been deleted, but I can still find traces in search, support, and analytics. Please handle them and disable any synchronization that could recreate them.
9. I would like to submit a request to delete this account and its personal data. Please apply the correct treatment to records covered by the request. I would appreciate confirmation of the final outcome.
10. I would like to submit a request to delete this account and its personal data. Please apply the correct treatment to records covered by the request. Let me know when the request has been completed.
11. I would like to submit a request to delete this account and its personal data. Please apply the correct treatment to records covered by the request. Please let me know once the request has been reviewed.
12. I would like to submit a request to delete this account and its personal data. Please apply the request across the systems covered by your deletion policy. I would appreciate confirmation of the final outcome.
13. I would like to submit a request to delete this account and its personal data. Please apply the request across the systems covered by your deletion policy. Please confirm when the review is complete.
14. I would like to submit a request to delete this account and its personal data. Please apply the request across the systems covered by your deletion policy. Please let me know once the request has been reviewed.
15. I would like to submit a request to delete this account and its personal data. Please apply the request across the systems covered by your deletion policy. Please send a confirmation after the process finishes.
16. I would like to submit a request to delete this account and its personal data. Please check the records connected to the account before confirming completion. Let me know when the request has been completed.
17. I would like to submit a request to delete this account and its personal data. Please check the records connected to the account before confirming completion. Please contact me if you need information to verify the request.
18. I would like to submit a request to delete this account and its personal data. Please complete the normal identity and data review for this request. Please confirm the result after completing the required checks.
19. I would like to submit a request to delete this account and its personal data. Please complete the normal identity and data review for this request. Please contact me if you need information to verify the request.
20. I would like to submit a request to delete this account and its personal data. Please complete the normal identity and data review for this request. Please let me know once the request has been reviewed.
21. I would like to submit a request to delete this account and its personal data. Please complete the normal identity and data review for this request. Please send a confirmation after the process finishes.
22. I would like to submit a request to delete this account and its personal data. Please ensure the request is applied to the relevant account records. A short confirmation when the process is complete is sufficient.
23. I would like to submit a request to delete this account and its personal data. Please ensure the request is applied to the relevant account records. I would appreciate confirmation of the final outcome.
24. I would like to submit a request to delete this account and its personal data. Please ensure the request is applied to the relevant account records. Let me know when the request has been completed.
25. I would like to submit a request to delete this account and its personal data. Please ensure the request is applied to the relevant account records. Please confirm the result after completing the required checks.
26. I would like to submit a request to delete this account and its personal data. Please ensure the request is applied to the relevant account records. Please contact me if you need information to verify the request.
27. I would like to submit a request to delete this account and its personal data. Please ensure the request is applied to the relevant account records. Please let me know once the request has been reviewed.
28. I would like to submit a request to delete this account and its personal data. Please ensure the request is applied to the relevant account records. Please send a confirmation after the process finishes.
29. I would like to submit a request to delete this account and its personal data. Please follow the applicable retention and deletion requirements for the account. A short confirmation when the process is complete is sufficient.
30. I would like to submit a request to delete this account and its personal data. Please follow the applicable retention and deletion requirements for the account. I would appreciate confirmation of the final outcome.
31. I would like to submit a request to delete this account and its personal data. Please follow the applicable retention and deletion requirements for the account. Let me know when the request has been completed.
32. I would like to submit a request to delete this account and its personal data. Please follow the applicable retention and deletion requirements for the account. Please confirm when the review is complete.
33. I would like to submit a request to delete this account and its personal data. Please follow the applicable retention and deletion requirements for the account. Please send a confirmation after the process finishes.
34. I would like to submit a request to delete this account and its personal data. Please handle any copies that fall within the scope of the deletion request. I would appreciate confirmation of the final outcome.
35. I would like to submit a request to delete this account and its personal data. Please handle any copies that fall within the scope of the deletion request. Please confirm the result after completing the required checks.
36. I would like to submit a request to delete this account and its personal data. Please handle any copies that fall within the scope of the deletion request. Please contact me if you need information to verify the request.
37. I would like to submit a request to delete this account and its personal data. Please include information linked through current or earlier account identifiers. Let me know when the request has been completed.
38. I would like to submit a request to delete this account and its personal data. Please include information linked through current or earlier account identifiers. Please contact me if you need information to verify the request.
39. I would like to submit a request to delete this account and its personal data. Please include records associated with the account under your privacy process. I would appreciate confirmation of the final outcome.
40. I would like to submit a request to delete this account and its personal data. Please process this under the standard personal-data deletion procedure. Please confirm the result after completing the required checks.
41. I would like to submit a request to delete this account and its personal data. Please process this under the standard personal-data deletion procedure. Please confirm when the review is complete.
42. I would like to submit a request to delete this account and its personal data. Please process this under the standard personal-data deletion procedure. Please contact me if you need information to verify the request.
43. I would like to submit a request to delete this account and its personal data. Please review any identifiers connected to this account as part of the request. Please confirm the result after completing the required checks.
44. I would like to submit a request to delete this account and its personal data. Please review any identifiers connected to this account as part of the request. Please confirm when the review is complete.
45. I would like to submit a request to delete this account and its personal data. Please review any identifiers connected to this account as part of the request. Please contact me if you need information to verify the request.
46. I would like to submit a request to delete this account and its personal data. Please review any identifiers connected to this account as part of the request. Please send a confirmation after the process finishes.
47. I would like to submit a request to delete this account and its personal data. Please review the account data that is eligible for deletion or de-identification. A short confirmation when the process is complete is sufficient.
48. I would like to submit a request to delete this account and its personal data. Please review the account data that is eligible for deletion or de-identification. I would appreciate confirmation of the final outcome.
49. I would like to submit a request to delete this account and its personal data. Please review the account data that is eligible for deletion or de-identification. Please confirm when the review is complete.
50. I would like to submit a request to delete this account and its personal data. Please review the account data that is eligible for deletion or de-identification. Please contact me if you need information to verify the request.
51. My account page is gone, but my old profile still appears when I search for it. Can you remove that search result too?
52. Please delete this account, including the downloadable archive I requested earlier and any search result that still points to me. Security records can stay if policy requires them.
53. Solicito a exclusão permanente da conta associada a este e-mail. Verifiquem os identificadores atuais e anteriores conforme o processo de privacidade. Por favor, confirmem o resultado quando a análise terminar.
54. Solicito la eliminación permanente de la cuenta asociada a este correo. Revisen los identificadores actuales y anteriores según su política de privacidad. Por favor, confirmen el resultado cuando termine la revisión.
55. The account itself is gone, but an internal deleted-account record still shows my personal details. Please keep only the reference needed for retained records and remove the rest.
56. The privacy page still says my request failed. Please inspect the actual systems and tell me whether the account and identifiable analytics data have already been removed.
57. 이 이메일 주소에 연결된 계정의 영구 삭제를 요청합니다. 개인정보 처리 절차에 따라 현재 및 이전 식별자를 검토해 주세요. 검토가 완료되면 결과를 확인해 주세요.
