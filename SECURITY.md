# Security Policy

HarmoNet is currently a research prototype. Treat all LLM outputs as untrusted,
especially when generated code, shell commands, credentials, or network calls are
involved.

## Reporting issues

Please open a private security advisory or contact the maintainers before
publishing a vulnerability publicly.

## Secrets

Do not commit API keys, tokens, local `.env` files, benchmark provider secrets,
or raw provider response dumps. Use `.env.example` as the only committed
configuration template.
