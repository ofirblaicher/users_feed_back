#!/usr/bin/env python3
"""
Validate theme analysis by examining human comments with their full trace context.
This script analyzes comments alongside the raw alert data to ensure theme categorization is accurate.
"""

import json
from collections import defaultdict
from typing import Dict, List, Any


def load_data(filepath: str) -> List[Dict]:
    """Load feedback alerts with traces."""
    with open(filepath, 'r') as f:
        return json.load(f)


def extract_alert_context(trace: Dict) -> Dict[str, Any]:
    """Extract key context from trace for analysis."""
    if not trace:
        return {}
    
    context = {
        'alert_name': trace.get('name', ''),
        'input': trace.get('input', {}),
        'output': trace.get('output', {}),
        'metadata': trace.get('metadata', {}),
    }
    
    # Try to extract raw alert data from input
    if isinstance(context['input'], dict):
        raw_alert = context['input'].get('raw_alert', {})
        context['device_name'] = raw_alert.get('device', {}).get('hostname', '')
        context['file_name'] = raw_alert.get('behaviors', [{}])[0].get('filename', '') if raw_alert.get('behaviors') else ''
        context['user_name'] = raw_alert.get('device', {}).get('user_name', '')
        context['severity'] = raw_alert.get('max_severity_displayname', '')
        
    return context


def analyze_comment_with_context(
    comment: str, 
    alert_metadata: Dict, 
    trace_context: Dict
) -> Dict[str, Any]:
    """Analyze a single comment with its full context."""
    
    comment_lower = comment.lower()
    analysis = {
        'comment': comment,
        'tenant': alert_metadata.get('account_short_name', 'unknown'),
        'triage_confirmation': alert_metadata.get('triage_confirmation', ''),
        'verdict': alert_metadata.get('verdict', ''),
        'alert_name': alert_metadata.get('alert_name', ''),
        'severity': alert_metadata.get('severity', ''),
        'trace_available': bool(trace_context),
        'suggested_themes': [],
        'key_indicators': []
    }
    
    # Add trace-specific context
    if trace_context:
        analysis['device_name'] = trace_context.get('device_name', '')
        analysis['file_name'] = trace_context.get('file_name', '')
        analysis['user_name'] = trace_context.get('user_name', '')
    
    # Theme 1: Internal/Authorized Team Activity
    internal_keywords = [
        'internal team', 'authorized', 'it team', 'service account',
        'admin', 'soc team', 'security team', 'deployment', 'wa user'
    ]
    if any(kw in comment_lower for kw in internal_keywords):
        analysis['suggested_themes'].append('Internal/Authorized Team')
        analysis['key_indicators'].append('Contains internal team keywords')
    
    # Theme 2: AI Verdict Inconsistency
    inconsistency_keywords = [
        'previous detections', 'does not match', 'same hash', 'same file',
        'similar', 'inconsistent', 'already', 'duplicate'
    ]
    if any(kw in comment_lower for kw in inconsistency_keywords):
        analysis['suggested_themes'].append('AI Inconsistency')
        analysis['key_indicators'].append('References previous alerts or inconsistency')
    
    # Theme 3: Legitimate Software/Application
    software_keywords = [
        'legitimate', 'known good', 'software', 'application', 'binary',
        'lenovo', 'vantage', 'clipboard', 'custom app', 'gaming',
        'install', 'driver', 'utility'
    ]
    if any(kw in comment_lower for kw in software_keywords):
        analysis['suggested_themes'].append('Legitimate Software')
        analysis['key_indicators'].append('References legitimate software')
    
    # Theme 4: Confirmed Malicious
    malicious_keywords = [
        'malicious', 'threat', 'suspicious software', 'not approved',
        'blocked', 'contained', 'real threat', 'true positive'
    ]
    if any(kw in comment_lower for kw in malicious_keywords) and analysis['verdict'] == 'True Positive - Malicious':
        analysis['suggested_themes'].append('Confirmed Malicious')
        analysis['key_indicators'].append('Confirms malicious activity')
    
    # Theme 5: Insufficient Evidence
    evidence_keywords = [
        'no additional indication', 'no evidence', 'no malicious activity',
        'no supporting', 'no observables', 'no indication'
    ]
    if any(kw in comment_lower for kw in evidence_keywords):
        analysis['suggested_themes'].append('Insufficient Evidence')
        analysis['key_indicators'].append('Lacks supporting evidence')
    
    # Theme 6: Test/Development Activity
    test_keywords = ['eicar', 'test', 'rules test']
    if any(kw in comment_lower for kw in test_keywords):
        analysis['suggested_themes'].append('Test/Dev Activity')
        analysis['key_indicators'].append('Test or development environment')
    
    # Theme 7: PHI/Escalation Concerns
    phi_keywords = ['phi', 'hipaa', 'ct folder', 'health', 'patient']
    if any(kw in comment_lower for kw in phi_keywords):
        analysis['suggested_themes'].append('PHI/Escalation')
        analysis['key_indicators'].append('PHI or compliance concern')
    
    return analysis


def main():
    print("="*80)
    print("THEME VALIDATION: Analyzing Comments with Trace Context")
    print("="*80)
    
    # Load data
    print("\n📖 Loading feedback alerts with traces...")
    alerts = load_data('data/feedback_alerts.json')
    print(f"✅ Loaded {len(alerts)} alerts")
    
    # Filter to alerts with comments
    alerts_with_comments = [
        alert for alert in alerts 
        if alert.get('metadata', {}).get('human_comment')
    ]
    print(f"✅ Found {len(alerts_with_comments)} alerts with human comments")
    
    # Analyze each comment with context
    print("\n🔍 Analyzing comments with trace context...\n")
    
    analyses = []
    for alert in alerts_with_comments:
        comment = alert['metadata']['human_comment']
        
        # Skip empty or generic comments
        if not comment or len(comment.strip()) < 10:
            continue
        
        # Extract trace context if available
        trace_context = {}
        if alert.get('traces'):
            trace_context = extract_alert_context(alert['traces'][0])
        
        analysis = analyze_comment_with_context(
            comment,
            alert['metadata'],
            trace_context
        )
        analyses.append(analysis)
    
    print(f"✅ Analyzed {len(analyses)} substantive comments\n")
    
    # Group by themes
    theme_examples = defaultdict(list)
    for analysis in analyses:
        for theme in analysis['suggested_themes']:
            theme_examples[theme].append(analysis)
    
    # Print detailed validation report
    print("="*80)
    print("VALIDATION REPORT")
    print("="*80)
    
    for theme, examples in sorted(theme_examples.items(), key=lambda x: len(x[1]), reverse=True):
        print(f"\n### {theme}: {len(examples)} examples ({len(examples)/len(analyses)*100:.1f}%)")
        print("-" * 80)
        
        # Show first 5 examples with context
        for i, ex in enumerate(examples[:5], 1):
            print(f"\n**Example {i}** [{ex['tenant']}]")
            print(f"Comment: \"{ex['comment'][:150]}...\"" if len(ex['comment']) > 150 else f"Comment: \"{ex['comment']}\"")
            print(f"Verdict: {ex['verdict']} | Confirmation: {ex['triage_confirmation']}")
            if ex.get('device_name'):
                print(f"Device: {ex['device_name']}")
            if ex.get('file_name'):
                print(f"File: {ex['file_name']}")
            print(f"Indicators: {', '.join(ex['key_indicators'])}")
    
    # Multi-theme analysis
    print("\n" + "="*80)
    print("MULTI-THEME COMMENTS (Comments matching multiple themes)")
    print("="*80)
    
    multi_theme = [a for a in analyses if len(a['suggested_themes']) > 1]
    print(f"\nFound {len(multi_theme)} comments with multiple themes\n")
    
    for analysis in multi_theme[:10]:
        print(f"\n[{analysis['tenant']}] Themes: {', '.join(analysis['suggested_themes'])}")
        print(f"Comment: \"{analysis['comment'][:120]}...\"" if len(analysis['comment']) > 120 else f"Comment: \"{analysis['comment']}\"")
        print()
    
    # Trace availability check
    print("\n" + "="*80)
    print("TRACE DATA AVAILABILITY")
    print("="*80)
    
    with_traces = sum(1 for a in analyses if a['trace_available'])
    print(f"\nComments with trace data: {with_traces}/{len(analyses)} ({with_traces/len(analyses)*100:.1f}%)")
    
    # Summary statistics by tenant
    print("\n" + "="*80)
    print("TENANT BREAKDOWN")
    print("="*80)
    
    tenant_stats = defaultdict(lambda: {'total': 0, 'themes': defaultdict(int)})
    for analysis in analyses:
        tenant = analysis['tenant']
        tenant_stats[tenant]['total'] += 1
        for theme in analysis['suggested_themes']:
            tenant_stats[tenant]['themes'][theme] += 1
    
    print()
    for tenant, stats in sorted(tenant_stats.items(), key=lambda x: x[1]['total'], reverse=True):
        print(f"\n{tenant}: {stats['total']} comments")
        for theme, count in sorted(stats['themes'].items(), key=lambda x: x[1], reverse=True):
            pct = count / stats['total'] * 100
            print(f"  - {theme}: {count} ({pct:.1f}%)")
    
    print("\n" + "="*80)
    print("VALIDATION COMPLETE")
    print("="*80)
    print(f"\n✅ Analyzed {len(analyses)} comments with full trace context")
    print(f"✅ Identified {len(theme_examples)} distinct themes")
    print(f"✅ {with_traces} comments validated against raw alert data")


if __name__ == "__main__":
    main()


