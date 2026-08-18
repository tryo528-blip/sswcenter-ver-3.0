# W3 successor와 W2 봉인 부모의 delta — 2026-08-17

> 상태: `W3_SUCCESSOR_IN_PROGRESS / W2_HISTORICAL_PARENT_SEAL_PRESERVED`

W2 reviewed manifest 98개 row 중 현재 `85/98`은 SHA-256·bytes exact다. 아래 13개는
형님의 W3 추천안 전체 승인 뒤 선택 계약과 0028 source-intake foundation 전환을
정본·active-head 경로에 반영한 의도적 successor 변경이다. W2 봉인 당시의 98/98
exact 증거를 수정하거나 무효라고 주장하지 않는다.

| classification | parent SHA-256 | parent bytes | current SHA-256 | current bytes | path |
|---|---|---:|---|---:|---|
| `INTENTIONAL_CANONICAL_CHANGE` | `4dea2b45e94ebfb46f96bb83c7359d5554f61e7c0b9aca45473371fc981b43a6` | 34628 | `8c52e20925bcc8ed7bc36f9f644b3c613a435511b3a71dfd6612e492c60e2606` | 34824 | `docs/02_업무규칙_계약_v1.1.md` |
| `INTENTIONAL_CANONICAL_CHANGE` | `f8c1133715dddeed9d12aa5a017576af32b922c583474468274d65da04b23841` | 13605 | `4a19d4ff5b5193566e8eb86297fe2a7542f5f5aed54d0c2fd0a7ce17f024eb2a` | 14379 | `docs/06_개발로드맵_결정현황_v1.2.md` |
| `INTENTIONAL_CANONICAL_CHANGE` | `e51fd59dcce8e7be6d11fb4328403808c9b7dc4a2480d035b043210311188920` | 36314 | `d6a70af5b5bd4bb0df0d91710a19a32637099f7b82a8e9db6750d6dde0704baf` | 38859 | `docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md` |
| `INTENTIONAL_CANONICAL_CHANGE` | `d0b632c9c383dc32cf08a3ff5949c9da777f249398a688f5961a41dd0f999bb9` | 25239 | `6b7ca2b15e050cd60a7a90f18812fba0bbf60e444f7cc3f81945ebcddab98d1c` | 26566 | `docs/05_기술_보안_파일처리_아키텍처_v1.5.md` |
| `INTENTIONAL_CANONICAL_CHANGE` | `d3c1d48cc90d57bf24962d7a006b2602124a89cbe03ce63b680e3b658101d500` | 2897 | `274542e6e59749f0facef3a3d4cf2899116681d1eab329954bcb5781ead189ad` | 2897 | `backend/app/core/readiness.py` |
| `INTENTIONAL_CANONICAL_CHANGE` | `cf65c10fe81b8e231b70728058929d1a83d5dd5cf4b4e620db4a0266ed8b8f6d` | 3012 | `93ffeaa0ed1b075cc719bad7134d8f13aa138c45ece929683825611cb5ddd63c` | 2036 | `backend/app/db/postcheck_dispatch.py` |
| `INTENTIONAL_CANONICAL_CHANGE` | `b11e163541b77d1e0a38354b5f577609539acc8ecd343489c0d267be511bd84f` | 12139 | `e12f1965d49f8eebc091a4a438941e4bc2460fcf0cbbf72fb03515b5248f5ff2` | 12434 | `backend/app/db/postcheck_current_0027.py` |
| `INTENTIONAL_CANONICAL_CHANGE` | `d01884ee85bb6f6dc92da1f50ea03c22b1bde37c74c2fb688a1604791dfbd317` | 7230 | `c25e9bb37c1cf72efb85c26a01493df5f383ee796ad6da33b0592060c9bad76e` | 7230 | `backend/tests/test_w0_readiness_write_gate.py` |
| `INTENTIONAL_CANONICAL_CHANGE` | `2049f868f7d35ee1c97256a308c69d19820781b57c1bbb020fdef18fe01beefc` | 3851 | `4f73164f7a724a7b9e2e84a7ae4580acc8e30458a2cb669c4f8656a0ecff58e1` | 3608 | `backend/tests/test_foundation_0025_contract.py` |
| `INTENTIONAL_CANONICAL_CHANGE` | `5df477a3b6257fa6d9796b9597c7d6374039eceebd9392ab24b82b73fa9fbf34` | 27360 | `7b116086844629cb7e051cfff289a3b9c9db745e4554a616c45d1cac6e1296ed` | 27122 | `backend/tests/test_w1e_phase1_contract.py` |
| `INTENTIONAL_CANONICAL_CHANGE` | `36ecf8c5c711c960d960b96348cb7a10c3e83ea121cc005e6e28f94c8e3c2fe5` | 12010 | `598146348819ca6f18927f73cc3affa7869b2d93f6411771b8c546ac3becf5d0` | 15529 | `backend/tests/test_w2_official_card_assignee_contract.py` |
| `INTENTIONAL_CANONICAL_CHANGE` | `1ea4f66cf371b1e19931e8443bd597d335074b06e884ba19a0895a0996d8d05d` | 20747 | `4dd1b20623d06dd83b1fee425220ee6279a45d0243b1853713d254214b8dfb4f` | 21962 | `scripts/restore-drill.ps1` |
| `INTENTIONAL_CANONICAL_CHANGE` | `e88591effb521f8e761a16e80533655738b802b6de0f770eb15e64701acbc038` | 43654 | `863cd5188536b89ee6d3163b700c24a89859b910923812a653cada26c163add8` | 49411 | `scripts/test-w2-0027-postgres-linux.ps1` |

```text
W2_PARENT_REVIEWED_ROWS_EXACT=85/98
W3_INTENTIONAL_CANONICAL_CHANGES=13
W2_UNAUTHORIZED_DRIFT=0
W2_SCOPED_SEAL_STATUS=HISTORICAL_PARENT_SEAL
REMOVED_PARENT_ROWS=0
```

후속 W3 migration·코드가 다른 W2 manifest 경로를 의도적으로 바꾸면 이 원장을 현재
candidate hash로 갱신한다. 승인된 W3 범위로 설명되지 않는 mismatch는
`W2_UNAUTHORIZED_DRIFT>0 / STATUS=BLOCKED`로 처리한다.
