# Windows 서비스 골격

Wave 0에서는 다음 프로세스를 별도 Windows 서비스로 운영하는 설치 초안을 준비한다.

- `SSWCenter-Gateway`: Caddy
- `SSWCenter-Web`: FastAPI/Uvicorn
- `SSWCenter-Worker`: 장시간 작업 worker
- PostgreSQL: PostgreSQL 설치 프로그램이 만든 서비스 사용

서비스 계정은 소스 저장소와 사용자 개인폴더에 쓰지 못하며, 프로그램 경로와 `SSWCENTER_DATA_ROOT`의 필요한 하위경로만 접근한다. 실제 서비스 등록·방화벽 변경은 설치경로와 서비스 계정이 확정된 뒤 관리자 승인 하에 수행한다.

## 운영 전 검증

- Web 서비스 환경에는 PostgreSQL 업무 DB URL, 절대 데이터 루트, PIN pepper,
  PIN lookup key, CSRF signing key와 Secure cookie 설정을 외부 환경변수로 제공한다.
- 운영 DB 이름으로 테스트·합성 seed 명령을 실행하지 않는다. 테스트 DB는
  `_test` 또는 `_review`로 끝나야 하고 테스트 파일 루트는 운영체제 임시
  디렉터리의 `sswcenter-*` 하위경로여야 한다.
- 로그는 `SSWCENTER_DATA_ROOT/logs`에 저장한다. 일반·access 로그는 30일,
  error는 90일, install/update는 180일 보관하며 일자 변경 또는 50MB에서
  압축 회전하고 전체 로그 용량은 2GB로 제한한다.
- `scripts/backup-postgres.ps1`로 백업한 뒤 `scripts/restore-drill.ps1`로
  `_review` DB 복원과 schema postcheck를 통과시킨다.
