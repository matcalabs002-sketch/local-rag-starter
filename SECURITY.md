# Security and privacy

This starter is a local single-user tool. Keep Streamlit and the database bound to loopback. It has no public authentication, tenant isolation, or application-level cloud spending cap. Public hosting needs a separate design and verification pass.

Never commit `.env`, `.private`, custom original storage directories, OAuth client/token files, database dumps, documents, model caches, or logs. If you choose a custom `RAG_DATA_DIR`, keep it outside the repository or add it to .gitignore before using it. Private storage and configuration use restrictive permissions on POSIX; Windows users should also restrict access through filesystem ACLs.

The default pipeline sends no document content to a cloud AI provider. Explicitly selecting a paid provider can send source passages and questions to that provider. Drive authorization is read-only but grants access at the Google-account scope; this app limits its own queries to the configured folder. Website imports make public HTTPS requests from your machine.

Uploaded source text is untrusted. The model is instructed to ignore embedded instructions, structured output is validated, citation IDs must come from supplied passages, and evidence revisions are checked before saving. These mitigations do not prove semantic entailment or defeat every prompt injection. Inspect evidence for consequential answers.

Remote Supabase connections require verified TLS and session pooling. Destructive tests reject remote hosts and ordinary database names. Do not weaken these checks to make a test pass.

To report an issue privately, use the hosting platform's private vulnerability reporting mechanism if enabled. If unavailable, request a private reporting channel without posting exploit details, credentials, or source documents publicly. Do not invent contact addresses in reports or documentation.

If credentials are discovered in history, revoke/rotate them before publishing and review whether history needs sanitization. An ignored file is not a substitute for a history scan.
