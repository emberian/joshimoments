# Market-state reducer fixtures

`adversarial.v1.json` declares the exact point-in-time cut and refusal cases exercised by
`joshi-market-state`. The Rust test builds typed facts using the existing validated attention
fixture and exact protocol types; the JSON fixture is scenario configuration, not a substitute for
retained source bytes.

All identities and values in this fixture are synthetic. Passing it proves deterministic contract
behavior and leakage/refusal guards. It does **not** satisfy the Wave 4 real-source canary gate,
establish source coverage, or authorize live collection or execution.
