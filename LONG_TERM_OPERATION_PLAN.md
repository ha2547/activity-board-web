# Activity Board 장기 운영 플랜 (v3.0 기준)

이 문서는 현재 Flask 기반 Activity Board를 개인 PC 의존 없이 상시 운영(24/7)하기 위한 실행 가이드다.

## 1) 목표

- 개인 PC 전원/로그오프/재부팅과 무관하게 상시 접속
- HTTPS 기반 외부/사내 접속 안정화
- 장애 대응 가능한 운영 구조 확보
- 데이터 유실 방지 및 백업/복구 체계 확보

## 2) 권장 아키텍처

- 애플리케이션: Flask (Waitress/Gunicorn)
- 인프라: AWS EC2 (1~2대), ALB, RDS PostgreSQL
- 저장소: RDS (업무 데이터), S3 (백업/아카이브)
- DNS/인증서: Route53 + ACM
- 모니터링: CloudWatch + Uptime 체크

## 3) 현재 코드 기준 핵심 개선 포인트

현재 앱은 `activity_board_data.json` 파일을 사용한다. 장기 운영에서는 아래가 필요하다.

1. 데이터 저장소를 PostgreSQL로 전환
2. 환경변수 기반 설정 분리
3. 프로세스 매니저(systemd) 기반 상시 실행
4. Nginx 또는 ALB 뒤에서 HTTPS 종단

## 4) 단계별 구축 절차

### 4-1. 인프라 생성

1. VPC/서브넷 생성 (public/private 분리 권장)
2. EC2 생성 (Ubuntu 22.04 LTS 권장)
3. RDS PostgreSQL 생성 (Multi-AZ 권장)
4. ALB 생성 후 EC2 타깃 연결
5. 보안 그룹 설정
   - ALB: 80/443 인바운드 허용
   - EC2: ALB에서만 앱 포트 접근 허용
   - RDS: EC2에서만 5432 접근 허용

### 4-2. 서버 기본 설정

1. OS 업데이트
2. Python 3.11+ 설치
3. 앱 배포 계정/디렉터리 생성 (예: `/opt/activity-board`)
4. 가상환경 생성 및 `requirements.txt` 설치

### 4-3. 앱 실행 구조

1. 환경변수 파일 준비 (`.env` 또는 systemd Environment)
   - `ACTIVITY_BOARD_HOST=0.0.0.0`
   - `ACTIVITY_BOARD_PORT=5050`
   - `DATABASE_URL=postgresql://...`
   - `SECRET_KEY=<강한 랜덤값>`
2. systemd 유닛 생성
3. 부팅 시 자동 실행 활성화

### 4-4. 리버스 프록시/로드밸런서

1. ALB 사용 시 HTTPS(443) 리스너 + ACM 인증서 적용
2. HTTP(80)는 HTTPS 리다이렉트
3. 헬스체크 경로는 `/health`

### 4-5. 배포 자동화

1. GitHub Actions 파이프라인 구성
2. 최소 파이프라인
   - lint/test
   - 배포
   - 헬스체크
3. 실패 시 롤백 전략 준비

## 5) 데이터 마이그레이션 전략

### 5-1. 초기 전환

1. `activity_board_data.json` 백업
2. PostgreSQL 스키마 생성
3. JSON -> DB 이관 스크립트 1회 실행
4. 앱 저장소 레이어를 DB로 교체

### 5-2. 운영 중 백업

1. RDS 자동 백업 활성화 (7~35일)
2. 주간 스냅샷 수동 보관
3. 월 1회 복구 리허설

## 6) 보안 운영 기준

1. SECRET_KEY/DB 비밀번호 코드 하드코딩 금지
2. 최소 권한 IAM 적용
3. SSH 접근은 특정 IP로 제한
4. 정기 패치(월 1회)
5. 접근 로그/오류 로그 보관 정책 수립

## 7) 모니터링/알림 기준

1. Uptime 체크
   - `/health` 1분 주기
2. CloudWatch 알람
   - CPU, 메모리, 디스크
   - 5xx 에러율
   - 응답 지연 시간
3. 알림 채널
   - 이메일/Slack/Teams

## 8) 운영 체크리스트

### 배포 전

- [ ] 스테이징에서 기능/데이터 검증 완료
- [ ] DB 백업 완료
- [ ] 롤백 절차 확인

### 배포 직후

- [ ] `/health` 정상 응답 확인
- [ ] 주요 기능(등록/수정/완료) 점검
- [ ] 오류 로그 확인

### 정기 점검

- [ ] 월간 보안 패치
- [ ] 백업 복구 리허설
- [ ] 리소스 사용량 리뷰

## 9) 권장 실행 순서 (빠른 시작)

1. AWS에 EC2 1대 + RDS 생성
2. 현재 앱을 EC2에 배포 후 systemd로 상시 실행
3. ALB + HTTPS 연결
4. JSON 저장을 PostgreSQL로 전환
5. GitHub Actions 자동 배포 적용

## 10) 참고

- 앱 버전은 이번 변경부터 `3.0` 기준
- 서버 헬스체크 엔드포인트: `/health`
