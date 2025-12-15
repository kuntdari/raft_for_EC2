#!/bin/bash
#===============================================================================
# S-Raft EC2 Instance Setup Script
#===============================================================================
# 이 스크립트는 각 EC2 인스턴스에서 실행됩니다.
# GitHub에서 코드를 클론하고 S-Raft 서버를 시작합니다.
#
# 사용법:
#   chmod +x setup_ec2.sh
#   ./setup_ec2.sh <NODE_ID> <PEERS>
#
# 예시:
#   ./setup_ec2.sh 1 "10.0.1.10:5000,10.0.1.11:5000,10.0.1.12:5000,10.0.1.13:5000,10.0.1.14:5000"
#===============================================================================

set -e

# 파라미터
NODE_ID=${1:-1}
PEERS=${2:-""}
GITHUB_REPO=${3:-"your-username/s-raft-ec2"}  # 여기에 실제 GitHub 레포지토리 입력
BRANCH=${4:-"main"}
PORT=${5:-5000}
ENABLE_SUBLEADER=${6:-"true"}

# 색상 출력
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  S-Raft EC2 Setup Script${NC}"
echo -e "${GREEN}============================================${NC}"
echo "  Node ID: $NODE_ID"
echo "  Peers: $PEERS"
echo "  Port: $PORT"
echo "  S-Raft Mode: $ENABLE_SUBLEADER"
echo -e "${GREEN}============================================${NC}"

# 1. 시스템 업데이트 및 Python 설치
echo -e "\n${YELLOW}[1/5] Installing Python...${NC}"
if command -v python3 &> /dev/null; then
    echo "Python3 already installed: $(python3 --version)"
else
    sudo yum update -y || sudo apt-get update -y
    sudo yum install -y python3 python3-pip git || sudo apt-get install -y python3 python3-pip git
fi

# 2. 작업 디렉토리 생성
echo -e "\n${YELLOW}[2/5] Creating work directory...${NC}"
WORK_DIR="/home/ec2-user/s-raft"
mkdir -p $WORK_DIR
cd $WORK_DIR

# 3. GitHub에서 코드 클론
echo -e "\n${YELLOW}[3/5] Cloning from GitHub...${NC}"
if [ -d "raft_for_EC2" ]; then
    echo "Directory exists, pulling latest..."
    cd raft_for_EC2
    git pull origin $BRANCH
else
    git clone --branch $BRANCH https://github.com/$GITHUB_REPO.git raft_for_EC2
    cd raft_for_EC2
fi

# 4. 환경변수 설정
echo -e "\n${YELLOW}[4/5] Setting environment variables...${NC}"
export RAFT_NODE_ID=$NODE_ID
export RAFT_PORT=$PORT
export RAFT_PEERS=$PEERS
export ENABLE_SUBLEADER=$ENABLE_SUBLEADER

# 환경변수 파일 생성
cat > /home/ec2-user/s-raft/raft_env.sh << EOF
export RAFT_NODE_ID=$NODE_ID
export RAFT_PORT=$PORT
export RAFT_PEERS="$PEERS"
export ENABLE_SUBLEADER=$ENABLE_SUBLEADER
EOF

echo "Environment file created: /home/ec2-user/s-raft/raft_env.sh"

# 5. Systemd 서비스 생성 (선택사항)
echo -e "\n${YELLOW}[5/5] Creating systemd service...${NC}"

sudo tee /etc/systemd/system/s-raft.service > /dev/null << EOF
[Unit]
Description=S-Raft Consensus Server
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/s-raft/raft_for_EC2
Environment="RAFT_NODE_ID=$NODE_ID"
Environment="RAFT_PORT=$PORT"
Environment="RAFT_PEERS=$PEERS"
Environment="ENABLE_SUBLEADER=$ENABLE_SUBLEADER"
ExecStart=/usr/bin/python3 ec2_server.py --peers "$PEERS" --debug
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable s-raft

echo -e "\n${GREEN}============================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "To start the S-Raft server:"
echo "  sudo systemctl start s-raft"
echo ""
echo "To check status:"
echo "  sudo systemctl status s-raft"
echo ""
echo "To view logs:"
echo "  sudo journalctl -u s-raft -f"
echo ""
echo "To run manually:"
echo "  cd /home/ec2-user/s-raft/raft_for_EC2"
echo "  source ../raft_env.sh"
echo "  python3 ec2_server.py --peers \"\$RAFT_PEERS\" --debug"
echo ""
