# 기술사 서머리 이미지 첨부 개발 결과

- 작업일: 2026-11-03 (한국 시간)
- 개발 브랜치: `feature/pe-summary-images`
- 기준 브랜치: `feature/pe-summary-audio-loop`
- 운영 서버 접속·배포·DB 변경 없음. 로컬 작업 트리에 변경을 남김.

## 변경 파일

- `pe_summary_files.py`: JPG/JPEG, PNG, WEBP 허용. 이미지 확장자와 선언 MIME 검사, Pillow 식별 형식 일치 검사, verify 후 재개방하여 전체 디코딩. 손상 파일, 다른 형식, 2,500만 화소 초과, 애니메이션 차단. 실패한 파일 삭제. MIME 미제공/일반 바이너리는 실제 내용 검증 후 허용. 응답 MIME은 서버 허용 목록으로 결정.
- `requirements.txt`: Pillow 12.0.0 추가. 승인된 배포 시 서비스 가상환경에 의존성 설치 및 대상 OS/Python에서 JPEG/PNG/WEBP 지원 검증 필요.
- `templates/admin_pe_summary_form.html`: 새 글/수정 공통 accept 및 안내 갱신, 기존 이미지 미리보기. 파일당 바이트 및 요청당 파일 수 설정 표시.
- `templates/pe_summary_detail.html`: 저장된 이미지의 상세 미리보기, 관리자 원본 다운로드 링크.
- `web/routes.py`: 이미지 응답 nosniff 유지, 이미지 열람 CSP 및 private/no-store 적용. 기존 공개 여부/첨부 소속 검사를 사용하고 다운로드는 관리자만 허용.
- `tests/test_pe_summary.py`: 이미지 형식별 등록·열람·수정·삭제, MIME, 권한, 제한, 위조/손상, 실패 시 정리 및 기존 글/파일 보존 테스트 추가.
- `tests/test_html_import.py`: Windows 임시 SQLite 삭제 전에 연결 풀 해제. 서머리 테스트에도 동일 적용.
- `.gitignore`: 로컬 테스트 임시 폴더 제외.

## 제한과 저장

기존 `PE_SUMMARY_MAX_FILE_BYTES`(기본 100 MiB), `PE_SUMMARY_MAX_FILES`(기본 요청당 20개)를 이미지에도 동일 적용한다. 별도 이미지 제한은 25,000,000화소이며 정지 이미지만 지원한다. 원본 바이트·SHA-256을 보존하며 UUID 파일명으로 기존 비공개 업로드 경로에 저장한다. DB 스키마 변경은 없다. 공개 글의 이미지 view는 일반 방문자가 열람 가능하고, 비공개 글은 관리자만 열람 가능하다. 다운로드 경로는 관리자 전용이다. 공개 미리보기 이미지는 브라우저로 전송되므로 복사 방지 기능은 아니다.

## 검증 결과

- Python unittest 전체: 23개 통과 (이미지 신규 검증 및 기존 PDF/문서·음원·HTML 업로드 회귀 테스트).
- Node 오디오 플레이어 테스트: 3개 통과 (반복재생, 곡 전환, 오디오 없는 화면).
- `git diff --check`: 통과.
- 정상 JPEG/JPG(대문자 확장자 포함), PNG, WEBP 등록 및 응답 MIME 확인.
- 확장자 위조, MIME 불일치, SVG 위장, 손상 이미지, 파일당 용량 초과, 파일 수 초과, 화소 제한 거부 확인.
- 공개/비공개, 타 글의 첨부 요청, 관리자 다운로드, 수정 시 추가·삭제, 실패한 수정의 롤백 확인.
- HTTP 테스트 클라이언트로 HTML과 파일 응답을 확인했다. 실제 브라우저의 파일 선택 대화상자 및 시각적 레이아웃 점검, 운영 환경 검증은 수행하지 않았다.

Windows 테스트에서는 저장소를 `ictlab` 패키지명으로 로드하고 tempfile 디렉터리를 저장소의 `.test-tmp`로 지정했다. 기본 임시 디렉터리는 실행 환경의 파일 권한 때문에 사용할 수 없었다. 테스트 DB는 운영 DB와 독립된 임시 SQLite다.
