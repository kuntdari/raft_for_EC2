#!/bin/bash
#===============================================================================
# S-Raft Start All Nodes Script
#===============================================================================
# 모든 EC2 노드에서 S-Raft 서버를 백그라운드로 시작
#
# 사용법:
#   ./start_all.sh
#===============================================================================

#===============================================================================
# 설정 - deploy_all.sh와 동일하게 수정하세요!
#===============================================================================

SSH_KEY="~/.ssh/your-key.pem"

NODE_IPS=(
    "10.0.1.10"
    "10.0.1.11"
    "10.0.1.12"
    "10.0.1.13"
    "10.0.1.14"
)

PORT=5000
EC2_USER="ec2-user"

#===============================================================================

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# PEERS 문자열 생성
PEERS=""
for ip in "${NODE_IPS[@]}"; do
    if [ -n "$PEERS" ]; then
        PEERS="${PEERS},"
    fi
    PEERS="${PEERS}${ip}:${PORT}"
done

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Starting S-Raft on All Nodes${NC}"
echo -e "${GREEN}============================================${NC}"

for i in "${!NODE_IPS[@]}"; do
    NODE_ID=$((i + 1))
    NODE_IP="${NODE_IPS[$i]}"

    echo -e "${BLUE}[Node $NODE_ID] Starting on $NODE_IP...${NC}"

    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$EC2_USER@$NODE_IP" << REMOTE_SCRIPT
#!/bin/bash

# 기존 프로세스 종료
pkill -f ec2_server.py 2>/dev/null || true
sleep 1

# 환경변수 로드
cd ~/s-raft/raft_for_EC2
source ../raft_env.sh

# 백그라운드로 시작
nohup python3 ec2_server.py --peers "$PEERS" --debug > ~/s-raft/node.log 2>&1 &

echo "Node $NODE_ID started (PID: \$!)"
REMOTE_SCRIPT

    echo -e "${GREEN}[Node $NODE_ID] Started!${NC}"
    sleep 2  # 순차 시작을 위한 대기
done

echo -e "\n${GREEN}============================================${NC}"
echo -e "${GREEN}  All nodes started!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "To check logs:"
echo "  ssh -i $SSH_KEY $EC2_USER@<NODE_IP> 'tail -f ~/s-raft/node.log'"
echo ""
echo "To check status:"
echo "  ./status_all.sh"
