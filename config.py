# -*- coding: utf-8 -*-
"""
S-Raft Configuration for AWS EC2
=================================
AWS EC2 환경에 최적화된 S-Raft 설정

AWS EC2 네트워크 특성:
- 같은 VPC 내 인스턴스 간 지연: 0.5-2ms
- 같은 리전 내 AZ 간 지연: 1-5ms
- 다른 리전 간 지연: 50-200ms
"""

import json
import os


class RaftConfig:
    """
    S-Raft 설정 클래스 (AWS EC2용)

    AWS EC2 환경에 맞게 타임아웃과 네트워크 설정 최적화
    """

    def __init__(self):
        # ===== 기본 Raft 설정 =====
        self.heartbeat_interval = 0.05  # 하트비트 간격 (50ms)
        self.election_timeout_base = 0.15  # 기본 선거 타임아웃 (150ms)

        # ===== S-Raft 전용 설정 =====
        self.enable_subleader = True  # 서브리더 기능 활성화
        self.subleader_ratio = 0.4  # 서브리더 비율 (40% = 5노드 중 2개)

        # Primary 서브리더 (rank 0) - 리더 장애 시 가장 먼저 승격
        self.primary_timeout_min = 0.15  # 150ms
        self.primary_timeout_max = 0.20  # 200ms

        # Secondary 서브리더 (rank 1) - Primary 실패 후 승격
        self.secondary_timeout_min = 0.25  # 250ms
        self.secondary_timeout_max = 0.35  # 350ms

        # Follower - 모든 서브리더 실패 후 기존 Raft 선거
        self.follower_timeout_min = 0.30  # 300ms
        self.follower_timeout_max = 1.00  # 1000ms

        # ===== 승격 설정 =====
        self.promotion_timeout = 0.3  # 승격 확인 타임아웃 (300ms)

        # ===== 네트워크 설정 (EC2 최적화) =====
        self.connection_timeout = 5.0  # 연결 타임아웃 (5초)
        self.connection_retry_time = 3.0  # 연결 재시도 시간 (3초)
        self.recv_timeout = 0.01  # 수신 타임아웃 (10ms)

        # ===== 성능 튜닝 =====
        self.rtt_alpha = 0.3  # RTT EMA 가중치
        self.auto_tick_period = 0.001  # 자동 틱 주기 (1ms)

        # ===== 시뮬레이션 설정 =====
        self.simulation_duration = 60.0  # 시뮬레이션 실행 시간 (초)
        self.warmup_time = 5.0  # 워밍업 시간 (초)
        self.leader_failure_interval = 10.0  # 리더 장애 발생 간격 (초)
        self.num_leader_failures = 3  # 시뮬레이션 중 리더 장애 발생 횟수

        # ===== 디버그 설정 =====
        self.debug = True  # 디버그 모드
        self.verbose = False  # 상세 로그 출력

    def validate(self, node_count):
        """설정 유효성 검사"""
        if node_count < 3:
            raise ValueError("S-Raft는 최소 3개 노드가 필요합니다")

        subleader_count = int(node_count * self.subleader_ratio)
        if subleader_count < 1:
            raise ValueError("서브리더가 최소 1개 이상이어야 합니다")

        return True

    def to_dict(self):
        """설정을 딕셔너리로 변환"""
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    @classmethod
    def from_dict(cls, d):
        """딕셔너리에서 설정 생성"""
        config = cls()
        for k, v in d.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return config

    def save(self, filepath):
        """설정 저장"""
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath):
        """설정 로드"""
        with open(filepath, 'r') as f:
            return cls.from_dict(json.load(f))


class ClusterConfig:
    """
    클러스터 설정 관리

    EC2 인스턴스 정보를 관리하고 노드 설정을 생성
    """

    def __init__(self, nodes=None):
        """
        Args:
            nodes: 노드 정보 리스트 [{'id': 0, 'host': 'ip', 'port': 5000}, ...]
        """
        self.nodes = nodes or []

    def add_node(self, node_id, host, port):
        """노드 추가"""
        self.nodes.append({
            'id': node_id,
            'host': host,
            'port': port,
            'address': f"{host}:{port}"
        })

    def get_node_address(self, node_id):
        """노드 주소 반환"""
        for node in self.nodes:
            if node['id'] == node_id:
                return node['address']
        return None

    def get_all_addresses(self):
        """모든 노드 주소 리스트 반환"""
        return [node['address'] for node in self.nodes]

    def get_peer_addresses(self, my_id):
        """자신을 제외한 피어 주소 리스트 반환"""
        return [node['address'] for node in self.nodes if node['id'] != my_id]

    def save(self, filepath):
        """클러스터 설정 저장"""
        with open(filepath, 'w') as f:
            json.dump({'nodes': self.nodes}, f, indent=2)

    @classmethod
    def load(cls, filepath):
        """클러스터 설정 로드"""
        with open(filepath, 'r') as f:
            data = json.load(f)
            return cls(nodes=data.get('nodes', []))

    @classmethod
    def from_addresses(cls, addresses):
        """
        주소 리스트에서 클러스터 설정 생성

        Args:
            addresses: ['ip1:port1', 'ip2:port2', ...]
        """
        config = cls()
        sorted_addrs = sorted(addresses)
        for i, addr in enumerate(sorted_addrs):
            host, port = addr.split(':')
            config.add_node(i, host, int(port))
        return config
