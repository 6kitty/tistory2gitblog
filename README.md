# Tistory → GitBlog (Jekyll) Backup Tool

Tistory 블로그 글을 GitHub 기반 블로그(마크다운, Jekyll 형식)에 백업하는 툴입니다.  
두 가지 스크립트를 포함합니다:

- `tistory2git_sel.py` : Selenium을 사용해 관리자(비공개/보호 포함) 페이지에 로그인하고 글 전체 또는 선택한 글을 백업(스크린/GUI 지원).
- `tistory2git.py` : 공개 글의 RSS(피드)만을 사용해 간단히 백업(더 단순한 환경, CLI/GUI 지원).

두 스크립트는 OpenAI API를 이용해 게시글 제목 → slug 생성, HTML → Jekyll 마크다운 변환을 수행합니다.

---

## 주요 기능
- Tistory 글(공개/보호/비공개)을 Markdown(Jekyll)으로 변환
- 이미지 URL 정제 (Tistory의 fname= 링크 처리)
- AI 기반 slug/마크다운 변환 (GPT 모델 사용)
- 로컬 임시 스테이징 후 GitHub API로 업로드(backup 브랜치 생성 후 PR)
- GUI(선택) 및 CLI 지원

---

## 요구사항 (사전 준비)
- Python 3.8 이상
- Chrome 브라우저 (Selenium 사용 시)
- 환경변수 설정을 위한 `.env` 파일
- GitHub 레포지토리 (권한 있는 Personal Access Token 필요, repo 권한 포함)

필요 Python 패키지:
- selenium
- webdriver-manager
- beautifulsoup4
- python-dotenv
- PyGithub
- openai (OpenAI 공식 SDK)
- requests (tistory2git.py)
- feedparser (tistory2git.py)
- tkinter (GUI 사용 시; 일반적으로 OS 패키지로 설치)

권장 설치:
```bash
python -m pip install --upgrade pip
pip install selenium webdriver-manager beautifulsoup4 python-dotenv PyGithub openai requests feedparser
# GUI 사용하려면 (Linux): sudo apt-get install python3-tk
```

---

## .env 설정 예시

tistory2git.py 용 (RSS 방식)
```env
OPENAI_API_KEY=sk-...
TISTORY_RSS_URL=https://yourblog.tistory.com/rss
GITHUB_REPO_NAME=yourusername/yourrepo
GITHUB_TOKEN=ghp_...
```

tistory2git_sel.py 용 (Selenium 관리자 로그인 방식)
```env
OPENAI_API_KEY=sk-...
GITHUB_REPO_NAME=yourusername/yourrepo
GITHUB_TOKEN=ghp_...
TISTORY_BLOG_NAME=yourblog               # (필수) 블로그 서브도메인 이름 (yourblog.tistory.com)
TISTORY_ID=youremail@example.com         # (선택) 자동 로그인(카카오 로그인)용 아이디
TISTORY_PW=yourpassword                  # (선택) 자동 로그인용 비밀번호
```

주의:
- `TISTORY_ID`/`TISTORY_PW`는 자동 로그인을 시도할 때만 사용됩니다. 자동 로그인 실패하면 수동으로 로그인 페이지에서 로그인해야 합니다.
- OpenAI API 키는 비용이 발생할 수 있으니 주의하세요.

---

## 사용법

공통: 먼저 `.env` 파일을 프로젝트 루트에 두고 필요한 값을 입력합니다.

1) RSS 기반 (공개 글만) — tistory2git.py
- GUI가 설치되어 있고 tkinter가 사용 가능하면 GUI로 목록을 불러오고 선택 후 실행할 수 있습니다.
- CLI 예:
  ```bash
  python tistory2git.py
  ```
  실행 시 RSS에서 글 목록을 불러와 인덱스가 표시됩니다. 번호 입력 후 하나의 글을 백업합니다.

2) Selenium 기반 (관리자 로그인, 보호/비공개 포함) — tistory2git_sel.py
- Chrome이 설치되어 있어야 합니다. webdriver-manager가 자동으로 드라이버를 설치합니다.
- GUI 사용 가능 시 GUI에서 "자동 로그인 & 전체 글 스캔"을 클릭하면 관리자 페이지로 이동하여 자동 또는 수동으로 로그인 가능합니다.
- CLI 예:
  ```bash
  python tistory2git_sel.py
  ```
  실행 후 글 목록이 표시되며, 번호(콤마 구분)를 입력해 여러 글을 선택하여 일괄 백업 가능합니다.

팁:
- Selenium 스크립트는 로그인 완료(관리자 페이지로의 리다이렉트)를 최대 300초(기본)까지 대기합니다. 자동 로그인이 실패하면 수동으로 로그인하세요.
- headless 모드를 사용하려면 `tistory2git_sel.py`의 ChromeOptions에서 `--headless` 주석을 해제할 수 있습니다. (디버깅 시는 주석 처리 권장)

---

## 출력 및 GitHub 업로드 흐름
- 로컬 임시 디렉토리: `./temp_staging_area`
- 각 글은 `_posts` 디렉토리 아래에 마크다운 파일로 저장됩니다.
  - `tistory2git_sel.py` : 파일명 포맷 `{YYYY-MM-DD}-{slug}.md`
  - `tistory2git.py` : 파일명 포맷 `{yy-mm-dd}-{slug}.md` (코드상 차이 있음)
- 업로드 방식:
  - `backup` 브랜치가 없으면 `main` 브랜치에서 파생된 `backup` 브랜치를 생성합니다.
  - 파일을 모두 `backup` 브랜치에 커밋하고, `main`으로 PR을 생성합니다(열려있는 PR이 이미 있으면 새로 생성하지 않음).

---

## 주의사항 & 트러블슈팅
- 필요한 환경변수가 없으면 스크립트가 에러를 내며 실행을 중단합니다. `.env` 파일을 다시 확인하세요.
- GitHub API 권한 오류: Personal Access Token에 repo(쓰기) 권한이 있는지 확인하세요.
- OpenAI API 호출 관련: 사용 모델은 `gpt-4o-mini`로 설정되어 있습니다. 모델명/요금 정책 변경 시 `.py` 파일의 모델명을 수정하세요.
- Selenium 로그인 실패 시:
  - Tistory 로그인 UI가 변경되었을 수 있습니다. `tistory2git_sel.py`의 셀렉터를 점검해야 합니다.
  - 수동 로그인 후 관리자 페이지로 이동하면 스크립트가 계속 진행됩니다.
- Tkinter GUI가 동작하지 않으면 CLI 모드로 실행하세요.
- 이미지 URL이 `fname=` 쿼리를 포함하면 원본 파일명을 추출해 `src`에 교체합니다. 다운로드는 하지 않습니다.

---

## Todo
- 현재 jekyll config에 대해서만 넣을 수 있는데 범용성 넓히기 
- 티스토리 자동로그인 오류 수정
- 마크다운 변환 규칙을 더 많은 블로그 엔진(Jekyll 외)으로 확장
- 이미지 파일을 로컬로 다운로드하여 리포지토리에 포함하거나 Git LFS/타 호스팅을 활용
- 변환 전용 테스트 및 샘플 케이스(HTML → Markdown) 추가
- 프롬프트 분리
- log 자잘하게 분리 

---

감사합니다. 문제가 발생하면 에러 로그와 함께 이 README의 Troubleshooting 섹션 정보를 확인해주세요.
