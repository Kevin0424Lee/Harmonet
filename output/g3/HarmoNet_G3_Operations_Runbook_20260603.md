# HarmoNet v2 G3 Operations Runbook

## Start

```bash
cd /home/kevinlee/harmoNet/harmoNet-v2-20260602
docker compose up -d redis harmonet prometheus grafana
docker compose ps
curl http://localhost:8080/healthz
curl http://localhost:8080/readyz
curl http://localhost:8080/metrics
```

## Stop

```bash
docker compose down
```

## Long Reliability Run

Short smoke:

```bash
.venv/bin/python -X utf8 -m benchmark.g3_runner \
  --duration-seconds 60 \
  --interval-seconds 2 \
  --concurrency 1,5,10,25,50 \
  --requests-per-level 100 \
  --failure-recovery \
  --output-dir output/g3
```

24-hour reliability run:

```bash
.venv/bin/python -X utf8 -m benchmark.g3_runner \
  --duration-seconds 86400 \
  --interval-seconds 30 \
  --concurrency 1,5,10,25,50 \
  --requests-per-level 1000 \
  --failure-recovery \
  --output-dir output/g3_24h
```

## Alerts

Prometheus alert rules live in:

```text
deploy/prometheus-alerts.yml
```

Configured alerts:

- `HarmoNetHealthDown`
- `HarmoNetLLMErrorSpike`
- `HarmoNetTokenSpike`
- `HarmoNetRedisFallback`

## Incident Checks

Health:

```bash
curl -fsS http://localhost:8080/healthz
```

Readiness and dependency state:

```bash
curl -fsS http://localhost:8080/readyz
```

Container state:

```bash
docker compose ps
docker compose logs --tail=100 harmonet
docker compose logs --tail=100 redis
```

Redis recovery:

```bash
docker compose restart redis
sleep 10
curl -fsS http://localhost:8080/readyz
```

## G3 Pass Criteria

| Gate | Minimum |
|---|---:|
| Short reliability availability | >= 99.5% |
| Load availability | >= 99.5% |
| Failure recovery | Redis stop/start does not kill HarmoNet |
| Security scan | No critical or high static findings |
| Compose config | No parse errors |
| Container health | `healthy` |

## Known Production-Hardening Items

- Run the 24-hour reliability command before claiming production uptime.
- Add authenticated ingress if exposed beyond localhost or a private network.
- Run a real CVE scanner such as Trivy or Docker Scout where available.
- Replace MockLLM health-only smoke with an authenticated API smoke in staging.
