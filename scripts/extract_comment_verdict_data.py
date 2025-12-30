import json
import os

def parse_generation_content(content):
    """Extract data from LLM generation output."""
    if not content:
        return {}
    
    try:
        # Remove markdown code blocks if present
        json_str = content.replace('```json\n', '').replace('```', '').strip()
        parsed = json.loads(json_str)
        # Unwrap if nested in 'properties' key
        if isinstance(parsed, dict) and 'properties' in parsed:
            parsed = parsed['properties']
        return parsed
    except (json.JSONDecodeError, AttributeError):
        return {}

def extract_generation_data(observations):
    """Extract GENERATION observation data."""
    if not observations:
        return {}
    
    for obs in observations:
        if obs.get('name') == 'llm:generate' or obs.get('type') == 'GENERATION':
            if obs.get('output') and obs['output'].get('content'):
                gen_data = parse_generation_content(obs['output']['content'])
                return {
                    'event_summary': gen_data.get('event_summary', ''),
                    'final_decision': gen_data.get('final_decision',
                                                    gen_data.get('primary_assessment', '')),
                    'justification': gen_data.get('justification',
                                                  gen_data.get('primary_summary', '')),
                    'investigative_gaps': gen_data.get('investigative_gaps', []),
                }
    return {}

def main():
    project_root = Path(__file__).resolve().parent.parent
    data_path = project_root / "data" / "feedback_alerts.json"
    output_path = project_root / "docs" / "research" / "data_first_eda" / "comment_verdict_alignment.md"
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load data
    if not data_path.exists():
        print(f"❌ Error: Data file not found at {data_path}")
        return
    
    with open(data_path, 'r') as f:
        data = json.load(f)
    
    # Filter to items with non-empty comments
    items_with_comments = [
        item for item in data
        if item.get('metadata', {}).get('human_comment')
        and isinstance(item['metadata']['human_comment'], str)
        and len(item['metadata']['human_comment'].strip()) > 10
    ]
    
    # Generate markdown
    md_lines = [
        '# Comment & Verdict Alignment Data',
        '',
        f'**Total items with comments**: {len(items_with_comments)}',
        '',
        'This file contains extracted data for manual AI analysis.',
        'Each entry shows: Human Comment + LLM GENERATION Data for cross-reference validation.',
        '',
        '---',
        '',
    ]
    
    for idx, item in enumerate(items_with_comments, 1):
        alert_id = item.get('alert_id', 'N/A')
        metadata = item.get('metadata', {})
        tenant = metadata.get('account_short_name', 'N/A')
        comment = metadata.get('human_comment', 'N/A')
        confirmation = metadata.get('triage_confirmation', 'N/A')
        verdict = metadata.get('verdict', 'N/A')
        
        # Extract LLM generation data
        traces = item.get('traces', [])
        gen_data = {}
        if traces:
            observations = traces[0].get('observations', [])
            gen_data = extract_generation_data(observations)
        
        # Format entry
        md_lines.extend([
            f'## [{idx}] {alert_id[:8]}... ({tenant})',
            '',
            '### Human Input',
            f'- **Comment**: {comment}',
            f'- **Confirmation**: {confirmation}',
            f'- **Verdict**: {verdict}',
            '',
            '### LLM GENERATION Data',
            f'- **Event Summary**: {gen_data.get("event_summary", "N/A")}',
            f'- **Final Decision**: {gen_data.get("final_decision", "N/A")}',
            f'- **Justification**: {gen_data.get("justification", "N/A")}',
        ])
        
        gaps = gen_data.get('investigative_gaps', [])
        if gaps:
            md_lines.append(f'- **Investigative Gaps**: {", ".join(gaps)}')
        
        md_lines.extend([
            '',
            '---',
            '',
        ])
    
    # Write output
    with open(output_path, 'w') as f:
        f.write('\n'.join(md_lines))
    
    print(f"✅ Extraction complete!")
    print(f"📊 Processed {len(items_with_comments)} items with comments")
    print(f"📁 Output: {output_path}")

if __name__ == '__main__':
    main()

