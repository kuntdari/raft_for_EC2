# S-Raft for AWS EC2

AWS EC2에서 실행 가능한 TCP 소켓 기반 S-Raft 합의 알고리즘 구현

## 개요

S-Raft는 기존 Raft 알고리즘에 **서브리더(Sub-leader)** 개념을 추가하여 리더 장애 시 빠른 복구를 가능하게 합니다.

### 핵심 특징

1. **즉시 승격 (Instant Promotion)**
   - 리더 장애 시 서브리더가 투표 없이 즉시 리더로 승격
   - 기존 Raft: 300-600ms → S-Raft: 50-200ms

2. **RTT 기반 서브리더 선정**
   - 리더가 RTT를 측정하여 가장 빠른 노드 2개를 서브리더로 지정
   - Primary (rank 0): 리더 장애 시 첫 번째 승격 시도
   - Secondary (rank 1): Primary 실패 시 승격 시도

3. **폴백 메커니즘**
   - 모든 서브리더 승격 실패 시 기존 Raft 투표 선거로 폴백

## 파일 구조

```
raft_for_EC2/
├── config.py           # 설정 클래스
├── message.py          # 메시지 프로토콜
├── transport.py        # TCP 전송 계층
├── node.py             # Raft 노드 구현
├── metrics.py          # 메트릭 수집
├── ec2_server.py       # EC2 서버 실행 스크립트
├── requirements.txt    # 의존성 (없음)
├── README.md           # 이 파일
├── AWS_EC2_GUIDE.md    # AWS EC2 상세 배포 가이드
└── scripts/
    ├── setup_ec2.sh    # 개별 노드 설정 스크립트
    ├── start_node.sh   # 개별 노드 시작 스크립트
    ├── deploy_all.sh   # 전체 노드 배포 스크립트
    ├── start_all.sh    # 전체 노드 시작 스크립트
    ├── stop_all.sh     # 전체 노드 중지 스크립트
    └── status_all.sh   # 전체 노드 상태 확인
```

## 빠른 시작

### 1. GitHub에 업로드

```bash
# 1. GitHub에서 새 레포지토리 생성 (예: s-raft-ec2)

# 2. 로컬에서 초기화 및 푸시
cd raft_for_EC2
git init
git add .
git commit -m "Initial commit: S-Raft for AWS EC2"
git remote add origin https://github.com/YOUR_USERNAME/s-raft-ec2.git
git push -u origin main
```

### 2. AWS EC2 인스턴스 생성 (5개)

1. AWS 콘솔 → EC2 → 인스턴스 시작
2. Amazon Linux 2023 또는 Ubuntu 22.04 선택
3. 인스턴스 유형: t2.micro (무료) 또는 t3.small
4. 네트워크: 같은 VPC, 같은 서브넷
5. 보안 그룹: 포트 22, 5000 허용
6. 키 페어 생성/선택

### 3. 각 EC2에서 실행

```bash
# SSH 접속
ssh -i your-key.pem ec2-user@<EC2_PUBLIC_IP>

# Git 설치 및 클론
sudo yum install -y git python3
git clone https://github.com/YOUR_USERNAME/s-raft-ec2.git
cd s-raft-ec2

# 실행 (5개 노드 예시)
python3 ec2_server.py \
    --peers "10.0.1.10:5000,10.0.1.11:5000,10.0.1.12:5000,10.0.1.13:5000,10.0.1.14:5000" \
    --debug
```

## 상세 가이드

자세한 AWS EC2 배포 가이드는 [AWS_EC2_GUIDE.md](AWS_EC2_GUIDE.md)를 참조하세요.

## 설정

### RaftConfig 주요 설정

```python
config = RaftConfig()

# 하트비트 간격
config.heartbeat_interval = 0.05  # 50ms

# 서브리더 기능
config.enable_subleader = True
config.subleader_ratio = 0.4  # 5노드 중 2개

# 타임아웃 설정
config.primary_timeout_min = 0.15    # 150ms
config.primary_timeout_max = 0.20    # 200ms
config.secondary_timeout_min = 0.25  # 250ms
config.secondary_timeout_max = 0.35  # 350ms
config.follower_timeout_min = 0.30   # 300ms
config.follower_timeout_max = 1.00   # 1000ms
```

## 명령어 옵션

```bash
python3 ec2_server.py --help

옵션:
  --node-id       노드 ID (0부터 시작)
  --host          바인딩 호스트 (기본: 자동 감지)
  --port          포트 번호 (기본: 5000)
  --peers         피어 주소 (필수)
  --config        설정 파일 경로
  --debug         디버그 모드
  --original-raft S-Raft 비활성화 (Original Raft 사용)
  --metrics-file  메트릭 출력 파일
```

## 환경변수

스크립트 대신 환경변수로 설정 가능:

```bash
export RAFT_NODE_ID=1
export RAFT_PORT=5000
export RAFT_PEERS="10.0.1.10:5000,10.0.1.11:5000,..."
export ENABLE_SUBLEADER=true

python3 ec2_server.py --peers "$RAFT_PEERS"
```

## 문제 해결

### 연결 실패

```bash
# 포트 확인
netstat -tlnp | grep 5000

# 방화벽 확인
sudo iptables -L

# 보안 그룹 확인 (AWS 콘솔)
```

### 리더 선출 안됨

1. 모든 노드 실행 중인지 확인
2. 피어 주소 정확한지 확인
3. 네트워크 연결 확인: `ping <OTHER_NODE_IP>`

### 프로세스 종료

```bash
pkill -f ec2_server.py
```

## 라이선스

MIT License
