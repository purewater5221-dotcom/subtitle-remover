# 자막 지우개 (subtitle-remover)

샤오홍슈·더우인·인스타그램·틱톡 같은 짧은 영상에 박힌 자막을 찾아서, 그 자리를 **배경으로 자연스럽게 메꿔 주는** 개인용 프로그램이에요. 블러나 모자이크로 가리지 않고, 처음부터 자막이 없던 영상처럼 만드는 게 목표예요.

> 👉 **처음 실행한다면 [실행가이드.md](실행가이드.md)를 보세요.** 준비부터 결과 확인, 문제 해결까지 단계별로 적어 두었어요.

## 어떻게 동작하나요

1. **찾기**: PP-OCRv6 텍스트 검출 모델로 프레임마다 글자를 찾고 시간 흐름에 따라 추적해요. 화면에 고정된 글자(자막·제목·캡션)만 지우고, 카메라와 함께 움직이는 간판은 남겨요. 자막이 서서히 나타나고 사라지는 프레임까지 덮어서 잔상이 안 남게 해요.
2. **메꾸기**: 자막 주변만 잘라서 [ProPainter](https://github.com/sczhou/ProPainter)(비디오 인페인팅 AI)로 채워요. 다른 프레임에 보이는 진짜 배경을 가져오고, 한 번도 안 보인 부분은 주변을 보고 그려요. 장면이 바뀌는 곳은 나눠서 처리해 다른 장면의 배경이 섞이지 않아요.
3. **합치기**: 채운 부분만 원본 해상도 영상에 부드럽게 붙이고 원래 소리를 넣어 저장해요. 나머지 화면은 원본 그대로예요.

## 어디서 돌릴까요?

세 방법 모두 같은 프로그램과 설정을 써서 결과도 같아요.

| | C. 배치파일 (추천) | A. Colab 노트북 | B. 내 컴퓨터 |
|---|---|---|---|
| 필요한 것 | 구글 계정, 윈도우 PC | 구글 계정 | NVIDIA 그래픽카드 (VRAM 8GB 이상 권장) |
| 처음 준비 | 설정 한 번 (10분 정도) | 토큰 저장 한 번 | 설치 한 번 (10~30분) |
| 실행 | 폴더 경로만 입력하면 끝까지 자동 | 노트북 셀을 차례로 실행 | 브라우저 화면에서 시작 |
| GPU | Colab 무료 T4 | Colab 무료 T4 | 내 그래픽카드 |
| 제한 | 세션 최대 약 12시간, 90분 동안 조작이 없으면 끊길 수 있음, GPU를 못 받는 때도 있음 | C와 같음 | 없음 |

그래픽카드가 없거나 AMD·Intel 그래픽이면 **C**(안 되면 **A**), NVIDIA 그래픽카드가 있으면 **B**가 편해요.

## C. 배치파일로 Colab 자동 실행

`colab_run.bat`을 실행하고 영상 폴더 경로를 입력하면, 영상을 Google Drive `subtitle-remover/input/YYYYMMDDHH`에 올리고, Colab T4 런타임에서 자막을 지워 `subtitle-remover/output/YYYYMMDDHH`에 저장한 뒤 런타임을 끄고 결과 폴더를 열어 줘요. 구글의 공식 [Colab CLI](https://github.com/googlecolab/google-colab-cli)를 써서 브라우저에서 Colab을 열 필요가 없어요.

- **처음 한 번**: Python 3.12 설치, GitHub 토큰 만들기, `colab_setup.bat` 실행 ([실행가이드 2](실행가이드.md#2-방법-c-배치파일로-자동-실행-추천))
- **설정**: `%APPDATA%\subtitle-remover\colab.json`에서 품질·영역·GPU 등을 바꿔요 ([실행가이드 2-5](실행가이드.md#2-5-설정-바꾸기)).
- **권장**: [Google Drive 데스크톱 앱](https://www.google.com/drive/download/)이 있으면 업로드가 빠르고 결과도 탐색기에 바로 보여요.
- **윈도우 지원**: Colab CLI는 아직 리눅스·맥만 공식 지원해요. 윈도우 대비 코드가 들어 있지만, 안 되면 알려 주세요.

## A. Colab 노트북

[colab.research.google.com](https://colab.research.google.com)에서 GitHub의 `colab/subtitle_remover.ipynb`를 열고, 🔑 보안 비밀에 `GITHUB_TOKEN`을 저장한 뒤 셀 ①~④를 차례로 실행해요. 영상은 Drive `subtitle-remover/input`에 넣고, 결과는 `subtitle-remover/output`에 저장돼요. 자세한 순서는 [실행가이드 3](실행가이드.md#3-방법-a-colab-노트북)을 보세요.

## B. 내 컴퓨터에서 쓰기 (NVIDIA 그래픽카드)

**필요한 것**: NVIDIA 그래픽카드(VRAM 8GB 이상 권장. 6GB도 되지만 처리 크기를 줄여서 조금 덜 선명해요), Windows 10/11 64비트 또는 리눅스, 최신 NVIDIA 드라이버, Python 3.12, 디스크 여유 약 10GB

**처음 한 번 (Windows)**
1. NVIDIA 드라이버를 최신으로 업데이트해요 ([nvidia.com/drivers](https://www.nvidia.com/drivers)).
2. Python 3.12를 설치해요. 설치 첫 화면에서 **Add python.exe to PATH**에 꼭 체크하세요.
3. 이 저장소에서 **Code → Download ZIP**을 받아 `C:\subtitle-remover`처럼 짧은 경로에 풀어요.
4. **install_windows.bat**을 실행해요. 그래픽카드 드라이버에 맞는 PyTorch를 골라 설치하고, 3~5GB를 받느라 10~30분 걸려요. 마지막에 `✅ 설치 완료!`가 나오면 성공이에요.

**매번**
1. **run_windows.bat**을 실행하면 브라우저에 화면이 열려요 (http://127.0.0.1:7860).
2. 영상을 끌어다 놓거나 폴더 경로를 입력하고, 설정을 고른 뒤 **시작**을 눌러요.
3. 결과는 `output`, 처리 기록은 `output\logs`에 저장되고, 오른쪽에 원본과 결과가 나란히 나와요.
4. 다 쓰면 검은 창을 닫아요.

**리눅스**: `./install.sh` 후 `./run.sh`

**업데이트**: 새 ZIP을 같은 폴더에 덮어써요. `.venv` 폴더를 그대로 두면 다시 설치할 필요는 없어요. 필요한 경우는 [실행가이드 8](실행가이드.md#8-업데이트와-최근-바뀐-점)에 적어 둘게요.

## 설정

| 설정 | 설명 |
|---|---|
| 무엇을 할까요? | **자막 지우기**, 또는 지울 부분만 표시한 미리보기를 빠르게 만드는 **마스크만 확인** |
| 품질 | 빠르게 / 보통 / 최고. 최고로 갈수록 느리지만 더 자연스러워요. |
| 어디에 있는 글자를 지울까요? | 전체 화면, 아래쪽 절반 같은 영역 또는 비율 좌표. 영역 밖의 글자는 건드리지 않아요. |
| 어떤 글자를 지울까요? | **화면에 고정된 자막·글자만**(권장) 또는 **간판 등 모든 글자** |

마스크 미리보기 색깔: 🟥 지울 곳 · 🟨 찾았지만 남긴 글자 · 🟦 처리 영역 · ⬜ 장면이 바뀌는 프레임

## 처리 시간

720p 1분(1,800프레임), 아래 자막 한 줄 기준 **예상치**예요. 실제로 재 본 값이 아니라 2배 정도 차이 날 수 있어요.

| 품질 | Colab 무료 T4 | Colab Pro L4 |
|---|---|---|
| 보통 | 약 10~15분 | 약 5~8분 |
| 빠르게 | 약 6~9분 | 약 4~6분 |

- 끝나면 영상별로 `⏱ 걸린 시간`이 정리돼요 ([읽는 법](실행가이드.md#5-1-걸린-시간-읽는-법)). 10초짜리로 먼저 재 보면 내 영상의 시간을 짐작할 수 있어요.
- 시간은 영상 길이보다 **글자 영역의 크기**에 더 좌우돼요. 위아래 모두 글자가 있으면 거의 두 배예요.
- **빠르게**는 자막 영역을 작게 줄여 처리해서, 메꾼 부분이 조금 흐려질 수 있어요.
- 런타임 준비(2~3분)는 실행마다 한 번이라, 여러 영상을 한 번에 돌리는 게 유리해요.
- Colab Pro 이상이면 L4·A100을 쓸 수 있어요 (C는 `colab.json`의 `gpu`, A는 런타임 유형).

## 한계

- 자막 뒤 배경이 영상 내내 안 보이면 AI가 추측해서 그려요. 복잡한 무늬·얼굴·손이 지나가면 살짝 뭉개질 수 있어요.
- 카메라가 고정된 장면의 간판 글자는 자막과 구분이 안 돼 같이 지워질 수 있어요. 이럴 땐 영역을 지정하세요.
- 틱톡·더우인 로고 같은 그림은 지워지지 않아요. 아이디 글자는 지워질 수 있어요.
- HDR 영상(아이폰 HDR 등)은 SDR로 저장돼서 색이 조금 달라질 수 있어요.

잘 안 될 때는 [실행가이드 7. 문제가 생기면](실행가이드.md#7-문제가-생기면)을 보세요.

## 명령어로 쓰기 (고급)

내 컴퓨터에 설치한 경우 `.venv` 안의 Python으로 실행해요 (Windows `.venv\Scripts\python.exe`, 리눅스 `.venv/bin/python`).

```bash
python -m subtitle_remover 영상.mp4                    # → 영상_clean.mp4
python -m subtitle_remover 폴더/ -o 결과폴더/            # 폴더 안의 영상 전부
python -m subtitle_remover 영상.mp4 --detect-only      # 마스크 미리보기만
python -m subtitle_remover 영상.mp4 --region bottom --quality best
python -m subtitle_remover 영상.mp4 --method opencv    # 빠른 테스트용 (품질 낮음)
python -m subtitle_remover --help                      # 모든 옵션
python -m subtitle_remover.app --open                  # 브라우저 화면 (run_windows.bat과 같음)
```

## 폴더 구조

```
subtitle_remover/
  video_io.py      FFmpeg로 영상 읽기/쓰기 (프레임 정확, 소리 유지)
  detect.py        텍스트 검출 (PP-OCRv6)
  tracking.py      글자 추적, 자막/간판 구분, 프레임별 마스크 일정
  scenes.py        장면 전환(컷) 찾기
  planner.py       잘라서 처리할 영역과 구간 정하기
  masks.py         마스크 그리기, 경계 부드럽게
  device.py        GPU 확인, 메모리에 맞춰 처리 크기 조절
  inpaint/         메꾸기 엔진 (propainter, opencv)
  pipeline.py      전체 흐름 (찾기 → 메꾸기 → 합치기)
  logs.py          처리 기록 파일, 걸린 시간 정리
  cli.py           명령어
  app.py           내 컴퓨터용 브라우저 화면 (B)
  colab_job.py     Colab 런타임에서 Drive의 작업 처리 (C)
colab/             Colab 노트북 (tools/build_notebook.py로 생성)
tools/             설치, Colab 자동 실행(colab_auto.py), 합성 테스트 영상, 품질 측정
tests/             자동 테스트 (pytest)
samples/           테스트용 영상을 올리는 곳
install_windows.bat, run_windows.bat, install.sh, run.sh     내 컴퓨터용 (B)
colab_setup.bat, colab_run.bat, colab_stop.bat             Colab 자동 실행용 (C)
```

## 개발 메모

- 테스트: `pytest`
- 정답이 있는 합성 테스트 영상: `python tools/make_synthetic.py 출력폴더 --motion pan`
- 품질 측정: `python tools/evaluate.py 결과.mp4 정답.mp4 정답_gt.npz --subtitled 입력.mp4`
- 노트북 수정: `tools/build_notebook.py`를 고친 뒤 실행하면 `colab/subtitle_remover.ipynb`가 다시 만들어져요.

## 사용한 모델과 라이선스

- **ProPainter** (ICCV 2023): [NTU S-Lab License 1.0](https://github.com/sczhou/ProPainter/blob/main/LICENSE), **비상업적 용도로만** 쓸 수 있어요. 코드는 처음 실행할 때 원본 저장소에서 받아 와요.
- **PP-OCRv6 텍스트 검출 모델**: [RapidOCR](https://github.com/RapidAI/RapidOCR) 패키지에 들어 있는 모델(Apache-2.0)을 써요.
- 이 저장소는 개인용이에요.
