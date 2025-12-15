#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S-Raft Local Test
==================
로컬 환경에서 5개 노드 S-Raft 클러스터 테스트

AWS EC2 배포 전 로컬에서 동작 확인용
"""

import sys
import time
import threading
import signal

from config import RaftConfig
from transport import TCPTransport
from node import RaftNode, NodeState
from metrics import MetricsCollector


class LocalCluster:
    """로컬 S-Raft 클러스터"""

    def __init__(self, num_nodes=5, base_port=5000, enable_subleader=True):
        self.num_nodes = num_nodes
        self.base_port = base_port

        # 설정
        self.config = RaftConfig()
        self.config.enable_subleader = enable_subleader
        self.config.debug = True

        # 노드들
        self.nodes = []
        self.transports = []
        self.threads = []

        # 메트릭
        self.metrics = MetricsCollector()

        # 주소 생성
        self.addresses = [f"127.0.0.1:{base_port + i}" for i in range(num_nodes)]

        self.running = False

    def start(self):
        """클러스터 시작"""
        print("=" * 70)
        print(f"S-Raft Local Cluster Starting ({self.num_nodes} nodes)")
        print(f"Mode: {'S-Raft (Sub-leader enabled)' if self.config.enable_subleader else 'Original Raft'}")
        print("=" * 70)

        self.running = True

        # 각 노드 생성 및 시작
        for i in range(self.num_nodes):
            self_addr = self.addresses[i]

            print(f"\n[Cluster] Starting Node {i} ({self_addr})...")

            # Transport 생성
            transport = TCPTransport(self_addr, self.addresses, self.config)
            self.transports.append(transport)

            # Raft 노드 생성
            node = RaftNode(i, self.num_nodes, self.config, transport, self.metrics)
            self.nodes.append(node)

            # 노드 스레드 시작
            thread = threading.Thread(target=node.run, daemon=True)
            thread.start()
            self.threads.append(thread)

            time.sleep(0.5)

        print("\n[Cluster] All nodes started!")

    def stop(self):
        """클러스터 중지"""
        print("\n[Cluster] Stopping all nodes...")
        self.running = False

        for node in self.nodes:
            node.stop()

        for transport in self.transports:
            transport.stop()

        # 메트릭 출력
        self.metrics.print_summary()

    def get_leader(self):
        """현재 리더 반환"""
        for node in self.nodes:
            if node.state == NodeState.LEADER:
                return node
        return None

    def simulate_leader_failure(self):
        """리더 장애 시뮬레이션"""
        leader = self.get_leader()
        if leader:
            print(f"\n{'='*70}")
            print(f"[TEST] Simulating leader failure: Node {leader.id}")
            print(f"{'='*70}\n")

            self.metrics.record_leader_failure(leader.id, leader.current_term)
            leader.stop()
            self.transports[leader.id].stop()

            return leader.id
        return None

    def print_status(self):
        """클러스터 상태 출력"""
        print("\n" + "-" * 70)
        print("Cluster Status:")
        print("-" * 70)

        for node in self.nodes:
            state = node.get_state()
            status = f"Node {state['id']}: {state['state']:10}"
            status += f" | Term: {state['term']:3}"
            status += f" | Leader: {state['leader_id']}"

            if state['is_sub_leader']:
                rank = "Primary" if state['subleader_rank'] == 0 else "Secondary"
                status += f" | [{rank}]"

            print(status)

        print("-" * 70)


def run_basic_test():
    """기본 테스트: 리더 선출"""
    print("\n" + "=" * 70)
    print("TEST: Basic Leader Election")
    print("=" * 70)

    cluster = LocalCluster(num_nodes=5)
    cluster.start()

    # 리더 선출 대기
    print("\n[Test] Waiting for leader election...")
    for i in range(30):
        time.sleep(1)
        leader = cluster.get_leader()
        if leader:
            print(f"[Test] Leader elected: Node {leader.id}")
            break
        print(f"[Test] Waiting... ({i+1}s)")

    cluster.print_status()

    # 서브리더 지정 대기
    print("\n[Test] Waiting for sub-leaders assignment...")
    time.sleep(5)
    cluster.print_status()

    cluster.stop()


def run_failover_test():
    """장애 복구 테스트"""
    print("\n" + "=" * 70)
    print("TEST: Leader Failover")
    print("=" * 70)

    cluster = LocalCluster(num_nodes=5)
    cluster.start()

    # 초기 리더 선출 대기
    print("\n[Test] Waiting for initial leader...")
    for _ in range(30):
        time.sleep(1)
        if cluster.get_leader():
            break

    # 서브리더 지정 대기
    time.sleep(8)
    cluster.print_status()

    # 리더 장애
    failed_id = cluster.simulate_leader_failure()

    if failed_id is not None:
        # 새 리더 선출 시간 측정
        start = time.time()
        for _ in range(20):
            time.sleep(0.5)
            for node in cluster.nodes:
                if node.id != failed_id and node.state == NodeState.LEADER:
                    elapsed = time.time() - start
                    print(f"\n[Test] New leader: Node {node.id} ({elapsed*1000:.1f}ms)")
                    break
            else:
                continue
            break

    cluster.print_status()
    cluster.stop()


def main():
    """메인 함수"""
    tests = {
        '1': ('Basic Leader Election', run_basic_test),
        '2': ('Leader Failover Test', run_failover_test),
    }

    print("\n" + "=" * 70)
    print("S-Raft Local Test")
    print("=" * 70)
    print("\nAvailable tests:")
    for key, (name, _) in tests.items():
        print(f"  {key}: {name}")

    if len(sys.argv) > 1:
        choice = sys.argv[1]
    else:
        choice = input("\nSelect test (1/2): ").strip()

    # 시그널 핸들러
    def signal_handler(sig, frame):
        print("\n[Main] Interrupted")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    if choice in tests:
        tests[choice][1]()
    else:
        print(f"Invalid choice: {choice}")
        sys.exit(1)

    print("\n[Main] Test completed")


if __name__ == '__main__':
    main()
