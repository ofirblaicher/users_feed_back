#!/usr/bin/env python3
"""
Fetch all traces from Langfuse for alert IDs in user_feedback.json
and link them with the feedback data for analysis.

Usage:
    uv run scripts/fetch_traces.py
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional
import time

from langfuse import Langfuse


def load_env_variables() -> tuple[str, str, str, str, Optional[str]]:
    """Load Langfuse credentials from .env file."""
    env_path = Path(".env")

    if not env_path.exists():
        raise FileNotFoundError(f".env file not found at {env_path}")

    env_vars = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip().strip('"')

    host = env_vars.get("LANGFUSE_HOST")
    public_key = env_vars.get("LANGFUSE_PUBLIC_KEY")
    secret_key = env_vars.get("LANGFUSE_SECRET_KEY")
    cf_token = env_vars.get("CF_ACCESS_TOKEN")

    if not all([host, public_key, secret_key]):
        raise ValueError(
            "Missing required env variables: "
            "LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY"
        )

    return host, public_key, secret_key, cf_token or "", cf_token


def extract_alert_ids(feedback_file: Path) -> set[str]:
    """Extract unique alert IDs from feedback file."""
    print(f"📖 Loading feedback data from {feedback_file}...")

    try:
        with open(feedback_file) as f:
            content = f.read().strip()
            if content.startswith('['):
                scores = json.loads(content)
            else:
                # Handle NDJSON
                scores = [json.loads(line) for line in content.splitlines() if line.strip()]
    except Exception as e:
        print(f"❌ Error loading feedback data: {e}")
        raise

    alert_ids = set()
    for score in scores:
        metadata = score.get("metadata", {})
        alert_id = metadata.get("alert_id") or score.get("sessionId")
        if alert_id:
            alert_ids.add(alert_id)

    print(f"✅ Found {len(alert_ids)} unique alert IDs")
    return alert_ids


def fetch_observations_for_trace(
    langfuse: Langfuse,
    trace_id: str,
    observation_ids: list[str],
) -> list[dict]:
    """Fetch and filter observations to GENERATION type."""
    generation_observations = []

    for obs_id in observation_ids:
        try:
            obs = langfuse.api.observations.get(obs_id)

            if hasattr(obs, 'model_dump'):
                obs_dict = obs.model_dump()
            elif hasattr(obs, 'dict'):
                obs_dict = obs.dict()
            else:
                obs_dict = dict(obs)

            # Filter to GENERATION type and extract only input,
            # output, metadata
            if obs_dict.get('type') == 'GENERATION':
                generation_observations.append({
                    'input': obs_dict.get('input'),
                    'output': obs_dict.get('output'),
                    'metadata': obs_dict.get('metadata', {}),
                    'id': obs_dict.get('id'),
                    'name': obs_dict.get('name'),
                    'model': obs_dict.get('model'),
                })
        except Exception as e:
            msg = f"Error fetching observation {obs_id}: {e}"
            print(f"    ⚠️  {msg}")
            continue

    return generation_observations


def fetch_traces_from_langfuse(
    alert_ids: set[str],
    host: str,
    public_key: str,
    secret_key: str,
    cf_token: str,
    test_mode: bool = False,
    test_limit: int = 5,
) -> dict[str, dict]:
    """Fetch traces and their GENERATION observations from Langfuse."""
    from langfuse import Langfuse

    print(f"\n🌐 Connecting to Langfuse at {host}...")

    # Prepare additional headers for Cloudflare Access
    # (key insight from scratchpad.py)
    additional_headers = {}
    if cf_token:
        additional_headers["cf-access-token"] = cf_token

    # Create Langfuse client with Cloudflare Access token
    langfuse = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
        additional_headers=additional_headers if additional_headers else None
    )

    print("✅ Using Langfuse SDK client with CF Access headers")

    traces_by_alert = {}
    alert_ids_list = sorted(list(alert_ids))

    # Limit alerts in test mode
    if test_mode:
        alert_ids_list = alert_ids_list[:test_limit]
        msg = f"TEST MODE: Processing only {len(alert_ids_list)} alerts"
        print(f"⚠️  {msg}")

    print(f"\n📡 Fetching {len(alert_ids_list)} traces...")
    print("=" * 80)

    for idx, alert_id in enumerate(alert_ids_list, 1):
        try:
            # Use the Langfuse SDK's API to list traces by session_id
            # The API should support filtering by session_id parameter
            traces_response = langfuse.api.trace.list(
                session_id=alert_id,
                limit=100
            )

            # Convert trace objects to dicts for JSON serialization
            if traces_response and hasattr(traces_response, 'data'):
                traces_list = []
                for trace in traces_response.data:
                    # Convert trace to dict
                    if hasattr(trace, 'model_dump'):
                        trace_dict = trace.model_dump()
                    elif hasattr(trace, 'dict'):
                        trace_dict = trace.dict()
                    else:
                        trace_dict = dict(trace)

                    # Fetch observations for this trace
                    trace_id = trace_dict.get('id')
                    observation_ids = trace_dict.get('observations', [])
                    if trace_id and observation_ids:
                        observations = fetch_observations_for_trace(
                            langfuse, trace_id, observation_ids
                        )
                        trace_dict['observations'] = observations

                        if idx == 1 and observations:
                            obs_msg = (
                                f"Fetched {len(observations)} GENERATION "
                                "observation(s) for first trace"
                            )
                            print(f"  ✅ {obs_msg}")
                    else:
                        # Clear observations if no IDs or can't fetch
                        trace_dict['observations'] = []

                    traces_list.append(trace_dict)

                traces_by_alert[alert_id] = traces_list

                if idx == 1 and traces_list:
                    msg = (
                        f"Successfully fetched {len(traces_list)} "
                        "trace(s) for first alert"
                    )
                    print(f"  ✅ {msg}")
            else:
                traces_by_alert[alert_id] = []

            if idx % 50 == 0:
                print(
                    f"[{idx}/{len(alert_ids_list)}] "
                    f"Fetched {idx} traces..."
                )
                time.sleep(0.1)  # Small rate limiting

        except Exception as e:
            if idx == 1:
                error_msg = (
                    f"Error on first trace: {type(e).__name__}: "
                    f"{str(e)[:200]}"
                )
                print(f"  ⚠️  {error_msg}")
                import traceback
                print(f"  Full traceback:\n{traceback.format_exc()}")
            traces_by_alert[alert_id] = []

    print("=" * 80)
    successful = sum(1 for traces in traces_by_alert.values() if traces)
    print(
        f"✅ Successfully fetched traces for {successful}/"
        f"{len(alert_ids_list)} alerts"
    )
    return traces_by_alert


def create_linked_data(
    feedback_file: Path,
    traces_by_alert: dict[str, dict],
) -> list[dict]:
    """Create linked data combining feedback and traces."""
    print("\n🔗 Linking feedback with traces...")

    try:
        with open(feedback_file) as f:
            content = f.read().strip()
            if content.startswith('['):
                scores = json.loads(content)
            else:
                # Handle NDJSON
                scores = [json.loads(line) for line in content.splitlines() if line.strip()]
    except Exception as e:
        print(f"❌ Error loading feedback data for linking: {e}")
        raise

    # Group feedback scores by alert_id
    feedback_by_alert = {}
    for score in scores:
        metadata = score.get("metadata", {})
        alert_id = metadata.get("alert_id") or score.get("sessionId")
        if alert_id:
            if alert_id not in feedback_by_alert:
                feedback_by_alert[alert_id] = {
                    "alert_id": alert_id,
                    "feedback_scores": [],
                    "traces": traces_by_alert.get(alert_id, []),
                    "metadata": metadata,
                }
            feedback_by_alert[alert_id]["feedback_scores"].append(score)

    # Convert to list sorted by alert_id
    linked_data = sorted(
        feedback_by_alert.values(),
        key=lambda x: x["alert_id"]
    )

    return linked_data


def save_linked_data(
    linked_data: list[dict],
    output_file: Path,
) -> None:
    """Save linked data to JSON file."""
    print(f"\n💾 Saving linked data to {output_file}...")

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w") as f:
        json.dump(linked_data, f, indent=2, default=str)

    print(f"✅ Saved {len(linked_data)} alert records")
    total_scores = sum(
        len(r['feedback_scores']) for r in linked_data
    )
    print(f"   - Total feedback scores: {total_scores}")
    total_traces = sum(len(r['traces']) for r in linked_data)
    print(f"   - Total traces: {total_traces}")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Fetch traces from Langfuse and link with feedback data"
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode: process only a limited number of alerts'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=5,
        help='Number of alerts to process in test mode (default: 5)'
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    feedback_file = project_root / "data" / "user_feedback.json"
    output_file = project_root / "data" / "feedback_alerts.json"

    print("=" * 80)
    print("LANGFUSE TRACE FETCHER")
    print("=" * 80)
    print()

    try:
        # Load environment variables
        host, public_key, secret_key, cf_header, cf_token = (
            load_env_variables()
        )
        print("✅ Loaded Langfuse credentials")
        print(f"   Host: {host}")
        print(f"   Public Key: {public_key[:20]}...")

        # Extract alert IDs from feedback
        alert_ids = extract_alert_ids(feedback_file)

        # Fetch traces from Langfuse
        traces_by_alert = fetch_traces_from_langfuse(
            alert_ids,
            host,
            public_key,
            secret_key,
            cf_token,
            test_mode=args.test,
            test_limit=args.limit
        )

        # Create linked data
        linked_data = create_linked_data(feedback_file, traces_by_alert)

        # Save to file
        save_linked_data(linked_data, output_file)

        print()
        print("=" * 80)
        print("✅ SUCCESS!")
        print("=" * 80)
        print()
        print("📊 Next steps:")
        print(
            "   1. Use alert_id to link between feedback and traces"
        )
        print(
            "   2. Access feedback_scores for triage confirmation data"
        )
        print(
            "   3. Access traces for raw alert/detection data"
        )
        print(
            "   4. Access observations within traces for "
            "GENERATION LLM outputs"
        )
        print()

    except Exception as e:
        print()
        print("=" * 80)
        print(f"❌ ERROR: {e}")
        print("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
