# Security

UnitMerge reads local JSON and caller-supplied source bytes. It does not make network requests, execute source content or authenticate sources. Treat proposals, source text and receipt metadata as potentially sensitive; outputs retain caller-supplied unit and source IDs.

The CLI rejects oversized or deeply nested JSON, duplicate keys and invalid contracts. The checked API bounds source sizes and proposal counts. It is not a sandbox for arbitrary objects or a semantic security validator. Embed it behind your own authentication, authorization and workload limits when building a service.

For a suspected vulnerability, prepare a minimal synthetic reproduction and use the repository host's private vulnerability-reporting channel if available. Do not include credentials, confidential source text or an exploit against a live third party in a public issue. No response-time guarantee or security certification is claimed.
