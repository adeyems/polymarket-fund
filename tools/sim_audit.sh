#!/bin/bash
# Check the latest [SIM_AUDIT] line from the production logs

IP="100.50.168.104"
KEY="infra/live/prod/quesquant-key-v2"
LOG="/var/log/quesquant/hft_bot.log"

echo "🔍 Fetching latest Simulation Audit from $IP..."
ssh -i $KEY -o StrictHostKeyChecking=no ec2-user@$IP "grep 'SIM_AUDIT' $LOG | tail -n 1"
