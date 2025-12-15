# -*- coding: utf-8 -*-
"""
S-Raft Metrics Collection
==========================
성능 메트릭 수집 및 분석
"""

import threading
import time
import statistics
import json
from collections import defaultdict
from datetime import datetime


class MetricsCollector:
    """
    실험 결과 측정 및 수집

    측정 항목:
    - 리더 선거/승격 시간
    - 클라이언트 요청 지연
    - 처리량 (throughput)
    - 리더 장애 횟수
    """

    def __init__(self):
        self.election_times = []
        self.request_latencies = []
        self.leader_failures = []
        self.throughput_data = defaultdict(list)
        self.leader_transitions = []
        self.sub_leader_promotions = []
        self.promotion_failures = []
        self.start_time = time.time()
        self.lock = threading.Lock()

    def record_election_time(self, duration, winner_id, is_sub_leader, method):
        """선거/승격 시간 기록"""
        with self.lock:
            self.election_times.append({
                'duration': duration,
                'winner': winner_id,
                'is_sub_leader': is_sub_leader,
                'method': method,  # 'instant_promotion' or 'voting'
                'timestamp': time.time() - self.start_time
            })

    def record_promotion_failure(self, node_id, term, ack_count, required):
        """서브리더 승격 실패 기록"""
        with self.lock:
            self.promotion_failures.append({
                'node_id': node_id,
                'term': term,
                'ack_count': ack_count,
                'required': required,
                'timestamp': time.time() - self.start_time
            })

    def record_request_latency(self, latency, success):
        """클라이언트 요청 응답 시간 기록"""
        with self.lock:
            self.request_latencies.append({
                'latency': latency,
                'success': success,
                'timestamp': time.time() - self.start_time
            })

    def record_leader_failure(self, old_leader_id, term):
        """리더 장애 발생 기록"""
        with self.lock:
            self.leader_failures.append({
                'old_leader': old_leader_id,
                'term': term,
                'timestamp': time.time() - self.start_time
            })

    def record_throughput(self, node_id, requests_per_second):
        """처리량 기록"""
        with self.lock:
            self.throughput_data[node_id].append({
                'rps': requests_per_second,
                'timestamp': time.time() - self.start_time
            })

    def get_summary(self):
        """수집된 메트릭 요약"""
        with self.lock:
            instant_promotions = [e for e in self.election_times
                                  if e['method'] == 'instant_promotion']
            voting_elections = [e for e in self.election_times
                               if e['method'] == 'voting']

            summary = {
                'total_elections': len(self.election_times),
                'instant_promotions': len(instant_promotions),
                'voting_elections': len(voting_elections),
                'promotion_failures': len(self.promotion_failures),
                'leader_failures': len(self.leader_failures),
                'total_requests': len(self.request_latencies),
                'successful_requests': len([r for r in self.request_latencies if r['success']]),
            }

            # 평균 시간 계산
            if self.election_times:
                summary['avg_election_time_ms'] = statistics.mean(
                    [e['duration'] * 1000 for e in self.election_times]
                )
            else:
                summary['avg_election_time_ms'] = 0

            if instant_promotions:
                summary['avg_instant_promotion_ms'] = statistics.mean(
                    [e['duration'] * 1000 for e in instant_promotions]
                )
            else:
                summary['avg_instant_promotion_ms'] = 0

            if voting_elections:
                summary['avg_voting_election_ms'] = statistics.mean(
                    [e['duration'] * 1000 for e in voting_elections]
                )
            else:
                summary['avg_voting_election_ms'] = 0

            if self.request_latencies:
                latencies = [r['latency'] * 1000 for r in self.request_latencies]
                summary['avg_latency_ms'] = statistics.mean(latencies)
                summary['p50_latency_ms'] = statistics.median(latencies)
                summary['p99_latency_ms'] = (
                    sorted(latencies)[int(len(latencies) * 0.99)]
                    if len(latencies) >= 100 else max(latencies)
                )
            else:
                summary['avg_latency_ms'] = 0
                summary['p50_latency_ms'] = 0
                summary['p99_latency_ms'] = 0

            return summary

    def print_summary(self):
        """실험 결과 요약 출력"""
        summary = self.get_summary()

        print("\n" + "=" * 70)
        print("S-Raft 실험 결과 요약 (Experiment Results Summary)")
        print("=" * 70)

        print(f"\n[리더 전환 (Leader Transitions)]")
        print(f"  총 전환 횟수: {summary['total_elections']}")
        print(f"    - 즉시 승격 성공: {summary['instant_promotions']}")
        print(f"    - 즉시 승격 실패: {summary['promotion_failures']}")
        print(f"    - 투표 선거: {summary['voting_elections']}")

        print(f"\n[전환 시간 (Transition Time)]")
        print(f"  평균 전환 시간: {summary['avg_election_time_ms']:.2f} ms")
        if summary['instant_promotions'] > 0:
            print(f"  평균 즉시 승격: {summary['avg_instant_promotion_ms']:.2f} ms")
        if summary['voting_elections'] > 0:
            print(f"  평균 투표 선거: {summary['avg_voting_election_ms']:.2f} ms")

        print(f"\n[클라이언트 요청 (Client Requests)]")
        print(f"  총 요청: {summary['total_requests']}")
        print(f"  성공: {summary['successful_requests']}")
        if summary['total_requests'] > 0:
            print(f"  평균 지연: {summary['avg_latency_ms']:.2f} ms")
            print(f"  P50 지연: {summary['p50_latency_ms']:.2f} ms")
            print(f"  P99 지연: {summary['p99_latency_ms']:.2f} ms")

        print(f"\n[장애 (Failures)]")
        print(f"  리더 장애: {summary['leader_failures']}")

        print("=" * 70)

        return summary

    def export_json(self, filepath):
        """결과를 JSON 파일로 내보내기"""
        with self.lock:
            data = {
                'timestamp': datetime.now().isoformat(),
                'summary': self.get_summary(),
                'election_times': self.election_times,
                'promotion_failures': self.promotion_failures,
                'leader_failures': self.leader_failures,
                'request_latencies': self.request_latencies[:1000],  # 최대 1000개
            }

            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)

            print(f"[Metrics] Exported to {filepath}")

    def export_csv(self, filepath):
        """결과를 CSV 파일로 내보내기 (선거 시간만)"""
        with self.lock:
            with open(filepath, 'w') as f:
                f.write("timestamp,duration_ms,winner,method,is_sub_leader\n")
                for e in self.election_times:
                    f.write(f"{e['timestamp']:.3f},{e['duration']*1000:.2f},"
                           f"{e['winner']},{e['method']},{e['is_sub_leader']}\n")

            print(f"[Metrics] Exported to {filepath}")
