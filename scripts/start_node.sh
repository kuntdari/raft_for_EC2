#!/bin/bash
#===============================================================================
# S-Raft Node Startup Script
#===============================================================================
# EC2 인스턴스에서 S-Raft 노드를 수동으로 시작하는 스크립트
#
# 사용법:
#   ./start_node.sh <PEERS>
#
# 예시:
#   ./start_node.sh "10.0.1.10:5000,10.0.1.11:5000,10.0.1.12:5000"
#===============================================================================

PEERS=${1:-$RAFT_PEERS}
PORT=${RAFT_PORT:-5000}
ENABLE_SUBLEADER=${ENABLE_SUBLEADER:-"true"}
DEBUG=${DEBUG:-"true"}

if [ -z "$PEERS" ]; then
    echo "Error: PEERS not specified"
    echo "Usage: ./start_node.sh <PEERS>"
    echo "Example: ./start_node.sh \"10.0.1.10:5000,10.0.1.11:5000,10.0.1.12:5000\""
    exit 1
fi

# 스크립트 디렉토리로 이동
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/.."

echo "============================================"
echo "  Starting S-Raft Node"
echo "============================================"
echo "  Peers: $PEERS"
echo "  Port: $PORT"
echo "  S-Raft Mode: $ENABLE_SUBLEADER"
echo "============================================"

# 옵션 구성
OPTS="--peers \"$PEERS\" --port $PORT"

if [ "$ENABLE_SUBLEADER" = "false" ]; then
    OPTS="$OPTS --original-raft"
fi

if [ "$DEBUG" = "true" ]; then
    OPTS="$OPTS --debug"
fi

# 서버 실행
eval "python3 ec2_server.py $OPTS"
