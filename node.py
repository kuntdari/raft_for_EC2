# -*- coding: utf-8 -*-
"""
S-Raft Node Implementation for AWS EC2
=======================================
S-Raft 합의 알고리즘 노드 구현

핵심 특징:
- 서브리더 기반 빠른 리더 전환
- TCP 기반 실제 네트워크 통신
- AWS EC2 환경에 최적화
"""

import threading
import time
import random
from collections import defaultdict

from message import (
    Message, MessageType, LogEntry,
    create_append_entries, create_append_ack,
    create_request_vote, create_vote_response
)


class NodeState:
    """노드 상태 상수"""
    FOLLOWER = 'Follower'
    CANDIDATE = 'Candidate'
    LEADER = 'Leader'
    STOPPED = 'Stopped'


class RaftNode:
    """
    S-Raft 노드 클래스

    핵심 메커니즘:
    1. 초기 시작: Original Raft 투표 선거
    2. 리더 선출 후: 서브리더 2명 지정 (RTT 기반)
    3. 리더 장애 시:
       - Primary 서브리더 즉시 승격 시도
       - Primary 실패 → Secondary 서브리더 승격 시도
       - 모두 실패 → 기존 Raft 선거
    """

    def __init__(self, node_id, total_nodes, config, transport, metrics=None):
        """
        Args:
            node_id: 노드 ID (0부터 시작)
            total_nodes: 전체 노드 수
            config: RaftConfig 객체
            transport: TCPTransport 객체
            metrics: MetricsCollector 객체 (선택)
        """
        self.id = node_id
        self.total_nodes = total_nodes
        self.config = config
        self.transport = transport
        self.metrics = metrics

        # ===== Raft 기본 상태 =====
        self.state = NodeState.FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.log = []  # [LogEntry, ...]
        self.commit_index = 0
        self.last_applied = 0
        self.leader_id = None
        self.had_leader_before = False

        # ===== S-Raft 서브리더 상태 =====
        self.is_sub_leader = False
        self.subleader_rank = None  # 0=Primary, 1=Secondary
        self.current_sub_leaders = {}  # {node_id: rank}
        self.subleaders_assigned = False
        self.leader_elected_time = None

        # RTT 측정
        self.response_times = {}  # {node_id: rtt}
        self.message_sent_times = {}  # {node_id: sent_time}

        # ===== 승격 상태 =====
        self.is_promotion_pending = False
        self.promotion_start_time = 0
        self.promotion_ack_count = 0
        self.promotion_ack_nodes = set()
        self.promotion_confirmed = False

        # ===== Leader Lease (Split-brain 방지) =====
        self.last_majority_ack_time = time.time()
        self.recent_ack_nodes = set()

        # ===== 로그 복제 추적 (리더 전용) =====
        self.next_index = {}  # {node_id: next_log_index}
        self.match_index = {}  # {node_id: match_log_index}

        # ===== 선거 상태 =====
        self.votes_received = 0
        self.voted_nodes = set()
        self.election_start_time = 0
        self.consecutive_election_failures = 0

        # ===== 타이머 =====
        self.last_heartbeat = time.time()
        self.election_timeout = self._reset_election_timer()

        # ===== 스레드 제어 =====
        self.running = True
        self.lock = threading.Lock()

        # ===== 노드별 통계 =====
        self.stats = {
            'elections_started': 0,
            'votes_received_total': 0,
            'became_leader_count': 0,
            'became_subleader_count': 0,
            'instant_promotions': 0,
            'promotion_successes': 0,
            'promotion_failures': 0,
        }

        # ===== 콜백 (애플리케이션 연동용) =====
        self.on_become_leader = None
        self.on_become_follower = None
        self.on_log_committed = None

        # ===== 시작 시 Term 학습 =====
        self.startup_grace_period = True
        self.startup_time = time.time()
        self.startup_grace_duration = 5.0

        print(f"[Node {self.id}] Initialized - election timeout: {self.election_timeout*1000:.0f}ms")

    def _reset_election_timer(self):
        """선거 타임아웃 리셋"""
        if not self.had_leader_before:
            base_offset = self.id * 0.05
            return random.uniform(
                self.config.election_timeout_base + base_offset,
                self.config.election_timeout_base * 2 + base_offset
            )

        if self.config.enable_subleader and self.is_sub_leader:
            if self.subleader_rank == 0:  # Primary
                return random.uniform(
                    self.config.primary_timeout_min,
                    self.config.primary_timeout_max
                )
            elif self.subleader_rank == 1:  # Secondary
                return random.uniform(
                    self.config.secondary_timeout_min,
                    self.config.secondary_timeout_max
                )

        id_offset = (self.id % self.total_nodes) * 0.15
        return random.uniform(
            self.config.follower_timeout_min + id_offset,
            self.config.follower_timeout_max + id_offset
        )

    def run(self):
        """노드 메인 루프"""
        self.last_heartbeat = time.time()
        print(f"[Node {self.id}] Started running")

        while self.running:
            msg = self.transport.receive(timeout=self.config.recv_timeout)
            if msg:
                self._handle_message(msg)

            self._check_timers()
            time.sleep(self.config.auto_tick_period)

    def _check_timers(self):
        """타이머 체크"""
        with self.lock:
            now = time.time()

            if self.state == NodeState.LEADER:
                if self.is_promotion_pending:
                    self._check_promotion_success()

                lease_timeout = max(self.config.heartbeat_interval * 30, 3.0)
                if now - self.last_majority_ack_time > lease_timeout:
                    self._step_down_to_follower("Leader Lease expired")
                    return

                if now - self.last_heartbeat >= self.config.heartbeat_interval:
                    self._send_append_entries()

            elif self.state == NodeState.CANDIDATE:
                if self.is_promotion_pending:
                    self._check_promotion_success()

            else:  # FOLLOWER
                if self.startup_grace_period:
                    if now - self.startup_time < self.startup_grace_duration:
                        self.last_heartbeat = now
                        return
                    else:
                        self.startup_grace_period = False
                        if self.config.debug:
                            print(f"[Node {self.id}] Startup grace period ended")

                if now - self.last_heartbeat >= self.election_timeout:
                    if self.config.enable_subleader and self.is_sub_leader:
                        self._instant_promotion()
                    else:
                        self._start_election()

    def _instant_promotion(self):
        """S-Raft 즉시 승격"""
        connected = self.transport.get_connected_count()

        if connected < 2:
            if self.config.debug:
                print(f"[Node {self.id}] Instant Promotion SKIPPED: no connections")
            self.last_heartbeat = time.time()
            self.election_timeout = self._reset_election_timer() + random.uniform(0.5, 1.0)
            return

        old_rank = self.subleader_rank
        rank_name = "Primary" if old_rank == 0 else "Secondary"

        self.state = NodeState.CANDIDATE
        self.current_term += 1
        self.voted_for = self.id
        self.is_sub_leader = False
        self.subleader_rank = None
        self.leader_id = None
        self.had_leader_before = True

        self.promotion_ack_count = 0
        self.promotion_ack_nodes = {self.id}
        self.promotion_start_time = time.time()
        self.promotion_confirmed = False
        self.is_promotion_pending = True

        self.stats['instant_promotions'] += 1

        print(f"\n{'='*60}")
        print(f"[S-RAFT INSTANT PROMOTION] Node {self.id}")
        print(f"  Role: {rank_name} Sub-leader -> Candidate")
        print(f"  Term: {self.current_term}")
        print(f"  Connected: {connected}/{self.total_nodes}")
        print(f"{'='*60}\n")

        self._send_append_entries()
        self.last_heartbeat = time.time()

    def _start_election(self):
        """기존 Raft 선거 시작"""
        if self.consecutive_election_failures >= 3:
            backoff = min(3.0, (2 ** (self.consecutive_election_failures - 2)) * 0.1)
            if self.config.debug:
                print(f"[Node {self.id}] Election backoff: {backoff*1000:.0f}ms")
            self.last_heartbeat = time.time()
            self.election_timeout = self._reset_election_timer() + backoff
            self.consecutive_election_failures += 1
            if self.consecutive_election_failures > 8:
                self.consecutive_election_failures = 0
            return

        connected = self.transport.get_connected_count()

        if connected < 2:
            self.consecutive_election_failures += 1
            if self.config.debug:
                print(f"[Node {self.id}] Pre-Vote FAILED: no connections")
            self.last_heartbeat = time.time()
            self.election_timeout = self._reset_election_timer() + random.uniform(0.5, 1.0)
            return

        self.state = NodeState.CANDIDATE
        self.current_term += 1
        self.voted_for = self.id
        self.votes_received = 1
        self.voted_nodes = {self.id}
        self.election_start_time = time.time()
        self.is_sub_leader = False
        self.subleader_rank = None

        self.stats['elections_started'] += 1

        election_type = "Initial" if not self.had_leader_before else "Fallback"
        print(f"\n{'='*60}")
        print(f"[{election_type.upper()} RAFT ELECTION] Node {self.id}")
        print(f"  Term: {self.current_term}")
        print(f"  Connected: {connected}/{self.total_nodes}")
        print(f"{'='*60}\n")

        for i in range(self.total_nodes):
            if i != self.id:
                msg = create_request_vote(
                    self.id,
                    self.current_term,
                    len(self.log),
                    self.log[-1].term if self.log else 0
                )
                self.transport.send(i, msg)

        self.last_heartbeat = time.time()
        self.election_timeout = self._reset_election_timer() + random.uniform(0, 0.1)
        self.consecutive_election_failures += 1

    def _send_append_entries(self):
        """AppendEntries 전송"""
        subleader_map = {}

        if self.config.enable_subleader:
            num_sub_leaders = int(self.total_nodes * self.config.subleader_ratio)

            if self.subleaders_assigned:
                subleader_map = self.current_sub_leaders.copy()
            elif self.response_times and len(self.response_times) >= num_sub_leaders:
                sorted_nodes = sorted(self.response_times.items(), key=lambda x: x[1])
                for rank, (node_id, rtt) in enumerate(sorted_nodes[:num_sub_leaders]):
                    subleader_map[node_id] = rank

                self.current_sub_leaders = subleader_map.copy()
                self.subleaders_assigned = True

                rank_info = []
                for nid, rank in sorted(subleader_map.items(), key=lambda x: x[1]):
                    rank_name = "Primary" if rank == 0 else "Secondary"
                    rtt_ms = self.response_times.get(nid, 0) * 1000
                    rank_info.append(f"Node {nid}={rank_name}(RTT:{rtt_ms:.1f}ms)")
                print(f"[Leader {self.id}] Sub-leaders assigned: {', '.join(rank_info)}")

        self.recent_ack_nodes = {self.id}
        current_time = time.time()

        if self.is_promotion_pending:
            data = {
                'prev_log_index': 0,
                'prev_log_term': 0,
                'entries': [],
                'leader_commit': len(self.log),
                'sub_leaders': subleader_map
            }
            for i in range(self.total_nodes):
                if i != self.id:
                    msg = create_append_entries(
                        self.id, self.current_term,
                        data['prev_log_index'], data['prev_log_term'],
                        data['entries'], data['leader_commit'],
                        data['sub_leaders']
                    )
                    self.message_sent_times[i] = current_time
                    self.transport.send(i, msg)
        else:
            for i in range(self.total_nodes):
                if i != self.id:
                    next_idx = self.next_index.get(i, len(self.log) + 1)
                    prev_log_index = next_idx - 1
                    prev_log_term = 0

                    if prev_log_index > 0 and prev_log_index <= len(self.log):
                        prev_log_term = self.log[prev_log_index - 1].term

                    if next_idx <= len(self.log):
                        entries = self.log[next_idx - 1:min(next_idx + 99, len(self.log))]
                    else:
                        entries = []

                    msg = create_append_entries(
                        self.id, self.current_term,
                        prev_log_index, prev_log_term,
                        entries, self.commit_index,
                        subleader_map
                    )
                    self.message_sent_times[i] = current_time
                    self.transport.send(i, msg)

        self.last_heartbeat = time.time()

    def _handle_message(self, msg):
        """메시지 처리"""
        with self.lock:
            if msg.term > self.current_term:
                if self.config.debug and self.state == NodeState.LEADER:
                    print(f"[Node {self.id}] Higher term found: {msg.term} > {self.current_term}")
                self.current_term = msg.term
                self._step_down_to_follower("Higher term discovered")

            if msg.type == MessageType.APPEND_ENTRIES:
                self._handle_append_entries(msg)
            elif msg.type == MessageType.APPEND_ACK:
                self._handle_append_ack(msg)
            elif msg.type == MessageType.REQUEST_VOTE:
                self._handle_request_vote(msg)
            elif msg.type == MessageType.VOTE_RESPONSE:
                self._handle_vote_response(msg)

    def _handle_append_entries(self, msg):
        """AppendEntries 처리"""
        if msg.term < self.current_term:
            ack = create_append_ack(self.id, self.current_term, False, 0)
            self.transport.send(msg.sender_id, ack)
            return

        self.last_heartbeat = time.time()
        self.consecutive_election_failures = 0
        self.startup_grace_period = False

        if self.state == NodeState.CANDIDATE and msg.term == self.current_term:
            self.state = NodeState.FOLLOWER
            self.is_promotion_pending = False
            self.promotion_confirmed = False

        self.state = NodeState.FOLLOWER
        self.current_term = msg.term
        self.leader_id = msg.sender_id

        if not self.had_leader_before:
            self.had_leader_before = True
            self.election_timeout = self._reset_election_timer()

        if self.config.enable_subleader and 'sub_leaders' in msg.data:
            self.current_sub_leaders = msg.data['sub_leaders']
            was_sub_leader = self.is_sub_leader
            self.is_sub_leader = self.id in self.current_sub_leaders

            if self.is_sub_leader:
                self.subleader_rank = self.current_sub_leaders.get(self.id)
                if not was_sub_leader:
                    rank_name = "Primary" if self.subleader_rank == 0 else "Secondary"
                    timeout_ms = self.election_timeout * 1000
                    print(f"[Node {self.id}] Designated as {rank_name} sub-leader (timeout: {timeout_ms:.0f}ms)")
                    self.stats['became_subleader_count'] += 1
                self.election_timeout = self._reset_election_timer()
            else:
                self.subleader_rank = None

        prev_log_index = msg.data.get('prev_log_index', 0)
        prev_log_term = msg.data.get('prev_log_term', 0)

        log_ok = True
        if prev_log_index > 0:
            if prev_log_index > len(self.log):
                log_ok = False
            elif self.log[prev_log_index - 1].term != prev_log_term:
                log_ok = False
                self.log = self.log[:prev_log_index - 1]

        if not log_ok:
            ack = create_append_ack(self.id, self.current_term, False, len(self.log))
            self.transport.send(msg.sender_id, ack)
            return

        entries = msg.data.get('entries', [])
        if entries:
            self.log = self.log[:prev_log_index]
            for entry in entries:
                if isinstance(entry, dict):
                    entry = LogEntry.from_dict(entry)
                self.log.append(entry)

        leader_commit = msg.data.get('leader_commit', 0)
        if leader_commit > self.commit_index:
            self.commit_index = min(leader_commit, len(self.log))
            self._apply_committed_entries()

        ack = create_append_ack(self.id, self.current_term, True, len(self.log))
        self.transport.send(msg.sender_id, ack)

    def _handle_append_ack(self, msg):
        """AppendAck 처리"""
        if self.state not in [NodeState.LEADER, NodeState.CANDIDATE]:
            return

        if msg.term > self.current_term:
            self._step_down_to_follower("Higher term in ACK")
            return

        if msg.term < self.current_term:
            return

        sender_id = msg.sender_id
        success = msg.data.get('success', False)

        if not success and self.state == NodeState.LEADER and not self.is_promotion_pending:
            if sender_id in self.next_index:
                self.next_index[sender_id] = max(1, self.next_index[sender_id] - 1)
            return

        if self.is_promotion_pending and success:
            if sender_id not in self.promotion_ack_nodes:
                self.promotion_ack_nodes.add(sender_id)
                self.promotion_ack_count += 1

                majority = (self.total_nodes // 2) + 1
                if self.config.debug:
                    print(f"[Node {self.id}] Promotion ACK from {sender_id}: "
                          f"{len(self.promotion_ack_nodes)}/{self.total_nodes} "
                          f"(need {majority})")

                if len(self.promotion_ack_nodes) >= majority and self.state == NodeState.CANDIDATE:
                    self._become_leader_from_promotion()

        if self.state == NodeState.LEADER and not self.is_promotion_pending and success:
            self.recent_ack_nodes.add(sender_id)

            match_index = msg.data.get('match_index', 0)
            if sender_id in self.match_index:
                self.match_index[sender_id] = max(self.match_index[sender_id], match_index)
                self.next_index[sender_id] = self.match_index[sender_id] + 1

            majority = (self.total_nodes // 2) + 1
            if len(self.recent_ack_nodes) >= majority:
                self.last_majority_ack_time = time.time()

        if sender_id in self.message_sent_times and success:
            rtt = time.time() - self.message_sent_times[sender_id]
            alpha = self.config.rtt_alpha

            if sender_id in self.response_times:
                self.response_times[sender_id] = alpha * rtt + (1 - alpha) * self.response_times[sender_id]
            else:
                self.response_times[sender_id] = rtt

    def _handle_request_vote(self, msg):
        """RequestVote 처리"""
        grant = False

        if msg.term > self.current_term:
            self.current_term = msg.term
            self.voted_for = None
            self.state = NodeState.FOLLOWER
            self.is_sub_leader = False
            self.subleader_rank = None

        if msg.term >= self.current_term:
            if self.state == NodeState.LEADER and msg.term == self.current_term:
                grant = False
            elif self.voted_for is None or self.voted_for == msg.sender_id:
                last_log_index = len(self.log)
                last_log_term = self.log[-1].term if self.log else 0

                candidate_last_index = msg.data.get('last_log_index', 0)
                candidate_last_term = msg.data.get('last_log_term', 0)

                if (candidate_last_term > last_log_term or
                    (candidate_last_term == last_log_term and candidate_last_index >= last_log_index)):
                    self.voted_for = msg.sender_id
                    grant = True
                    self.last_heartbeat = time.time()

        response = create_vote_response(self.id, self.current_term, grant)
        self.transport.send(msg.sender_id, response)

    def _handle_vote_response(self, msg):
        """VoteResponse 처리"""
        if self.state != NodeState.CANDIDATE:
            return

        if msg.term > self.current_term:
            self._step_down_to_follower("Higher term in vote response")
            return

        if msg.term < self.current_term:
            return

        if msg.data.get('vote_granted', False):
            if msg.sender_id in self.voted_nodes:
                return

            self.votes_received += 1
            self.voted_nodes.add(msg.sender_id)
            self.stats['votes_received_total'] += 1

            if self.config.debug:
                print(f"[Node {self.id}] Vote from {msg.sender_id}: "
                      f"{self.votes_received}/{self.total_nodes}")

            if self.votes_received > self.total_nodes / 2:
                self._become_leader_from_election()

    def _become_leader_from_promotion(self):
        """즉시 승격으로 리더가 됨"""
        elapsed = time.time() - self.promotion_start_time

        self.state = NodeState.LEADER
        self.leader_id = self.id
        self.promotion_confirmed = True
        self.is_promotion_pending = False
        self.consecutive_election_failures = 0

        self.stats['promotion_successes'] += 1
        self.stats['became_leader_count'] += 1

        self.last_majority_ack_time = time.time()
        self.recent_ack_nodes = {self.id}

        self._init_log_tracking()

        self.subleaders_assigned = False
        self.current_sub_leaders = {}
        self.leader_elected_time = time.time()

        print(f"\n{'='*60}")
        print(f"[INSTANT PROMOTION SUCCESS] Node {self.id} -> LEADER")
        print(f"  Term: {self.current_term}")
        print(f"  ACKs: {len(self.promotion_ack_nodes)}/{self.total_nodes}")
        print(f"  Time: {elapsed*1000:.1f}ms")
        print(f"{'='*60}\n")

        if self.metrics:
            self.metrics.record_election_time(elapsed, self.id, True, 'instant_promotion')

        if self.on_become_leader:
            self.on_become_leader()

        self._send_append_entries()

    def _become_leader_from_election(self):
        """투표 선거로 리더가 됨"""
        elapsed = time.time() - self.election_start_time

        self.state = NodeState.LEADER
        self.leader_id = self.id
        self.is_sub_leader = False
        self.subleader_rank = None
        self.had_leader_before = True
        self.consecutive_election_failures = 0

        self.stats['became_leader_count'] += 1

        self.last_majority_ack_time = time.time()
        self.recent_ack_nodes = {self.id}

        self._init_log_tracking()

        self.subleaders_assigned = False
        self.current_sub_leaders = {}
        self.leader_elected_time = time.time()

        print(f"\n{'='*60}")
        print(f"[ELECTION SUCCESS] Node {self.id} -> LEADER")
        print(f"  Term: {self.current_term}")
        print(f"  Votes: {self.votes_received}/{self.total_nodes}")
        print(f"  Time: {elapsed*1000:.1f}ms")
        print(f"{'='*60}\n")

        if self.metrics:
            self.metrics.record_election_time(elapsed, self.id, False, 'voting')

        if self.on_become_leader:
            self.on_become_leader()

        self._send_append_entries()

    def _init_log_tracking(self):
        """로그 복제 추적 초기화"""
        self.next_index = {}
        self.match_index = {}
        for i in range(self.total_nodes):
            if i != self.id:
                self.next_index[i] = len(self.log) + 1
                self.match_index[i] = 0

    def _check_promotion_success(self):
        """승격 성공 여부 확인"""
        elapsed = time.time() - self.promotion_start_time
        majority = (self.total_nodes // 2) + 1

        if len(self.promotion_ack_nodes) >= majority and self.state == NodeState.CANDIDATE:
            self._become_leader_from_promotion()
        elif elapsed > self.config.promotion_timeout:
            self.stats['promotion_failures'] += 1

            print(f"\n{'='*60}")
            print(f"[INSTANT PROMOTION FAILED] Node {self.id}")
            print(f"  ACKs: {len(self.promotion_ack_nodes)}/{self.total_nodes} (need {majority})")
            print(f"  Timeout: {self.config.promotion_timeout*1000:.0f}ms")
            print(f"{'='*60}\n")

            if self.metrics:
                self.metrics.record_promotion_failure(
                    self.id, self.current_term,
                    len(self.promotion_ack_nodes), majority
                )

            self._step_down_to_follower("Promotion timeout")

    def _step_down_to_follower(self, reason=""):
        """Follower로 강등"""
        if self.config.debug and self.state != NodeState.FOLLOWER:
            print(f"[Node {self.id}] Step down to Follower: {reason}")

        self.state = NodeState.FOLLOWER
        self.is_promotion_pending = False
        self.promotion_confirmed = False
        self.promotion_ack_count = 0
        self.promotion_ack_nodes.clear()
        self.voted_for = None
        self.is_sub_leader = False
        self.subleader_rank = None
        self.leader_id = None
        self.last_heartbeat = time.time()
        self.election_timeout = self._reset_election_timer()

        if self.on_become_follower:
            self.on_become_follower()

    def _apply_committed_entries(self):
        """커밋된 로그 적용"""
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            if self.last_applied <= len(self.log):
                entry = self.log[self.last_applied - 1]
                if self.on_log_committed:
                    self.on_log_committed(entry)

    # ===== 클라이언트 인터페이스 =====

    def submit_command(self, command):
        """명령 제출"""
        with self.lock:
            if self.state != NodeState.LEADER:
                return False

            entry = LogEntry(self.current_term, command, len(self.log) + 1)
            self.log.append(entry)
            return True

    def is_leader(self):
        """리더 여부 확인"""
        return self.state == NodeState.LEADER

    def get_leader_id(self):
        """현재 리더 ID 반환"""
        return self.leader_id

    def get_state(self):
        """현재 상태 반환"""
        return {
            'id': self.id,
            'state': self.state,
            'term': self.current_term,
            'leader_id': self.leader_id,
            'is_sub_leader': self.is_sub_leader,
            'subleader_rank': self.subleader_rank,
            'log_length': len(self.log),
            'commit_index': self.commit_index
        }

    def get_stats(self):
        """노드 통계 반환"""
        with self.lock:
            return {
                'id': self.id,
                'state': self.state,
                'term': self.current_term,
                'leader_id': self.leader_id,
                'is_sub_leader': self.is_sub_leader,
                'subleader_rank': self.subleader_rank,
                **self.stats
            }

    def stop(self):
        """노드 중지"""
        with self.lock:
            self.running = False
            self.state = NodeState.STOPPED
            print(f"[Node {self.id}] Stopped")
