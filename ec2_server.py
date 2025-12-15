#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S-Raft Server for AWS EC2
==========================
AWS EC2에서 실행되는 S-Raft 노드 서버

사용법:
    python ec2_server.py --node-id 0 --port 5000 --peers "10.0.1.11:5000,10.0.1.12:5000,..."

환경변수:
    RAFT_NODE_ID: 노드 ID
    RAFT_PORT: 리스닝 포트
    RAFT_PEERS: 쉼표로 구분된 피어 주소
    ENABLE_SUBLEADER: S-Raft 서브리더 활성화 (true/false)
"""

import argparse
import os
import sys
import time
import signal
import threading
import json
import socket
import urllib.request
from datetime import datetime

from config import RaftConfig, ClusterConfig
from transport import TCPTransport
from node import RaftNode
from metrics import MetricsCollector


class EC2RaftServer:
    """
    AWS EC2용 S-Raft 서버

    AWS EC2 인스턴스에서 실행되는 단일 Raft 노드
    """

    def __init__(self, node_id, host, port, peer_addresses, config=None):
        """
        Args:
            node_id: 노드 ID
            host: 바인딩 호스트 (0.0.0.0 또는 실제 IP)
            port: 리스닝 포트
            peer_addresses: 피어 주소 리스트 ['ip:port', ...]
            config: RaftConfig 객체
        """
        self.node_id = node_id
        self.host = host
        self.port = port

        # 설정
        self.config = config or RaftConfig()

        # 클러스터 설정
        self_addr = f"{host}:{port}"
        all_addrs = [self_addr] + peer_addresses
        self.cluster = ClusterConfig.from_addresses(all_addrs)

        # 메트릭 수집
        self.metrics = MetricsCollector()

        # 전송 계층
        print(f"[Server] Initializing transport...")
        self.transport = TCPTransport(self_addr, all_addrs, self.config)

        # Raft 노드
        total_nodes = len(all_addrs)
        self.config.validate(total_nodes)

        # 노드 ID 재계산 (주소 정렬 기반)
        sorted_addrs = sorted(all_addrs)
        actual_node_id = sorted_addrs.index(self_addr)

        print(f"[Server] Creating Raft node {actual_node_id}...")
        self.node = RaftNode(
            actual_node_id,
            total_nodes,
            self.config,
            self.transport,
            self.metrics
        )

        # 콜백 설정
        self.node.on_become_leader = self._on_become_leader
        self.node.on_become_follower = self._on_become_follower
        self.node.on_log_committed = self._on_log_committed

        # 상태
        self.running = False
        self.node_thread = None

        # 애플리케이션 상태 (예: 카운터)
        self.app_state = {'counter': 0}
        self.app_lock = threading.Lock()

    def _on_become_leader(self):
        """리더가 됐을 때 콜백"""
        print(f"[Server] This node is now the LEADER")

    def _on_become_follower(self):
        """Follower가 됐을 때 콜백"""
        print(f"[Server] This node is now a Follower")

    def _on_log_committed(self, entry):
        """로그가 커밋됐을 때 콜백"""
        with self.app_lock:
            command = entry.command
            if command.get('type') == 'increment':
                self.app_state['counter'] += command.get('value', 1)
            elif command.get('type') == 'set':
                self.app_state['counter'] = command.get('value', 0)

    def start(self):
        """서버 시작"""
        if self.running:
            return

        self.running = True

        # Raft 노드 스레드 시작
        self.node_thread = threading.Thread(target=self.node.run, daemon=True)
        self.node_thread.start()

        print(f"[Server] Started - Node {self.node.id}")
        print(f"[Server] Listening on {self.host}:{self.port}")

    def stop(self):
        """서버 중지"""
        if not self.running:
            return

        print(f"[Server] Stopping...")
        self.running = False
        self.node.stop()
        self.transport.stop()

        # 메트릭 출력
        self.metrics.print_summary()

    def get_status(self):
        """서버 상태 반환"""
        node_state = self.node.get_state()
        return {
            **node_state,
            'app_state': self.app_state.copy(),
            'transport_stats': self.transport.get_stats()
        }

    def submit_increment(self, value=1):
        """카운터 증가 명령 제출"""
        return self.node.submit_command({
            'type': 'increment',
            'value': value
        })

    def get_counter(self):
        """카운터 값 반환"""
        with self.app_lock:
            return self.app_state['counter']


def get_ec2_private_ip():
    """EC2 인스턴스의 프라이빗 IP 조회 (메타데이터 서비스)"""
    try:
        # EC2 메타데이터 서비스에서 프라이빗 IP 조회
        url = "http://169.254.169.254/latest/meta-data/local-ipv4"
        req = urllib.request.Request(url)
        req.add_header('X-aws-ec2-metadata-token-ttl-seconds', '21600')

        with urllib.request.urlopen(req, timeout=2) as response:
            return response.read().decode('utf-8')
    except:
        pass

    # 폴백: 소켓으로 로컬 IP 얻기
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "0.0.0.0"


def get_ec2_instance_id():
    """EC2 인스턴스 ID 조회"""
    try:
        url = "http://169.254.169.254/latest/meta-data/instance-id"
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.read().decode('utf-8')
    except:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(description='S-Raft Server for AWS EC2')

    parser.add_argument('--node-id', type=int, default=0,
                       help='Node ID (0-based)')
    parser.add_argument('--host', type=str, default=None,
                       help='Bind host (default: auto-detect EC2 private IP)')
    parser.add_argument('--port', type=int, default=5000,
                       help='Listen port (default: 5000)')
    parser.add_argument('--peers', type=str, required=True,
                       help='Comma-separated peer addresses (ip:port)')
    parser.add_argument('--config', type=str, default=None,
                       help='Config file path (JSON)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug mode')
    parser.add_argument('--metrics-file', type=str, default=None,
                       help='Metrics output file (JSON)')
    parser.add_argument('--original-raft', action='store_true',
                       help='Disable S-Raft sub-leader (use Original Raft)')

    args = parser.parse_args()

    # 환경변수 오버라이드
    node_id = int(os.environ.get('RAFT_NODE_ID', args.node_id))
    port = int(os.environ.get('RAFT_PORT', args.port))
    peers_str = os.environ.get('RAFT_PEERS', args.peers)
    enable_subleader = os.environ.get('ENABLE_SUBLEADER', 'true').lower() == 'true'

    if args.original_raft:
        enable_subleader = False

    # 호스트 자동 감지 (EC2 프라이빗 IP)
    host = args.host or get_ec2_private_ip()
    instance_id = get_ec2_instance_id()

    # 피어 주소 파싱
    peer_addresses = [p.strip() for p in peers_str.split(',') if p.strip()]

    # 설정 로드
    config = RaftConfig()
    if args.config and os.path.exists(args.config):
        config = RaftConfig.load(args.config)

    config.debug = args.debug
    config.enable_subleader = enable_subleader

    print(f"=" * 60)
    print(f"S-Raft Server Starting on AWS EC2")
    print(f"=" * 60)
    print(f"  Instance ID: {instance_id}")
    print(f"  Node ID: {node_id}")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Peers: {peer_addresses}")
    print(f"  S-Raft Mode: {'Enabled' if enable_subleader else 'Disabled (Original Raft)'}")
    print(f"  Debug: {config.debug}")
    print(f"=" * 60)

    # 서버 생성 및 시작
    server = EC2RaftServer(node_id, host, port, peer_addresses, config)

    # 시그널 핸들러
    def signal_handler(sig, frame):
        print(f"\n[Server] Received signal {sig}, shutting down...")
        server.stop()

        # 메트릭 저장
        if args.metrics_file:
            server.metrics.export_json(args.metrics_file)

        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 시작
    server.start()

    # 상태 모니터링 루프
    try:
        while server.running:
            time.sleep(5)

            status = server.get_status()
            leader_str = f"LEADER" if status['state'] == 'Leader' else f"Follower (leader={status['leader_id']})"
            subleader_str = ""
            if status['is_sub_leader']:
                rank = "Primary" if status['subleader_rank'] == 0 else "Secondary"
                subleader_str = f" [{rank} Sub-leader]"

            print(f"[Status] {leader_str}{subleader_str} | "
                  f"Term: {status['term']} | "
                  f"Log: {status['log_length']} | "
                  f"Counter: {server.get_counter()}")

    except KeyboardInterrupt:
        pass
    finally:
        server.stop()

        if args.metrics_file:
            server.metrics.export_json(args.metrics_file)


if __name__ == '__main__':
    main()
