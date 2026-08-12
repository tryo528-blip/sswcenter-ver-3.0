# SSWCenter v3.0-alpha

## 업무 시작 전 필수 절차

모든 작업자는 업무를 시작하기 전에 다음 순서를 지킨다.

1. 루트 [`00-먼저읽기-작업환경안내.md`](00-먼저읽기-작업환경안내.md)를 처음부터 끝까지 먼저 읽고, 실제 드라이브·작업 루트·러너·키 배치를 확인한다.
2. 브랜치·상태를 먼저 확인한다. 원격 비교가 필요하면 fetch한다.
   `git pull --ff-only`는 사용자가 지정한 통합 체크아웃이 tracking 브랜치에
   있고 clean 상태일 때만 사용한다. 분리된 리뷰 worktree, 격리된 리뷰 작업,
   dirty worktree에서는 pull하지 않고 기존 작업을 보존·보고한다.
3. 이 `README.md`를 읽는다.
4. Windows PC별 최초 1회 UTF-8 설정을 확인한다.
5. 활성 작업 패킷의 확정 역할-모델 배정과 기준 SHA를 확인한다.
6. 패킷이 지정한 정본의 최하위 절·anchor와 matrix ID만 읽는다.
7. 소유권이나 범위가 불명확할 때만 [정본 문서 목록](docs/00_정본_문서_목록.md)을 확인한다.

로컬 변경사항이나 Git 충돌이 있으면 임의로 폐기·덮어쓰기·병합하지 말고 먼저 사용자에게 보고한다.

## Windows UTF-8 최초 설정

이 저장소의 Markdown·Python·설정 파일은 UTF-8을 기준으로 한다. 집과 사무실 등 각 Windows 사용자 계정에서 저장소를 처음 사용할 때 다음 명령을 한 번 실행한다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\setup-windows-utf8.ps1
```

실행 후 Codex와 터미널을 다시 시작한다. 이후 Python은 별도의 `-X utf8` 옵션 없이 UTF-8을 기본값으로 사용한다. 레거시 CP949 파일만 코드에서 `encoding="cp949"`를 명시하여 읽는다.

## 운영 비밀값

`.env.example` 파일의 모든 값은 의도적으로 유효하지 않은 자리표시자(placeholder)이며,
운영 환경에서 그대로 사용하면 시작이 거부된다(fail-closed). 실제 비밀값은 저장소 외부에서
운영자가 독립적으로 생성해야 한다.

- 모든 애플리케이션 비밀값(PIN pepper, PIN lookup, CSRF signing, transition token)은
  서로 다른 고유한 값이어야 하며, 원시 문자열 기준 최소 32자 이상이어야 한다.
- `SSWCENTER_RESIDENT_NUMBER_KEY_V1`과 `SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY`는
  각각 독립적인 32바이트 난수를 표준 RFC 4648 base64로 인코딩한 값(44자)이어야 하며,
  디코딩된 바이트열이 서로 달라야 한다.
- 운영 환경 데이터베이스 비밀번호는 높은 다양성(high-diversity)을 갖추고 최소 16자
  이상이어야 하며, 어떤 애플리케이션 비밀값과도 재사용해서는 안 된다.
- 애플리케이션은 명백히 취약한 값(자리표시자, 낮은 문자 다양성, 반복 단위, 오름차순·
  내림차순 등)을 거부하지만, 생성 출처(provenance)까지 증명할 수는 없으므로 운영자는
  반드시 CSPRNG 기반 도구로 생성해야 한다.

안전한 생성 예시(개념 설명용 — 실제 값이 아님):

```powershell
# Windows PowerShell 5.1: 32바이트 난수 → base64 (주민번호 키)
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $bytes = [byte[]]::new(32)
    $rng.GetBytes($bytes)
    [Convert]::ToBase64String($bytes)
} finally {
    $rng.Dispose()
}
```

```bash
# Linux / WSL: 32 random bytes / 64 hex characters
openssl rand -hex 32
```

```bash
# Linux / WSL: 32바이트 난수 → base64 (주민번호 키)
openssl rand -base64 32
```

```bash
# Linux / WSL: 16자 이상 고엔트로피 DB 비밀번호
tr -dc 'A-Za-z0-9!@#$%^&*()_+-=' < /dev/urandom | head -c 20; echo
```

## AI 운영·업무분담 정본

AI 역할, Writer 선정, 업무분담과 독립검수의 유일한 정본은
[`C:\sswcenter\3.0\00-오케스트레이션-작업지침.md`](00-오케스트레이션-작업지침.md)다.
형님의 최신 명시 지시가 최우선이며, 활성 작업 패킷은 해당 작업의
범위·SHA·쓰기 경로만 소유하고 AI 운영 정본을 덮어쓰지 않는다.
