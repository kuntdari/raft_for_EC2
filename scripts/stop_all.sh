#!/bin/bash
#===============================================================================
# S-Raft Stop All Nodes Script
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
echo "  Stopping S-Raft on All Nodes"
echo "============================================"

for i in "${!NODE_IPS[@]}"; do
    NODE_ID=$((i + 1))
    NODE_IP="${NODE_IPS[$i]}"

    echo "[Node $NODE_ID] Stopping on $NODE_IP..."

    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$EC2_USER@$NODE_IP" \
        "pkill -f ec2_server.py 2>/dev/null || echo 'Not running'"

    echo "[Node $NODE_ID] Stopped"
done

echo ""
echo "All nodes stopped!"
