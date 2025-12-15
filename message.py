# -*- coding: utf-8 -*-
"""
S-Raft Message Protocol
========================
노드 간 TCP 통신을 위한 메시지 정의
"""

import time
import json
import struct


class MessageType:
    """메시지 타입 상수"""
    APPEND_ENTRIES = 'AppendEntries'
    APPEND_ACK = 'AppendAck'
    REQUEST_VOTE = 'RequestVote'
    VOTE_RESPONSE = 'VoteResponse'
    CLIENT_REQUEST = 'ClientRequest'
    CLIENT_RESPONSE = 'ClientResponse'


class LogEntry:
    """로그 엔트리 클래스"""

    def __init__(self, term, command, index=0):
        self.term = term
        self.command = command
        self.index = index

    def to_dict(self):
        return {
            'term': self.term,
            'command': self.command,
            'index': self.index
        }

    @classmethod
    def from_dict(cls, d):
        return cls(d['term'], d['command'], d.get('index', 0))


class Message:
    """
    노드 간 통신 메시지

    프로토콜:
    - 4 bytes: 메시지 길이 (빅 엔디안)
    - N bytes: JSON 인코딩된 메시지 데이터
    """

    def __init__(self, msg_type, sender_id, term, data=None):
        self.type = msg_type
        self.sender_id = sender_id
        self.term = term
        self.data = data if data else {}
        self.timestamp = time.time()
        self.message_id = f"{sender_id}_{int(self.timestamp * 1000000)}"

    def to_dict(self):
        """딕셔너리로 변환"""
        return {
            'type': self.type,
            'sender_id': self.sender_id,
            'term': self.term,
            'data': self._serialize_data(self.data),
            'timestamp': self.timestamp,
            'message_id': self.message_id
        }

    def _serialize_data(self, data):
        """데이터 직렬화 (LogEntry 처리)"""
        if isinstance(data, dict):
            result = {}
            for k, v in data.items():
                if k == 'entries' and isinstance(v, list):
                    result[k] = [
                        e.to_dict() if isinstance(e, LogEntry) else e
                        for e in v
                    ]
                else:
                    result[k] = v
            return result
        return data

    @classmethod
    def from_dict(cls, d):
        """딕셔너리에서 생성"""
        msg = cls(
            d['type'],
            d['sender_id'],
            d['term'],
            cls._deserialize_data(d.get('data', {}))
        )
        msg.timestamp = d.get('timestamp', time.time())
        msg.message_id = d.get('message_id', '')
        return msg

    @classmethod
    def _deserialize_data(cls, data):
        """데이터 역직렬화 (LogEntry 처리)"""
        if isinstance(data, dict):
            result = {}
            for k, v in data.items():
                if k == 'entries' and isinstance(v, list):
                    result[k] = [
                        LogEntry.from_dict(e) if isinstance(e, dict) and 'term' in e else e
                        for e in v
                    ]
                elif k == 'sub_leaders' and isinstance(v, dict):
                    # JSON은 dict 키를 문자열로 변환하므로, int로 복원
                    result[k] = {int(node_id): rank for node_id, rank in v.items()}
                else:
                    result[k] = v
            return result
        return data

    def encode(self):
        """바이트로 인코딩"""
        json_data = json.dumps(self.to_dict()).encode('utf-8')
        length = len(json_data)
        return struct.pack('>I', length) + json_data

    @classmethod
    def decode(cls, data):
        """바이트에서 디코딩"""
        if len(data) < 4:
            return None
        length = struct.unpack('>I', data[:4])[0]
        if len(data) < 4 + length:
            return None
        json_data = data[4:4 + length].decode('utf-8')
        return cls.from_dict(json.loads(json_data))

    def __repr__(self):
        return f"Message({self.type}, from={self.sender_id}, term={self.term})"


# 메시지 생성 헬퍼 함수들
def create_append_entries(sender_id, term, prev_log_index, prev_log_term,
                          entries, leader_commit, sub_leaders=None):
    """AppendEntries 메시지 생성"""
    return Message(MessageType.APPEND_ENTRIES, sender_id, term, {
        'prev_log_index': prev_log_index,
        'prev_log_term': prev_log_term,
        'entries': entries,
        'leader_commit': leader_commit,
        'sub_leaders': sub_leaders or {}
    })


def create_append_ack(sender_id, term, success, match_index):
    """AppendAck 메시지 생성"""
    return Message(MessageType.APPEND_ACK, sender_id, term, {
        'success': success,
        'match_index': match_index
    })


def create_request_vote(sender_id, term, last_log_index, last_log_term):
    """RequestVote 메시지 생성"""
    return Message(MessageType.REQUEST_VOTE, sender_id, term, {
        'last_log_index': last_log_index,
        'last_log_term': last_log_term
    })


def create_vote_response(sender_id, term, vote_granted):
    """VoteResponse 메시지 생성"""
    return Message(MessageType.VOTE_RESPONSE, sender_id, term, {
        'vote_granted': vote_granted
    })
