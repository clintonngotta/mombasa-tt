"""Money is integer minor units plus an ISO currency code (REQ-032): KES 500.00 is
`{"amount_minor": 50000, "currency": "KES"}`."""

MAX_AMOUNT_MINOR = 1_000_000_000
