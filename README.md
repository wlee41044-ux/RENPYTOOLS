# RenPy Tools v0.2

두 개의 Windows GUI 도구입니다.

- `RenPyExtractor.py` → RPA/RPI 추출 + RPYC/RPYMC 디컴파일
- `RenPyAIPatcher.py` → `.rpy`에서 번역 후보를 찾아 `game/tl/<language>/` 패치 ZIP 생성

## v0.2 변경점

- 단계형 UI/UX로 전면 개편
- 게임 폴더 인식 결과를 바로 표시
- 진행률과 현재 작업 단계를 명확히 표시
- 자세한 로그는 기본 숨김
- 완료 화면에서 결과 위치 열기
- Extractor의 파일 복제 기본 ON
- Extractor의 RPYC 제거 옵션
- 빌드 BAT 오류 수정
  - Python이 없으면 즉시 중단
  - pip/PyInstaller 실패 시 즉시 중단
  - 실제 EXE 두 개가 존재할 때만 SUCCESS 표시
  - 이전 버전처럼 실패했는데 DONE이라고 표시하지 않음

## 중요: Winlator에서 BAT 실행

`BUILD_WINDOWS_EXE.cmd`는 완성된 EXE가 아니라 **EXE를 만드는 빌드 스크립트**입니다.
Winlator 안에 Windows용 Python이 설치되어 있지 않으면 빌드는 불가능합니다.
이번 버전에서는 이 경우 가짜 성공 메시지를 띄우지 않고 정확히 오류로 종료합니다.

Winlator에서는 Windows에서 빌드된 아래 두 파일만 넣어 실행하는 방식이 가장 단순합니다.

- `RenPyExtractor.exe`
- `RenPyAIPatcher.exe`

## Windows에서 EXE 만들기

1. Python 3.12+ 설치
2. `BUILD_WINDOWS_EXE.cmd` 실행
3. 성공하면 `dist/` 안에 EXE 2개 생성

## GitHub Actions로 빌드

프로젝트를 GitHub 저장소 루트에 올리면 `.github/workflows/build-windows.yml`이
Windows runner에서 두 EXE를 빌드하고 Artifact로 올리도록 구성되어 있습니다.

## 주의

Extractor는 본인이 소유하거나 분석/수정 권한이 있는 콘텐츠에 사용하세요.
AI Patcher가 생성하는 패치와 원본 게임 전체의 재배포 권리는 별개의 문제입니다.


## v0.3 배포용 설치 프로그램

최종 사용자에게는 아래 파일 하나만 배포하면 됩니다.

`RenPyTools_Setup.exe`

설치하면:
- RenPyExtractor.exe
- RenPyAIPatcher.exe
- 시작 메뉴 바로가기
- 선택 시 바탕화면 바로가기
- Windows 앱 제거 목록에서 제거 가능

GitHub Actions는 Windows에서 EXE 2개를 만든 뒤 Inno Setup으로
`RenPyTools_Setup.exe`까지 자동 생성합니다.

`BUILD_INSTALLER.cmd`는 Windows 개발/빌드 PC용입니다.
최종 사용자는 이 파일을 실행할 필요가 없습니다.
