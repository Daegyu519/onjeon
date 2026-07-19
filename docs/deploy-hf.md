# Hugging Face Spaces 배포 (Streamlit Cloud 대체)

> **왜 옮기나**: Streamlit Community Cloud는 무료 RAM이 **1GB**라 우리 ML 스택
> (fastembed·qdrant·sklearn·matplotlib)이 계속 OOM으로 죽었다. Hugging Face
> Spaces는 무료 **16GB**라 이 문제가 근본적으로 사라진다. Streamlit을 네이티브로
> 지원해 코드·requirements.txt·packages.txt를 그대로 쓴다.

## 사용자가 하는 것 (계정·로그인은 나 대신 못 함)

### 1. HF 계정 + 토큰
1. https://huggingface.co 가입/로그인
2. Settings → **Access Tokens** → **New token** → 유형 **Write** → 생성 후 복사

### 2. Space 생성
1. https://huggingface.co/new-space
2. Owner: 본인 / Space name: **onjeon**
3. SDK: **Streamlit** 선택
4. Hardware: **CPU basic (무료)** — 16GB RAM
5. **Create Space** (빈 Space가 만들어짐)
   - ⚠️ 생성 화면에 표시되는 **Streamlit sdk_version**을 확인. README.md의
     `sdk_version: 1.44.0`과 다르면 그 값으로 바꿔야 빌드 성공 (아래 4번에서).

### 3. 코드 푸시 (프로젝트 폴더 `~/Desktop/idea`에서)
```bash
# HF CLI 설치 + 로그인 (위에서 복사한 Write 토큰 붙여넣기)
.venv/bin/pip install -q huggingface_hub
.venv/bin/huggingface-cli login

# HF Space를 git 원격으로 추가하고 푸시 (<사용자명>을 본인 것으로)
git remote add hf https://huggingface.co/spaces/<사용자명>/onjeon
git push hf main
```
푸시하면 HF가 packages.txt(fonts-nanum) + requirements.txt를 설치하고 자동 빌드한다.

### 4. (필요 시) sdk_version 수정
2번에서 본 버전과 다르면:
```bash
# README.md의 sdk_version 한 줄만 그 값으로 수정 후
git add README.md && git commit -m "chore: HF sdk_version" && git push hf main
```

### 5. 키·설정 (Space Settings → Variables and secrets)
- **Secret** `GEMINI_API_KEY` = 발급한 Gemini 키 (what-if·L0 라이브 추출용)
- **(선택) Variable** `ONJEON_EMBED_MODEL` = `intfloat/multilingual-e5-large`
  → 16GB라 여유 있으니 설정하면 RAG 검색이 풀 품질(R@5 1.0)로 동작.
  안 넣으면 경량 HashEmbedder(R@5 0.77)로 안전하게 돈다.

## 완료
Space가 빌드되면 `https://huggingface.co/spaces/<사용자명>/onjeon` 에서 앱이 뜬다.
이후 코드 수정 → `git push hf main` 하면 자동 재배포.

## 참고
- GitHub(`Daegyu519/onjeon`)와 HF Space는 **별개 원격**이다. `git push`는 GitHub,
  `git push hf main`은 HF로 간다.
- 공모전 **라이브 데모는 로컬(`./run.sh`)이 가장 안정적** — 클라우드는 심사위원이
  나중에 눌러볼 공유 URL 용도.
- `data/qdrant/`·`.env`는 `.gitignore` 처리되어 푸시되지 않는다(정상).
