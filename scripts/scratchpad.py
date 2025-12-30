import os
import json
from dotenv import load_dotenv
from langfuse import Langfuse

if __name__ == "__main__":
    load_dotenv()

    # Load credentials from environment
    host = os.getenv("LANGFUSE_HOST")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    cf_token = os.getenv("CF_ACCESS_TOKEN")

    if not all([host, public_key, secret_key]):
        raise ValueError(
            "Missing required env variables: "
            "LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY"
        )

    # Ensure host has protocol
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"

    # Prepare additional headers for Cloudflare Access
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

    # Fetch a single trace by ID
    trace_id = "2b2c94cc66d08789aff3ccfcaccbc9c6"
    try:
        trace = langfuse.api.trace.get(trace_id)

        # Convert to dict for printing
        if hasattr(trace, 'model_dump'):
            trace_dict = trace.model_dump()
        elif hasattr(trace, 'dict'):
            trace_dict = trace.dict()
        else:
            trace_dict = dict(trace)

        print(json.dumps(trace_dict, indent=2, default=str))
    except Exception as e:
        print(f"Error fetching trace: {e}")
        print(f"Trace ID: {trace_id}")
        print(f"Host: {host}")
        if cf_token:
            print(f"CF Token present: {cf_token[:20]}...")
        else:
            print("CF Token: Not found")
        raise
