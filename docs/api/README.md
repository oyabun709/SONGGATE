# RopQA Public API

Base URL: `https://api.ropqa.com/api/v1`

All requests require a `Bearer` token:

```
Authorization: Bearer ropqa_sk_<your_key>
```

API keys are created from **Settings → API Keys** in the dashboard (Professional plan and above). Each key shows the secret once — store it securely.

---

## Quick Start

### 1. Create a release

```bash
curl -X POST https://api.ropqa.com/api/v1/releases \
  -H "Authorization: Bearer ropqa_sk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My Album",
    "artist": "Artist Name",
    "submission_format": "ddex_ern43",
    "upc": "0123456789012",
    "release_date": "2024-03-01"
  }'
```

Response:
```json
{
  "id": "rel_abc123",
  "title": "My Album",
  "artist": "Artist Name",
  "status": "pending",
  "created_at": "2024-01-15T10:00:00Z"
}
```

### 2. Trigger a scan

```bash
curl -X POST https://api.ropqa.com/api/v1/releases/rel_abc123/scan \
  -H "Authorization: Bearer ropqa_sk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "dsps": ["spotify", "apple_music", "amazon"],
    "layers": ["ddex", "metadata", "artwork", "fraud"]
  }'
```

Response (202 Accepted):
```json
{
  "id": "scan_xyz789",
  "status": "queued",
  "release_id": "rel_abc123",
  "created_at": "2024-01-15T10:00:01Z"
}
```

### 3. Poll for results

```bash
curl https://api.ropqa.com/api/v1/scans/scan_xyz789 \
  -H "Authorization: Bearer ropqa_sk_..."
```

Poll until `status` is `complete` or `failed`. Typical scan time: 15–45 seconds.

```json
{
  "id": "scan_xyz789",
  "status": "complete",
  "grade": "WARN",
  "readiness_score": 72,
  "total_issues": 3,
  "critical_count": 0,
  "warning_count": 2,
  "info_count": 1,
  "layers_run": ["ddex", "metadata", "artwork", "fraud"],
  "completed_at": "2024-01-15T10:00:38Z"
}
```

### 4. Get detailed results

```bash
curl "https://api.ropqa.com/api/v1/scans/scan_xyz789/results?severity=warning" \
  -H "Authorization: Bearer ropqa_sk_..."
```

```json
{
  "id": "scan_xyz789",
  "results": [
    {
      "id": "res_001",
      "layer": "artwork",
      "rule_id": "ART_MIN_RESOLUTION",
      "severity": "warning",
      "status": "fail",
      "message": "Cover art is 2000×2000 px; minimum required is 3000×3000 px for Spotify and Apple Music.",
      "field_path": "Image[FrontCoverImage].ImageHeight",
      "actual_value": "2000",
      "expected_value": "3000",
      "fix_hint": "Re-export artwork at 3000×3000 px or larger (RGB, JPG/PNG, ≤100 MB).",
      "dsp_targets": ["spotify", "apple_music"],
      "resolved": false
    }
  ]
}
```

---

## Node.js Example

```typescript
const API_KEY = process.env.ROPQA_API_KEY!;
const BASE = "https://api.ropqa.com/api/v1";

async function scanRelease(releaseId: string): Promise<ScanResult> {
  // Trigger scan
  const scanRes = await fetch(`${BASE}/releases/${releaseId}/scan`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ dsps: ["spotify", "apple_music"] }),
  });
  const scan = await scanRes.json();

  // Poll until complete
  let result = scan;
  while (result.status === "queued" || result.status === "running") {
    await new Promise((r) => setTimeout(r, 2000));
    const pollRes = await fetch(`${BASE}/scans/${result.id}`, {
      headers: { Authorization: `Bearer ${API_KEY}` },
    });
    result = await pollRes.json();
  }

  return result;
}
```

---

## Python Example

```python
import os, time, requests

API_KEY = os.environ["ROPQA_API_KEY"]
BASE = "https://api.ropqa.com/api/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

def scan_release(release_id: str) -> dict:
    # Trigger scan
    resp = requests.post(
        f"{BASE}/releases/{release_id}/scan",
        json={"dsps": ["spotify", "apple_music"]},
        headers=HEADERS,
    )
    resp.raise_for_status()
    scan = resp.json()

    # Poll until complete
    while scan["status"] in ("queued", "running"):
        time.sleep(2)
        scan = requests.get(f"{BASE}/scans/{scan['id']}", headers=HEADERS).json()

    return scan

def get_issues(scan_id: str, severity: str = "warning") -> list:
    resp = requests.get(
        f"{BASE}/scans/{scan_id}/results",
        params={"severity": severity},
        headers=HEADERS,
    )
    resp.raise_for_status()
    return resp.json()["results"]
```

---

## Batch Scan (Enterprise)

Trigger up to 100 scans in a single request:

```bash
curl -X POST https://api.ropqa.com/api/v1/batch/scan \
  -H "Authorization: Bearer ropqa_sk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "releases": [
      {"title": "Album A", "artist": "Artist 1", "submission_format": "ddex_ern43"},
      {"title": "Album B", "artist": "Artist 2", "submission_format": "ddex_ern43"}
    ],
    "scan_options": {
      "dsps": ["spotify"],
      "layers": ["ddex", "metadata"]
    },
    "label": "Q1 2024 batch"
  }'
```

Response (202 Accepted):
```json
{
  "job_id": "job_abc",
  "status": "pending",
  "total": 2,
  "completed": 0,
  "failed": 0
}
```

Poll `GET /api/v1/batch/{job_id}` to track progress.

---

## Webhooks (coming soon)

Receive a POST to your endpoint when scans complete. Contact support to configure.

---

## Rate Limits

| Plan       | Requests/min | Concurrent scans |
|------------|-------------|-----------------|
| Starter    | 20          | 1               |
| Pro        | 200         | 5               |
| Enterprise | 2000        | 50              |

Exceeded limits return `429 Too Many Requests` with a `Retry-After` header.

---

## Error Format

All errors use standard HTTP status codes with a JSON body:

```json
{
  "detail": "Human-readable error message"
}
```

Common codes:
- `401` — Invalid or missing API key
- `403` — Feature not available on your plan
- `404` — Resource not found
- `422` — Validation error (check request body)
- `429` — Scan limit or rate limit exceeded

---

## OpenAPI / Swagger

Interactive docs (requires API key): `https://api.ropqa.com/docs`
