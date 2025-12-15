#!/bin/bash
#===============================================================================
# S-Raft Multi-Node Deployment Script
#===============================================================================
# 여러 EC2 인스턴스에 S-Raft를 한 번에 배포하는 스크립트
#
# 사전 요구사항:
# 1. EC2 인스턴스 5개 생성 완료
# 2. SSH 키 파일 (.pem) 준비
# 3. 보안 그룹에서 포트 5000, 22 허용
#
# 사용법:
#   ./deploy_all.sh
#===============================================================================

#===============================================================================
# 설정 - 여기를 수정하세요!
#===============================================================================

# SSH 키 파일 경로
SSH_KEY="~/.ssh/your-key.pem"

# EC2 인스턴스 프라이빗 IP 주소 (5개)
# AWS 콘솔에서 확인 후 입력하세요
NODE_IPS=(
    "10.0.1.10"   # Node 1
    "10.0.1.11"   # Node 2
    "10.0.1.12"   # Node 3
    "10.0.1.13"   # Node 4
    "10.0.1.14"   # Node 5
)

# 포트 번호
PORT=5000

# GitHub 레포지토리 (본인의 레포지토리로 변경)
GITHUB_REPO="your-username/s-raft-ec2"
BRANCH="main"

# S-Raft 모드 (true: S-Raft, false: Original Raft)
ENABLE_SUBLEADER="true"

# EC2 사용자 (Amazon Linux: ec2-user, Ubuntu: ubuntu)
EC2_USER="ec2-user"

#===============================================================================
# 스크립트 시작
#===============================================================================

set -e

# 색상 출력
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  S-Raft Multi-Node Deployment${NC}"
echo -e "${GREEN}============================================${NC}"

# PEERS 문자열 생성
PEERS=""
for ip in "${NODE_IPS[@]}"; do
    if [ -n "$PEERS" ]; then
        PEERS="${PEERS},"
    fi
    PEERS="${PEERS}${ip}:${PORT}"
done

echo "  Nodes: ${#NODE_IPS[@]}"
echo "  Peers: $PEERS"
echo "  Mode: $([ "$ENABLE_SUBLEADER" = "true" ] && echo "S-Raft" || echo "Original Raft")"
echo -e "${GREEN}============================================${NC}"

# 각 노드에 배포
for i in "${!NODE_IPS[@]}"; do
    NODE_ID=$((i + 1))
    NODE_IP="${NODE_IPS[$i]}"

    echo -e "\n${BLUE}[Node $NODE_ID] Deploying to $NODE_IP...${NC}"

    # SSH로 setup 스크립트 실행
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$EC2_USER@$NODE_IP" << REMOTE_SCRIPT
#!/bin/bash
set -e

echo "[Node $NODE_ID] Starting setup..."

# Python 설치 확인
if ! command -v python3 &> /dev/null; then
    echo "Installing Python3..."
    sudo yum install -y python3 git 2>/dev/null || sudo apt-get install -y python3 git 2>/dev/null
fi

# 작업 디렉토리
mkdir -p ~/s-raft
cd ~/s-raft

# GitHub에서 클론
if [ -d "raft_for_EC2" ]; then
    cd raft_for_EC2
    git pull origin $BRANCH
else
    git clone --branch $BRANCH https://github.com/$GITHUB_REPO.git raft_for_EC2
    cd raft_for_EC2
fi

# 환경변수 파일 생성
cat > ../raft_env.sh << EOF
export RAFT_NODE_ID=$NODE_ID
export RAFT_PORT=$PORT
export RAFT_PEERS="$PEERS"
export ENABLE_SUBLEADER=$ENABLE_SUBLEADER
EOF

echo "[Node $NODE_ID] Setup complete!"
REMOTE_SCRIPT

    echo -e "${GREEN}[Node $NODE_ID] Deployment complete!${NC}"
done

echo -e "\n${GREEN}============================================${NC}"
echo -e "${GREEN}  All nodes deployed successfully!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Next steps:"
echo "1. SSH into each node and start the server:"
echo "   ssh -i $SSH_KEY $EC2_USER@<NODE_IP>"
echo "   cd ~/s-raft/raft_for_EC2"
echo "   source ../raft_env.sh"
echo "   python3 ec2_server.py --peers \"\$RAFT_PEERS\" --debug"
echo ""
echo "Or use the start_all.sh script to start all nodes."
