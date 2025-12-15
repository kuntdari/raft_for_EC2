#!/bin/bash
#===============================================================================
# S-Raft Status Check Script
#===============================================================================

SSH_KEY="~/.ssh/your-key.pem"

NODE_IPS=(
    "10.0.1.10"
    "10.0.1.11"
    "10.0.1.12"
    "10.0.1.13"
    "10.0.1.14"
)

EC2_USER="ec2-user"

echo "============================================"
echo "  S-Raft Cluster Status"
echo "============================================"
echo ""

for i in "${!NODE_IPS[@]}"; do
    NODE_ID=$((i + 1))
    NODE_IP="${NODE_IPS[$i]}"

    echo "[Node $NODE_ID] $NODE_IP"

    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$EC2_USER@$NODE_IP" << 'REMOTE_SCRIPT' 2>/dev/null
# 프로세스 확인
PID=$(pgrep -f ec2_server.py)
if [ -n "$PID" ]; then
    echo "  Status: Running (PID: $PID)"

    # 최근 로그 확인
    if [ -f ~/s-raft/node.log ]; then
        LAST_LOG=$(tail -1 ~/s-raft/node.log 2>/dev/null)
        echo "  Last log: $LAST_LOG"
    fi
else
    echo "  Status: Stopped"
fi
REMOTE_SCRIPT

    echo ""
done
