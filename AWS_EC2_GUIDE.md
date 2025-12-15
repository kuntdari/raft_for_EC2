# AWS EC2 배포 상세 가이드

S-Raft를 AWS EC2에서 실행하기 위한 완벽한 가이드입니다.

## 목차

1. [사전 준비](#1-사전-준비)
2. [GitHub 레포지토리 생성](#2-github-레포지토리-생성)
3. [AWS EC2 인스턴스 생성](#3-aws-ec2-인스턴스-생성)
4. [보안 그룹 설정](#4-보안-그룹-설정)
5. [EC2에 배포하기](#5-ec2에-배포하기)
6. [S-Raft 실행](#6-s-raft-실행)
7. [실험 및 테스트](#7-실험-및-테스트)
8. [문제 해결](#8-문제-해결)

---

## 1. 사전 준비

### 필요한 것

- AWS 계정
- GitHub 계정
- SSH 클라이언트 (Windows: PuTTY 또는 WSL, Mac/Linux: Terminal)
- Git 설치

### 비용 안내

- t2.micro 인스턴스 5개: 무료 티어 (첫 12개월, 월 750시간)
- t3.small 인스턴스 5개: 약 $50-70/월 (온디맨드)
- 스팟 인스턴스 사용 시: 70-90% 절감 가능

---

## 2. GitHub 레포지토리 생성

### 2.1 GitHub에서 새 레포지토리 생성

1. [GitHub](https://github.com) 접속 및 로그인
2. 우측 상단 `+` 버튼 → `New repository`
3. 설정:
   - Repository name: `s-raft-ec2`
   - Description: `S-Raft Consensus Algorithm for AWS EC2`
   - Public 또는 Private 선택
   - ❌ "Add a README file" 체크 해제
4. `Create repository` 클릭

### 2.2 로컬에서 코드 업로드

```bash
# raft_for_EC2 폴더로 이동
cd "D:\프랑스 업데이트\python\raft_for_EC2"

# Git 초기화
git init

# 모든 파일 추가
git add .

# 첫 번째 커밋
git commit -m "Initial commit: S-Raft for AWS EC2"

# GitHub 원격 저장소 연결 (YOUR_USERNAME을 실제 사용자명으로 변경)
git remote add origin https://github.com/YOUR_USERNAME/s-raft-ec2.git

# main 브랜치로 푸시
git branch -M main
git push -u origin main
```

### 2.3 푸시 확인

GitHub 레포지토리 페이지를 새로고침하면 모든 파일이 업로드되어 있어야 합니다.

---

## 3. AWS EC2 인스턴스 생성

### 3.1 AWS 콘솔 접속

1. [AWS 콘솔](https://console.aws.amazon.com) 접속
2. 리전 선택 (예: Seoul `ap-northeast-2`)
3. EC2 서비스로 이동

### 3.2 인스턴스 시작

1. `인스턴스 시작` 버튼 클릭

2. **이름 및 태그**
   - 이름: `s-raft-node-1` (5개 각각 다르게)

3. **AMI 선택**
   - Amazon Linux 2023 AMI (권장)
   - 또는 Ubuntu Server 22.04 LTS

4. **인스턴스 유형**
   - 테스트용: `t2.micro` (무료 티어)
   - 실제 실험: `t3.small` 또는 `t3.medium`

5. **키 페어**
   - 새 키 페어 생성: `s-raft-key`
   - 유형: RSA
   - 형식: .pem (OpenSSH)
   - 다운로드 후 안전하게 보관!

6. **네트워크 설정**
   - VPC: 기본 VPC
   - 서브넷: 같은 서브넷 선택 (중요!)
   - 퍼블릭 IP 자동 할당: 활성화
   - 보안 그룹: 새로 생성 또는 기존 선택

7. **스토리지**
   - 8 GiB gp3 (기본값)

8. **고급 세부 정보**
   - 사용자 데이터 (선택사항 - 자동 설치):
   ```bash
   #!/bin/bash
   yum update -y
   yum install -y python3 git
   ```

9. **인스턴스 개수**
   - 5개 (또는 원하는 노드 수)

10. `인스턴스 시작` 클릭

### 3.3 인스턴스 이름 지정

생성된 5개 인스턴스에 각각 이름 부여:
- s-raft-node-1
- s-raft-node-2
- s-raft-node-3
- s-raft-node-4
- s-raft-node-5

---

## 4. 보안 그룹 설정

### 4.1 보안 그룹 규칙 추가

EC2 → 보안 그룹 → 해당 보안 그룹 선택 → 인바운드 규칙 편집

| 유형 | 프로토콜 | 포트 범위 | 소스 | 설명 |
|------|---------|----------|------|------|
| SSH | TCP | 22 | 내 IP | SSH 접속 |
| 사용자 지정 TCP | TCP | 5000 | 0.0.0.0/0 | S-Raft 통신 |

> **보안 권장**: 포트 5000은 VPC 내부 IP 범위로 제한 (예: 10.0.0.0/16)

### 4.2 아웃바운드 규칙

기본값 유지 (모든 트래픽 허용)

---

## 5. EC2에 배포하기

### 5.1 SSH 키 권한 설정

```bash
# Windows (Git Bash 또는 WSL)
chmod 400 s-raft-key.pem

# 또는 Windows PowerShell
icacls s-raft-key.pem /inheritance:r
icacls s-raft-key.pem /grant:r "$($env:USERNAME):(R)"
```

### 5.2 프라이빗 IP 확인

AWS 콘솔 → EC2 → 인스턴스에서 각 노드의 **프라이빗 IPv4 주소** 확인:

| 노드 | 프라이빗 IP (예시) |
|------|-------------------|
| node-1 | 10.0.1.10 |
| node-2 | 10.0.1.11 |
| node-3 | 10.0.1.12 |
| node-4 | 10.0.1.13 |
| node-5 | 10.0.1.14 |

### 5.3 PEERS 문자열 생성

```
PEERS="10.0.1.10:5000,10.0.1.11:5000,10.0.1.12:5000,10.0.1.13:5000,10.0.1.14:5000"
```

### 5.4 각 노드에 SSH 접속 및 설정

**Node 1:**
```bash
# 퍼블릭 IP로 SSH 접속
ssh -i s-raft-key.pem ec2-user@<NODE1_PUBLIC_IP>

# Python, Git 설치 확인
sudo yum install -y python3 git

# GitHub에서 클론
git clone https://github.com/YOUR_USERNAME/s-raft-ec2.git
cd s-raft-ec2
```

나머지 4개 노드도 동일하게 진행합니다.

---

## 6. S-Raft 실행

### 6.1 수동 실행 (각 터미널에서)

각 노드에서 별도 터미널을 열고 실행:

**Node 1:**
```bash
cd s-raft-ec2
python3 ec2_server.py \
    --peers "10.0.1.10:5000,10.0.1.11:5000,10.0.1.12:5000,10.0.1.13:5000,10.0.1.14:5000" \
    --debug
```

**Node 2:**
```bash
cd s-raft-ec2
python3 ec2_server.py \
    --peers "10.0.1.10:5000,10.0.1.11:5000,10.0.1.12:5000,10.0.1.13:5000,10.0.1.14:5000" \
    --debug
```

(나머지 노드도 동일)

### 6.2 백그라운드 실행

```bash
nohup python3 ec2_server.py \
    --peers "10.0.1.10:5000,10.0.1.11:5000,10.0.1.12:5000,10.0.1.13:5000,10.0.1.14:5000" \
    --debug > node.log 2>&1 &

# 로그 확인
tail -f node.log
```

### 6.3 스크립트로 일괄 배포

1. 로컬에서 `scripts/deploy_all.sh` 수정:
   - `SSH_KEY` 경로 수정
   - `NODE_IPS` 배열에 실제 프라이빗 IP 입력
   - `GITHUB_REPO` 수정

2. 배포 실행:
```bash
chmod +x scripts/*.sh
./scripts/deploy_all.sh
./scripts/start_all.sh
```

---

## 7. 실험 및 테스트

### 7.1 클러스터 상태 확인

로그에서 다음을 확인:
- `[ELECTION SUCCESS]` - 리더 선출 성공
- `[Leader X] Sub-leaders assigned` - 서브리더 지정
- `[INSTANT PROMOTION SUCCESS]` - 즉시 승격 성공

### 7.2 리더 장애 테스트

리더 노드에서:
```bash
# 리더 프로세스 종료
pkill -f ec2_server.py
```

다른 노드 로그에서 즉시 승격 확인:
```
[S-RAFT INSTANT PROMOTION] Node X
...
[INSTANT PROMOTION SUCCESS] Node X -> LEADER
  Time: 89.3ms
```

### 7.3 Original Raft와 비교

```bash
# Original Raft 모드로 실행
python3 ec2_server.py \
    --peers "..." \
    --original-raft \
    --debug
```

---

## 8. 문제 해결

### 연결 거부 (Connection refused)

```bash
# 포트 확인
netstat -tlnp | grep 5000

# 방화벽 확인
sudo iptables -L -n

# 보안 그룹 규칙 확인 (AWS 콘솔)
```

### 리더 선출 안됨

1. 모든 노드가 실행 중인지 확인
2. 피어 주소가 정확한지 확인 (프라이빗 IP 사용!)
3. 네트워크 연결 테스트:
```bash
ping 10.0.1.11
telnet 10.0.1.11 5000
```

### SSH 타임아웃

```bash
# SSH 설정에 KeepAlive 추가
ssh -i key.pem -o ServerAliveInterval=60 ec2-user@<IP>
```

### 프로세스 정리

```bash
# 모든 S-Raft 프로세스 종료
pkill -f ec2_server.py

# 포트 점유 프로세스 확인
lsof -i :5000
```

---

## 부록: 비용 최적화

### 스팟 인스턴스 사용

1. EC2 → 스팟 요청 → 스팟 인스턴스 요청
2. 최대 가격 설정 (온디맨드의 50-70%)
3. 중단 시 행동: 종료

### 실험 후 정리

```bash
# 모든 인스턴스 종료
aws ec2 terminate-instances --instance-ids i-xxx i-yyy i-zzz

# 또는 AWS 콘솔에서 수동 종료
```

---

## 다음 단계

- [ ] CloudWatch로 메트릭 모니터링
- [ ] Auto Scaling 그룹 설정
- [ ] 여러 가용 영역(AZ) 분산 배포
- [ ] Load Balancer 연동 (클라이언트 요청용)
