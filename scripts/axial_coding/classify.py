"""
Main classification workflow for theme assignment.

Classifies feedback items using Gemini 2.5 Flash via Vertex AI.
Supports resumption, crash recovery, and limiting for testing.
"""

import json
import os
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from google import genai
from google.genai import types
from scripts.axial_coding.prompt import (
    SYSTEM_PROMPT,
    format_user_prompt,
    VALID_THEMES,
    GLOBAL_TRENDS_PROMPT,
)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ThemeClassifier:
    """Classifies feedback items into predefined themes using Gemini."""

    def __init__(
        self,
        project_id: str,
        location: str = "us-central1",
        output_file: str = "data/axial_coding.json",
    ):
        """
        Initialize classifier.
        
        Args:
            project_id: GCP project ID for Vertex AI
            location: GCP location (default: us-central1)
            output_file: Path to write NDJSON results
        """
        self.project_id = project_id
        self.location = location
        self.output_file = Path(output_file)
        
        # Initialize Vertex AI client
        logger.info(f"Initializing Vertex AI client (project={project_id}, location={location})")
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
        )
        
        # Track processed items for resume support
        self.processed_ids = self._load_processed_ids()
        logger.info(f"Loaded {len(self.processed_ids)} previously processed items")
    
    def _load_processed_ids(self) -> set:
        """Load alert_ids that have already been processed."""
        if not self.output_file.exists():
            return set()
        
        processed = set()
        try:
            with open(self.output_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            data = json.loads(line)
                            processed.add(data.get("alert_id"))
                        except json.JSONDecodeError:
                            logger.warning(f"Skipping malformed JSON line: {line[:50]}")
        except Exception as e:
            logger.error(f"Error loading processed IDs: {e}")
        
        return processed
    
    def _save_result(self, result: Dict[str, Any]) -> None:
        """Append classification result to NDJSON file."""
        try:
            with open(self.output_file, 'a') as f:
                f.write(json.dumps(result) + '\n')
            logger.debug(f"Saved result for {result['alert_id']}")
        except Exception as e:
            logger.error(f"Error saving result: {e}")
            raise
    
    def classify_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Classify a single feedback item.
        
        Args:
            item: Feedback item from feedback_alerts.json
            
        Returns:
            Classification result dict or None if classification fails
        """
        alert_id = item.get("alert_id")
        
        # Skip if already processed
        if alert_id in self.processed_ids:
            logger.debug(f"Skipping already processed: {alert_id}")
            return None
        
        try:
            # Extract required fields
            metadata = item.get("metadata", {})
            human_comment = metadata.get("human_comment", "")
            
            # Fallback: Check feedback_scores for comments if not in metadata
            if not human_comment:
                scores = item.get("feedback_scores", [])
                for score in scores:
                    comment = score.get("comment") or score.get("value")
                    if isinstance(comment, str) and len(comment.strip()) > 10:
                        human_comment = comment
                        break
            
            if not human_comment or len(human_comment.strip()) < 10:
                logger.debug(f"Skipping {alert_id}: comment too short")
                return None
            
            # Extract GENERATION data if available
            traces = item.get("traces", [])
            ai_verdict = "N/A"
            ai_justification = "N/A"
            event_summary = "N/A"
            investigative_gaps = "N/A"
            
            if traces and len(traces) > 0:
                observations = traces[0].get("observations", [])
                for obs in observations:
                    if (obs.get("type") == "GENERATION" \
                    or obs.get("name") == "llm:generate") \
                    and obs.get("output"):
                        content = obs["output"].get("content", "")
                        try:
                            # Try to parse generation content
                            json_str = content.replace('```json\n', '').replace('```', '').strip()
                            gen_data = json.loads(json_str)
                            if isinstance(gen_data, dict) and "properties" in gen_data:
                                gen_data = gen_data["properties"]
                            
                            ai_verdict = gen_data.get("final_decision", "N/A")
                            ai_justification = gen_data.get("justification", "N/A")
                            event_summary = gen_data.get("event_summary", "N/A")
                            gaps = gen_data.get("investigative_gaps", [])
                            investigative_gaps = ", ".join(gaps) if gaps else "N/A"
                        except json.JSONDecodeError:
                            pass
                        break
            
            # Format user prompt
            user_prompt = format_user_prompt(
                alert_id=alert_id,
                tenant=metadata.get("account_short_name", "Unknown"),
                human_comment=human_comment,
                human_verdict=metadata.get("verdict", "N/A"),
                confirmation_status=metadata.get("triage_confirmation", "N/A"),
                ai_verdict=ai_verdict,
                ai_justification=ai_justification,  # Truncate for prompt length
                event_summary=event_summary,
                investigative_gaps=investigative_gaps,
            )
            
            # Call Gemini
            logger.info(f"Classifying {alert_id}...")
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_schema=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "theme": types.Schema(type=types.Type.STRING),
                            "confidence": types.Schema(type=types.Type.STRING),
                            "reasoning": types.Schema(type=types.Type.STRING),
                            "missing_context": types.Schema(type=types.Type.STRING),
                            "trend_insight": types.Schema(type=types.Type.STRING),
                        },
                        required=["theme", "confidence", "reasoning", "trend_insight"],
                    ),
                    response_mime_type="application/json",
                ),
            )
            
            # Parse response
            try:
                result_data = json.loads(response.text)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse response for {alert_id}: {response.text[:200]}")
                return None
            
            # Validate theme
            theme = result_data.get("theme", "OTHER")
            if theme not in VALID_THEMES:
                logger.warning(f"Invalid theme {theme} for {alert_id}, using OTHER")
                theme = "OTHER"
            
            # Build result
            result = {
                "alert_id": alert_id,
                "theme": theme,
                "confidence": result_data.get("confidence", "UNKNOWN"),
                "reasoning": result_data.get("reasoning", ""),
                "missing_context": result_data.get("missing_context", ""),
                "trend_insight": result_data.get("trend_insight", ""),
                "processed_at": datetime.utcnow().isoformat() + "Z",
            }
            
            logger.info(f"✓ {alert_id}: {theme} ({result['confidence']})")
            return result
            
        except Exception as e:
            logger.error(f"Error classifying {alert_id}: {e}", exc_info=True)
            return None
    
    def run(self, feedback_data: list, limit: Optional[int] = None, num_workers: int = 5) -> int:
        """
        Run classification on feedback data with parallel processing.
        
        Args:
            feedback_data: List of feedback items from feedback_alerts.json
            limit: Maximum number of items to process (for testing)
            num_workers: Number of parallel worker threads (default: 5)
            
        Returns:
            Number of items successfully classified
        """
        # Filter to items with comments
        items_with_comments = []
        for item in feedback_data:
            metadata = item.get("metadata", {})
            comment = metadata.get("human_comment")
            
            # Fallback for checking feedback_scores
            if not comment:
                for score in item.get("feedback_scores", []):
                    s_comment = score.get("comment")
                    if isinstance(s_comment, str) and len(s_comment.strip()) > 10:
                        comment = s_comment
                        break
            
            # Check if comment is a string and has sufficient length
            if isinstance(comment, str) and len(comment.strip()) > 10:
                items_with_comments.append(item)
        
        logger.info(f"Found {len(items_with_comments)} items with valid comments")
        
        # Apply limit if specified
        if limit:
            items_with_comments = items_with_comments[:limit]
            logger.info(f"Limiting to {limit} items for testing")
        
        # Skip already processed items
        to_process = [
            item for item in items_with_comments
            if item.get("alert_id") not in self.processed_ids
        ]
        
        logger.info(f"Processing {len(to_process)} new items with {num_workers} workers")
        
        success_count = 0
        completed_count = 0
        
        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            # Submit all tasks
            future_to_item = {
                executor.submit(self.classify_item, item): item 
                for item in to_process
            }
            
            # Process results as they complete
            for future in as_completed(future_to_item):
                completed_count += 1
                result = future.result()
                
                if result:
                    self._save_result(result)
                    success_count += 1
                    self.processed_ids.add(result["alert_id"])
                
                # Progress indicator
                progress_pct = (completed_count / len(to_process)) * 100
                progress_bar = self._get_progress_bar(completed_count, len(to_process))
                logger.info(f"{progress_bar} {completed_count}/{len(to_process)} ({progress_pct:.1f}%)")
        
        logger.info(f"Classification complete: {success_count}/{len(to_process)} successful")
        return success_count

    def generate_global_trends(self, results_data: list) -> Dict[str, Any]:
        """Analyze all classification results to extract global security trends."""
        logger.info(f"Generating global trend analysis for {len(results_data)} alerts...")
        
        # Prepare data for the prompt (compact format to save tokens)
        compact_data = []
        for r in results_data:
            compact_data.append({
                "theme": r.get("theme"),
                "insight": r.get("trend_insight"),
                "tenant": r.get("tenant") or "Unknown"
            })
        
        user_prompt = f"Analyze these {len(compact_data)} classification insights:\n\n{json.dumps(compact_data, indent=2)}"
        
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=GLOBAL_TRENDS_PROMPT,
                    response_schema=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "trends": types.Schema(
                                type=types.Type.ARRAY,
                                items=types.Schema(
                                    type=types.Type.OBJECT,
                                    properties={
                                        "title": types.Schema(type=types.Type.STRING),
                                        "description": types.Schema(type=types.Type.STRING),
                                        "affected_tenants": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
                                        "severity": types.Schema(type=types.Type.STRING),
                                        "recommendation": types.Schema(type=types.Type.STRING),
                                    },
                                    required=["title", "description", "severity"]
                                )
                            ),
                            "summary": types.Schema(type=types.Type.STRING),
                        },
                        required=["trends", "summary"],
                    ),
                    response_mime_type="application/json",
                ),
            )
            
            trends_result = json.loads(response.text)
            
            # Save to global_trends.json
            global_trends_file = self.output_file.parent / "global_trends.json"
            with open(global_trends_file, 'w') as f:
                json.dump(trends_result, f, indent=2)
            
            logger.info(f"Global trends saved to {global_trends_file}")
            return trends_result
            
        except Exception as e:
            logger.error(f"Error generating global trends: {e}", exc_info=True)
            return {"trends": [], "summary": "Error generating trends."}
    
    def _get_progress_bar(self, completed: int, total: int, bar_length: int = 30) -> str:
        """Generate a simple progress bar string."""
        if total == 0:
            return "[" + "=" * bar_length + "]"
        
        filled = int((completed / total) * bar_length)
        bar = "=" * filled + "-" * (bar_length - filled)
        return f"[{bar}]"


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Classify feedback items into themes using Gemini 2.5 Flash"
    )
    parser.add_argument(
        "--project",
        required=False,
        help="GCP project ID (or set GOOGLE_CLOUD_PROJECT env var)",
    )
    parser.add_argument(
        "--location",
        default="us-central1",
        help="GCP location (default: us-central1)",
    )
    parser.add_argument(
        "--input",
        default="data/feedback_alerts.json",
        help="Path to feedback_alerts.json",
    )
    parser.add_argument(
        "--output",
        default="data/axial_coding.json",
        help="Path to output NDJSON file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit to N items (for testing)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of parallel worker threads (default: 5)",
    )
    parser.add_argument(
        "--global-trends",
        action="store_true",
        help="Generate global trend analysis after individual classification",
    )
    
    args = parser.parse_args()
    
    # Load env if available
    load_dotenv()
    
    # Get project ID
    project_id = args.project or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        logger.error("GCP project ID required (--project or GOOGLE_CLOUD_PROJECT env var)")
        sys.exit(1)
    
    # Load feedback data
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)
    
    logger.info(f"Loading feedback data from {input_path}")
    with open(input_path, 'r') as f:
        feedback_data = json.load(f)
    logger.info(f"Loaded {len(feedback_data)} feedback items")
    
    # Run classifier
    classifier = ThemeClassifier(
        project_id=project_id,
        location=args.location,
        output_file=args.output,
    )
    
    success_count = classifier.run(feedback_data, limit=args.limit, num_workers=args.workers)
    
    # Optional global trend analysis
    if args.global_trends:
        # Reload results to ensure we have all of them (including resume)
        all_results = []
        if Path(args.output).exists():
            with open(args.output, 'r') as f:
                for line in f:
                    if line.strip():
                        all_results.append(json.loads(line))
        
        # Add tenant info for analysis
        tenant_map = {item['alert_id']: item.get('metadata', {}).get('account_short_name', 'Unknown') 
                     for item in feedback_data}
        for res in all_results:
            res['tenant'] = tenant_map.get(res['alert_id'], 'Unknown')
            
        classifier.generate_global_trends(all_results)
    
    logger.info(f"Successfully classified {success_count} items")
    logger.info(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()

