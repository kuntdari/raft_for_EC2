# -*- coding: utf-8 -*-
"""
S-Raft for AWS EC2
==================
AWS EC2 환경에서 실행 가능한 TCP 소켓 기반 S-Raft 합의 알고리즘

모듈 구성:
- config.py: 설정 클래스
- message.py: 메시지 프로토콜
- transport.py: TCP 전송 계층
- node.py: Raft 노드 구현
- metrics.py: 메트릭 수집
- ec2_server.py: EC2 서버 실행 스크립트
"""

__version__ = '1.0.0'
__author__ = 'S-Raft Team'

from .config import RaftConfig, ClusterConfig
from .message import Message, MessageType, LogEntry
from .transport import TCPTransport
from .node import RaftNode, NodeState
from .metrics import MetricsCollector
