"""
Simple test script to verify Vertex AI + Gemini 2.5 Flash connection.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types


def test_genai_connection():
    """Test basic connection and generation with Gemini 2.5 Flash."""
    
    # Load environment variables from .env
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    
    # Get credentials from environment or use defaults for testing
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("GCP_LOCATION") or "us-central1"
    
    # Allow CLI override
    if len(sys.argv) > 1:
        project_id = sys.argv[1]
    if len(sys.argv) > 2:
        location = sys.argv[2]
    
    if not project_id:
        print("ERROR: GOOGLE_CLOUD_PROJECT environment variable not set")
        sys.exit(1)
    
    print(f"Initializing Vertex AI client...")
    print(f"  Project: {project_id}")
    print(f"  Location: {location}")
    
    try:
        # Create Vertex AI client
        client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
        )
        print("✓ Client initialized successfully")
        
        # Test simple generation
        print("\nSending test prompt to Gemini 2.5 Flash...")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say 'Hello from Gemini!' in JSON format: {\"message\": \"...\"}",
        )
        print("✓ API call successful")
        
        print(f"\nResponse:")
        print(response.text)
        
        # Test with system instruction and JSON response
        print("\n" + "="*60)
        print("Testing with system instruction and JSON schema...")
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Classify this theme: AUTHORIZED_USER_ACTIVITY",
            config=types.GenerateContentConfig(
                system_instruction="You are a JSON responder. Always respond with valid JSON only.",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "theme": types.Schema(type=types.Type.STRING),
                        "confidence": types.Schema(type=types.Type.STRING),
                        "message": types.Schema(type=types.Type.STRING),
                    },
                    required=["theme", "confidence"],
                ),
                response_mime_type="application/json",
            ),
        )
        print("✓ JSON schema call successful")
        
        print(f"\nJSON Response:")
        print(response.text)
        
        print("\n" + "="*60)
        print("✓✓✓ All tests passed! ✓✓✓")
        print("="*60)
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    test_genai_connection()

