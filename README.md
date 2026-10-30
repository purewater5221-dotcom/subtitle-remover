# 자막 지우개 (subtitle-remover)

샤오홍슈·더우인·인스타그램·틱톡 같은 짧은 영상에 박혀 있는 자막을 찾아서, 그 자리를 **배경으로 자연스럽게 메꿔 주는** 개인용 프로그램입니다. 블러나 모자이크로 가리는 게 아니라, 자막이 처음부터 없던 영상처럼 만드는 게 목표예요.

> 👉 **처음 실행한다면 [실행가이드.md](실행가이드.md)를 보세요.** 준비부터 결과 확인, 문제 해결까지 단계별로 자세히 적어 두었어요.

## 어떻게 동작하나요

1. **자막 찾기**: PP-OCRv6 텍스트 검출 모델로 프레임마다 글자 위치를 찾고, 시간 흐름에 따라 추적해요.
   - 화면에 고정된 글자(자막·제목·캡션)만 지우고, 카메라와 함께 움직이는 간판 같은 글자는 남겨요.
   - 자막이 서서히 나타나거나 사라지는 프레임까지 마스크를 조금 늘려서 잔상이 안 남게 해요.
2. **메꾸기**: 자막 주변만 잘라서 [ProPainter](https://github.com/sczhou/ProPainter)(비디오 인페인팅 AI)로 채워요.
   - 다른 프레임에서 보이는 **진짜 배경을 가져와서** 붙이고, 영상 내내 한 번도 안 보인 부분은 주변을 보고 그려요.
   - 장면이 바뀌는 곳(컷)은 따로 처리해서, 다른 장면의 배경이 섞이지 않게 해요.
3. **합치기**: 채운 부분만 원본 해상도 영상에 부드럽게 붙이고, 원래 소리를 그대로 넣어서 저장해요. 나머지 부분은 원본 그대로예요.

## 어디서 돌릴까요?

세 방법 모두 같은 프로그램과 같은 설정을 써서 결과도 같아요. 편한 쪽을 고르면 되고, 섞어 써도 돼요.

| | A. Colab 노트북 | B. 내 컴퓨터 | C. 배치파일로 Colab 자동 실행 |
|---|---|---|---|
| 필요한 것 | 구글 계정 | NVIDIA 그래픽카드 (VRAM 8GB 이상 권장) | 구글 계정, 윈도우 PC (그래픽카드 필요 없음) |
| 설치 | 없음 (처음에 토큰만 한 번 설정) | 처음 한 번 설치 (10~30분) | 처음 한 번 설정 (10분 정도) |
| 실행 | 노트북 셀을 차례로 실행 | 브라우저 화면에서 시작 | 폴더 경로만 입력하면 끝까지 자동 |
| 속도 | 무료 T4 GPU | 그래픽카드에 따라 달라요 | 무료 T4 GPU |
| 제한 | 세션 최대 약 12시간, 90분 동안 조작이 없으면 끊김, GPU를 못 받는 때도 있음 | 없음 | A와 같음 |

- 그래픽카드가 없거나 AMD·Intel 그래픽이면 **A** 또는 **C**를 쓰세요. 손이 덜 가는 건 **C**예요.
- NVIDIA 그래픽카드가 있는 컴퓨터라면 **B**가 편해요.

## A. Colab에서 쓰기

### 처음 한 번만

**1) GitHub 토큰 만들기**: Colab이 이 비공개 저장소의 코드를 받아 갈 때 필요해요.

1. GitHub에 로그인 → 오른쪽 위 프로필 사진 → **Settings**
2. 왼쪽 메뉴 맨 아래 **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
3. 다음처럼 입력해요.
   - Token name: `subtitle-remover` (목록에서 알아보기 위한 이름표예요. 이미 있는 이름이면 다른 이름으로)
   - Expiration: 원하는 기간 (만료되면 새로 만들어서 3)번처럼 다시 저장하면 돼요)
   - Repository access: **Only select repositories** → `subtitle-remover`
   - Permissions → Repository permissions → **Contents: Read-only**
4. **Generate token**을 누르고 `github_pat_`로 시작하는 토큰을 복사해요. 창을 닫으면 다시 볼 수 없어요.

**2) 노트북 열기**

- [colab.research.google.com](https://colab.research.google.com)에서 **파일 → 노트북 열기 → GitHub 탭**을 눌러요.
- **비공개 저장소 포함**에 체크하고 GitHub 접근을 허용해요.
- `purewater5221-dotcom/subtitle-remover`를 고르고 `colab/subtitle_remover.ipynb`를 열어요.
- 열린 노트북을 **파일 → Drive에 사본 저장**해 두면, 다음부터는 내 Drive에서 바로 열 수 있어요.

**3) 토큰 저장**

노트북 왼쪽의 🔑(보안 비밀) → **새 보안 비밀 추가**를 눌러요. 이름은 `GITHUB_TOKEN`(토큰 이름 `subtitle-remover`가 아니라 꼭 이대로), 값에는 복사한 토큰을 붙여 넣고, **노트북 액세스**를 켜요.

**4) GPU 켜기**

메뉴 **런타임 → 런타임 유형 변경 → T4 GPU**를 선택해요.

### 매번

1. **①**을 실행해요. Google Drive 연결 창이 뜨면 허용해요.
2. 내 Google Drive의 `subtitle-remover/input` 폴더에 영상을 넣어요. PC에서 [drive.google.com](https://drive.google.com)에 끌어다 놓으면 돼요.
3. **②**에서 설정을 고르고 **③**을 실행해요.
4. **④**로 원본과 결과를 나란히 비교해요. 결과는 `subtitle-remover/output/원래이름_clean.mp4`로 저장돼요.

## B. 내 컴퓨터에서 쓰기 (NVIDIA 그래픽카드)

### 필요한 것

- **NVIDIA 그래픽카드**: VRAM 8GB 이상을 권장해요. 6GB도 되지만, 메모리에 맞춰 처리 크기를 자동으로 줄여서 조금 덜 선명해질 수 있어요.
- Windows 10/11 64비트 (리눅스도 돼요)
- 최신 NVIDIA 드라이버, Python 3.12, 디스크 여유 공간 약 10GB

### 처음 한 번만 (Windows)

1. NVIDIA 드라이버를 최신으로 업데이트해요. NVIDIA 앱이나 [nvidia.com/drivers](https://www.nvidia.com/drivers)에서 받을 수 있어요.
2. [python.org/downloads](https://www.python.org/downloads/)에서 Python 3.12의 Windows installer (64-bit)를 받아 설치해요. 설치 첫 화면에서 **Add python.exe to PATH**에 꼭 체크하세요.
3. 코드를 받아요. GitHub에 로그인 → 이 저장소 → 초록색 **Code** 버튼 → **Download ZIP**을 누르고, `C:\subtitle-remover`처럼 짧은 경로에 압축을 풀어요.
4. 압축을 푼 폴더에서 **install_windows.bat**을 더블클릭해요.
   - 10~30분 걸려요. 인터넷으로 3~5GB를 받아요.
   - 그래픽카드 드라이버에 맞는 PyTorch를 자동으로 골라서 설치해요.
   - "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요.
5. 마지막에 **✅ 설치 완료!**가 나오면 성공이에요.

### 매번

1. **run_windows.bat**을 더블클릭하면 브라우저에 화면이 열려요 (http://127.0.0.1:7860).
2. 영상을 끌어다 놓거나 영상이 있는 폴더 경로를 입력하고, 설정을 고른 뒤 **시작**을 눌러요.
3. 결과는 `output` 폴더에 저장되고, 오른쪽에 원본과 결과를 나란히 보여 줘요. **결과 폴더 열기**를 누르면 폴더가 바로 열려요.
4. 다 쓰면 검은 창(명령 프롬프트)을 닫으면 꺼져요.

### 새 버전으로 업데이트

새 ZIP을 받아서 같은 폴더에 덮어쓰면 돼요. `.venv` 폴더를 그대로 두면 다시 설치할 필요가 없어요.

### 리눅스

```bash
./install.sh
./run.sh
```

## C. 배치파일 하나로 Colab 자동 실행

폴더 경로만 입력하면 나머지는 전부 자동이에요.

1. 영상을 Google Drive의 `subtitle-remover/input/YYYYMMDDHH` 폴더에 올려요 (실행할 때마다 새 폴더).
2. Colab에 T4 GPU 런타임을 켜고, GitHub에서 최신 코드를 받아요.
3. 자막을 지워서 Drive의 `subtitle-remover/output/YYYYMMDDHH` 폴더에 저장해요.
4. 런타임을 끄고, 결과 폴더를 열어 줘요.

구글이 2026년에 내놓은 공식 [Colab CLI](https://github.com/googlecolab/google-colab-cli)(명령어로 Colab을 쓰는 도구)를 써서, 브라우저에서 Colab을 직접 열 필요가 없어요.

### 처음 한 번만

1. [python.org/downloads](https://www.python.org/downloads/)에서 **Python 3.12**를 설치해요. 설치 첫 화면에서 **Add python.exe to PATH**에 꼭 체크하세요.
2. (권장) [Google Drive 데스크톱 앱](https://www.google.com/drive/download/)을 설치하고, Colab에 쓸 구글 계정으로 로그인해요.
   - 없어도 되지만, 있으면 영상 업로드가 빠르고 안정적이에요. 결과도 내 컴퓨터의 Drive 폴더에 바로 보여요.
   - 없으면 영상을 Colab으로 직접 올리고, 결과는 영상 폴더 안의 `subtitle-remover-output`에도 받아 와요.
3. GitHub 토큰을 준비해요. 만드는 방법은 [A의 1번](#a-colab에서-쓰기)과 같아요.
4. 코드를 받아요. GitHub 저장소에서 **Code → Download ZIP**을 누르고, `C:\subtitle-remover`처럼 짧은 경로에 압축을 풀어요.
5. **colab_setup.bat**을 더블클릭해요.
   - GitHub 토큰을 붙여 넣어요 (창에서 오른쪽 클릭 = 붙여넣기).
   - 브라우저가 열리면 구글 계정으로 로그인하고 허용해요. 화면에 나온 **인증 코드**를 복사해서 창에 붙여 넣고 Enter를 눌러요.
   - T4 시험 연결 중에 Drive 허용 주소가 열리면 허용하고, 창으로 돌아와 Enter를 눌러요.
   - **✅ 준비 완료!**가 나오면 끝이에요.

### 매번

1. **colab_run.bat**을 더블클릭하고, 영상이 있는 폴더 경로를 입력하고 Enter를 눌러요. 영상 폴더를 colab_run.bat 위로 끌어다 놓아도 돼요.
2. 진행 상황이 창에 표시돼요. **끝날 때까지 창을 닫지 마세요.** 닫으면 Colab 런타임이 한동안 켜진 채로 남아서 무료 사용량을 쓸 수 있어요.
3. 끝나면 결과 폴더가 열려요. 결과 파일 이름은 `원래이름_clean.mp4`예요.

참고할 점이에요.
- 같은 시간대(같은 YYYYMMDDHH)에 또 실행하면 `YYYYMMDDHH_2` 폴더가 새로 생겨요.
- GPU를 받지 못해 실패해도 Drive에 올라간 영상은 남아 있어서, 다음 실행 때 같이 처리돼요.
- 런타임이 켜진 채로 남은 것 같으면 **colab_stop.bat**을 실행하세요.

### 설정 바꾸기

`%APPDATA%\subtitle-remover\colab.json` 파일을 메모장으로 열어 값을 바꾸면 돼요. 파일은 colab_setup.bat이 만들어요.

| 항목 | 값 |
|---|---|
| `quality` | `빠르게`, `보통`, `최고` |
| `region` | `전체 화면`, `아래쪽 절반`, `아래쪽 1/3`, `위쪽 절반`, `위쪽 1/3`, `직접 입력` |
| `custom_region` | region이 `직접 입력`일 때 `x0,y0,x1,y1` (0~1 비율) |
| `target` | `overlay`(화면에 고정된 자막·글자만) 또는 `all`(모든 글자) |
| `gpu` | `T4`(무료, 기본) / Colab Pro 이상이면 `L4`(약 2~3배 빠름), `A100`(약 4~6배 빠름) |
| `drive_root` | Drive 앱 폴더를 못 찾을 때 직접 지정. JSON이라 역슬래시는 두 번 써요 (예: `"G:\\내 드라이브"`) |

### 알아둘 점

- **윈도우 지원**: Colab CLI는 아직 리눅스와 맥만 공식 지원해요. 코드에 윈도우 대비가 들어 있어서 동작할 가능성이 높지만, 안 되면 알려 주세요. 그때는 WSL(윈도우 안의 리눅스)로 돌리는 방법을 안내할게요.
- **무료 계정**: CLI로 무료 T4를 받을 수 있는지는 공식 문서에 분명히 나와 있지 않아요. colab_setup.bat의 시험 연결에서 바로 확인돼요.
- Colab 이용 약관이 그대로 적용돼요.

## 설정 설명 (공통)

| 설정 | 설명 |
|---|---|
| 무엇을 할까요? | **자막 지우기**, 또는 **마스크만 확인**. 마스크만 확인은 지울 부분을 표시한 미리보기만 빠르게 만들어요. |
| 품질 | 빠르게 / 보통 / 최고. 최고로 갈수록 느리지만 더 자연스러워요. |
| 어디에 있는 글자를 지울까요? | 전체 화면, 아래쪽 절반 같은 영역을 고르거나 비율 좌표로 직접 입력해요. 영역 밖의 글자는 건드리지 않아요. |
| 어떤 글자를 지울까요? | **화면에 고정된 자막·글자만**(권장), 또는 **간판 등 모든 글자** |

마스크 미리보기 색깔의 의미예요.

- 🟥 빨간 부분: 지울 곳
- 🟨 노란 테두리: 찾았지만 남긴 글자
- 🟦 파란 상자: 처리 영역
- ⬜ 흰 테두리: 장면이 바뀌는 프레임

## 잘 안 될 때

- **GPU가 없다고 나와요**
  - Colab: 메뉴 *런타임 → 런타임 유형 변경 → T4 GPU*를 고르세요. 무료 GPU를 못 받는 시간대도 있으니 잠시 뒤 다시 해 보세요.
  - 내 컴퓨터: NVIDIA 드라이버를 최신으로 업데이트한 뒤 `install_windows.bat`을 다시 실행하세요.
- **GPU 메모리가 부족하대요**: 품질을 *빠르게*로 낮추세요. 메모리가 모자라면 자동으로 잘게 나눠서 다시 시도하지만, 그래도 안 될 때가 있어요.
- **자막이 덜 지워져요**: *마스크만 확인*으로 빨간 부분이 자막을 다 덮는지 보세요.
  - 자막에 노란 테두리가 있으면 "찾았지만 남긴 글자"라는 뜻이에요. 대상을 *모든 글자*로 바꾸거나 영역을 지정하세요.
- **지우면 안 되는 글자까지 지워져요**: 영역을 *아래쪽 1/3* 등으로 좁히세요.
- **Colab 세션이 끊겼어요**: ①부터 다시 실행하세요. 이미 끝난 영상은 건너뛰어요.

## 알아둘 점

- 자막 뒤 배경이 영상 내내 한 번도 안 보이면(카메라가 고정된 경우) AI가 추측해서 그려요. 그래서 원본과 똑같지는 않고, 복잡한 무늬·얼굴·손이 지나가면 살짝 뭉개질 수 있어요.
- 카메라가 고정된 장면의 간판 글자는 자막과 구분이 안 돼서 같이 지워질 수 있어요. 이럴 땐 영역을 지정하세요.
- 틱톡·더우인 로고 같은 그림은 글자가 아니라서 지워지지 않아요. 아이디 글자는 지워질 수 있어요.
- HDR 영상(아이폰 HDR 등)은 SDR로 저장돼서 색이 조금 달라질 수 있어요.

## 처리 시간과 빠르게 하는 법

자막 자리를 프레임마다 AI로 다시 그리기 때문에 시간이 꽤 걸려요. 720p 1분(1,800프레임), 아래 자막 한 줄 기준 **예상치**예요. 실제로 재 본 값이 아니라서 2배 정도 차이 날 수 있어요.

| 설정 | Colab 무료 T4 | Colab Pro L4 |
|---|---|---|
| 보통 | 약 10~15분 | 약 5~8분 |
| 빠르게 | 약 6~9분 | 약 4~6분 |

- 각 영상이 끝날 때마다 `⏱ 찾기 ○초 · 메꾸기 ○초 · 합치기 ○초`가 표시돼요. 10초짜리로 먼저 재 보면 내 영상에서 얼마나 걸릴지 알 수 있어요.
- **빠르게**: 자막 영역을 작게 줄여서 처리하고 계산을 덜 해요. 메꾼 부분이 조금 더 부드러워(흐려)질 수 있어요.
- **여러 영상을 한 번에**: 런타임 준비(2~3분)는 실행마다 한 번만 들어요.
- **더 좋은 GPU**: Colab Pro 이상이면 L4나 A100을 쓸 수 있어요 (C 방식은 colab.json의 `gpu`, A 방식은 런타임 유형에서 선택).
- 처리 시간은 영상 길이보다 **글자 영역의 크기**에 더 좌우돼요. 위아래 모두 글자가 있으면 거의 두 배가 돼요.

## 명령어로 쓰기 (고급)

내 컴퓨터에 설치한 경우 `.venv` 안의 Python으로 실행해요 (Windows는 `.venv\Scripts\python.exe`, 리눅스는 `.venv/bin/python`).

```bash
python -m subtitle_remover 영상.mp4                    # → 영상_clean.mp4
python -m subtitle_remover 폴더/ -o 결과폴더/            # 폴더 안의 영상 전부
python -m subtitle_remover 영상.mp4 --detect-only      # 마스크 미리보기만 (영상_clean_mask.mp4)
python -m subtitle_remover 영상.mp4 --region bottom --quality best
python -m subtitle_remover 영상.mp4 --method opencv    # 빠른 테스트용 (품질 낮음)
python -m subtitle_remover --help                      # 모든 옵션
python -m subtitle_remover.app --open                  # 브라우저 화면 (run_windows.bat과 같음)
```

## 폴더 구조

```
subtitle_remover/
  video_io.py      FFmpeg로 영상 읽기/쓰기 (프레임 정확, 소리 유지)
  detect.py        텍스트 검출 (PP-OCRv6, ONNX)
  tracking.py      글자 추적, 자막/간판 구분, 프레임별 마스크 일정
  scenes.py        장면 전환(컷) 찾기
  planner.py       잘라서 처리할 영역과 구간 정하기
  masks.py         마스크 그리기, 경계 부드럽게
  device.py        GPU 확인, 메모리에 맞춰 처리 크기 조절
  inpaint/         메꾸기 엔진 (propainter, opencv)
  pipeline.py      전체 흐름 (찾기 → 메꾸기 → 합치기)
  cli.py           명령어
  app.py           내 컴퓨터용 브라우저 화면
  colab_job.py     Colab 런타임에서 Drive의 작업을 처리 (C)
colab/             Colab 노트북 (tools/build_notebook.py로 생성)
tools/             설치, Colab 자동 실행(colab_auto.py), 합성 테스트 영상, 품질 측정, 노트북 생성
tests/             자동 테스트 (pytest)
samples/           테스트용 영상을 올리는 곳
실행가이드.md       처음 실행할 때 보는 단계별 안내
install_windows.bat, run_windows.bat, install.sh, run.sh     내 컴퓨터용 (B)
colab_setup.bat, colab_run.bat, colab_stop.bat             Colab 자동 실행용 (C)
```

## 개발 메모

- 테스트: `pytest`
- 정답이 있는 합성 테스트 영상 만들기: `python tools/make_synthetic.py 출력폴더 --motion pan`
- 품질 측정: `python tools/evaluate.py 결과.mp4 정답.mp4 정답_gt.npz --subtitled 입력.mp4`
- 노트북 수정: `tools/build_notebook.py`를 고친 뒤 실행하면 `colab/subtitle_remover.ipynb`가 다시 만들어져요.

## 사용한 모델과 라이선스

- **ProPainter** (ICCV 2023): [NTU S-Lab License 1.0](https://github.com/sczhou/ProPainter/blob/main/LICENSE). **비상업적 용도로만** 쓸 수 있어요. 코드는 처음 실행할 때 원본 저장소에서 받아 와요.
- **PP-OCRv6 텍스트 검출 모델**: [RapidOCR](https://github.com/RapidAI/RapidOCR) 패키지에 들어 있는 모델(Apache-2.0)을 써요.
- 이 저장소는 개인용이에요.
