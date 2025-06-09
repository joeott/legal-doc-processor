#!/usr/bin/env python3
"""Set up CloudWatch alarms for monitoring"""

import boto3
import os

def setup_alarms():
    """Create CloudWatch alarms"""
    
    cloudwatch = boto3.client('cloudwatch')
    sns_topic_arn = os.getenv('SNS_ALERT_TOPIC_ARN')
    
    if not sns_topic_arn:
        print("❌ SNS_ALERT_TOPIC_ARN not set in environment")
        return
    
    alarms = [
        {
            'AlarmName': 'LegalDocProcessor-HighMemoryUsage',
            'MetricName': 'MemoryUsagePercent',
            'Namespace': 'LegalDocProcessor',
            'Statistic': 'Average',
            'Period': 300,  # 5 minutes
            'EvaluationPeriods': 2,
            'Threshold': 85.0,
            'ComparisonOperator': 'GreaterThanThreshold',
            'AlarmDescription': 'Memory usage above 85% for 10 minutes'
        },
        {
            'AlarmName': 'LegalDocProcessor-HighErrorRate',
            'MetricName': 'ErrorRate',
            'Namespace': 'LegalDocProcessor',
            'Statistic': 'Average',
            'Period': 300,
            'EvaluationPeriods': 3,
            'Threshold': 10.0,  # 10%
            'ComparisonOperator': 'GreaterThanThreshold',
            'AlarmDescription': 'Error rate above 10% for 15 minutes'
        },
        {
            'AlarmName': 'LegalDocProcessor-HighQueueDepth',
            'MetricName': 'TotalQueueDepth',
            'Namespace': 'LegalDocProcessor',
            'Statistic': 'Average',
            'Period': 300,
            'EvaluationPeriods': 2,
            'Threshold': 100.0,
            'ComparisonOperator': 'GreaterThanThreshold',
            'AlarmDescription': 'Queue depth above 100 for 10 minutes'
        }
    ]
    
    for alarm in alarms:
        try:
            # Add common properties
            alarm['ActionsEnabled'] = True
            alarm['AlarmActions'] = [sns_topic_arn]
            alarm['TreatMissingData'] = 'notBreaching'
            
            cloudwatch.put_metric_alarm(**alarm)
            print(f"✅ Created alarm: {alarm['AlarmName']}")
            
        except Exception as e:
            print(f"❌ Failed to create alarm {alarm['AlarmName']}: {e}")

if __name__ == "__main__":
    setup_alarms()