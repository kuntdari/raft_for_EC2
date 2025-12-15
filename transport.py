# -*- coding: utf-8 -*-
"""
S-Raft TCP Transport for AWS EC2
=================================
AWS EC2 환경에 최적화된 TCP 소켓 통신 구현

특징:
- 영구 연결 유지 (Connection Pooling)
- 자동 재연결
- Keep-alive 설정
- 논블로킹 I/O
"""

import socket
import threading
import json
import struct
import time
import queue
from collections import defaultdict

from message import Message


class TCPTransport:
    """
    TCP 기반 네트워크 전송 계층

    AWS EC2 인스턴스 간 통신에 최적화됨:
    - TCP Keep-alive로 연결 유지
    - 자동 재연결 메커니즘
    - 영구 연결 풀 관리
    """

    def __init__(self, self_addr, all_addrs, config=None):
        """
        Args:
            self_addr: 자신의 주소 (예: '10.0.1.10:5000')
            all_addrs: 모든 노드 주소 리스트
            config: RaftConfig 객체 (선택)
        """
        self.self_addr = self_addr
        self.all_addrs = sorted(all_addrs)  # 정렬하여 ID 일관성 보장

        # 주소 파싱
        self.host, self.port = self._parse_address(self_addr)

        # 주소 ↔ ID 매핑
        self.addr_to_id = {addr: i for i, addr in enumerate(self.all_addrs)}
        self.id_to_addr = {i: addr for i, addr in enumerate(self.all_addrs)}
        self.self_id = self.addr_to_id[self_addr]

        # 메시지 큐 (수신용)
        self.recv_queue = queue.Queue()

        # TCP 서버
        self.server_socket = None
        self.running = True

        # 영구 연결 풀 (target_id → socket)
        self.connections = {}
        self.connections_lock = threading.Lock()

        # 연결 재시도 추적
        self.last_connect_attempt = {}
        self.connection_errors = defaultdict(int)

        # 통계
        self.stats = {
            'send_count': 0,
            'recv_count': 0,
            'send_errors': 0,
            'connect_errors': 0,
            'reconnects': 0
        }
        self.stats_lock = threading.Lock()

        # 설정
        self.connect_timeout = 2.0  # 연결 타임아웃 (2초)
        self.send_timeout = 1.0  # 전송 타임아웃 (1초)
        self.retry_interval = 1.0  # 재시도 간격 (1초)

        print(f"[TCP Node {self.self_id}] Initializing transport: {self_addr}")

        # 서버 시작
        self._start_server()

        # 다른 노드들이 서버 시작할 시간 대기
        print(f"[TCP Node {self.self_id}] Waiting for other nodes to start...")
        time.sleep(5.0)  # 5초 대기 (네트워크 안정화)

        # 모든 노드에 초기 연결 시도
        self._initial_connections()

    def _parse_address(self, addr):
        """주소 파싱: '10.0.1.10:5000' → ('10.0.1.10', 5000)"""
        parts = addr.split(':')
        return parts[0], int(parts[1])

    def _start_server(self):
        """TCP 서버 시작"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Keep-alive 설정
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            # 바인딩 (0.0.0.0으로 모든 인터페이스 수신)
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(20)
            self.server_socket.settimeout(1.0)

            print(f"[TCP Node {self.self_id}] Server listening on 0.0.0.0:{self.port}")

            # Accept 스레드 시작
            accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            accept_thread.start()

        except Exception as e:
            print(f"[TCP Node {self.self_id}] ERROR: Failed to start server: {e}")
            raise

    def _accept_loop(self):
        """클라이언트 연결 수락 루프"""
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
                client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

                # 각 연결마다 별도 스레드에서 처리
                handler = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr),
                    daemon=True
                )
                handler.start()

            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[TCP Node {self.self_id}] Accept error: {e}")

    def _handle_client(self, client_sock, addr):
        """클라이언트 연결 처리 (수신 루프)"""
        client_sock.settimeout(30.0)  # 30초 수신 타임아웃

        try:
            while self.running:
                # 메시지 길이 수신 (4 bytes)
                length_data = self._recv_exact(client_sock, 4)
                if not length_data:
                    break

                msg_length = struct.unpack('>I', length_data)[0]
                if msg_length > 10 * 1024 * 1024:  # 10MB 제한
                    print(f"[TCP Node {self.self_id}] Message too large: {msg_length}")
                    break

                # 메시지 데이터 수신
                msg_data = self._recv_exact(client_sock, msg_length)
                if not msg_data:
                    break

                # 역직렬화
                try:
                    json_data = msg_data.decode('utf-8')
                    msg_dict = json.loads(json_data)
                    msg = Message.from_dict(msg_dict)

                    # 큐에 추가
                    self.recv_queue.put(msg)
                    with self.stats_lock:
                        self.stats['recv_count'] += 1

                except Exception as e:
                    print(f"[TCP Node {self.self_id}] Deserialize error: {e}")

        except socket.timeout:
            pass  # 타임아웃, 정상
        except Exception as e:
            if self.running:
                pass  # 연결 종료
        finally:
            try:
                client_sock.close()
            except:
                pass

    def _recv_exact(self, sock, n):
        """정확히 n 바이트 수신"""
        data = b''
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                return None
            except Exception:
                return None
        return data

    def _initial_connections(self):
        """초기 연결 설정"""
        print(f"[TCP Node {self.self_id}] Establishing initial connections...")

        # 5회 시도, 각 시도 사이 1초 대기 (안정적 연결 확보)
        for attempt in range(5):
            for target_id in range(len(self.all_addrs)):
                if target_id != self.self_id:
                    self._ensure_connection(target_id)
            # 모든 연결 완료 시 조기 종료
            connected = len([k for k in self.connections.keys()])
            if connected >= len(self.all_addrs) - 1:
                break
            time.sleep(1.0)

        # 연결 상태 출력
        connected = len([k for k in self.connections.keys()])
        total = len(self.all_addrs) - 1
        print(f"[TCP Node {self.self_id}] Initial connections: {connected}/{total}")

    def _ensure_connection(self, target_id):
        """
        타겟 노드에 대한 연결 확보

        Returns:
            socket 또는 None
        """
        with self.connections_lock:
            # 기존 연결 확인
            if target_id in self.connections:
                sock = self.connections[target_id]
                try:
                    # 연결 유효성 검사
                    sock.setblocking(False)
                    try:
                        sock.recv(1, socket.MSG_PEEK)
                    except BlockingIOError:
                        pass  # 데이터 없음, 정상
                    except Exception:
                        raise Exception("Connection invalid")
                    sock.setblocking(True)
                    return sock
                except:
                    # 연결 끊어짐
                    try:
                        sock.close()
                    except:
                        pass
                    del self.connections[target_id]
                    with self.stats_lock:
                        self.stats['reconnects'] += 1

            # 재연결 간격 확인
            now = time.time()
            last_attempt = self.last_connect_attempt.get(target_id, 0)
            if now - last_attempt < self.retry_interval:
                return None

            self.last_connect_attempt[target_id] = now

            # 새 연결 생성
            target_addr = self.id_to_addr.get(target_id)
            if not target_addr:
                return None

            try:
                host, port = self._parse_address(target_addr)
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(self.connect_timeout)
                sock.connect((host, port))
                sock.settimeout(self.send_timeout)

                self.connections[target_id] = sock
                self.connection_errors[target_id] = 0

                print(f"[TCP Node {self.self_id}] Connected to Node {target_id} ({target_addr})")
                return sock

            except Exception as e:
                self.connection_errors[target_id] += 1
                with self.stats_lock:
                    self.stats['connect_errors'] += 1

                # 처음 몇 번만 에러 출력
                if self.connection_errors[target_id] <= 2:
                    print(f"[TCP Node {self.self_id}] Connection failed to Node {target_id}: {e}")

                return None

    def send(self, target_id, message):
        """
        메시지 전송

        Args:
            target_id: 대상 노드 ID
            message: Message 객체
        """
        if target_id == self.self_id:
            # 자기 자신에게 보내기
            self.recv_queue.put(message)
            return

        if target_id < 0 or target_id >= len(self.all_addrs):
            print(f"[TCP Node {self.self_id}] Invalid target_id: {target_id}")
            return

        # 재시도 로직
        for attempt in range(2):
            sock = self._ensure_connection(target_id)
            if not sock:
                continue

            try:
                # 메시지 직렬화
                json_data = json.dumps(message.to_dict()).encode('utf-8')
                length = len(json_data)
                packet = struct.pack('>I', length) + json_data

                # 전송
                sock.sendall(packet)
                with self.stats_lock:
                    self.stats['send_count'] += 1
                return  # 성공

            except Exception as e:
                # 연결 제거
                with self.connections_lock:
                    if target_id in self.connections:
                        try:
                            self.connections[target_id].close()
                        except:
                            pass
                        del self.connections[target_id]

                with self.stats_lock:
                    self.stats['send_errors'] += 1

        # 모든 시도 실패
        if self.connection_errors.get(target_id, 0) <= 3:
            pass  # 로그 스팸 방지

    def receive(self, node_id=None, timeout=0.01):
        """
        메시지 수신

        Args:
            node_id: 무시됨 (호환성용)
            timeout: 타임아웃 (초)

        Returns:
            Message 객체 또는 None
        """
        try:
            return self.recv_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_stats(self):
        """통계 반환"""
        with self.stats_lock:
            return dict(self.stats)

    def get_connected_count(self):
        """현재 연결된 노드 수 반환 (자신 포함)"""
        with self.connections_lock:
            # 활성 연결만 카운트
            active_count = 0
            for target_id, sock in list(self.connections.items()):
                try:
                    # 소켓이 유효한지 간단히 체크
                    sock.getpeername()
                    active_count += 1
                except:
                    pass
            return active_count + 1  # 자신 포함

    def stop(self):
        """전송 중지"""
        print(f"[TCP Node {self.self_id}] Stopping transport...")
        self.running = False

        # 모든 연결 닫기
        with self.connections_lock:
            for sock in self.connections.values():
                try:
                    sock.close()
                except:
                    pass
            self.connections.clear()

        # 서버 소켓 닫기
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        stats = self.get_stats()
        print(f"[TCP Node {self.self_id}] Transport stopped. Stats: {stats}")
