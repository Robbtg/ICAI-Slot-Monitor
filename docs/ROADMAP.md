# Roadmap

## v1.0 — current

- Playwright
- configurable watches
- public batch lookup
- generic table extraction
- seat inference
- Telegram alerts
- state deduplication
- GitHub Actions

## v1.1

- direct HTTP/ASP.NET postback adapter
- lower CPU/memory use
- faster polling

## v1.2

- date filters
- venue filters
- exact seat thresholds
- multiple Telegram recipients
- daily health-check

## v2

- static dashboard
- historical availability chart
- CSV export
- optional screenshot on alert
- health monitoring

## v3

A reusable portal-monitoring framework:

```text
Portal Adapter
     ↓
Workflow Engine
     ↓
State Engine
     ↓
Notification Engine
     ↓
Dashboard
```

The ICAI adapter becomes only one connector. The same framework can later monitor other public portals where automated monitoring is permitted.
