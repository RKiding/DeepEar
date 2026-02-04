---
name: DeepEar Analysis Skill
description: A skill that performs financial signal analysis using the DeepEar workflow.
---

# DeepEar Analysis Skill

This skill wraps the DeepEar analysis workflow, allowing you to trigger comprehensive financial signal analysis via an API.

## API Endpoints

### POST /analyze

Triggers the DeepEar analysis workflow.

**Request Body:**

```json
{
  "query": "A-share tech sector",
  "sources": "all",
  "wide": 10,
  "depth": "auto",
  "concurrency": 5,
  "update_from": "20240203_110000"
}
```

- `query` (optional): The user intent or topic to analyze.
- `sources` (optional): News sources ('all', 'financial', 'social', 'tech', or comma-separated). Default: 'all'.
- `wide` (optional): Number of items to fetch per source. Default: 10.
- `depth` (optional): Analysis depth ('auto' or integer). Default: 'auto'.
- `concurrency` (optional): Number of concurrent threads. Default: 5.
- `update_from` (optional): Provide a `run_id` to update an existing analysis with new market data/logic.

**Response:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "submitted_at": "2024-02-04T12:00:00.000000"
}
```

### GET /status/{job_id}

Check the progress and get the result of the analysis job.

**Response (Completed):**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "result": {
    "report_path": "/path/to/DeepEar/reports/daily_report_20240204_1205.html",
    "message": "Analysis completed successfully."
  },
  "timestamp": "2024-02-04T12:05:00.000000"
}
```

## Usage

Run the server:

```bash
uv run skills/deepear/scripts/server.py
```
